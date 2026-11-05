"""Fully synthetic, offline tests; no user CSV, provider API or server access."""
from __future__ import annotations

import unittest
from dataclasses import dataclass

from scripts.apple_music_local_handoff_rehearsal import (
    ArtistHandoffRehearsal, SAFE_CANCEL, SAFE_COMPLETE, SAFE_ERROR, main,
)


class FakeCount:
    def __init__(self):
        self.text = None
    def configure(self, *, text):
        self.text = text


class FakeTree:
    def __init__(self, selected=("0",)):
        self.selected = tuple(selected)
        self.items = {
            "0": ("Imaginary Northbound Quartet", "2-3 days", "Apple Daily Tracks - unverified", "Unreviewed"),
            "1": ("Fictional Mesa Duo", "1 day", "Apple Daily Tracks - unverified", "Unreviewed"),
        }
    def selection(self):
        return self.selected
    def item(self, row_id, option):
        if option != "values":
            raise AssertionError("unexpected tree property")
        return self.items.get(row_id, ())


class FakeReviewSession:
    def __init__(self):
        self.candidates = [("Imaginary Northbound Quartet", "2-3 days"),
                           ("Fictional Mesa Duo", "1 day")]
        self.actions = {}
    def discard(self):
        self.candidates.clear()
        self.actions.clear()


class FakeWindow:
    def __init__(self, selection=("0",), consent=True):
        self.used = True
        self.session = FakeReviewSession()
        self.tree = FakeTree(selection)
        self.root = object()
        self.count = FakeCount()
        self.consent = consent
        self.prompts = []
    def confirm(self, title, message, *, parent):
        assert parent is self.root
        self.prompts.append((title, message))
        return self.consent


