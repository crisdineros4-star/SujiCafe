"""Bound form input before database access; route/domain rules validate meaning."""
class FormValidator:
    LIMITS={'email':254,'first_name':50,'middle_name':50,'last_name':50,
        'password':128,'confirm':128,'current':128,'new':128,'phone':30,
        'address':2000,'street':255,'label':40,'name':150,'description':5000,
        'reason':500,'note':255,'account':150,'number':11,'reference':150,
        'date':10,'birthdate':10,'slot':20,'table':10,'lat':32,'lng':32,
        'price':32,'received':32,'earn_per_peso':32,'id':32,'rider_id':32,
        'csrf':64,'checkout_key':64,'reward_key':64,'receipt_key':64,'code':110}
    def validate(self,form):
        for key in form:
            values=form.getlist(key)
            if len(key)>80 or len(values)!=1:raise ValueError('The form contains duplicate or invalid fields. Refresh and try again.')
            limit=self.LIMITS.get(key,12 if key.startswith(('qty_','points_')) else 5000)
            if len(values[0])>limit:
                label=key.replace('_',' ').capitalize()
                raise ValueError(f'{label} is too long (maximum {limit} characters).')
