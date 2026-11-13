"""Workshop pay-at-cafe ledger; paid funds and booking status are independent."""
from decimal import Decimal, InvalidOperation
import re
import core, ops


def initialize():
    d=core.db()
    d.execute('''CREATE TABLE IF NOT EXISTS workshop_payments (
        booking_id INTEGER PRIMARY KEY, amount DECIMAL(10,2) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'unpaid', method VARCHAR(12),
        reference VARCHAR(30), paid_at VARCHAR(40), verified_by INTEGER,
        refunded_at VARCHAR(40), refund_method VARCHAR(12),
        refund_reference VARCHAR(80), refund_reason VARCHAR(500), refunded_by INTEGER)''')
    # Enforce one GCash reference per workshop payment, even if two staff submit together.
    if core.mysql_enabled():
        has_index=core.q('SELECT INDEX_NAME FROM information_schema.statistics WHERE table_schema=? AND table_name=? AND index_name=?',(core.config.MYSQL_DATABASE,'workshop_payments','uq_workshop_reference'))
        if not has_index:d.execute('CREATE UNIQUE INDEX uq_workshop_reference ON workshop_payments(reference)')
    else:d.execute('CREATE UNIQUE INDEX IF NOT EXISTS uq_workshop_reference ON workshop_payments(reference)')
    d.commit()


def price():
    product=core.q("SELECT price FROM products WHERE category='diy_cake' ORDER BY id LIMIT 1",one=True)
    return Decimal(str(product['price'])) if product else Decimal('0')


def record_new(booking_id,pax):
    amount=price()*int(pax)
    if amount<=0:raise ValueError('Workshop rate is unavailable. Contact the café.')
    core.db().execute('INSERT INTO workshop_payments(booking_id,amount) VALUES (?,?)',(booking_id,str(amount)))


def amount(value):
    try: x=Decimal(str(value))
    except (ValueError,InvalidOperation):raise ValueError('Enter a valid amount.')
    if not x.is_finite() or x<=0 or x.as_tuple().exponent < -2:raise ValueError('Enter a valid positive amount with at most two decimals.')
    return x


def payment_row(booking_id):
    return core.q('SELECT * FROM workshop_payments WHERE booking_id=?',(booking_id,),one=True)


def collect(booking_id,form):
    ops.actor('workshop_update')
    d=core.db()
    b=core.q('SELECT * FROM diy_bookings WHERE id=?',(booking_id,),one=True)
    if not b or b['status']!='confirmed':raise ValueError('Only confirmed reservations can be paid.')
    existing=payment_row(booking_id)
    if existing and existing['status']!='unpaid':raise ValueError('Payment is already recorded. Do not charge twice.')
    expected=Decimal(str(existing['amount'])) if existing else price()*int(b['pax'])
    if not existing and form.get('legacy_price_confirmed')!='yes':raise ValueError('Confirm the rate for this older reservation before collecting payment.')
    if expected<=0:raise ValueError('The workshop price is not configured.')
    if amount(form.get('amount'))!=expected:raise ValueError('Amount must match the reservation total.')
    method=form.get('method')
    if method not in ('cash','gcash'):raise ValueError('Choose Cash or GCash.')
    reference=None
    if method=='gcash':
        reference=form.get('reference','').strip()
        if not re.fullmatch(r'\d{13}',reference):raise ValueError('Enter the 13-digit GCash reference.')
        if form.get('wallet_checked')!='yes':raise ValueError('Verify the actual incoming GCash wallet transaction first.')
        if core.q('SELECT id FROM orders WHERE gcash_reference=?',(reference,),one=True) or core.q('SELECT booking_id FROM workshop_payments WHERE reference=?',(reference,),one=True):raise ValueError('That GCash reference was already used.')
    else:
        if form.get('cash_received')!='yes':raise ValueError('Confirm that full cash payment was actually received.')
    if not existing:d.execute('INSERT INTO workshop_payments(booking_id,amount) VALUES (?,?)',(booking_id,str(expected)))
    changed=d.execute('''UPDATE workshop_payments SET status='paid',method=?,reference=?,paid_at=?,verified_by=? WHERE booking_id=? AND status='unpaid' ''',(method,reference,ops.now(),core.current_user()['id'],booking_id))
    if changed.rowcount!=1:raise ValueError('The payment was already recorded. Refresh the reservation.')
    ops.audit('workshop.payment','booking',booking_id,{'method':method,'amount':str(expected),'reference':reference})
    d.commit()


def refund(booking_id,form):
    ops.actor('record_refund')
    b=core.q('SELECT status FROM diy_bookings WHERE id=?',(booking_id,),one=True)
    paid=payment_row(booking_id)
    if not b or b['status']!='cancelled' or not paid or paid['status']!='paid':raise ValueError('Only a cancelled, paid workshop reservation can be refunded.')
    if form.get('funds_returned')!='yes':raise ValueError('Confirm funds have actually been returned.')
    if amount(form.get('amount'))!=Decimal(str(paid['amount'])):raise ValueError('Refund amount must equal the full paid amount.')
    method=form.get('method')
    if method not in ('cash','gcash'):raise ValueError('Choose the actual refund method.')
    reference=form.get('reference','').strip(); reason=form.get('reason','').strip()
    if len(reason)<10 or len(reason)>500:raise ValueError('Explain the refund reason (10–500 characters).')
    if method=='gcash' and not reference:raise ValueError('Enter the refund transaction reference.')
    if len(reference)>80:raise ValueError('Refund reference is too long.')
    changed=core.db().execute('''UPDATE workshop_payments SET status='refunded',refunded_at=?,refund_method=?,refund_reference=?,refund_reason=?,refunded_by=? WHERE booking_id=? AND status='paid' ''',(ops.now(),method,reference,reason,core.current_user()['id'],booking_id))
    if changed.rowcount!=1:raise ValueError('Refund already recorded. Refresh the reservation.')
    ops.audit('workshop.refunded','booking',booking_id,{'amount':str(paid['amount']),'method':method,'reference':reference,'reason':reason})
    core.db().commit()
