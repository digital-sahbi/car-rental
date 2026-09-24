"""Base settings shared by all environments.

Values that differ between environments live in ``dev.py`` / ``prod.py``.
Secrets and host-specific values come from the environment via python-decouple.
"""
from __future__ import annotations

from pathlib import Path

from decouple import Csv, config

# config/settings/base.py -> config/settings -> config -> project root
BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent

SECRET_KEY: str = config("DJANGO_SECRET_KEY", default="unsafe-dev-key-change-me")
DEBUG: bool = config("DJANGO_DEBUG", default=False, cast=bool)
ALLOWED_HOSTS: list[str] = config("DJANGO_ALLOWED_HOSTS", default="", cast=Csv())

INSTALLED_APPS: list[str] = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third-party
    "modeltranslation",
    # local apps — order matters: core first, then dependants.
    "apps.core",
    "apps.accounts",
    "apps.vehicles",
    "apps.clients",
    "apps.bookings",
    "apps.invoicing",
]

MIDDLEWARE: list[str] = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",  # i18n: must sit after Session
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF: str = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.template.context_processors.i18n",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.company_settings",
                "apps.core.context_processors.notifications",
            ],
        },
    },
]

WSGI_APPLICATION: str = "config.wsgi.application"
ASGI_APPLICATION: str = "config.asgi.application"

# Dev uses SQLite (zero setup). ``prod.py`` overrides this with PostgreSQL,
# which is also where the booking range-exclusion constraint is enforced.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {"transaction_mode": "IMMEDIATE"},
    }
}

# --- Custom user ---
AUTH_USER_MODEL: str = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL: str = "accounts:login"
LOGIN_REDIRECT_URL: str = "core:dashboard"
LOGOUT_REDIRECT_URL: str = "accounts:login"

# --- i18n ---
LANGUAGE_CODE: str = "fr"
LANGUAGES = [("fr", "Français"), ("ar", "العربية"), ("en", "English")]
LOCALE_PATHS: list[Path] = [BASE_DIR / "locale"]

TIME_ZONE: str = "Africa/Casablanca"
USE_I18N: bool = True
USE_TZ: bool = True

# --- Static / media ---
STATIC_URL: str = "/static/"
STATICFILES_DIRS: list[Path] = [BASE_DIR / "static"]
STATIC_ROOT: Path = BASE_DIR / "staticfiles"
MEDIA_URL: str = "/media/"
MEDIA_ROOT: Path = BASE_DIR / "media"

DEFAULT_AUTO_FIELD: str = "django.db.models.BigAutoField"

# modeltranslation: `name` -> name_fr / name_ar / name_en
MODELTRANSLATION_DEFAULT_LANGUAGE = "fr"
MODELTRANSLATION_LANGUAGES = ("fr", "ar", "en")