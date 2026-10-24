# Next hardware purchase discussion — 2026-10-24

Status: research and provisional recommendation, not an accepted hardware selection or migration approval.

## Confirmed operator priorities

Anthony set a total next-purchase budget of $300–500. The Latitude already provides always-on Home Hub; keeping that capability and improving desktop performance both matter. First desired local AI use is coding and knowledge. Sensors, more microphones and cameras are future interests; counts, retention, voice expectations and offline requirements remain unspecified.

The [September 29 audit](HOME_SERVER_PURCHASE_AUDIT_2026_09_29.md) is preserved unchanged. Its service inventory and capacity assumptions are dated evidence, not a current runtime certification. In particular its RGB references must not be interpreted as reinstating retired OpenRGB work. Its Ethernet plan is not verified feasible.

## Provisional direction

Keep production on the Latitude while evaluating desktop memory pressure. A matched 2x16 GB desktop DDR4 kit is the first upgrade candidate if representative gaming/development actually exhausts physical memory. It does not promise to fix CPU, GPU, network or thermal stalls. Preserve the established preference for DDR4-3600; compare a cheaper DDR4-3200 CL16 kit only as an explicit capacity/price tradeoff, not an automatic recommendation to lower speed. Do not mix the historical slow RAM back in.

Prefer an upgradeable x86 mini PC over Raspberry Pi for an eventual combined Home Hub/OSRS host, but do not purchase merely to duplicate an adequate always-on Latitude. No complete under-budget mini PC passed exact configured price, availability and return-policy checks in this session. Do not assume headline barebone prices include memory or SSD.

Separate stable home services from experimental coding/model workloads. Start local knowledge/coding model evaluation on existing hardware with bounded read-only documents and a disposable project workspace. The RX 5700 XT runtime/performance remains untested. A model capable of answering document questions does not establish autonomous coding reliability or permission to administer production.

## Price evidence checked October 24

Advertised US prices before tax/shipping; no checkout or order was performed.

- [Newegg Team T-Force Vulcan Z 32GB (2x16GB) DDR4-3200 CL16](https://www.newegg.com/p/pl?d=TLZGD432G3200HC16FDC01): $239.99, advertised $40 off with GTWF576 = $199.99; free shipping and Add to cart shown. Coupon eligibility/expiry not checkout-verified.
- [PiShop Pi 5 category](https://www.pishop.us/product-category/raspberry-pi/raspberry-pi-5/): indexed 8GB aluminum starter kit $232, 16GB $362. Included storage and exact stock require verification; do not equate a starter kit with an SSD server.
- [GMKtec M2 Pro S i7-1185G7](https://www.gmktec.com/products/intel-core%E2%84%A2-i7-1185g7-mini-pc-nucbox-m2-pro-s): $279.99 is selected barebone. 16GB/512GB and 32GB/1TB variants exist, but their prices were not established.
- [GMKtec M3 i5-12450H](https://www.gmktec.com/products/intel-12th-core-i5-12450h-mini-pc-nucbox-m3): $299.99 selected barebone; complete variants marked sold out/unavailable.
- [GMKtec M6 Ultra Ryzen 7640HS](https://www.gmktec.com/products/amd-ryzen-5-7640hs-mini-pc-nucbox-m6-ultra): $269.99 selected barebone, not a 32GB/1TB price.
- [Deluxe PCs Dell 7000 Micro i5-12500T 32GB/1TB](https://deluxepcs.com/products/7000mff-12500t-32-1tbn-1p): $849.99 with conflicting Add To Cart/Sold Out text. Reject for this budget.

## Next evidence and discussion

1. Establish current desktop RAM configuration and memory/commit/paging during representative slow workload before spending roughly $200 on memory.
2. Determine whether Latitude will remain home or needs to travel; this changes server urgency.
3. Clarify AI expectations: document Q&A/summaries, coding suggestions, or autonomous build/test work; offline/privacy goal versus experimentation.
4. Choose concrete sensing use cases and approximate rooms/camera count. Continuous recording retention is a separate storage decision. Microphones need endpoint placement/audio design, not just more central RAM.
5. If server replacement becomes first priority, validate a complete 32GB x86 configuration within the $300–500 budget; account for replacement living-room camera and network placement.

GitHub docs are authoritative. The existing Obsidian scheduled mirror is the delivery path; no manual host refresh or current mirror verification was performed.
