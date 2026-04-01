import logging
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


def validate_production_settings(settings_dict: dict) -> None:
    allowed_hosts = settings_dict.get("ALLOWED_HOSTS") or []
    if not allowed_hosts:
        raise ImproperlyConfigured("ALLOWED_HOSTS must not be empty in production.")
    if "*" in allowed_hosts:
        raise ImproperlyConfigured('ALLOWED_HOSTS must not contain wildcard "*".')

    secret_key = settings_dict.get("SECRET_KEY")
    if not secret_key:
        raise ImproperlyConfigured("SECRET_KEY must be set in production.")
    if secret_key == "django-insecure-your-secret-key" or str(secret_key).startswith("django-insecure"):
        raise ImproperlyConfigured("SECRET_KEY must not use the insecure default in production.")

    if not settings_dict.get("SESSION_COOKIE_SECURE"):
        raise ImproperlyConfigured("SESSION_COOKIE_SECURE must be True in production.")
    if not settings_dict.get("CSRF_COOKIE_SECURE"):
        raise ImproperlyConfigured("CSRF_COOKIE_SECURE must be True in production.")
    if not settings_dict.get("SECURE_PROXY_SSL_HEADER"):
        raise ImproperlyConfigured("SECURE_PROXY_SSL_HEADER must be set in production.")
    if not settings_dict.get("SECURE_HSTS_SECONDS"):
        raise ImproperlyConfigured("SECURE_HSTS_SECONDS must be set in production.")
    if not settings_dict.get("SECURE_HSTS_INCLUDE_SUBDOMAINS"):
        raise ImproperlyConfigured("SECURE_HSTS_INCLUDE_SUBDOMAINS must be True in production.")
    if not settings_dict.get("SECURE_HSTS_PRELOAD"):
        raise ImproperlyConfigured("SECURE_HSTS_PRELOAD must be True in production.")

    caches = settings_dict.get("CACHES") or {}
    default_cache = caches.get("default") or {}
    backend = default_cache.get("BACKEND", "")
    if backend == "django.core.cache.backends.locmem.LocMemCache":
        raise ImproperlyConfigured(
            "CACHES must use a shared backend in production (not LocMemCache)."
        )

    required_secrets = (
        "FAWRY_WEBHOOK_SECRET",
        "VODAFONE_WEBHOOK_SECRET",
        "BANK_WEBHOOK_SECRET",
    )
    for key in required_secrets:
        if not settings_dict.get(key):
            raise ImproperlyConfigured(f"{key} must be set in production.")

    webhook_allowed_ips = settings_dict.get("WEBHOOK_ALLOWED_IPS") or []
    if not webhook_allowed_ips:
        raise ImproperlyConfigured("WEBHOOK_ALLOWED_IPS must be set in production.")


def maybe_validate_production_settings(debug: bool, settings_dict: dict) -> None:
    if debug:
        return
    validate_production_settings(settings_dict)
    if not settings_dict.get("SECURE_SSL_REDIRECT"):
        logger.warning(
            "SECURE_SSL_REDIRECT is disabled in production; ensure HTTPS is enforced upstream."
        )
