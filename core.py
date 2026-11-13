"""Shared helpers: database, rules, login checks, email. Used by every part of the site."""
import os, re, math, sqlite3, secrets, hashlib, smtplib, random
from datetime import datetime, timedelta, date
from email.message import EmailMessage
from functools import wraps
from flask import g, session, redirect, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
import config
from service_area import DELIVERY_BARANGAYS, DELIVERY_COVERAGE, DELIVERY_RADII_KM, address_allowed, pin_allowed

# Compatibility for older app.py/templates: use the current primary service area.
# Actual Bay municipality coverage remains DELIVERY_COVERAGE['Bay'].
BAY_BARANGAYS = DELIVERY_BARANGAYS

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, 'suji.db')
UPLOAD_DIR = os.path.join(BASE, 'static', 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Shared entity names remain import-compatible; rules live in domain.py.
from domain import User, Product, Order, Booking, ORDER_FLOWS, business_today

# ---------------- store, categories, order statuses ----------------
STORE = dict(name=getattr(config, 'STORE_NAME', 'Suji Cafe'),
             address=getattr(config, 'STORE_ADDRESS', 'Suji Cafe store (set STORE_ADDRESS in config.py)'),
             lat=float(getattr(config, 'STORE_LAT', 14.1667)), lng=float(getattr(config, 'STORE_LNG', 121.2333)),
             google_place_id=config.GOOGLE_MAPS_PLACE_ID, maps_embed_url=config.GOOGLE_MAPS_EMBED_URL, radius=float(getattr(config, 'DELIVERY_RADIUS_KM', 8)), pin_verified=getattr(config,'STORE_COORDINATES_VERIFIED',False))
CATEGORIES = [('drink', 'Drinks'), ('food', 'Food'), ('merchandise', 'Merchandise'), ('diy_cake', 'Cake Painting Workshop')]
CAT_LABEL = dict(CATEGORIES)
CAT_ICON = {'drink': 'bi-cup-straw', 'food': 'bi-egg-fried', 'merchandise': 'bi-bag-heart', 'diy_cake': 'bi-palette'}
TYPE_INFO = {'delivery': ('bi-bicycle', 'Delivery'), 'dinein': ('bi-cup-hot', 'Dine-in'),
             'pickup': ('bi-shop', 'Pick-up'), 'instore': ('bi-receipt', 'In-store')}
ORDER_STATUS = ['pending', 'preparing', 'ready', 'picked_up', 'out_for_delivery', 'delivered', 'cancelled']
_ST = {'pending': 'Placed', 'preparing': 'Preparing', 'ready': 'Ready for rider', 'picked_up': 'Picked up by rider', 'out_for_delivery': 'On the way',
       'delivered': 'Delivered', 'cancelled': 'Cancelled'}
STATUS_LABELS = {'delivery': _ST,
                 'dinein': {**_ST, 'ready': 'Ready to serve', 'out_for_delivery': 'Ready to serve', 'delivered': 'Completed'},
                 'pickup': {**_ST, 'ready': 'Ready for pick-up', 'delivered': 'Picked up'},
                 'instore': {**_ST, 'delivered': 'Completed'}}
FLOWS = {kind:list(path) for kind,path in ORDER_FLOWS.items()}

def status_label(t, s): return STATUS_LABELS.get(t, _ST).get(s, s)
def flow(t): return FLOWS.get(t, FLOWS['delivery'])
def flow_idx(t, s):
    fl = flow(t); return fl.index(s) if s in fl else -1
def points_text(o):
    if o['voided_at']: return 'Voided; reward adjustments recorded'
    if o['status'] == 'cancelled': return 'Cancelled, no points'
    if o['payment_method']=='points':return f"{o['points_used']} points used · "+('Reward collected' if o['status']=='delivered' else 'Collect at the café')
    if o['points_credited'] and o['points_earned']: return f"+{o['points_earned']} points earned"
    if o['order_type']!='dinein':return 'This order type does not earn points'
    if o['points_credited']:return 'No new points; eligible dine-in spending carries over'
    when = {'dinein': 'completed', 'pickup': 'picked up'}.get(o['order_type'], 'delivered')
    return f'Points after {when}; eligible spending carries over'


# Official Suji Street Cafe menu supplied by the owner (prices in PHP).
# These are inserted idempotently during migration; existing products and order history stay intact.
FACEBOOK_PAGE_URL = "https://www.facebook.com/sujistreetcafe/"
MENU_CATALOG = [
    # Asian signature plates
    ("Chicken Teriyaki", "food", "Soy sauce, ginger and sesame.", 150),
    ("Honey Garlic Butter Chicken", "food", "Honey and garlic butter sauce.", 150),
    ("Orange Spice Chicken", "food", "Ginger, garlic and onion.", 150),
    ("Grilled Liempo", "food", "Pan-grilled pork belly.", 160),
    ("Pork Teriyaki", "food", "Sukiyaki pork, soy sauce, ginger and sesame.", 160),
    ("Pork Kare-Kare", "food", "Pork belly, pechay, pole beans, shrimp paste and peanuts.", 170),
    ("Burger Steak", "food", "Beef patty in mushroom gravy sauce.", 180),
    ("Garlic Pepper Beef", "food", "Soy sauce, garlic, black pepper and butter.", 180),
    ("Beef Tapa w/ Egg", "food", "Homemade marinated beef, soy sauce and egg.", 180),
    ("Beef Gyudon", "food", "Sukiyaki beef, soy sauce, ginger and egg.", 180),
    ("Beef & Broccoli", "food", "Beef sirloin, soy sauce, oyster sauce and garlic.", 190),
    # Pasta selection
    ("Garlic Aglio Olio", "food", "Garlic, olive oil and parsley.", 150),
    ("Creamy Pesto", "food", "Cream, Parmesan, basil and olive oil.", 150),
    ("Pesto Sardines", "food", "Sardines, basil and olive oil.", 160),
    ("Creamy Carbonara", "food", "Cream, ham and mushroom.", 170),
    ("Asian-style Chicken", "food", "Kung pao chicken, shiitake mushroom and peanuts.", 180),
    ("Baked Macaroni", "food", "Pork, carrots, bell pepper and bechamel.", 190),
    ("Beef Lasagna", "food", "Beef, bell pepper, mushroom and bechamel.", 210),
    # Espresso classics
    ("Americano", "drink", "Espresso-based classic coffee.", 100),
    ("Latte", "drink", "Espresso with milk.", 120),
    ("Spanish Latte", "drink", "Espresso-based Spanish latte.", 150),
    ("Orange Black", "drink", "Refreshing orange and black coffee.", 150),
    ("Dark Mocha", "drink", "Espresso and dark chocolate.", 160),
    ("White Mocha", "drink", "Espresso and white chocolate.", 160),
    ("Salted Ube Latte", "drink", "Ube latte with a salted finish.", 170),
    # Premium cold brew
    ("Oat Velvet", "drink", "Premium cold brew with oat.", 160),
    ("Roasted Almond", "drink", "Premium cold brew; oat milk-based.", 180),
    ("Vanilla Creme", "drink", "Premium cold brew; oat milk-based.", 180),
    # Non-coffee
    ("Orange Juice", "drink", "Orange juice.", 130),
    ("Blueberry Soda", "drink", "Blueberry-flavored soda.", 130),
    ("Dark Chocolate", "drink", "Rich dark chocolate drink.", 150),
    ("Dark Choco Peppermint", "drink", "Dark chocolate with peppermint.", 160),
    ("Strawberry Latte", "drink", "Strawberry milk latte.", 160),
    ("Suji Sunset", "drink", "Suji signature non-coffee drink.", 170),
    # Frappe / ice blended
    ("Dark Chocolate Frappe", "drink", "Dark chocolate ice-blended drink.", 160),
    ("Strawberry Creme Frappe", "drink", "Strawberry creme ice-blended drink.", 170),
    ("Vanilla Creme Frappe", "drink", "Vanilla creme ice-blended drink.", 170),
    ("Ube Cinnamon Frappe", "drink", "Ube and cinnamon ice-blended drink.", 170),
    ("Matcha Creme Frappe", "drink", "Matcha creme ice-blended drink.", 180),
    # Dulce latte series
    ("Cinnamon Dulce", "drink", "Caramelized Spanish latte; espresso-based.", 160),
    ("Dulce Hazelnut", "drink", "Caramelized Spanish latte with hazelnut.", 160),
    ("Dulce Peppermint", "drink", "Caramelized Spanish latte with peppermint.", 160),
    ("Classic Dulce", "drink", "Caramelized Spanish latte; oat milk-based.", 170),
    ("Chili Oat Dulce", "drink", "Caramelized Spanish latte with chili; oat milk-based.", 170),
    ("Vanilla Dulce", "drink", "Caramelized Spanish latte; oat milk-based.", 180),
    # Suji matcha series
    ("Matcha Flan", "drink", "Suji matcha series.", 150),
    ("Matcha Latte", "drink", "Matcha latte.", 160),
    ("Ube Matcha", "drink", "Ube and matcha.", 170),
    ("Dark Matcha", "drink", "Dark matcha drink.", 170),
    ("White Matcha", "drink", "White matcha drink.", 170),
    ("Matcha Hazelnut", "drink", "Matcha with hazelnut.", 170),
    ("Strawberry Matcha", "drink", "Strawberry and matcha.", 180),
    ("Matcha Espresso", "drink", "Matcha with espresso.", 180),
]

def seed_menu_catalog(connection, mysql=False):
    """Add supplied menu entries once without duplicating existing products."""
    for name, category, description, price in MENU_CATALOG:
        if mysql:
            connection.execute("SELECT id FROM products WHERE LOWER(name)=LOWER(%s) LIMIT 1", (name,))
            exists = connection.fetchone()
            if not exists:
                connection.execute("INSERT INTO products (name,category,description,price) VALUES (%s,%s,%s,%s)",
                                   (name, category, description, price))
        else:
            exists = connection.execute("SELECT id FROM products WHERE LOWER(name)=LOWER(?) LIMIT 1", (name,)).fetchone()
            if not exists:
                connection.execute("INSERT INTO products (name,category,description,price) VALUES (?,?,?,?)",
                                   (name, category, description, price))


# ---------------- database ----------------
class MySQLConnection:
    """Small compatibility wrapper so existing parameterized queries work with MySQL."""
    def __init__(self, connection):
        self.connection = connection
    def execute(self, sql, args=()):
        # SQLite's || operator is converted in the few application queries that use it.
        sql = sql.replace('?', '%s')
        cur = self.connection.cursor()
        cur.execute(sql, args)
        return cur
    def commit(self): self.connection.commit()
    def rollback(self): self.connection.rollback()
    def close(self): self.connection.close()

def mysql_enabled():
    return getattr(config, 'DB_BACKEND', 'sqlite') == 'mysql'

def split_sql_script(script):
    buffer=''
    for char in script:
        buffer+=char
        if char==';' and sqlite3.complete_statement(buffer):
            yield buffer
            buffer=''
    tail='\n'.join(line for line in buffer.splitlines() if not line.lstrip().startswith('--')).strip()
    if tail:raise ValueError('SQL setup file contains an incomplete statement.')

def mysql_connection_options():
    import pymysql
    options=dict(host=config.MYSQL_HOST,port=config.MYSQL_PORT,user=config.MYSQL_USER,
        password=config.MYSQL_PASSWORD,database=config.MYSQL_DATABASE,charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,autocommit=False,init_command="SET time_zone = '+00:00'",
        connect_timeout=10,read_timeout=30,write_timeout=30)
    if config.MYSQL_SSL_CA:
        from pathlib import Path
        if not Path(config.MYSQL_SSL_CA).is_file():raise ValueError('MYSQL_SSL_CA must point to a readable trusted CA file.')
        options.update(ssl_ca=config.MYSQL_SSL_CA,ssl_verify_cert=True,ssl_verify_identity=True)
    return options

def init_db():
    if mysql_enabled():
        import pymysql
        c = pymysql.connect(**mysql_connection_options())
        with c.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM information_schema.tables WHERE table_schema=%s AND table_name='users'",
                        (config.MYSQL_DATABASE,))
            exists = cur.fetchone()['n']
        if not exists:
            from pathlib import Path
            script = Path(BASE,'schema.mysql.sql').read_text(encoding='utf-8')
            with c.cursor() as cur:
                for statement in split_sql_script(script):
                    if statement.strip(): cur.execute(statement)
            c.commit()
        c.close()
        return
    if not os.path.exists(DB):
        c = sqlite3.connect(DB)
        from pathlib import Path
        c.executescript(Path(BASE,'schema.sql').read_text(encoding='utf-8'))
        c.commit(); c.close()

