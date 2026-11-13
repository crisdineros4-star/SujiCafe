"""Server-terminal initiated, backed-up and email-verified Owner succession."""
import gzip,hashlib,json,os,re,secrets,sqlite3,time
from pathlib import Path
from html import escape
from flask import Blueprint,request,session,render_template,redirect,url_for,jsonify,flash,make_response,g
import click,core,config,security
from account_validation import details, password as validate_password

bp=Blueprint('owner_recovery',__name__)
LIFETIME=3600
BACKUP_ROOT=Path(core.BASE)/'private/owner-recovery'

def initialize():
    d=core.db()
    d.execute('''CREATE TABLE IF NOT EXISTS owner_transfers (
      id VARCHAR(32) PRIMARY KEY, old_owner_id INTEGER NOT NULL, new_owner_id INTEGER NULL,
      recipient_email VARCHAR(254) NOT NULL, token_hash VARCHAR(64) NULL UNIQUE,
      status VARCHAR(20) NOT NULL, requested_by VARCHAR(120) NOT NULL,
      approval_reference VARCHAR(255) NOT NULL, reason VARCHAR(500) NOT NULL,
      backup_path VARCHAR(500) NOT NULL, backup_sha256 VARCHAR(64) NOT NULL,
      created_at DOUBLE NOT NULL, expires_at DOUBLE NOT NULL, completed_at DOUBLE NULL,
      FOREIGN KEY(old_owner_id) REFERENCES users(id),
      FOREIGN KEY(new_owner_id) REFERENCES users(id))''')
    d.execute('''CREATE TABLE IF NOT EXISTS owner_recovery_state (
      slot INTEGER PRIMARY KEY, active_transfer VARCHAR(32) NULL)''')
    if core.mysql_enabled():d.execute('INSERT IGNORE INTO owner_recovery_state(slot) VALUES (1)')
    else:d.execute('INSERT OR IGNORE INTO owner_recovery_state(slot) VALUES (1)')
    d.commit()

def _text(value,label,minimum,maximum):
    value=str(value).strip()
    if not minimum<=len(value)<=maximum or any(ord(c)<32 for c in value):
        raise ValueError(f'{label} must be {minimum}–{maximum} characters without control characters.')
    return value

def _sha_file(path):
    result=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):result.update(chunk)
    return result.hexdigest()

def _backup_path(row):
    path=(Path(core.BASE)/row['backup_path']).resolve()
    if not path.is_relative_to(BACKUP_ROOT.resolve()) or not path.is_file():
        raise ValueError('The required private database backup is missing. Ask the technical administrator to cancel and prepare a new transfer.')
    if not secrets.compare_digest(_sha_file(path),row['backup_sha256']):
        raise ValueError('The private backup integrity check failed. No ownership was changed.')
    return path

def create_backup(transfer_id):
    """SQLite online backup or consistent InnoDB SQL snapshot; never printed/served."""
    folder=BACKUP_ROOT/transfer_id;folder.mkdir(parents=True,mode=0o700,exist_ok=False)
    path=folder/('before-transfer.sql.gz' if core.mysql_enabled() else 'before-transfer.sqlite')
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(descriptor)
    try:
        if not core.mysql_enabled():
            with sqlite3.connect(core.DB) as source,sqlite3.connect(path) as target:source.backup(target)
        else:
            import pymysql
            options=core.mysql_connection_options();options['cursorclass']=pymysql.cursors.Cursor
            with pymysql.connect(**options) as conn:
                with conn.cursor() as cur:
                    cur.execute('SELECT TABLE_NAME,ENGINE FROM information_schema.tables WHERE table_schema=%s AND TABLE_TYPE=%s',(config.MYSQL_DATABASE,'BASE TABLE'))
                    tables=cur.fetchall()
                    if not tables or any(engine!='InnoDB' for _,engine in tables):raise ValueError('A consistent recovery backup requires InnoDB application tables.')
                    conn.rollback() # Metadata SELECT may open a transaction on MySQL.
                    cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                    cur.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT')
                with gzip.open(path,'wt',encoding='utf-8',newline='\n') as out:
                    out.write('-- Private Suji database backup before Owner succession. Restore to a NEW empty database.\nSET NAMES utf8mb4;\nSET FOREIGN_KEY_CHECKS=0;\n')
                    for name,_ in sorted(tables):
                        quoted='`'+name.replace('`','``')+'`'
                        with conn.cursor() as cur:
                            cur.execute('SHOW CREATE TABLE '+quoted);out.write(cur.fetchone()[1]+';\n')
                        with conn.cursor(pymysql.cursors.SSCursor) as cur:
                            cur.execute('SELECT * FROM '+quoted)
                            columns=','.join('`'+c[0].replace('`','``')+'`' for c in cur.description)
                            while True:
                                rows=cur.fetchmany(250)
                                if not rows:break
                                for row in rows:
                                    values=','.join(conn.escape(v) for v in row)
                                    out.write(f'INSERT INTO {quoted} ({columns}) VALUES ({values});\n')
                    out.write('SET FOREIGN_KEY_CHECKS=1;\n')
                conn.rollback()
        return path.relative_to(Path(core.BASE)).as_posix(),_sha_file(path)
    except Exception:
        path.unlink(missing_ok=True)
        raise

