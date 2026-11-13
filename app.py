"""Suji Cafe web system. Run with:  python app.py
Areas:  /customer  (menu, bag, orders, workshop)   /admin   /rider   plus public login pages."""
import os, secrets
from flask import Flask, request, session, redirect, url_for, abort, render_template
import config, core
from auth import bp as auth_bp
from customer import bp as customer_bp
from admin import bp as admin_bp
from owner import bp as owner_bp
from rider import bp as rider_bp
from staff import bp as staff_bp
from psgc import bp as psgc_bp
from payments import bp as payments_bp
from account_settings import bp as account_bp
from owner_recovery import bp as owner_recovery_bp

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
import security
security.configure(app)
from time_utils import transaction_time
app.jinja_env.filters['transaction_time']=transaction_time
app.config.update(TEMPLATES_AUTO_RELOAD=True, SEND_FILE_MAX_AGE_DEFAULT=3600, MAX_CONTENT_LENGTH=3 * 1024 * 1024, SESSION_COOKIE_SAMESITE='Lax',
                  SESSION_COOKIE_SECURE=app.config['SESSION_COOKIE_SECURE'], SESSION_COOKIE_HTTPONLY=True, MAX_FORM_PARTS=1000)
app.jinja_env.auto_reload=True
for bp in (auth_bp, customer_bp, admin_bp, owner_bp, rider_bp, staff_bp, psgc_bp, payments_bp, account_bp, owner_recovery_bp):
    app.register_blueprint(bp)
core.init_db(); core.migrate()
import workshop_payments
with app.app_context(): workshop_payments.initialize()
import commerce
with app.app_context(): commerce.initialize()

import click
def create_local_account(email,password,role):
    import ops
    email=email.strip().lower()
    if role=='owner' and (not config.OWNER_EMAIL or email!=config.OWNER_EMAIL):
        raise click.ClickException('Set OWNER_EMAIL in .env to this owner email first.')
    if role=='admin' and email in {config.OWNER_EMAIL,config.ADMIN_EMAIL}- {''}:
        raise click.ClickException('This email is reserved for the owner. Use create-owner.')
    if not core.EMAIL.fullmatch(email) or not 8<=len(password)<=128 or not core.PW.fullmatch(password):
        raise click.ClickException('Use a valid email and a strong password with upper, lower, number and symbol.')
    from registration_policy import validate_email_policy
    try:validate_email_policy(email)
    except ValueError as exc:raise click.ClickException(str(exc)) from exc
    d=core.db()
    try:
        if core.mysql_enabled():
            lock=d.execute("SELECT GET_LOCK('suji_bootstrap_owner',10) AS acquired").fetchone()
            if not lock['acquired']:raise click.ClickException('Account setup is busy. Try again.')
        else:d.execute('BEGIN IMMEDIATE')
        if role=='owner' and core.q("SELECT id FROM users WHERE role='owner'",one=True):
            raise click.ClickException('An owner already exists. Use the existing owner account.')
        if core.user_by_email(email):raise click.ClickException('This email already has an account. No role was changed.')
        uid=d.execute("INSERT INTO users(first_name,last_name,email,phone,birthdate,address,password_hash,role) VALUES ('Store',?,?,'','','',?,?)",(role.title(),email,core.generate_password_hash(password),role)).lastrowid
        ops.audit('account.created','user',uid,{'role':role,'via':'local setup'})
        d.commit();click.echo(role.title()+' account created. Sign in at /login.')
    except Exception:d.rollback();raise
    finally:
        if core.mysql_enabled():d.execute("SELECT RELEASE_LOCK('suji_bootstrap_owner')")

@app.cli.command('create-owner')
@click.option('--email',prompt=True)
@click.password_option(confirmation_prompt=True)
def create_owner(email,password):
    """Create the configured owner from the local terminal only."""
    create_local_account(email,password,'owner')

@app.cli.command('create-admin')
def create_admin():
    """Create a daily operations administrator, without owner permissions."""
    raise click.ClickException('Admin accounts must now be invited and email-activated through the Owner workspace. Use create-owner only for local Owner setup.')

# things every page can use
app.jinja_env.globals.update(status_label=core.status_label, points_text=core.points_text, flow=core.flow,
                             cat_icon=core.CAT_ICON, cat_label=core.CAT_LABEL, type_info=core.TYPE_INFO)
from order_qr import code_for
app.jinja_env.globals['order_qr_code']=code_for

@app.teardown_appcontext
def close_db(error):
    core.close_db(error)

security.register_hooks(app)

@app.before_request
def csrf_check():
    import posixpath
    if request.endpoint=='static' and posixpath.normpath((request.view_args or {}).get('filename','')) in ('data/registration-policy.json','data/adult-domains.hosts'):
        abort(404)
    session.setdefault('csrf', secrets.token_hex(16))
    if request.method in ('POST','PUT','PATCH','DELETE'):
        from validation import FormValidator
        try:FormValidator().validate(request.form)
        except ValueError as exc:abort(400,description=str(exc))
        sent = request.form.get('csrf') or request.headers.get('X-CSRF')
        if not isinstance(sent,str) or len(sent)>64 or not secrets.compare_digest(sent.encode(),str(session['csrf']).encode()):abort(400)

import device_trust
device_trust.register_hooks(app)

