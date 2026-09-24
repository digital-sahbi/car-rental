"""WeasyPrint rendering for invoices.

Kept separate from ``services.py`` so that the web layer can be imported (and
tested) on a machine where the native PDF stack is unavailable — WeasyPrint is
imported lazily inside :func:`render_invoice_pdf`.
"""
from __future__ import annotations

from django.template.loader import render_to_string
from django.utils import translation

from apps.core.i18n import is_rtl

from .models import Invoice


def invoice_html(*, invoice: Invoice, for_pdf: bool = False) -> str:
    """Render the invoice template to an HTML string.

    ``for_pdf=True`` uses the PDF template, which inlines print CSS instead of
    the on-screen chrome.
    """
    template = "invoicing/invoice_pdf.html" if for_pdf else "invoicing/invoice_print.html"

    # ``render_to_string`` builds a plain Context, so the context processors
    # (and therefore ``current_language`` / ``is_rtl`` / ``company``) do NOT run.
    # Without these two the sheet prints left-to-right even when the body text is
    # Arabic, so they are supplied explicitly here.
    language = translation.get_language() or "fr"
    return render_to_string(
        template,
        {
            "invoice": invoice,
            "company": _company(),
            "for_pdf": for_pdf,
            "current_language": language,
            "is_rtl": is_rtl(language),
        },
    )


def _company():
    """Company branding, or ``None`` when the singleton is missing."""
    from apps.core.models import CompanySettings

    return CompanySettings.objects.first()


def render_invoice_pdf(invoice: Invoice) -> bytes:
    """Return the invoice as PDF bytes.

    Raises :class:`RuntimeError` with an actionable message when WeasyPrint or
    its native dependencies are unavailable. On Windows WeasyPrint needs the
    GTK/Pango DLLs; without them the import succeeds but rendering fails with
    an ``OSError``, which is why both errors are handled here.
    """
    try:
        from weasyprint import HTML
    except (ImportError, OSError) as exc:
        # ImportError  -> package missing.
        # OSError      -> package present but its native libraries (GTK/Pango)
        #                 cannot be loaded; this is the common Windows case.
        raise RuntimeError(
            "L'export PDF nécessite WeasyPrint et ses bibliothèques natives "
            "(GTK/Pango). Utilisez l'impression HTML, ou installez les "
            "dépendances GTK puis relancez."
        ) from exc

    html = invoice_html(invoice=invoice, for_pdf=True)
    try:
        return HTML(string=html).write_pdf()
    except OSError as exc:  # pragma: no cover - depends on the host
        raise RuntimeError(
            "WeasyPrint n'a pas pu produire le PDF (bibliothèques natives "
            "indisponibles). Utilisez l'impression HTML en attendant."
        ) from exc
