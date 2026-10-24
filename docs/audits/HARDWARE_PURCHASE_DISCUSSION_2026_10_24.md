# Next hardware purchase discussion — 2026-10-24

Status: research and provisional recommendation, not an accepted hardware selection or migration approval.

## Latest clarification and shopping pass — October 24 (supersedes provisional RAM-first direction below)

Anthony is currently taking the Latitude on work trips. Local AI goals include editing code/running tests and a personalized Alexa/Home Hub assistant for moods and general questions. Therefore a dedicated always-home server is now the first purchase candidate, ahead of desktop RAM. The earlier RAM-first discussion below is retained as history. No hardware selected or ordered; no migration authorized.

Complete configuration checks:
- [HP EliteDesk 800 G6, i5-10500T, 32GB/512GB at REFURB.io](https://us.refurb.io/collections/32gb-ram-desktops/products/hp-elitedesk-800-g6-mini-desktop-i5-10500t-32gb-ram-512-gb-solid-state-drive-windows-11-pro-refurbished): $564 with advertised extra 13% off orders over $500, calculated $490.68 before tax. Promotion ends November 4, 2026; not checkout-verified. Page reports 104 in stock, free continental-US delivery, AC adapter and one-year parts/labor warranty. Wi-Fi not specified. Returns page: 30 days from purchase, 15% nondefective-return restocking fee.
- [Same CPU/RAM/storage HP at Best Buy Marketplace](https://www.bestbuy.com/product/hp-elitedesk-800g6-mini-intel-i5-10500t-32gb-512gb-ssd-windows-11-pro-black/J39WY9H4HP/sku/10117534): $485, Add to cart and free shipping shown; seller CNB Computers USA Inc, 3.49/5 from 73 ratings, 90-day warranty. Displayed delivery ZIP was not Anthony's. Wi-Fi, exact adapter and seller-specific return details still need confirmation.
- GMKtec first-party public product JSON confirmed US-plug complete variants available: [M2 Pro S](https://www.gmktec.com/products/intel-core%E2%84%A2-i7-1185g7-mini-pc-nucbox-m2-pro-s?variant=47321213567130), i7-1185G7, 32GB/1TB $579.99 (16GB/512GB $459.99); [M5 Ultra](https://www.gmktec.com/products/gmktec-nucbox-m5-ultra-amd-ryzen-7-7730u-mini-pc?variant=47330098151578), Ryzen 7730U, 32GB/1TB $599.99 (16GB/512GB $449.99); [M6 Ultra](https://www.gmktec.com/products/amd-ryzen-5-7640hs-mini-pc-nucbox-m6-ultra?variant=47330369405082), Ryzen 7640HS, 32GB/1TB $679.99 (16GB/512GB $499.99). These replace unverified complete-variant prices earlier. Product pages advertise one-year warranty and seven-day returns; no checkout shipping total verified.
- Deluxe PCs M70q Gen 1 32GB/512GB $454.99: public product JSON says available=false. Exclude; page's mixed Add to cart/Sold Out text was not proof of stock. Also lacks Wi-Fi.
- Micro Center lists M5 Ultra 32GB/1TB $699.99 and M3 Pro 32GB/1TB $749.99, pickup-only; no Indianapolis stock confirmed. Not value picks here.
- eBay M2 Pro listings 168421486196 and 178517042083 were already SOLD; exclude.

Assessment: REFURB.io HP is a plausible production-server candidate near $500 before tax, not an unconditional buy. Its warranty is more attractive than the cheaper Marketplace HP, but Wi-Fi and return costs matter. None is a proven fast all-local coding-agent plus production host. Keep model inference and isolated build/test resources separately budgeted; do not promise local LLM performance from RAM capacity alone. Current confirmed 32GB new units exceed the $500 budget. Network placement, replacement living-room camera and delivered total remain purchase gates.

## Confirmed operator priorities (initial discussion)

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
