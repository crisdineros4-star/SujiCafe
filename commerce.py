"""Money, item rewards, versioned menu import, and additive database updates."""
import json, math, secrets
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, ROUND_CEILING
from pathlib import Path
import core

BASE = Path(__file__).resolve().parent
CATALOG = json.loads((BASE/'data/menu_catalog.json').read_text())
REWARD_CATEGORIES = ('food', 'drink')

def money(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount > 1000000: raise ValueError('Invalid amount.')
        return amount.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError): raise ValueError('Invalid amount.')

def default_points_cost(price, category):
    """Drinks: about 10% face value; food: up to 8%, rounded to 5 points."""
    price=money(price)
    if category=='drink':return max(1,int((price/10).to_integral_value(rounding=ROUND_CEILING)))
    if category=='food':return max(5,int((price/40).to_integral_value(rounding=ROUND_CEILING))*5)
    return 0

def setting(key, default=''):
    row = core.q('SELECT value FROM commerce_settings WHERE name=?', (key,), one=True)
    return row['value'] if row else default

def set_setting(key, value):
    d = core.db()
    if core.q('SELECT name FROM commerce_settings WHERE name=?', (key,), one=True):
        d.execute('UPDATE commerce_settings SET value=? WHERE name=?', (str(value), key))
    else: d.execute('INSERT INTO commerce_settings(name,value) VALUES (?,?)', (key,str(value)))

def initialize():
    import security
    security.initialize()
    import password_reset,signup_verification
    password_reset.initialize();signup_verification.initialize()
    import owner_recovery
    owner_recovery.initialize()
    import delivery_tracking
    delivery_tracking.initialize()
    d=core.db(); mysql=core.mysql_enabled()
    d.execute('CREATE TABLE IF NOT EXISTS commerce_settings (name VARCHAR(100) PRIMARY KEY, value TEXT NOT NULL)')
    columns={
      'users':{'reward_carry_cents':'INTEGER NOT NULL DEFAULT 0'},
      'products':{'points_cost':'INTEGER NOT NULL DEFAULT 0','menu_section':"VARCHAR(100) NOT NULL DEFAULT ''"},
      'orders':{'reward_earn_cents':'INTEGER NOT NULL DEFAULT 0','reward_rate_cents':'INTEGER NULL','subtotal':'DECIMAL(10,2) NULL','reward_value':'DECIMAL(10,2) NOT NULL DEFAULT 0','reward_product_id':'INTEGER NULL',
                'payment_status':"VARCHAR(30) NOT NULL DEFAULT 'unpaid'",'gcash_reference':'VARCHAR(30) NULL',
                'payment_proof':'VARCHAR(100) NULL','payment_note':"VARCHAR(255) NOT NULL DEFAULT ''",'verified_by':'INTEGER NULL',
                'submitted_at':'VARCHAR(40) NULL','paid_at':'VARCHAR(40) NULL','checkout_key':'VARCHAR(64) NULL','hidden_by_customer':'INTEGER NOT NULL DEFAULT 0'},
      'order_items':{'item_name':'VARCHAR(150) NULL','is_reward':'INTEGER NOT NULL DEFAULT 0'}}
    for table,cols in columns.items():
        if mysql:
            names={r['COLUMN_NAME'] for r in core.q('SELECT COLUMN_NAME FROM information_schema.columns WHERE table_schema=? AND table_name=?',(core.config.MYSQL_DATABASE,table))}
        else: names={r['name'] for r in core.q(f'PRAGMA table_info({table})')}
        for col,ddl in cols.items():
            if col not in names:d.execute(f'ALTER TABLE {table} ADD COLUMN {col} {ddl}')
    for col in ('gcash_reference','checkout_key'):
        name='uq_orders_'+col
        if mysql:
            exists=core.q('SELECT INDEX_NAME FROM information_schema.statistics WHERE table_schema=? AND table_name=? AND index_name=?',(core.config.MYSQL_DATABASE,'orders',name))
        else:exists=[r for r in core.q('PRAGMA index_list(orders)') if r['name']==name]
        if not exists:d.execute(f'CREATE UNIQUE INDEX {name} ON orders({col})')
    d.execute('UPDATE order_items SET item_name=(SELECT name FROM products WHERE products.id=order_items.product_id) WHERE item_name IS NULL')
    if not core.q("SELECT id FROM products WHERE category='diy_cake' LIMIT 1",one=True):
        d.execute("INSERT INTO products(name,category,description,price) VALUES ('Cake Painting Workshop (per person)','diy_cake','Paint and decorate your own cake in a guided session. Cakes, paints and tools included.',650)")
    if not setting('menu_revision'):
        for item in CATALOG['items']:
            row=core.q('SELECT id FROM products WHERE lower(name)=lower(?)',(item['name'],),one=True)
            cost=default_points_cost(item['price'],item['category'])
            image='menu/'+item['image'] if item['image'] else None
            vals=(item['name'],item['category'],item['description'],item['price'],image,item['section'],cost)
            if row:d.execute('UPDATE products SET name=?,category=?,description=?,price=?,image=?,menu_section=?,points_cost=?,is_available=1 WHERE id=?',(*vals,row['id']))
            else:d.execute('INSERT INTO products(name,category,description,price,image,menu_section,points_cost) VALUES (?,?,?,?,?,?,?)',vals)
        # Original template-only entries are archived, preserving their order history.
        for name in ('Ube Latte','Chicken Pesto Panini','Tuna Melt Toastie','Suji Tote Bag','Suji Ceramic Mug'):
            d.execute('UPDATE products SET is_available=0 WHERE name=?',(name,))
        set_setting('menu_revision','photos-and-prices-2026-11')
        set_setting('earn_per_peso','100')
    if setting('rewards_revision')!='food-and-drinks-v1':
        # Apply the requested category policy once, preserving balances/history.
        for row in core.q('SELECT id,price,category FROM products'):
            d.execute('UPDATE products SET points_cost=? WHERE id=?',(default_points_cost(row['price'],row['category']),row['id']))
        set_setting('earn_per_peso','100')
        set_setting('rewards_revision','food-and-drinks-v1')
    if setting('orange_vanilla_revision')!='priced-170-v1':
        item=next(i for i in CATALOG['items'] if i['name']=='Orange Vanilla')
        row=core.q('SELECT id FROM products WHERE lower(name)=lower(?)',(item['name'],),one=True)
        values=(item['name'],item['category'],item['description'],170,'menu/'+item['image'],item['section'],default_points_cost(170,'drink'))
        if row:d.execute('UPDATE products SET name=?,category=?,description=?,price=?,image=?,menu_section=?,points_cost=?,is_available=1 WHERE id=?',(*values,row['id']))
        else:d.execute('INSERT INTO products(name,category,description,price,image,menu_section,points_cost) VALUES (?,?,?,?,?,?,?)',values)
        set_setting('orange_vanilla_revision','priced-170-v1')
    d.commit()
    import ops
    ops.initialize()
    import accounts
    accounts.initialize()
    import employee_invitations
    employee_invitations.initialize()
    import order_notifications
    order_notifications.initialize()

