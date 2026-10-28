# Changelog

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
