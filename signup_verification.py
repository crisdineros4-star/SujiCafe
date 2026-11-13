"""Inbox ownership proof; pending details and password hashes stay server-side."""
import json
import math
import secrets
import time
from flask import session
import core


def initialize():
    core.db().execute('''CREATE TABLE IF NOT EXISTS signup_verifications (
        token VARCHAR(64) PRIMARY KEY, email VARCHAR(254) NOT NULL UNIQUE,
        payload TEXT NOT NULL, code_hash VARCHAR(255) NOT NULL,
        expires_at DOUBLE NOT NULL, sent_at DOUBLE NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0, sends INTEGER NOT NULL DEFAULT 1)''')
    core.db().commit()


def pending():
    """Return only a live verification for this browser session."""
    token = session.get('registration_token')
    if not token:
        return None
    initialize()
    row = core.q('SELECT * FROM signup_verifications WHERE token=?', (token,), one=True)
    if not row or row['expires_at'] <= time.time():
        session.pop('registration_token', None)
        return None
    return row



def _resend_for(row, replacement_payload=None):
    """Rotate a pending OTP after 60 s, with 10-minute validity from this send.

    Keep the original token and total attempt/send limits so going Back or
    changing browser never bypasses the rate limits.
    """
    now = time.time()
    if not row or row['expires_at'] <= now:
        return False, 'This code has expired. Start sign up to request a new code.'
    if row['sent_at'] + 60 > now:
        remaining = max(1, math.ceil(row['sent_at'] + 60 - now))
        return False, f'Please wait {remaining} seconds before resending. You can still use your latest code.'
    if row['sends'] >= 5 or row['attempts'] >= 5:
        return False, 'Code request limit reached. Please use the latest code or start over when it expires.'

    payload = json.loads(row['payload']) if replacement_payload is None else replacement_payload
    code = str(secrets.randbelow(900000) + 100000)
    # Conditional update protects against two parallel sends for the same row.
    changed = core.db().execute("""UPDATE signup_verifications
         SET code_hash=?, sent_at=?, expires_at=?, sends=sends+1, payload=?
         WHERE token=? AND sent_at=? AND expires_at>? AND sends<5 AND attempts<5""",
        (core.generate_password_hash(code), now, now + 600, json.dumps(payload),
         row['token'], row['sent_at'], now))
    if not changed.rowcount:
        core.db().rollback()
        return False, 'A code request is being processed. Refresh the page and try again.'
    try:
        core.send_code(row['email'], payload['first_name'], code, 'verify your sign-up email')
        core.db().commit()
    except Exception:
        core.db().rollback()
        return False, 'Email could not be sent. Please check your connection and try again.'
    return True, 'New code sent. The previous code was replaced. This code is valid for 10 minutes.'


def start(form):
    """Start or resume signup without enforcing a 10-minute wait to resend."""
    initialize()
    now = time.time()
    core.db().execute('DELETE FROM signup_verifications WHERE expires_at<?', (now,))
    core.db().commit()
    current = pending()
    payload = {key: form[key] for key in
               ('first_name', 'middle_name', 'last_name', 'email', 'phone', 'birthdate', 'address')}
    payload['password_hash'] = core.generate_password_hash(form['password'])
    if current and current['email'].lower() == form['email'].lower():
        if current['attempts'] >= 5:
            return False, 'Too many incorrect codes. Please wait until your current code expires.'
        # Preserve the existing code, send timestamp and security counters.
        core.db().execute('UPDATE signup_verifications SET payload=? WHERE token=? AND expires_at>?',
                          (json.dumps(payload), current['token'], now))
        core.db().commit()
        return True, 'Your verification is still active; no new code was sent. Enter your latest code or select Resend code after 60 seconds.'

    # A browser restart can lose the session while a verification remains in
    # the database. Re-use it instead of waiting for its 10-minute expiry or
    # failing the UNIQUE(email) insertion.
    existing = core.q('SELECT * FROM signup_verifications WHERE email=?',
                      (form['email'],), one=True)
    if existing:
        if existing['attempts'] >= 5 or existing['sends'] >= 5:
            return False, 'Verification request limit reached. Use your latest code or start over once it expires.'
        session['registration_token'] = existing['token']
        if existing['sent_at'] + 60 > now:
            remaining = max(1, math.ceil(existing['sent_at'] + 60 - now))
            return True, f'You already have a code. Enter it now, or resend in {remaining} seconds.'
        return _resend_for(existing, replacement_payload=payload)

    token = secrets.token_hex(32)
    code = str(secrets.randbelow(900000) + 100000)
    try:
        core.db().execute('INSERT INTO signup_verifications(token,email,payload,code_hash,expires_at,sent_at) VALUES (?,?,?,?,?,?)',
                          (token, form['email'], json.dumps(payload), core.generate_password_hash(code), now + 600, now))
        core.send_code(form['email'], form['first_name'], code, 'verify your sign-up email')
        core.db().commit()
    except Exception:
        core.db().rollback()
        return False, 'Could not send a verification code. If one was sent recently, check your inbox or try again after 60 seconds.'
    session['registration_token'] = token
    return True, 'A verification code was sent. You can request another code after 60 seconds.'


