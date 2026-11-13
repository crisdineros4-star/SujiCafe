"""Private order QR images and authenticated, read-only staff lookup."""
import re,secrets
from io import BytesIO
import core,ops

def code_for(o):
    return f"SUJI-ORDER-{o['id']}"+(('-'+o['qr_token']) if o['qr_token'] else '')

def image(o):
    import qrcode
    data=BytesIO();qrcode.make(code_for(o),error_correction=qrcode.constants.ERROR_CORRECT_M,box_size=7,border=4).save(data,format='PNG');data.seek(0)
    return data

def lookup(code,lock=False):
    ops.actor('order_scan')
    if not isinstance(code,str) or len(code)>110:raise ValueError('Scan a valid order QR.')
    short=re.fullmatch(r'ORDER-([A-HJ-NP-Z2-9]{8})',code.strip().upper())
    if short:
        row=core.q('SELECT id FROM orders WHERE collection_code=?',(short.group(1),),one=True)
        if not row:raise ValueError('Order code not found. Check the eight characters shown in My Orders.')
        return ops.lock_order(row['id']) if lock else core.q('SELECT * FROM orders WHERE id=?',(row['id'],),one=True)
    match=re.fullmatch(r'SUJI-ORDER-(\d{1,18})(?:-([A-Za-z0-9_-]{32}))?',code.strip(),re.I)
    if not match:raise ValueError('Unknown QR. Scan the customer’s order QR, not their member QR.')
    oid=int(match.group(1));o=ops.lock_order(oid) if lock else core.q('SELECT * FROM orders WHERE id=?',(oid,),one=True)
    if not o or (o['qr_token'] and not secrets.compare_digest(o['qr_token'],match.group(2) or '')) or (not o['qr_token'] and match.group(2)):
        raise ValueError('Order QR not found or invalid.')
    return o

def details(o):
    u=core.q('SELECT first_name,last_name FROM users WHERE id=?',(o['user_id'],),one=True)
    lines=core.q('SELECT qty,price,item_name,is_reward FROM order_items WHERE order_id=? ORDER BY id',(o['id'],))
    model=core.Order.from_row(o)
    active=not model.terminal
    blocked=o['payment_method']=='gcash' and o['payment_status']!='paid'
    return dict(id=o['id'],created_at=__import__('time_utils').transaction_time(o['created_at']),customer=u['first_name']+' '+u['last_name'],member_code=f"SUJI-{o['user_id']:05d}",order_code=('ORDER-'+o['collection_code']) if o['collection_code'] else '',reference=o['gcash_reference'] or '',can_review_payment=active and o['payment_method']=='gcash' and o['payment_status'] in ('unpaid','submitted') and o['total']>0,type=o['order_type'],status=o['status'],status_label=core.status_label(o['order_type'],o['status']),
        payment_method=o['payment_method'],payment_status=o['payment_status'],total=str(o['total']),amount_due='0.00' if o['payment_status'] in ('paid','refund_required','refunded') or o['status']=='cancelled' else str(o['total']),points_used=o['points_used'],
        items=[dict(name=r['item_name'] or 'Order item',qty=r['qty'],price=str(r['price']),is_reward=bool(r['is_reward'])) for r in lines],
        can_accept=model.can_accept(),
        can_ready=model.can_ready(),
        can_complete=model.can_complete_in_store(),
        message=('This order was cancelled or voided. Do not fulfill it.' if o['status']=='cancelled' else 'This order is already completed. Do not serve it again.' if o['status']=='delivered' else 'Payment must be verified before preparation.' if blocked else 'Order found. Scanning does not change its status or deduct points again.'))


def member_lookup(code):
    ops.actor('order_scan')
    match=re.fullmatch(r'SUJI-(\d{1,18})',str(code or '').strip(),re.I)
    if not match:raise ValueError('Enter a member code such as SUJI-00012, or an order code.')
    member=core.q("SELECT id,first_name,last_name FROM users WHERE id=? AND role='customer'",(int(match.group(1)),),one=True)
    if not member:raise ValueError('Customer member code not found.')
    rows=core.q("SELECT * FROM orders WHERE user_id=? AND status NOT IN ('cancelled','delivered') ORDER BY id DESC LIMIT 20",(member['id'],))
    return dict(code=f"SUJI-{member['id']:05d}",name=member['first_name']+' '+member['last_name'],orders=[dict(details(o),code=('ORDER-'+o['collection_code']) if o['collection_code'] else code_for(o)) for o in rows])
