"""Public pages: register, login (with email device verification), Google sign-in, forgot password, logout."""
import os, json, time, urllib.parse, urllib.request
import config
import ops
import email_validation
import device_trust
import security
from registration_policy import validate_email_policy, validate_name_policy, valid_email_username
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, make_response, jsonify
from core import *

bp = Blueprint('auth', __name__)
DUMMY_PASSWORD_HASH=generate_password_hash(secrets.token_urlsafe(32))

@bp.route('/register', methods=['GET', 'POST'])
def register():
    import signup_verification
    errors, f = [], {}
    if request.method == 'POST':
        f = {k: request.form.get(k, '').strip() for k in
             ['first_name', 'middle_name', 'last_name', 'email', 'phone', 'birthdate', 'address']}
        f['password'] = request.form.get('password', ''); f['confirm'] = request.form.get('confirm', '')
        f['terms'] = request.form.get('terms'); f['email'] = f['email'].lower()
        errors = validate(f)
        try:
            for key in ('first_name','middle_name','last_name'):validate_name_policy(f[key],key.replace('_',' ').title())
            validate_email_policy(f['email'])
        except ValueError as exc:errors.append(str(exc))
        if not valid_registration_email(f['email']) and not any('email' in error.lower() for error in errors):
            errors.append('Enter a complete valid email address, such as name@gmail.com.')
        if not errors and user_by_email(f['email']): errors.append('This email is already registered.')
        import accounts
        if not errors and accounts.taken(f['phone']): errors.append('This mobile number is already registered. Please log in or recover your account.')
        if f['email'] in {config.OWNER_EMAIL,config.ADMIN_EMAIL}- {''}:
            errors.append('This email is reserved for store setup. Contact the owner.')
        if not errors:
            try:email_validation.validate_email_domain(f['email'])
            except email_validation.EmailDomainError as exc:errors.append(str(exc))
        if not errors:
            ok, message = signup_verification.start(f)
            if ok:
                flash(message, 'info')
                return redirect(url_for('auth.verify_registration'))
            errors.append(message)
        f.pop('password'); f.pop('confirm')
    live = signup_verification.pending()
    if live and live['attempts'] >= 5:
        live = None
    return render_template('auth/register.html', old=f, errors=errors,
                           pending_verification=live,
                           verification_seconds=max(0, int(live['expires_at'] - time.time())) if live else 0)

@bp.route('/register/verify', methods=['GET', 'POST'])
def verify_registration():
    import signup_verification
    pending = signup_verification.pending()
    if not pending:
        flash('Start sign up to request an email verification code.', 'info')
        return redirect(url_for('auth.register'))
    if request.method == 'POST':
        if request.form.get('action') == 'resend':
            ok, message = signup_verification.resend()
        else:
            ok, message = signup_verification.complete(request.form.get('code', ''))
            if ok:
                flash(message, 'success')
                return redirect(url_for('auth.login'))
        flash(message, 'info' if ok else 'danger')
    active = signup_verification.pending()
    if active is None:
        flash('The verification code expired. You can request a new code now.', 'info')
        return redirect(url_for('auth.register'))
    response = make_response(render_template('auth/verify_registration.html', email=active['email'],
                          verification_seconds=max(0, int(active['expires_at'] - time.time())),
                          resend_wait=max(0, int(active['sent_at'] + 60 - time.time()))))
    response.headers['Cache-Control'] = 'private, no-store'
    return response

@bp.route('/register/finish', methods=['GET', 'POST'])
def finish_registration():
    """Let people with an emailed code finish even after browser Back/session loss."""
    email = ''
    error = None
    if request.method == 'POST':
        import signup_verification
        email = request.form.get('email', '').strip().lower()
        code = request.form.get('code', '').strip()
        if len(code) != 6 or not code.isascii() or not code.isdigit():
            error = 'Enter the 6-digit code from your email.'
        else:
            ok, message = signup_verification.finish_with_existing_code(email, code)
            if ok:
                flash(message, 'success')
                return redirect(url_for('auth.login'))
            error = message
    response = make_response(render_template('auth/finish_registration.html', email=email, error=error))
    response.headers['Cache-Control'] = 'private, no-store'
    return response

def valid_registration_email(value):
    return isinstance(value,str) and 3<=len(value)<=254 and value==value.strip() and not any(ch.isspace() for ch in value) and bool(EMAIL.fullmatch(value)) and valid_email_username(value)

