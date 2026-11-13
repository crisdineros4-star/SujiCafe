"""Real GCash transfers: merchant QR, submitted reference, explicit wallet verification."""
from flask import Blueprint,request,render_template,redirect,url_for,flash,send_from_directory,abort,jsonify
from core import *
import commerce, ops
bp=Blueprint('payments',__name__)

def staff_user():
    return ops.actor('payment_review')

def confirm_received(oid,reference,note='',accept=False):
    """Record a staff-checked wallet transfer; optionally accept the order atomically."""
    u=staff_user();o=ops.lock_order(oid)
    if not o or o['payment_method']!='gcash' or o['status']=='cancelled' or o['voided_at'] or o['payment_status'] not in ('unpaid','submitted'):
        raise ValueError('This GCash order cannot accept another payment confirmation. Refresh its status.')
    ref=(reference or o['gcash_reference'] or '').strip()
    if not re.fullmatch(r'\d{13}',ref):raise ValueError('Enter the 13-digit reference from the actual received GCash transfer.')
    if q('SELECT id FROM orders WHERE gcash_reference=? AND id<>?',(ref,oid),one=True):raise ValueError('This reference is already recorded for another order.')
    db().execute("UPDATE orders SET gcash_reference=?,payment_status='paid',payment_note=?,verified_by=?,paid_at=? WHERE id=?",(ref,(note or '').strip()[:255],u['id'],ops.now(),oid))
    ops.audit('payment.approved','order',oid,{'reference':ref,'amount':str(o['total']),'source':'staff checked received transfer','accept_order':accept})
    if accept and o['status']=='pending':ops.transition_order(oid,'preparing')

def confirm_cash_received(oid, amount, note, cash_received, wallet_checked):
    """Settle an existing GCash order with cash physically received at the cafe."""
    user=staff_user();order=ops.lock_order(oid)
    if not order or order['payment_method']!='gcash' or order['payment_status'] not in ('unpaid','rejected') or order['status'] not in ('pending','preparing','ready') or order['voided_at']:
        raise ValueError('Only active unpaid or rejected GCash orders can be settled with cash. Refresh the order.')
    if q('SELECT order_id FROM rider_advances WHERE order_id=?',(oid,),one=True):
        raise ValueError('This order has a rider advance. Resolve its cash record first.')
    if cash_received!='yes' or wallet_checked!='yes':
        raise ValueError('Confirm cash received at the cafe and verify no GCash transfer was received for this order.')
    reason=(note or '').strip()
    if not 5<=len(reason)<=255:raise ValueError('Enter an explanation of 5–255 characters.')
    total=commerce.money(order['total'])
    if total<=0 or commerce.money(amount)!=total:raise ValueError('Cash applied must match the full order total. Return any change first.')
    previous={'method':order['payment_method'],'status':order['payment_status'],'reference':order['gcash_reference'],'note':order['payment_note']}
    stamp=ops.now()
    db().execute("UPDATE orders SET payment_method='cash',payment_status='paid',payment_note=?,verified_by=?,paid_at=?,updated_at=? WHERE id=?",(reason,user['id'],stamp,stamp,oid))
    ops.audit('payment.cash_received','order',oid,{'previous':previous,'amount':str(total),'reason':reason,'received_at':'cafe','wallet_checked':True})
    ops.audit('payment.approved','order',oid,{'method':'cash','amount':str(total),'source':'cash received at cafe'})
    if order['status']=='pending':ops.transition_order(oid,'preparing')

