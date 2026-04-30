"""
Apartment Logbook — nightly narrative journal generated from event tables.

Runs as a ScheduledTask at 2am, reads activity / light / sonos / scene events
for the previous calendar day (Indiana local time), and writes a single
Markdown file per day to ``data/journal/YYYY-MM-DD.md``. Pure read; the file
is the artifact. Surfaced behind a ``/journal`` route hidden from main nav.

Design notes
------------
- Sections with no data omit themselves rather than print "None" — the
  output should read like prose, not a forms checklist.
- Mode totals are computed from ``ActivityEvent.duration_seconds`` plus the
  inferred duration of the *open* tail session (events whose duration_seconds
  is NULL because no successor has stamped them yet).
- The journal directory is ``data/journal/`` — already gitignored via the
  parent ``data/`` rule, so per-day files never enter version control.
- Narrative composition is deterministic string templating (no LLM). The
  output file is, however, well-suited as grounding context for a future
  LLM-backed assistant.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select

from backend.database import async_session
from backend.models import (
    ActivityEvent,
    LightAdjustment,
    SceneActivation,
    SonosPlaybackEvent,
)

logger = logging.getLogger("home_hub.journal")

TZ = ZoneInfo("America/Indiana/Indianapolis")

_DOW = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

_MODE_LABELS = {
    "gaming": "Gaming",
    "working": "Worked",
    "watching": "Watched media",
    "social": "Social",
    "relax": "Relaxed",
    "cooking": "Cooked",
    "sleeping": "Slept",
    "idle": "Idle",
}


def _format_duration(seconds: float) -> str:
    """Render a second count as ``Xh Ym`` / ``Ym`` for prose."""
    if seconds <= 0:
        return "0m"
    minutes = int(round(seconds / 60))
    if minutes < 60:
        return f"{minutes}m"
    hours, mins = divmod(minutes, 60)
    if mins == 0:
        return f"{hours}h"
    return f"{hours}h {mins}m"


def _format_clock(dt: datetime) -> str:
    """``2:05pm`` style for prose. Strips leading zero from the hour."""
    s = dt.strftime("%I:%M%p").lower()
    if s.startswith("0"):
        s = s[1:]
    return s


class JournalService:
    """Reads event tables and composes nightly Markdown summaries."""

    def __init__(self, journal_dir: Path) -> None:
        self.journal_dir = journal_dir
        self.journal_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate_for_date(self, target_date: date) -> Path:
        """Build and write the journal entry for ``target_date`` (local).

        The day window is ``[target_date 00:00, target_date+1 00:00)`` in
        Indiana time; both bounds are converted to UTC for the query.
        """
        start_local = datetime.combine(target_date, time.min, tzinfo=TZ)
        end_local = start_local + timedelta(days=1)
        start_utc = start_local.astimezone(timezone.utc)
        end_utc = end_local.astimezone(timezone.utc)

        sections = await self._collect_sections(start_utc, end_utc, target_date)
        markdown = self._compose_markdown(target_date, sections)

        path = self._path_for(target_date)
        path.write_text(markdown, encoding="utf-8")
        logger.info("Journal written: %s (%d bytes)", path, len(markdown))
        return path

    async def run_nightly(self) -> None:
        """ScheduledTask callback — generate yesterday's entry."""
        yesterday = (datetime.now(tz=TZ) - timedelta(days=1)).date()
        try:
            await self.generate_for_date(yesterday)
        except Exception as e:
            logger.error("Nightly journal generation failed: %s", e, exc_info=True)

    def list_entries(self) -> list[dict[str, Any]]:
        """Return all journal files sorted newest-first."""
        out: list[dict[str, Any]] = []
        for p in sorted(self.journal_dir.glob("*.md"), reverse=True):
            stem = p.stem
            try:
                d = datetime.strptime(stem, "%Y-%m-%d").date()
            except ValueError:
                continue
            stat = p.stat()
            out.append({
                "date": d.isoformat(),
                "size_bytes": stat.st_size,
                "modified_utc": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc,
                ).isoformat(),
            })
        return out

    def read_entry(self, target_date: date) -> Optional[str]:
        """Load entry markdown for a date, or None if it doesn't exist."""
        path = self._path_for(target_date)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _path_for(self, d: date) -> Path:
        return self.journal_dir / f"{d.isoformat()}.md"

    async def _collect_sections(
        self, start_utc: datetime, end_utc: datetime, target_date: date,
    ) -> dict[str, Any]:
        """Pull raw rows once, return per-section data dicts."""
        async with async_session() as session:
            activity = (await session.execute(
                select(ActivityEvent)
                .where(ActivityEvent.timestamp >= start_utc)
                .where(ActivityEvent.timestamp < end_utc)
                .order_by(ActivityEvent.timestamp.asc())
            )).scalars().all()

            lights = (await session.execute(
                select(LightAdjustment)
                .where(LightAdjustment.timestamp >= start_utc)
                .where(LightAdjustment.timestamp < end_utc)
            )).scalars().all()

            sonos = (await session.execute(
                select(SonosPlaybackEvent)
                .where(SonosPlaybackEvent.timestamp >= start_utc)
                .where(SonosPlaybackEvent.timestamp < end_utc)
            )).scalars().all()

            scenes = (await session.execute(
                select(SceneActivation)
                .where(SceneActivation.timestamp >= start_utc)
                .where(SceneActivation.timestamp < end_utc)
                .order_by(SceneActivation.timestamp.asc())
            )).scalars().all()

        return {
            "modes": self._summarize_modes(activity, end_utc),
            "lights": self._summarize_lights(lights),
            "music": self._summarize_music(sonos),
            "scenes": self._summarize_scenes(scenes),
        }

    def _summarize_modes(
        self, rows, end_utc: datetime,
    ) -> dict[str, Any]:
        """Per-mode totals + first/last clock times for prose.

        Each event's contribution is capped to ``end_utc`` so a session that
        started near midnight doesn't bleed several hours of the *next* day's
        time into today's totals. The pre-first-event gap is not attributed
        to any mode here — that's whichever mode yesterday's last event
        set, and we leave it to yesterday's journal entry.
        """
        if not rows:
            return {"total_transitions": 0, "totals": [], "manual_overrides": 0}

        totals: dict[str, float] = defaultdict(float)
        first_seen: dict[str, datetime] = {}
        last_seen: dict[str, datetime] = {}
        manual_count = 0

        last_row = rows[-1]
        for r in rows:
            ts = r.timestamp
            if ts is None:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            local = ts.astimezone(TZ)
            first_seen.setdefault(r.mode, local)
            last_seen[r.mode] = local
            duration = r.duration_seconds
            if duration is None and r is last_row:
                # Open tail — bound it to end of day.
                duration = max(0.0, (end_utc - ts).total_seconds())
            if duration:
                # Clamp so a session that crosses midnight doesn't double-
                # attribute the spillover to today.
                cap = max(0.0, (end_utc - ts).total_seconds())
                totals[r.mode] += min(float(duration), cap)
            if r.source == "manual":
                manual_count += 1

        rendered = []
        for mode, secs in sorted(totals.items(), key=lambda x: -x[1]):
            if mode == "idle":
                continue  # Idle is the gap between modes — boring to call out.
            rendered.append({
                "mode": mode,
                "label": _MODE_LABELS.get(mode, mode.capitalize()),
                "duration_seconds": int(secs),
                "duration_text": _format_duration(secs),
                "first": _format_clock(first_seen[mode]),
                "last": _format_clock(last_seen[mode]),
            })

        return {
            "total_transitions": len(rows),
            "totals": rendered,
            "manual_overrides": manual_count,
        }

    def _summarize_lights(self, rows) -> dict[str, Any]:
        if not rows:
            return {"total": 0}

        by_light: dict[str, dict[str, Any]] = {}
        by_trigger: dict[str, int] = defaultdict(int)
        for r in rows:
            entry = by_light.setdefault(
                r.light_id,
                {"name": r.light_name or r.light_id, "count": 0},
            )
            entry["count"] += 1
            if r.trigger:
                by_trigger[r.trigger] += 1

        top = max(by_light.values(), key=lambda v: v["count"]) if by_light else None
        return {
            "total": len(rows),
            "top_light": top,
            "manual_count": by_trigger.get("ws", 0) + by_trigger.get("rest", 0),
            "automation_count": by_trigger.get("automation", 0),
            "scene_count": by_trigger.get("scene", 0),
        }

    def _summarize_music(self, rows) -> dict[str, Any]:
        if not rows:
            return {"total": 0}

        by_type: dict[str, int] = defaultdict(int)
        favs: dict[str, int] = defaultdict(int)
        for r in rows:
            by_type[r.event_type] += 1
            if r.favorite_title:
                favs[r.favorite_title] += 1

        top_fav = None
        if favs:
            title = max(favs, key=favs.get)
            top_fav = {"title": title, "count": favs[title]}
        return {
            "total": len(rows),
            "auto_plays": by_type.get("auto_play", 0),
            "manual_plays": by_type.get("play", 0),
            "suggestions": by_type.get("suggestion", 0),
            "skips": by_type.get("skip", 0),
            "top_favorite": top_fav,
        }

    def _summarize_scenes(self, rows) -> dict[str, Any]:
        if not rows:
            return {"total": 0, "items": []}
        items = []
        for r in rows:
            ts = r.timestamp.astimezone(TZ) if r.timestamp else None
            items.append({
                "name": r.scene_name or r.scene_id,
                "source": r.source,
                "time": _format_clock(ts) if ts else None,
            })
        return {"total": len(rows), "items": items}

    def _compose_markdown(
        self, target_date: date, sections: dict[str, Any],
    ) -> str:
        """Stitch the section dicts into a prose Markdown file."""
        dow_label = _DOW[target_date.weekday()]
        # %-d is POSIX-only; Windows needs %#d. Try POSIX first, fall back.
        try:
            long_date = target_date.strftime("%B %-d, %Y")
        except ValueError:
            long_date = target_date.strftime("%B %#d, %Y")

        lines: list[str] = [
            f"# {dow_label}, {long_date}",
            "",
        ]

        modes = sections["modes"]
        if modes["total_transitions"] > 0 and modes["totals"]:
            lines.append("## Modes")
            for entry in modes["totals"]:
                if entry["first"] == entry["last"]:
                    lines.append(
                        f"- **{entry['label']}** — {entry['duration_text']} "
                        f"(around {entry['first']})."
                    )
                else:
                    lines.append(
                        f"- **{entry['label']}** — {entry['duration_text']} "
                        f"({entry['first']}–{entry['last']})."
                    )
            if modes["manual_overrides"]:
                lines.append("")
                lines.append(
                    f"You manually overrode the mode "
                    f"{modes['manual_overrides']} time"
                    f"{'s' if modes['manual_overrides'] != 1 else ''} today."
                )
            lines.append("")

        lights = sections["lights"]
        if lights["total"] > 0:
            lines.append("## Lights")
            top = lights.get("top_light")
            line = f"{lights['total']} adjustment{'s' if lights['total'] != 1 else ''} today"
            if top:
                line += (
                    f" — **{top['name']}** was the busiest "
                    f"({top['count']})."
                )
            else:
                line += "."
            lines.append(line)
            mix = []
            if lights.get("manual_count"):
                mix.append(f"{lights['manual_count']} manual")
            if lights.get("automation_count"):
                mix.append(f"{lights['automation_count']} automated")
            if lights.get("scene_count"):
                mix.append(f"{lights['scene_count']} from scenes")
            if mix:
                lines.append(f"Mix: {', '.join(mix)}.")
            lines.append("")

        music = sections["music"]
        if music["total"] > 0:
            lines.append("## Music")
            parts = []
            if music["auto_plays"]:
                parts.append(
                    f"auto-played {music['auto_plays']} time"
                    f"{'s' if music['auto_plays'] != 1 else ''}"
                )
            if music["manual_plays"]:
                parts.append(
                    f"{music['manual_plays']} manual play"
                    f"{'s' if music['manual_plays'] != 1 else ''}"
                )
            if music["suggestions"]:
                parts.append(
                    f"{music['suggestions']} suggestion"
                    f"{'s' if music['suggestions'] != 1 else ''} surfaced"
                )
            if music["skips"]:
                parts.append(f"{music['skips']} skip{'s' if music['skips'] != 1 else ''}")
            if parts:
                lines.append("Sonos " + ", ".join(parts) + ".")
            top = music.get("top_favorite")
            if top:
                lines.append(
                    f"Most-played: **{top['title']}** "
                    f"({top['count']}×)."
                )
            lines.append("")

        scenes = sections["scenes"]
        if scenes["total"] > 0:
            lines.append("## Scenes")
            for item in scenes["items"]:
                if item.get("time"):
                    lines.append(f"- **{item['name']}** at {item['time']}")
                else:
                    lines.append(f"- **{item['name']}**")
            lines.append("")

        if (
            modes["total_transitions"] == 0
            and lights["total"] == 0
            and music["total"] == 0
            and scenes["total"] == 0
        ):
            lines.append("_Quiet day — no events recorded._")
            lines.append("")

        return "\n".join(lines)
