"""Server-checked device trust: seven days since the last authenticated activity."""
from datetime import datetime,timedelta,timezone
import os,secrets
from flask import request,session,g,redirect,url_for,flash,current_app
import core
IDLE_WINDOW=timedelta(days=7)
COOKIE_MAX_AGE=365*86400

def now_utc():return datetime.now(timezone.utc)
def parse_time(value):
    result=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    # Older releases wrote server-local naive values; new records always use UTC.
    if result.tzinfo is None:result=result.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return result.astimezone(timezone.utc)
def trusted_device(uid,token):
    if not token or len(token)!=64:return None
    row=core.q('SELECT * FROM trusted_devices WHERE user_id=? AND token_hash=?',(uid,core.sha(token)),one=True)
    if not row:return None
    try:
        age=now_utc()-parse_time(row['last_seen_at'] or row['created_at'])
        return row if timedelta(0)<=age<IDLE_WINDOW else None
    except (ValueError,TypeError):return None

def touch(row,token):
    current=now_utc()
    core.run('UPDATE trusted_devices SET last_seen_at=?,expires_at=? WHERE id=?',(current.isoformat(),(current+IDLE_WINDOW).isoformat(),row['id']))
    g.refresh_device_token=token

def remember(uid,response):
    previous=request.cookies.get('suji_device')
    if previous and len(previous)==64:core.run('DELETE FROM trusted_devices WHERE user_id=? AND token_hash=?',(uid,core.sha(previous)))
    token=secrets.token_hex(32);current=now_utc()
    core.run('INSERT INTO trusted_devices(user_id,token_hash,user_agent,last_seen_at,expires_at,session_hash) VALUES (?,?,?,?,?,?)',(uid,core.sha(token),request.headers.get('User-Agent','')[:255],current.isoformat(),(current+IDLE_WINDOW).isoformat(),core.sha(session['login_session']) if session.get('uid')==uid and session.get('login_session') else None))
    g.refresh_device_token=token
    set_cookie(response,token)
    return response

def set_cookie(response,token):
    response.set_cookie('suji_device',token,max_age=COOKIE_MAX_AGE,httponly=True,samesite='Lax',secure=current_app.config['SESSION_COOKIE_SECURE'])
    return response

def register_hooks(app):
    @app.before_request
    def check_device_activity():
        g.pop('refresh_device_token',None)
        endpoint=request.endpoint or ''
        if not session.get('uid') or endpoint=='static' or endpoint.startswith('psgc.'):return
        token=request.cookies.get('suji_device');row=trusted_device(session['uid'],token)
        proof=session.get('login_session')
        valid_session=bool(row and isinstance(proof,str) and len(proof)==64 and row['session_hash'] and secrets.compare_digest(core.sha(proof),row['session_hash']))
        if not valid_session:
            session.pop('login_session',None)
            session.pop('uid',None);g.pop('u',None)
            if endpoint in ('auth.login','auth.logout','auth.google_auth','auth.verify','owner_recovery.accept','owner_recovery.claim'):return
            flash('Please log in again. Devices inactive for seven days also require email verification.','info')
            return redirect(url_for('auth.login'))
        # Live dashboards poll in the background; polling is not user activity.
        if not endpoint.endswith('.live') and endpoint not in ('customer.orders_live','customer.notifications_live'):touch(row,token)
    @app.after_request
    def refresh_trusted_cookie(response):
        token=g.get('refresh_device_token')
        return set_cookie(response,token) if token else response
