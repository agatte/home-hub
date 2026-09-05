# Apple Health Sleep Evidence (GH#236)

Status: Phase 1 shadow/calibration design. No Apple Health evidence has lifecycle
authority yet. Manual Sleeping remains primary, and #235 owns wake authority.

## Goal

Use Apple Watch / Apple Health as the privacy-compatible overnight sleep/wake
evidence lane while HomeHub cameras remain off during established Sleeping.
The first phase records evidence and delivery behavior only. Automatic Sleeping
is a later graduation decision after several representative nights of data.

HomeHub is not a sleep-quality product. It does not calculate a sleep score,
make medical claims, or treat HomeHub Sleeping duration as physiological sleep.

## Apple platform facts that shape the design

- HealthKit `sleepAnalysis` samples can represent in-bed, awake, core, deep, REM,
  and unspecified sleep stages.
- Apple notes that Watch-generated `awake` samples occur only between sleep
  samples; detailed samples may be absent at the beginning or end of in-bed
  time. Absence of an `awake` sample therefore cannot prove continued sleep.
- HealthKit access requires an iOS/watchOS app with the HealthKit capability and
  explicit user authorization for each data type. HomeHub's Linux backend cannot
  read the HealthKit store directly.
- Background delivery uses a HealthKit observer query plus the background-
  delivery entitlement. The observer reports that something changed; a follow-up
  sample/anchored query retrieves the actual objects.
- Anchored queries return new and deleted objects since the previous anchor.
  The client must retain its anchor and handle deletion UUIDs.
- Background delivery is system-managed, not a real-time guarantee. Phase 1
  measures actual latency on Anthony's devices rather than assuming a deadline.

Primary references:
- https://developer.apple.com/documentation/healthkit/hkcategoryvaluesleepanalysis
- https://developer.apple.com/documentation/healthkit/authorizing-access-to-health-data
- https://developer.apple.com/documentation/healthkit/executing-observer-queries
- https://developer.apple.com/documentation/healthkit/hkanchoredobjectquery
- https://developer.apple.com/documentation/healthkit/hksourcerevision

## Chosen architecture

Preferred production observation path:

`Apple Watch -> HealthKit store on iPhone -> small read-only iOS bridge -> authenticated HomeHub ingest -> shadow calibration table`

The bridge sends evidence. It never sends `house_state=...` and never decides
whether HomeHub is Sleeping or Home.
### iOS bridge responsibilities

1. Enable HealthKit read access for `HKCategoryType(.sleepAnalysis)` only.
2. Install the observer query at app launch and request background delivery.
3. Use a persisted `HKQueryAnchor` to fetch only new/changed samples.
4. Map HealthKit categories to HomeHub's bounded stage enum.
5. Send HealthKit UUID, start/end time, source revision provenance, and the time
   the client observed the anchored-query result.
6. Send deleted HealthKit UUIDs as tombstones.
7. Retry safely. Do not advance past undelivered changes without durable local
   retry state; duplicate POSTs are intentionally idempotent server-side.
8. Call the HealthKit observer completion handler promptly after work is safely
   handed off so background delivery is not penalized.

The bridge should request read permission only. It has no reason to write sleep
or other health samples into HealthKit.

## HomeHub ingest contract

`POST /api/sleep/evidence`

The path is the only Apple Health surface allowed through the public Cloudflare
tunnel. Tunnel callers still require both `X-API-Key` and `X-Skill-Token`; use
`X-Source: ios_healthkit:<client>` for attribution. Raw review is not public.

The request is a batch so one HealthKit observer wake can deliver multiple
changed samples and deletions efficiently. Both batch and sample objects reject
unknown JSON fields, and the public tunnel rejects sleep-evidence bodies larger
than 128 KiB before forwarding them to the backend.
Example:

```json
{
  "client_kind": "healthkit_observer",
  "client_observed_at": "2026-09-06T06:42:10-04:00",
  "client_version": "1",
  "samples": [
    {
      "sample_uuid": "550e8400-e29b-41d4-a716-446655440000",
      "stage": "asleep_core",
      "start_at": "2026-09-06T06:24:00-04:00",
      "end_at": "2026-09-06T06:40:00-04:00",
      "source_bundle_id": "<HealthKit source bundle>",
      "source_product_type": "<HealthKit source product type>",
      "source_version": "<source revision version>"
    }
  ],
  "deleted_sample_uuids": []
}
```

Accepted stages are `in_bed`, `awake`, `asleep_core`, `asleep_deep`,
`asleep_rem`, and `asleep_unspecified`.

