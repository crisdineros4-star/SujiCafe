"""Shared mobile-number uniqueness for all Suji Cafe account roles."""
import re
import core

DUPLICATE_MESSAGE = 'This mobile number is already registered. Please log in or recover your account.'


def normalize(phone):
    """Convert Philippine mobile formats to 09XXXXXXXXX."""
    value = re.sub(r'[\s().-]', '', str(phone or '').strip())
    if value.startswith('+63'):
        value = '0' + value[3:]
    elif value.startswith('63') and len(value) == 12:
        value = '0' + value[2:]
    return value if re.fullmatch(r'09\d{9}', value) else None


def initialize():
    db = core.db()
    db.execute('''CREATE TABLE IF NOT EXISTS account_phones (
        phone VARCHAR(11) PRIMARY KEY, user_id INTEGER NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)''')
    # Keep existing ownership; detect legacy conflicts rather than overwriting them.
    for user in core.q("SELECT id,phone FROM users WHERE phone IS NOT NULL AND phone<>'' ORDER BY id"):
        number = normalize(user['phone'])
        if not number:
            continue
        owner = core.q('SELECT user_id FROM account_phones WHERE phone=?', (number,), one=True)
        if not owner and not taken(number, user['id']):
            db.execute('INSERT INTO account_phones(phone,user_id) VALUES (?,?)', (number,user['id']))
    db.commit()


def taken(phone, except_id=None):
    number = normalize(phone)
    if not number:
        return False
    excluded = except_id if except_id is not None else -1
    owner = core.q('SELECT user_id FROM account_phones WHERE phone=?', (number,), one=True)
    if owner and owner['user_id'] != excluded:
        return True
    for user in core.q("SELECT id,phone FROM users WHERE phone IS NOT NULL AND phone<>''"):
        if user['id'] != excluded and normalize(user['phone']) == number:
            return True
    return False


def claim(phone, user_id):
    number = normalize(phone)
    if not number or core.phone_error(number):
        raise ValueError('Mobile number must contain exactly 11 digits starting with 09.')
    if taken(number, user_id):
        raise ValueError(DUPLICATE_MESSAGE)
    db = core.db()
    owner = core.q('SELECT user_id FROM account_phones WHERE phone=?', (number,), one=True)
    if not owner:
        try:
            db.execute('INSERT INTO account_phones(phone,user_id) VALUES (?,?)', (number,user_id))
        except Exception as exc:
            if isinstance(exc, core.sqlite3.IntegrityError) or type(exc).__name__ == 'IntegrityError':
                raise ValueError(DUPLICATE_MESSAGE) from exc
            raise
    db.execute('DELETE FROM account_phones WHERE user_id=? AND phone<>?', (user_id,number))
