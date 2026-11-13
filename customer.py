"""Customer area: /customer  (menu, bag, orders, cake painting workshop, profile)."""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, abort, send_file
from core import *
import commerce
import email_validation
import ops, order_qr
from services import BookingService,CustomerDashboardService
import workshop_payments
from domain import BOOKING_SLOTS

bp = Blueprint('customer', __name__, url_prefix='/customer')
customer_only = login_required('customer')

# ---------------- menu (guests can look, ordering needs login) ----------------
@bp.route('/')
def menu():
    u = current_user()
    if u and u['role'] != 'customer': return redirect(home_for(u))
    prods=q("SELECT * FROM products WHERE is_available=1 AND category<>'diy_cake' ORDER BY name")
    sections=list(dict.fromkeys(i['section'] for i in commerce.CATALOG['items']))
    groups=[]
    for section in sections:
        items=[r for r in prods if r['menu_section']==section and r['category']!='merchandise']
        if items:groups.append((section,items,items[0]['category']))
    other=[r for r in prods if r['menu_section'] not in sections and r['category']!='merchandise']
    for cat,label in CATEGORIES:
        items=[r for r in other if r['category']==cat]
        if items:groups.append((label,items,cat))
    merchandise=[r for r in prods if r['category']=='merchandise']
    if merchandise:groups.append(('Merchandise',merchandise,'merchandise'))
    return render_template('customer/menu.html', groups=groups,category_filters=CATEGORIES[:3],gallery=commerce.CATALOG)

@bp.get('/dashboard')
@customer_only
def dashboard():
    data=CustomerDashboardService(db(),mysql_enabled()).for_user(current_user())
    return render_template('customer/dashboard.html',**data)

# ---------------- delivery, dine-in or pick-up, chosen before ordering ----------------
MODES = ('delivery', 'dinein')

@bp.post('/mode')
def set_mode():
    if request.form.get('mode') not in MODES:return jsonify(ok=False,msg='Choose Dine-in or Delivery.'),400
    session['mode']=request.form['mode']
    return jsonify(mode=session['mode'])

# ---------------- bag ----------------
def _styled_bouquets(rows):
    selected=session.get('bouquet_styles',{})
    styled=[]
    for raw in rows:
        row=dict(raw);image=selected.get(str(row['id']))
        if image in commerce.CATALOG['flowers'] and row['category']=='merchandise' and row['name'].startswith('Likha Blooms'):
            index=commerce.CATALOG['flowers'].index(image)+1
            row['name']=row['name']+' · Bouquet style '+str(index)
            row['image']='menu/'+image
        styled.append(row)
    return styled

@bp.post('/cart/add')
@customer_only
def cart_add():
    if session.get('mode') not in MODES:return jsonify(need_mode=True),409
    pid=to_int(request.form.get('id'))
    row=q("SELECT * FROM products WHERE id=? AND is_available=1 AND category<>'diy_cake'",(pid,),one=True)
    if not row:return jsonify(ok=False,msg='This item is not available.'),400
    style=request.form.get('bouquet_style','')
    selected=session.setdefault('bouquet_styles',{})
    is_bouquet=row['category']=='merchandise' and row['name'].startswith('Likha Blooms')
    if style and (not is_bouquet or style not in commerce.CATALOG['flowers']):return jsonify(ok=False,msg='Choose a valid bouquet design.'),400
    if is_bouquet and not style:style=selected.get(str(pid)) or (row['image'] or '').removeprefix('menu/')
    c=session.setdefault('cart',{})
    if is_bouquet and c.get(str(pid),0)>0 and selected.get(str(pid)) and selected[str(pid)]!=style:
        return jsonify(ok=False,msg='One design per bouquet size is allowed in each order. Remove that size from your cart before choosing another design.'),409
    if is_bouquet and style in commerce.CATALOG['flowers']:selected[str(pid)]=style
    c[str(pid)]=min(20,c.get(str(pid),0)+1);session.modified=True
    n,sub=cart_totals();return jsonify(count=n,sub=sub)

@bp.post('/cart/set')
@customer_only
def cart_set():   # live quantity change from the bag page (0 = remove)
    c = session.setdefault('cart', {}); pid = to_int(request.form.get('id'))
    n = max(0, min(20, to_int(request.form.get('qty'))))
    ok = q("SELECT 1 FROM products WHERE id=? AND is_available=1 AND category<>'diy_cake'", (pid,), one=True)
    if n and ok: c[str(pid)] = n
    else:
        c.pop(str(pid),None);session.setdefault('bouquet_styles',{}).pop(str(pid),None)
    session.modified = True
    n, sub = cart_totals(); return jsonify(count=n, sub=sub)