HealthKit sample UUIDs are immutable identities. A retry with the same UUID and
same sample data updates delivery bookkeeping rather than creating a duplicate;
a UUID reused with different stage/times is rejected. Missing provenance may be
filled in later without changing the sample identity.
## Calibration timing semantics

For each sample HomeHub preserves:

- HealthKit sample start/end timestamps;
- `first_observed_at` / `first_received_at`: first arrival through any supported
  client path, including a Shortcut/manual backfill;
- `first_client_kind`: identifies that first arrival path;
- `native_observer_observed_at` / `native_observer_received_at`: first delivery
  through the real HealthKit observer path, tracked separately so a prior
  backfill cannot contaminate observer-latency measurements;
- source revision bundle/product/version when available;
- House state and activity at first receipt;
- deletion timestamp when HealthKit later removes the sample.

The localhost-only `GET /api/sleep/evidence/recent` surface derives:

- observer delay = first **native HealthKit observer** observed time minus
  HealthKit sample end; it remains null for backfill-only samples;
- network delay = native observer HomeHub receive time minus native observer
  observed time;
- client-clock status: a native observed timestamp more than two minutes ahead
  of server receipt is retained as `future_skew` evidence but excluded from
  observer-delay min/avg/max so a bad phone clock cannot poison calibration;
- diagnostic freshness bucket: `under_5m`, `under_30m`, `over_30m`,
  `future_sample`, or `unknown`;
- stage counts and simple observer-delay min/avg/max.

These buckets are calibration labels only. None is an authority threshold.
Graduation criteria will be chosen from actual data, not from these labels.

### AutoSleep and multiple HealthKit producers

Anthony also uses AutoSleep. AutoSleep can read Apple Health sleep data and,
when the user grants/configures it to do so, may write sleep-analysis data back
to HealthKit. It can also display Apple Sleep Stages instead of its own Sleep
Analysis model. HomeHub therefore must not assume that every `sleepAnalysis`
sample was authored by Apple or pre-whitelist a single bundle ID.

Phase 1 preserves the HealthKit source revision and reports active sample counts
by source bundle. During calibration, compare the actual sources seen on the
phone and their agreement with manual Sleeping/wake and interactive activity.
Do not hard-code an AutoSleep bundle identifier from documentation; use the
`HKSourceRevision` attached to the real samples. If Apple and AutoSleep produce
overlapping/conflicting sleep intervals, keep both as evidence and resolve
source authority only after real-night calibration. AutoSleep HomeKit controls
remain user-action conveniences, not physiological sleep/wake authority.

## Privacy / retention

Only sleep stage/timing and the minimum source provenance needed to distinguish
where a sample came from are stored. No heart rate, respiratory rate, wrist
temperature, raw motion, medical records, sleep-quality score, or arbitrary
HealthKit metadata is accepted by this endpoint.
The calibration table has a hard 30-day retention target measured from the
immutable first HomeHub receipt, not the most recent retry. Replaying an old
batch therefore cannot extend health-data retention. The first HealthKit
deletion receipt is likewise retained instead of moving forward on retries. Raw
review is localhost-only and deliberately absent from the public tunnel
allowlist.

## Shortcuts bootstrap versus native observer

Apple Shortcuts includes `Find Health Samples`, and current Shortcuts supports
sleep phases. That makes a Shortcut useful for manual/backfill experiments or a
Waking Up automation that inspects the just-finished night's samples. Apple's
public Shortcuts documentation does not document HealthKit UUID exposure for a
Health Sample variable, so the native HealthKit bridge remains the canonical
source of HealthKit object identity; do not invent UUIDs merely to force a
Shortcut backfill through this API.

It is not the preferred delivery-latency path. Shortcuts Sleep automations fire
for Wind Down, Bedtime, or Waking Up; they do not provide a trigger for each new
HealthKit sleep sample. A daily/wake backfill can validate stage shape and
historical agreement but cannot measure true background observer latency.

References:
- https://support.apple.com/guide/shortcuts/apd3c845e881/ios
- https://support.apple.com/101583
- https://support.apple.com/guide/shortcuts/apd932ff833f/ios

## Graduation gate

Phase 1 remains shadow-only until several representative nights answer:

- How long after stage/sample end does the native bridge actually receive data?
- Are there long gaps or late batches?
- Does HealthKit report sleep while strong Desktop interaction proves awake?
- What does a brief overnight wake look like in the sample sequence?
- How reliably does the data agree with manual Sleeping and explicit wake?

Only after that review may #236 propose automatic fallback Sleeping. Production
enablement is a separate authorization gate, and PC/projector shutdown remains
separately gated even after sleep authority graduates.