@bp.post('/register/check')
def registration_check():
    import accounts
    field=request.form.get('field');value=request.form.get('value','').strip().lower()
    if field in ('first_name','middle_name','last_name'):
        if field=='middle_name' and not value:return jsonify(ok=True,msg='Optional field.')
        if not NAME.fullmatch(value):return jsonify(ok=False,msg='Use 2–50 letters for your name.')
        try:validate_name_policy(value,field.replace('_',' ').title())
        except ValueError as exc:return jsonify(ok=False,msg=str(exc))
        return jsonify(ok=True,msg='Name format passed.')
    if field not in ('email','phone'):return jsonify(ok=False,msg='Invalid field.'),400
    if (field=='email' and (len(value)>254 or not EMAIL.fullmatch(value))) or (field=='phone' and phone_error(value)):
        return jsonify(ok=False,msg='Enter a complete valid '+field+'.')
    if field=='email':
        try:validate_email_policy(value)
        except ValueError as exc:return jsonify(ok=False,msg=str(exc))
    used=bool(user_by_email(value)) if field=='email' else accounts.taken(value)
    if field=='email' and value in {config.OWNER_EMAIL,config.ADMIN_EMAIL}- {''}:used=True
    if field=='email' and not used:
        try:email_validation.validate_email_domain(value)
        except email_validation.EmailDomainUnavailable as exc:return jsonify(ok=False,msg=str(exc),retryable=True),503
        except email_validation.EmailDomainError as exc:return jsonify(ok=False,msg=str(exc))
    message='Already registered. Please log in or recover your account.' if used else ('Email format and mail domain are valid; this address is available for registration.' if field=='email' else 'Mobile number is available.')
    return jsonify(ok=not used,msg=message)

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user(): return redirect(home_for(current_user()))
    login_email=request.form.get('email','') if request.method=='POST' else ''
    if request.method == 'POST':
        u = user_by_email(login_email)
        candidate=request.form.get('password','')
        valid=check_password_hash(u['password_hash'] if u else DUMMY_PASSWORD_HASH,candidate)
        locked=bool(u and u['locked_until'] and datetime.fromisoformat(u['locked_until'])>datetime.now())
        if not valid or locked:
            if u and not locked:
                run('UPDATE users SET locked_until=CASE WHEN failed_logins>=4 THEN ? ELSE locked_until END, failed_logins=CASE WHEN failed_logins>=4 THEN 0 ELSE failed_logins+1 END WHERE id=?',((datetime.now()+timedelta(minutes=10)).isoformat(),u['id']))
            security.auth_event('login_failed',u['id'] if u else None)
            flash('Wrong email or password, or sign-in is temporarily unavailable. Try again later or use Forgot password.','danger')
        elif not __import__('employee_invitations').is_active(u['id']):
            security.auth_event('login_blocked',u['id'])
            flash(__import__('employee_invitations').access_message(u['id']), 'warning')
        else:
            run('UPDATE users SET failed_logins=0, locked_until=NULL WHERE id=?',(u['id'],))
            token=request.cookies.get('suji_device')
            trusted=device_trust.trusted_device(u['id'],token)
            if trusted:
                security.establish(u['id']);device_trust.touch(trusted,token)
                security.auth_event('login_succeeded',u['id'])
                return redirect(home_for(u))
            if not issue_code(u,'login','verify your device'):
                flash('Could not send a code. Wait before retrying; check email settings if the problem continues.','danger')
                return render_template('auth/login.html',login_email=login_email)
            # Rotate the anonymous state at the password authentication boundary.
            session.clear();session['csrf']=secrets.token_hex(32);session['pending']=u['id']
            return redirect(url_for('auth.verify'))
    return render_template('auth/login.html',login_email=login_email)

@bp.route('/verify', methods=['GET', 'POST'])
def verify():
    uid = session.get('pending')
    if not uid: return redirect(url_for('auth.login'))
    if not __import__('employee_invitations').is_active(uid):
        session.pop('pending',None);flash('Activate this employee account using its invitation first.','warning');return redirect(url_for('auth.login'))
    if request.method == 'POST':
        ok, msg = check_code(uid, 'login', request.form.get('code', ''))
        if ok:
            security.establish(uid)
            security.auth_event('login_succeeded',uid,'password+email')
            u=q('SELECT * FROM users WHERE id=?',(uid,),one=True)
            response=make_response(redirect(home_for(u)))
            return device_trust.remember(uid,response)
        flash(msg, 'danger')
    return render_template('auth/verify.html')

