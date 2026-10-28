# OpenRouter Status

A small, dependency-free dashboard for **one** OpenRouter account: available credits, spend
for the last three months, stacked cost charts per model and per API key, and the remaining
budget of every key — all on a single, responsive page.

It runs as **one container** on the official `python:3.12-slim` image. No custom image, no
build step, no pip packages: the app only uses the Python standard library (`http.server`,
`urllib`), so staying up to date is nothing more than pulling a newer `python:3.12-slim`
(a Renovate config is included).

![Dashboard screenshot with synthetic example data](docs/screenshot.png)

## Why this exists

I built this for my own use, simply because I prefer this condensed overview over clicking
through several pages.

**Everything shown here can also be found in the OpenRouter dashboard**, no third-party data
is involved:

| This page | Where it comes from in OpenRouter |
|---|---|
| Credits, total spend, credits added | *Settings → Credits* |
| Cost and token usage per model | *Activity* (grouped by model) |
| Cost per workspace | *Activity* (grouped by workspace) |
| Cost per API key | *Activity*, filtered per key |
| Key limits and remaining budget | *Settings → API Keys* |

The only thing this project adds is presentation: the numbers sit side by side on one page,
per-key remaining budget is turned into a percentage bar, and the local sampler fills in the
current day before OpenRouter publishes it. Treat it as a convenience view, **not** as an
additional source of truth.

## What it shows

- **KPI row** – available credits, total spend, credits added, and the cost of the last three
  calendar months as three tiles side by side.
- **Spend per model** – stacked bars for the last 30 days / 7 days / 24 hours. A bar never
  uses more than six colours: the top five models by cost in the selected period plus a grey
  "Other" bucket. The legend lists up to ten models and marks the ones folded into "Other".
- **Spend per API key (all workspaces)** – the same periods and the same aggregation, but
  grouped by key instead of model; in the 24-hour view each bar becomes an hourly stack.
- **Remaining budget per API key** – limit and reset interval, amount used, amount remaining,
  a percentage bar and a status pill. Rows at 80 % or more turn red, 60–80 % amber. The
  percentage is calculated from `limit - limit_remaining` (the current reset period), not
  from the monthly usage.
- **Controls** – Reload (immediate upstream fetch), Live (fetch plus refresh every 10 s),
  a configurable refresh interval, and S/M/L chart zoom. On narrow screens the charts scroll
  horizontally instead of squeezing the bars.
- **Two UI languages** – English and German (`UI_LANG`, or `?lang=en|de` per request).

All charts are hand-written SVG: no CDN, no JavaScript framework, so the page also works on
an isolated network or embedded in a Home Assistant dashboard.

## How it works

```text
OpenRouter Management API ──► app.py ──► /api/data ──► static/index.html (SVG)
        (every N minutes / on demand)      │
                                           └──► data/*.json (local history)
```

The container is both the web server and the background worker:

- A **refresh** fetch pulls credits, all workspaces, all keys and the activity series and
  merges them into `data/history.json`. It runs every `REFRESH_MINUTES` (default 60) and on
  `POST /api/refresh`.
- A **sampler** reads the cumulative counters every `SAMPLE_SECONDS` (default 300), diffs
  them against the last reading and adds the delta to the current hour bucket in
  `data/hourly.json`. This is what makes the current day and the rolling 24-hour view
  available before OpenRouter's daily activity row appears.
- The browser only talks to this app; the management key never leaves the server.

### Data files

| File | Content | Retention |
|---|---|---|
| `data/hourly.json` | per hour: `total` (USD) and `keys` (USD per key) | `RETENTION_DAYS` (93) |
| `data/history.json` | daily aggregates per model, workspace and key from `/activity` | `RETENTION_DAYS` (93) |
| `data/state.json` | last sampled cumulative counters (delta baseline, survives restarts) | – |
| `data/config.json` | refresh interval changed in the UI | – |

Raw five-minute samples are not stored; hourly is the smallest granularity kept.

### Known limits of the OpenRouter API

These are the reason the app keeps its own history:

- `/activity` returns a **rolling window of roughly 30 days** with **day resolution**.
  `limit`, `cursor`, `start_date`, `offset` and `granularity` are accepted but ignored, so
  there is no way to ask for older data or for hourly rows. Months older than the first fetch
  therefore fill up over time; a month that started before the first fetch is labelled
  "partially captured".
- **There is no model breakdown per hour.** The 24-hour chart is a single sampled total per
  hour and is drawn hatched so it cannot be mistaken for a model split. The same applies to
  the current day: it shows the sampled total until OpenRouter publishes the completed day.
- `GET /keys` is **workspace-scoped**. Without `?workspace_id=<id>` you only see the Default
  Workspace, so the app iterates every workspace and unions the keys.
