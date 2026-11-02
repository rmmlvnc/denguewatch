"""
Django settings for denguewatch project.

DengueWatch:
AI-Assisted Predictive Dengue Surveillance and
Hotspot Analytics System in Iligan City
"""

from pathlib import Path
import os


# Load local development settings without adding a runtime dependency. Values
# already provided by the hosting environment take precedence over .env.
_local_env = Path(__file__).resolve().parent.parent / '.env'
if _local_env.exists():
    for _line in _local_env.read_text(encoding='utf-8-sig').splitlines():
        _line = _line.strip()
        if not _line or _line.startswith('#') or '=' not in _line:
            continue
        _key, _value = _line.split('=', 1)
        _key = _key.strip()
        _value = _value.strip()
        if _value.startswith(('"', "'")) and _value.endswith(_value[0]):
            _value = _value[1:-1]
        if _key:
            os.environ.setdefault(_key, _value)


# ============================================================
# BASE DIRECTORY
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent


# ============================================================
# SECURITY
# ============================================================

SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'django-insecure-development-only-change-before-deployment'
)

DEBUG = os.environ.get('DJANGO_DEBUG', 'True').lower() == 'true'

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get(
        'DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1'
    ).split(',')
    if host.strip()
]

# Expo Go reaches the development server through a changing LAN IP. Production
# deployments must set DEBUG=False and an explicit allowed-host list.
if DEBUG:
    ALLOWED_HOSTS = ['*']


# ============================================================
# APPLICATIONS
# ============================================================

INSTALLED_APPS = [

    # Django built-in apps
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    

    # DengueWatch application
    'monitoring.apps.MonitoringConfig',
]


# ============================================================
# MIDDLEWARE
# ============================================================

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',

    'monitoring.middleware.DevelopmentCorsMiddleware',

    'django.contrib.sessions.middleware.SessionMiddleware',

    'django.middleware.common.CommonMiddleware',

    'django.middleware.csrf.CsrfViewMiddleware',

    'django.contrib.auth.middleware.AuthenticationMiddleware',

    'django.contrib.messages.middleware.MessageMiddleware',

    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# Expo web runs on a separate localhost origin during development.
CORS_ALLOWED_ORIGINS = {
    origin.strip()
    for origin in os.environ.get(
        'CORS_ALLOWED_ORIGINS', 'http://localhost:8081,http://127.0.0.1:8081'
    ).split(',')
    if origin.strip()
}


# ============================================================
# URL CONFIGURATION
# ============================================================

ROOT_URLCONF = 'denguewatch.urls'


# ============================================================
# TEMPLATES
# ============================================================

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',

        'DIRS': [
            BASE_DIR / 'templates',
        ],

        'APP_DIRS': True,

        'OPTIONS': {
            'context_processors': [

                'django.template.context_processors.request',

                'django.contrib.auth.context_processors.auth',

                'django.contrib.messages.context_processors.messages',
                'monitoring.context_processors.current_account',
            ],
        },
    },
]


# ============================================================
# WSGI
# ============================================================

WSGI_APPLICATION = 'denguewatch.wsgi.application'


# ============================================================
# DATABASE
# ============================================================

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


# ============================================================
# PASSWORD VALIDATION
# ============================================================

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME':
        'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },

    {
        'NAME':
        'django.contrib.auth.password_validation.MinimumLengthValidator',
    },

    {
        'NAME':
        'django.contrib.auth.password_validation.CommonPasswordValidator',
    },

    {
        'NAME':
        'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# ============================================================
# INTERNATIONALIZATION
# ============================================================

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Asia/Manila'

USE_I18N = True

USE_TZ = True


# ============================================================
# STATIC FILES
# ============================================================

STATIC_URL = '/static/'
SERVE_STATIC_FILES = os.environ.get('DJANGO_SERVE_STATIC_FILES', 'True').lower() == 'true'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

AUTH_USER_MODEL = 'monitoring.UserAccount'

STATICFILES_DIRS = [
    BASE_DIR / 'static',
]

STATIC_ROOT = BASE_DIR / 'staticfiles'


# ============================================================
# MEDIA FILES
# ============================================================

MEDIA_URL = '/media/'

MEDIA_ROOT = BASE_DIR / 'media'


# ============================================================
# DJANGO AUTHENTICATION
# ============================================================

LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/login/'


# ============================================================
# SESSION SETTINGS
# ============================================================

SESSION_COOKIE_AGE = 60 * 60 * 8  # 8 hours

SESSION_EXPIRE_AT_BROWSER_CLOSE = False


# ============================================================
# DEFAULT PRIMARY KEY
# ============================================================

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ============================================================
# DENGUEWATCH APPLICATION SETTINGS
# ============================================================

# ============================================================
# FIREBASE SETTINGS
# ============================================================

# Firebase service account file
FIREBASE_CREDENTIALS = BASE_DIR / 'firebase' / 'serviceAccountKey.json'


# Firebase project ID
FIREBASE_PROJECT_ID = os.environ.get(
    'FIREBASE_PROJECT_ID',
    ''
)


# ============================================================
# MACHINE LEARNING SETTINGS
# ============================================================

ML_MODEL_PATH = (
    BASE_DIR
    / 'monitoring'
    / 'ml'
    / 'random_forest.pkl'
)


# ============================================================
# DENGUE RISK LEVELS
# ============================================================

DENGUE_RISK_LEVELS = {
    'LOW': 'Low',
    'MODERATE': 'Moderate',
    'HIGH': 'High',
}


# ============================================================
# EMAIL SETTINGS
# ============================================================

EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True').lower() == 'true'
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', EMAIL_HOST_USER)
SITE_BASE_URL = os.environ.get('SITE_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')
# Stay in console mode until a Gmail address and Google App Password are set.
EMAIL_BACKEND = (
    'django.core.mail.backends.smtp.EmailBackend'
    if EMAIL_HOST_USER and EMAIL_HOST_PASSWORD
    else 'django.core.mail.backends.console.EmailBackend'
)

# Deep link opened by the installed DengueWatch mobile app.
MOBILE_ALERT_LINK_BASE = os.environ.get(
    'MOBILE_ALERT_LINK_BASE', 'denguewatch://alert'
).rstrip('/')
MOBILE_NOTIFICATIONS_LINK = os.environ.get(
    'MOBILE_NOTIFICATIONS_LINK', 'denguewatch://alerts'
).rstrip('/')
MOBILE_VERIFICATION_LINK_BASE = os.environ.get(
    'MOBILE_VERIFICATION_LINK_BASE', 'denguewatch://verify-email'
).rstrip('/')
EMAIL_DELIVERY_ENABLED = bool(
    EMAIL_HOST_USER
    and EMAIL_HOST_PASSWORD
    and EMAIL_BACKEND.endswith('smtp.EmailBackend')
)


# ============================================================
# SECURITY SETTINGS FOR DEVELOPMENT
# ============================================================

CSRF_COOKIE_HTTPONLY = False

SESSION_COOKIE_HTTPONLY = True

X_FRAME_OPTIONS = 'SAMEORIGIN'
