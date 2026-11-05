"""All names below are synthetic. No HomeHub imports, filesystem or network."""
import unittest
from dataclasses import FrozenInstanceError
from backend.services.apple_music_single_artist_handoff import (
    ArtistPreview, PreparedSingleArtist, OneArtistConsentSession,
    HandoffRefused, RECIPIENT, SOURCE, EVIDENCE, ERROR as HANDOFF_ERROR,
)


class RehearsalTests(unittest.TestCase):
    def setUp(self):
        self.session = OneArtistConsentSession((("Imaginary Comet Quartet", "2-3 days"),
                                                ("Fictional Harbor Ensemble", "1 day")))

    def test_one_exact_label_only(self):
        p = self.session.preview(0)
        b = self.session.approve_once(p.challenge, p.recipient, confirmed=True).body
        self.assertEqual(b["artist_label"], "Imaginary Comet Quartet")
        self.assertEqual(b["source"], SOURCE)
        self.assertEqual(b["evidence"], EVIDENCE)
        self.assertEqual(len(b), 8)
        for flag in ("preference_eligible", "session_proven", "cross_source_independent", "actuation_eligible"):
            self.assertEqual(b[flag], "false")
        with self.assertRaises(HandoffRefused):
            self.session.preview(1)
        with self.assertRaises(HandoffRefused):
            self.session.approve_once(p.challenge, RECIPIENT, confirmed=True)

    def test_no_preview_no_approve(self):
        with self.assertRaises(HandoffRefused):
            self.session.approve_once("arbitrary", RECIPIENT, confirmed=True)

    def test_must_confirm(self):
        p = self.session.preview(0)
        with self.assertRaises(HandoffRefused):
            self.session.approve_once(p.challenge, RECIPIENT, confirmed=False)

    def test_wrong_recipient(self):
        p = self.session.preview(0)
        with self.assertRaises(HandoffRefused):
            self.session.approve_once(p.challenge, "ThirdPartyCatalog", confirmed=True)

    def test_wrong_token(self):
        p = self.session.preview(0)
        with self.assertRaises(HandoffRefused):
            self.session.approve_once("bad", RECIPIENT, confirmed=True)

    def test_reselect_invalidates_old_confirmation(self):
        old = self.session.preview(0)
        new = self.session.preview(1)
        with self.assertRaises(HandoffRefused):
            self.session.approve_once(old.challenge, RECIPIENT, confirmed=True)
        self.assertEqual(self.session.approve_once(new.challenge, RECIPIENT, confirmed=True).body["artist_label"], "Fictional Harbor Ensemble")

    def test_cancel_and_discard(self):
        p = self.session.preview(0)
        self.session.discard()
        with self.assertRaises(HandoffRefused):
            self.session.approve_once(p.challenge, RECIPIENT, confirmed=True)
        with self.assertRaises(HandoffRefused):
            self.session.preview(1)

    def test_bounds_bad_text(self):
        for value in ("", "  fictional", "fictional ", "x"*257, "Evil\u202eName", "Bad\nName", "X\x00Y"):
            with self.subTest(value=repr(value)[:8]):
                s=OneArtistConsentSession(((value, "1 day"),))
                with self.assertRaises(HandoffRefused): s.preview(0)

    def test_utf8_limit_matches_closed_receiver_contract(self):
        from backend.services.apple_music_ephemeral_review_receiver import (
            MAX_ARTIST_UTF8_BYTES, _validate_body,
        )
        from backend.services.apple_music_single_artist_handoff import (
            MAX_ARTIST_UTF8_BYTES as LOCAL_UTF8_CAP,
        )
        self.assertEqual(LOCAL_UTF8_CAP, MAX_ARTIST_UTF8_BYTES)
        # 129 emoji exceed 512 UTF-8 bytes while remaining under 256 code points.
        for label in ("🎼" * 129, "\ud800"):
            with self.subTest(characters=len(label)):
                s=OneArtistConsentSession(((label,"1 day"),))
                with self.assertRaises(HandoffRefused): s.preview(0)
        for label in ("🎼" * 128, "詞" * 170):
            s=OneArtistConsentSession(((label, "1 day"),))
            preview=s.preview(0)
            proposed=s.approve_once(preview.challenge, RECIPIENT, confirmed=True).body
            self.assertEqual(_validate_body(proposed), label)

    def test_bounds_invalid_bands(self):
        for band in ("plays", "favorites", "", "11 days"):
            s=OneArtistConsentSession((("Fictional Quartet", band),))
            with self.assertRaises(HandoffRefused): s.preview(0)

    def test_indices(self):
        for index in (True, -1, 2, "0", 0.0):
            with self.subTest(index=index):
                with self.assertRaises(HandoffRefused): self.session.preview(index)

    def test_schema_and_redaction(self):
        p=self.session.preview(0)
        self.assertEqual(repr(p), "ArtistPreview(<redacted>)")
        self.assertEqual(repr(self.session), "OneArtistConsentSession(<redacted>)")
        ready=self.session.approve_once(p.challenge, RECIPIENT, confirmed=True)
        self.assertEqual(repr(ready), "PreparedSingleArtist(<redacted>)")
        with self.assertRaises(FrozenInstanceError):p.artist_label="changed"

    def test_errors_redacted(self):
        with self.assertRaises(HandoffRefused) as e:self.session.preview(99)
        self.assertEqual(str(e.exception), HANDOFF_ERROR)

    def test_confirmation_requires_real_boolean(self):
        p=self.session.preview(0)
        with self.assertRaises(HandoffRefused):
            self.session.approve_once(p.challenge, RECIPIENT, confirmed="yes")

    def test_body_is_copy_not_mutable_alias(self):
        p=self.session.preview(0)
        prepared=self.session.approve_once(p.challenge, RECIPIENT, confirmed=True)
        a=prepared.body
        a["artist_label"]="tampered"
        self.assertEqual(prepared.body["artist_label"], "Imaginary Comet Quartet")

    def test_no_transport_by_design(self):
        import inspect, backend.services.apple_music_single_artist_handoff as m
        src=inspect.getsource(m)
        for forbidden in ("requests", "urllib", "socket", "sqlite", "httpx", "FastAPI", "open(", "logging.", "Sonos", "music_taste"):
            self.assertNotIn(forbidden, src)

