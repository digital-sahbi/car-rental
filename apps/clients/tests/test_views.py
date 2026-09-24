"""Client CRUD through the real forms."""
from __future__ import annotations

from django.test import TestCase
from django.urls import reverse

from apps.clients.models import Client
from apps.core.tests.factories import make_client, make_employee


class ClientFormFlowTests(TestCase):
    """The create/edit/delete round trip.

    These views write through the service layer rather than ``form.save()``, so
    they are checked explicitly — that pattern is where the maintenance-record
    ``self.object`` bug came from.
    """

    def setUp(self):
        self.employee = make_employee()
        self.client.force_login(self.employee)

    def payload(self, **overrides) -> dict:
        data = {
            "name": "Nouveau Client",
            "telephone": "+212 600 000 000",
            "whatsapp": "",
            "email": "",
            "address": "",
            "country": "Maroc",
            "id_document": "AA000000",
            "comment": "",
        }
        data.update(overrides)
        return data

    def test_adding_a_client_redirects_and_saves(self):
        response = self.client.post(reverse("clients:client_add"), self.payload())

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("clients:client_list"))
        self.assertTrue(Client.objects.filter(name="Nouveau Client").exists())

    def test_a_new_client_is_audited(self):
        from apps.core.models import AuditAction, AuditLog

        self.client.post(reverse("clients:client_add"), self.payload())

        self.assertTrue(
            AuditLog.objects.filter(model_name="Client", action=AuditAction.CREATE).exists()
        )

    def test_editing_a_client_redirects_and_saves(self):
        existing = make_client(name="Ancien Nom")

        response = self.client.post(
            reverse("clients:client_edit", args=[existing.pk]),
            self.payload(name="Nom Corrigé"),
        )

        self.assertEqual(response.status_code, 302)
        existing.refresh_from_db()
        self.assertEqual(existing.name, "Nom Corrigé")

    def test_archiving_a_client_redirects_and_soft_deletes(self):
        existing = make_client(name="À Archiver")

        response = self.client.post(reverse("clients:client_delete", args=[existing.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Client.objects.filter(pk=existing.pk).exists())
        self.assertTrue(Client.all_objects.filter(pk=existing.pk, is_deleted=True).exists())

    def test_detail_page_renders(self):
        existing = make_client(name="Fiche Client")
        response = self.client.get(reverse("clients:client_detail", args=[existing.pk]))
        self.assertEqual(response.status_code, 200)

    def test_invalid_submission_is_re_rendered(self):
        response = self.client.post(reverse("clients:client_add"), self.payload(name=""))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Client.objects.filter(name="").count(), 0)
