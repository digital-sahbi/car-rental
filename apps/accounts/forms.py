"""Forms for authentication and (admin-only) employee management."""
from __future__ import annotations

from typing import Any

from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from django import forms

from .models import Role, User


class EmailAuthenticationForm(AuthenticationForm):
    """Login form using email instead of username."""

    username = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={"autofocus": True, "placeholder": "vous@entreprise.ma"}),
    )


class EmployeeForm(forms.ModelForm):
    """Create/update an employee. Password handling differs by mode."""

    password1 = forms.CharField(
        label="Mot de passe",
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Obligatoire à la création ; laisser vide pour conserver en édition.",
    )
    password2 = forms.CharField(
        label="Confirmer le mot de passe",
        required=False,
        widget=forms.PasswordInput(render_value=False),
    )

    class Meta:
        model = User
        fields = (
            "first_name", "last_name", "email",
            "telephone", "whatsapp", "cin", "role", "is_active",
        )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["email"].widget.attrs.update({"placeholder": "vous@entreprise.ma"})
        # On create, password is mandatory.
        if self.instance.pk is None:
            self.fields["password1"].required = True
            self.fields["password2"].required = True

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 or p2:
            if p1 != p2:
                self.add_error("password2", "Les mots de passe ne correspondent pas.")
            elif p1 is not None:
                from django.contrib.auth.password_validation import validate_password

                try:
                    validate_password(p1, self.instance)
                except ValidationError as exc:
                    self.add_error("password1", exc)
        return cleaned

    def save(self, commit: bool = True) -> User:
        user: User = super().save(commit=False)
        password = self.cleaned_data.get("password1")
        if password:
            user.set_password(password)
        if commit:
            user.save()
        return user