class RehearsalTests(unittest.TestCase):
    def test_single_confirm_creates_and_discards_not_sends(self):
        w=FakeWindow()
        controller=ArtistHandoffRehearsal(w)
        self.assertTrue(controller.review_selected())
        self.assertEqual(w.count.text,SAFE_COMPLETE)
        self.assertEqual(len(w.prompts),1)
        self.assertIn("Imaginary Northbound Quartet",w.prompts[0][1])
        self.assertIn("OFFLINE REHEARSAL",w.prompts[0][1])
        self.assertEqual(len(w.session.candidates),2)
        self.assertFalse(controller.review_selected())
        self.assertEqual(len(w.prompts),1)

    def test_reject_cancel_no_prepared_name(self):
        w=FakeWindow(consent=False)
        self.assertFalse(ArtistHandoffRehearsal(w).review_selected())
        self.assertEqual(w.count.text,SAFE_CANCEL)
        self.assertEqual(len(w.prompts),1)

    def test_unselected_or_multiple(self):
        for selected in [(), ("0","1"), ("99",), ("00",)]:
            w=FakeWindow(selection=selected)
            with self.subTest(selected=selected):
                self.assertFalse(ArtistHandoffRehearsal(w).review_selected())
                self.assertFalse(w.prompts)
                self.assertEqual(w.count.text, SAFE_ERROR)

    def test_requires_loaded_source(self):
        w=FakeWindow()
        w.used=False
        self.assertFalse(ArtistHandoffRehearsal(w).review_selected())
        self.assertFalse(w.prompts)

    def test_do_not_offer_rejected_label(self):
        w=FakeWindow()
        w.session.actions["0"]="Reject label"
        self.assertFalse(ArtistHandoffRehearsal(w).review_selected())
        self.assertFalse(w.prompts)

    def test_previously_selected_changes_during_modal(self):
        w=FakeWindow()
        def change(*args, **kwargs):
            w.tree.selected=("1",)
            return True
        w.confirm=change
        self.assertFalse(ArtistHandoffRehearsal(w).review_selected())
        self.assertEqual(w.count.text, SAFE_ERROR)

    def test_displayed_row_mismatch_refused_before_prompt(self):
        w=FakeWindow()
        w.tree.items["0"]=("Different shown artist", "2-3 days", "Apple Daily Tracks - unverified", "Unreviewed")
        self.assertFalse(ArtistHandoffRehearsal(w).review_selected())
        self.assertEqual(w.prompts,[])
        self.assertEqual(w.count.text, SAFE_ERROR)

    def test_displayed_row_change_during_prompt_refused(self):
        w=FakeWindow()
        def change(*args, **kwargs):
            w.tree.items["0"]=("Different shown artist", "2-3 days", "Apple Daily Tracks - unverified", "Unreviewed")
            return True
        w.confirm=change
        self.assertFalse(ArtistHandoffRehearsal(w).review_selected())
        self.assertEqual(w.count.text, SAFE_ERROR)

    def test_displayed_source_name_or_state_drift_refused(self):
        for field, value in [(2, "Untrusted source"), (3, "Accepted match")]:
            w=FakeWindow()
            item=list(w.tree.items["0"])
            item[field]=value
            w.tree.items["0"]=tuple(item)
            self.assertFalse(ArtistHandoffRehearsal(w).review_selected())
            self.assertEqual(w.prompts,[])

    def test_status_mismatch_refused_without_prompt(self):
        w=FakeWindow()
        w.session.actions["0"] = "Needs verification"
        self.assertFalse(ArtistHandoffRehearsal(w).review_selected())
        self.assertEqual(w.prompts, [])
        self.assertEqual(w.count.text, SAFE_ERROR)

    def test_needs_verification_status_consistent_can_rehearse(self):
        w=FakeWindow()
        w.session.actions["0"] = "Needs verification"
        w.tree.items["0"] = (*w.tree.items["0"][:3], "Needs verification")
        self.assertTrue(ArtistHandoffRehearsal(w).review_selected())
        self.assertEqual(w.count.text, SAFE_COMPLETE)

    def test_source_discard_during_modal(self):
        w=FakeWindow()
        def change(*args, **kwargs):
            w.session.discard()
            return True
        w.confirm=change
        self.assertFalse(ArtistHandoffRehearsal(w).review_selected())
        self.assertEqual(w.count.text,SAFE_ERROR)

    def test_source_replacement_during_modal(self):
        w=FakeWindow()
        def change(*args, **kwargs):
            w.session=FakeReviewSession()
            return True
        w.confirm=change
        self.assertFalse(ArtistHandoffRehearsal(w).review_selected())
        self.assertEqual(w.count.text,SAFE_ERROR)

    def test_rejection_during_modal(self):
        w=FakeWindow()
        def change(*args, **kwargs):
            w.session.actions["0"]="Reject label"
            return True
        w.confirm=change
        self.assertFalse(ArtistHandoffRehearsal(w).review_selected())
        self.assertEqual(w.count.text,SAFE_ERROR)

    def test_exception_redacted(self):
        w=FakeWindow()
        def broken(*args,**kwargs):
            raise RuntimeError("PRIVATE ARTIST")
        w.confirm=broken
        self.assertFalse(ArtistHandoffRehearsal(w).review_selected())
        self.assertEqual(w.count.text,SAFE_ERROR)
        self.assertNotIn("PRIVATE",repr(ArtistHandoffRehearsal(w)))

    def test_cli_no_auto_gui(self):
        self.assertEqual(main([]),0)
        with self.assertRaises(SystemExit) as e:
            main(["--offline-rehearsal", "private-path.csv"])
        self.assertEqual(e.exception.code,2)

    def test_no_io_dependencies(self):
        import inspect
        import scripts.apple_music_local_handoff_rehearsal as m
        import scripts.apple_music_single_artist_review_adapter as a
        source=inspect.getsource(m)+inspect.getsource(a)
        for bad in ("import requests","import httpx","import socket","import urllib",
                    "music_taste", "MusicBandit", "import logging"):
            self.assertNotIn(bad,source)


if __name__ == "__main__":
    unittest.main()

# Dialogs can temporarily hand control to other UI callbacks. Never accept
# consent against a review state changed while the modal was visible.
class ConcurrentReviewChangeTests(unittest.TestCase):
    def test_review_change_and_reset_during_modal_are_refused(self):
        w = FakeWindow()
        def change_and_reset(*args, **kwargs):
            w.session.actions['0'] = 'Needs verification'
            w.session.actions['0'] = 'Unreviewed'
            return True
        w.confirm = change_and_reset
        self.assertFalse(ArtistHandoffRehearsal(w).review_selected())
        self.assertEqual(w.count.text, SAFE_ERROR)

    def test_review_status_change_during_modal_is_refused(self):
        w = FakeWindow()
        def change(*args, **kwargs):
            w.session.actions['0'] = 'Needs verification'
            return True
        w.confirm = change
        self.assertFalse(ArtistHandoffRehearsal(w).review_selected())
        self.assertEqual(w.count.text, SAFE_ERROR)

    def test_actions_container_replaced_during_modal_is_refused(self):
        w = FakeWindow()
        def change(*args, **kwargs):
            w.session.actions = dict(w.session.actions)
            return True
        w.confirm = change
        self.assertFalse(ArtistHandoffRehearsal(w).review_selected())
        self.assertEqual(w.count.text, SAFE_ERROR)
