"""Email-domain validation without signup OTPs or paid services.
A domain must exist and publish a usable mail (MX) record. This does not prove
that a particular mailbox exists or belongs to the person registering.
"""
import json
import re
import threading
import time
import urllib.parse
import urllib.request

class EmailDomainError(ValueError):
    """The domain cannot receive mail according to the selected DNS policy."""

class EmailDomainUnavailable(EmailDomainError):
    """DNS could not be checked; retry instead of accepting an unknown domain."""

class MailDomainValidator:
    PROVIDERS=('https://dns.google/resolve','https://cloudflare-dns.com/dns-query')
    def __init__(self):
        self._cache={}
        self._lock=threading.Lock()
    def _lookup(self,domain):
        query=urllib.parse.urlencode({'name':domain,'type':'MX'})
        for provider in self.PROVIDERS:
            try:
                req=urllib.request.Request(provider+'?'+query,headers={'Accept':'application/dns-json','User-Agent':'SujiCafeEmailDomainCheck/1.0'})
                with urllib.request.urlopen(req,timeout=4) as response:data=json.loads(response.read(65536))
                status=data.get('Status')
                if status==3:raise EmailDomainError('This email domain does not exist. Check its spelling.')
                if status!=0:continue
                records=[record.get('data','').split() for record in data.get('Answer',[]) if record.get('type')==15]
                if any(len(record)==2 and record[1]=='.' for record in records):
                    raise EmailDomainError('This email domain does not accept email. Please use another address.')
                hosts=[record[1].rstrip('.') for record in records if len(record)==2 and record[0].isdigit() and record[1]!='.']
                if hosts:return
                raise EmailDomainError('This domain has no email server (MX record). Check the domain or use another email address.')
            except EmailDomainError:raise
            except Exception:continue
        raise EmailDomainUnavailable('We could not check the email domain right now. Please check your connection and try again.')
    def validate(self,email):
        if not isinstance(email,str) or email.count('@')!=1:raise EmailDomainError('Enter a complete valid email address.')
        from registration_policy import validate_email_policy
        try:validate_email_policy(email)
        except ValueError as exc:raise EmailDomainError(str(exc)) from exc
        domain=email.rsplit('@',1)[1].lower()
        if len(domain)>253 or not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}',domain):
            raise EmailDomainError('Enter a valid email domain, such as gmail.com.')
        now=time.monotonic()
        with self._lock:
            cached=self._cache.get(domain)
            if cached and cached[0]>now:
                if cached[1]=='valid':return
                error=EmailDomainUnavailable if cached[1]=='unavailable' else EmailDomainError
                raise error(cached[2])
        try:self._lookup(domain)
        except EmailDomainError as exc:
            temporary=isinstance(exc,EmailDomainUnavailable)
            with self._lock:self._cache[domain]=(now+(5 if temporary else 120),'unavailable' if temporary else 'invalid',str(exc))
            raise
        with self._lock:
            if len(self._cache)>1000:self._cache={key:value for key,value in self._cache.items() if value[0]>now}
            self._cache[domain]=(now+600,'valid','')

_validator=MailDomainValidator()
def validate_email_domain(email):
    _validator.validate(email)
