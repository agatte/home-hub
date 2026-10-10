"""Offline Sonos must not make catalog initialization or status fail."""
from types import SimpleNamespace
import unittest

from backend.services.playlist_catalog import AppleMusicShareCatalog


class NetworkDevice:
    def __init__(self):
        self.online = False
        self.reads = 0
        self.value = "HH-TEST"

    @property
    def household_id(self):
        self.reads += 1
        if not self.online:
            raise ConnectionError("No route to host")
        return self.value


class AppleCatalogOfflineTests(unittest.TestCase):
    def setUp(self):
        self.device = NetworkDevice()
        self.sonos = SimpleNamespace(connected=True, device=self.device)

    def catalog(self, proof="HH-TEST"):
        return AppleMusicShareCatalog(
            self.sonos, lookup_source=None, verified_household_id=proof,
        )

    def test_unverified_catalog_does_not_contact_offline_speaker(self):
        catalog = self.catalog(proof=None)
        self.assertFalse(catalog.playback_verified)
        self.assertFalse(catalog.status()["playback_verified"])
        self.assertEqual(self.device.reads, 0)

    def test_household_connection_error_does_not_abort_initialization_or_status(self):
        catalog = self.catalog()
        self.assertFalse(catalog.playback_verified)  # bootstrap log argument
        status = catalog.status()
        self.assertFalse(status["playback_verified"])
        self.assertEqual(status["verification_state"], "queue_test_required")
        self.assertFalse(status["actuation_allowed"])

    def test_disconnected_speaker_does_not_reuse_household_proof(self):
        self.device.online = True
        self.sonos.connected = False
        catalog = self.catalog()
        self.assertFalse(catalog.playback_verified)
        self.assertEqual(self.device.reads, 0)

    def test_recovery_requires_matching_live_household(self):
        catalog = self.catalog()
        self.assertFalse(catalog.playback_verified)
        self.device.online = True
        self.assertTrue(catalog.playback_verified)
        self.device.value = "HH-OTHER"
        self.assertFalse(catalog.playback_verified)
        self.device.value = ""
        self.assertFalse(catalog.playback_verified)
        self.device.online = False
        self.assertFalse(catalog.playback_verified)

    def test_status_reports_one_consistent_verification_result(self):
        self.device.online = True
        status = self.catalog().status()
        self.assertTrue(status["playback_verified"])
        self.assertEqual(status["verification_state"], "live_verified")
        self.assertEqual(self.device.reads, 1)


if __name__ == "__main__":
    unittest.main()
