"""Expiring email codes and single-use grants for the existing reset screens."""
import secrets
import time
import core


def initialize():
    core.db().execute('''CREATE TABLE IF NOT EXISTS password_reset_requests (
        email VARCHAR(254) PRIMARY KEY, user_id INTEGER NOT NULL,
        code_hash VARCHAR(255) NOT NULL, expires_at DOUBLE NOT NULL,
        sent_at DOUBLE NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
        sends INTEGER NOT NULL DEFAULT 1, grant_hash VARCHAR(64) NULL,
        grant_expires_at DOUBLE NULL)''')
    core.db().commit()


def request_code(user):
    import employee_invitations
    if not employee_invitations.is_active(user['id']):return False
    initialize()
    now = time.time()
    row = core.q('SELECT * FROM password_reset_requests WHERE email=?', (user['email'],), one=True)
    if row and row['expires_at'] > now and (row['sent_at'] + 60 > now or row['sends'] >= 5 or row['attempts'] >= 5):
        return False
    code = str(secrets.randbelow(900000) + 100000)
    hashed = core.generate_password_hash(code)
    try:
        if row and row['expires_at'] > now:
            changed = core.db().execute('''UPDATE password_reset_requests
                SET code_hash=?,sent_at=?,sends=sends+1,grant_hash=NULL,grant_expires_at=NULL
                WHERE email=? AND sent_at=? AND attempts<5 AND sends<5''',
                (hashed, now, user['email'], row['sent_at']))
            if not changed.rowcount:
                core.db().rollback()
                return False
        else:
            core.db().execute('DELETE FROM password_reset_requests WHERE email=?', (user['email'],))
            core.db().execute('''INSERT INTO password_reset_requests
                (email,user_id,code_hash,expires_at,sent_at) VALUES (?,?,?,?,?)''',
                (user['email'], user['id'], hashed, now + 600, now))
        core.send_code(user['email'], user['first_name'], code, 'reset your password')
        core.db().commit()
        return True
    except Exception:
        core.db().rollback()
        return False


def check(email, code, consume=False):
    initialize()
    row = core.q('SELECT * FROM password_reset_requests WHERE email=?', (email,), one=True)
    invalid = 'Code expired or too many attempts. Request a new reset code.'
    if not row or row['expires_at'] <= time.time() or row['attempts'] >= 5 or row['grant_hash']:
        return False, invalid
    claimed=core.db().execute('''UPDATE password_reset_requests SET attempts=attempts+1
        WHERE email=? AND code_hash=? AND attempts<5 AND expires_at>? AND grant_hash IS NULL''',(email,row['code_hash'],time.time()))
    core.db().commit()
    if not claimed.rowcount:return False,invalid
    if not core.check_password_hash(row['code_hash'],str(code).strip()):return False,'Wrong code. Check your email and try again.'
    if not consume:
        return True, 'Code is valid.'
    grant = secrets.token_urlsafe(32)
    changed = core.db().execute('''UPDATE password_reset_requests SET grant_hash=?,grant_expires_at=?
        WHERE email=? AND code_hash=? AND grant_hash IS NULL AND attempts<=5 AND expires_at>?''',
        (core.sha(grant), time.time() + 600, email, row['code_hash'], time.time()))
    core.db().commit()
    return (True, grant) if changed.rowcount else (False, invalid)


def active(grant):
    if not isinstance(grant, str) or not 20 <= len(grant) <= 128:
        return False
    initialize()
    return bool(core.q('SELECT user_id FROM password_reset_requests WHERE grant_hash=? AND grant_expires_at>?',
                       (core.sha(grant), time.time()), one=True))


def update(grant, password):
    if not active(grant) or not isinstance(password, str) or not 8 <= len(password) <= 128 or not core.PW.fullmatch(password):
        return False
    row = core.q('SELECT * FROM password_reset_requests WHERE grant_hash=? AND grant_expires_at>?',
                 (core.sha(grant), time.time()), one=True)
    if not row:
        return False
    import employee_invitations
    if not employee_invitations.is_active(row['user_id']):return False
    try:
        consumed = core.db().execute('DELETE FROM password_reset_requests WHERE grant_hash=? AND grant_expires_at>?',
                                     (core.sha(grant), time.time()))
        if not consumed.rowcount:
            core.db().rollback()
            return False
        core.db().execute('UPDATE users SET password_hash=?,failed_logins=0,locked_until=NULL WHERE id=?',
                          (core.generate_password_hash(password), row['user_id']))
        __import__('security').revoke_credentials(row['user_id'])
        import ops
        ops.audit('account.password_reset', 'user', row['user_id'], {'via': 'verified reset email'})
        core.db().commit()
        return True
    except Exception:
        core.db().rollback()
        raise