@app.context_processor
def inject():
    u = core.current_user()
    if config.GOOGLE_CLIENT_ID and request.endpoint in ('auth.login','auth.register'):session.setdefault('google_nonce',secrets.token_urlsafe(32))
    n, sub = core.cart_totals() if u and u['role'] == 'customer' else (0, 0)
    return dict(csrf=session.get('csrf'), user=u, cart_count=n, cart_total=sub, store=core.STORE, mode=session.get('mode'),
                facebook_page_url=config.FACEBOOK_URL, instagram_url=config.INSTAGRAM_URL,
                gcash_ready=commerce.gcash_ready(), gcash_qr=commerce.setting('gcash_qr'), gcash_account=commerce.setting('gcash_account'),gcash_number=commerce.setting('gcash_number'),
                earn_per_peso=commerce.setting('earn_per_peso','100'),
                google_maps_url=config.GOOGLE_MAPS_URL, delivery_barangays=core.DELIVERY_BARANGAYS, delivery_coverage=core.DELIVERY_COVERAGE,delivery_radii=core.DELIVERY_RADII_KM,
                google_nonce=session.get('google_nonce',''),google_client_id=config.GOOGLE_CLIENT_ID,                           # real Google button
                google_dev=bool(config.DEV_PRINT_OTP and not config.GOOGLE_CLIENT_ID))  # setup hint, only while testing

@app.route('/')
def home():
    u = core.current_user()
    if u and u['role']!='customer': return redirect(core.home_for(u))
    from pathlib import Path
    uploaded=commerce.setting('landing_image')
    if uploaded and (Path(core.BASE)/'static/uploads'/uploaded).is_file():
        hero_image='uploads/'+uploaded;hero_alt='Inside Suji Café'
    elif (Path(core.BASE)/'static/brand/suji-interior.png').is_file():
        hero_image='brand/suji-interior.png';hero_alt='Inside Suji Café'
    elif (Path(core.BASE)/'static/brand/suji-interior.jpg').is_file():
        hero_image='brand/suji-interior.jpg';hero_alt='Inside Suji Café'
    else:
        hero_image=None;hero_alt='Inside Suji Café'
    address=core.STORE['address']
    visit_detail='' if any(word in address.lower() for word in ('confirm','set store')) else address
    return render_template('home.html',hero_image=hero_image,hero_alt=hero_alt,visit_detail=visit_detail)

@app.get('/guide')
def help_guide():
    return render_template('guide.html')

@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(405)
@app.errorhandler(429)
@app.errorhandler(413)
def error_page(e):
    from werkzeug.exceptions import SecurityError
    if isinstance(e,SecurityError):return 'Invalid Host header.',400
    messages={429:'Too many attempts. Please wait before trying again.',400:'Your session expired or the form was invalid. Refresh and check the fields.',
      403:'This account does not have permission for that action.',404:'We could not find that page.',
      405:'This action is not available at this address.',413:'The uploaded file is too large (maximum request size 3 MB).'}
    from werkzeug.exceptions import BadRequest
    msg=e.description if e.code==400 and e.description!=BadRequest.description else messages[e.code]
    if request.path.startswith(('/auth/google','/staff/scan','/staff/payments/receive','/rider/pickup','/rider/deliver','/customer/cart/add','/customer/cart/set','/register/check','/customer/location/address','/admin/reservations')):
        from flask import jsonify
        response=jsonify(ok=False,msg=msg);response.status_code=e.code
        if e.code==429:response.headers['Retry-After']=str(e.retry_after or 60)
        return response
    from flask import make_response
    response=make_response(render_template('error.html',code=e.code,msg=msg),e.code)
    if e.code==429:response.headers['Retry-After']=str(e.retry_after or 60)
    return response

@app.errorhandler(500)
def internal_error(error):
    # A rollback makes retrying safer; never show database details or credentials.
    try:core.db().rollback()
    except Exception:pass
    message='We could not complete that action. Refresh and check the order or record before trying again.'
    if request.path.startswith(('/auth/google','/staff/scan','/staff/payments/receive','/rider/','/customer/cart/')):
        from flask import jsonify
        return jsonify(ok=False,msg=message),500
    # Keep the fallback independent of context processors, which may have failed.
    from flask import make_response
    html=app.jinja_env.get_template('server_error.html').render(message=message)
    response=make_response(html,500)
    return response

@app.url_defaults
def version_static_assets(endpoint,values):
    if endpoint=='static' and str(values.get('filename','')).endswith(('.css','.js')):
        from pathlib import Path
        filename=Path(app.static_folder)/values['filename']
        if filename.is_file():values['rev']=str(filename.stat().st_mtime_ns)

@app.after_request
def response_headers(response):
    if request.endpoint!='static' and response.mimetype in ('text/html','application/json'):
        response.headers['Cache-Control']='private, no-store'
    elif request.endpoint=='static' and request.path.endswith(('.js','.css')):
        response.headers['Cache-Control']='no-cache'
    response.headers.setdefault('X-Content-Type-Options','nosniff')
    response.headers.setdefault('X-Frame-Options','SAMEORIGIN')
    response.headers.setdefault('Referrer-Policy','strict-origin-when-cross-origin')
    return response

from setup_checks import register_commands
register_commands(app)
from owner_recovery import register_commands as register_owner_recovery
register_owner_recovery(app)

if __name__ == '__main__':
    app.run(debug=os.environ.get('FLASK_DEBUG') == '1')
