"""Invoicing URLs — printable HTML and PDF hang off the booking."""
from __future__ import annotations

from django.urls import path

from . import views

app_name = "invoicing"

urlpatterns = [
    path("invoices/", views.InvoiceListView.as_view(), name="invoice_list"),
    path("bookings/<int:pk>/issue/", views.InvoiceIssueView.as_view(), name="invoice_issue"),
    path("bookings/<int:pk>/print/", views.InvoicePrintView.as_view(), name="invoice_print"),
    path("bookings/<int:pk>/pdf/", views.InvoicePDFView.as_view(), name="invoice_pdf"),
]
