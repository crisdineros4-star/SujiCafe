"""Role permissions, transactional order operations and append-only activity records."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from functools import wraps
from flask import abort, has_request_context, request
import core, commerce

PERMISSIONS = {
    'customer_workspace': {'customer'}, 'staff_workspace': {'staff'},
    'owner_workspace': {'owner'}, 'admin_workspace': {'admin'}, 'rider_workspace': {'rider'},
    'assign_rider': {'staff','admin','owner'}, 'update_order': {'staff','admin','owner'},
    'payment_review': {'staff','admin','owner'}, 'cash_handover': {'staff','admin','owner'},
    'counter_sale': {'staff'}, 'workshop_update': {'staff','admin','owner'},
    'order_scan': {'staff'}, 'order_fulfill': {'staff'},
    'manage_store': {'owner'}, 'manage_menu': {'admin','owner'},
    'manage_accounts': {'admin','owner'}, 'create_admin': {'owner'},
    'void_sale': {'owner'}, 'record_refund': {'owner'}, 'activity_log': {'owner'},
    'rider_pickup': {'rider'}, 'rider_deliver': {'rider'},
}

def now(): return datetime.now(ZoneInfo('Asia/Manila')).isoformat(timespec='seconds')
def allowed(role, permission): return role in PERMISSIONS.get(permission,set())
def actor(permission):
    u=core.current_user()
    if not u or not core.User.from_row(u).has_permission(permission): abort(403)
    return u

def initialize():
    d=core.db();mysql=core.mysql_enabled()
    auto='INT AUTO_INCREMENT PRIMARY KEY' if mysql else 'INTEGER PRIMARY KEY AUTOINCREMENT'
    d.execute(f'''CREATE TABLE IF NOT EXISTS audit_log (
        id {auto}, actor_id INTEGER NULL, actor_name VARCHAR(120) NOT NULL,
        actor_role VARCHAR(20) NOT NULL, event VARCHAR(60) NOT NULL,
        entity_type VARCHAR(30) NOT NULL, entity_id INTEGER NULL,
        details TEXT NOT NULL, created_at VARCHAR(40) NOT NULL)''')
    d.execute(f'''CREATE TABLE IF NOT EXISTS cash_remittances (
        id {auto}, rider_id INTEGER NOT NULL, received_by INTEGER NOT NULL,
        expected_cents INTEGER NOT NULL, received_cents INTEGER NOT NULL,
        variance_cents INTEGER NOT NULL, reason VARCHAR(500) NOT NULL,
        receipt_key VARCHAR(64) NOT NULL UNIQUE, created_at VARCHAR(40) NOT NULL)''')
    d.execute(f'''CREATE TABLE IF NOT EXISTS rider_advances (
        order_id INTEGER PRIMARY KEY, rider_id INTEGER NOT NULL,
        amount_cents INTEGER NOT NULL, advanced_at VARCHAR(40) NOT NULL,
        status VARCHAR(30) NOT NULL DEFAULT 'advanced',
        failed_reason VARCHAR(500) NOT NULL DEFAULT '',
        failed_at VARCHAR(40) NULL, resolved_at VARCHAR(40) NULL,
        resolved_by INTEGER NULL, resolution_note VARCHAR(500) NOT NULL DEFAULT ''
    )''')
    columns={
        'users':{'reward_debt_points':'INTEGER NOT NULL DEFAULT 0','reward_opening_carry_cents':'INTEGER NULL','reward_next_sequence':'INTEGER NOT NULL DEFAULT 0'},
        'orders':{
            'qr_token':'VARCHAR(40) NULL',
            'collection_code':'VARCHAR(20) NULL',
            'cash_collected_cents':'INTEGER NOT NULL DEFAULT 0','cash_remittance_id':'INTEGER NULL',
            'updated_at':'VARCHAR(40) NULL','accepted_at':'VARCHAR(40) NULL','ready_at':'VARCHAR(40) NULL','delivered_at':'VARCHAR(40) NULL','cancelled_at':'VARCHAR(40) NULL',
            'voided_at':'VARCHAR(40) NULL','voided_by':'INTEGER NULL','void_reason':"VARCHAR(500) NOT NULL DEFAULT ''",
            'refund_method':"VARCHAR(40) NOT NULL DEFAULT ''",'refund_reference':"VARCHAR(150) NOT NULL DEFAULT ''",
            'refunded_at':'VARCHAR(40) NULL','refunded_by':'INTEGER NULL',
            'reward_carry_delta_cents':'INTEGER NULL','reward_sequence':'INTEGER NULL','reward_effective_points':'INTEGER NULL',
            'points_reversed':'INTEGER NOT NULL DEFAULT 0'}}
    for table,cols in columns.items():
        names={r['COLUMN_NAME'] for r in core.q('SELECT COLUMN_NAME FROM information_schema.columns WHERE table_schema=? AND table_name=?',(core.config.MYSQL_DATABASE,table))} if mysql else {r['name'] for r in core.q(f'PRAGMA table_info({table})')}
        for col,ddl in cols.items():
            if col not in names:d.execute(f'ALTER TABLE {table} ADD COLUMN {col} {ddl}')
    for name,cols in [('idx_orders_reward_sequence','user_id,reward_sequence'),('idx_orders_rider_cash','rider_id,cash_remittance_id')]:
        exists=core.q('SELECT INDEX_NAME FROM information_schema.statistics WHERE table_schema=? AND table_name=\'orders\' AND index_name=?',(core.config.MYSQL_DATABASE,name)) if mysql else [r for r in core.q('PRAGMA index_list(orders)') if r['name']==name]
        if not exists:d.execute(f'CREATE INDEX {name} ON orders({cols})')
    name='uq_orders_collection_code'
    exists=core.q('SELECT INDEX_NAME FROM information_schema.statistics WHERE table_schema=? AND table_name=\'orders\' AND index_name=?',(core.config.MYSQL_DATABASE,name)) if mysql else [r for r in core.q('PRAGMA index_list(orders)') if r['name']==name]
    if not exists:d.execute(f'CREATE UNIQUE INDEX {name} ON orders(collection_code)')
    d.commit()
    owner_email=core.config.OWNER_EMAIL
    if owner_email and not core.q("SELECT id FROM owner_transfers WHERE status='completed' LIMIT 1",one=True):
        rows=core.q("SELECT id,email FROM users WHERE role='admin' AND lower(email)=?",(owner_email,))
        for row in rows:
            changed=d.execute("UPDATE users SET role='owner' WHERE id=? AND role='admin' AND lower(email)=?",(row['id'],owner_email))
            if changed.rowcount:audit('account.owner_migrated','user',row['id'],{'from':'admin','to':'owner','via':'configured owner email'})
        d.commit()

def audit(event,entity_type,entity_id,details=None):
    u=core.current_user() if has_request_context() else None
    entry=core.db().execute('INSERT INTO audit_log(actor_id,actor_name,actor_role,event,entity_type,entity_id,details,created_at) VALUES (?,?,?,?,?,?,?,?)',
        (u['id'] if u else None,(u['first_name']+' '+u['last_name']) if u else 'System',u['role'] if u else 'system',event,entity_type,entity_id,json.dumps(details or {},ensure_ascii=False,default=str),now()))
    if entity_type=='order':
        import order_notifications
        order_notifications.capture(entity_id,event,'audit:'+str(entry.lastrowid))

def lock_order(oid):
    d=core.db()
    if not core.mysql_enabled():d.execute('UPDATE orders SET id=id WHERE id=?',(oid,))
    return d.execute('SELECT * FROM orders WHERE id=?'+(' FOR UPDATE' if core.mysql_enabled() else ''),(oid,)).fetchone()

def lock_rider(rid):
    d=core.db()
    if not core.mysql_enabled():d.execute('UPDATE users SET id=id WHERE id=?',(rid,))
    u=d.execute("SELECT * FROM users WHERE id=? AND role='rider'"+(' FOR UPDATE' if core.mysql_enabled() else ''),(rid,)).fetchone()
    if not u:raise ValueError('Choose a valid rider account.')
    return u

def points_delta(uid,delta):
    """Keep available points nonnegative, retaining any unpaid reversal as debt."""
    d=core.db();suffix=' FOR UPDATE' if core.mysql_enabled() else ''
    u=d.execute('SELECT points,reward_debt_points FROM users WHERE id=?'+suffix,(uid,)).fetchone()
    net=u['points']-u['reward_debt_points']+int(delta)
    d.execute('UPDATE users SET points=?,reward_debt_points=? WHERE id=?',(max(0,net),max(0,-net),uid))

def allowed_statuses(o,role):
    return core.Order.from_row(o).next_statuses(role)

def transition_order(oid,next_status,reason=''):
    from services import OrderService
    return OrderService(core.db(),core.mysql_enabled()).transition(oid,next_status,reason)

def assign_rider(oid,rid):
    from services import OrderService
    return OrderService(core.db(),core.mysql_enabled()).assign_rider(oid,rid)

def valid_reason(reason):
    reason=(reason or '').strip()
    if not 5<=len(reason)<=500:raise ValueError('Provide a reason of 5–500 characters.')
    return reason

def cash_outstanding(rid,lock=False):
    return core.q('SELECT id,cash_collected_cents FROM orders WHERE rider_id=? AND cash_collected_cents>0 AND cash_remittance_id IS NULL ORDER BY id'+(' FOR UPDATE' if lock and core.mysql_enabled() else ''),(rid,))

def handover(rid,received,reason,expected,key):
    u=actor('cash_handover');lock_rider(rid)
    old=core.q('SELECT id,rider_id FROM cash_remittances WHERE receipt_key=?',(key,),one=True)
    if old:
        if old['rider_id']!=rid:raise ValueError('Invalid cash receipt key.')
        return old['id']
    rows=cash_outstanding(rid,lock=True);amount=sum(r['cash_collected_cents'] for r in rows)
    if amount<=0:raise ValueError('This rider has no recorded cash to hand over.')
    if amount!=expected:raise ValueError('The cash balance changed. Refresh and count the cash again.')
    received_cents=int(commerce.money(received)*100)
    difference=received_cents-amount
    if difference:reason=valid_reason(reason)
    else:reason=(reason or '').strip()[:500]
    receipt=core.db().execute('INSERT INTO cash_remittances(rider_id,received_by,expected_cents,received_cents,variance_cents,reason,receipt_key,created_at) VALUES (?,?,?,?,?,?,?,?)',
        (rid,u['id'],amount,received_cents,difference,reason,key,now())).lastrowid
    for r in rows:core.db().execute('UPDATE orders SET cash_remittance_id=? WHERE id=? AND cash_remittance_id IS NULL',(receipt,r['id']))
    audit('cash.handover','cash_remittance',receipt,{'rider_id':rid,'order_ids':[r['id'] for r in rows],'expected_cents':amount,'received_cents':received_cents,'variance_cents':difference,'reason':reason})
    return receipt

def void_sale(oid,reason):
    actor('void_sale');reason=valid_reason(reason)
    # Serialize voids for the same member before locking their reward ledger.
    initial=core.q('SELECT user_id FROM orders WHERE id=?',(oid,),one=True)
    if not initial:raise ValueError('Sale not found.')
    if not core.mysql_enabled():core.db().execute('UPDATE users SET id=id WHERE id=?',(initial['user_id'],))
    core.db().execute('SELECT id FROM users WHERE id=?'+(' FOR UPDATE' if core.mysql_enabled() else ''),(initial['user_id'],)).fetchone()
    o=lock_order(oid)
    if not o or o['status']!='delivered' or o['voided_at']:raise ValueError('Only a completed sale can be voided once.')
    d=core.db();reverse=o['points_earned'] if o['points_credited'] else 0
    if o['points_credited'] and o['reward_rate_cents']:
        u=d.execute('SELECT reward_carry_cents,reward_opening_carry_cents FROM users WHERE id=?'+(' FOR UPDATE' if core.mysql_enabled() else ''),(o['user_id'],)).fetchone()
        ledger=d.execute('SELECT * FROM orders WHERE user_id=? AND reward_sequence IS NOT NULL ORDER BY reward_sequence'+(' FOR UPDATE' if core.mysql_enabled() else ''),(o['user_id'],)).fetchall()
        carry=u['reward_opening_carry_cents'] if u['reward_opening_carry_cents'] is not None else u['reward_carry_cents']
        old_total=sum(r['reward_effective_points'] or 0 for r in ledger);new_total=0
        if o['reward_sequence'] is None:
            # Legacy completions have no reliable completion sequence. Remove their
            # recorded contribution from the carried opening balance, retaining original awards.
            contribution=o['reward_earn_cents']-o['points_earned']*o['reward_rate_cents']
            correction,carry=divmod(carry-contribution,o['reward_rate_cents']);reverse-=correction
            if u['reward_opening_carry_cents'] is not None:d.execute('UPDATE users SET reward_opening_carry_cents=? WHERE id=?',(carry,o['user_id']))
        else:reverse=0
        for r in ledger:
            earned=0
            if r['id']!=oid and not r['voided_at']:
                earned,carry=divmod(carry+r['reward_earn_cents'],r['reward_rate_cents'])
            d.execute('UPDATE orders SET reward_effective_points=? WHERE id=?',(earned,r['id']));new_total+=earned
        reverse+=old_total-new_total
        d.execute('UPDATE users SET reward_carry_cents=? WHERE id=?',(carry,o['user_id']))
    points_delta(o['user_id'],o['points_used']-reverse)
    pay='refund_required' if o['payment_status']=='paid' and commerce.money(o['total'])>0 else o['payment_status']
    d.execute('UPDATE orders SET status=\'cancelled\',voided_at=?,voided_by=?,void_reason=?,payment_status=?,points_reversed=1 WHERE id=?',(now(),core.current_user()['id'],reason,pay,oid))
    audit('sale.voided','order',oid,{'reason':reason,'points_returned':o['points_used'],'points_reversed':reverse,'refund_required':pay=='refund_required','total':str(o['total'])})

def record_refund(oid,method,reference,reason):
    actor('record_refund');o=lock_order(oid);reason=valid_reason(reason)
    if not o or o['payment_status']!='refund_required' or o['refunded_at']:raise ValueError('This order does not have an outstanding refund.')
    if method not in ('cash','gcash','bank'):raise ValueError('Choose the actual refund method.')
    reference=(reference or '').strip()
    if not 5<=len(reference)<=150:raise ValueError('Enter a refund transaction reference or signed cash receipt ID (5–150 characters).')
    core.db().execute("UPDATE orders SET payment_status='refunded',refund_method=?,refund_reference=?,refunded_at=?,refunded_by=? WHERE id=?",(method,reference,now(),core.current_user()['id'],oid))
    audit('payment.refunded','order',oid,{'method':method,'reference':reference,'amount':str(o['total']),'reason':reason})

def cash_summary():
    return core.q("""SELECT u.id,CONCAT(u.first_name,' ',u.last_name) name,
        COALESCE(SUM(CASE WHEN o.cash_remittance_id IS NULL THEN o.cash_collected_cents ELSE 0 END),0) expected_cents
        FROM users u LEFT JOIN orders o ON o.rider_id=u.id WHERE u.role='rider'
        GROUP BY u.id,u.first_name,u.last_name ORDER BY u.first_name""")

def handover_history(limit=100,rider_id=None):
    where='WHERE c.rider_id=?' if rider_id else ''
    return core.q(f'''SELECT c.*,CONCAT(r.first_name,' ',r.last_name) rider_name,
        CONCAT(s.first_name,' ',s.last_name) staff_name FROM cash_remittances c
        JOIN users r ON r.id=c.rider_id JOIN users s ON s.id=c.received_by {where}
        ORDER BY c.id DESC LIMIT ?''',((rider_id,limit) if rider_id else (limit,)))