@bp.route('/customer/orders/<int:order_id>/payment',methods=['GET','POST'])
@login_required('customer')
def payment(order_id):
    u=current_user();o=q('SELECT * FROM orders WHERE id=? AND user_id=?',(order_id,u['id']),one=True)
    if not o:abort(404)
    if o['payment_method']!='gcash':return redirect(url_for('customer.orders'))
    if request.method=='POST':
        proof=None
        try:
            if o['status']=='cancelled' or o['payment_status'] in ('paid','refund_required'):raise ValueError('This order cannot accept a new payment submission.')
            if not commerce.gcash_ready():raise ValueError('Contact the cafe: its GCash QR is not configured.')
            ref=request.form.get('reference','').strip()
            if not re.fullmatch(r'\d{13}',ref):raise ValueError('Enter the 13-digit reference number from your GCash transaction receipt.')
            existing=q('SELECT id FROM orders WHERE gcash_reference=? AND id<>?',(ref,order_id),one=True)
            if existing:raise ValueError('That reference is already attached to another order. Contact the cafe if you entered it incorrectly.')
            proof=commerce.save_verified_image(request.files.get('proof'),private=True)
            d=db();d.execute("UPDATE orders SET gcash_reference=?,payment_proof=COALESCE(?,payment_proof),payment_status='submitted',payment_note='',submitted_at=?,updated_at=? WHERE id=? AND status<>'cancelled' AND payment_status NOT IN ('paid','refund_required')",(ref,proof,ops.now(),ops.now(),order_id));ops.audit('payment.submitted','order',order_id,{'method':'gcash'});d.commit()
            flash('Payment details submitted. Staff will check the actual GCash transaction. Your order is not marked Paid yet.','success')
            return redirect(url_for('payments.payment',order_id=order_id))
        except ValueError as exc:db().rollback();flash(str(exc),'danger')
        except Exception:db().rollback();flash('Could not save payment details. Refresh and check before retrying.','danger')
    o=q('SELECT * FROM orders WHERE id=?',(order_id,),one=True)
    return render_template('customer/payment.html',order=o)

@bp.get('/payments/<int:order_id>/proof')
def proof(order_id):
    u=current_user();o=q('SELECT user_id,payment_proof FROM orders WHERE id=?',(order_id,),one=True)
    if not u or not o or (u['role'] not in ('staff','admin','owner') and u['id']!=o['user_id']):abort(404)
    if not o['payment_proof']:abort(404)
    response=send_from_directory(str(commerce.BASE/'private/payments'),o['payment_proof'])
    response.headers['Cache-Control']='private, no-store';return response

@bp.route('/staff/payments',methods=['GET','POST'])
def review():
    u=staff_user()
    if request.method=='POST':
        oid=to_int(request.form.get('id'));o=ops.lock_order(oid)
        verdict=request.form.get('verdict');note=request.form.get('note','').strip()[:255]
        if verdict=='cash_received':
            try:
                confirm_cash_received(oid,request.form.get('cash_amount',''),request.form.get('cash_note',''),request.form.get('cash_received'),request.form.get('no_gcash_received'))
                db().commit();flash('Cash recorded on the same order. Payment receipt is now available.','success')
            except ValueError as exc:db().rollback();flash(str(exc),'danger')
            except Exception:db().rollback();flash('Could not record cash. Refresh the order before retrying.','danger')
        elif verdict in ('paid','paid_accept'):
            try:
                if request.form.get('wallet_checked')!='yes':raise ValueError('Check the actual store GCash wallet: recipient, amount and reference must match.')
                confirm_received(oid,request.form.get('reference',''),note,accept=verdict=='paid_accept');db().commit()
                flash('GCash payment received and order accepted.' if verdict=='paid_accept' else 'GCash payment confirmed.','success')
            except ValueError as exc:db().rollback();flash(str(exc),'danger')
            except Exception:db().rollback();flash('Could not record the payment. Refresh the order and check its status before retrying.','danger')
        elif not o or o['payment_method']!='gcash' or o['payment_status']!='submitted' or o['status']=='cancelled':flash('Only active submitted payments can be rejected.','danger')
        elif verdict=='rejected':
            d=db();changed=d.execute("UPDATE orders SET payment_status=?,payment_note=?,verified_by=?,paid_at=? WHERE id=? AND payment_status='submitted' AND status<>'cancelled'",(verdict,note,u['id'],ops.now() if verdict=='paid' else None,oid))
            if changed.rowcount:ops.audit('payment.approved' if verdict=='paid' else 'payment.rejected','order',oid,{'reference':o['gcash_reference'],'amount':str(o['total']),'note':note})
            d.commit()
            flash('Payment review saved.','success')
        return redirect(url_for('payments.review'))
    selected=to_int(request.args.get('order'))
    rows=q("SELECT o.*,CONCAT(u.first_name,' ',u.last_name) customer FROM orders o JOIN users u ON u.id=o.user_id WHERE (payment_method='gcash' OR EXISTS (SELECT 1 FROM audit_log a WHERE a.entity_type='order' AND a.entity_id=o.id AND a.event='payment.cash_received'))"+(' AND o.id=?' if selected else '')+" ORDER BY o.id DESC LIMIT 100",(selected,) if selected else ())
    return render_template('staff/payments.html',payments=rows)

