"""Admin area: /admin  (orders, QR scan, store sales, workshop bookings, products, riders)."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from core import *
import json
import commerce, ops, workshop_payments
import email_validation
import employee_invitations
import account_management

bp = Blueprint('admin', __name__, url_prefix='/admin')
admin_only = login_required('admin')

def admin_orders():
    return q("""SELECT o.*, CONCAT(u.first_name,' ',u.last_name) cust, u.phone, CONCAT(r.first_name,' ',r.last_name) rider_name
                FROM orders o JOIN users u ON u.id=o.user_id LEFT JOIN users r ON r.id=o.rider_id ORDER BY o.id DESC LIMIT 60""")

def order_dict(r):   # one order, ready to send to the page as JSON
    t = r['order_type']
    opts = [[s,status_label(t,s)] for s in ops.allowed_statuses(r,'admin')]
    return dict(id=r['id'], cust=r['cust'], phone=r['phone'], type=t, type_icon=TYPE_INFO[t][0], type_label=TYPE_INFO[t][1],
                created_at=__import__('time_utils').transaction_time(r['created_at']),total=f"₱{r['total']:,.2f}", where=r['delivery_address'], lat=r['lat'], lng=r['lng'],
                status=r['status'], status_label=status_label(t,r['status']), opts=opts, payment_method=r['payment_method'],payment_status=r['payment_status'],voided=bool(r['voided_at']), rider=r['rider_name'] or '', rider_id=r['rider_id'])

def stats():
    return q("""SELECT (SELECT COUNT(*) FROM users WHERE role='customer') users,
                (SELECT COALESCE(SUM(total),0) FROM orders WHERE status='delivered') sales,
                (SELECT COUNT(*) FROM orders WHERE status='pending') pending""", one=True)

def sig_of(rows):
    return hashlib.sha256(json.dumps([dict(r) for r in rows],sort_keys=True,default=str).encode()).hexdigest()[:16]

@bp.route('/', methods=['GET', 'POST'])
@admin_only
def dashboard():
    if request.method == 'POST':
        a = request.form.get('action'); i = to_int(request.form.get('id')); s = request.form.get('status'); d = db()
        tab = 'orders'
        try:
            if a == 'order_status':
                ops.transition_order(i,s,request.form.get('reason',''));flash('Order status updated.','success')
            elif a == 'assign_rider':
                ops.assign_rider(i,to_int(request.form.get('rider_id')));flash('Rider assigned.','success')
            elif a == 'void_sale':
                ops.void_sale(i,request.form.get('reason'));tab='sales';flash('Sale voided. Record the actual refund separately if required.','success')
            elif a == 'record_refund':
                if request.form.get('funds_returned')!='yes':raise ValueError('Confirm the funds were actually returned first.')
                ops.record_refund(i,request.form.get('method'),request.form.get('reference'),request.form.get('reason'));tab='sales';flash('Actual refund recorded.','success')
            elif a == 'workshop_payment':
                # Staff, Admin and Owner can record funds they have actually verified.
                # collect() enforces the workshop permission, total, booking status,
                # GCash reference uniqueness and duplicate-payment protection.
                tab='workshop';workshop_payments.collect(i,request.form)
                flash('Verified workshop payment recorded.','success')
            elif a == 'workshop_refund':
                tab='workshop';workshop_payments.refund(i,request.form);flash('Workshop refund recorded.','success')
            elif a == 'booking' and s in ('confirmed','cancelled'):
                ops.actor('workshop_update');tab='workshop'
                from services import BookingService
                BookingService(d,mysql_enabled()).update(i,s)
            elif a in ('edit_employee','disable_employee','enable_employee'):
                target=account_management.target(i)
                tab='admins' if target['role']=='admin' else 'staff' if target['role']=='staff' else 'riders'
                if a=='edit_employee':account_management.edit(i,request.form);flash('Account details saved. An email correction on a pending invitation sends a new link.','success')
                else:account_management.set_enabled(i,a=='enable_employee',request.form.get('reason',''));flash('Account access updated. Re-enabled pending accounts still need an invitation.','success')
            elif a in ('resend_invitation' ,'cancel_invitation'):
                invited = q("SELECT id,role FROM users WHERE id=? AND role IN ('staff','rider','admin')", (i,), one=True)
                if not invited:raise ValueError('Choose a Staff or Rider invitation.')
                tab = 'admins' if invited['role']=='admin' else 'staff' if invited['role']=='staff' else 'riders'
                if a=='resend_invitation':
                    employee_invitations.resend(i);flash('A new invitation was sent. The previous link no longer works.','success')
                else:
                    employee_invitations.cancel(i);flash('Invitation cancelled. This pending account cannot sign in.','info')
            elif a in ('new_staff','new_rider','new_admin'):
                ops.actor('create_admin' if a=='new_admin' else 'manage_accounts');role={'new_staff':'staff','new_rider':'rider','new_admin':'admin'}[a];tab='admins' if role=='admin' else 'staff' if role=='staff' else 'riders'
                f={k:request.form.get(k,'').strip() for k in ('first_name','last_name','email','phone')};f['email']=f['email'].lower();pw=request.form.get('password','')
                if len(f['email'])>254 or not EMAIL.fullmatch(f['email']):raise ValueError('Enter a valid email address.')
                from registration_policy import validate_name_policy,validate_email_policy
                try:validate_email_policy(f['email'])
                except ValueError as exc:
                    raise ValueError(str(exc)+' (Email domain entered: '+f['email'].rpartition('@')[2]+'.)') from exc
                if f['email'] in {config.OWNER_EMAIL,config.ADMIN_EMAIL}- {''}:raise ValueError('This email is reserved for owner setup.')
                email_validation.validate_email_domain(f['email'])
                import accounts
                if user_by_email(f['email']):raise ValueError('This email is already registered.')
                employee_invitations.invite(f,role)
                flash(role.title()+' invitation sent. This account remains Pending activation until the email is verified and a private password is set.','success')
            elif a in ('new_product','edit_product','toggle','product_image','delete_product'):
                ops.actor('manage_menu');tab='products';old=q('SELECT * FROM products WHERE id=?',(i,),one=True)
                if a in ('new_product','edit_product'):
                    price=commerce.money(request.form.get('price'));name=request.form.get('name','').strip();category=request.form.get('category','');description=request.form.get('description','').strip()
                    if not Product(name,category,price,description).is_valid():raise ValueError('Provide a valid product name, category and price.')
                    cost=commerce.default_points_cost(price,category)
                    if a=='new_product':
                        i=d.execute('INSERT INTO products(name,category,description,price,image,points_cost) VALUES (?,?,?,?,?,?)',(name,category,description,str(price),commerce.save_verified_image(request.files.get('image')),cost)).lastrowid
                    else:
                        if not old:raise ValueError('Product not found.')
                        d.execute('UPDATE products SET name=?,category=?,description=?,price=?,points_cost=? WHERE id=?',(name,category,description,str(price),cost,i))
                    ops.audit('product.created' if a=='new_product' else 'product.edited','product',i,{'name':name,'old_price':str(old['price']) if old else None,'new_price':str(price),'category':category,'points_cost':cost})
                elif not old:raise ValueError('Product not found.')
                elif a=='toggle':
                    d.execute('UPDATE products SET is_available=1-is_available WHERE id=?',(i,));ops.audit('product.availability','product',i,{'from':old['is_available'],'to':1-old['is_available']})
                elif a=='product_image':
                    image=commerce.save_verified_image(request.files.get('image'))
                    if not image:raise ValueError('Choose a product image.')
                    d.execute('UPDATE products SET image=? WHERE id=?',(image,i));ops.audit('product.image','product',i)
                elif a=='delete_product':
                    used=q('SELECT COUNT(*) n FROM order_items WHERE product_id=?',(i,),one=True)['n']
                    if used:d.execute('UPDATE products SET is_available=0 WHERE id=?',(i,))
                    else:d.execute('DELETE FROM products WHERE id=?',(i,))
                    ops.audit('product.archived' if used else 'product.deleted','product',i,{'name':old['name']})
                flash('Product saved.','success')
            else:raise ValueError('Unknown admin action.')
        except ValueError as exc:
            d.rollback();flash(str(exc),'danger')
            if a in ('new_rider','new_staff','new_admin'):
                session['account_form']={'action':a,'error':str(exc)[:600],**{key:request.form.get(key,'').strip()[:limit] for key,limit in [('first_name',100),('last_name',100),('email',254),('phone',30)]}}
        else:
            if a in ('new_rider','new_staff','new_admin'):session.pop('account_form',None)
        d.commit(); return redirect(url_for(('owner' if current_user()['role']=='owner' else 'admin')+'.dashboard', tab=tab))
    account_form=session.pop('account_form',{})
    rows = admin_orders()
    return render_template('owner/dashboard.html' if current_user()['role']=='owner' else 'admin/dashboard.html', workshop_unit_price=workshop_payments.price(), account_form=account_form, admins=q("SELECT * FROM users WHERE role='admin' ORDER BY first_name") if current_user()['role']=='owner' else [], stats=stats(), orders=[order_dict(r) for r in rows], sig=sig_of(rows),
        books=[dict(r) for r in q("SELECT b.*, p.amount AS payment_amount,p.status AS payment_status,p.method AS payment_method, CONCAT(u.first_name,' ',u.last_name) cust, u.phone FROM diy_bookings b JOIN users u ON u.id=b.user_id LEFT JOIN workshop_payments p ON p.booking_id=b.id ORDER BY b.event_date DESC LIMIT 50")],
        prods=q('SELECT * FROM products ORDER BY category,name'), cats=CATEGORIES,
        staff=q("SELECT * FROM users WHERE role='staff' ORDER BY first_name"),
        riders=q("""SELECT u.*, (SELECT COUNT(*) FROM orders WHERE rider_id=u.id AND status='delivered') done,
                    (SELECT COUNT(*) FROM orders WHERE rider_id=u.id AND status IN ('ready','picked_up')) active
                    FROM users u WHERE u.role='rider' ORDER BY u.first_name"""),
        rider_list=[dict(r) for r in q("SELECT id,first_name,last_name FROM users WHERE role='rider' AND NOT EXISTS (SELECT 1 FROM employee_invitations i WHERE i.user_id=users.id AND i.status<>'active') AND NOT EXISTS (SELECT 1 FROM account_access a WHERE a.user_id=users.id AND a.disabled_at IS NOT NULL) ORDER BY first_name")],
        invitation_statuses=employee_invitations.summaries(),disabled_accounts=account_management.disabled_ids(),
        activity=q('SELECT * FROM audit_log ORDER BY id DESC LIMIT 100') if ops.allowed(current_user()['role'],'activity_log') else [],sales_controls=rows if ops.allowed(current_user()['role'],'void_sale') else [],
        refunds=q("SELECT * FROM orders WHERE payment_status='refund_required' ORDER BY id DESC LIMIT 100") if current_user()['role']=='owner' else [])

@bp.get('/live')
@admin_only
def live():   # polled by the admin page: new orders appear by themselves
    rows = admin_orders(); st = stats(); sig = sig_of(rows)
    return jsonify(sig=sig, last=max([r['id'] for r in rows], default=0), pending=st['pending'], sales=f"₱{st['sales']:,.2f}",
                   orders=[order_dict(r) for r in rows] if sig != request.args.get('sig') else None)


@bp.get('/reservations')
@admin_only
def reservations():
    if request.args.get('scope')=='table':
        rows=q("SELECT b.*,p.amount AS payment_amount,p.status AS payment_status,p.method AS payment_method, CONCAT(u.first_name,' ',u.last_name) cust,u.phone FROM diy_bookings b JOIN users u ON u.id=b.user_id LEFT JOIN workshop_payments p ON p.booking_id=b.id ORDER BY b.event_date DESC,b.id DESC LIMIT 50")
        response=jsonify([dict(dict(row),created_at=str(row['created_at'])) for row in rows])
        response.headers['Cache-Control']='private, no-store'
        return response
    from datetime import date
    try:
        start=date.fromisoformat(request.args.get('start',''));end=date.fromisoformat(request.args.get('end',''))
        if not 0<(end-start).days<=93:raise ValueError()
    except ValueError:return jsonify(error='Choose a valid calendar range of up to 93 days.'),400
    rows=q("SELECT b.*,CONCAT(u.first_name,' ',u.last_name) cust FROM diy_bookings b JOIN users u ON u.id=b.user_id WHERE b.event_date>=? AND b.event_date<? ORDER BY b.event_date,b.time_slot,b.id",(start.isoformat(),end.isoformat()))
    return jsonify([dict(dict(r),created_at=str(r['created_at'])) for r in rows])


@bp.get('/rider-advances')
@admin_only
def rider_advances():
    rows=q("""SELECT a.*, o.status AS order_status, o.total,
             CONCAT(u.first_name,' ',u.last_name) AS rider_name
             FROM rider_advances a JOIN orders o ON o.id=a.order_id
             JOIN users u ON u.id=a.rider_id ORDER BY a.advanced_at DESC LIMIT 100""")
    return render_template('admin/rider_advances.html',advances=rows)

@bp.post('/rider-advances/resolve')
@admin_only
def resolve_rider_advance():
    ops.actor('payment_review')
    oid=to_int(request.form.get('order_id'))
    decision=request.form.get('decision')
    note=(request.form.get('note') or '').strip()
    if decision not in ('store_refunded','no_refund') or not 10<=len(note)<=500:
        flash('Select a resolution and provide a 10–500 character explanation.','danger')
        return redirect(url_for('admin.rider_advances'))
    ops.lock_order(oid)
    a=q('SELECT * FROM rider_advances WHERE order_id=?'+(' FOR UPDATE' if mysql_enabled() else ''),(oid,),one=True)
    if not a or a['status']!='failed_pending':
        flash('This case is no longer pending review.','warning')
        return redirect(url_for('admin.rider_advances'))
    if decision=='store_refunded' and request.form.get('refund_confirmed')!='yes':
        flash('Confirm that the store actually returned the advance before recording a refund.','danger')
        return redirect(url_for('admin.rider_advances'))
    db().execute("UPDATE rider_advances SET status=?,resolved_at=?,resolved_by=?,resolution_note=? WHERE order_id=? AND status='failed_pending'",
                 (decision,ops.now(),current_user()['id'],note,oid))
    ops.audit('rider.advance_resolved','order',oid,{'decision':decision,'note':note})
    db().commit()
    flash('Rider advance case recorded.','success')
    return redirect(url_for('admin.rider_advances'))
