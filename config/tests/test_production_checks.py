from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from config.production_checks import validate_production_settings, maybe_validate_production_settings


class ProductionChecksTests(SimpleTestCase):
    def _base_settings(self, **overrides):
        base = {
            "ALLOWED_HOSTS": ["example.com"],
            "SESSION_COOKIE_SECURE": True,
            "CSRF_COOKIE_SECURE": True,
            "SECURE_PROXY_SSL_HEADER": ("HTTP_X_FORWARDED_PROTO", "https"),
            "SECURE_HSTS_SECONDS": 31536000,
            "SECURE_HSTS_INCLUDE_SUBDOMAINS": True,
            "SECURE_HSTS_PRELOAD": True,
            "WEBHOOK_ALLOWED_IPS": ["1.2.3.4"],
            "FAWRY_WEBHOOK_SECRET": "fawry-secret",
            "VODAFONE_WEBHOOK_SECRET": "vodafone-secret",
            "BANK_WEBHOOK_SECRET": "bank-secret",
            "SECRET_KEY": "change-me-strong-secret",
        }
        base.update(overrides)
        return base

    def test_production_rejects_missing_secret_key(self):
        settings_dict = self._base_settings(SECRET_KEY=None)
        with self.assertRaises(ImproperlyConfigured):
            validate_production_settings(settings_dict)

    def test_production_rejects_default_secret_key(self):
        settings_dict = self._base_settings(SECRET_KEY="django-insecure-your-secret-key")
        with self.assertRaises(ImproperlyConfigured):
            validate_production_settings(settings_dict)

    def test_production_accepts_non_default_secret_key(self):
        settings_dict = self._base_settings(SECRET_KEY="super-strong-secret-key")
        validate_production_settings(settings_dict)

    def test_debug_skips_production_validation(self):
        settings_dict = self._base_settings(SECRET_KEY="django-insecure-your-secret-key")
        maybe_validate_production_settings(True, settings_dict)

    def test_production_rejects_locmem_cache(self):
        settings_dict = self._base_settings(CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            }
        })
        with self.assertRaises(ImproperlyConfigured):
            validate_production_settings(settings_dict)

    def test_production_accepts_shared_cache(self):
        settings_dict = self._base_settings(CACHES={
            "default": {
                "BACKEND": "django_redis.cache.RedisCache",
                "LOCATION": "redis://localhost:6379/0",
            }
        })
        validate_production_settings(settings_dict)

    def test_production_rejects_missing_proxy_ssl_header(self):
        settings_dict = self._base_settings(SECURE_PROXY_SSL_HEADER=None)
        with self.assertRaises(ImproperlyConfigured):
            validate_production_settings(settings_dict)

    def test_production_rejects_missing_hsts(self):
        settings_dict = self._base_settings(SECURE_HSTS_SECONDS=0)
        with self.assertRaises(ImproperlyConfigured):
            validate_production_settings(settings_dict)

    def test_production_rejects_hsts_without_subdomains(self):
        settings_dict = self._base_settings(SECURE_HSTS_INCLUDE_SUBDOMAINS=False)
        with self.assertRaises(ImproperlyConfigured):
            validate_production_settings(settings_dict)

    def test_production_rejects_hsts_without_preload(self):
        settings_dict = self._base_settings(SECURE_HSTS_PRELOAD=False)
        with self.assertRaises(ImproperlyConfigured):
            validate_production_settings(settings_dict)

    def test_production_rejects_missing_webhook_allowed_ips(self):
        settings_dict = self._base_settings(WEBHOOK_ALLOWED_IPS=[])
        with self.assertRaises(ImproperlyConfigured):
            validate_production_settings(settings_dict)

    def test_production_accepts_webhook_allowed_ips(self):
        settings_dict = self._base_settings(WEBHOOK_ALLOWED_IPS=["10.0.0.1"])
        validate_production_settings(settings_dict)
