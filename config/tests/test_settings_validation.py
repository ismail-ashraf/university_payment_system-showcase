from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase

from config import settings


class SettingsValidationTests(TestCase):
    def test_production_validation_fails_missing_secrets(self):
        with self.assertRaises(ImproperlyConfigured):
            settings._validate_production_settings({
                "SECRET_KEY": "django-insecure-test",
                "ALLOWED_HOSTS": ["example.com"],
                "FAWRY_WEBHOOK_SECRET": None,
                "VODAFONE_WEBHOOK_SECRET": None,
                "BANK_WEBHOOK_SECRET": None,
                "CORS_ALLOW_ALL_ORIGINS": False,
                "CORS_ALLOWED_ORIGINS": [],
            })

    def test_production_validation_rejects_wildcard_cors(self):
        with self.assertRaises(ImproperlyConfigured):
            settings._validate_production_settings({
                "SECRET_KEY": "secret",
                "ALLOWED_HOSTS": ["payments.example.edu"],
                "FAWRY_WEBHOOK_SECRET": "x",
                "VODAFONE_WEBHOOK_SECRET": "y",
                "BANK_WEBHOOK_SECRET": "z",
                "CORS_ALLOW_ALL_ORIGINS": False,
                "CORS_ALLOWED_ORIGINS": ["*"],
            })

    def test_dev_mode_not_production_like(self):
        self.assertFalse(settings._is_production_like())

    def test_security_flags_follow_debug(self):
        self.assertEqual(settings.SESSION_COOKIE_SECURE, settings._is_production_like())
        self.assertEqual(settings.CSRF_COOKIE_SECURE, settings._is_production_like())

    def test_test_mode_allows_testserver_host(self):
        if settings.TESTING:
            self.assertIn("testserver", settings.ALLOWED_HOSTS)
