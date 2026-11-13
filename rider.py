"""Rider area: only Admin-assigned deliveries are visible."""
from flask import Blueprint, render_template, request, jsonify
from core import *
import ops, commerce

def advance_for(oid):
    return q('SELECT * FROM rider_advances WHERE order_id=?', (oid,), one=True)


bp = Blueprint('rider', __name__, url_prefix='/rider')
rider_only = login_required('rider')

JOBS_SQL = """SELECT o.*, CONCAT(c.first_name,' ',c.last_name) cust, c.phone,
              COALESCE(group_concat(CONCAT(oi.qty,'x ',COALESCE(oi.item_name,p.name)), ', '), '') items
              FROM orders o JOIN users c ON c.id=o.user_id
              LEFT JOIN order_items oi ON oi.order_id=o.id LEFT JOIN products p ON p.id=oi.product_id
              WHERE {where} GROUP BY o.id ORDER BY o.id {order} LIMIT 30"""

def job(r):
    try:
        lat,lng=float(r['lat']),float(r['lng'])
        maps=f'https://www.google.com/maps/dir/?api=1&destination={lat},{lng}' if math.isfinite(lat) and math.isfinite(lng) and -90<=lat<=90 and -180<=lng<=180 else ''
    except (ValueError,TypeError):maps=''
    return dict(id=r['id'], cust=r['cust'], phone=r['phone'], address=r['delivery_address'], items=r['items'],
                total=f"₱{r['total']:,.2f}", collect=(f"₱{r['total']:,.2f}" if r['payment_status']!='paid' else '₱0.00'), paid=r['payment_status']=='paid', pay='GCash' if r['payment_method'] == 'gcash' else 'Cash', maps=maps,
                when=__import__('time_utils').transaction_time(r['created_at']), status=r['status'],
                advance_status=(advance_for(r['id']) or {}).get('status', ''),
                advance_required=r['payment_method'] in ('cod','cash') and r['payment_status']!='paid')

@bp.route('/')
@rider_only
def dashboard():
    amount=sum(r['cash_collected_cents'] for r in ops.cash_outstanding(current_user()['id']))
    return render_template('rider/dashboard.html',cash_to_hand_over=amount/100,cash_history=ops.handover_history(15,current_user()['id']))

@bp.get('/live')
@rider_only
def live():
    me = current_user()['id']
    amount=sum(r['cash_collected_cents'] for r in ops.cash_outstanding(me))
    return jsonify(available=[],cash_cents=amount,cash_to_hand_over=f'₱{amount/100:,.2f}',
        mine=[job(r) for r in q(JOBS_SQL.format(where="o.rider_id=? AND o.order_type='delivery' AND o.status IN ('ready','picked_up','out_for_delivery')", order='ASC'), (me,))],
        done=[job(r) for r in q(JOBS_SQL.format(where="o.rider_id=? AND o.order_type='delivery' AND o.status='delivered'", order='DESC'), (me,))])

@bp.post('/pickup')
@rider_only
def pickup():
    ops.actor('rider_pickup')
    d = db(); oid = to_int(request.form.get('id'))
    row=ops.lock_order(oid)
    if not row or not Order.from_row(row).can_pick_up(current_user()['id']):return jsonify(ok=False,msg='This assigned order is not ready for pickup or payment is unverified.')
    if row['payment_method'] in ('cod','cash') and row['payment_status']!='paid':
        if request.form.get('advance_paid')!='yes':
            return jsonify(ok=False,msg='Confirm you paid the store for this order before pickup.')
        cents=int(commerce.money(row['total'])*100)
        if not advance_for(oid):
            d.execute('INSERT INTO rider_advances(order_id,rider_id,amount_cents,advanced_at,status) VALUES (?,?,?,?,?)',
                      (oid,current_user()['id'],cents,ops.now(),'advanced'))
    cur = d.execute("UPDATE orders SET status='picked_up',updated_at=?,pickup_time=? WHERE id=? AND rider_id=? AND order_type='delivery' AND status='ready' AND (payment_method<>'gcash' OR payment_status='paid')", (ops.now(),ops.now(),oid, current_user()['id']))
    if cur.rowcount:ops.audit('rider.pickup','order',oid)
    d.commit()
    return jsonify(ok=cur.rowcount > 0, msg=f'Order #{oid} marked as picked up.' if cur.rowcount else 'This assigned order is not ready for pickup.')

