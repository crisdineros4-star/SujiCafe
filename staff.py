"""Staff workspace: limited order and workshop operations; no admin account management."""
from flask import session, Blueprint, render_template, request, redirect, url_for, flash, jsonify
from core import *
import commerce, ops, order_qr, workshop_payments

bp = Blueprint('staff', __name__, url_prefix='/staff')
staff_only = login_required('staff')

@bp.route('/', methods=['GET', 'POST'])
@staff_only
def dashboard():
    if request.method == 'POST':
        action = request.form.get('action')
        oid = to_int(request.form.get('id'))
        status = request.form.get('status')
        if action in ('order_status','assign_rider'):
            try:
                if action=='order_status':ops.transition_order(oid,status)
                elif action=='assign_rider':ops.assign_rider(oid,to_int(request.form.get('rider_id')))
                db().commit();flash('Operation recorded.','success')
            except ValueError as exc:db().rollback();flash(str(exc),'danger')
        elif action == 'complete_dinein':
            try:
                ops.actor('order_fulfill')
                if oid <= 0:
                    raise ValueError('Choose a valid dine-in order.')
                order = ops.lock_order(oid)
                if not order or order['order_type'] != 'dinein' or order['status'] != 'ready' or order['voided_at']:
                    raise ValueError('Only a Ready to Serve dine-in order can be marked Completed.')
                if order['payment_method'] == 'gcash' and order['payment_status'] != 'paid':
                    raise ValueError('Verify the actual GCash payment first.')
                if order['payment_status'] != 'paid' and order['total'] > 0 and request.form.get('cash_received') != 'yes':
                    raise ValueError('Confirm that the full cash payment was received before marking Completed.')
                if not complete_order(db(), oid):
                    raise ValueError('This order cannot be completed until payment is verified.')
                ops.audit('order.completed', 'order', oid, {'via': 'staff orders tab'})
                db().commit()
                flash('Dine-in order #' + str(oid) + ' marked Completed.', 'success')
            except ValueError as exc:
                db().rollback()
                flash(str(exc), 'danger')
        elif action == 'instore':
            ops.actor('counter_sale')
            key=request.form.get('member','').strip()
            member=None
            if re.match(r'^SUJI-?\d+$',key,re.I):member=q("SELECT * FROM users WHERE id=? AND role='customer'",(int(re.sub(r'\D','',key)),),one=True)
            elif '@' in key:member=user_by_email(key)
            elif key.isdigit():member=q("SELECT * FROM users WHERE phone=? AND role='customer'",(key,),one=True)
            try:
                if key and (not member or member['role']!='customer'):raise ValueError('Member not found.')
                quantities={}
                for k,v in request.form.items():
                    if k.startswith('qty_') and v and v!='0':
                        if not v.isdigit() or not 1<=int(v)<=20:raise ValueError('Quantity must be 1–20.')
                        quantities[k[4:]]=int(v)
                rows=[]
                if quantities:rows=q("SELECT * FROM products WHERE is_available=1 AND id IN ("+','.join('?'*len(quantities))+")",tuple(quantities))
                quote=commerce.OrderQuote(rows,quantities,'instore',to_int(request.form.get('reward_id')))
                pay=request.form.get('payment','cash')
                if pay not in ('cash','gcash'):raise ValueError('Choose cash or GCash.')
                if pay=='gcash' and not re.fullmatch(r'\d{13}',request.form.get('reference','').strip()):raise ValueError('Enter the 13-digit GCash reference.')
                if pay=='gcash' and q('SELECT id FROM orders WHERE gcash_reference=?',(request.form.get('reference','').strip(),),one=True):raise ValueError('That payment reference is already recorded.')
                if pay=='gcash' and request.form.get('wallet_checked')!='yes':raise ValueError('Verify the received transfer in the actual GCash wallet first.')
                token=request.form.get('checkout_key','')
                if not token or token!=session.get('instore_key'):raise ValueError('Refresh this page before recording the purchase.')
                if not member:
                    if quote.points_used:raise ValueError('Select a member account to redeem an item.')
                    member=user_by_email('walkin@suji.invalid')
                    if not member:
                        run("INSERT INTO users(first_name,last_name,email,phone,birthdate,address,password_hash,role) VALUES ('Walk-in','Customer','walkin@suji.invalid','','','',?,'walkin')",(generate_password_hash(secrets.token_urlsafe(40)),))
                        member=user_by_email('walkin@suji.invalid')
                    quote.disable_earnings()
                d=db();oid=quote.insert(member['id'],pay,'In-store purchase','instore',checkout_key=token,paid=True)
                
                if pay=='gcash':d.execute('UPDATE orders SET gcash_reference=?,verified_by=?,paid_at=? WHERE id=?',(request.form.get('reference','').strip(),current_user()['id'],ops.now(),oid))
                complete_order(d,oid);ops.audit('sale.counter','order',oid,{'payment_method':pay,'total':str(quote.total),'member':member['role']=='customer'})
                if pay=='gcash':ops.audit('payment.approved','order',oid,{'via':'counter wallet check'})
                d.commit();session.pop('instore_key',None)
                return redirect(url_for('payments.staff_receipt',order_id=oid))
            except ValueError as exc:db().rollback();flash(str(exc),'danger')
            except Exception:db().rollback();flash('Purchase could not be recorded. Check recent receipts before retrying.','danger')
        elif action == 'booking' and status in ('confirmed', 'cancelled'):
            from services import BookingService
            try:
                BookingService(db(),mysql_enabled()).update(oid,status);db().commit()
                flash('Reservation updated.','success')
            except ValueError as exc:db().rollback();flash(str(exc),'danger')
        return redirect(url_for('staff.dashboard',tab='workshop' if action=='booking' else 'counter' if action=='instore' else 'orders'))
    orders = q("""SELECT o.*,
                  CONCAT(u.first_name,' ',u.last_name) AS customer
                  FROM orders o JOIN users u ON u.id=o.user_id
                  WHERE o.status IN ('pending','preparing','ready') ORDER BY o.id DESC LIMIT 100""")
    completed_dinein = q("""SELECT o.id,o.total,o.created_at, CONCAT(u.first_name,' ',u.last_name) AS customer
                            FROM orders o JOIN users u ON u.id=o.user_id
                            WHERE o.order_type='dinein' AND o.status='delivered' AND o.voided_at IS NULL
                            ORDER BY o.id DESC LIMIT 10""")
    bookings = q("""SELECT b.*,p.amount AS payment_amount,p.status AS payment_status,p.method AS payment_method, CONCAT(u.first_name,' ',u.last_name) AS customer
                    FROM diy_bookings b JOIN users u ON u.id=b.user_id LEFT JOIN workshop_payments p ON p.booking_id=b.id
                    ORDER BY b.event_date DESC LIMIT 100""")
    session.setdefault('instore_key',secrets.token_hex(24))
    return render_template('staff/dashboard.html', workshop_unit_price=workshop_payments.price(), orders=orders, completed_dinein=completed_dinein, bookings=bookings, products=q("SELECT * FROM products WHERE is_available=1 AND category<>'diy_cake' ORDER BY category,name"), checkout_key=session['instore_key'], recent=q("SELECT id,total,created_at FROM orders WHERE order_type='instore' ORDER BY id DESC LIMIT 15"),riders=q("SELECT id,first_name,last_name FROM users WHERE role='rider' AND NOT EXISTS (SELECT 1 FROM employee_invitations i WHERE i.user_id=users.id AND i.status<>'active') AND NOT EXISTS (SELECT 1 FROM account_access a WHERE a.user_id=users.id AND a.disabled_at IS NOT NULL) ORDER BY first_name"))