# Additional fictional-only receiver and local-adapter acceptance.

import inspect
import unittest
from concurrent.futures import ThreadPoolExecutor

from backend.services.apple_music_ephemeral_review_receiver import (
    OfflineSingleArtistReceiver, ReviewRefused, ERROR as RECEIVER_ERROR,
)
from scripts.apple_music_single_artist_review_adapter import LocalReviewerAdapter
from backend.services.apple_music_single_artist_handoff import OneArtistConsentSession, HandoffRefused, RECIPIENT


_KEY = b"c" * 32  # SYNTHETIC TEST ONLY. NEVER USE AS A REAL CREDENTIAL.


class FakeReviewer:
    def __init__(self):
        self.candidates = [("Fictional Northwind Quartet", "1 day"),
                           ("Imaginary Harbor Trio", "2-3 days")]

    def discard(self):
        self.candidates.clear()


def draft():
    s = OneArtistConsentSession((("Fictional Northwind Quartet", "1 day"),))
    p = s.preview(0)
    return s.approve_once(p.challenge, RECIPIENT, confirmed=True).body


class SyntheticReceiverTests(unittest.TestCase):
    def new(self, clock=lambda: 0.0):
        return OfflineSingleArtistReceiver(expected_credential=_KEY, clock=clock)

    def test_authenticated_single_receive_take(self):
        r = self.new()
        self.assertEqual(r.receive(draft(), credential=_KEY, transport_verified=True),
                         {"status": "received_for_temporary_review"})
        self.assertEqual(r.take_once(credential=_KEY, transport_verified=True).artist_label,
                         "Fictional Northwind Quartet")
        with self.assertRaises(ReviewRefused):
            r.receive(draft(), credential=_KEY, transport_verified=True)

    def test_no_plain_http(self):
        with self.assertRaises(ReviewRefused):
            self.new().receive(draft(), credential=_KEY)

    def test_missing_wrong_short_credentials(self):
        r = self.new()
        for key in (b"", b"x" * 32, b"c" * 31, "c" * 32):
            with self.subTest(key_type=type(key).__name__):
                with self.assertRaises(ReviewRefused):
                    r.receive(draft(), credential=key, transport_verified=True)
        self.assertEqual(r.receive(draft(), credential=_KEY, transport_verified=True)["status"],
                         "received_for_temporary_review")

    def test_no_private_auth_bypass_concept(self):
        r = self.new()
        for proof in (False, None, "yes", 1):
            with self.assertRaises(ReviewRefused):
                r.receive(draft(), credential=_KEY, transport_verified=proof)

    def test_invalid_payloads_rejected_without_consuming_slot(self):
        b = draft()
        bad = [dict(b, extra="no"), dict(b, preference_eligible="true"),
               dict(b, source="sonos"), dict(b, artist_label="bad\nartist"),
               dict(b, artist_label="x" * 257), dict(b, artist_label=""),
               dict(b, artist_label=True), [b], None, dict(b, artist_label="name\ud800")]
        r = self.new()
        for item in bad:
            with self.assertRaises(ReviewRefused):
                r.receive(item, credential=_KEY, transport_verified=True)
        self.assertEqual(r.receive(b, credential=_KEY, transport_verified=True)["status"],
                         "received_for_temporary_review")

    def test_no_second_name_even_after_take(self):
        r = self.new()
        r.receive(draft(), credential=_KEY, transport_verified=True)
        with self.assertRaises(ReviewRefused):
            r.receive(draft(), credential=_KEY, transport_verified=True)
        r.take_once(credential=_KEY, transport_verified=True)
        with self.assertRaises(ReviewRefused):
            r.take_once(credential=_KEY, transport_verified=True)

    def test_readback_also_requires_authorization(self):
        r = self.new()
        r.receive(draft(), credential=_KEY, transport_verified=True)
        with self.assertRaises(ReviewRefused):
            r.take_once(credential=b"invalid", transport_verified=True)
        with self.assertRaises(ReviewRefused):
            r.take_once(credential=_KEY, transport_verified=False)
        self.assertEqual(r.take_once(credential=_KEY, transport_verified=True).source,
                         "apple_daily_tracks")

    def test_expiry_or_clock_rollback_refuses(self):
        now = [10.0]
        r = self.new(clock=lambda: now[0])
        now[0] = 71.0
        with self.assertRaises(ReviewRefused):
            r.receive(draft(), credential=_KEY, transport_verified=True)
        r = self.new(clock=lambda: now[0])
        now[0] = 69.0
        with self.assertRaises(ReviewRefused):
            r.receive(draft(), credential=_KEY, transport_verified=True)

    def test_discard_drops_pending_name(self):
        r = self.new()
        r.receive(draft(), credential=_KEY, transport_verified=True)
        r.discard()
        with self.assertRaises(ReviewRefused):
            r.take_once(credential=_KEY, transport_verified=True)

    def test_no_detail_echo(self):
        r = self.new()
        self.assertEqual(repr(r), "OfflineSingleArtistReceiver(<redacted>)")
        with self.assertRaises(ReviewRefused) as e:
            r.receive(dict(draft(), artist_label="bad\nartist"), credential=_KEY, transport_verified=True)
        self.assertEqual(str(e.exception), RECEIVER_ERROR)
        ack = r.receive(draft(), credential=_KEY, transport_verified=True)
        self.assertNotIn("Fictional", repr(ack))
        self.assertEqual(repr(r.take_once(credential=_KEY, transport_verified=True)), "EphemeralReview(<redacted>)")

    def test_simultaneous_submissions_only_one_success(self):
        r = self.new()
        body = draft()
        def attempt(_):
            try:
                r.receive(body, credential=_KEY, transport_verified=True)
                return True
            except ReviewRefused:
                return False
        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(attempt, range(64)))
        self.assertEqual(results.count(True), 1)

    def test_credential_min_length(self):
        with self.assertRaises(ReviewRefused):
            OfflineSingleArtistReceiver(expected_credential=b"x")

    def test_no_io_imports(self):
        from backend.services import apple_music_ephemeral_review_receiver as ephemeral_review_receiver
        from scripts import apple_music_single_artist_review_adapter as local_reviewer_adapter
        src = inspect.getsource(ephemeral_review_receiver)+inspect.getsource(local_reviewer_adapter)
        for forbidden in ("requests", "urllib", "socket", "sqlite", "fastapi", "httpx", "open(",
                          "import logging", "MusicArtist", "Sonos", "MusicBandit"):
            self.assertNotIn(forbidden, src)


