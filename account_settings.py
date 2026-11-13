"""Authenticated self-service settings, with immutable role and sign-in email."""
from flask import Blueprint,render_template,request,redirect,url_for,flash,session
import core,accounts,ops,device_trust
from registration_policy import validate_name_policy

bp=Blueprint('account',__name__)

@bp.route('/account',methods=['GET','POST'])
@core.login_required()
def settings():
    user=core.current_user()
    if user['role']=='customer':return redirect(url_for('customer.profile'))
    if request.method=='POST':
        try:
            if request.form.get('action')=='details':
                from account_validation import details
                values=details(request.form)
                first,last,middle,phone=(values[k] for k in ('first_name','last_name','middle_name','phone'))
                if phone!=user['phone']:
                    if accounts.taken(phone,user['id']):raise ValueError('This mobile number is already registered.')
                    accounts.claim(phone,user['id'])
                core.db().execute('UPDATE users SET first_name=?,middle_name=?,last_name=?,phone=? WHERE id=?',(first,middle or None,last,phone,user['id']))
                ops.audit('account.self_details','user',user['id']);core.db().commit();flash('Your details were saved.','success')
            elif request.form.get('action')=='password':
                password=request.form.get('password','')
                if not core.check_password_hash(user['password_hash'],request.form.get('current','')):raise ValueError('Current password is incorrect.')
                from account_validation import password as validate_password
                validate_password(password,request.form.get('confirm',''),user['password_hash'])
                core.db().execute('UPDATE users SET password_hash=? WHERE id=?',(core.generate_password_hash(password),user['id']))
                __import__('security').revoke_credentials(user['id'])
                ops.audit('account.self_password','user',user['id']);core.db().commit()
                __import__('security').establish(user['id'])
                flash('Password updated. Other trusted devices must verify again.','success')
                return device_trust.remember(user['id'],redirect(url_for('account.settings')))
            else:raise ValueError('Choose a valid account action.')
        except Exception as exc:
            if not isinstance(exc,ValueError) and type(exc).__name__!='IntegrityError':raise
            if type(exc).__name__=='IntegrityError':exc=ValueError('This mobile number is already registered.')
            core.db().rollback();flash(str(exc),'danger')
            return render_template('account/settings.html',back_url=core.home_for(user),account_values=request.form),422

        return redirect(url_for('account.settings'))
    return render_template('account/settings.html',back_url=core.home_for(user))