@bp.route('/forgot', methods=['GET', 'POST'])
def forgot():
    email=request.form.get('email','').strip().lower() if request.method=='POST' else ''
    error=None
    if request.method=='POST':
        if len(email)>254 or not EMAIL.fullmatch(email):error='Enter a complete valid email address.'
        else:
            import password_reset
            session.pop('reset_grant',None)
            user=user_by_email(email)
            if user:password_reset.request_code(user)
            session['reset_email']=email
            flash('If that email is registered, we sent a 6-digit code to it.','info')
            return redirect(url_for('auth.reset'))
        flash(error,'danger')
    return render_template('auth/forgot.html',forgot_email=email,field_error=error)

@bp.route('/reset', methods=['GET', 'POST'])
def reset():
    import password_reset
    email=session.get('reset_email')
    if not email:return redirect(url_for('auth.forgot'))
    if request.method=='GET' and password_reset.active(session.get('reset_grant')):return redirect(url_for('auth.update_password'))
    error=None;code=request.form.get('code','').strip() if request.method=='POST' else ''
    if request.method=='POST':
        ok,result=password_reset.check(email,code,consume=True)
        if ok:
            session['reset_grant']=result
            return redirect(url_for('auth.update_password'))
        error=result;flash(error,'danger')
    return render_template('auth/reset.html',reset_code=code,field_error=error)

@bp.post('/reset/check')
def reset_check():
    import password_reset
    email=session.get('reset_email')
    ok,message=password_reset.check(email,request.form.get('code','')) if email else (False,'Request a reset code first.')
    response=jsonify(ok=ok,msg=message);response.headers['Cache-Control']='private, no-store';return response

@bp.route('/reset/password',methods=['GET','POST'])
def update_password():
    import password_reset
    grant=session.get('reset_grant')
    if not password_reset.active(grant):
        session.pop('reset_grant',None);flash('Verify a valid reset code before setting a new password.','warning')
        return redirect(url_for('auth.reset') if session.get('reset_email') else url_for('auth.forgot'))
    error=None
    if request.method=='POST':
        password=request.form.get('password','')
        if len(password)>128 or not PW.fullmatch(password):error='Password needs 8–128 characters with uppercase, lowercase, a number and a symbol.'
        elif password!=request.form.get('confirm',''):error='Passwords do not match.'
        elif not password_reset.update(grant,password):
            session.pop('reset_grant',None);flash('Your reset session expired. Request a new code.','danger');return redirect(url_for('auth.forgot'))
        else:
            session.clear();session['csrf']=secrets.token_hex(32)
            flash('Password updated. Log in with your new password.','success');return redirect(url_for('auth.login'))
        flash(error,'danger')
    response=make_response(render_template('auth/auth-update_password.html',field_error=error));response.headers['Cache-Control']='private, no-store';return response

@bp.post('/logout')
def logout():
    user=current_user();token=request.cookies.get('suji_device')
    if user:
        if token and len(token)==64:run('UPDATE trusted_devices SET session_hash=NULL WHERE user_id=? AND token_hash=?',(user['id'],sha(token)))
        security.auth_event('logout',user['id'])
    session.clear()
    from flask import g
    g.pop('refresh_device_token',None);g.pop('u',None)
    resp=make_response(redirect(url_for('auth.login')))
    return resp


# ---------------- Sign up / log in with Google ----------------
def verify_google(token):
    """Ask Google if this sign-in token is real and was made for this site. Returns the profile or None."""
    url = 'https://oauth2.googleapis.com/tokeninfo?id_token=' + urllib.parse.quote(token, safe='')
    with urllib.request.urlopen(url, timeout=8) as r:
        info = json.loads(r.read().decode('utf-8'))
    if info.get('aud') != config.GOOGLE_CLIENT_ID: return None
    if info.get('iss') not in ('accounts.google.com', 'https://accounts.google.com'): return None
    if str(info.get('email_verified')).lower() != 'true' or not info.get('email'): return None
    if int(info.get('exp', 0)) < time.time(): return None
    expected=session.get('google_nonce')
    if not expected or not secrets.compare_digest(str(info.get('nonce','')),expected):return None
    return info

