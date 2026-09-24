"""Accounts service layer — all employee writes go through here.

Each function records an audit entry. Views never touch the ORM directly.
"""
from __future__ import annotations

from typing import Any, Optional

from django.http import HttpRequest

from apps.core.models import AuditAction
from apps.core.services import business_diff, log_action

from .models import Role, User


def create_employee(*, data: dict[str, Any], actor: Optional[User], request: Optional[HttpRequest] = None) -> User:
    """Create an employee from validated form data (password already parsed)."""
    password = data.pop("password1", None)
    data.pop("password2", None)
    # ``cin`` is unique but optional: "" would collide on the unique index.
    if not data.get("cin"):
        data["cin"] = None
    user = User(**data)
    if password:
        user.set_password(password)
    user.save()
    log_action(
        action=AuditAction.CREATE,
        instance=user,
        user=actor,
        request=request,
        changes={"created": {"email": user.email, "role": user.role}},
    )
    return user


def update_employee(
    *,
    user: User,
    data: dict[str, Any],
    actor: Optional[User],
    request: Optional[HttpRequest] = None,
) -> User:
    """Update an employee, logging only the fields that actually changed."""
    password = data.pop("password1", None)
    data.pop("password2", None)
    if "cin" in data and not data["cin"]:
        data["cin"] = None

    before = {field: getattr(user, field) for field in data.keys()}
    for field, value in data.items():
        setattr(user, field, value)
    if password:
        user.set_password(password)
    user.save()

    changes = business_diff(before, data)
    if password:
        changes["password"] = {"old": "*", "new": "*"}  # never store the secret
    log_action(
        action=AuditAction.UPDATE,
        instance=user,
        user=actor,
        request=request,
        changes=changes,
    )
    return user


def deactivate_employee(
    *,
    user: User,
    actor: Optional[User],
    request: Optional[HttpRequest] = None,
) -> User:
    """Soft-disable an employee (never hard-delete)."""
    user.is_active = False
    user.save(update_fields=["is_active", "updated_at"])
    log_action(
        action=AuditAction.UPDATE,
        instance=user,
        user=actor,
        request=request,
        changes={"is_active": {"old": True, "new": False}},
    )
    return user


def reactivate_employee(
    *,
    user: User,
    actor: Optional[User],
    request: Optional[HttpRequest] = None,
) -> User:
    user.is_active = True
    user.save(update_fields=["is_active", "updated_at"])
    log_action(
        action=AuditAction.UPDATE,
        instance=user,
        user=actor,
        request=request,
        changes={"is_active": {"old": False, "new": True}},
    )
    return user


def log_login(*, user: User, request: Optional[HttpRequest] = None) -> None:
    log_action(action=AuditAction.LOGIN, instance=user, user=user, request=request)


def log_logout(*, user: User, request: Optional[HttpRequest] = None) -> None:
    log_action(action=AuditAction.LOGOUT, instance=user, user=user, request=request)


def employees_queryset():
    """Base queryset for the employee list (active + inactive)."""
    return User.objects.all().order_by("last_name", "first_name")


def role_choices() -> list[tuple[str, str]]:
    return list(Role.choices)