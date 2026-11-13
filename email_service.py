"""Real SMTP delivery with configurable TLS and no embedded credentials."""
from email.message import EmailMessage
from email.utils import parseaddr
from html import escape
import smtplib,ssl

class EmailService:
    def __init__(self,settings):self._settings=settings
    @property
    def configured(self):
        s=self._settings
        return bool(s.SMTP_HOST and s.SMTP_PORT and s.GMAIL_USER and s.GMAIL_APP_PASSWORD and s.SMTP_FROM)
    def send(self,to,subject,text,html=None):
        if not self.configured:raise ValueError('Email is not configured. Set SMTP and sender credentials in your private .env.')
        if '\n' in to or '\r' in to or parseaddr(to)[1]!=to:raise ValueError('Enter a valid recipient email address.')
        s=self._settings
        if s.SMTP_SECURITY not in ('ssl','starttls'):raise ValueError('SMTP_SECURITY must be ssl or starttls.')
        msg=EmailMessage();msg['Subject']=subject;msg['From']=s.SMTP_FROM;msg['To']=to;msg.set_content(text)
        if html:msg.add_alternative(html,subtype='html')
        factory=smtplib.SMTP_SSL if s.SMTP_SECURITY=='ssl' else smtplib.SMTP
        options={'host':s.SMTP_HOST,'port':s.SMTP_PORT,'timeout':15}
        if s.SMTP_SECURITY=='ssl':options['context']=ssl.create_default_context()
        with factory(**options) as server:
            if s.SMTP_SECURITY=='starttls':server.starttls(context=ssl.create_default_context())
            server.login(s.GMAIL_USER,s.GMAIL_APP_PASSWORD.replace(' ',''))
            refused=server.send_message(msg)
            if refused:raise ValueError('The mail server did not accept this recipient.')
    def send_code(self,to,name,code,reason):
        name=escape(str(name));reason=escape(str(reason))
        self.send(to,'Suji Café: '+reason,f'Hi {name}, your code to {reason} is {code}. It expires in 10 minutes.',
          f'<p>Hi {name},</p><p>Your code to {reason} is</p><h1>{escape(str(code))}</h1><p>It expires in 10 minutes. If this was not you, ignore this email.</p>')