- `GET /activity?api_key_hash=<hash>` is the **only** working per-key filter; `api_key`,
  `api_key_id`, `key_hash` and `key_id` are silently ignored and return the whole account.
- There is no ledger, billing or invoice endpoint (all of them return 404).

## Example data

The screenshot and the numbers below are **synthetic** and only illustrate the layout:

| Metric | Example value |
|---|---|
| Available credits | `$ 12.40` |
| Total spent | `$ 87.60` |
| Credits added | `$ 100.00` |
| Last three months | `$ 0.00` / `$ 4.85` / `$ 82.75` |

| Key | Workspace | Limit / period | Used | Remaining | Status |
|---|---|---|---|---|---|
| `backend-prod` | `default` | `$ 50.00` weekly | `$ 38.10` | `$ 11.90` | 76 % |
| `laptop-cli` | `default` | `$ 20.00` monthly | `$ 18.40` | `$ 1.60` | 92 % |
| `ci-pipeline` | `team-alpha` | `$ 10.00` weekly | `$ 3.25` | `$ 6.75` | 33 % |
| `playground` | `team-alpha` | no limit | `$ 27.85` | – | – |

Model names in the chart are ordinary public OpenRouter model IDs (for example
`openai/gpt-4o-mini` or `anthropic/claude-3.5-sonnet`); replace them with whatever your own
account actually uses.

## Quick start

```bash
git clone https://github.com/Valtheryx/openrouter-status.git
cd openrouter-status
cp .env.example .env         # paste your OpenRouter management key
mkdir -p data
docker compose up -d
# open http://localhost:8097
```

You need a **management key**, not a normal inference key:
<https://openrouter.ai/settings/management-keys>. Keep it private — it can read the whole
account and manage keys.

The compose file mounts `./app` (code, read-only) and `./data` (history, read-write) and uses
the official `python:3.12-slim` image, so an update is `docker compose pull && docker compose up -d`.

### Behind Portainer / with absolute paths

A Portainer *string stack* resolves relative bind mounts against Portainer's own working
directory, so use absolute paths there:

```yaml
services:
  openrouter-status:
    image: python:3.12-slim
    command: ["python", "/app/app.py"]
    ports:
      - "8097:8000"
    volumes:
      - /srv/openrouter-status/app:/app:ro
      - /srv/openrouter-status/data:/data
    environment:
      - TZ=Europe/Berlin
      - OPENROUTER_API_KEY=${OPENROUTER_API_KEY}
```

Put the key into the stack's environment variables (or a Portainer secret), never into the
compose file in Git.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `OPENROUTER_API_KEY` | – | OpenRouter management key (required) |
| `REFRESH_MINUTES` | `60` | activity refresh interval; can be overridden in the UI |
| `SAMPLE_SECONDS` | `300` | counter sampling interval for the hourly buckets |
| `RETENTION_DAYS` | `93` | retention for hourly and daily data (~3 months) |
| `TZ` | `Europe/Berlin` | timezone for day/hour buckets and labels |
| `PORT` | `8000` | listen port inside the container |
| `UI_LANG` | `en` | default UI language (`en` or `de`) |

## HTTP endpoints

| Endpoint | Purpose |
|---|---|
| `GET /` | the dashboard |
| `GET /api/data` | merged payload used by the page (credits, keys, daily series, hourly series) |
| `GET /api/status` | fetch state, last success, last error |
| `GET /api/health` | liveness probe for the container healthcheck |
| `POST /api/refresh` | trigger an immediate upstream fetch |
| `GET`/`POST /api/config` | read or set the refresh interval |

`POST /api/refresh` answers `{"status": "already_running"}` when a fetch is in flight; that is
not an error, just read `/api/data` again a moment later.

## Privacy

- All data stays in the container's `data/` directory. Nothing is sent anywhere except the
  read-only requests to `openrouter.ai/api/v1`.
- No telemetry, no analytics, no external fonts or scripts.
- The repository contains no credentials, host names or IP addresses. The only secret is the
  management key you provide at runtime.
- Bind the port to a private interface or put the app behind your reverse proxy if the host is
  reachable from the internet.

## Project layout

```text
app/app.py              HTTP server, upstream fetch, sampler, aggregation
app/static/index.html   UI, i18n dictionaries, hand-written SVG charts
tests/                  stdlib unittest suite (no dependencies)
compose.yaml            single-container stack
docs/screenshot.png     screenshot with synthetic example data
```

## Development

```bash
python -m unittest discover -s tests     # stdlib only, uses a throwaway DATA_DIR
python app/app.py                        # serve locally on :8000 (DATA_DIR defaults to /data)
```

The tests patch out the sampler thread, so importing the app does not start background work.
CI runs a syntax check and boots the stack against a dummy key to verify `/api/health`.

## License

MIT — see [LICENSE](LICENSE).
