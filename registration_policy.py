"""Shared business policy; domain records alone do not establish eligibility."""
import json,re,unicodedata
from pathlib import Path
from functools import lru_cache
POLICY=Path(__file__).parent/'static/data/registration-policy.json'
@lru_cache(maxsize=1)
def _read(stamp):return json.loads(POLICY.read_text())
def rules():return _read(POLICY.stat().st_mtime_ns)
def inappropriate_text(value):
    value=''.join(c for c in unicodedata.normalize('NFKD',str(value).casefold()) if not unicodedata.combining(c))
    blocked=set(rules()['blocked_words'])
    for text in (value,value.translate(str.maketrans('013457$@','oieastsa'))):
        tokens=re.findall('[a-z]+',text)
        if any(t in blocked for t in tokens) or ''.join(tokens) in blocked:return True
    return False
def validate_name_policy(value,label='Name'):
    if inappropriate_text(value):raise ValueError(label+' contains inappropriate language. Please use your real name.')
ADULT_DOMAINS=Path(__file__).parent/'static/data/adult-domains.hosts'
@lru_cache(maxsize=1)
def _adult_domains(stamp):
    domains=set()
    for line in ADULT_DOMAINS.read_text(encoding='utf-8').splitlines():
        fields=line.split('#',1)[0].split()
        if len(fields)>=2 and fields[0] in ('0.0.0.0','127.0.0.1'):
            for domain in fields[1:]:
                domain=domain.lower().rstrip('.')
                if domain.startswith('www.'):domain=domain[4:]
                if '.' in domain:domains.add(domain)
    return frozenset(domains)
def is_adult_domain(domain):
    domains=_adult_domains(ADULT_DOMAINS.stat().st_mtime_ns)
    labels=domain.lower().rstrip('.').split('.')
    return any('.'.join(labels[i:]) in domains for i in range(len(labels)-1))
def valid_email_username(email):
    local,separator,_=str(email).rpartition('@')
    return bool(separator) and rules()['email_username_min_length']<=len(local)<=rules()['email_username_max_length']
SCHOOL_DOMAINS=Path(__file__).parent/'static/data/school-email-domains.json'
@lru_cache(maxsize=1)
def _school_domains(stamp):
    data=json.loads(SCHOOL_DOMAINS.read_text())
    return frozenset(data['academic_suffixes']),frozenset(data['known_school_domains'])
def approved_email_domain(domain):
    domain=domain.lower().rstrip('.')
    if domain in rules()['allowed_public_email_domains'] or domain in rules().get('approved_company_email_domains',[]):return True
    if any(domain.endswith('.'+suffix) for suffix in rules().get('allowed_email_domain_suffixes',[])):return True
    suffixes,institutions=_school_domains(SCHOOL_DOMAINS.stat().st_mtime_ns)
    approved=institutions|frozenset(rules()['approved_school_domains'])
    labels=domain.split('.')
    if any('.'.join(labels[i:]) in approved for i in range(len(labels)-1)):return True
    return any('.'.join(labels[i:]) in suffixes for i in range(1,len(labels)))
def validate_email_policy(email):
    if not valid_email_username(email):
        raise ValueError('Email username (before @) must be 6–30 characters long.')
    local,_,domain=str(email).lower().rpartition('@')
    providers=set(rules()['allowed_public_email_domains'])
    if domain not in providers and any(domain.startswith(provider+'.') for provider in providers):
        raise ValueError('This email domain is not allowed. Use the exact email provider domain.')
    if domain in rules()['allowed_ph_suffixes']:
        raise ValueError('Enter the complete domain before the Philippine suffix, such as school.edu.ph.')
    accepted=set(rules()['allowed_generic_tlds']) | set(rules()['allowed_country_tlds'])
    if domain.rsplit('.',1)[-1] not in accepted:
        raise ValueError('This email extension is not allowed. Use a domain with an accepted generic or official country-code extension.')
    if not approved_email_domain(domain):
        raise ValueError('This email domain is not allowed. Use an approved email provider, school email, or a domain ending in .org, .edu, .gov or .ph.')
    labels=domain.split('.')
    if len(labels)>=3 and labels[-1]=='ph' and '.'.join(labels[-2:]) not in rules()['allowed_ph_suffixes']:
        raise ValueError('This .ph suffix is not allowed by the café. Use com.ph, net.ph, org.ph, ngo.ph, i.ph, edu.ph, gov.ph or mil.ph.')
    if is_adult_domain(domain) or any(domain==d or domain.endswith('.'+d) for d in rules()['blocked_domains']):
        raise ValueError('This email domain is not allowed by the café. Please use another email address.')
    domain_text=domain.rsplit('.',1)[0]
    compact=re.sub('[^a-z0-9]','',domain_text)
    compact=compact.translate(str.maketrans('013457$@','oieastsa'))
    if any(word in compact for word in rules().get('blocked_domain_keywords',[])):
        raise ValueError('This email domain is not allowed by the café. Please use a personal or business email address.')
    if inappropriate_text(local) or inappropriate_text(domain_text):
        raise ValueError('Please use an email address without inappropriate language.')
