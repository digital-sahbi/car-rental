# 🚗 Smart Rent Car — Internal CRM

Internal management system for a car-rental company based in Marrakech (near
Menara Airport). Employees and administrators only — **there is no public or
guest access**.

Replaces the original single-app `bicycle` prototype (Car + Booking, with dead
`car` and `bike` apps) with a modular Django project.

---

## Features

| Area | What it does |
|---|---|
| **Fleet (`vehicles`)** | Car categories, cars with specs + gallery, status lifecycle, maintenance log |
| **Clients (`clients`)** | Local & international customers, WhatsApp deep links, search |
| **Bookings (`bookings`)** | Date-range rentals, extras, **overbooking prevention**, approval workflow |
| **Invoicing (`invoicing`)** | Auto-numbered `INV-YYYY-####`, immutable snapshots, printable HTML + PDF |
| **Accounts (`accounts`)** | Custom `User` with email login and ADMIN / MANAGER / EMPLOYEE roles |
| **Core (`core`)** | Dashboard, company settings, promotions, immutable audit log |
| **i18n** | FR / AR / EN for templates and model fields, RTL layout for Arabic. See [`locale/README.md`](locale/README.md) |

### Business rules

* **Price is always computed server-side**: `car.price_per_day × days + Σ options`,
  with promotions applied at invoice time. A client-supplied price is ignored.
* **Days are billed inclusively** (pick-up day and return day both count).
* **Overbooking is blocked** for the same car while another booking in a
  blocking status (`pending` / `confirmed` / `ongoing`) overlaps the window.
  Cancelled and completed bookings do not block.
* **Employees cannot edit bookings directly** — they file an `EditRequest` that a
  manager or administrator approves or rejects.
* **Invoices are immutable**: client, car, dates, prices and extras are frozen
  into JSON snapshots at issue time, so later edits never alter an issued
  invoice.
* **Nothing is hard-deleted** — `Car`, `Booking`, `Client` and `Invoice` use
  soft delete (`is_deleted`).

---

## Project layout

```
car-managment-django/
├── manage.py
├── requirements.txt
├── .env                       # secrets (gitignored)
├── .env.example
├── config/                    # project package
│   ├── settings/{base,dev,prod,test}.py
│   └── urls.py, wsgi.py, asgi.py
├── apps/
│   ├── accounts/              # custom User, roles, employee CRUD
│   ├── core/                  # shared bases, audit log, dashboard, promotions
│   ├── vehicles/              # CarCategory, Car, CarImage, Maintenance
│   ├── clients/               # Client
│   ├── bookings/              # Booking, BookingOption, EditRequest
│   └── invoicing/             # Invoice + PDF/HTML rendering
├── templates/                 # namespaced per app, plus base.html + partials
├── static/                    # css/js
├── locale/                    # FR / AR / EN message catalogues
└── media/                     # uploads (cars/, company/, invoices/)
```

---

## Getting started

### 1. Install dependencies

```powershell
python -m pip install -r requirements.txt
```

### 2. Configure the environment

```powershell
Copy-Item .env.example .env
```

Then set a real `DJANGO_SECRET_KEY` in `.env`:

```powershell
python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"
```

### 3. Set up the database

Development uses **SQLite** — nothing to configure.

```powershell
python manage.py migrate
python manage.py seed_demo_data     # optional: realistic demo data
python manage.py runserver
```

`seed_demo_data` creates 3 users, 5 categories, 15 cars (with generated
placeholder images), 10 clients, 20 bookings, invoices and 2 promotions. It is
idempotent; add `--fresh` to wipe business data first.

Demo logins (password `SmartRent2026!`):

| Email | Role |
|---|---|
| `admin@smartrent.ma` | Administrateur (superuser) |
| `manager@smartrent.ma` | Responsable |
| `employe@smartrent.ma` | Employé |

### 4. Run the tests

```powershell
python manage.py test --settings=config.settings.test
```

The `test` settings use a fast password hasher, which takes the suite from
~10 minutes to ~13 seconds.

---

## Routes

| URL | View | Access |
|---|---|---|
| `/` | Dashboard: availability, today's activity, revenue | any employee |
| `/bookings/` | Booking list (search, filters, CSV/Excel export) | any employee |
| `/bookings/add/` | Create a booking | any employee |
| `/bookings/<id>/` | Booking detail **= invoice view** (Print + PDF) | any employee |
| `/bookings/<id>/edit/` | Admin/manager edit directly; employees file an `EditRequest` | role-dependent |
| `/bookings/<id>/print/` | Printable HTML invoice (`window.print()`) | any employee |
| `/bookings/<id>/pdf/` | WeasyPrint PDF download | any employee |
| `/vehicles/`, `/clients/`, `/invoices/`, `/vehicles/maintenance/` | Lists & CRUD | any employee |
| `/edit-requests/` | Approve / reject change requests | MANAGER, ADMIN |
| `/employees/` | Employee CRUD (create, edit, deactivate) | ADMIN |
| `/settings/`, `/promotions/`, `/audit-log/` | Company settings, promos, audit journal | ADMIN |
| `/admin/` | Django admin | staff |

Every route requires authentication. Authenticated users whose role is not
permitted receive **403**, not a redirect.

---

## Architecture notes

**Service layer.** Views never compute prices, check date overlaps, or write to
the ORM directly — that all lives in each app's `services.py`. This keeps the
rules testable in isolation and reusable from the shell or a future API.

**Audit log.** `core.services.log_action()` records CREATE / UPDATE / DELETE /
LOGIN / LOGOUT / APPROVE / REJECT / PRINT with the actor, client IP and a
before/after JSON diff. The diff ignores framework-maintained columns
(`created_by`, `updated_by`, `created_at`, `updated_at`) so saving an unchanged
form logs nothing. `AuditLog` rows are append-only: `save()` refuses updates.

**Overbooking prevention** is enforced in two layers:

1. `bookings.services.assert_car_free()` — runs inside a transaction, locks the
   car row and re-checks for overlaps. Works on every backend: on SQLite
   `transaction_mode = IMMEDIATE` takes the write lock at `BEGIN`, which
   serialises writers.
2. On **PostgreSQL**, migration `bookings/0002` adds an `EXCLUDE USING gist`
   constraint (`daterange … &&`) that blocks overlapping rows at the database
   level. It is a deliberate no-op on SQLite, so one migration graph applies
   everywhere.

**Invoicing.** `invoicing.services.issue_invoice()` runs in a transaction,
draws the next number from a per-year `InvoiceSequence` row locked with
`select_for_update()`, freezes the snapshots, computes VAT and the discount,
and audits the action. `Invoice.save()` compares against the stored snapshot
and refuses any change to an issued document.

---

## Dependencies

`Django`, `python-decouple` (settings), `django-modeltranslation` (i18n fields),
`psycopg[binary]` (PostgreSQL), `pillow` (images), `weasyprint` (invoice PDF),
`openpyxl` (Excel export).

### PDF export requires native libraries

WeasyPrint renders PDFs through **GTK / Pango**, which is a separate native
install (on Windows: the
[MSYS2 GTK runtime](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#windows)).
Without it the PDF endpoint degrades gracefully — the user is redirected to
the booking with an explanatory message, and the **HTML print view remains
fully functional**.

DRF (`djangorestframework`) is present in the environment but deliberately
**not** used or listed: this is a server-rendered internal tool with no API
consumer. Add it back when a mobile app or partner integration exists.
