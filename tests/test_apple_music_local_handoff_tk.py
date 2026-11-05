"""Mounted Tk GUI exercise using fabricated labels, no source files or I/O."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
import unittest

from scripts.apple_music_local_handoff_rehearsal import (
    install_rehearsal_button, SAFE_COMPLETE, SAFE_CANCEL,
)
LOCAL_SOURCE = "Apple Daily Tracks - unverified"


class FakeReviewSession:
    def __init__(self):
        self.candidates = [("Fictional Orchid Ensemble", "1 day"),
                           ("Imaginary Lantern Trio", "2-3 days")]
        self.actions = {}


class MountedTkTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("Tk display unavailable")
        self.root.title("Synthetic single artist review")
        self.window = type("FakeMountedWindow", (), {})()
        self.window.root = self.root
        self.window.used = True
        self.window.session = FakeReviewSession()
        self.window.tree = ttk.Treeview(self.root, columns=("label", "band", "source", "action"), show="headings", selectmode="browse")
        for column in ("label", "band", "source", "action"):
            self.window.tree.heading(column, text=column)
        for i, (artist, band) in enumerate(self.window.session.candidates):
            self.window.tree.insert("", "end", iid=str(i), values=(artist, band, LOCAL_SOURCE, "Unreviewed"))
        self.window.tree.pack(fill="both", expand=True)
        self.window.count = ttk.Label(self.root, text="No rehearsal yet")
        self.window.count.pack()
        self.window.prompts = []
        self.window.confirm = self._confirm
        self.approved = True
        self.controller = install_rehearsal_button(self.window)
        self.root.update()

    def tearDown(self):
        if hasattr(self, "root"):
            try: self.root.destroy()
            except tk.TclError: pass

    def _confirm(self, title, message, *, parent):
        self.assertIs(parent, self.root)
        self.window.prompts.append((title, message))
        return self.approved

    def test_real_treeview_one_row_and_button(self):
        self.window.tree.selection_set("1")
        self.root.update()
        self.window.handoff_rehearsal_button.invoke()
        self.root.update()
        self.assertEqual(self.window.count.cget("text"), SAFE_COMPLETE)
        self.assertEqual(len(self.window.prompts), 1)
        self.assertIn("Imaginary Lantern Trio", self.window.prompts[0][1])
        self.assertEqual(len(self.window.session.candidates),2)
        self.window.handoff_rehearsal_button.invoke()
        self.assertEqual(len(self.window.prompts),1)

    def test_real_treeview_display_mismatch(self):
        self.window.tree.selection_set("0")
        self.window.tree.set("0", "label", "Fictional Other Artist")
        self.root.update()
        self.window.handoff_rehearsal_button.invoke()
        self.assertNotEqual(self.window.count.cget("text"), SAFE_COMPLETE)
        self.assertEqual(self.window.prompts, [])

    def test_real_treeview_cancel(self):
        self.approved=False
        self.window.tree.selection_set("0")
        self.root.update()
        self.window.handoff_rehearsal_button.invoke()
        self.assertEqual(self.window.count.cget("text"),SAFE_CANCEL)
        self.assertEqual(len(self.window.prompts),1)

    def test_real_treeview_rejected_action_has_no_prompt(self):
        self.window.session.actions["0"]="Reject label"
        self.window.tree.selection_set("0")
        self.root.update()
        self.window.handoff_rehearsal_button.invoke()
        self.assertEqual(self.window.prompts,[])

    def test_real_treeview_selection_switch_during_dialog(self):
        self.window.tree.selection_set("0")
        def switch(*a, **kw):
            self.window.tree.selection_set("1")
            self.root.update()
            return True
        self.window.confirm=switch
        self.window.handoff_rehearsal_button.invoke()
        self.assertNotEqual(self.window.count.cget("text"),SAFE_COMPLETE)


if __name__ == "__main__":
    unittest.main()
