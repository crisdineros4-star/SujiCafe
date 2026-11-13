"""Role-safe employee edits and deactivation; role changes are not accepted here."""
import time
import core
import employee_invitations as invitations
import accounts
import ops
import email_validation
from registration_policy import validate_name_policy, validate_email_policy


def initialize():
    core.db().execute('''CREATE TABLE IF NOT EXISTS account_access (
        user_id INTEGER PRIMARY KEY, disabled_at DOUBLE NULL, disabled_by INTEGER NULL,
        reason VARCHAR(255) NOT NULL DEFAULT '',
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)''')
    core.db().commit()


def disabled(uid):
    return bool(core.q('SELECT user_id FROM account_access WHERE user_id=? AND disabled_at IS NOT NULL',(uid,),one=True))


def target(uid):
    actor=ops.actor('manage_accounts')
    user=core.q('SELECT * FROM users WHERE id=?',(uid,),one=True)
    if not user or user['id']==actor['id'] or user['role']=='owner':
        raise ValueError('Use your own account settings. Owner access cannot be changed here.')
    if user['role'] not in ('staff','rider','admin') or user['role']=='admin' and actor['role']!='owner':
        from flask import abort
        abort(403)
    return user


def set_enabled(uid,enabled,reason=''):
    user=target(uid);reason=reason.strip()
    if core.mysql_enabled():core.db().execute('SELECT id FROM users WHERE id=? FOR UPDATE',(uid,)).fetchone()
    else:core.db().execute('UPDATE users SET id=id WHERE id=?',(uid,))
    if not enabled:
        if not 5<=len(reason)<=255:raise ValueError('Give a 5–255 character reason for deactivation.')
        if user['role']=='rider' and core.q("SELECT id FROM orders WHERE rider_id=? AND status IN ('ready','picked_up','out_for_delivery') LIMIT 1",(uid,),one=True):
            raise ValueError('Resolve or reassign this rider’s active deliveries before deactivation.')
    d=core.db();row=core.q('SELECT user_id FROM account_access WHERE user_id=?',(uid,),one=True)
    if row:d.execute('UPDATE account_access SET disabled_at=?,disabled_by=?,reason=? WHERE user_id=?',(None if enabled else time.time(),core.current_user()['id'],'' if enabled else reason,uid))
    else:d.execute('INSERT INTO account_access(user_id,disabled_at,disabled_by,reason) VALUES (?,?,?,?)',(uid,None if enabled else time.time(),core.current_user()['id'],'' if enabled else reason))
    if not enabled:
        __import__('security').revoke_credentials(uid)
        d.execute("UPDATE employee_invitations SET status='cancelled',token_hash=NULL WHERE user_id=? AND status='pending'",(uid,))
    ops.audit('account.enabled' if enabled else 'account.disabled','user',uid,{'role':user['role'],'reason':reason if not enabled else ''})


def edit(uid,form):
    user=target(uid)
    invitation=core.q('SELECT status FROM employee_invitations WHERE user_id=?',(uid,),one=True)
    pending=invitation and invitation['status']!='active'
    if pending:
        values={key:user[key] for key in ('first_name','last_name','phone')}
    else:
        values={key:form.get(key,'').strip() for key in ('first_name','last_name','phone')}
        for key in ('first_name','last_name'):validate_name_policy(values[key],key.replace('_',' ').title())
        if any(not core.NAME.fullmatch(values[k]) for k in ('first_name','last_name')):raise ValueError('Enter valid first and last names.')
        if core.phone_error(values['phone']):raise ValueError(core.phone_error(values['phone']))
        if values['phone']!=user['phone'] and accounts.taken(values['phone'],uid):raise ValueError('This mobile number is already registered.')
    email=form.get('email',user['email']).strip().lower()
    invitation=core.q('SELECT status FROM employee_invitations WHERE user_id=?',(uid,),one=True)
    pending=invitation and invitation['status']!='active'
    if email!=user['email'].lower():
        if not pending:raise ValueError('An active account’s sign-in email cannot be changed here.')
        validate_email_policy(email);email_validation.validate_email_domain(email)
        if not core.EMAIL.fullmatch(email) or core.user_by_email(email):raise ValueError('Use a valid, unregistered email address.')
        if email in {core.config.OWNER_EMAIL,core.config.ADMIN_EMAIL}-{''}:raise ValueError('This email is reserved for owner setup.')
    d=core.db()
    try:
        if values['phone']!=user['phone']:accounts.claim(values['phone'],uid)
        d.execute('UPDATE users SET first_name=?,last_name=?,phone=?,email=? WHERE id=?',(values['first_name'],values['last_name'],values['phone'],email,uid))
        if email!=user['email'].lower():invitations.resend(uid)
        ops.audit('account.details_edited','user',uid,{'role':user['role'],'email_reinvited':email!=user['email'].lower()})
    except Exception as exc:
        d.rollback()
        if isinstance(exc,core.sqlite3.IntegrityError) or type(exc).__name__=='IntegrityError':raise ValueError('Email or mobile number is already registered. Refresh and try again.') from exc
        raise


def disabled_ids():
    return {r['user_id'] for r in core.q('SELECT user_id FROM account_access WHERE disabled_at IS NOT NULL')}
