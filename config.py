import os
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.environ.get('SECRET_KEY') or os.urandom(32)
GMAIL_USER = os.environ.get('GMAIL_USER')
GMAIL_APP_PASSWORD = os.environ.get('GMAIL_APP_PASSWORD')
SMTP_HOST=os.environ.get('SMTP_HOST','smtp.gmail.com')
SMTP_SECURITY=os.environ.get('SMTP_SECURITY','starttls').lower()
SMTP_PORT=int(os.environ.get('SMTP_PORT','465' if SMTP_SECURITY=='ssl' else '587'))
SMTP_FROM=os.environ.get('SMTP_FROM') or GMAIL_USER

# Origin reachable by invited employees; never derive invitation links from Host headers.
PUBLIC_BASE_URL = os.environ.get('PUBLIC_BASE_URL', '').strip().rstrip('/')

DEV_PRINT_OTP = os.environ.get('DEV_PRINT_OTP', '0') == '1'
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', '').strip().lower()
OWNER_EMAIL = os.environ.get('OWNER_EMAIL',ADMIN_EMAIL).strip().lower()
# Database: set DB_BACKEND=mysql to use the required MySQL database.
DB_BACKEND = os.environ.get('DB_BACKEND', 'mysql').lower()
MYSQL_HOST = os.environ.get('MYSQL_HOST', '127.0.0.1')
MYSQL_PORT = int(os.environ.get('MYSQL_PORT', '3306'))
MYSQL_USER = os.environ.get('MYSQL_USER', 'root')
MYSQL_PASSWORD = os.environ.get('MYSQL_PASSWORD', '')
MYSQL_DATABASE = os.environ.get('MYSQL_DATABASE', 'suji_cafe')
MYSQL_SSL_CA = os.environ.get('MYSQL_SSL_CA', '').strip()

# Public business information: confirm with the cafe owner before deployment.
STORE_NAME = os.environ.get('STORE_NAME', 'Suji Cafe')
STORE_ADDRESS = os.environ.get('STORE_ADDRESS', '10384 Diamond St., Umali Subdivision, Batong Malake, Los Baños, Laguna 4030, Philippines')
STORE_LAT = os.environ.get('STORE_LAT', '14.1667')
STORE_LNG = os.environ.get('STORE_LNG', '121.2333')
DELIVERY_RADIUS_KM = 8
FACEBOOK_URL = os.environ.get('FACEBOOK_URL', 'https://www.facebook.com/sujistreetcafe/')
INSTAGRAM_URL = os.environ.get('INSTAGRAM_URL', 'https://www.instagram.com/sujicafe_/')
# Verified Google Maps listing: Suji Cafe, 10384 Diamond St, Los Baños, 4030 Laguna.
GOOGLE_MAPS_PLACE_ID = os.environ.get('GOOGLE_MAPS_PLACE_ID','ChIJeSEWYCFhvTMRA2hPLgqRhMc').strip()
from urllib.parse import urlencode, urlsplit
_default_map='https://www.google.com/maps/search/?'+urlencode({'api':1,'query':STORE_NAME+', '+STORE_ADDRESS,'query_place_id':GOOGLE_MAPS_PLACE_ID})
_configured_map=os.environ.get('GOOGLE_MAPS_URL','').strip()
# Upgrade old generic Google search links left in existing .env files.
GOOGLE_MAPS_URL = _default_map if not _configured_map or urlsplit(_configured_map).netloc in ('www.google.com','google.com','maps.google.com') else _configured_map
GOOGLE_MAPS_EMBED_URL = 'https://maps.google.com/maps?'+urlencode({'q':'place_id:'+GOOGLE_MAPS_PLACE_ID,'z':18,'output':'embed'})

# Enable only after the owner confirms the actual store coordinates.
STORE_COORDINATES_VERIFIED = os.environ.get('STORE_COORDINATES_VERIFIED','0') == '1'