def send_transfer(email,token):
    from employee_invitations import public_url
    from email_service import EmailService
    link=public_url(token).replace('/activate-account?token=','/owner-recovery#token=')
    EmailService(config).send(email,'Suji Café: authorized Owner transfer',
        'An authorized technical operator prepared an Owner transfer for Suji Café. '
        'Open this private link to verify this inbox, enter your own details and set your own password:\n'+link+
        '\nThe link expires in one hour and is single-use. Existing ownership changes only after valid acceptance. '
        'If this was unexpected, do not accept; contact the café and its technical administrator.',
        '<p>An authorized technical operator prepared a Suji Café Owner transfer.</p>'
        f'<p><a href="{escape(link,quote=True)}">Verify email and accept Owner transfer</a></p>'
        '<p>Enter your own details and choose a private password. This link expires in one hour and can be used once. '
        'If unexpected, do not accept; contact the café and its technical administrator.</p>')

class OwnerRecoveryService:
    """Only prepare/cancel are terminal operations; a private proof authorizes acceptance."""
    def _lock(self):
        d=core.db()
        if core.mysql_enabled():d.execute('SELECT slot FROM owner_recovery_state WHERE slot=1 FOR UPDATE').fetchone()
        else:d.execute('UPDATE owner_recovery_state SET slot=slot WHERE slot=1')
    def _owners(self):
        return core.db().execute("SELECT * FROM users WHERE role='owner'"+(' FOR UPDATE' if core.mysql_enabled() else '')).fetchall()
    def _audit(self,event,tid,info):
        import ops
        ops.audit('owner_recovery.'+event,'owner_transfer',None,dict(info,transfer_id=tid))
    def find(self,proof):
        if not isinstance(proof,str) or len(proof)!=64:return None
        return core.q('''SELECT t.* FROM owner_transfers t JOIN owner_recovery_state s ON s.active_transfer=t.id
          JOIN users u ON u.id=t.old_owner_id WHERE s.slot=1 AND t.token_hash=? AND t.status='pending'
          AND t.expires_at>? AND u.role='owner' ''',(proof,time.time()),one=True)
    def prepare(self,current_email,new_email,operator,approval,reason):
        # This method is only called by the local CLI; there is no initiating HTTP route.
        from registration_policy import validate_email_policy
        import email_validation
        from employee_invitations import public_url
        new_email=str(new_email).strip().lower();current_email=str(current_email).strip().lower()
        if len(new_email)>254 or not core.EMAIL.fullmatch(new_email):raise ValueError('Enter a complete valid new Owner email.')
        validate_email_policy(new_email);email_validation.validate_email_domain(new_email)
        operator=_text(operator,'Operator',2,120);approval=_text(approval,'Approval reference',5,255);reason=_text(reason,'Reason',10,500)
        public_url('configuration-check')
        owners=core.q("SELECT * FROM users WHERE role='owner'")
        current=core.user_by_email(current_email)
        if len(owners)!=1 or not current or current['id']!=owners[0]['id']:
            raise ValueError('Specify the current Owner email. Exactly one existing Owner is required; use first-time setup if none exists.')
        if core.user_by_email(new_email):raise ValueError('Use a new, unregistered email for the successor. Existing accounts are not silently promoted or overwritten.')
        active=core.q("SELECT t.id FROM owner_transfers t JOIN owner_recovery_state s ON s.active_transfer=t.id WHERE t.status='pending' AND t.expires_at>?",(time.time(),),one=True)
        if active:raise ValueError('A pending transfer already exists. Review/cancel it in the terminal before preparing another.')
        core.db().rollback() # End metadata read transactions before taking a consistent backup.
        tid=secrets.token_hex(16);token=secrets.token_urlsafe(32)
        path,digest=create_backup(tid)
        d=core.db()
        try:
            self._lock();owners=self._owners()
            if len(owners)!=1 or owners[0]['id']!=current['id']:raise ValueError('Ownership changed while preparing. No transfer was created.')
            active=d.execute("SELECT t.* FROM owner_transfers t JOIN owner_recovery_state s ON s.active_transfer=t.id WHERE s.slot=1").fetchone()
            if active and active['status']=='pending' and active['expires_at']>time.time():raise ValueError('Another pending transfer was prepared. Review it before retrying.')
            if core.user_by_email(new_email):raise ValueError('The successor email was registered meanwhile. Choose another unused email.')
            if active and active['status']=='pending':d.execute("UPDATE owner_transfers SET status='expired',token_hash=NULL WHERE id=?",(active['id'],))
            now=time.time()
            d.execute('''INSERT INTO owner_transfers(id,old_owner_id,recipient_email,token_hash,status,requested_by,
              approval_reference,reason,backup_path,backup_sha256,created_at,expires_at)
              VALUES (?,?,?,?,'pending',?,?,?,?,?,?,?)''',
              (tid,current['id'],new_email,core.sha(token),operator,approval,reason,path,digest,now,now+LIFETIME))
            d.execute('UPDATE owner_recovery_state SET active_transfer=? WHERE slot=1',(tid,))
            send_transfer(new_email,token)
            self._audit('prepared',tid,{'old_owner_id':current['id'],'recipient_email':new_email,'operator':operator,'approval_reference':approval,'reason':reason,'backup_sha256':digest})
            d.commit();return tid,path
        except Exception as exc:
            d.rollback()
            if isinstance(exc,ValueError):raise
            raise ValueError('The transfer could not be prepared or emailed. No access was changed. A completed private backup, if created, was retained.') from exc
    def cancel(self,tid,operator,reason):
        operator=_text(operator,'Operator',2,120);reason=_text(reason,'Reason',10,500)
        d=core.db()
        try:
            self._lock()
            row=d.execute('SELECT * FROM owner_transfers WHERE id=?',(tid,)).fetchone()
            if not row or row['status']!='pending':raise ValueError('Only a pending transfer can be cancelled.')
            d.execute("UPDATE owner_transfers SET status='cancelled',token_hash=NULL WHERE id=?",(tid,))
            d.execute('UPDATE owner_recovery_state SET active_transfer=NULL WHERE slot=1 AND active_transfer=?',(tid,))
            self._audit('cancelled',tid,{'operator':operator,'reason':reason});d.commit()
        except Exception:d.rollback();raise
    def accept(self,proof,form):
        import accounts
        values=details(form);validate_password(form.get('password',''),form.get('confirm',''))
        if form.get('accept_owner')!='yes':raise ValueError('Confirm that you are the authorized successor accepting Owner responsibilities.')
        row=self.find(proof)
        if not row:raise ValueError('This transfer is unavailable, expired, cancelled or already completed.')
        _backup_path(row);core.db().rollback()
        d=core.db()
        try:
            self._lock();row=self.find(proof);owners=self._owners()
            if not row or len(owners)!=1 or owners[0]['id']!=row['old_owner_id']:raise ValueError('The transfer or current ownership changed. Ask the operator to review it.')
            if core.user_by_email(row['recipient_email']):raise ValueError('The successor email is now registered. Ask the operator to cancel this transfer and review the account.')
            if accounts.taken(values['phone']):raise ValueError('This mobile number is already registered. Enter your own unused mobile number.')
            uid=d.execute('''INSERT INTO users(first_name,middle_name,last_name,email,phone,birthdate,address,password_hash,role)
              VALUES (?,?,?,?,?,'','',?,'owner')''',(values['first_name'],values['middle_name'] or None,values['last_name'],row['recipient_email'],values['phone'],core.generate_password_hash(form['password']))).lastrowid
            accounts.claim(values['phone'],uid)
            changed=d.execute("UPDATE users SET role='former_owner' WHERE id=? AND role='owner'",(row['old_owner_id'],))
            if not changed.rowcount:raise ValueError('The former Owner changed. No transfer was completed.')
            old=row['old_owner_id'];now=time.time();reason='Owner succession completed: '+row['id']
            existing=d.execute('SELECT user_id FROM account_access WHERE user_id=?',(old,)).fetchone()
            if existing:d.execute('UPDATE account_access SET disabled_at=?,disabled_by=?,reason=? WHERE user_id=?',(now,uid,reason,old))
            else:d.execute('INSERT INTO account_access(user_id,disabled_at,disabled_by,reason) VALUES (?,?,?,?)',(old,now,uid,reason))
            security.revoke_credentials(old)
            d.execute("UPDATE owner_transfers SET status='completed',new_owner_id=?,completed_at=?,token_hash=NULL WHERE id=? AND status='pending'",(uid,now,row['id']))
            d.execute('UPDATE owner_recovery_state SET active_transfer=NULL WHERE slot=1',( ))
            self._audit('completed',row['id'],{'old_owner_id':old,'new_owner_id':uid,'approval_reference':row['approval_reference'],'operator':row['requested_by'],'backup_sha256':row['backup_sha256']})
            d.commit();return uid
        except Exception as exc:
            d.rollback()
            if isinstance(exc,ValueError):raise
            raise ValueError('Ownership could not be transferred. No partial ownership change was saved.') from exc

