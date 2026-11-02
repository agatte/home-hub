"""Opt-in, volatile operator review. No source values belong in diagnostics."""
from __future__ import annotations

import argparse
import os
import ntpath
from collections import Counter, defaultdict
from pathlib import Path, PureWindowsPath
import unicodedata

from backend.services.apple_music_artist_familiarity_preview import (
    DailyArtistObservation, _parse, preview_artist_label_days,
)
from backend.services.apple_music_artist_local_audit import _source_day, _safe_int
from backend.services.apple_music_daily_join_audit import DAILY, _csv_rows

SAFE_ERROR = "Local review could not be completed. Session discarded."
BASENAME = "Apple Music - Play History Daily Tracks.csv"
SOURCE = "Apple Daily Tracks - unverified"
BANDS = ("1_day", "2_to_3_days", "4_to_9_days", "10_plus_days")
DISPLAY_BANDS = dict(zip(BANDS, ("1 day", "2-3 days", "4-9 days", "10+ days")))


class ReviewRejected(ValueError):
    def __init__(self):
        super().__init__(SAFE_ERROR)


class LocalReviewSession:
    def __init__(self):
        self.candidates = []
        self.actions = {}
        self.summary = None

    def __repr__(self):
        return "LocalReviewSession(<redacted>)"

    def discard(self):
        self.candidates.clear()
        self.actions.clear()
        self.summary = None


def _band(n):
    return BANDS[0] if n == 1 else BANDS[1] if n <= 3 else BANDS[2] if n <= 9 else BANDS[3]


