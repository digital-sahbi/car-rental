"""Client model helpers: WhatsApp deep links, international detection, search."""
from __future__ import annotations

from django.test import TestCase

from apps.clients import services
from apps.clients.models import Client
from apps.core.tests.factories import make_client


class WhatsAppLinkTests(TestCase):
    """Requirement 16: https://wa.me/<number>."""

    def test_local_moroccan_number_gets_the_212_prefix(self):
        client = make_client(whatsapp="0612345678")
        self.assertEqual(client.whatsapp_link, "https://wa.me/212612345678")

    def test_number_already_in_international_format_is_kept(self):
        client = make_client(whatsapp="+212661234567")
        self.assertEqual(client.whatsapp_link, "https://wa.me/212661234567")

    def test_spaces_and_dashes_are_stripped(self):
        client = make_client(whatsapp="+212 661-234-567")
        self.assertEqual(client.whatsapp_link, "https://wa.me/212661234567")

    def test_telephone_is_used_when_whatsapp_is_missing(self):
        client = make_client(whatsapp="", telephone="0662334455")
        self.assertEqual(client.whatsapp_link, "https://wa.me/212662334455")

    def test_blank_links_are_empty(self):
        client = make_client(whatsapp="", telephone="")
        self.assertEqual(client.whatsapp_link, "")
        self.assertEqual(client.tel_link, "")

    def test_tel_link_has_the_plus_prefix(self):
        client = make_client(telephone="+212 661 234 567")
        self.assertEqual(client.tel_link, "tel:+212661234567")


class InternationalTests(TestCase):
    """``is_international`` drives the local/foreign distinction."""

    def test_moroccan_client_is_not_international(self):
        self.assertFalse(make_client(country="Maroc").is_international)

    def test_moroccan_country_is_case_insensitive(self):
        self.assertFalse(make_client(country="maroc").is_international)

    def test_foreign_client_is_international(self):
        self.assertTrue(make_client(country="France").is_international)


class SearchTests(TestCase):
    """Search covers the fields employees actually type."""

    def setUp(self):
        make_client(name="Ahmed El Fassi", telephone="+212 661 111 111")
        make_client(name="Sophie Durand", telephone="+33 6 12 34 56 78",
                    country="France", id_document="12AB34567")

    def test_search_by_name(self):
        self.assertEqual(services.search_clients("Durand").count(), 1)

    def test_search_by_phone_fragment(self):
        self.assertEqual(services.search_clients("661").count(), 1)

    def test_search_by_document(self):
        self.assertEqual(services.search_clients("12AB").count(), 1)

    def test_search_by_country(self):
        self.assertEqual(services.search_clients("France").count(), 1)

    def test_blank_search_returns_everything(self):
        self.assertEqual(services.search_clients("").count(), 2)


class SoftDeleteTests(TestCase):
    """Clients are archived, not deleted."""

    def test_delete_is_soft(self):
        client = make_client(name="Archive Me")
        services.delete_client(client=client, actor=None)

        self.assertFalse(Client.objects.filter(pk=client.pk).exists())
        self.assertTrue(Client.all_objects.filter(pk=client.pk).exists())
