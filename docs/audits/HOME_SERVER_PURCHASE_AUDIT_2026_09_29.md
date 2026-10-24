# Home server and AI purchase audit

Prepared September 29, 2026 for Anthony. Architecture and purchase-requirements audit; not a live capacity certification or authorization to migrate services.

## Decision

Prefer an upgradeable Intel x86 mini PC running Ubuntu 24.04 LTS, with 32 GB RAM and ideally a 1 TB NVMe SSD, for the expanded goal of Home Hub, OSRS background services, and one isolated coding-agent environment. A 512 GB SSD is a reasonable cost-saving compromise if current retained data and VM sizes fit. No discrete GPU or AI accelerator is required for cloud-model agents or the existing music implementation.

Preferred CPU class: Core i5-12500T or comparable; a substantially cheaper i5-10500T/11500T system remains worth comparing. This is engineering headroom, not a measured application minimum. The earlier i5-8500T/16 GB/256 GB suggestion was for a narrower role and should not be treated as a proven long-term configuration for all the newly requested work. Do not replace a complete, good-value older system merely for a newer badge, but do not pay a premium for an old one either.

Model families to evaluate: Lenovo ThinkCentre M70q Gen 3 and Dell OptiPlex 7000 Micro in the exact i5-12500T configuration. RAM slots, SSD slots, power adapter, firmware support, warranty, and availability must be confirmed for the actual unit. AMD Ryzen mini PCs can be good general-purpose hosts, but the current camera path uses OpenVINO: benchmark the exact model/runtime before choosing AMD for this migration. Intel is the lower-change preference, not a claim that AMD cannot work.

No exact listing is approved for purchase. Increasing the budget is not blanket permission to buy an expensive AI workstation.

## Evidence and limits

Inspected the Home Hub repository's recent commits and current source/documents through GitHub; examined OSRS tracker issues and the recorded cross-host audit. Anthony confirms no coding agents currently run on the Linux Latitude. Documentation contains local machine-learning features and optional cloud-model code; those are different from an installed autonomous coding agent.

The remote interface inspected earlier in this conversation reports a restricted control-plane mode with no arbitrary shell or generic filesystem access. No live Latitude process, memory, disk, temperature, camera throughput, or complete backup inventory was collected. Committed code and historical audits do not prove today's deployment is healthy. No production files, settings, databases, or services were changed.

## Current workload

- Home Hub: Python/FastAPI backend, SQLite, scheduler, Hue/Sonos control, static web dashboard, tunnel/proxy, Pi-hole/Unbound and associated monitoring/services.
- Local sensing: living-room YOLO pose inference through OpenVINO CPU, with other perception and learning components. Taking the Latitude removes its built-in camera and kiosk screen. Budget a replacement USB camera only if keeping living-room sensing; use phone/laptop dashboard initially instead of purchasing a screen.
- Windows remains the hardware-facing workstation for its camera, microphone, display/DDC, RGB and process agents. Moving the backend does not move those physical peripherals.
- OSRS on Latitude: five-minute public-market collector and five-minute selector; persistent archive, received publisher packages, and selector state. September audit measured a roughly 2.79 GiB selector DB and post-fix natural runs of 10–15 seconds wall / 6.3–6.6 CPU-seconds. Earlier swap/I/O pressure was documented. These are historical measurements, not present usage or target-machine benchmarks.
- Windows OSRS: dashboard, authoritative trading DB, publisher and RuneLite integration remain separate. Do not share one live SQLite file between machines over a network filesystem.

## Recent music findings

Reviewed these changes and current bootstrap/source:

- a794335: shared music intelligence and replaceable intent-provider boundary.
- 4530da0: semantic ranking foundation.
- 6cddf10: unified preference evidence (commit history).
- 329b326: narrow assisted playback (commit history and current specification).
- 3dcb154: passive learning restricted to Home Hub-owned playback sessions.

Current bootstrap wires LastFmSemanticAnalyzer. Its source uses Last.fm tags, weighted concepts and deterministic text/preset intent resolution. This is useful semantic ranking, but not a large locally hosted language model or audio-generation model.

The separate MusicCurator is still wired with UnavailableMusicIntentProvider in the inspected bootstrap. Its architecture anticipates a future reasoning provider; no configured model is demonstrated by that code. Current specification documents explicit, trusted exact-track Apple Music playback with ownership and verified-start checks; autonomous contextual DJ behavior remains future work.

The vibe router already supports deterministic lighting interpretation followed by optional Anthropic API fallback, with a cost-cap mechanism. Live credentials/provider availability were not inspected. Keep model-provider choice independent of the music catalogue, playback permissions and physical execution checks.

## Development agents versus product assistants

Development agents edit code, invoke terminals, run browsers, compile and test. The model can run in a cloud service while the tools run in a local VM. Multiple conversations are not necessarily expensive locally; simultaneous browsers, test suites, builds and VMs are. Begin with one active build/test worker and impose CPU, memory and disk limits.