def resend():
    return _resend_for(pending())


def complete(code):
    row = pending()
    if not row or row['expires_at'] <= time.time() or row['attempts'] >= 5:
        return False, 'Code expired or too many attempts. Start sign up again.'
    # Count all attempts atomically, including valid ones, before checking the hash.
    changed = core.db().execute('UPDATE signup_verifications SET attempts=attempts+1 WHERE token=? AND code_hash=? AND attempts<5 AND expires_at>?',
                              (row['token'], row['code_hash'], time.time()))
    core.db().commit()
    if not changed.rowcount:
        return False, 'Code expired or too many attempts. Start sign up again.'
    if not core.check_password_hash(row['code_hash'], code.strip()):
        return False, 'Wrong code. Check your email and try again.'
    import accounts
    import ops
    f = json.loads(row['payload'])
    try:
        consumed = core.db().execute('DELETE FROM signup_verifications WHERE token=? AND code_hash=? AND expires_at>?',
                                    (row['token'], row['code_hash'], time.time()))
        if not consumed.rowcount:
            core.db().rollback()
            return False, 'Code was already used or replaced. Try the latest code.'
        uid = core.db().execute('INSERT INTO users (first_name,middle_name,last_name,email,phone,birthdate,address,password_hash,role) VALUES (?,?,?,?,?,?,?,?,?)',
            (f['first_name'], f['middle_name'] or None, f['last_name'], f['email'], f['phone'], f['birthdate'], f['address'], f['password_hash'], 'customer')).lastrowid
        accounts.claim(f['phone'], uid)
        ops.audit('account.created', 'user', uid, {'role': 'customer', 'via': 'verified sign-up email'})
        core.db().commit()
    except Exception as exc:
        core.db().rollback()
        if isinstance(exc, (ValueError, core.sqlite3.IntegrityError)) or type(exc).__name__ == 'IntegrityError':
            return False, 'Email or mobile number is already registered. Log in or restart sign up.'
        raise
    session.pop('registration_token', None)
    return True, 'Email verified. Account created successfully. You can now log in.'


def finish_with_existing_code(email, code):
    """Recover an interrupted sign-up only by proving access to its emailed OTP.

    Never authenticate a browser based only on the supplied email address.
    The normal complete() function consumes an attempt and is single-use.
    """
    initialize()
    email = str(email).strip().lower()
    if len(email) > 254 or not email:
        return False, 'Check your email address and 6-digit code.'
    row = core.q('SELECT * FROM signup_verifications WHERE email=?', (email,), one=True)
    if not row or row['expires_at'] <= time.time():
        return False, 'No active code was found, or it expired. Return to sign up to request a new code.'
    if row['attempts'] >= 5:
        return False, 'Too many incorrect attempts. Wait until this code expires before registering again.'
    previous = session.get('registration_token')
    session['registration_token'] = row['token']
    try:
        return complete(code)
    finally:
        # Do not retain the session token after an unsuccessful recovery attempt.
        if session.get('registration_token') == row['token']:
            if previous is not None:
                session['registration_token'] = previous
            else:
                session.pop('registration_token', None)
