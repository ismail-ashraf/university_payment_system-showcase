import logging.config

from django.conf import settings
from django.test import SimpleTestCase


class LoggingConfigTests(SimpleTestCase):
    def test_logging_config_present_and_safe(self):
        self.assertTrue(hasattr(settings, "LOGGING"))
        logging_config = settings.LOGGING

        handler = logging_config["handlers"]["console"]
        self.assertIn("safe_context", handler["filters"])

        fmt = logging_config["formatters"]["standard"]["format"]
        self.assertIn("%(event)s", fmt)
        self.assertIn("%(request_id)s", fmt)

        logging.config.dictConfig(logging_config)
