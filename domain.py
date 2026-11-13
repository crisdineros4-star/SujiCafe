"""Domain entities: validated state and business rules, independent of Flask routes."""
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo
import re

ORDER_FLOWS={
 'delivery':('pending','preparing','ready','picked_up','out_for_delivery','delivered'),
 'dinein':('pending','preparing','ready','delivered'),
 'pickup':('pending','preparing','ready','delivered'),'instore':('delivered',)}
BOOKING_SLOTS=('10:00 AM','2:00 PM','5:00 PM')

def business_today():return datetime.now(ZoneInfo('Asia/Manila')).date()
def amount(value):
    try:
        result=Decimal(str(value))
        if not result.is_finite() or result<0 or result>1000000:raise ValueError('Invalid amount.')
        return result.quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
    except (InvalidOperation,TypeError):raise ValueError('Invalid amount.')

class User:
    def __init__(self,user_id,email,role='customer'):
        self._id=int(user_id);self._email=str(email).strip().lower();self._role=role
    id=property(lambda self:self._id)
    email=property(lambda self:self._email)
    role=property(lambda self:self._role)
    @classmethod
    def from_row(cls,row):return cls(row['id'],row['email'],row['role'])
    def has_permission(self,permission):
        import ops
        return ops.allowed(self.role,permission)
    def can_access(self,area):return self.has_permission(area+'_workspace')

class Product:
    def __init__(self,name,category,price,description='',points_cost=0):
        self._name=str(name).strip();self._category=category;self._raw_price=price
        self._description=str(description).strip();self._points_cost=int(points_cost or 0)
    name=property(lambda self:self._name)
    category=property(lambda self:self._category)
    description=property(lambda self:self._description)
    price=property(lambda self:amount(self._raw_price))
    points_cost=property(lambda self:self._points_cost)
    @classmethod
    def from_row(cls,row):return cls(row['name'],row['category'],row['price'],row['description'] or '',row['points_cost'])
    def is_valid(self):
        try:return 1<=len(self.name)<=150 and self.price>0 and self.category in {'food','drink','merchandise','diy_cake'} and len(self.description)<=5000
        except (ValueError,TypeError):return False
    def can_redeem(self):return self.is_valid() and self.category in ('food','drink') and self.points_cost>0

class Order:
    """Base order rules. DeliveryOrder and StoreOrder specialize fulfillment."""
    VALID_STATUSES=set(s for path in ORDER_FLOWS.values() for s in path)|{'cancelled'}
    def __init__(self,order_id,user_id,total,status='pending',order_type='delivery',payment_method='cod',payment_status='unpaid',rider_id=None,voided=False):
        self._id=int(order_id);self._user_id=int(user_id);self._total=amount(total);self._status=status
        self._order_type=order_type;self._payment_method=payment_method;self._payment_status=payment_status
        self._rider_id=rider_id;self._voided=bool(voided)
    id=property(lambda self:self._id)
    user_id=property(lambda self:self._user_id)
    total=property(lambda self:self._total)
    status=property(lambda self:self._status)
    order_type=property(lambda self:self._order_type)
    rider_id=property(lambda self:self._rider_id)
    terminal=property(lambda self:self.status in ('cancelled','delivered') or self._voided)
    payment_cleared=property(lambda self:self._payment_method!='gcash' or self._payment_status=='paid')
    flow=property(lambda self:ORDER_FLOWS.get(self.order_type,()))
    @classmethod
    def from_row(cls,row):
        kind=DeliveryOrder if row['order_type']=='delivery' else StoreOrder
        return kind(row['id'],row['user_id'],row['total'],row['status'],row['order_type'],row['payment_method'],row['payment_status'],row['rider_id'],bool(row['voided_at']))
    def next_statuses(self,role):
        if self.terminal or self.status not in self.flow or role not in ('staff','admin','owner'):return []
        later=list(self.flow[self.flow.index(self.status)+1:])
        if role=='staff':later=[s for s in later if s in ('preparing','ready')]
        if role in ('admin','owner'):later.append('cancelled')
        return later
    def can_transition_to(self,status,role='admin'):return status in self.next_statuses(role)
    def can_finalize(self):return not self._voided and self.status!='cancelled' and self.payment_cleared
    def can_accept(self):return not self.terminal and self.status=='pending' and self.payment_cleared
    def can_ready(self):return not self.terminal and self.status=='preparing' and self.payment_cleared
    def can_complete_in_store(self):return False
    def can_assign_rider(self):return False
    def can_pick_up(self,rider_id):return False
    def can_deliver(self,rider_id):return False

class DeliveryOrder(Order):
    def next_statuses(self,role):
        return [s for s in super().next_statuses(role) if s in ('preparing','ready','cancelled')]
    def can_assign_rider(self):return not self.terminal and self.status=='ready'
    def can_pick_up(self,rider_id):return self.can_assign_rider() and self.rider_id==rider_id and self.payment_cleared
    def can_deliver(self,rider_id):return not self.terminal and self.status=='picked_up' and self.rider_id==rider_id and self.payment_cleared

class StoreOrder(Order):
    def can_complete_in_store(self):return not self.terminal and self.status=='ready' and self.order_type in ('pickup','dinein') and self.payment_cleared

class Booking:
    def __init__(self,user_id,event_date,time_slot,pax):
        self._user_id=int(user_id);self._date_text=str(event_date or '');self._slot=time_slot
        self._pax=int(pax) if not isinstance(pax,bool) and re.fullmatch(r'\d{1,2}',str(pax or '')) else 0
    user_id=property(lambda self:self._user_id)
    event_date=property(lambda self:self._date_text)
    time_slot=property(lambda self:self._slot)
    pax=property(lambda self:self._pax)
    def validation_errors(self,today=None):
        errors=[]
        try:
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',self.event_date):raise ValueError
            actual=date.fromisoformat(self.event_date)
            if actual<(today or business_today())+timedelta(days=1):raise ValueError
        except (ValueError,OverflowError):errors.append('Choose a real calendar date from tomorrow onward.')
        if self.time_slot not in BOOKING_SLOTS:errors.append('Choose an available workshop time slot.')
        if not 1<=self.pax<=10:errors.append('Group size must be a whole number from 1–10.')
        return errors
    def is_valid(self):return not self.validation_errors()
