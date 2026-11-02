"""HomeHub #431 synthetic-only, local, in-memory artist-label review prototype.

Portable developer demo; not a private-data reader, Apple integration,
identity verifier or consent. Loads the merged HomeHub aggregate-only preview
via a normal backend module import, with fictional observations in memory.
No CSV creation, private file access, account login, network, persistence,
recommendation or device effects. Explicit --demo is required for UI.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass

from scripts.apple_music_synthetic_fixture_preview import (
    FIXTURES, _band, build_synthetic_preview,
)

MAX_ITEMS = 32
SOURCE = "synthetic_example_only"
BANDS = ("1_day", "2_to_3_days", "4_to_9_days", "10_plus_days")
DECISIONS = ("Unreviewed", "Needs verification", "Reject label")


@dataclass(frozen=True, repr=False)
class ArtistLabelCandidate:
    """Only fictional demo labels. A label is not a verified catalog artist."""

    label: str
    band: str
    source: str = SOURCE

    def __repr__(self) -> str:
        return "ArtistLabelCandidate(<redacted>)"


# Synthetic fixture labels are NOT output of HomeHub's aggregate-only engine.
DEMO_CANDIDATES = tuple(
    ArtistLabelCandidate(label, _band(days)) for label, days in FIXTURES
)


class LocalArtistReviewDemo:
    """Ephemeral synthetic review state. No export, import or persistence API."""

    __slots__ = ("_items", "_decisions", "_discarded", "_summary")

    def __init__(self, *, demo: bool = False) -> None:
        if demo is not True:
            raise ValueError("Explicit synthetic demo mode is required")
        # Merged HomeHub aggregate preview with invented observations only.
        # Canonical output never contains identity-bearing source rows.
        self._summary = build_synthetic_preview()
        self._items = [
            ArtistLabelCandidate(label, band)
            for label, band in self._summary.fictional_labels
        ]
        self._decisions = [DECISIONS[0]] * len(self._items)
        self._discarded = False

    def __repr__(self) -> str:
        return "LocalArtistReviewDemo(<redacted>)"

    def rows(self) -> tuple[tuple[int, str, str, str, str], ...]:
        """Current in-memory display only: no exact dates or listening records."""
        if self._discarded:
            return ()
        return tuple(
            (i, item.label, item.band, item.source, self._decisions[i])
            for i, item in enumerate(self._items)
        )

    def decide(self, index: int, decision: str) -> None:
        if self._discarded:
            raise ValueError("Review session already discarded")
        if type(index) is not int or not 0 <= index < len(self._items):
            raise ValueError("Invalid demo selection")
        if decision not in DECISIONS or not isinstance(decision, str):
            raise ValueError("Invalid demo review action")
        self._decisions[index] = decision

    def discard(self) -> None:
        """Drop all session references to candidate and decision lists."""
        self._items.clear()
        self._decisions.clear()
        self._summary = None
        self._discarded = True

    @property
    def summary(self):
        return self._summary

    @property
    def discarded(self) -> bool:
        return self._discarded


def create_demo_window():
    """Construct local GUI without entering its event loop (testable in Sandbox)."""
    import tkinter as tk
    from tkinter import ttk

    # Validate synthetic aggregate before allocating any visible Tk window.
    session = LocalArtistReviewDemo(demo=True)
    root = None
    try:
        root = tk.Tk()
        root.title("HomeHub | Apple history review (SYNTHETIC DEMO)")
        root.geometry("920x575")
        root.minsize(760, 490)
        root.configure(bg="#101721")

        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(
            "Review.Treeview", background="#192330", foreground="#f0f4f8",
            fieldbackground="#192330", rowheight=31, borderwidth=0
        )
        style.map("Review.Treeview", background=[("selected", "#345677")])
        style.configure("Review.Treeview.Heading", font=("Segoe UI", 10, "bold"))

        title = tk.Label(
            root, text="Apple listening history  |  SYNTHETIC DEMO",
            bg="#101721", fg="#f5f7fb", font=("Segoe UI", 17, "bold")
        )
        title.pack(anchor="w", padx=24, pady=(20, 5))
        tk.Label(
            root,
            text=("Fictional labels only. No Apple export is opened. Artist-label "
                  "days are exposure, NOT liking, identity proof or playback sessions."),
            bg="#101721", fg="#c3d0de", font=("Segoe UI", 10),
            wraplength=850, justify="left"
        ).pack(anchor="w", padx=24, pady=(0, 9))

        summary = session.summary
        tk.Label(
            root,
            name="synthetic_summary",
            text=(f"HomeHub aggregate preview: {summary.artist_label_days} "
                  f"artist-label days, {summary.provisional_labels} provisional "
                  f"labels; {summary.excluded_ambiguous_rows} ambiguous "
                  "demo rows excluded."),
            bg="#101721", fg="#abcde0", font=("Segoe UI", 10, "bold"),
            wraplength=850, justify="left"
        ).pack(anchor="w", padx=24, pady=(0, 12))

        columns = ("label", "band", "source", "decision")
        table = ttk.Treeview(
            root, columns=columns, show="headings", selectmode="browse",
            style="Review.Treeview"
        )
        for key, text, width in (
            ("label", "Unverified artist label", 250),
            ("band", "Days with a label (demo)", 160),
            ("source", "Source", 150),
            ("decision", "Local review (not identity proof)", 230),
        ):
            table.heading(key, text=text)
            table.column(key, width=width, stretch=(key == "label"))
        table.pack(fill="both", expand=True, padx=24, pady=(0, 12))

        for i, label, band, source, decision in session.rows():
            table.insert("", "end", iid=str(i),
                         values=(label, band.replace("_", " "), source, decision))

        actions = tk.Frame(root, bg="#101721")
        actions.pack(fill="x", padx=24, pady=(0, 8))

        def selected_index() -> int | None:
            chosen = table.selection()
            return int(chosen[0]) if chosen else None

        def mark(decision: str) -> None:
            index = selected_index()
            if index is None:
                return
            session.decide(index, decision)
            table.set(str(index), "decision", decision)

        for caption, decision in (
            ("Needs verification", "Needs verification"),
            ("Reject label", "Reject label"),
            ("Reset to unreviewed", "Unreviewed"),
        ):
            ttk.Button(actions, text=caption,
                       command=lambda d=decision: mark(d)).pack(
                           side="left", padx=(0, 8)
                       )

        def discard_and_close() -> None:
            if session.discarded:
                return
            session.discard()
            children = table.get_children()
            if children:
                table.delete(*children)
            root.destroy()

        ttk.Button(actions, text="Discard and close",
                   command=discard_and_close).pack(side="right")
        root.protocol("WM_DELETE_WINDOW", discard_and_close)

        def on_destroy(event) -> None:
            if event.widget is root:
                session.discard()

        root.bind("<Destroy>", on_destroy, add="+")
        footer = tk.Label(
            root, name="safety_footer",
            text=("No save/export/import, background task, provider login, "
                  "recommendation changes or Sonos actions. "
                  "Selections vanish when this window is closed."),
            bg="#101721", fg="#9caec0", font=("Segoe UI", 9),
            wraplength=850, justify="left"
        )
        # Reserve bottom space before allocating the expandable table.
        table.pack_forget()
        actions.pack_forget()
        footer.pack(side="bottom", fill="x", padx=24, pady=(4, 13))
        actions.pack(side="bottom", fill="x", padx=24, pady=(0, 8))
        table.pack(fill="both", expand=True, padx=24, pady=(0, 12))
        return root, session, table, discard_and_close
    except BaseException:
        # Preserve the creation/setup exception even if Tk cleanup also fails.
        session.discard()
        if root is not None:
            try:
                root.destroy()
            except BaseException:
                pass
        raise



class _DemoOnlyArgumentParser(argparse.ArgumentParser):
    """Do not echo an accidentally supplied private file path on CLI errors."""

    def error(self, message: str) -> None:
        self.exit(2, "Synthetic demo arguments rejected.\n")


def main(argv: list[str] | None = None) -> int:
    parser = _DemoOnlyArgumentParser(description=__doc__)
    parser.add_argument(
        "--demo", action="store_true",
        help="Display synthetic artist labels only; never accesses Apple history"
    )
    args = parser.parse_args(argv)
    if not args.demo:
        parser.print_help()
        return 0
    from tkinter import TclError
    root, session, _table, _discard = create_demo_window()
    try:
        root.mainloop()
    finally:
        # Normal close has already destroyed Tk; do not query dead widgets.
        if not session.discarded:
            session.discard()
            try:
                root.destroy()
            except TclError:
                # Tk may already be destroyed by an external close path.
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