@bp.post('/workshop/<int:booking_id>/payment')
@staff_only
def workshop_payment(booking_id):
    try:workshop_payments.collect(booking_id,request.form);flash('Workshop payment recorded.','success')
    except ValueError as exc:db().rollback();flash(str(exc),'danger')
    except Exception:db().rollback();flash('Payment was not recorded. Check the booking and GCash reference before trying again.','danger')
    return redirect(url_for('staff.dashboard',tab='workshop'))

@bp.post('/scan')
@staff_only
def scan():
    try:
        code=request.form.get('code','').strip()
        if re.fullmatch(r'SUJI-\d{1,18}',code,re.I):return jsonify(ok=True,member=order_qr.member_lookup(code))
        o=order_qr.lookup(code)
        return jsonify(ok=True,order=order_qr.details(o))
    except ValueError as exc:return jsonify(ok=False,msg=str(exc)),400

@bp.post('/scan/<action>')
@staff_only
def scan_action(action):
    ops.actor('order_fulfill')
    try:
        if request.form.get('confirmed')!='yes':raise ValueError('Review and confirm the order action first.')
        o=order_qr.lookup(request.form.get('code',''),lock=True)
        details=order_qr.details(o)
        if action=='accept':
            if not details['can_accept']:raise ValueError('This order can no longer be accepted. Scan again to check its status.')
            ops.transition_order(o['id'],'preparing')
        elif action=='ready':
            if not details['can_ready']:raise ValueError('Only a Preparing order can be marked Ready. Scan again to check its status.')
            ops.transition_order(o['id'],'ready')
        elif action=='complete':
            if not details['can_complete']:raise ValueError('Only a Ready dine-in or collection order can be completed. Scan again to check its status.')
            if o['payment_status']!='paid' and o['total']>0 and request.form.get('cash_received')!='yes':raise ValueError('Confirm the full cash payment was received before serving this order.')
            if not complete_order(db(),o['id']):raise ValueError('Payment verification is required before completion.')
            ops.audit('order.completed','order',o['id'],{'via':'staff scanned order','points_used':o['points_used']})
        else:raise ValueError('Unknown order action.')
        db().commit();o=q('SELECT * FROM orders WHERE id=?',(o['id'],),one=True)
        return jsonify(ok=True,order=order_qr.details(o))
    except ValueError as exc:db().rollback();return jsonify(ok=False,msg=str(exc)),400