@bp.post('/owner-recovery/claim')
def claim():
    data=request.get_json(silent=True)
    token=data.get('token') if isinstance(data,dict) else None
    session.pop('owner_recovery_proof',None)
    row=OwnerRecoveryService().find(core.sha(token)) if isinstance(token,str) and re.fullmatch(r'[A-Za-z0-9_-]{40,128}',token) else None
    if not row:return jsonify(ok=False,msg='This transfer link is unavailable, expired, cancelled or already completed.'),400
    session['owner_recovery_proof']=core.sha(token)
    return jsonify(ok=True,redirect=url_for('owner_recovery.accept'))

@bp.route('/owner-recovery',methods=['GET','POST'])
def accept():
    service=OwnerRecoveryService();proof=session.get('owner_recovery_proof');row=service.find(proof);error=None
    if request.method=='POST' and row:
        try:uid=service.accept(proof,request.form)
        except ValueError as exc:error=str(exc)
        else:
            token=request.cookies.get('suji_device');signed=session.get('uid')
            if signed and token and len(token)==64:core.run('UPDATE trusted_devices SET session_hash=NULL WHERE user_id=? AND token_hash=?',(signed,core.sha(token)))
            session.clear();session['csrf']=secrets.token_hex(32);g.pop('u',None);g.pop('refresh_device_token',None)
            flash('Owner transfer completed. Sign in using your own verified email and new password.','success')
            import device_trust
            return device_trust.remember(uid,make_response(redirect(url_for('auth.login'))))
    if not row:session.pop('owner_recovery_proof',None)
    response=make_response(render_template('auth/owner_recovery.html',transfer=row,field_error=error),200 if row or request.method=='GET' else 400)
    response.headers['Referrer-Policy']='no-referrer';response.headers['Cache-Control']='private, no-store';return response

