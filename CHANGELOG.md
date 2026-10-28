# Changelog

## 1.1.4 – 2026-10-28

### Changed

- Shortened the current-day series label in the model legend to "Today (estimated)" /
  "Heute (geschätzt)".
- Live mode now refreshes every 15 seconds instead of 10, leaving slow upstream fetches
  enough time to answer before the next cycle asks again.

## 1.1.3 – 2026-10-28

### Changed

- Removed model attribution estimates from both daily and 24-hour model views. The
  current day and each hour now display only the sampled cumulative spend as one
  blue bar/segment; no historical model mix is applied. The provisional hatching
  remains to identify sampler-based totals, and the legend says that model attribution
  is unavailable from the hourly API.

## 1.1.2 – 2026-10-28

### Added (superseded by 1.1.3)

- The 24-hour model chart now splits every hour by model instead of showing one
  unallocated total. OpenRouter's activity API is day-granular even with
  `granularity=hourly` (verified: identical payload), so the hourly split uses the
  same model mix as the current-day estimate. Segments are faded/dashed, the legend
  names the basis day and the estimated total.

## 1.1.1 – 2026-10-28

### Added

- The current day is now split **per model** instead of showing one unallocated
  total: the backend distributes today's sampled spend using the model mix of the
  most recent completed days (up to 7). Estimated segments are drawn at 55 %
  opacity with a dashed outline, and the legend states which day the mix came from.
  Without any completed day in the history the single "hourly total" segment remains.

## 1.1.0 – 2026-10-28

### Added

- **Provisional current-day bars**: today's spend now appears in the per-model and
  per-key charts as soon as the local 5-minute counter samples record usage — no
  waiting for OpenRouter's daily activity row. The bar grows over the day with each
  sample. Model-level detail still arrives with the official daily data.
- The provisional amount is included in the current-month tile (labelled
  "Today (hourly total; model split pending)" / "Heute (Stundensumme; Modellaufteilung folgt)").
- The dashboard polls `/api/data` every 60 seconds (cached, no upstream fetch), so
  the current-day bar updates while the page is open. Reload/Live still force a
  real backend fetch.
- The daily charts always label the latest date, so the current day stays identifiable
  in the 30-day view.
- Unit tests for the current-day fallback logic (`tests/`).

### Fixed

- The current-month cost is now computed on the Europe/Berlin calendar day instead of
  a hard-coded UTC+2 offset, which broke month grouping after the DST change.
- A partial same-day activity row is replaced by the hourly total (never added on top),
  so today's total is never double-counted.