@bp.route('/cart', methods=['GET', 'POST'])
@customer_only
def cart():
    c=session.setdefault('cart',{});u=current_user()
    mode=session.get('mode') if session.get('mode') in MODES else 'delivery'
    form=request.form.to_dict() if request.method=='POST' else {}
    needs_phone=bool(phone_error(u['phone'] or ''));phone_message=None
    if request.method=='POST' and form.get('action')=='checkout' and c:
        mode=form.get('order_type') if form.get('order_type') in MODES else 'delivery'
        ids=[to_int(i) for i in c]
        rows=_styled_bouquets(q(f"SELECT * FROM products WHERE id IN ({','.join('?' * len(ids))})",ids))
        errs=[];lat=lng=None;new_phone=None
        if not rows:errs.append('Those items are no longer available.')
        if mode=='delivery':
            pay='gcash' if form.get('payment')=='gcash' else 'cod'
            address_errors,addr=delivery_address(request.form);errs+=address_errors
            if needs_phone:
                new_phone=form.get('phone','').strip();phone_message=phone_error(new_phone)
                if not phone_message:
                    import accounts
                    if accounts.taken(new_phone,u['id']):phone_message='This mobile number is already registered. Use your own number or recover your existing account.'
                if phone_message:errs.append(phone_message)
            try:lat=float(form.get('lat',''));lng=float(form.get('lng',''))
            except (TypeError,ValueError):lat=lng=None
            if form.get('location_confirmed') != 'yes':errs.append('Confirm your delivery location on the map before ordering.')
            if lat is None or not (-90<=lat<=90 and -180<=lng<=180):errs.append('Drop a pin on the map so the rider can find you.')
            elif not pin_allowed(lat,lng,form.get('city','')):errs.append('The map pin must be within the delivery service area.')
        else:
            table=re.sub(r'[^A-Za-z0-9 -]','',form.get('table','')).strip()[:10]
            addr=f"Dine-in at {STORE['name']}"+(f", table {table}" if table else '')
            pay='gcash' if form.get('payment')=='gcash' else 'counter'
        if errs:
            for message in errs:flash(message,'danger')
        else:
            try:
                if form.get('confirm_order')!='yes':raise ValueError('Review your order and select Yes, place order in the confirmation dialog.')
                key=form.get('checkout_key','')
                if not key or key!=session.get('checkout_key'):raise ValueError('Refresh your bag before placing this order.')
                quote=commerce.OrderQuote(rows,c,mode,to_int(form.get('reward_id')))
                if pay=='gcash' and quote.total>0 and not commerce.gcash_ready():raise ValueError('The café needs to configure its real GCash QR or receiving number first. Choose cash or ask Staff.')
                d=db()
                if new_phone:
                    import accounts
                    accounts.claim(new_phone,u['id'])
                    d.execute('UPDATE users SET phone=? WHERE id=?',(new_phone,u['id']))
                oid=quote.insert(u['id'],pay,addr,mode,lat,lng,key)
                if mode=='delivery':
                    if not q('SELECT id FROM saved_addresses WHERE user_id=? AND full_address=?',(u['id'],addr),one=True):
                        d.execute('INSERT INTO saved_addresses(user_id,label,full_address,region,province,city,barangay,street,lat,lng) VALUES (?,?,?,?,?,?,?,?,?,?)',(u['id'],'Home',addr,form.get('region',''),form.get('province',''),form.get('city',''),form.get('barangay',''),form.get('street',''),lat,lng))
                    if not u['address']:d.execute('UPDATE users SET address=? WHERE id=?',(addr,u['id']))
                d.commit()
            except ValueError as exc:
                db().rollback();flash(str(exc),'danger')
                if 'mobile number' in str(exc).lower():phone_message=str(exc)
            except Exception:
                db().rollback();flash('Could not place this order. Check My Orders before retrying.','danger')
            else:
                session['cart']={};session.pop('checkout_key',None);session.pop('selected_reward',None);session.pop('bouquet_styles',None)
                flash((f"Order #{oid} placed. Complete the GCash transfer and submit its reference so Staff can confirm payment and accept the order." if pay=='gcash' and quote.total>0 else f"Order #{oid} placed. Show the order QR or your member code to Staff at the café." if mode=='dinein' else f"Order #{oid} placed! Delivery orders do not earn reward points."),'success')
                return redirect(url_for('payments.payment',order_id=oid) if pay=='gcash' and quote.total>0 else url_for('customer.orders'))
    items=[];sub=0
    if c:
        ids=[to_int(i) for i in c]
        for row in _styled_bouquets(q(f"SELECT * FROM products WHERE id IN ({','.join('?' * len(ids))})",ids)):
            qty=c[str(row['id'])];items.append(dict(p=row,qty=qty,line=row['price']*qty));sub+=row['price']*qty
    session.setdefault('checkout_key',secrets.token_hex(24))
    return render_template('customer/cart.html',checkout_key=session['checkout_key'],items=items,sub=sub,mode=mode,
                           fee=50 if mode=='delivery' and items and sub<500 else 0,
                           addresses=[r for r in q('SELECT * FROM saved_addresses WHERE user_id=? ORDER BY id DESC',(u['id'],)) if address_allowed(dict(r))],
                           checkout_form=form,needs_delivery_phone=needs_phone,delivery_phone=form.get('phone',u['phone'] or '') if needs_phone else u['phone'],delivery_phone_error=phone_message)