@bp.post('/staff/payments/receive')
def receive():
    staff_user()
    try:
        if request.form.get('wallet_checked')!='yes' or request.form.get('confirmed')!='yes':raise ValueError('Check the received funds in the store wallet and confirm this action first.')
        oid=to_int(request.form.get('id'))
        confirm_received(oid,request.form.get('reference',''),request.form.get('note',''),accept=True);db().commit()
        import order_qr
        return jsonify(ok=True,order=order_qr.details(q('SELECT * FROM orders WHERE id=?',(oid,),one=True)))
    except ValueError as exc:db().rollback();return jsonify(ok=False,msg=str(exc)),400
    except Exception:db().rollback();return jsonify(ok=False,msg='Payment could not be saved. Refresh and check the order before retrying.'),409

@bp.route('/admin/commerce',methods=['GET','POST'])
@bp.route('/owner/commerce',methods=['GET','POST'])
@login_required('owner')
def settings():
    ops.actor('manage_store')
    if request.method=='POST':
        ops.actor('manage_store')
        try:
            before={}
            if request.form.get('action')=='landing':
                image=commerce.save_verified_image(request.files.get('landing_image'))
                if not image:raise ValueError('Choose a café interior JPG, PNG or WebP file, up to 2 MB.')
                commerce.set_setting('landing_image',image)
            elif request.form.get('action')=='rewards':
                before={'earn_per_peso':commerce.setting('earn_per_peso','100'),'points':{str(p['id']):p['points_cost'] for p in q('SELECT id,points_cost FROM products')}}
                spend=commerce.money(request.form.get('earn_per_peso','100'))
                if not 1<=spend<=1000:raise ValueError('Earning rate must be ₱1–₱1,000 per point.')
                commerce.set_setting('earn_per_peso',str(spend))
                for p in q('SELECT id,category FROM products'):
                    raw=request.form.get('points_'+str(p['id']))
                    if raw is None:continue
                    if p['category'] not in commerce.REWARD_CATEGORIES:
                        db().execute('UPDATE products SET points_cost=0 WHERE id=?',(p['id'],));continue
                    if not raw.isdigit() or not 1<=int(raw)<=100000:raise ValueError('Food and drink reward costs must be whole numbers from 1–100,000.')
                    db().execute('UPDATE products SET points_cost=? WHERE id=?',(int(raw),p['id']))
            else:
                account=request.form.get('account','').strip()
                if len(account)>150:raise ValueError('Account label is too long.')
                image=commerce.save_verified_image(request.files.get('qr'))
                number=request.form.get('number',commerce.setting('gcash_number')).strip()
                if number and not re.fullmatch(r'09\d{9}',number):raise ValueError('Enter the actual 11-digit GCash receiving number starting with 09.')
                commerce.set_setting('gcash_account',account)
                commerce.set_setting('gcash_number',number)
                if image:commerce.set_setting('gcash_qr',image)
            after={'earn_per_peso':commerce.setting('earn_per_peso','100'),'points':{str(p['id']):p['points_cost'] for p in q('SELECT id,points_cost FROM products')}} if request.form.get('action')=='rewards' else {}
            ops.audit('settings.'+request.form.get('action','gcash'),'store',None,{'before':before,'after':after})
            db().commit();flash('Settings saved.','success')
        except ValueError as exc:db().rollback();flash(str(exc),'danger')
        return redirect(url_for('payments.settings'))
    return render_template('admin/commerce.html',products=q('SELECT * FROM products WHERE is_available=1 ORDER BY category,name'))

@bp.get('/staff/receipts/<int:order_id>')
def staff_receipt(order_id):
    staff_user();o,items=commerce.receipt_data(order_id)
    if not o:abort(404)
    if not commerce.receipt_ready(o):
        flash('Payment receipt is available after payment confirmation.','info')
        return redirect(url_for('payments.review',order=order_id))
    return render_template('customer/receipt.html',order=o,items=items)
