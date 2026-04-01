import os
import sys
from pathlib import Path
from config.production_checks import maybe_validate_production_settings

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-your-secret-key')

DEBUG = os.getenv('DEBUG', 'False').lower() in {'1', 'true', 'yes'}
TESTING = "test" in sys.argv
PRODUCTION_LIKE = (not DEBUG) and (not TESTING)

_allowed_hosts_raw = os.getenv('ALLOWED_HOSTS', '').strip()
if TESTING and not _allowed_hosts_raw:
    ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1']
elif DEBUG and not _allowed_hosts_raw:
    ALLOWED_HOSTS = ['*']
else:
    ALLOWED_HOSTS = [h.strip() for h in _allowed_hosts_raw.split(',') if h.strip()]

# INSTALLED_APPS = [
    
#     'rest_framework',  
#     'payments',        
# ]

# INSTALLED_APPS = [
#     'django.contrib.admin',
#     'django.contrib.auth',
#     'django.contrib.contenttypes',
#     'django.contrib.sessions',
#     'django.contrib.messages',
#     'django.contrib.staticfiles',
#     'rest_framework',
#     'students',
#     'payments',
# ]


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'corsheaders',
    'rest_framework',
    'auth_api',
    'students',
    'payments',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'config.middleware.RequestIdMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True

STATIC_URL = '/static/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 10,
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.ScopedRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'auth_login': '5/min',
        'payment_start': '10/min',
        'payment_submit': '10/min',
        'payment_webhook': '120/min',
        'ai_agent_query': '20/min',
        'ai_agent_chat': '20/min',
        'admin_audit_log': '30/min',
    },
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "safe_context": {
            "()": "config.logging.SafeContextFilter",
        },
    },
    "formatters": {
        "standard": {
            "format": "%(asctime)s %(levelname)s %(name)s event=%(event)s request_id=%(request_id)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["safe_context"],
            "formatter": "standard",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}

# Cache configuration (shared cache recommended for production)
_redis_url = os.getenv("REDIS_URL", "").strip()
if _redis_url:
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": _redis_url,
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
            },
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "local-dev-cache",
        }
    }

# Abuse guard defaults (cache-based, per-process)
ABUSE_LOGIN_MAX_ATTEMPTS = int(os.getenv("ABUSE_LOGIN_MAX_ATTEMPTS", "5"))
ABUSE_LOGIN_WINDOW_SECONDS = int(os.getenv("ABUSE_LOGIN_WINDOW_SECONDS", "300"))
ABUSE_PAYMENT_START_MAX = int(os.getenv("ABUSE_PAYMENT_START_MAX", "10"))
ABUSE_PAYMENT_START_WINDOW_SECONDS = int(os.getenv("ABUSE_PAYMENT_START_WINDOW_SECONDS", "60"))
ABUSE_PAYMENT_SUBMIT_MAX = int(os.getenv("ABUSE_PAYMENT_SUBMIT_MAX", "10"))
ABUSE_PAYMENT_SUBMIT_WINDOW_SECONDS = int(os.getenv("ABUSE_PAYMENT_SUBMIT_WINDOW_SECONDS", "60"))
ABUSE_STUDENT_VERIFY_MAX = int(os.getenv("ABUSE_STUDENT_VERIFY_MAX", "5"))
ABUSE_STUDENT_VERIFY_WINDOW_SECONDS = int(os.getenv("ABUSE_STUDENT_VERIFY_WINDOW_SECONDS", "300"))

STUDENT_VERIFICATION_TTL_SECONDS = int(os.getenv("STUDENT_VERIFICATION_TTL_SECONDS", "1800"))

# Session/CSRF hardening in production-like mode
SESSION_COOKIE_SECURE = PRODUCTION_LIKE
CSRF_COOKIE_SECURE = PRODUCTION_LIKE
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SECURE_SSL_REDIRECT = PRODUCTION_LIKE
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if PRODUCTION_LIKE else None
SECURE_HSTS_SECONDS = 31536000 if PRODUCTION_LIKE else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = True if PRODUCTION_LIKE else False
SECURE_HSTS_PRELOAD = True if PRODUCTION_LIKE else False

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',')
    if origin.strip()
]
if DEBUG:
    for origin in ['http://localhost:3000', 'http://127.0.0.1:3000']:
        if origin not in CSRF_TRUSTED_ORIGINS:
            CSRF_TRUSTED_ORIGINS.append(origin)

# CORS
CORS_ALLOW_ALL_ORIGINS = False
if DEBUG:
    CORS_ALLOWED_ORIGINS = [
        'http://localhost:3000',
        'http://localhost:3001',
        'http://127.0.0.1:3000',
        'http://127.0.0.1:3001',
    ]
else:
    CORS_ALLOWED_ORIGINS = [
        origin.strip()
        for origin in os.getenv('CORS_ALLOWED_ORIGINS', '').split(',')
        if origin.strip()
    ]
CORS_ALLOW_CREDENTIALS = True

# Webhook secrets (dev fallback handled in gateway classes when DEBUG=True)
FAWRY_WEBHOOK_SECRET = os.getenv('FAWRY_WEBHOOK_SECRET')
VODAFONE_WEBHOOK_SECRET = os.getenv('VODAFONE_WEBHOOK_SECRET')
BANK_WEBHOOK_SECRET = os.getenv('BANK_WEBHOOK_SECRET')
WEBHOOK_ALLOWED_IPS = [
    ip.strip()
    for ip in os.getenv("WEBHOOK_ALLOWED_IPS", "").split(",")
    if ip.strip()
]
ALLOW_WEBHOOK_SECRET_FALLBACK = os.getenv("ALLOW_WEBHOOK_SECRET_FALLBACK", "False").lower() in {"1", "true", "yes"}
WEBHOOK_REPLAY_TTL_SECONDS = int(os.getenv("WEBHOOK_REPLAY_TTL_SECONDS", "1800"))

# AI agent (Groq)
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama3-8b-8192")

if TESTING:
    if not FAWRY_WEBHOOK_SECRET:
        FAWRY_WEBHOOK_SECRET = "test-fawry-secret"
    if not VODAFONE_WEBHOOK_SECRET:
        VODAFONE_WEBHOOK_SECRET = "test-vodafone-secret"
    if not BANK_WEBHOOK_SECRET:
        BANK_WEBHOOK_SECRET = "test-bank-secret"

maybe_validate_production_settings(DEBUG, globals())
