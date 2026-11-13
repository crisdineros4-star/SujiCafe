"""Request hardening and shared, database-backed authentication rate limits."""
import hashlib,hmac,math,os,re,secrets,time
from datetime import timedelta
from urllib.parse import urlsplit
from flask import request,session,g,abort,jsonify,current_app
import config,core

PUBLIC_POST_LIMITS={
 'owner_recovery.claim':(12,600),'owner_recovery.accept':(10,600),
 'auth.login':(30,600),'auth.google_auth':(30,600),
 'auth.register':(30,600),'auth.registration_check':(120,60),
 'auth.verify':(12,600),'auth.verify_registration':(15,600),
 'auth.forgot':(12,600),'auth.reset':(12,600),'auth.reset_check':(12,600),
 'auth.update_password':(12,600),'auth.activate_account':(15,600)}

def configure(app):
    production=os.environ.get('APP_ENV','development').lower()=='production'
    secret=os.environ.get('SECRET_KEY','')
    origin=urlsplit(config.PUBLIC_BASE_URL)
    hosts=[x.strip() for x in os.environ.get('ALLOWED_HOSTS','').split(',') if x.strip()]
    if production:
        if len(secret)<32 or any(x in secret.lower() for x in ('replace','changeme','your-secret')):
            raise RuntimeError('Production requires a private random SECRET_KEY of at least 32 characters.')
        if os.environ.get('HTTPS')!='1':raise RuntimeError('Production requires HTTPS=1 and HTTPS at the public proxy.')
        if os.environ.get('FLASK_DEBUG')=='1' or config.DEV_PRINT_OTP:raise RuntimeError('Disable FLASK_DEBUG and DEV_PRINT_OTP in production.')
        if origin.scheme!='https' or not origin.hostname or origin.username or origin.password or origin.path.rstrip('/') or origin.query or origin.fragment:
            raise RuntimeError('Production requires PUBLIC_BASE_URL as your HTTPS origin only.')
        if core.mysql_enabled() and config.MYSQL_HOST not in ('localhost','127.0.0.1','::1') and not config.MYSQL_SSL_CA:
            raise RuntimeError('Remote production MySQL requires MYSQL_SSL_CA with certificate and hostname verification.')
        hosts=hosts or [origin.hostname]
    hosts=hosts or ['localhost','127.0.0.1','[::1]']
    if any(not re.fullmatch(r'\.?[A-Za-z0-9.\-\[\]:]+',host) or host in ('.','*') for host in hosts):
        raise RuntimeError('ALLOWED_HOSTS must be a comma-separated hostname allowlist.')
    hops=int(os.environ.get('TRUSTED_PROXY_HOPS','0'))
    if hops not in (0,1):raise RuntimeError('TRUSTED_PROXY_HOPS must be 0 or 1.')
    if hops:
        from werkzeug.middleware.proxy_fix import ProxyFix
        # Only enable behind one proxy which strips/replaces forwarded headers.
        app.wsgi_app=ProxyFix(app.wsgi_app,x_for=1,x_proto=1,x_host=0,x_port=0,x_prefix=0)
    app.config.update(PRODUCTION=production,TRUSTED_HOSTS=hosts,
        SESSION_COOKIE_SECURE=production or os.environ.get('HTTPS')=='1',
        SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),SESSION_REFRESH_EACH_REQUEST=False,
        MAX_FORM_MEMORY_SIZE=256*1024)

def initialize():
    core.db().execute('''CREATE TABLE IF NOT EXISTS security_rate_limits (
      bucket_key VARCHAR(64) PRIMARY KEY, hits INTEGER NOT NULL, expires_at DOUBLE NOT NULL)''')
    core.db().commit()

def canonical_email(value):
    value=str(value).strip().lower()
    if value.endswith('@gmail.com'):
        local,domain=value.rsplit('@',1);value=local.replace('.','')+'@'+domain
    return value[:254]

