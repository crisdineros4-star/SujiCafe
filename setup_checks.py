"""Local readiness and real SMTP verification commands; no secrets in output."""
import json
from datetime import datetime,timezone
from pathlib import Path
import click,config,core
from email_service import EmailService

def register_commands(app):
    @app.cli.command('check-setup')
    def check_setup():
        checks={
          'MySQL backend':core.mysql_enabled(),
          'Production security mode':app.config.get('PRODUCTION',False),
          'Secure session cookies':app.config['SESSION_COOKIE_SECURE'],
          'Host allowlist configured':bool(app.config.get('TRUSTED_HOSTS')),
          'MySQL account avoids server root':not core.mysql_enabled() or config.MYSQL_USER.lower()!='root',
          'Remote MySQL verifies TLS':not core.mysql_enabled() or config.MYSQL_HOST in ('localhost','127.0.0.1','::1') or bool(config.MYSQL_SSL_CA),
          'Database connection':False,
          'Private session secret':len(str(config.SECRET_KEY))>=32 and bool(__import__('os').environ.get('SECRET_KEY')) and 'replace' not in str(config.SECRET_KEY).lower(),
          'Reserved owner email':bool(config.OWNER_EMAIL),
          'Real SMTP credentials configured':EmailService(config).configured,
          'SMTP transport uses TLS':config.SMTP_SECURITY in ('ssl','starttls'),
          'Development OTP printing disabled':not config.DEV_PRINT_OTP,
          'Google sign-in configured (optional)':bool(config.GOOGLE_CLIENT_ID)}
        try:core.q('SELECT 1 AS ok',one=True);checks['Database connection']=True
        except Exception:pass
        for name,ok in checks.items():click.echo(('READY: ' if ok else 'SETUP NEEDED: ')+name)
        click.echo('Configuration checks do not prove email inbox delivery, Google login or payment receipt. Follow docs/SETUP.md and docs/EMAIL_SETUP.md.')
    @app.cli.command('test-email')
    @click.option('--to',required=True,help='Your own inbox to verify actual delivery.')
    def test_email(to):
        if not core.EMAIL.fullmatch(to) or len(to)>254:raise click.ClickException('Enter a valid recipient email address.')
        now=datetime.now(timezone.utc);marker='SUJI-'+now.strftime('%Y%m%d%H%M%S')
        try:EmailService(config).send(to,'SUJI Café email delivery check '+marker,'This is your requested SMTP check. Verification ID: '+marker+'. Confirm this message arrived in your inbox or spam folder. No customer transaction was created.')
        except Exception as exc:
            raise click.ClickException('The SMTP server did not accept the test. Check sender credentials, host/port/TLS and outbound access. No inbox delivery has been verified.') from exc
        folder=Path(core.BASE)/'private/verification';folder.mkdir(parents=True,exist_ok=True)
        (folder/(marker+'.json')).write_text(json.dumps({'verification_id':marker,'requested_at_utc':now.isoformat(),'smtp_accepted':True,'inbox_receipt_confirmed':False},indent=2))
        click.echo('SMTP server accepted '+marker+'. Open your recipient inbox/spam and confirm receipt. Acceptance alone does not prove delivery. Evidence metadata was saved privately; no password or OTP was saved.')