# ---------------- orders ----------------
ORDERS_SQL = """SELECT o.*, COALESCE(group_concat(CONCAT(oi.qty,'x ',COALESCE(oi.item_name,p.name)), ', '), 'In-store purchase') AS items,
                CONCAT(r.first_name,' ',r.last_name) AS rider_name, r.phone AS rider_phone,
                MAX(gps.lat) AS rider_lat,MAX(gps.lng) AS rider_lng,MAX(gps.accuracy) AS rider_accuracy,MAX(gps.observed_at) AS rider_observed_at
                FROM orders o LEFT JOIN order_items oi ON oi.order_id=o.id LEFT JOIN products p ON p.id=oi.product_id
                LEFT JOIN users r ON r.id=o.rider_id
                LEFT JOIN order_rider_locations gps ON gps.order_id=o.id AND gps.rider_id=o.rider_id
                WHERE o.user_id=? AND o.hidden_by_customer=0 GROUP BY o.id ORDER BY o.id DESC LIMIT 60"""

@bp.route('/orders', methods=['GET', 'POST'])
@customer_only
def orders():
    u = current_user()
    if request.method == 'POST' and request.form.get('action')=='hide':
        run("UPDATE orders SET hidden_by_customer=1 WHERE id=? AND user_id=? AND status IN ('delivered','cancelled')",(to_int(request.form.get('id')),u['id']))
        flash('Order hidden from your list. Store receipt records are retained.','info')
        return redirect(url_for('customer.orders'))
    if request.method == 'POST':   # a customer can cancel while the order is still "Placed"; points come back
        o = q("SELECT * FROM orders WHERE id=? AND user_id=? AND status='pending'", (to_int(request.form.get('id')), u['id']), one=True)
        if o:
            d = db(); cancel_order(d, o); d.commit(); flash(f"Order #{o['id']} cancelled.", 'info')
        else: flash('Only orders that are still "Placed" can be cancelled.', 'warning')
        return redirect(url_for('customer.orders'))
    return render_template('customer/orders.html', orders=q(ORDERS_SQL, (u['id'],)))

@bp.get('/orders/<int:order_id>/receipt')
@customer_only
def receipt(order_id):
    u = current_user()
    order = q("SELECT * FROM orders WHERE id=? AND user_id=?", (order_id, u['id']), one=True)
    if not order: return ('Receipt not found.', 404)
    if not commerce.receipt_ready(order):
        flash('Payment receipt is available after payment confirmation.','info')
        return redirect(url_for('customer.orders'))
    items = q("SELECT oi.qty,oi.price,oi.is_reward,COALESCE(oi.item_name,p.name) name FROM order_items oi JOIN products p ON p.id=oi.product_id WHERE oi.order_id=?", (order_id,))
    return render_template('customer/receipt.html', order=order, items=items)

@bp.get('/orders/<int:order_id>/qr.png')
@customer_only
def order_qr_image(order_id):
    o=q('SELECT * FROM orders WHERE id=? AND user_id=?',(order_id,current_user()['id']),one=True)
    if not o or o['order_type'] not in ('dinein','pickup') or o['status'] in ('cancelled','delivered'):abort(404)
    response=send_file(order_qr.image(o),mimetype='image/png',max_age=0)
    response.headers['Cache-Control']='private, no-store'
    return response

