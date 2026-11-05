"""Optional, OFFLINE ONLY, one-artist consent exercise for the existing Tk reviewer.

This module does not send names to HomeHub. It does not perform file selection,
open any CSV, use HTTP, or register an API route. The original standalone local
reviewer is unchanged. Every name shown here stays on the operator's PC.

The button is intentionally labelled 'offline rehearsal' to distinguish
consent-composition testing from a functional HomeHub transfer.
"""
from __future__ import annotations

import argparse
from typing import Any

from backend.services.apple_music_single_artist_handoff import HandoffRefused, RECIPIENT
from scripts.apple_music_single_artist_review_adapter import LocalReviewerAdapter
LOCAL_SOURCE = "Apple Daily Tracks - unverified"  # Pinned to existing LocalReviewWindow source label.

SAFE_ERROR = "Offline artist review could not be completed. No data sent."
SAFE_CANCEL = "Offline review canceled. No data sent."
SAFE_COMPLETE = "Offline consent rehearsal complete. No artist name sent or saved."


class ArtistHandoffRehearsal:
    """One attempt per opened local-review window; no destination transport.

    The existing LocalReviewWindow treeview, session and user-facing modal
    callbacks are supplied by the UI. Confirmation is not a server credential.
    """

    def __init__(self, window: Any) -> None:
        self._window = window
        self._attempted = False

    def __repr__(self) -> str:
        return "ArtistHandoffRehearsal(<redacted>)"

    @staticmethod
    def _tree_matches_source(window: Any, row_id: str, artist: str, band: str) -> bool:
        """The displayed Tk row must agree with the underlying source row.

        A UI label is not a trustworthy source of identity, but this prevents
        confirming a different displayed name than the selected source value.
        """
        if not hasattr(window.tree, "item"):
            return False
        values = window.tree.item(row_id, "values")
        actions = window.session.actions
        expected_status = actions.get(row_id, "Unreviewed")
        return (type(values) in (tuple, list) and len(values) == 4
                and values[0] == artist and values[1] == band
                and values[2] == LOCAL_SOURCE
                and expected_status in {"Unreviewed", "Needs verification"}
                and values[3] == expected_status)

    def review_selected(self) -> bool:
        """Ask for explicit local per-name consent; discard the prepared body.

        No artist name is returned. Invalid input and cancellation never prepare
        a body. This function is not a sender and must not be used as one.
        """
        if self._attempted:
            return False
        adapter: LocalReviewerAdapter | None = None
        prepared = None
        body = None
        try:
            window = self._window
            if window.used is not True:
                raise HandoffRefused()
            session = window.session
            if not isinstance(session.candidates, list):
                raise HandoffRefused()
            selection = tuple(window.tree.selection())
            if len(selection) != 1 or session.actions.get(selection[0]) == "Reject label":
                raise HandoffRefused()
            # Compare the local review state before and after the modal dialog;
            # a nested Tk event loop may allow unrelated review callbacks.
            actions = session.actions
            initial_actions = dict(actions)
            adapter = LocalReviewerAdapter(session)
            preview = adapter.preview_selected(selection)
            if not self._tree_matches_source(window, selection[0], preview.artist_label, preview.date_band):
                raise HandoffRefused()
            # A deliberate, single-item confirmation. No network is attempted.
            self._attempted = True
            approved = window.confirm(
                "OFFLINE ONLY — single artist review rehearsal",
                "Selected unverified artist: " + preview.artist_label + "\n"
                "Seen on Apple export dates: " + preview.date_band + "\n\n"
                "Future recipient: " + RECIPIENT + "\n"
                "Only this name plus fixed unverified-source flags would be "
                "included; no other artist or source row.\n\n"
                "This is an OFFLINE REHEARSAL. No artist name will be sent, "
                "saved, looked up or used to change recommendations.\n\n"
                "Confirm this selection for the offline test?",
                parent=window.root,
            )
            if approved is not True:
                window.count.configure(text=SAFE_CANCEL)
                return False
            # Tk dialogs run a nested event loop: selection and review state
            # can change during the confirmation prompt. Recheck AFTER return.
            if (tuple(window.tree.selection()) != selection
                    or window.session is not session
                    or session.actions is not actions
                    or dict(actions) != initial_actions
                    or session.actions.get(selection[0]) == "Reject label"
                    or not self._tree_matches_source(window, selection[0], preview.artist_label,
                                                     preview.date_band)):
                raise HandoffRefused()
            prepared = adapter.confirm(preview, confirmed=True)
            # Construct the exact proposed eight-field body, then discard it.
            # Not passed to any sender, file writer, logger or backend API.
            body = prepared.body
            if (len(body) != 8 or body["artist_label"] != preview.artist_label
                    or body["source"] != "apple_daily_tracks"
                    or body["preference_eligible"] != "false"):
                raise HandoffRefused()
            window.count.configure(text=SAFE_COMPLETE)
            return True
        except Exception:
            # Keep the failure fixed, without displaying private names.
            try:
                self._window.count.configure(text=SAFE_ERROR)
            except Exception:
                pass
            return False
        finally:
            if body is not None:
                body.clear()
            prepared = None
            if adapter is not None:
                adapter.discard()


def install_rehearsal_button(window: Any) -> ArtistHandoffRehearsal:
    """Extend a real LocalReviewWindow without modifying its normal launcher."""
    from tkinter import ttk

    controller = ArtistHandoffRehearsal(window)
    window.handoff_rehearsal_button = ttk.Button(
        window.root,
        text="Review one artist (offline test — does not send)",
        command=controller.review_selected,
    )
    window.handoff_rehearsal_button.pack(pady=4)
    return controller


class _SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.exit(2, "Offline handoff arguments rejected.\n")


def main(argv: list[str] | None = None) -> int:
    parser = _SafeParser(allow_abbrev=False)
    parser.add_argument("--offline-rehearsal", action="store_true")
    args = parser.parse_args(argv)
    if not args.offline_rehearsal:
        return 0
    root = None
    try:
        import tkinter as tk
        from scripts.apple_music_local_artist_review import LocalReviewWindow
        root = tk.Tk()
        window = LocalReviewWindow(root)
        install_rehearsal_button(window)
        root.mainloop()
        return 0
    except Exception:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
