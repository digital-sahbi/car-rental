"""Manager for the email-based custom user model."""
from __future__ import annotations

from typing import Any, Optional

from django.contrib.auth.base_user import BaseUserManager


class UserManager(BaseUserManager):
    """Manager where ``email`` is the unique identifier."""

    use_in_migrations = True

    def _create_user(self, email: str, password: Optional[str], **extra_fields: Any):
        if not email:
            raise ValueError("L'email est obligatoire.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: Optional[str] = None, **extra_fields: Any):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("role", "EMPLOYEE")
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email: str, password: Optional[str] = None, **extra_fields: Any):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", "ADMIN")
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Un superuser doit avoir is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Un superuser doit avoir is_superuser=True.")
        return self._create_user(email, password, **extra_fields)