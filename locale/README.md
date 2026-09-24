# Translations

Django's i18n catalogues live here, one directory per language (`fr`, `ar`, `en`).

Source strings in the code and templates are written in **French**, so `fr` is the
source language: it needs no catalogue at all, and `msgid` is already French.
`ar` and `en` are both fully translated.

| Language | Catalogue | Status |
| --- | --- | --- |
| `fr` | none needed | source language, renders correctly as-is |
| `ar` | `ar/LC_MESSAGES/django.{po,mo}` | complete, RTL |
| `en` | `en/LC_MESSAGES/django.{po,mo}` | complete |

## Extracting and compiling

The GNU gettext tools (`xgettext`, `msgfmt`) are **not required** — and are usually
not installed on Laragon. This project ships two small replacement scripts that
work on plain Python 3:

```powershell
# 1. Regenerate the inventory of every translatable string, and scaffold a
#    .po file with empty msgstr entries for a new language:
& 'C:\laragon\bin\python\python-3.13\python.exe' tools/extract_messages.py --po locale/en/LC_MESSAGES/django.po

# 2. Compile every .po into a .mo, reporting untranslated or missing strings:
& 'C:\laragon\bin\python\python-3.13\python.exe' tools/compile_messages.py

# Validate only, without writing the .mo:
& 'C:\laragon\bin\python\python-3.13\python.exe' tools/compile_messages.py --check
```

`extract_messages.py` also accepts `--json <path>` for the raw inventory.
It scans `apps/**/*.py` (skipping migrations and tests) for `_()`, `gettext`,
`gettext_lazy` and `gettext_noop`, and `templates/**/*.html` for `{% trans %}` and
`{% blocktrans %}`.

> **Restart the server after compiling.** Django's autoreloader only watches `.py`
> files, so a freshly written `.mo` is ignored until the process restarts, and the
> in-process catalogue cache would otherwise keep serving the old language.

The compiled `.mo` files **are committed** (unlike Django's default `.gitignore`
template). Because the toolchain here is a project-owned script rather than
gettext, committing them means a fresh clone runs translated without a build step.
Re-run the compiler whenever you edit a `.po`.

## Model content

Model fields translated with `django-modeltranslation` are declared in each app's
`translation.py` (`vehicles`, `core`). They exist as `*_fr`, `*_ar` and `*_en`
columns, so their content is entered per language in the admin.

`seed_demo_data` writes all three languages for cars, categories, promotions and
the invoice footer. Re-running it backfills languages added after the database was
first seeded (`get_or_create(defaults=…)` never touches existing rows).

## Right-to-left layout

`apps/core/i18n.py` holds the single definition of which languages are
right-to-left.

* Normal templates get `is_rtl` and `current_language` from
  `apps/core/context_processors.py`, which `templates/base.html` turns into
  `dir="rtl"`.
* The invoice templates are rendered through `render_to_string` **without a
  request**, so their context processors never run. `apps/invoicing/pdf.py` passes
  `current_language` and `is_rtl` explicitly for exactly that reason — without it
  the invoice sheet prints left-to-right next to right-to-left Arabic text.