@bp.post('/auth/google')
def google_auth():
    """Google already checked the person's email, so there is no password or email code step."""
    if not config.GOOGLE_CLIENT_ID: return jsonify(ok=False, msg='Google sign-in is not set up yet.'), 400
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict): return jsonify(ok=False, msg='Invalid Google sign-in request.'), 400
    token = payload.get('credential', '')
    if not isinstance(token, str) or not token or len(token) > 4096: return jsonify(ok=False, msg='Google sign-in failed. Please try again.'), 400
    try: info = verify_google(token)
    except Exception: return jsonify(ok=False, msg='Could not reach Google to confirm your sign-in. Try again in a moment.'), 502
    if not info: return jsonify(ok=False, msg='Google sign-in could not be verified.'), 400
    email = info['email'].strip().lower()
    u = user_by_email(email)
    created = not bool(u)
    if u and not __import__('employee_invitations').is_active(u['id']):
        return jsonify(ok=False,msg='This account is not active. Complete its invitation or contact the Owner/Admin.'),403
    if not u and email in {config.OWNER_EMAIL,config.ADMIN_EMAIL}- {''}:
        return jsonify(ok=False,msg='The owner must complete the local store account setup first.'),403
    if not u:                                             # first time: create the account (no password, phone and address are added later)
        first = (info.get('given_name') or (info.get('name') or '').split(' ')[0] or 'Customer').strip()[:50]
        last = (info.get('family_name') or '').strip()[:50]
        try:
            validate_email_policy(email)
            validate_name_policy(first,'First name');validate_name_policy(last,'Last name')
        except ValueError as exc:return jsonify(ok=False,msg=str(exc)),400
        role = 'customer'
        uid=db().execute('INSERT INTO users (first_name,middle_name,last_name,email,phone,birthdate,address,password_hash,role) VALUES (?,?,?,?,?,?,?,?,?)',
            (first, None, last, email, '', '', '', generate_password_hash(secrets.token_urlsafe(32)), role)).lastrowid
        ops.audit('account.created','user',uid,{'role':role,'via':'verified Google sign-in'});db().commit()
        u = user_by_email(email)
    security.establish(u['id'])
    security.auth_event('login_succeeded',u['id'],'google')
    return device_trust.remember(u['id'],make_response(jsonify(ok=True, registered=created, redirect=home_for(u))))


@bp.route('/activate-account', methods=['GET', 'POST'])
def activate_account():
    import employee_invitations as invitations
    token = request.args.get('token')
    error = None
    if request.method == 'GET' and token is not None:
        session.pop('employee_activation', None)
        row = invitations.find_by_hash(sha(token)) if isinstance(token,str) and 20<=len(token)<=128 else None
        if row:
            session['employee_activation'] = sha(token)
            response = make_response(redirect(url_for('auth.activate_account')))
            response.headers['Cache-Control']='private, no-store'
            response.headers['Referrer-Policy']='no-referrer'
            return response
    proof = session.get('employee_activation')
    invite = invitations.find_by_hash(proof)
    if not invite:
        session.pop('employee_activation',None)
        error = 'This invitation is missing, expired, cancelled, replaced, or already used. Ask Owner/Admin to send a new one.'
    elif request.method == 'POST':
        password=request.form.get('password','')
        if password!=request.form.get('confirm',''):
            error='Passwords do not match.'
        else:
            try:
                uid=invitations.activate(proof,password,request.form)
            except ValueError as exc:
                error=str(exc)
            else:
                session.pop('employee_activation',None)
                flash('Your '+invite['role'].title()+' account is active. Log in with your email and new password.','success')
                response=make_response(redirect(url_for('auth.login')))
                # Email ownership and the new password were just established here.
                # Remember this device, without switching any existing signed-in account.
                if not current_user():response=device_trust.remember(uid,response)
                response.headers['Cache-Control']='private, no-store'
                response.headers['Referrer-Policy']='no-referrer'
                return response
    response=make_response(render_template('auth/activate_account.html',invite=invite,field_error=error),200 if invite else 400)
    response.headers['Cache-Control']='private, no-store'
    response.headers['Referrer-Policy']='no-referrer'
    return response