def register_commands(app):
    @app.cli.group('owner-recovery')
    def commands():
        """Authorized, backed-up ownership succession. Preparation is terminal-only."""
    @commands.command('prepare')
    @click.option('--current-owner',required=True)
    @click.option('--new-email',required=True)
    @click.option('--operator',required=True)
    @click.option('--approval-reference',required=True)
    @click.option('--reason',required=True)
    @click.option('--yes',is_flag=True,help='Skip the local review prompt after obtaining business authorization.')
    def prepare(current_owner,new_email,operator,approval_reference,reason,yes):
        click.echo('Prepare an email-verified Owner succession: '+current_owner+' -> '+new_email)
        click.echo('The current Owner remains unchanged until the successor verifies the email and accepts. A private database backup is required and will be created.')
        if not yes:click.confirm('Do you have authorization from the business and want to prepare this transfer?',abort=True)
        try:tid,path=OwnerRecoveryService().prepare(current_owner,new_email,operator,approval_reference,reason)
        except ValueError as exc:raise click.ClickException(str(exc)) from exc
        except Exception as exc:raise click.ClickException('Recovery preparation failed. No ownership was transferred; check database/backup/email setup.') from exc
        click.echo('Transfer ID: '+tid+'\nStatus: pending email acceptance (expires in one hour).\nPrivate backup: '+path)
        click.echo('No token/password is printed. After completion, update private OWNER_EMAIL to the successor email; retain the existing SECRET_KEY.')
    @commands.command('status')
    @click.option('--transfer-id',default=None)
    def status(transfer_id):
        for owner in core.q("SELECT id,email,first_name,last_name FROM users WHERE role='owner'"):
            click.echo('Current Owner: '+json.dumps(dict(owner),ensure_ascii=False))
        rows=core.q('SELECT id,old_owner_id,new_owner_id,recipient_email,status,created_at,expires_at FROM owner_transfers'+(' WHERE id=?' if transfer_id else ' ORDER BY created_at DESC LIMIT 10'),(transfer_id,) if transfer_id else ())
        for row in rows:
            info=dict(row)
            if info['status']=='pending' and info['expires_at']<=time.time():info['status']='expired'
            click.echo(json.dumps(info,ensure_ascii=False))
        if not rows:click.echo('No recovery transfer found.')
    @commands.command('cancel')
    @click.option('--transfer-id',required=True)
    @click.option('--operator',required=True)
    @click.option('--reason',required=True)
    def cancel(transfer_id,operator,reason):
        try:OwnerRecoveryService().cancel(transfer_id,operator,reason)
        except ValueError as exc:raise click.ClickException(str(exc)) from exc
        click.echo('Pending transfer cancelled. Owner access was not changed.')