@bp.get('/live')
@staff_only
def live():
    rows=q("""SELECT o.id,o.order_type,o.payment_method,o.payment_status,o.status,o.total,o.rider_id,o.created_at,
              CONCAT(u.first_name,' ',u.last_name) customer,CONCAT(r.first_name,' ',r.last_name) rider
              FROM orders o JOIN users u ON u.id=o.user_id LEFT JOIN users r ON r.id=o.rider_id
              WHERE o.status IN ('pending','preparing','ready') ORDER BY o.id DESC LIMIT 100""")
    orders=[dict(dict(row),created_at=__import__('time_utils').transaction_time(row['created_at']),status_label=status_label(row['order_type'],row['status'])) for row in rows]
    completed_dinein=[dict(row) for row in q("""SELECT o.id,o.total,o.created_at,CONCAT(u.first_name,' ',u.last_name) AS customer FROM orders o JOIN users u ON u.id=o.user_id WHERE o.order_type='dinein' AND o.status='delivered' AND o.voided_at IS NULL ORDER BY o.id DESC LIMIT 10""")]
    riders=[dict(row) for row in q("SELECT id,first_name,last_name FROM users WHERE role='rider' AND NOT EXISTS (SELECT 1 FROM employee_invitations i WHERE i.user_id=users.id AND i.status<>'active') AND NOT EXISTS (SELECT 1 FROM account_access a WHERE a.user_id=users.id AND a.disabled_at IS NOT NULL) ORDER BY first_name")]
    return jsonify(orders=orders,riders=riders,completed_dinein=completed_dinein)
