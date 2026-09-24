"""Root URL configuration.

Route ownership (first match wins):

* ``/admin/``  Django admin
* ``/i18n/``   language switcher (set_language)
* ``/``        accounts (login/logout/employees) → core (dashboard, settings,
  promotions, audit log) → vehicles → clients → bookings → invoicing

Every URL requires authentication; see each app's views for the role gate.
"""
from __future__ import annotations

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),

    # Auth (login/logout) + admin-only employee CRUD.
    path("", include("apps.accounts.urls")),
    # Dashboard, company settings, promotions, audit log.
    path("", include("apps.core.urls")),
    # Fleet + maintenance.
    path("", include("apps.vehicles.urls")),
    # Clients.
    path("", include("apps.clients.urls")),
    # Bookings + edit-request workflow.
    path("", include("apps.bookings.urls")),
    # Invoices: issue / print / PDF.
    path("", include("apps.invoicing.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)