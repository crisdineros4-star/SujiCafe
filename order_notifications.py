"""Persistent customer-only updates written in the same order transaction."""
import core


def initialize():
    auto='INT AUTO_INCREMENT PRIMARY KEY' if core.mysql_enabled() else 'INTEGER PRIMARY KEY AUTOINCREMENT'
    core.db().execute(f'''CREATE TABLE IF NOT EXISTS customer_notifications (
        id {auto},user_id INTEGER NOT NULL,order_id INTEGER NOT NULL,
        event_key VARCHAR(100) NOT NULL UNIQUE,title VARCHAR(160) NOT NULL,
        message VARCHAR(500) NOT NULL,created_at VARCHAR(40) NOT NULL,read_at VARCHAR(40) NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE)''')
    core.db().commit()


def capture(oid,event,key):
    allowed={'order.placed','order.status','order.cancelled','rider.assigned','rider.pickup','rider.delivered','payment.approved','payment.rejected','payment.refunded','sale.voided','sale.counter'}
    if event not in allowed:return
    order=core.q('SELECT o.*,u.role FROM orders o JOIN users u ON u.id=o.user_id WHERE o.id=?',(oid,),one=True)
    if not order or order['role']!='customer':return
    label=core.status_label(order['order_type'],order['status'])
    titles={'order.placed':'Order placed','rider.assigned':'Rider assigned','rider.pickup':'Your order is on the way','rider.delivered':'Delivery completed','payment.approved':'Payment confirmed','payment.rejected':'Payment needs review','payment.refunded':'Refund recorded','sale.voided':'Order voided','sale.counter':'Counter purchase recorded','order.cancelled':'Order cancelled'}
    title=titles.get(event,'Order update: '+label)
    message=f'Order #{oid} · {label}. '
    if event=='payment.approved':message+='The store confirmed your payment.'
    elif event=='payment.rejected':message+='Check the payment page for the store’s note.'
    elif event=='payment.refunded':message+='The store recorded the actual refund.'
    elif event=='rider.assigned':message+='A rider has been assigned to your delivery.'
    else:message+='Open My orders for the latest details.'
    import ops
    core.db().execute('INSERT INTO customer_notifications(user_id,order_id,event_key,title,message,created_at) VALUES (?,?,?,?,?,?)',(order['user_id'],oid,key,title,message,ops.now()))


def unread(uid):return core.q('SELECT COUNT(*) n FROM customer_notifications WHERE user_id=? AND read_at IS NULL',(uid,),one=True)['n']
