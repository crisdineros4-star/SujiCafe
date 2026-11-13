"""Latest GPS fix only. Customers see their own active delivery's assigned rider."""
import math,time,secrets,hmac
import core
ACTIVE=('picked_up','out_for_delivery')
FRESH_SECONDS=60
DDL='''CREATE TABLE IF NOT EXISTS order_rider_locations (
order_id INTEGER PRIMARY KEY, rider_id INTEGER NOT NULL,
lat DOUBLE NOT NULL, lng DOUBLE NOT NULL, accuracy DOUBLE NOT NULL,
observed_at DOUBLE NOT NULL, received_at DOUBLE NOT NULL)'''
SESSION_DDL="""CREATE TABLE IF NOT EXISTS rider_location_sessions (
rider_id INTEGER PRIMARY KEY, token_hash VARCHAR(64) NOT NULL, started_at DOUBLE NOT NULL)"""
def initialize():
    core.db().execute(DDL);core.db().execute(SESSION_DDL)
def start(rider_id):
    import ops
    ops.lock_rider(rider_id)
    if not core.q("SELECT id FROM orders WHERE rider_id=? AND order_type='delivery' AND status IN ('picked_up','out_for_delivery')",(rider_id,),one=True):raise ValueError('Pick up an assigned delivery before sharing.')
    token=secrets.token_hex(32)
    core.db().execute('DELETE FROM rider_location_sessions WHERE rider_id=?',(rider_id,))
    core.db().execute('DELETE FROM order_rider_locations WHERE rider_id=?',(rider_id,))
    core.db().execute('INSERT INTO rider_location_sessions(rider_id,token_hash,started_at) VALUES (?,?,?)',(rider_id,core.sha(token),time.time()))
    return token
def session_matches(rider_id,token):
    if not isinstance(token,str) or len(token)!=64:return False
    row=core.q('SELECT token_hash FROM rider_location_sessions WHERE rider_id=?',(rider_id,),one=True)
    return bool(row and hmac.compare_digest(row['token_hash'],core.sha(token)))
def stop(rider_id,token):
    import ops
    ops.lock_rider(rider_id)
    if session_matches(rider_id,token):
        core.db().execute('DELETE FROM order_rider_locations WHERE rider_id=?',(rider_id,))
        core.db().execute('DELETE FROM rider_location_sessions WHERE rider_id=?',(rider_id,))
def clear(order_id):core.db().execute('DELETE FROM order_rider_locations WHERE order_id=?',(order_id,))
def save(rider_id,values):
    import ops
    ops.lock_rider(rider_id)
    if not session_matches(rider_id,values.get('sharing_token')):return dict(ok=False,msg='Location sharing ended. Start sharing again if needed.'),403
    order=ops.lock_order(core.to_int(values.get('order_id')))
    if not order or order['rider_id']!=rider_id or order['order_type']!='delivery':return dict(ok=False,msg='This delivery is not assigned to you.'),403
    if order['status'] not in ACTIVE:return dict(ok=False,msg='Location sharing is available only after pickup and before delivery.'),409
    try:
        lat,lng,accuracy,observed=[float(values.get(k,'')) for k in ('lat','lng','accuracy','captured_at')]
        now=time.time()
        if not all(math.isfinite(v) for v in (lat,lng,accuracy,observed)) or not (-90<=lat<=90 and -180<=lng<=180):raise ValueError
        if not 0<=accuracy<=1000:return dict(ok=False,msg='GPS accuracy is too low. Wait for a stronger location signal.'),400
        if not -10<=now-observed<=30:return dict(ok=False,msg='The GPS fix is old. Get a fresh location and check your phone clock.'),400
    except (ValueError,TypeError):return dict(ok=False,msg='Invalid GPS reading.'),400
    old=core.q('SELECT observed_at,received_at FROM order_rider_locations WHERE order_id=?',(order['id'],),one=True)
    if old and observed<=old['observed_at']:return dict(ok=False,msg='A newer location has already been received.'),409
    if old and now-old['received_at']<3:return dict(ok=False,msg='Wait a few seconds before the next GPS update.'),429
    if old:
        core.db().execute('UPDATE order_rider_locations SET rider_id=?,lat=?,lng=?,accuracy=?,observed_at=?,received_at=? WHERE order_id=?',(rider_id,lat,lng,accuracy,observed,now,order['id']))
    else:core.db().execute('INSERT INTO order_rider_locations(order_id,rider_id,lat,lng,accuracy,observed_at,received_at) VALUES (?,?,?,?,?,?,?)',(order['id'],rider_id,lat,lng,accuracy,observed,now))
    return dict(ok=True,msg='Live location updated.'),200

def snapshot(order):
    if order['order_type']!='delivery':return None
    result=dict(state='waiting_pickup',message='Live rider location will be available after pickup.')
    if order['status'] in ('cancelled','delivered'):return dict(state='complete',message='Live location sharing has ended for this order.')
    if order['status'] not in ACTIVE:return result
    result.update(state='waiting_location',message='The rider is on the way. Waiting for the rider to share a fresh GPS location.')
    if order['rider_observed_at'] is None:return result
    age=time.time()-order['rider_observed_at']
    if not -10<=age<=FRESH_SECONDS:return dict(state='stale',message='Rider GPS updates are paused. The rider may have lost connection or stopped sharing.')
    return dict(state='live',message='Live rider location · GPS is approximate.',lat=order['rider_lat'],lng=order['rider_lng'],accuracy=order['rider_accuracy'],updated_at=order['rider_observed_at'],age_seconds=max(0,age))