def migrate():
    if mysql_enabled():
        import pymysql
        raw = pymysql.connect(**mysql_connection_options())
        try:
            with raw.cursor() as cur:
                cur.execute("""CREATE TABLE IF NOT EXISTS saved_addresses (
                    id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, label VARCHAR(40) NOT NULL DEFAULT 'Home',
                    full_address TEXT NOT NULL, region VARCHAR(100), province VARCHAR(100), city VARCHAR(100),
                    barangay VARCHAR(100), street VARCHAR(255), lat DOUBLE NULL, lng DOUBLE NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
                columns = {
                    'users': {'failed_logins': "INT NOT NULL DEFAULT 0", 'locked_until': "VARCHAR(40) NULL"},
                    'trusted_devices': {'session_hash': 'VARCHAR(64) NULL','last_seen_at': "VARCHAR(40) NULL", 'expires_at': "VARCHAR(40) NULL"},
                    'otp_codes': {'purpose': "VARCHAR(20) NOT NULL DEFAULT 'login'"},
                    'products': {'image': "VARCHAR(255) NULL"},
                    'orders': {'order_type': "VARCHAR(20) NOT NULL DEFAULT 'delivery'", 'lat': "DOUBLE NULL",
                               'lng': "DOUBLE NULL", 'pickup_time': "VARCHAR(30) NULL", 'rider_id': "INT NULL"}
                }
                for table, cols in columns.items():
                    cur.execute("SELECT COLUMN_NAME FROM information_schema.columns WHERE table_schema=%s AND table_name=%s",
                                (config.MYSQL_DATABASE, table))
                    existing = {r['COLUMN_NAME'] for r in cur.fetchall()}
                    for col, ddl in cols.items():
                        if col not in existing: cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
            raw.commit()
        finally:
            raw.close()
        return
    c = sqlite3.connect(DB)
    def add(t, col, ddl):
        if col not in [r[1] for r in c.execute(f'PRAGMA table_info({t})')]:
            c.execute(f'ALTER TABLE {t} ADD COLUMN {col} {ddl}')
    add('otp_codes', 'purpose', "TEXT NOT NULL DEFAULT 'login'")
    add('products', 'image', 'TEXT')
    add('users', 'failed_logins', 'INTEGER NOT NULL DEFAULT 0')
    add('users', 'locked_until', 'TEXT')
    add('orders', 'order_type', "TEXT NOT NULL DEFAULT 'delivery'")
    add('orders', 'lat', 'REAL'); add('orders', 'lng', 'REAL'); add('orders', 'pickup_time', 'TEXT')
    add('orders', 'rider_id', 'INTEGER')
    add('trusted_devices','session_hash','VARCHAR(64) NULL')
    add('trusted_devices', 'last_seen_at', 'TEXT'); add('trusted_devices', 'expires_at', 'TEXT')
    c.execute("""CREATE TABLE IF NOT EXISTS saved_addresses (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        label TEXT NOT NULL DEFAULT 'Home', full_address TEXT NOT NULL, region TEXT, province TEXT,
        city TEXT, barangay TEXT, street TEXT, lat REAL, lng REAL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""UPDATE products SET name='Cake Painting Workshop (per person)',
                 description='Paint and decorate your own cake in a guided session. Cakes, paints and tools included.'
                 WHERE category='diy_cake' AND name LIKE 'DIY Cake Kit%'""")
    c.commit(); c.close()

def db():
    if 'db' not in g:
        if mysql_enabled():
            import pymysql
            conn = pymysql.connect(**mysql_connection_options())
            g.db = MySQLConnection(conn)
        else:
            g.db = sqlite3.connect(DB); g.db.row_factory = sqlite3.Row
            g.db.create_function('CONCAT', -1, lambda *parts: ''.join('' if v is None else str(v) for v in parts))
            g.db.execute('PRAGMA foreign_keys=ON')
    return g.db

def close_db(error=None):
    conn = g.pop('db', None)
    if conn is not None:
        conn.close()

def q(sql, args=(), one=False):
    rows = db().execute(sql, args).fetchall()
    return (rows[0] if rows else None) if one else rows

def run(sql, args=()):
    cur = db().execute(sql, args); db().commit(); return cur.lastrowid

def to_int(v, default=0):
    try: return int(v)
    except (TypeError, ValueError): return default

def sha(s): return hashlib.sha256(s.encode()).hexdigest()

def km(lat1, lng1, lat2, lng2):
    p = math.pi / 180
    a = 0.5 - math.cos((lat2 - lat1) * p) / 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lng2 - lng1) * p)) / 2
    return 12742 * math.asin(math.sqrt(a))

# ---------------- input rules (email, phone, names, password) ----------------
EMAIL = re.compile(r"^(?!\.)(?!.*\.\.)[A-Za-z0-9._%+-]{1,64}(?<!\.)@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
                   r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.[A-Za-z]{2,}$")
GMAIL = EMAIL        # old name, still used by the admin page
NAME = re.compile(r"^[A-Za-zÑñ][A-Za-zÑñ .'-]{1,49}$")
PW = re.compile(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{8,}$')
EMAIL_SQL = "REPLACE(SUBSTR(email,1,INSTR(email,'@')-1),'.','')=?"

def user_by_email(e):
    """Find an account by email. Gmail ignores dots (juan.cruz = juancruz), so Gmail is compared without them."""
    e = (e or '').strip().lower()
    if '@' not in e: return None
    if e.endswith('@gmail.com'):
        return q(f"SELECT * FROM users WHERE {EMAIL_SQL} AND lower(email) LIKE ?",
                 (e.split('@')[0].replace('.', ''), '%@gmail.com'), one=True)
    return q('SELECT * FROM users WHERE lower(email)=?', (e,), one=True)

def phone_error(p):
    if not re.match(r'^09\d{9}$', p): return 'Phone must be 11 digits starting with 09.'
    if re.search(r'(\d)\1{4}', p): return "Phone number can't repeat the same digit 5 times in a row (like 11111)."

def validate(f):
    e = []
    if not NAME.match(f['first_name']): e.append('First name must be 2–50 letters only.')
    if f['middle_name'] and not NAME.match(f['middle_name']): e.append('Middle name must contain letters only.')
    if not NAME.match(f['last_name']): e.append('Last name must be 2–50 letters only.')
    if len(f['email']) > 254 or not EMAIL.fullmatch(f['email']): e.append('Enter a valid email address, e.g. juan.cruz@example.com.')
    if phone_error(f['phone']): e.append(phone_error(f['phone']))
    if f['birthdate']:                                   # birthdate is optional, but if given it must make sense
        try:
            b = datetime.strptime(f['birthdate'], '%Y-%m-%d').date(); t = business_today()
            age = t.year - b.year - ((t.month, t.day) < (b.month, b.day))
            if not 13 <= age <= 110: raise ValueError
        except ValueError: e.append('You must be at least 13 years old.')
    if f['address'] and len(f['address']) < 10: e.append('Your address looks incomplete. Complete it or leave it empty.')
    if not 8<=len(f['password'])<=128 or not PW.fullmatch(f['password']): e.append('Password needs 8+ chars with upper, lower, number and symbol.')
    if f['password'] != f['confirm']: e.append('Passwords do not match.')
    if not f['terms']: e.append('Please accept the terms.')
    return e

# ---------------- delivery address: every part is required ----------------
ADDR_PART = re.compile(r"^[\w .,'’#/()&-]+$", re.UNICODE)
ADDR_FIELDS = [('region', 'Region', 2), ('province', 'Province', 2), ('city', 'City / Municipality', 2),
               ('barangay', 'Barangay', 2), ('street', 'House no. and street', 3)]

def delivery_address(form):
    """Checks Region, Province, City/Municipality, Barangay and House/Street. Returns (errors, one-line address)."""
    errs, v = [], {}
    for key, label, mn in ADDR_FIELDS:
        v[key] = ' '.join(form.get(key, '').split())
        if not v[key]: errs.append(f'{label} is required for delivery.')
        elif len(v[key]) < mn or len(v[key]) > 100 or not ADDR_PART.match(v[key]): errs.append(f'{label} is not valid.')
    if not address_allowed(v): errs.append('Choose a supported municipality and barangay: Los Baños, selected Bay areas, or Pansol in Calamba.')
    if errs: return errs, ''
    b = v['barangay'] if re.match(r'(?i)^(brgy|barangay)', v['barangay']) else 'Brgy. ' + v['barangay']
    return [], ', '.join([v['street'], b, v['city'], v['province'], v['region']])

# ---------------- who is logged in ----------------
def current_user():
    if 'u' not in g:
        g.u = q('SELECT * FROM users WHERE id=?', (session['uid'],), one=True) if session.get('uid') else None
        if g.u:
            import employee_invitations
            if not employee_invitations.is_active(g.u['id']):
                g.u = None
                session.pop('uid', None)
    return g.u

def home_for(u):
    """Each role has its own area: /customer, /admin, /rider."""
    return url_for({'owner':'owner.dashboard', 'admin': 'admin.dashboard', 'staff': 'staff.dashboard', 'rider': 'rider.dashboard'}.get(u['role'], 'customer.dashboard'))

def login_required(role=None):
    def deco(f):
        @wraps(f)
        def wrapper(*a, **k):
            u = current_user()
            if not u: return redirect(url_for('auth.login'))
            import ops
            if role and not User.from_row(u).can_access(role): return redirect(home_for(u))
            return f(*a, **k)
        return wrapper
    return deco

def cart_totals():
    c = session.get('cart', {})
    if not c: return 0, 0.0
    ids = [to_int(i) for i in c]
    rows = q(f"SELECT id,price FROM products WHERE id IN ({','.join('?' * len(ids))})", ids)
    return sum(c.values()), sum(r['price'] * c[str(r['id'])] for r in rows)

# ---------------- orders and points ----------------
def complete_order(d, oid):
    """Complete only payable orders, and credit earnings once."""
    import ops
    o = ops.lock_order(oid)
    if not o or not Order.from_row(o).can_finalize(): return False
    d.execute("UPDATE orders SET status='delivered',payment_status='paid',paid_at=COALESCE(paid_at,?),updated_at=?,delivered_at=COALESCE(delivered_at,?) WHERE id=? AND status<>'cancelled'", (__import__('ops').now(),__import__('ops').now(),__import__('ops').now(),oid))
    state=d.execute('SELECT status FROM orders WHERE id=?'+(' FOR UPDATE' if mysql_enabled() else ''),(oid,)).fetchone()
    if state['status']!='delivered':return False
    __import__('delivery_tracking').clear(oid)
    credited=d.execute("UPDATE orders SET points_credited=1 WHERE id=? AND points_credited=0 AND status='delivered'", (oid,))
    if credited.rowcount:
        member=d.execute('SELECT role FROM users WHERE id=?',(o['user_id'],)).fetchone()
        if o['order_type']!='dinein' or not member or member['role']!='customer':
            # Apply the current policy to pending orders too; keep completed history intact.
            d.execute('UPDATE orders SET points_earned=0,reward_earn_cents=0,reward_rate_cents=NULL WHERE id=?',(oid,))
        elif o['reward_rate_cents']:
            # Serialize each customer's carry update on MySQL. SQLite's write
            # transaction already serializes this after claiming the order.
            suffix=' FOR UPDATE' if mysql_enabled() else ''
            customer=d.execute('SELECT reward_carry_cents,reward_opening_carry_cents,reward_next_sequence FROM users WHERE id=?'+suffix,(o['user_id'],)).fetchone()
            if customer['reward_opening_carry_cents'] is None:
                d.execute('UPDATE users SET reward_opening_carry_cents=? WHERE id=?',(customer['reward_carry_cents'],o['user_id']))
            sequence=customer['reward_next_sequence']+1
            earned,carry=divmod(customer['reward_carry_cents']+o['reward_earn_cents'],o['reward_rate_cents'])
            ops.points_delta(o['user_id'],earned)
            d.execute('UPDATE users SET reward_carry_cents=?,reward_next_sequence=? WHERE id=?',(carry,sequence,o['user_id']))
            d.execute('UPDATE orders SET points_earned=?,reward_carry_delta_cents=?,reward_sequence=?,reward_effective_points=? WHERE id=?',(earned,carry-customer['reward_carry_cents'],sequence,earned,oid))
        else:
            # Preserve previously promised earnings for legacy orders.
            ops.points_delta(o['user_id'],o['points_earned'])
    return True

def cancel_order(d, o):
    """Return redeemed points once. Real paid transfers need a staff refund."""
    import ops
    if o['status'] in ('cancelled','delivered'):return False
    changed=d.execute("UPDATE orders SET status='cancelled',updated_at=?,cancelled_at=?,payment_status=CASE WHEN payment_status='paid' AND total>0 THEN 'refund_required' ELSE payment_status END WHERE id=? AND status=? AND voided_at IS NULL", (__import__('ops').now(),__import__('ops').now(),o['id'],o['status']))
    if changed.rowcount:
        __import__('delivery_tracking').clear(o['id'])
        if o['points_used']:ops.points_delta(o['user_id'],o['points_used'])
        ops.audit('order.cancelled','order',o['id'],{'from':o['status'],'points_returned':o['points_used']})
    return bool(changed.rowcount)

# ---------------- email codes ----------------
def send_code(to,name,code,reason):
    from email_service import EmailService
    EmailService(config).send_code(to,name,code,reason)

def issue_code(u, purpose, reason):
    """Bound code sends, reuse the last minute's code, and roll back mail failures."""
    import security
    allowed,_=security.consume('otp-send',str(u['id'])+':'+purpose,5,600)
    if not allowed:return False
    d=db()
    try:
        if mysql_enabled():d.execute('SELECT id FROM users WHERE id=? FOR UPDATE',(u['id'],)).fetchone()
        else:d.execute('UPDATE users SET id=id WHERE id=?',(u['id'],))
        previous=d.execute('SELECT * FROM otp_codes WHERE user_id=? AND purpose=? ORDER BY id DESC LIMIT 1',(u['id'],purpose)).fetchone()
        if previous and datetime.fromisoformat(previous['expires_at'])>datetime.now():
            if previous['attempts']>=5:d.rollback();return False
            if datetime.fromisoformat(previous['expires_at'])>datetime.now()+timedelta(minutes=9):
                d.rollback();return True
        code=str(secrets.randbelow(900000)+100000)
        d.execute('DELETE FROM otp_codes WHERE user_id=? AND purpose=?',(u['id'],purpose))
        d.execute('INSERT INTO otp_codes(user_id,code_hash,expires_at,purpose) VALUES (?,?,?,?)',(u['id'],generate_password_hash(code),(datetime.now()+timedelta(minutes=10)).isoformat(),purpose))
        try:send_code(u['email'],u['first_name'],code,reason)
        except Exception:
            if not config.DEV_PRINT_OTP:raise
            print(f'[DEV] {purpose} verification code: {code}')
            flash('Development only: email failed; the code is in your local terminal.','warning')
        d.commit();return True
    except Exception:
        d.rollback();return False

def check_code(uid,purpose,code):
    """Count attempts atomically and consume a successful proof exactly once."""
    row=q('SELECT * FROM otp_codes WHERE user_id=? AND purpose=? ORDER BY id DESC LIMIT 1',(uid,purpose),one=True)
    invalid='Code expired or too many attempts. Please start again.'
    if not row:return False,invalid
    now=datetime.now().isoformat()
    changed=db().execute('UPDATE otp_codes SET attempts=attempts+1 WHERE id=? AND code_hash=? AND attempts<5 AND expires_at>?',(row['id'],row['code_hash'],now));db().commit()
    if not changed.rowcount:return False,invalid
    if not re.fullmatch(r'[0-9]{6}',str(code).strip()) or not check_password_hash(row['code_hash'],str(code).strip()):return False,'Wrong code. Check your email and try again.'
    consumed=db().execute('DELETE FROM otp_codes WHERE id=? AND code_hash=? AND attempts<=5 AND expires_at>?',(row['id'],row['code_hash'],datetime.now().isoformat()));db().commit()
    return (True,'') if consumed.rowcount else (False,invalid)

def save_image(file):
    # Compatibility entrypoint: every caller must use verified image decoding.
    from commerce import save_verified_image
    return save_verified_image(file)
