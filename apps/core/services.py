"""Core service layer: audit logging.

Logging is explicit (called from services) rather than signal-based: that way
we can capture the actor, the request IP, and a genuine before/after diff.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.db.models.fields.files import FieldFile
from django.http import HttpRequest

from .models import AuditAction, AuditLog


def _client_ip(request: Optional[HttpRequest]) -> Optional[str]:
    """Best-effort client IP, honouring a reverse-proxy header."""
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _jsonable(value: Any) -> Any:
    """Best-effort conversion so ``changes`` is always JSON-serialisable.

    Handles the common offenders:

    * ``Decimal``            → ``"12.50"``
    * ``date`` / ``datetime``→ ISO 8601
    * ``UUID``               → ``str``
    * model instances        → their ``pk``
    * ``FieldFile`` (ImageField/FileField uploads) → the stored file name

    Anything still unknown is stringified rather than raising: an audit write
    must never be the reason a business operation fails.
    """
    import datetime
    import decimal
    import uuid

    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    # Must be checked before Model: an ImageFieldFile is not a Model, but it is
    # also not JSON-serialisable, which is what this conversion exists to avoid.
    if isinstance(value, FieldFile):
        return value.name or ""
    if isinstance(value, models.Model):
        return value.pk
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def log_action(
    *,
    action: str,
    instance: Optional[models.Model] = None,
    user: Optional[Any] = None,
    request: Optional[HttpRequest] = None,
    changes: Optional[Mapping[str, Any]] = None,
    model_name: Optional[str] = None,
    object_id: Optional[int] = None,
    object_repr: Optional[str] = None,
) -> AuditLog:
    """Create an :class:`AuditLog` row.

    Either pass ``instance`` (its class, id and repr are inferred) or the
    explicit ``model_name`` / ``object_id`` / ``object_repr`` trio.
    """
    if instance is not None:
        model_name = model_name or instance.__class__.__name__
        object_id = object_id if object_id is not None else instance.pk
        object_repr = object_repr or str(instance)
    if user is None and request is not None:
        candidate = getattr(request, "user", None)
        if candidate is not None and candidate.is_authenticated:
            user = candidate

    return AuditLog.objects.create(
        user=user,
        action=action,
        model_name=model_name or "Unknown",
        object_id=object_id,
        object_repr=(object_repr or "")[:255],
        changes=_jsonable(dict(changes or {})),
        ip_address=_client_ip(request),
    )


def diff(old: Mapping[str, Any], new: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return ``{field: {"old": ..., "new": ...}}`` for changed keys only."""
    result: dict[str, dict[str, Any]] = {}
    for key, new_value in new.items():
        old_value = old.get(key)
        if old_value != new_value:
            result[key] = {"old": old_value, "new": new_value}
    return result


#: Columns the framework maintains on every save. They carry no business
#: meaning, so they are stripped from audit diffs — otherwise saving an
#: unchanged form would still log an "update".
BOOKKEEPING_FIELDS = frozenset({"created_by", "updated_by", "created_at", "updated_at"})


def business_diff(
    old: Mapping[str, Any],
    new: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Like :func:`diff`, but ignoring framework-maintained bookkeeping columns."""
    changes = diff(old, new)
    for field in BOOKKEEPING_FIELDS:
        changes.pop(field, None)
    return changes


def apply_form_data(instance: models.Model, data: Mapping[str, Any]) -> models.Model:
    """Copy validated form data onto a model instance, field by field.

    Uses ``Field.save_form_data()`` rather than a bare ``setattr()``. That
    matters because Django *overloads* the value for ``FileField`` /
    ``ImageField``:

    * ``None``            → "no change", keep the existing file
    * ``False`` / ``""``  → "clear the file"
    * an ``UploadedFile`` → store the new file

    A plain ``setattr(instance, "picture", False)`` stores the boolean itself,
    which then explodes in ``FileField.pre_save`` with
    ``AttributeError: 'bool' object has no attribute 'name'`` (and a bare
    ``None`` silently wipes the stored file).

    Returns the instance for convenient chaining.
    """
    for name, value in data.items():
        try:
            field = instance._meta.get_field(name)
        except FieldDoesNotExist:
            setattr(instance, name, value)
        else:
            field.save_form_data(instance, value)
    return instance


def snapshot(instance: models.Model) -> dict[str, Any]:
    """Capture ``{field: value}`` before mutating a model instance.

    Pass the result to :func:`diff` after the mutation to build a changes dict.

    Auto-managed columns (``created_at`` / ``updated_at``) and the primary key
    are excluded on purpose: ``auto_now`` is bumped on every save, so including
    it would make :func:`diff` report a change for every update and fill the
    audit log with meaningless entries.
    """
    return {
        field.name: getattr(instance, field.name, None)
        for field in instance._meta.fields
        if not field.primary_key
        and not getattr(field, "auto_now", False)
        and not getattr(field, "auto_now_add", False)
    }
