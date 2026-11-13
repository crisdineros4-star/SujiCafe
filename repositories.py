"""Parameterized database access; services own transactions, entities own rules."""
class Repository:
    def __init__(self,connection,mysql=False):self._connection=connection;self._mysql=mysql
    def _rows(self,sql,args=()):return self._connection.execute(sql,args).fetchall()
    def _one(self,sql,args=()):return self._connection.execute(sql,args).fetchone()
    @property
    def _lock_suffix(self):return ' FOR UPDATE' if self._mysql else ''

class OrderRepository(Repository):
    def lock(self,oid):
        if not self._mysql:self._connection.execute('UPDATE orders SET id=id WHERE id=?',(oid,))
        return self._one('SELECT * FROM orders WHERE id=?'+self._lock_suffix,(oid,))
    def change_status(self,oid,status):
        import ops
        fields={'preparing':'accepted_at','ready':'ready_at','delivered':'delivered_at','cancelled':'cancelled_at'}
        column=fields.get(status)
        if column:self._connection.execute(f'UPDATE orders SET status=?,updated_at=?,{column}=COALESCE({column},?) WHERE id=?',(status,ops.now(),ops.now(),oid))
        else:self._connection.execute('UPDATE orders SET status=?,updated_at=? WHERE id=?',(status,ops.now(),oid))
    def rider_exists(self,rid):
        return bool(self._one("""SELECT u.id FROM users u
            LEFT JOIN employee_invitations i ON i.user_id=u.id
            LEFT JOIN account_access a ON a.user_id=u.id
            WHERE u.id=? AND u.role='rider' AND (i.user_id IS NULL OR i.status='active')
            AND a.disabled_at IS NULL"""+self._lock_suffix,(rid,)))
    def assign(self,oid,rid):self._connection.execute("UPDATE orders SET rider_id=? WHERE id=? AND status='ready'",(rid,oid))

class BookingRepository(Repository):
    def get(self,bid):return self._one('SELECT * FROM diy_bookings WHERE id=?'+self._lock_suffix,(bid,))
    def update_status(self,bid,status):self._connection.execute('UPDATE diy_bookings SET status=? WHERE id=?',(status,bid))
    def lock_capacity(self):
        if not self._mysql:self._connection.execute("UPDATE products SET id=id WHERE category='diy_cake'")
        row=self._one("SELECT id FROM products WHERE category='diy_cake' ORDER BY id LIMIT 1"+self._lock_suffix)
        if not row:raise ValueError('Workshop booking is temporarily unavailable. Contact Staff.')
    def taken(self,day,slot):
        rows=self._rows("SELECT pax FROM diy_bookings WHERE event_date=? AND time_slot=? AND status<>'cancelled'"+self._lock_suffix,(day,slot))
        return sum(r['pax'] for r in rows)
    def create(self,booking):
        return self._connection.execute('INSERT INTO diy_bookings(user_id,event_date,time_slot,pax) VALUES (?,?,?,?)',(booking.user_id,booking.event_date,booking.time_slot,booking.pax)).lastrowid
    def cancel(self,bid,uid):
        return self._connection.execute("UPDATE diy_bookings SET status='cancelled' WHERE id=? AND user_id=? AND status IN ('pending','confirmed')",(bid,uid)).rowcount>0

class CustomerRepository(Repository):
    def summary(self,uid):
        return self._one("""SELECT COUNT(*) total_orders,
            COALESCE(SUM(CASE WHEN status NOT IN ('cancelled','delivered') THEN 1 ELSE 0 END),0) active_orders,
            COALESCE(SUM(CASE WHEN status='delivered' AND payment_status='paid' THEN total ELSE 0 END),0) completed_spend
            FROM orders WHERE user_id=?""",(uid,))
    def recent(self,uid):return self._rows('SELECT id,total,order_type,status,payment_status,points_used,created_at FROM orders WHERE user_id=? AND hidden_by_customer=0 ORDER BY id DESC LIMIT 5',(uid,))
    def bookings(self,uid,today):return self._one("SELECT COUNT(*) n FROM diy_bookings WHERE user_id=? AND status<>'cancelled' AND event_date>=?",(uid,today))['n']
