"""
=== FILE: ai_agent/apps.py ===
"""

from django.apps import AppConfig


class AiAgentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name               = "ai_agent"
    verbose_name       = "Financial AI Agent"