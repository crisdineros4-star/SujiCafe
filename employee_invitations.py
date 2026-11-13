"""Owner/Admin-approved employee invitations, separate from public registration."""
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit
from html import escape
import core
import config

LIFETIME = 24 * 60 * 60
COOLDOWN = 60
MAX_SENDS = 5


def initialize():
    core.db().execute('''CREATE TABLE IF NOT EXISTS employee_invitations (
        user_id INTEGER PRIMARY KEY, token_hash VARCHAR(64) NULL UNIQUE,
        status VARCHAR(20) NOT NULL DEFAULT 'pending', created_by INTEGER NOT NULL,
        created_at DOUBLE NOT NULL, sent_at DOUBLE NOT NULL, expires_at DOUBLE NOT NULL,
        send_count INTEGER NOT NULL DEFAULT 1, send_window_start DOUBLE NOT NULL,
        activated_at DOUBLE NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)''')
    core.db().commit()
    import account_management
    account_management.initialize()


def is_active(uid):
    import account_management
    if account_management.disabled(uid):return False
    row = core.q('SELECT status FROM employee_invitations WHERE user_id=?', (uid,), one=True)
    # Existing employees and all non-invited accounts remain active.
    return not row or row['status'] == 'active'


def public_url(token):
    base = getattr(config, 'PUBLIC_BASE_URL', '').strip().rstrip('/')
    parsed = urlsplit(base)
    local = parsed.hostname in ('localhost', '127.0.0.1', '::1')
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path or not (parsed.scheme == 'https' or parsed.scheme == 'http' and local)):
        raise ValueError('Invitation sending needs PUBLIC_BASE_URL in the private .env. Use your HTTPS website origin, or localhost for development.')
    return base + '/activate-account?token=' + token


def send_invitation(user, token):
    from email_service import EmailService
    link = public_url(token)
    name, role = 'there', str(user['role']).title()
    EmailService(config).send(
        user['email'], 'Suji Café: activate your ' + role + ' account',
        f'Hi {name},\n\nYou have been invited to join Suji Café as {role}.\n'
        f'Open this link to verify your email, enter your personal details and create your own password:\n{link}\n\n'
        'This invitation expires in 24 hours and can be used once. '
        'If you were not expecting this invitation, ignore it or contact the café.',
        f'<p>Hi {escape(name)},</p><p>You have been invited to join Suji Café as <strong>{escape(role)}</strong>.</p>'
        f'<p><a href="{escape(link, quote=True)}">Verify email and set your password</a></p>'
        '<p>This invitation expires in 24 hours and can be used once. '
        'If you were not expecting it, ignore this email or contact the café.</p>'
    )


def invite(form, role):
    import ops
    import accounts
    manager = ops.actor('create_admin' if role=='admin' else 'manage_accounts')
    if role not in ('staff', 'rider','admin'):
        raise ValueError('Choose a Staff, Rider or Admin invitation.')
    token = secrets.token_urlsafe(32)
    public_url(token)  # Validate deployment origin before reserving an account.
    now = time.time()
    d = core.db()
    try:
        uid = d.execute('''INSERT INTO users(first_name,last_name,email,phone,birthdate,address,password_hash,role)
            VALUES (?,?,?,?,?,?,?,?)''', ('', '', form['email'], '', '', '',
            core.generate_password_hash(secrets.token_urlsafe(48)), role)).lastrowid
        d.execute('''INSERT INTO employee_invitations
            (user_id,token_hash,status,created_by,created_at,sent_at,expires_at,send_window_start)
            VALUES (?,?,'pending',?,?,?,?,?)''', (uid, core.sha(token), manager['id'], now, now, now + LIFETIME, now))
        send_invitation(dict(form, role=role), token)
        ops.audit('account.invited', 'user', uid, {'role': role, 'expires_in_hours': 24})
        return uid
    except Exception as exc:
        d.rollback()
        if isinstance(exc, (core.sqlite3.IntegrityError, ValueError)) or type(exc).__name__ == 'IntegrityError':
            if isinstance(exc, ValueError):
                raise
            raise ValueError('Email or mobile number is already registered. No invitation account was created.') from exc
        raise ValueError('The invitation could not be sent. No account was created. Check email delivery settings and try again.') from exc