def _windows_volume_api():
    """Only local volume classification and non-following attribute queries."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    drive_type = kernel.GetDriveTypeW
    drive_type.argtypes = [wintypes.LPCWSTR]
    drive_type.restype = wintypes.UINT
    attributes = kernel.GetFileAttributesW
    attributes.argtypes = [wintypes.LPCWSTR]
    attributes.restype = wintypes.DWORD
    return drive_type, attributes


def _running_on_windows():
    return os.name == "nt"


def _reserved_component(part):
    # Python 3.13+ renamed the Windows reserved-name predicate.
    check = getattr(ntpath, "isreserved", None)
    return check(part) if check is not None else PureWindowsPath(part).is_reserved()


def _require_local_file(selected):
    """Reject network syntax before WinAPI; inspect parents from root to leaf.

    Preflight cannot eliminate TOCTOU: a local component can change between
    attribute checks and the shared reader's open. No race-free identity claim.
    """
    try:
        raw = os.fspath(selected)
        if not isinstance(raw, str):
            raise ReviewRejected()
        # Accept only ordinary drive-absolute paths, excluding devices, ADS,
        # dot traversal and Win32 alias spellings before any native query.
        raw = raw.replace("/", "\\")
        if (len(raw) < 3 or raw[0] not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
                or raw[1:3] != ":\\" or ":" in raw[2:]
                or any(c in raw for c in '\x00<>"|?*')
                or any(unicodedata.category(c).startswith("C") for c in raw)):
            raise ReviewRejected()
        parts = raw[3:].split("\\")
        if any(not part or part in (".", "..") or part.endswith((".", " ")) for part in parts):
            raise ReviewRejected()
        if any(_reserved_component(part) for part in parts):
            raise ReviewRejected()
        if not _running_on_windows():
            raise ReviewRejected()
        drive_type, attributes = _windows_volume_api()
        root = raw[:3]
        if drive_type(root) != 3:  # DRIVE_FIXED only; no remote volume query.
            raise ReviewRejected()
        paths = [root]
        for part in parts:
            paths.append(str(PureWindowsPath(paths[-1]) / part))
        for index, component in enumerate(paths):
            flags = attributes(component)
            if flags == 0xFFFFFFFF or flags & (0x400 | 0x40):  # reparse/device
                raise ReviewRejected()
            if bool(flags & 0x10) != (index < len(paths) - 1):
                raise ReviewRejected()
    except Exception:
        raise ReviewRejected() from None


def read_selected_source(path):
    """One bounded read; canonical parsing and aggregate invariant before return.

    The shared CSV reader transiently parses excluded columns. Only the four
    allowlisted observation fields are retained during analysis.
    """
    session = LocalReviewSession()
    observations = []
    try:
        _require_local_file(path)
        path = Path(path)
        if path.name.casefold() != BASENAME.casefold():
            raise ReviewRejected()
        with _csv_rows(path, DAILY) as (pos, rows):
            for cells in rows:
                description = cells[pos["Track Description"]]
                raw_artist = description.split(" - ", 1)[0]
                if any(unicodedata.category(c).startswith("C") for c in raw_artist):
                    raise ReviewRejected()
                observations.append(DailyArtistObservation(
                    description,
                    _source_day(cells[pos["Date Played"]])[0],
                    _safe_int(cells[pos["Play Count"]]),
                    _safe_int(cells[pos["Play Duration Milliseconds"]]),
                ))
        # Exiting the context completes the shared source-stability check.
        canonical = preview_artist_label_days(observations)
        artists = defaultdict(set)
        metrics = defaultdict(set)
        for row in observations:
            parsed = _parse(row)
            if parsed is None:
                continue
            day, artist, title, plays, duration = parsed
            artists[day, title].add(artist)
            metrics[day, artist, title].add((plays, duration))
        excluded = { (day, title) for (day, artist, title), values in metrics.items() if len(values) != 1 }
        excluded.update(key for key, labels in artists.items() if len(labels) != 1)
        days = defaultdict(set)
        for day, artist, title in metrics:
            if (day, title) not in excluded:
                days[artist].add(day)
        histogram = Counter(_band(len(value)) for value in days.values())
        if (len(days) > 5000
                or len(days) != canonical["counts"]["distinct_provisional_artist_labels"]
                or sum(map(len, days.values())) != canonical["counts"]["candidate_artist_label_days"]
                or {key: histogram[key] for key in BANDS} != canonical["artist_label_day_histogram"]):
            raise ReviewRejected()
        # Never rewrite deceptive controls into a seemingly verified label.
        # Fail the whole session, preserving the canonical invariant.
        if any(unicodedata.category(c).startswith("C") for label in days for c in label):
            raise ReviewRejected()
        session.candidates = [(label, DISPLAY_BANDS[_band(len(value))]) for label, value in sorted(days.items())]
        session.summary = canonical
        return session
    except Exception:
        session.discard()
        raise ReviewRejected() from None
    finally:
        observations.clear()


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "Local review arguments rejected.\n")


class LocalReviewWindow:
    def __init__(self, root):
        from tkinter import ttk, filedialog, messagebox
        self.root = root
        self.session = LocalReviewSession()
        self.used = False
        self.pick = filedialog.askopenfilename
        self.confirm = messagebox.askyesno
        self.alert = messagebox.showerror
        root.report_callback_exception = self.callback_error
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Destroy>", self.destroyed, add="+")
        try:
            root.title("Local unverified artist-label review")
            root.geometry("1000x650")
            ttk.Label(root, wraplength=940, text=(
                "Optional local review of one Apple Daily Tracks CSV. Artist names are personal data. "
                "This session displays unverified artist labels in RAM only. Seen on Apple export dates "
                "does not mean plays, likes, verified artists or catalog identities. Rejection is not dislike. "
                "No save, import, sync or taste update. Closing discards this session. "
                "The CSV reader transiently parses excluded columns too."
            )).pack(fill="x", padx=20, pady=15)
            self.select_button = ttk.Button(root, text="Select local Apple Daily Tracks CSV", command=self.select)
            self.select_button.pack(pady=5)
            self.count = ttk.Label(root, text="No source selected.")
            self.count.pack()
            frame = ttk.Frame(root)
            frame.pack(fill="both", expand=True, padx=20, pady=10)
            self.tree = ttk.Treeview(frame, columns=("label", "band", "source", "action"), show="headings", selectmode="browse")
            for key, label, width in (("label", "Unverified artist label", 320), ("band", "Seen on Apple export dates", 175), ("source", "Source", 240), ("action", "Review", 160)):
                self.tree.heading(key, text=label)
                self.tree.column(key, width=width)
            scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
            self.tree.configure(yscrollcommand=scroll.set)
            scroll.pack(side="right", fill="y")
            self.tree.pack(fill="both", expand=True)
            actions = ttk.Frame(root)
            actions.pack(pady=10)
            for action in ("Needs verification", "Reject label", "Reset"):
                ttk.Button(actions, text=action, command=lambda a=action: self.review(a)).pack(side="left", padx=5)
            ttk.Button(root, text="Close and discard", command=self.close).pack(pady=10)
        except Exception:
            self.close()
            raise ReviewRejected() from None

    def select(self):
        if self.used:
            return
        try:
            selected = self.pick(parent=self.root, title="Select one local Apple Daily Tracks CSV", filetypes=(("CSV files", "*.csv"),))
            if not selected:
                return
            if not self.confirm("Personal data confirmation", "Artist names are personal data. Read this one selected CSV and show unverified labels in RAM only? Closing discards all review results.", parent=self.root):
                return
            self.used = True
            self.select_button.configure(state="disabled")
            self.session = read_selected_source(selected)
            selected = None
            for index, (label, band) in enumerate(self.session.candidates):
                self.tree.insert("", "end", iid=str(index), values=(label, band, SOURCE, "Unreviewed"))
            self.count.configure(text=f"{len(self.session.candidates)} provisional unverified labels")
        except Exception:
            self.fail()

    def review(self, action):
        try:
            for item in self.tree.selection():
                value = "Unreviewed" if action == "Reset" else action
                self.session.actions[item] = value
                self.tree.set(item, "action", value)
        except Exception:
            self.fail()

    def destroyed(self, event):
        if event.widget is self.root:
            self.session.discard()

    def callback_error(self, *ignored):
        self.fail()

    def fail(self):
        self.session.discard()
        # Remove identified widgets before any error dialog.
        try:
            self.tree.delete(*self.tree.get_children())
            self.alert("Local review", SAFE_ERROR, parent=self.root)
        except Exception:
            pass
        finally:
            self.close()

    def close(self):
        self.session.discard()
        try:
            self.root.destroy()
        except Exception:
            pass


def main(argv=None):
    parser = SafeArgumentParser(description="Opt-in local ephemeral label review", allow_abbrev=False)
    parser.add_argument("--local-review", action="store_true")
    args = parser.parse_args(argv)
    if not args.local_review:
        return 0
    root = None
    try:
        import tkinter as tk
        root = tk.Tk()
        LocalReviewWindow(root)
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
