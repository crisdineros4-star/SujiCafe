"""Shared server-side validation for every role's personal settings."""
import re
import core
from registration_policy import validate_name_policy

def details(form):
    result={k:form.get(k,'').strip() for k in ('first_name','middle_name','last_name','phone')}
    for key,label in [('first_name','First name'),('middle_name','Middle name'),('last_name','Last name')]:
        value=result[key]
        if key=='middle_name' and not value:continue
        if not core.NAME.fullmatch(value) or sum(c.isalpha() for c in value)<2:
            raise ValueError(label+' must be 2–50 characters using letters, spaces, apostrophes, periods or hyphens.')
        validate_name_policy(value,label)
    if not re.fullmatch(r'09[0-9]{9}',result['phone']):raise ValueError('Mobile number must contain exactly 11 digits starting with 09.')
    if core.phone_error(result['phone']):raise ValueError(core.phone_error(result['phone']))
    return result

def password(value,confirm,current_hash=None):
    if not 8<=len(value)<=128 or not core.PW.fullmatch(value):
        raise ValueError('Use 8–128 characters with uppercase, lowercase, a number and a symbol.')
    if value!=confirm:raise ValueError('Passwords do not match.')
    if current_hash and core.check_password_hash(current_hash,value):raise ValueError('New password must be different from your current password.')