@bp.get('/orders/live')
@customer_only
def orders_live():   # polled by the Orders page so "Delivered" shows up by itself
    u = current_user()
    response=jsonify(points=u['points'], orders=[dict(
        id=r['id'], payment_method=r['payment_method'], payment_status=r['payment_status'], receipt_ready=commerce.receipt_ready(r), status=r['status'], label=status_label(r['order_type'], r['status']),
        idx=flow_idx(r['order_type'], r['status']), pts=points_text(r),earned=r['points_earned'] if r['points_credited'] else 0,
        rider=(f"{r['rider_name']}, {r['rider_phone']}" if r['rider_name'] else ''),tracking=__import__('delivery_tracking').snapshot(r)) for r in q(ORDERS_SQL, (u['id'],))])
    response.headers['Cache-Control']='private, no-store'
    return response

# ---------------- saved delivery addresses ----------------
@bp.route('/addresses', methods=['GET', 'POST'])
@customer_only
def addresses():
    u = current_user()
    if request.method == 'POST':
        aid = to_int(request.form.get('id'))
        if request.form.get('action') == 'delete':
            run('DELETE FROM saved_addresses WHERE id=? AND user_id=?', (aid, u['id']))
            flash('Address deleted.', 'success')
        else:
            errs, full = delivery_address(request.form)
            try:
                lat, lng = request.form.get('lat'), request.form.get('lng')
                if lat or lng:
                    if not pin_allowed(float(lat), float(lng),request.form.get('city','')): errs.append('Pin must be within the local delivery service area.')
            except (TypeError, ValueError): errs.append('Invalid map coordinates.')
            if errs:
                for e in errs: flash(e, 'danger')
            else:
                args = (u['id'], request.form.get('label','Home')[:40], full,
                        request.form.get('region',''), request.form.get('province',''),
                        request.form.get('city',''), request.form.get('barangay',''),
                        request.form.get('street',''), request.form.get('lat') or None,
                        request.form.get('lng') or None)
                if request.form.get('action') == 'update':
                    run('UPDATE saved_addresses SET label=?,full_address=?,region=?,province=?,city=?,barangay=?,street=?,lat=?,lng=? WHERE id=? AND user_id=?',
                        (args[1],args[2],args[3],args[4],args[5],args[6],args[7],args[8],args[9],aid,u['id']))
                    flash('Address updated.', 'success')
                else:
                    run('INSERT INTO saved_addresses (user_id,label,full_address,region,province,city,barangay,street,lat,lng) VALUES (?,?,?,?,?,?,?,?,?,?)', args)
                    flash('Address saved.', 'success')
        return redirect(url_for('customer.addresses'))
    return render_template('customer/addresses.html', addresses=q('SELECT * FROM saved_addresses WHERE user_id=? ORDER BY id DESC',(u['id'],)))

# ---------------- cake painting workshop ----------------
SLOTS = list(BOOKING_SLOTS); CAP = BookingService.CAPACITY

@bp.route('/workshop', methods=['GET', 'POST'])
@customer_only
def workshop():
    u=current_user();tomorrow=(business_today()+timedelta(days=1)).isoformat()
    if request.method=='POST':
        service=BookingService(db(),mysql_enabled())
        try:
            if request.form.get('action')=='cancel':
                changed=service.cancel(to_int(request.form.get('id')),u['id'])
                flash('Reservation cancelled.' if changed else 'This reservation cannot be cancelled.','info')
            else:
                bid=service.reserve(u['id'],request.form.get('date',''),request.form.get('slot',''),request.form.get('pax',''))
                workshop_payments.record_new(bid,request.form.get('pax',''))
                flash('Workshop slot reserved! Staff will review it shortly.','success')
            db().commit()
        except ValueError as exc:db().rollback();flash(str(exc),'danger')
        except Exception:db().rollback();flash('The reservation could not be saved. Refresh and check your reservations before retrying.','danger')
        return redirect(url_for('customer.workshop'))
    price = q("SELECT price FROM products WHERE category='diy_cake' ORDER BY id LIMIT 1", one=True)
    bookings = q('SELECT b.*,p.amount AS payment_amount,p.status AS payment_status,p.method AS payment_method FROM diy_bookings b LEFT JOIN workshop_payments p ON p.booking_id=b.id WHERE b.user_id=? ORDER BY b.event_date DESC', (u['id'],))
    return render_template('customer/workshop.html', slots=SLOTS, price=price['price'] if price else 0,
                           bookings=bookings, tomorrow=tomorrow, today=business_today().isoformat())