Product assistants answer questions and use a bounded set of Home Hub functions. A recipe question can be a single model request; it need not be a continuously reasoning agent. A music assistant can consult preferences and catalogue tools, then propose a validated playback action. Neither requires terminal access, Git credentials or permission to change the server OS.

Cloud-first is the economical initial design. Expect separate provider usage costs and network dependency; do not assume a chat subscription funds an embedded application API. Add request budgets, timeouts and caching. Ordinary lighting/scheduling should retain deterministic operation when the model or internet is unavailable.

Local LLM hosting is a separate optional workload. 32 GB permits experiments with appropriately sized models, but does not promise conversational speed, large context, multiple concurrent models or coding quality comparable to hosted frontier models. Do not buy GPU/NPU hardware until a specific model, latency requirement and supported runtime justify it. Existing GPU compatibility has not been audited.

## Alexa example

The repository already documents a custom skill using the invocation “home hub”: Echo/Alexa to AWS Lambda, authenticated Cloudflare tunnel/proxy, then Home Hub. Existing intents mostly provide structured control and status. General recipe Q&A is not demonstrated as implemented.

Proposed request flow: Alexa captures a supported question utterance; the skill sends the question to a bounded Home Hub assistant endpoint; the service calls a model, optionally using approved recipe/pantry data; the skill returns text for Alexa to speak. The mini PC hosts the service and context, while the heavy model may run online.

Alexa custom skills have approximately an eight-second response deadline. Progressive speech does not extend it. Slow research cannot simply block the voice request indefinitely; use a short initial answer or an explicitly designed follow-up route such as the dashboard. The current skill README also documents a five-second Lambda setting and historical Alexa+ routing problems. Re-test the actual Echo/account before promising the exact phrase works. Those project observations are not a universal claim about all current Alexa+ accounts.

## Operating system and isolation

Choose Ubuntu 24.04 LTS initially to preserve the existing production environment, Python dependencies, systemd timers and Docker workflows. Windows remains appropriate for Windows-specific development and physical workstation agents. Hosting everything on Windows would introduce additional Linux VM/WSL networking, startup and camera-device questions without a demonstrated benefit here.

A practical initial arrangement is an Ubuntu host running the production services under dedicated identities, plus a separately administered KVM/libvirt VM for development. Agents receive project working copies, not host administration. A separate production VM is possible, but USB camera passthrough and device discovery add migration work. Proxmox is an optional later management choice, not required to obtain VM isolation.

The security boundary must be enforced and tested:

- Agent cannot write host disks, production directories, backup destinations or Windows drives.
- No host administrator credentials, hypervisor-control socket, Docker socket or unrestricted SSH keys inside the agent VM.
- Network policy denies the agent direct production/admin access except explicitly allowed services. LAN APIs matter as much as filesystem shares.
- Product assistant has only narrowly scoped application tools; no shell or development credentials.
- Deployment is a separate reviewed/restricted path. Do not allow an agent to promote its own work through an unrestricted production credential.
- VM snapshots aid rollback. Separate versioned backups outside agent reach provide recovery; another partition or SSD writable by the same agent is not that protection.
- Verify denied access using harmless probes and scratch fixtures, never destructive commands against real data.

Windows-specific testing still needs Windows. An isolated Windows VM may require separate licensing; an OEM license supplied with a mini PC must not be assumed to cover arbitrary guest VMs. Hardware-specific DDC/audio/camera behavior still needs testing on the physical desktop.

## Capacity planning

32 GB is a planning target: allow roughly 8–12 GB for production/camera services, roughly 8–12 GB for one development VM, and the remainder for host/kernel cache and headroom. These are starting budgets for measurement, not observed requirements or rigid reservations. If future sustained usage needs multiple development VMs or much more inference, upgrade to 64 GB only on a validated configuration.

Prefer replaceable SO-DIMM RAM over soldered-only memory, a standard replaceable NVMe SSD, Ethernet, accessible cooling and firmware updates. DDR4 is acceptable; do not pay extra for DDR5 by itself. 1 TB is for working copies, packages, VM disks/snapshots and data growth, not a promise of long camera retention.

For scale: a camera averaging 4 megabits/second consumes about 43 GB/day of continuous video, before filesystem/format overhead. Four cameras at that rate consume roughly 173 GB/day. Recording storage and AI analysis must be sized separately by camera count, codec, resolution, detection cadence and retention. No camera-count guarantee is justified yet.

## Travel, recovery and migration

