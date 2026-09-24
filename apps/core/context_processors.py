"""Template context shared across the whole CRM."""
from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from django.utils import translation

from .i18n import is_rtl

LANGUAGES = [
    ("fr", "Français"),
    ("ar", "العربية"),
    ("en", "English"),
]


def company_settings(request: HttpRequest) -> dict[str, Any]:
    """Expose company branding + i18n switches to every template."""
    from .models import CompanySettings

    company = None
    try:
        company = CompanySettings.objects.first()
    except Exception:  # pragma: no cover - DB not ready (e.g. during migrate)
        company = None

    current = translation.get_language() or "fr"
    return {
        "company": company,
        "available_languages": LANGUAGES,
        "current_language": current,
        "is_rtl": is_rtl(current),
    }


def notifications(request: HttpRequest) -> dict[str, Any]:
    """Header bell: the latest items plus the unread badge count."""
    from . import notifications as notifications_service

    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}

    try:
        return {
            "latest_notifications": notifications_service.notifications_for(user),
            "unread_notifications": notifications_service.unread_notification_count(user),
            "history_url": notifications_service.history_url_for(user),
        }
    except Exception:  # pragma: no cover - DB not ready (e.g. during migrate)
        return {}