@bp.get('/workshop/<int:booking_id>/receipt')
@customer_only
def workshop_receipt(booking_id):
    b=q("""SELECT b.*,p.amount,p.status AS payment_status,p.method,p.reference,p.paid_at,p.refunded_at,p.refund_method,p.refund_reference FROM diy_bookings b JOIN workshop_payments p ON p.booking_id=b.id WHERE b.id=? AND b.user_id=?""",(booking_id,current_user()['id']),one=True)
    if not b or b['payment_status'] not in ('paid','refunded'):
        flash('Receipt available after payment is recorded.','info');return redirect(url_for('customer.workshop'))
    return render_template('customer/workshop_receipt.html',booking=b)

# ---------------- profile ----------------
@bp.route('/profile', methods=['GET', 'POST'])
@customer_only
def profile():
    u = current_user()
    if request.method == 'POST':
        if request.form.get('action') == 'info':
            from account_validation import details
            err=None
            try:values=details(request.form)
            except ValueError as exc:err=str(exc);values={k:request.form.get(k,'').strip() for k in ('first_name','middle_name','last_name','phone')}
            first,last,phone=(values[k] for k in ('first_name','last_name','phone'))
            email=u['email'];addr=request.form.get('address','').strip()
            if len(addr)>500 or any(ord(c)<32 for c in addr):err='Address must be at most 500 characters without control characters.'
            import accounts
            if not err and phone!=u['phone'] and accounts.taken(phone,u['id']):err='This mobile number is already registered.'
            if not err and addr and len(addr) < 10: err = 'Your address looks incomplete. Complete it or leave it empty.'
            if err: flash(err, 'danger'); return redirect(url_for('customer.profile', open='info'))
            try:
                if phone!=u['phone']:accounts.claim(phone,u['id'])
                db().execute('UPDATE users SET first_name=?,middle_name=?,last_name=?,phone=?,address=? WHERE id=?', (first,values['middle_name'] or None,last,phone,addr,u['id']))
                db().commit()
            except Exception as exc:
                db().rollback()
                if isinstance(exc,ValueError) or type(exc).__name__=='IntegrityError':
                    flash('Email or mobile number is already registered.','danger');return redirect(url_for('customer.profile',open='info'))
                raise
            flash('Details saved.', 'success')
        else:
            new = request.form.get('new', '')
            if not check_password_hash(u['password_hash'], request.form.get('current', '')): flash('Current password is wrong.', 'danger')
            elif not 8<=len(new)<=128 or not PW.fullmatch(new): flash('Use 8–128 characters with uppercase, lowercase, a number and a symbol.', 'danger')
            elif check_password_hash(u['password_hash'],new):flash('New password must be different from your current password.','danger')
            elif new != request.form.get('confirm'): flash('Passwords do not match.', 'danger')
            else:
                db().execute('UPDATE users SET password_hash=? WHERE id=?', (generate_password_hash(new), u['id']))
                __import__('security').revoke_credentials(u['id']);db().commit()
                __import__('security').establish(u['id'])
                flash('Password changed. Other devices must verify again.','success')
                import device_trust
                return device_trust.remember(u['id'],redirect(url_for('customer.profile')))
            return redirect(url_for('customer.profile', open='password'))
        return redirect(url_for('customer.profile'))
    return render_template('customer/profile.html')