def consume(scope,subject,limit,period):
    now=time.time();window=int(now//period);expiry=(window+1)*period
    raw=f'{scope}:{subject}:{window}'.encode()
    key=hmac.new(str(config.SECRET_KEY).encode(),raw,hashlib.sha256).hexdigest()
    d=core.db()
    if core.mysql_enabled():
        d.execute('INSERT INTO security_rate_limits(bucket_key,hits,expires_at) VALUES (?,1,?) ON DUPLICATE KEY UPDATE hits=hits+1',(key,expiry))
    else:
        d.execute('INSERT INTO security_rate_limits(bucket_key,hits,expires_at) VALUES (?,1,?) ON CONFLICT(bucket_key) DO UPDATE SET hits=hits+1',(key,expiry))
    hits=d.execute('SELECT hits FROM security_rate_limits WHERE bucket_key=?',(key,)).fetchone()['hits']
    d.execute('DELETE FROM security_rate_limits WHERE expires_at<?',(now,));d.commit()
    return hits<=limit,max(1,math.ceil(expiry-now))

def throttle(scope,subject,limit,period):
    allowed,retry=consume(scope,subject,limit,period)
    if not allowed:
        from werkzeug.exceptions import TooManyRequests
        raise TooManyRequests(description='Too many attempts. Please wait before trying again.',retry_after=retry)

def revoke_credentials(uid):
    # All these tables are initialized at startup; caller owns the transaction.
    for table in ('trusted_devices','otp_codes','password_reset_requests'):
        core.db().execute('DELETE FROM '+table+' WHERE user_id=?',(uid,))

def establish(uid):
    session.clear();session['uid']=uid;session['csrf']=secrets.token_hex(32);session['login_session']=secrets.token_hex(32);session.permanent=True
    token=request.cookies.get('suji_device')
    if token and len(token)==64:
        core.run('UPDATE trusted_devices SET session_hash=? WHERE user_id=? AND token_hash=?',(core.sha(session['login_session']),uid,core.sha(token)))
    g.pop('u',None)

def auth_event(event,uid=None,method='password'):
    import ops
    ops.audit('auth.'+event,'user',uid,{'method':method})
    core.db().commit()

def nonce():
    if not g.get('csp_nonce'):g.csp_nonce=secrets.token_urlsafe(24)
    return g.csp_nonce

def register_hooks(app):
    @app.before_request
    def request_guard():
        g.csp_nonce=secrets.token_urlsafe(24)
        if app.config['PRODUCTION'] and not request.is_secure:abort(400,description='Use the HTTPS website address.')
        if request.method in ('POST','PUT','PATCH','DELETE'):
            if request.headers.get('Sec-Fetch-Site')=='cross-site':abort(403)
            origin=request.headers.get('Origin')
            if origin:
                parsed=urlsplit(origin);expected=urlsplit(request.host_url)
                if origin=='null':
                    # Chromium may omit the Origin on private no-referrer forms.
                    # Require browser same-origin metadata; CSRF still applies below.
                    if request.headers.get('Sec-Fetch-Site')!='same-origin':abort(403)
                elif (parsed.scheme,parsed.netloc)!=(expected.scheme,expected.netloc):abort(403)
            limit=PUBLIC_POST_LIMITS.get(request.endpoint)
            if limit:
                throttle('endpoint:'+request.endpoint,request.remote_addr or 'unknown',*limit)
                if request.endpoint in ('auth.login','auth.forgot','auth.register'):
                    email=canonical_email(request.form.get('email',''))
                    if email:throttle('email:'+request.endpoint,email,10 if request.endpoint=='auth.login' else 5,600)
            elif request.endpoint in ('account.settings','customer.profile'):
                throttle('account-edit',str(session.get('uid',request.remote_addr)),30,600)
    @app.context_processor
    def template_nonce():return {'csp_nonce':nonce()}
    @app.after_request
    def secure_headers(response):
        script=f"'self' 'nonce-{nonce()}' 'strict-dynamic' https://cdn.jsdelivr.net https://unpkg.com https://accounts.google.com https://maps.googleapis.com https://www.gstatic.com"
        response.headers['Content-Security-Policy']=(
            "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; "
            f"script-src {script}; script-src-attr 'none'; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com https://fonts.googleapis.com https://accounts.google.com https://cdnjs.cloudflare.com; "
            "img-src 'self' data: blob: https://tile.openstreetmap.org https://*.tile.openstreetmap.org https://maps.gstatic.com https://maps.googleapis.com https://*.googleusercontent.com https://unpkg.com https://cdnjs.cloudflare.com; "
            "font-src 'self' data: https://fonts.gstatic.com https://cdn.jsdelivr.net; "
            "connect-src 'self' https://accounts.google.com https://maps.googleapis.com https://router.project-osrm.org; "
            "frame-src https://accounts.google.com https://maps.google.com https://www.google.com; worker-src 'self' blob:")
        response.headers['X-Frame-Options']='DENY'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer' if request.endpoint in ('auth.activate_account','owner_recovery.accept','owner_recovery.claim') else 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy']='camera=(self), geolocation=(self), microphone=(), payment=()'
        response.headers['Cross-Origin-Resource-Policy']='same-origin'
        if app.config['PRODUCTION'] and request.is_secure:
            response.headers['Strict-Transport-Security']='max-age=31536000'
        if request.endpoint!='static' or request.path.startswith('/static/uploads/'):
            response.headers['Cache-Control']='private, no-store'
        if response.status_code>=400:response.headers['Cache-Control']='private, no-store'
        return response