class ExistingReviewerAdapterTests(unittest.TestCase):
    def test_one_selected_row_and_preapproval_no_payload(self):
        reviewer = FakeReviewer()
        bridge = LocalReviewerAdapter(reviewer)
        p = bridge.preview_selected(("1",))
        self.assertEqual(p.artist_label, "Imaginary Harbor Trio")
        self.assertEqual(bridge.confirm(p, confirmed=True).body["artist_label"], "Imaginary Harbor Trio")
        with self.assertRaises(HandoffRefused):
            bridge.preview_selected(("0",))
        self.assertEqual(len(reviewer.candidates), 2)

    def test_reject_zero_many_invalid_ui_selections(self):
        bridge = LocalReviewerAdapter(FakeReviewer())
        for bad in ((), ("0", "1"), ("00",), ("-1",), ("a",), (0,), ["0"], ("99",)):
            with self.assertRaises(HandoffRefused):
                bridge.preview_selected(bad)

    def test_changing_reviewer_source_invalidates_pending(self):
        reviewer = FakeReviewer()
        bridge = LocalReviewerAdapter(reviewer)
        p = bridge.preview_selected(("0",))
        reviewer.candidates[0] = ("Changed Imaginary Artist", "1 day")
        with self.assertRaises(HandoffRefused):
            bridge.confirm(p, confirmed=True)
        with self.assertRaises(HandoffRefused):
            bridge.preview_selected(("1",))

    def test_replaced_source_list_even_equal_revokes(self):
        reviewer = FakeReviewer()
        bridge = LocalReviewerAdapter(reviewer)
        p = bridge.preview_selected(("0",))
        reviewer.candidates = list(reviewer.candidates)
        with self.assertRaises(HandoffRefused):
            bridge.confirm(p, confirmed=True)

    def test_fake_preview_does_not_authorize_mismatched_display(self):
        from backend.services.apple_music_single_artist_handoff import ArtistPreview
        bridge = LocalReviewerAdapter(FakeReviewer())
        actual = bridge.preview_selected(("0",))
        spoofed = ArtistPreview("Someone Else", actual.date_band, actual.recipient, actual.challenge)
        with self.assertRaises(HandoffRefused):
            bridge.confirm(spoofed, confirmed=True)
        self.assertEqual(bridge.confirm(actual, confirmed=True).body["artist_label"], "Fictional Northwind Quartet")

    def test_reviewer_discard_invalidates_pending(self):
        reviewer = FakeReviewer()
        bridge = LocalReviewerAdapter(reviewer)
        p = bridge.preview_selected(("0",))
        reviewer.discard()
        with self.assertRaises(HandoffRefused):
            bridge.confirm(p, confirmed=True)

    def test_explicit_cancel_no_approval(self):
        bridge = LocalReviewerAdapter(FakeReviewer())
        p = bridge.preview_selected(("0",))
        with self.assertRaises(HandoffRefused):
            bridge.confirm(p, confirmed=False)
        bridge.discard()
        with self.assertRaises(HandoffRefused):
            bridge.confirm(p, confirmed=True)


if __name__ == "__main__":
    unittest.main()
