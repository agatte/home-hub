# Apple Music play-history evidence — handoff (2026-10-31)

> **Status:** Verified *aggregate CSV schema and counts only*; **no importer code, private-row inspection, persistent learning update, production change, or automatic iPhone sync**. Primary implementation issue: [#431](https://github.com/agatte/home-hub/issues/431), child of [#254](https://github.com/agatte/home-hub/issues/254). This is a dated resume note, not a substitute for current code/issues.

## Goal and product boundary

The user primarily listens using the **native iPhone Apple Music app**, including during travel. HomeHub should eventually learn genuine track/artist familiarity and preferences from those listening events, not just pick one of several saved Sonos Favorites. Future ranking must use source-qualified, deduplicated evidence; away listening is **not** room/presence evidence and must **never** actuate Sonos while away. Keep explicit feedback and provider-verified catalog/playback boundaries, DND, Sleeping, Away, manual ownership, and Sonos leases authoritative. Reuse the canonical `backend/services/music_taste.py` and existing Music Intelligence rather than creating a second recommender or learning history.

The user requested an Apple Data & Privacy copy of **Apple Media Services Information** on October 10. The export became available October 31 and was downloaded to the user's private Windows PC. The `Apple Music Activity` directory includes `Apple Music Play Activity.csv`, daily and track play histories, and library metadata exports. **Neither the raw archive nor private song/event rows were shared with this project.** No developer membership or MusicKit credentials were provisioned.

## Verified local read-only evidence

The user executed only a header inspection and an aggregate `Import-Csv` count on **Apple Music Play Activity.csv** (about 92,785 KB uncompressed). Confirmed columns include `Event ID`, `Event Type`, `Event Start Timestamp`, `Event End Timestamp`, `Song Name`, `Album Name`, `Provider ID`, `Play Duration Milliseconds`, `Media Duration In Milliseconds`, `End Reason Type`, `Repeat Play`, `Client Platform`, `Device Type`, `Offline`, `Use Listening History` and `Source Type`. The file also has account, IP, geolocation, device-identity and subscription fields that are **out of scope** for importer reads/logging.

| Observed field/category | Record count |
| --- | ---: |
| Total CSV rows | 69,918 |
| `Event Type = PLAY_END` | 46,429 |
| `Event Type = PLAY_START` | 22,986 |
| `Event Type` blank / `LYRIC_DISPLAY` | 416 / 87 |
| `NATURAL_END_OF_TRACK` | 21,633 |
| `TRACK_SKIPPED_FORWARDS` | 11,945 |
| `PLAYBACK_MANUALLY_PAUSED` | 5,988 |
| `End Reason Type` blank | 23,084 |
| `Song Name` populated | 69,812 |
| `Provider ID` populated | 21,306 |
| `Play Duration Milliseconds` populated | 50,960 |
| `Media Duration In Milliseconds` populated | 68,913 |
| `End Reason Type` populated | 46,834 |
| `Repeat Play` populated | 53,008 |
| `Event ID` populated | 69,918 |

Other ending reasons include selecting another item, other/unsupported, scrub start/end, suspended playback, skipped backwards, failed load and exited application. **These are event counts, not unique track plays, complete listens or independent reward evidence**. Event-ID *population* is not uniqueness. There is no confirmed per-`PLAY_END` joint completeness, validated time range, provider-ID mapping, or cross-device/cross-source deduplication.

## First implementation slice — strict read-only, synthetic-first

1. Inspect current [`AGENTS.md`](../AGENTS.md), [knowledge workflow](KNOWLEDGE_WORKFLOW.md), [product spec](PROJECT_SPEC.md) Music Curator section, #431/#254 and current music taste/library import code and tests. Confirm Git/worktree status and the persistent Codex registry. The Sandbox main was observed clean but behind its origin-tracking branch; use a **fresh isolated branch/worktree** from verified current GitHub `master`, preserving unrelated work.
2. Build a **streaming, bounded, strict-allowlist CSV inspector** with aggregate-only output. It must not log/print/write source rows, titles, account/network/device identifiers or unexpected raw field values. Handle BOM/quoting, missing headers, malformed values, invalid durations/timestamps, file/row limits, unknown event/end codes and duplicated events. No DB/schema writes, audio or production calls.
3. Use synthetic fixtures to test `PLAY_START` versus `PLAY_END`, genuinely qualified natural endings, early/late skips, repeat signals and neutral/ambiguous pauses, scrubs, unknown codes and partial durations. Do **not** turn an ending reason into preference without verifying its event/duration/identity. Provider ID is preferable but often absent; do not assume a song title or `Container Artist Name` alone identifies the track.
4. Verify output provenance, counts, identity/dedup confidence and privacy/exception safety with deterministic tests and static checks. Publish only synthetic fixtures and aggregate conclusions via reviewed source.
5. Only after offline tests and review, run the tool **locally against the private Windows export** using an operator-approved, read-only path. Transfer only the aggregate report to HomeHub project discussion. Do not copy the ZIP/CSV to the Sandbox, GitHub, repository, Obsidian, or Latitude.

**Later, separately gated:** design a private, consented, idempotent importer into canonical taste evidence, with Apple/Sonos overlap rules, rollback and preview before any write. Real recommendation influence, production DB writes, deployment and Sonos playback need separate authorization. Automatic Apple Music account synchronization is a separate MusicKit feasibility/authorization/cost/coverage lane; this historical export is **not** a live iPhone telemetry feed. A local LLM is not required for parsing, event normalization, or deterministic taste inference; optional semantic retrieval/embeddings can be evaluated later.

## Continuity and Obsidian delivery

- Durable state and requirements: [#431](https://github.com/agatte/home-hub/issues/431); parent strategy and prior acceptance: [#254](https://github.com/agatte/home-hub/issues/254).
- Other music/UX work is separate, particularly deferred Calming diversity under #254 and the application-wide redesign [#270](https://github.com/agatte/home-hub/issues/270).
- The Windows `HomeHub Knowledge Vault` is an **automatically refreshed, read-only Obsidian mirror of reviewed Git-tracked Markdown**, not of GitHub issue comments. This note is eligible for the managed mirror **only after it is merged to `master`**. The existing hourly task was operationally verified on October 31 under [#399](https://github.com/agatte/home-hub/issues/399)/[#422](https://github.com/agatte/home-hub/issues/422); this historical observation is **not** evidence that this particular note was physically imported. Do not manually edit `HomeHub Source` or invoke/repair the host task without a distinct approved gate. Verify its exact source SHA and note after the next natural refresh before claiming delivery.

## Restart instruction for a new chat

“Resume HomeHub [#431](https://github.com/agatte/home-hub/issues/431) from the live repo and this dated evidence. Begin with current authority and Git/worktrees/Codex registry. Implement only the synthetic-first, streaming, privacy-safe, non-actuating Apple Music Play Activity inspector, validate it and independently review where warranted; preserve the private operator export and all unrelated work. Stop at separate integration/host-data/DB/playback gates. Update #431/#254 and canonical docs with actual findings and pending gates.”