@bp.route('/rewards',methods=['GET','POST'])
@customer_only
def rewards():
    if request.method=='POST':
        pid=to_int(request.form.get('id'))
        product=q("SELECT * FROM products WHERE id=? AND is_available=1 AND points_cost>0 AND category IN ('food','drink')",(pid,),one=True)
        if not product or current_user()['points']<product['points_cost']:
            flash('You do not have enough points for that available item yet.','warning')
        elif request.form.get('action')=='redeem':
            try:
                if not mysql_enabled():db().execute('UPDATE products SET id=id WHERE id=?',(pid,))
                product=db().execute("SELECT * FROM products WHERE id=? AND is_available=1 AND points_cost>0 AND category IN ('food','drink')"+(' FOR UPDATE' if mysql_enabled() else ''),(pid,)).fetchone()
                if not product:raise ValueError('This reward is no longer available. Choose another item.')
                if request.form.get('confirm_reward')!='yes':raise ValueError('Confirm your reward before redeeming it.')
                key=request.form.get('reward_key','')
                if not key or key!=session.get('reward_key'):raise ValueError('This redemption was already submitted or the page expired. Check My Orders before trying again.')
                if request.form.get('expected_points')!=str(product['points_cost']):raise ValueError('The points price changed. Refresh and review the reward before confirming.')
                quote=commerce.OrderQuote([product],{str(pid):1},'pickup',pid)
                oid=quote.insert(current_user()['id'],'points','Collect at '+STORE['address'],'pickup',checkout_key=key)
                ops.audit('reward.redeemed','order',oid,{'product_id':pid,'points_used':quote.points_used,'fulfillment':'store collection'})
                db().commit();session.pop('reward_key',None)
                flash(f'Reward order #{oid} created. Show its QR at the café. {quote.points_used} points used; no cash payment is due.','success')
                return redirect(url_for('customer.orders',_anchor='order-'+str(oid)))
            except ValueError as exc:db().rollback();flash(str(exc),'danger')
            except Exception:db().rollback();flash('Could not save the reward. Check My Orders before retrying.','danger')
            return redirect(url_for('customer.rewards'))
        else:
            cart=session.setdefault('cart',{})
            cart[str(pid)]=max(1,min(20,cart.get(str(pid),0)))
            session['selected_reward']=pid;session.setdefault('mode','delivery');session.modified=True
            flash('Reward added to your bag. Review the order and confirm redemption at checkout.','success')
            return redirect(url_for('customer.cart'))
    session.setdefault('reward_key',secrets.token_hex(24))
    return render_template('customer/rewards.html',reward_key=session['reward_key'],products=q("SELECT * FROM products WHERE is_available=1 AND points_cost>0 AND category IN ('food','drink') ORDER BY category,points_cost,name"))

@bp.post('/location/search')
@customer_only
def search_delivery_location():
    """Approximate map suggestion for supported municipality/barangay selection."""
    import json, time, urllib.parse, urllib.request, unicodedata
    from service_area import DELIVERY_COVERAGE, canonical_city, pin_allowed

    city = canonical_city(request.form.get('city', ''))
    barangay = request.form.get('barangay', '').strip()
    street = request.form.get('street', '').strip()[:100]
    if city not in DELIVERY_COVERAGE or barangay not in DELIVERY_COVERAGE[city]:
        return jsonify(ok=False, message='Choose a supported municipality and barangay.'), 400
    if time.time() - session.get('last_forward_location', 0) < 2:
        return jsonify(ok=False, message='Please wait a moment before searching again.'), 429
    session['last_forward_location'] = time.time()

    def norm(value):
        return ''.join(c for c in unicodedata.normalize('NFD', value.casefold())
                       if not unicodedata.combining(c)).replace('city of ', '').strip()

    try:
        # Try the street/landmark first; fall back to the barangay if the map
        # provider cannot identify a house or street. The pin remains unconfirmed.
        # '(Pob.)' is a local administrative suffix; many OSM entries omit it.
        # Try the exact barangay first, then accepted spelling variants.
        base_barangay = barangay.replace(' (Pob.)', '').strip()
        variants = [barangay]
        if base_barangay != barangay:
            variants.extend([base_barangay, f'{base_barangay} Poblacion'])
        searches = []
        for name in dict.fromkeys(variants):
            if len(street) >= 3:
                searches.append((f'{street}, {name}, {city}, Laguna, Philippines', 'street'))
            searches.append((f'{name}, {city}, Laguna, Philippines', 'barangay'))
        for query, precision in searches:
            params = urllib.parse.urlencode({'q': query, 'format': 'jsonv2',
                                             'limit': 5, 'countrycodes': 'ph'})
            req = urllib.request.Request(
                'https://nominatim.openstreetmap.org/search?' + params,
                headers={'User-Agent': 'SujiCafeDelivery/1.0 (customer-requested map search)',
                         'Accept-Language': 'en'})
            try:
                with urllib.request.urlopen(req, timeout=6) as response:
                    candidates = json.loads(response.read(65536))
            except Exception:
                # A missing street lookup should not prevent trying the barangay.
                if precision == 'street':
                    continue
                raise
            for candidate in candidates:
                description = norm(candidate.get('display_name', ''))
                lat, lng = float(candidate['lat']), float(candidate['lon'])
                if norm(city) in description and norm('Laguna') in description and pin_allowed(lat, lng, city):
                    message = ('Possible street location found. Check and adjust the pin to your exact entrance.'
                               if precision == 'street' else
                               'Approximate barangay location found. Move the pin to your actual house or street.')
                    return jsonify(ok=True, lat=lat, lng=lng, message=message)
        return jsonify(ok=False, message='Map could not locate this address. Tap the map to pin your exact location.'), 404
    except Exception:
        return jsonify(ok=False, message='Address search is unavailable. Tap the map instead.'), 503


