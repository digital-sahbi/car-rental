"""Language helpers shared by the template layer and the document renderers.

The invoice PDF/print templates are rendered with ``render_to_string`` (no
request object), so Django's context processors do not run for them. They ask
this module for their direction instead, which keeps a single definition of
"which languages are right-to-left".
"""
from __future__ import annotations

# Right-to-left languages. ``ar`` is the only one enabled in settings.LANGUAGES
# today; the others are listed so enabling them later needs no code change.
RTL_LANGUAGES = frozenset({"ar", "he", "fa", "ur", "ps", "sd", "yi"})


def is_rtl(language: str | None) -> bool:
    """Return ``True`` when ``language`` is written right-to-left.

    Accepts both bare codes and locale variants: ``"ar"`` and ``"ar-MA"`` are
    both right-to-left.
    """
    if not language:
        return False
    return language.split("-")[0].lower() in RTL_LANGUAGES