@bp.post('/deliver')
@rider_only
def deliver():
    ops.actor('rider_deliver')
    d = db(); oid = to_int(request.form.get('id'))
    ops.lock_rider(current_user()['id']);o=ops.lock_order(oid)
    if not o or not Order.from_row(o).can_deliver(current_user()['id']): return jsonify(ok=False, msg='Pick up this assigned order before marking it delivered.')
    advance=advance_for(oid)
    if o['payment_method'] in ('cod','cash') and o['payment_status']!='paid' and (not advance or advance['status']!='advanced'):
        return jsonify(ok=False,msg='Rider advance must be recorded before COD delivery.')
    collected=int(commerce.money(o['total'])*100) if o['payment_method'] in ('cod','cash') and o['payment_status']!='paid' else 0
    if collected and request.form.get('cash_received')!='yes':return jsonify(ok=False,msg='Confirm cash was collected before completing this COD delivery.')
    
    if not complete_order(d, oid):return jsonify(ok=False,msg='GCash payment must be verified first.')
    if collected and advance:
        d.execute("UPDATE rider_advances SET status='recovered',resolved_at=? WHERE order_id=? AND status='advanced'",(ops.now(),oid))
    elif collected:
        d.execute('UPDATE orders SET cash_collected_cents=? WHERE id=?',(collected,oid))
    ops.audit('rider.delivered','order',oid,{'cash_collected_cents':collected})
    d.commit()
    return jsonify(ok=True, msg=f'Order #{oid} delivered. Delivery orders do not earn points.')

@bp.post('/failed')
@rider_only
def failed_delivery():
    d=db();oid=to_int(request.form.get('id'))
    reason=(request.form.get('reason') or '').strip()
    if not 10<=len(reason)<=500:
        return jsonify(ok=False,msg='Describe the failed delivery (10–500 characters).')
    ops.lock_rider(current_user()['id']);order=ops.lock_order(oid)
    if not order or order['rider_id']!=current_user()['id'] or order['status'] not in ('picked_up','out_for_delivery'):
        return jsonify(ok=False,msg='Only your active picked-up order can be reported.')
    advance=advance_for(oid)
    if not advance or advance['status']!='advanced':
        return jsonify(ok=False,msg='No active rider advance found for this order.')
    d.execute("UPDATE rider_advances SET status='failed_pending',failed_reason=?,failed_at=? WHERE order_id=? AND status='advanced'",(reason,ops.now(),oid))
    ops.audit('rider.delivery_failed','order',oid,{'reason':reason,'advance_cents':advance['amount_cents']})
    d.commit()
    return jsonify(ok=True,msg='Failed delivery reported. Admin must review the rider advance; no refund is automatic.')

@bp.post('/location')
@rider_only
def share_location():
    import delivery_tracking
    result,status=delivery_tracking.save(current_user()['id'],request.form)
    if status==200:db().commit()
    else:db().rollback()
    response=jsonify(result);response.status_code=status
    response.headers['Cache-Control']='private, no-store'
    if status==429:response.headers['Retry-After']='3'
    return response

@bp.post('/location/stop')
@rider_only
def stop_location():
    import delivery_tracking
    delivery_tracking.stop(current_user()['id'],request.form.get('sharing_token'));db().commit()
    response=jsonify(ok=True);response.headers['Cache-Control']='private, no-store';return response

@bp.post('/location/start')
@rider_only
def start_location():
    import delivery_tracking
    try:
        token=delivery_tracking.start(current_user()['id']);db().commit()
        response=jsonify(ok=True,sharing_token=token)
    except ValueError as exc:
        db().rollback();response=jsonify(ok=False,msg=str(exc));response.status_code=409
    response.headers['Cache-Control']='private, no-store';return response
