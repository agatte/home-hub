# HomeHub Development Journal

> **Purpose:** a compact, dated reading view of meaningful development conversations, decisions, discoveries and recovery points. It is not a live task tracker, a raw chat archive or product authority. Recheck the linked owning issue, latest comments, PR and runtime before acting. [Continuity rules](KNOWLEDGE_WORKFLOW.md) · [Project command center](PROJECT_ADMIN_HUB.md) · [#365 trial](https://github.com/agatte/home-hub/issues/365).

## Resume and browse

- Active goals and gates: [Execution map](EXECUTION_MAP.md) and the [live project board](https://github.com/users/agatte/projects/1).
- Accepted decisions: [Product specification](PROJECT_SPEC.md) and relevant subsystem specs.
- Unimplemented ideas: [Future development index](Future_Development.md); do not silently promote ideas into active work.
- Historical lessons: [dated audits](audits/) and issue/PR evidence.
- Detailed chronological checkpoints: owning issue/PR comments. They are not directly mirrored here; links provide the detail on demand.

## Recent meaningful sessions

### 2026-11-24 — Dashboard UI and Music Intelligence

**Owner intent:** one unified HomeHub interface, eventually retire Classic only after capability parity and real acceptance. The direct mode buttons are preferred to the dropdown; remove nested card framing, retain subtle mode colors. Navigation generally satisfactory. Music should support new-music/mood sessions without requiring individual track approvals; Settings needs usability refinement. [Owner direction and feedback](https://github.com/agatte/home-hub/issues/461) · [Mode refinement decision](https://github.com/agatte/home-hub/issues/461#issuecomment-7141467589) · [Music requirement](https://github.com/agatte/home-hub/issues/254#issuecomment-7140645451).

**Progress and recovery:** #568 merged with CI success; newer mode styling not yet evidenced deployed or owner-accepted at this checkpoint. #254's original Codex task failed; the later recorded recovery used a bounded direct implementation with 20 focused tests and Ruff passing, publishing the non-actuating planner in [#570](https://github.com/agatte/home-hub/pull/570). The worker's old running status is superseded. Exact worktree, staged blobs and failure details remain in [the recovery checkpoint](https://github.com/agatte/home-hub/issues/254#issuecomment-7141931489).

**Ideas and discovery:** Scrobblie → Last.fm has a recorded three-track trial, not proof of active HomeHub learning. Last.fm top/loved tracks may provide opt-in ephemeral seed hints; names/MBIDs are not Apple playback IDs. Soulbeet is a recommendation-design reference (familiar/balanced/adventurous discovery), not a verified Apple Music/Sonos integration or new stack dependency. Keep the idea under #254/#431 and preserve separate account/retention/playback gates. [Research and limitations](https://github.com/agatte/home-hub/issues/254#issuecomment-7142027763).

**Source revisions:** #461 @ 2026-11-24T19:28:05Z; #254 @ 2026-11-24T19:28:20Z

**Next at this dated checkpoint:** The [newer #461 scope reassessment](https://github.com/agatte/home-hub/issues/461) supersedes Music-first execution. Await owner confirmation of the proposed single-track sequence: Home visual acceptance, Control/scene parity, Settings, bounded Music, unified acceptance, Classic retirement. [#254 parking decision](https://github.com/agatte/home-hub/issues/254#issuecomment-7142144212): preserve #570 and the source research; no merge, new Music implementation, account reads or playback work until the Music slice is selected. Preserve local staged work. Separate release/device approvals remain required.

### 2026-11-24 — Project Admin continuity

**Owner intent:** preserve the meaning of ChatGPT/Codex development sessions across context limits; avoid losing good ideas, rediscovering prior investigations or drifting from the original objective. Begin before the historical export is available. [Approved scope and baseline](https://github.com/agatte/home-hub/issues/365#issuecomment-7141844469).

**Progress:** [#569](https://github.com/agatte/home-hub/pull/569) and [#571](https://github.com/agatte/home-hub/pull/571) merged with exact-head docs CI: objective anchors, blocker evidence, incremental checkpoints, consolidation rules, journal and command-center links. The #254 recovery above superseded the old running-worker checkpoint; a further read preserved the new candidate-source investigation without a duplicate issue or integration project. These are retrieval observations, not independent worker or operational trials. [Integration evidence](https://github.com/agatte/home-hub/issues/365#issuecomment-7142030808).

**Next:** establish this journal's natural Vault delivery, use it during actual remaining redesign work, and measure repeat investigations and recoverability. Historical import remains separate, private/local-filtered and not required to proceed. No host or production changes.

## Earlier milestone / lesson

### 2026-11-14–15 — Preserve the redesign critical path

The owner-selected sequence separated the smallest safe redesigned Home release from broader #287/#293 security migration. Existing safety requirements still apply; independent hardening should not automatically become a redesign prerequisite. The owner had to correct the execution sequence more than once. [Controlling dated correction](https://github.com/agatte/home-hub/issues/461#issuecomment-6899745711). Time/cost attributable to context loss is unknown; do not fabricate a baseline.

## Maintenance

Keep recent entries focused on meaningful changes, not every message or PR. At milestone close or useful weekly reconciliation, replace repetitive status with a concise dated summary and links; promote enduring decisions to their owning spec, ideas to the future-development index and unique failures to dated evidence. Use roughly 30 days of detailed reading and 90 days of weekly detail as preferences, not deletion deadlines. Keep unresolved gates and unique evidence accessible. Do not delete historical issue comments, Git history, Vault snapshots or private exports. No raw chats, personal data, credentials, hidden reasoning, automatic transcript access, or implied permission. The journal is maintained through reviewed repo Markdown and the existing natural mirror, not by editing managed Obsidian files.
