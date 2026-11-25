# HomeHub Development Journal

> **Purpose:** a compact, dated reading view of meaningful development conversations, decisions, discoveries and recovery points. It is not a live task tracker, a raw chat archive or product authority. Recheck the linked owning issue, latest comments, PR and runtime before acting. [Continuity rules](KNOWLEDGE_WORKFLOW.md) · [Project command center](PROJECT_ADMIN_HUB.md) · [#365 trial](https://github.com/agatte/home-hub/issues/365).

## Resume and browse

- Active goals and gates: [Execution map](EXECUTION_MAP.md) and the [live project board](https://github.com/users/agatte/projects/1).
- Accepted decisions: [Product specification](PROJECT_SPEC.md) and relevant subsystem specs.
- Unimplemented ideas: [Future development index](Future_Development.md); do not silently promote ideas into active work.
- Historical lessons: [dated audits](audits/) and issue/PR evidence.
- Detailed chronological checkpoints: owning issue/PR comments. They are not directly mirrored here; links provide the detail on demand.

## Recent meaningful sessions

### 2026-11-25 — Dashboard UI and Music Intelligence

**Owner intent:** one beautiful, functional HomeHub interface; retire Classic only after parity, explicit retirements and real acceptance. Owner confirmed the [six-stage order](https://github.com/agatte/home-hub/issues/461#issuecomment-7145394652): Home → Control/scenes → Settings/navigation → bounded Music → unified acceptance → Classic retirement.

**Completed slices:** [#568 Home](https://github.com/agatte/home-hub/issues/461#issuecomment-7146281166) (direct unframed mode buttons, restrained colors; visual acceptance); [#575 kitchen](https://github.com/agatte/home-hub/issues/461#issuecomment-7147702627) (Together/Individually, owner-reported operation/appearance); [#576 scenes](https://github.com/agatte/home-hub/issues/461#issuecomment-7148455690) (editor/preview visual acceptance, save and timed/cancel restoration still pending); #577 Settings, #578 mobile parent navigation and [#579 Guest owner return](https://github.com/agatte/home-hub/issues/461#issuecomment-7152556177) (owner return journey accepted; invited guest isolation, wider device coverage and physical mode checks remain in unified acceptance). Last witnessed deployed build cd0b660b; no fresh production probe in this summary. No further speculative redesign of accepted surfaces.

**Music decisions:** mood text → small selection of real albums/playlists/personal mixes → select and listen, without individual track approvals. Healthy familiar/new mix; similar-music continuation; passive listening plus optional feedback; contextual suggestions, not autoplay by default; optional remembered PC-game music preference; native Apple Music listening should inform taste and discoveries should be usable on iPhone away from home, with explicit output destination. Flow first, not cosmetic redesign. [Owner decisions](https://github.com/agatte/home-hub/issues/461#issuecomment-7152829910) · [Bounded contract](https://github.com/agatte/home-hub/issues/461#issuecomment-7152932187).

**Ideas and discoveries:** reuse existing recommendation/taste/semantic/discovery services ([source inventory](https://github.com/agatte/home-hub/issues/461#issuecomment-7152901093)). Scrobblie → Last.fm three-track trial is not active taste learning; top/loved tracks may be opt-in seed hints, not Apple IDs. Soulbeet is a design reference, not an integration dependency. Proposed discovery ratios/game modes are not accepted specifics. Named history, portable custom mixes and game automation remain separate gates. [Source research](https://github.com/agatte/home-hub/issues/254#issuecomment-7142027763).

**Recovery:** [#580](https://github.com/agatte/home-hub/pull/580) remains open draft, now exact 1e278f27e0798093d4d765d96cdb2fb9b2600374; all four [CI jobs](https://github.com/agatte/home-hub/actions/runs/45672541393) passed. Selected-choice exact-identity start, finite and bounded sustained append-only continuation are implemented, not operationally validated. Previous [fresh-chat recovery](https://github.com/agatte/home-hub/issues/461#issuecomment-7153197554) recovered interrupted API test output without rerun; [second recovery](https://github.com/agatte/home-hub/issues/461#issuecomment-7153363952) reconciled the existing worktree and found #570 whole-preview/80:20 mismatch and title-only favorite identity constraint. Current [review evidence](https://github.com/agatte/home-hub/pull/580#issuecomment-7170570893) includes provider identity hardening, unresolved ordinary nonempty-queue compatibility and failed independent Codex auth; no actual speaker compatibility proof.

**Next:** [Latest Sonos checkpoint](https://github.com/agatte/home-hub/pull/580#issuecomment-7171551104): last witnessed live cd0b660b, stopped/no loaded track, volume 0, no active leases; queue count and resource shapes unknown. Existing Sandbox discovery/SSH cannot answer. Owner's existing Latitude terminal must provide bounded sanitized read-only queue/transport evidence; do not repeat valid probes, assume empty queue, clear queue, or extend scope speculatively. Then resolve concrete compatibility and review gaps, separately authorize high-risk integration/deploy and witness real audible start/continuation. #570 remains unmerged; retain its staged work and [failed worker evidence](https://github.com/agatte/home-hub/issues/254#issuecomment-7141931489), reuse only fitting primitives. Unified acceptance and Classic retirement remain open. No account, device or host actions authorized here.

**Source revisions:** #461 @ 2026-11-25T19:27:44Z; #254 @ 2026-11-24T19:28:20Z

### 2026-11-25 — Project Admin continuity

**Owner intent:** preserve meaningful conversations across context limits without losing ideas, repeating work or drifting from the original objective. [Approved scope](https://github.com/agatte/home-hub/issues/365#issuecomment-7141844469).

**Progress:** #569/#571/#572/#574 established anchors, journal/command center and advisory checks; [natural Vault delivery PASS](https://github.com/agatte/home-hub/issues/365#issuecomment-7145070870) Nov 24 16:00 ET, both hashes matched pinned #572 source. [Trial #1](https://github.com/agatte/home-hub/issues/365#issuecomment-7153197996) recovered interrupted work/test output; [trial #2](https://github.com/agatte/home-hub/issues/365#issuecomment-7153400087) recovered primary objective and unfinished task from generic continuation with a stale opening status table later corrected. #581 added meaningful milestone/handoff consolidation, but [follow-up audit](https://github.com/agatte/home-hub/issues/365#issuecomment-7171956115) found another cutoff after only two visible user turns and stale summary despite detailed PR/issue evidence. Actual token/cost causes unknown. On Nov 25, bounded read-only retrieval recovered the latest three #461 comments by fetching four of 424 records, and three #580 comments of 13; this is comment-count evidence, not total token savings. Updated current #461 and #580 anchors, preserving dated histories; narrow retrieval and evidence reuse are explicit workflow rules.

**Source revisions:** #365 @ 2026-11-25T19:12:00Z

**Next:** apply bounded recovery and consolidate during ordinary product milestones; measure recovery elapsed time, records/bytes surfaced, repeat investigations and avoidable prompts, verify natural delivery of newer Markdown when relevant. Two genuine recoveries evidenced; consistent consolidation and quantitative efficiency not proven. Historical export remains separate, locally filtered; no automatic chat capture, new infrastructure or host changes.

## Earlier milestone / lesson

### 2026-11-14–15 — Preserve the redesign critical path

The owner-selected sequence separated the smallest safe redesigned Home release from broader #287/#293 security migration. Existing safety requirements still apply; independent hardening should not automatically become a redesign prerequisite. The owner had to correct the execution sequence more than once. [Controlling dated correction](https://github.com/agatte/home-hub/issues/461#issuecomment-6899745711). Time/cost attributable to context loss is unknown; do not fabricate a baseline.

## Maintenance

Keep recent entries focused on meaningful changes, not every message or PR. At meaningful slice closure, before an anticipated context transition, or first safe recovery after an unexpected cutoff, reconcile material changes into the existing dated summary; batch with authorized reviewed docs where practical. Use weekly reconciliation as a backstop, not a substitute. Replace repetitive status with concise links; promote enduring decisions to their owning spec, ideas to the future-development index and unique failures to dated evidence. Use roughly 30 days of detailed reading and 90 days of weekly detail as preferences, not deletion deadlines. Keep unresolved gates and unique evidence accessible. Do not delete historical issue comments, Git history, Vault snapshots or private exports. No raw chats, personal data, credentials, hidden reasoning, automatic transcript access, or implied permission. The journal is maintained through reviewed repo Markdown and the existing natural mirror, not by editing managed Obsidian files.
