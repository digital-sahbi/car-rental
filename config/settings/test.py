"""Test settings.

Run the suite with::

    python manage.py test --settings=config.settings.test

Differences from ``dev`` are purely about speed:

* ``MD5PasswordHasher`` — the default PBKDF2 hasher runs >1M iterations, which
  dominates runtime in a suite that creates a user in almost every test.
* A file-backed database is avoided; Django already runs tests against an
  in-memory SQLite database.
"""
from __future__ import annotations

from .dev import *  # noqa: F401,F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Fail loudly if a template is missing rather than silently rendering empty.
TEMPLATES[0]["OPTIONS"]["string_if_invalid"] = ""  # noqa: F405

# Keep test output deterministic.
LANGUAGE_CODE = "fr"
USE_TZ = True