def resend(uid):
    import ops
    ops.actor('manage_accounts')
    row = core.q('''SELECT i.*,u.email,u.first_name,u.role FROM employee_invitations i
        JOIN users u ON u.id=i.user_id WHERE i.user_id=?''', (uid,), one=True)
    if not row or row['role'] not in ('staff', 'rider','admin') or row['status'] == 'active':
        raise ValueError('Choose a pending or cancelled Staff, Rider or Admin invitation.')
    if row['role']=='admin':ops.actor('create_admin')
    import account_management
    if account_management.disabled(uid):raise ValueError('Re-enable this account before sending an invitation.')
    now = time.time()
    if now < row['sent_at'] + COOLDOWN:
        raise ValueError('Wait 60 seconds before sending another invitation.')
    fresh = now - row['send_window_start'] >= LIFETIME
    if not fresh and row['send_count'] >= MAX_SENDS:
        raise ValueError('Five invitations were already sent in this 24-hour window. Try again later.')
    token = secrets.token_urlsafe(32)
    public_url(token)
    d = core.db()
    try:
        changed = d.execute('''UPDATE employee_invitations SET token_hash=?,status='pending',sent_at=?,
            expires_at=?,send_count=?,send_window_start=? WHERE user_id=? AND sent_at=? AND status<>'active' ''',
            (core.sha(token), now, now + LIFETIME, 1 if fresh else row['send_count'] + 1,
             now if fresh else row['send_window_start'], uid, row['sent_at']))
        if not changed.rowcount:
            raise ValueError('This invitation changed. Refresh before sending again.')
        send_invitation(row, token)
        ops.audit('account.invitation_resent', 'user', uid, {'role': row['role']})
    except Exception as exc:
        d.rollback()
        if isinstance(exc, ValueError):
            raise
        raise ValueError('The new invitation could not be sent. The previous invitation was kept.') from exc


def cancel(uid):
    import ops
    ops.actor('manage_accounts')
    user=core.q('SELECT role FROM users WHERE id=?',(uid,),one=True)
    if user and user['role']=='admin':ops.actor('create_admin')
    changed = core.db().execute('''UPDATE employee_invitations SET status='cancelled',token_hash=NULL
        WHERE user_id=? AND status='pending' ''', (uid,))
    if not changed.rowcount:
        raise ValueError('Only pending invitations can be cancelled. Active accounts were not changed.')
    ops.audit('account.invitation_cancelled', 'user', uid)


def find_by_hash(value):
    if not isinstance(value, str) or len(value) != 64:
        return None
    return core.q('''SELECT i.*,u.first_name,u.last_name,u.email,u.role FROM employee_invitations i
        JOIN users u ON u.id=i.user_id WHERE i.token_hash=? AND i.status='pending' AND i.expires_at>?
        AND u.role IN ('staff','rider','admin') AND NOT EXISTS (SELECT 1 FROM account_access a WHERE a.user_id=u.id AND a.disabled_at IS NOT NULL)''', (value, time.time()), one=True)


def activate(value, password, form=None):
    if not isinstance(password, str) or not 8 <= len(password) <= 128 or not core.PW.fullmatch(password):
        raise ValueError('Use 8–128 characters with uppercase, lowercase, a number and a symbol.')
    row = find_by_hash(value)
    if not row:
        raise ValueError('This invitation expired, was replaced, was cancelled, or was already used. Ask Owner/Admin for a new one.')
    from account_validation import details
    import accounts
    values=details(form or {})
    if accounts.taken(values['phone'],row['user_id']):raise ValueError('This mobile number is already registered.')
    d = core.db()
    try:
        changed = d.execute('''UPDATE employee_invitations SET status='active',activated_at=?,token_hash=NULL
            WHERE user_id=? AND token_hash=? AND status='pending' AND expires_at>?''',
            (time.time(), row['user_id'], value, time.time()))
        if not changed.rowcount:
            raise ValueError('This invitation is no longer valid. Request a new invitation.')
        accounts.claim(values['phone'],row['user_id'])
        d.execute('UPDATE users SET first_name=?,middle_name=?,last_name=?,phone=?,password_hash=?,failed_logins=0,locked_until=NULL WHERE id=? AND role=?',
                  (values['first_name'],values['middle_name'] or None,values['last_name'],values['phone'],core.generate_password_hash(password), row['user_id'], row['role']))
        d.execute('DELETE FROM trusted_devices WHERE user_id=?', (row['user_id'],))
        d.execute('DELETE FROM otp_codes WHERE user_id=?', (row['user_id'],))
        import ops
        ops.audit('account.activated', 'user', row['user_id'], {'role': row['role'], 'via': 'emailed invitation'})
        d.commit()
        return row['user_id']
    except Exception:
        d.rollback()
        raise


def summaries():
    result = {}
    for row in core.q('SELECT * FROM employee_invitations'):
        state = row['status']
        if state == 'pending' and row['expires_at'] <= time.time():
            state = 'expired'
        result[row['user_id']] = {'state': state, 'label': {'pending': 'Pending activation', 'expired': 'Invitation expired',
            'cancelled': 'Invitation cancelled', 'active': 'Active'}[state],
            'expires': datetime.fromtimestamp(row['expires_at'], timezone.utc).isoformat()}
    return result


def access_message(uid):
    import account_management
    return 'This account has been deactivated. Contact the Owner/Admin.' if account_management.disabled(uid) else 'This account is awaiting activation. Open the email invitation or ask Owner/Admin for a new one.'
