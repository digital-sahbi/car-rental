"""Reusable access-control mixins (requirement 3).

Roles live on ``accounts.User.Role``. To avoid importing ``accounts`` from
``core`` (which would create a cycle at app-load time) the comparison uses the
plain string values of that enum.
"""
from __future__ import annotations

from typing import Any, Iterable

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext_lazy as _

ADMIN = "ADMIN"
MANAGER = "MANAGER"
EMPLOYEE = "EMPLOYEE"


class RoleRequiredMixin(LoginRequiredMixin):
    """Restrict a class-based view to a set of roles.

    Anonymous users are redirected to the login page by
    :class:`LoginRequiredMixin`; authenticated users whose role is not allowed
    get a 403.

    Usage::

        class EmployeeListView(RoleRequiredMixin, ListView):
            allowed_roles = (ADMIN,)
    """

    #: Roles allowed to reach the view. Empty tuple = any logged-in user.
    allowed_roles: Iterable[str] = ()

    def dispatch(self, request, *args: Any, **kwargs: Any):
        # LoginRequiredMixin already redirects anonymous users.
        response = super().dispatch(request, *args, **kwargs)
        allowed = tuple(self.allowed_roles)
        if allowed and request.user.is_authenticated and request.user.role not in allowed:
            raise PermissionDenied(
                _("Votre rôle ne permet pas d'accéder à cette page.")
            )
        return response


class AdminRequiredMixin(RoleRequiredMixin):
    """Administrators only."""

    allowed_roles = (ADMIN,)


class ManagerRequiredMixin(RoleRequiredMixin):
    """Managers and administrators."""

    allowed_roles = (MANAGER, ADMIN)


class AuditContextMixin:
    """Mixin giving CBVs a uniform handle on the acting user."""

    def get_actor(self):
        """The acting user (``None`` when anonymous)."""
        user = getattr(self.request, "user", None)
        return user if (user and user.is_authenticated) else None

    def audit_kwargs(self) -> dict[str, Any]:
        """Keyword arguments shared by every ``log_action`` call."""
        return {"user": self.get_actor(), "request": self.request}


class FormMessageMixin:
    """Add a flash message after a successful form submission."""

    success_message: str = _("Enregistrement effectué.")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, self.success_message)
        return response