- Dedicated server stays home on Ethernet; Latitude becomes a client and development machine.
- Tailscale protects remote access without publishing RDP directly. Validate desktop unattended startup and reconnect after a reboot before local login, including any disk-unlock prompts.
- Test from cellular/hotel-like internet; previous Tailscale relay connectivity was functional but not a guarantee of future latency. No home setup guarantees access through a home power or ISP outage.
- Keep server and router separate from the desktop's Kasa EP10. Verify Kasa control from cellular, desktop BIOS power restoration and post-boot remote access. Hard power cycling is emergency recovery, not routine restarting. The EP10 is not a UPS and does not fix ISP or boot failures.
- Copy verified backups of DBs, archives, model assets, calibrations, configuration and service definitions. Git alone is insufficient. Preserve original copies through acceptance.
- Stage new host without duplicate automation or evidence writers; perform one controlled cutover, update Windows publisher/backend destinations, and verify fresh acknowledgements and collector records.
- Preserve Sonos household playback-verification state and test local device discovery/firewalls after moving.
- Reassign travel-mode behavior so the Latitude entering travel mode cannot stop the dedicated server. House Away remains distinct from server lifecycle; remote desktop use must not falsely imply someone returned home.
- Recheck router DNS fallback with the old host absent. Existing documentation records a fallback test, but migration must not silently invalidate it.
- Acceptance should include at least a normal day of camera, OSRS and automation operation while a representative development job runs, plus reboot, laptop-disconnect, backup-restore and external-access checks. This is a recommendation, not a completed test.

## Shopping evidence and purchase gate

Retrieved September 29; web pages may be cached and variant/stock controls can be ambiguous. Prices below are evidence of listings, not verified checkout totals or promises of stock.

- BuyRefurbished M720q $194.99: user confirmed wishlist-only/unavailable. Reject as a purchase option.
- Beelink EQ14 16 GB/500 GB: $385 preorder on official US page. Poor fit for this expanded role at that price.
- GMKtec G3 Plus: sold out on official page. No available budget option established.
- GMKtec M6 Ultra: official displayed $269.99 applies to barebone; 32 GB/1 TB option exists, but its exact price/availability was not verified. Do not quote the barebone price for a complete system.
- Minisforum NAB6 and UM Slim pages: conflicting default variants and Notify Me/Add to Bag text. No ready-to-buy configuration validated.
- Dell 7000 Micro i5-12500T 32 GB/512 GB eBay listing: $535 and out of stock. Reject as a current option.
- Deluxe PCs M70q Gen 3 32 GB/512 GB $634.99 and Dell 7000 32 GB/1 TB $734.99: stock output ambiguous and pages stale. Neither is a value recommendation.

Before purchase, require exact configured delivered price, real stock, delivery date, included adapter, memory arrangement/upgradability, SSD identity or meaningful warranty, clear return terms and no firmware/admin locks. If a complete 32 GB machine costs too much, retain development work in the existing isolated Windows environment temporarily and buy only for measured home-service needs. Do not spend $600–700 merely to accommodate an unspecified six-month possibility.

Remaining uncertainties: live combined load and storage growth; exact budget ceiling; desired number of simultaneous development workers; future camera requirements; cloud-model versus offline/privacy goals; camera replacement; verified current backup location and restore; exact device firmware recovery behavior. These do not require choosing a local LLM now.

## Sources

- [Home Hub specification](https://github.com/agatte/home-hub/blob/master/docs/PROJECT_SPEC.md)
- [Current bootstrap](https://github.com/agatte/home-hub/blob/master/backend/bootstrap.py)
- [Music semantic implementation](https://github.com/agatte/home-hub/blob/master/backend/services/music_semantics.py)
- [Music foundation commit](https://github.com/agatte/home-hub/commit/a79433539a74819830a3cc5128b423c5616a642a)
- [Semantic ranking commit](https://github.com/agatte/home-hub/commit/4530da03c678f5179e32116b7fb8cf77195c2c1d)
- [Passive learning correction](https://github.com/agatte/home-hub/commit/3dcb15463eb4e9f0af99d7674b855703da440f28)
- [Vibe router](https://github.com/agatte/home-hub/blob/master/backend/services/personality/vibe_router.py)
- [Alexa project setup](https://github.com/agatte/home-hub/blob/master/alexa_skill/README.md)
- [OSRS runtime audit](https://github.com/agatte/osrs-flip-assistant-tracker/issues/69)
- [OSRS connectivity audit](https://github.com/agatte/osrs-flip-assistant-tracker/issues/48)
- [Ubuntu libvirt documentation](https://ubuntu.com/server/docs/how-to/virtualisation/libvirt/)
- [Alexa progressive response deadline](https://developer.amazon.com/en-US/docs/alexa/custom-skills/progressive-response-api-reference.html)
- [OpenVINO supported hardware](https://docs.openvino.ai/2026/about-openvino/release-notes-openvino/system-requirements.html)
- [Lenovo M70q Gen 3 specification](https://psref.lenovo.com/syspool/Sys/PDF/ThinkCentre/ThinkCentre_M70q_Gen_3/ThinkCentre_M70q_Gen_3_Spec.pdf)
- [Dell 7000 Micro specification](https://www.dell.com/en-us/shop/desktop-computers/optiplex-7000-micro-form-factor/spd/optiplex-7000-micro)
- [GMKtec M6 Ultra listing](https://www.gmktec.com/products/amd-ryzen-5-7640hs-mini-pc-nucbox-m6-ultra)
- [Dell out-of-stock listing](https://www.ebay.com/itm/277873054275)
- [Lenovo listing checked](https://deluxepcs.com/products/m70qg3-12500t-32-512n-iwf-1p)
- [Dell listing checked](https://deluxepcs.com/products/7000mff-12500t-32-1tbn-1p)