@bp.post('/location/address')
@customer_only
def locate_address():
    """Opt-in reverse geocoding; coordinates never enter request URLs or logs."""
    import json,time,urllib.parse,urllib.request,unicodedata
    try:
        lat=float(request.form.get('lat',''));lng=float(request.form.get('lng',''))
        if not __import__('service_area').pin_allowed(lat,lng,None):return jsonify(ok=False,message='Your location is outside our current delivery area. Select a supported address manually.'),400
    except (ValueError,TypeError):return jsonify(ok=False,message='Invalid location.'),400
    if time.time()-session.get('last_reverse_location',0)<2:return jsonify(ok=False,message='Please wait a moment before trying again.'),429
    session['last_reverse_location']=time.time()
    try:
        query=urllib.parse.urlencode(dict(format='jsonv2',lat=lat,lon=lng,zoom=18,addressdetails=1))
        req=urllib.request.Request('https://nominatim.openstreetmap.org/reverse?'+query,headers={'User-Agent':'SujiCafeDelivery/1.0 (customer-requested address lookup)','Accept-Language':'en'})
        with urllib.request.urlopen(req,timeout=5) as response:data=json.loads(response.read(65536))
        a=data.get('address',{})
        norm=lambda value: ''.join(c for c in unicodedata.normalize('NFD',value.casefold()) if not unicodedata.combining(c)).replace('barangay ','').replace('brgy. ','').replace('city of ','').replace(' (pob.)','').replace(' poblacion','').strip()
        from service_area import DELIVERY_COVERAGE
        cities=[a.get(k,'') for k in ('city','town','municipality')]
        city=next((__import__('service_area').canonical_city(c) for c in cities if __import__('service_area').canonical_city(c) in DELIVERY_COVERAGE),'')
        if not city or not pin_allowed(lat,lng,city):return jsonify(ok=False,message='This location is outside the supported delivery areas.'),400
        parts=[a.get(k,'') for k in ('suburb','village','neighbourhood','quarter','hamlet')]
        barangay=next((b for b in DELIVERY_COVERAGE.get(city,[]) if norm(b) in [norm(part) for part in parts]),'')
        street=' '.join(a.get(k,'') for k in ('house_number','road')).strip()[:100]
        return jsonify(ok=True,city=city,barangay=barangay,street=street,display=data.get('display_name','')[:500],message='Confirm your house number, barangay and landmark before ordering. GPS may be approximate.')
    except Exception:
        return jsonify(ok=False,message='Your pin was saved. Address lookup is unavailable; please select your barangay and enter your house/street.'),503


@bp.route('/notifications',methods=['GET','POST'])
@customer_only
def notifications():
    uid=current_user()['id']
    if request.method=='POST':
        if request.form.get('action')=='read_all':db().execute('UPDATE customer_notifications SET read_at=? WHERE user_id=? AND read_at IS NULL',(ops.now(),uid))
        elif request.form.get('action')=='read':db().execute('UPDATE customer_notifications SET read_at=? WHERE id=? AND user_id=?',(ops.now(),to_int(request.form.get('id')),uid))
        else:flash('Choose a valid notification action.','danger');return redirect(url_for('customer.notifications'))
        db().commit();return redirect(url_for('customer.notifications'))
    rows=q('SELECT * FROM customer_notifications WHERE user_id=? ORDER BY id DESC LIMIT 100',(uid,))
    return render_template('customer/notifications.html',notifications=rows)

@bp.get('/notifications/live')
@customer_only
def notifications_live():
    import order_notifications
    uid=current_user()['id']
    return jsonify(unread=order_notifications.unread(uid),items=[dict(r) for r in q('SELECT id,order_id,title,message,created_at,read_at FROM customer_notifications WHERE user_id=? ORDER BY id DESC LIMIT 20',(uid,))])
