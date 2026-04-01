"""
=== FILE: ai_agent/urls.py ===

URL routing for the Financial Agent app.

Route:
    POST  /ai-agent/chat/  →  chat_view

Mount in config/urls.py with:
    path("ai-agent/", include("ai_agent.urls"))
"""

from django.urls import path
from .views import chat_view, query_view

app_name = "ai_agent"

urlpatterns = [
    path("chat/", chat_view, name="agent-chat"),
    path("query/", query_view, name="agent-query"),
]
