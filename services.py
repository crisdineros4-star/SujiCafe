"""Application services orchestrate domain rules and repositories in one transaction."""
import core
from domain import User,Order,Booking,business_today
from repositories import OrderRepository,BookingRepository,CustomerRepository

class OrderService:
    def __init__(self,connection,mysql=False):self._repository=OrderRepository(connection,mysql);self._connection=connection
    def transition(self,oid,next_status,reason=''):
        import ops
        actor=User.from_row(ops.actor('update_order'));row=self._repository.lock(oid)
        if not row or not Order.from_row(row).can_transition_to(next_status,actor.role):raise ValueError('That status change is not allowed. Refresh the order.')
        model=Order.from_row(row)
        if next_status=='cancelled':
            reason=ops.valid_reason(reason)
            if not core.cancel_order(self._connection,row):raise ValueError('This order cannot be cancelled.')
            ops.audit('order.cancel_reason','order',oid,{'reason':reason})
        else:
            if not model.payment_cleared:raise ValueError('Verify the GCash payment first.')
            if next_status=='delivered':
                if not core.complete_order(self._connection,oid):raise ValueError('This order cannot be completed.')
            else:self._repository.change_status(oid,next_status)
            ops.audit('order.status','order',oid,{'from':model.status,'to':next_status})
    def assign_rider(self,oid,rid):
        import ops
        ops.actor('assign_rider');row=self._repository.lock(oid)
        if not row or not Order.from_row(row).can_assign_rider():raise ValueError('Only a ready delivery can be assigned or reassigned.')
        if not self._repository.rider_exists(rid):raise ValueError('Choose a valid rider account.')
        model=Order.from_row(row)
        if not model.payment_cleared:raise ValueError('Verify the GCash payment first.')
        if model.rider_id==rid:return
        self._repository.assign(oid,rid);ops.audit('rider.assigned','order',oid,{'from_rider':model.rider_id,'to_rider':rid})

class BookingService:
    CAPACITY=12
    def __init__(self,connection,mysql=False):self._repository=BookingRepository(connection,mysql)
    def reserve(self,uid,day,slot,pax):
        import ops
        actor=User.from_row(ops.actor('customer_workspace'))
        if actor.id!=uid:raise ValueError('You can reserve only for your own account.')
        booking=Booking(uid,day,slot,pax);errors=booking.validation_errors()
        if errors:raise ValueError(' '.join(errors))
        self._repository.lock_capacity();remaining=self.CAPACITY-self._repository.taken(booking.event_date,booking.time_slot)
        if booking.pax>remaining:raise ValueError(f'Only {max(0,remaining)} seat(s) left for that slot.')
        bid=self._repository.create(booking);ops.audit('booking.created','booking',bid,{'date':booking.event_date,'slot':booking.time_slot,'pax':booking.pax});return bid
    def update(self,bid,status):
        import ops
        ops.actor('workshop_update');self._repository.lock_capacity()
        row=self._repository.get(bid)
        if not row or status not in ('confirmed','cancelled'):raise ValueError('Reservation not found or invalid status.')
        if row['status']=='cancelled':raise ValueError('A cancelled reservation cannot be reopened. Ask the customer to make a new booking.')
        if status==row['status']:return
        self._repository.update_status(bid,status)
        ops.audit('booking.updated','booking',bid,{'from':row['status'],'to':status})
    def cancel(self,bid,uid):
        import ops
        actor=User.from_row(ops.actor('customer_workspace'))
        if actor.id!=uid:raise ValueError('You can cancel only your own reservation.')
        changed=self._repository.cancel(bid,uid)
        if changed:ops.audit('booking.cancelled','booking',bid)
        return changed

class CustomerDashboardService:
    def __init__(self,connection,mysql=False):self._repository=CustomerRepository(connection,mysql)
    def for_user(self,user):
        model=User.from_row(user)
        if not model.can_access('customer'):raise ValueError('Customer account required.')
        return dict(summary=self._repository.summary(model.id),recent=self._repository.recent(model.id),upcoming=self._repository.bookings(model.id,business_today().isoformat()))