class OrderQuote:
    """Prices come from the database; one basket item may be redeemed per order."""
    def __init__(self, rows, quantities, mode, reward_id=0):
        if not rows:raise ValueError('Your bag is empty.')
        self._lines=[];self._subtotal=Decimal('0');self._reward_value=Decimal('0');self._points_used=0;self._reward_id=reward_id or None
        found=False
        if len(rows)!=len(quantities):raise ValueError('Some items are unavailable. Refresh your bag.')
        for row in rows:
            qty=quantities.get(str(row['id']))
            if isinstance(qty,bool) or not isinstance(qty,int) or not 1<=qty<=20:raise ValueError('Quantity must be 1–20.')
            product=core.Product.from_row(row)
            if not product.is_valid():raise ValueError('An item has invalid product information. Ask Staff.')
            price=product.price;self._subtotal+=price*qty
            reward=reward_id==row['id']
            if reward:
                if not product.can_redeem():raise ValueError('Only food and drinks can be redeemed.')
                found=True;self._reward_value=price;self._points_used=row['points_cost']
            self._lines.append((row,qty,price,reward))
        if reward_id and not found:raise ValueError('Add the reward item to your bag first.')
        self._fee=Decimal('50') if mode=='delivery' and self._subtotal<500 else Decimal('0')
        self._total=self._subtotal-self._reward_value+self._fee
        self._rate_cents=int(money(setting('earn_per_peso','100'))*100)
        if self._rate_cents<=0:raise ValueError('Rewards earning rate must be positive.')
        self._eligible_cents=int((self._subtotal-self._reward_value)*100)
        self._earn_enabled=mode=='dinein'
        self._earn=self._eligible_cents//self._rate_cents if self._earn_enabled else 0

    subtotal=property(lambda self:self._subtotal)
    reward_value=property(lambda self:self._reward_value)
    points_used=property(lambda self:self._points_used)
    reward_id=property(lambda self:self._reward_id)
    fee=property(lambda self:self._fee)
    total=property(lambda self:self._total)
    rate_cents=property(lambda self:self._rate_cents)
    eligible_cents=property(lambda self:self._eligible_cents)
    earn_enabled=property(lambda self:self._earn_enabled)
    earn=property(lambda self:self._earn)
    lines=property(lambda self:tuple(self._lines))

    def disable_earnings(self):
        self._earn_enabled=False;self._earn=0

    def insert(self,user_id,payment,address,mode,lat=None,lng=None,checkout_key=None,paid=False):
        d=core.db()
        if mode!='dinein':self.disable_earnings()
        if self._points_used:
            changed=d.execute('UPDATE users SET points=points-? WHERE id=? AND points>=?',(self._points_used,user_id,self._points_used))
            if not changed.rowcount:raise ValueError('You do not have enough points for this item.')
        oid=d.execute('''INSERT INTO orders(user_id,total,subtotal,delivery_fee,points_used,points_earned,reward_value,reward_product_id,
                          payment_method,payment_status,delivery_address,order_type,lat,lng,checkout_key,reward_earn_cents,reward_rate_cents,qr_token,collection_code)
                          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                          (user_id,str(self._total),str(self._subtotal),str(self._fee),self._points_used,self._earn,str(self._reward_value),self._reward_id,
                           payment,'paid' if paid or self._total==0 else 'unpaid',address,mode,lat,lng,checkout_key,self._eligible_cents if self._earn_enabled else 0,self._rate_cents if self._earn_enabled and self._eligible_cents>0 else None,secrets.token_urlsafe(24),''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(8)))).lastrowid
        for row,qty,price,reward in self._lines:
            if reward:
                d.execute('INSERT INTO order_items(order_id,product_id,qty,price,item_name,is_reward) VALUES (?,?,?,?,?,1)',(oid,row['id'],1,'0.00',row['name']))
                qty-=1
            if qty:d.execute('INSERT INTO order_items(order_id,product_id,qty,price,item_name,is_reward) VALUES (?,?,?,?,?,0)',(oid,row['id'],qty,str(price),row['name']))
        if mode!='instore':
            import order_notifications
            order_notifications.capture(oid,'order.placed','placed:'+str(oid))
        return oid

def receipt_data(oid):
    order=core.q('SELECT * FROM orders WHERE id=?',(oid,),one=True)
    items=core.q('SELECT oi.*,COALESCE(oi.item_name,p.name) name FROM order_items oi JOIN products p ON p.id=oi.product_id WHERE order_id=?',(oid,))
    return order,items

def gcash_ready():return bool(setting('gcash_account') and (setting('gcash_qr') or setting('gcash_number')))

def save_verified_image(upload, private=False):
    """Decode and re-encode uploads; private payment proofs are never static files."""
    from PIL import Image, ImageOps, UnidentifiedImageError
    if not upload or not upload.filename:return None
    raw=upload.stream.read(2*1024*1024+1)
    if len(raw)>2*1024*1024:raise ValueError('Image must be 2 MB or smaller.')
    from io import BytesIO
    try:
        with Image.open(BytesIO(raw)) as image:
            if image.format not in ('JPEG','PNG','WEBP'):raise ValueError('Upload a JPG, PNG or WebP image.')
            if image.width*image.height>20000000:raise ValueError('Image dimensions are too large.')
            image=ImageOps.exif_transpose(image).convert('RGB');image.thumbnail((1800,1800))
            folder=BASE/'private/payments' if private else BASE/'static/uploads'
            folder.mkdir(parents=True,exist_ok=True);name=secrets.token_hex(20)+'.png'
            image.save(folder/name,'PNG')
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError):raise ValueError('Upload a valid JPG, PNG or WebP image.')
    return name


def receipt_ready(order):
    """Confirmed payment, or a later refund record for a previously paid order."""
    return order['payment_status']=='paid' or (order['payment_status'] in ('refund_required','refunded') and bool(order['paid_at']))
