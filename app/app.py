import json
import os
import threading
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", "/data")
os.makedirs(DATA_DIR, exist_ok=True)
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
HOURLY_FILE = os.path.join(DATA_DIR, "hourly.json")
STATE_FILE = os.path.join(DATA_DIR, "state.json")
RETENTION_DAYS = max(7, int(os.environ.get("RETENTION_DAYS", "93")))  # ~3 months
API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
UI_LANG = "de" if os.environ.get("UI_LANG", "en").lower().startswith("de") else "en"
APP_VERSION = "1.1.4"
OR_BASE = "https://openrouter.ai/api/v1"

_lock = threading.Lock()
_save_lock = threading.Lock()
TZ = ZoneInfo("Europe/Berlin")
SAMPLE_SECONDS = max(60, int(os.environ.get("SAMPLE_SECONDS", "300")))
_hourly: dict = {}          # "YYYY-MM-DDTHH" -> {"total": usd, "keys": {name: usd}}
_last: dict | None = None   # {"t","u","keys":{name:usage}}
_state = {"fetching": False, "last_ok": None, "last_error": None, "last_sample": None}


def or_get(path):
    req = urllib.request.Request(OR_BASE + path, headers={"Authorization": "Bearer " + API_KEY})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def _hour_key(dt):
    return dt.astimezone(TZ).strftime("%Y-%m-%dT%H")


def _persist_state():
    with _save_lock:
        save_json(STATE_FILE, _last or {})
        save_json(HOURLY_FILE, _hourly)


def _prune(hist):
    cutoff_day = (datetime.now(TZ).date() - timedelta(days=RETENTION_DAYS)).isoformat()
    for field in ("daily_model", "daily_workspace", "daily_key"):
        d = hist.get(field) or {}
        hist[field] = {k: v for k, v in d.items() if k >= cutoff_day}


def collect():
    """Hourly compaction: sample the cumulative counters (total + per key) and add
    the delta since the last sample to the current hour bucket."""
    global _last
    try:
        credits = or_get("/credits")["data"]
        usage = float(credits.get("total_usage") or 0)
        key_usage = {}
        for w in or_get("/workspaces")["data"]:
            for k in or_get("/keys?workspace_id=" + w["id"])["data"]:
                if k.get("name") and k.get("usage") is not None:
                    key_usage[k["name"]] = float(k["usage"])
        now = datetime.now(timezone.utc)
        bucket = _hourly.setdefault(_hour_key(now), {"total": 0.0, "keys": {}})
        if _last:
            dtot = usage - float(_last.get("u") or 0)
            if 0 < dtot < 50:                       # Sprünge > $50 = Reset/Fehler, ignorieren
                bucket["total"] = round(bucket.get("total", 0.0) + dtot, 6)
            for name, u in key_usage.items():
                d = u - float((_last.get("keys") or {}).get(name, u))
                if 0 < d < 50:
                    cur = bucket.setdefault("keys", {})
                    acc = bk = cur.get(name, 0.0)
                    cur[name] = round(acc + d, 6)
        _last = {"t": now.isoformat(), "u": usage, "keys": key_usage}
        # retention for the hour buckets (~3 months)
        cutoff = (now.astimezone(TZ) - timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%dT%H")
        for k in [k for k in _hourly if k < cutoff]:
            _hourly.pop(k, None)
        _state["last_sample"] = now.isoformat()
        _persist_state()
    except Exception as e:
        _state["last_error"] = "sample: " + str(e)


def hourly_today():
    """Rolling last 24 hours (Europe/Berlin): total and per key.
    hour = label hour ("5", "17", ...), day = ISO date for context."""
    now = datetime.now(TZ)
    start_hour = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=23)
    out = []
    for i in range(24):
        start = start_hour + timedelta(hours=i)
        b = _hourly.get(start.strftime("%Y-%m-%dT%H"), {})
        out.append({"hour": str(start.hour), "day": start.strftime("%Y-%m-%d"),
                    "cost": round(b.get("total", 0.0), 4),
                    "keys": {n: round(v, 4) for n, v in (b.get("keys") or {}).items()}})
    return out


def refresh():
    with _lock:
        if _state["fetching"]:
            return {"status": "already_running"}
        _state["fetching"] = True
    try:
        hist = load_json(HISTORY_FILE, {"daily_model": {}, "daily_workspace": {}, "daily_key": {}})
        hist.setdefault("daily_model", {})
        hist.setdefault("daily_workspace", {})
        hist.setdefault("daily_key", {})
        credits = or_get("/credits")["data"]
        workspaces = or_get("/workspaces")["data"]

        keys = []
        for w in workspaces:
            try:
                wkeys = or_get("/keys?workspace_id=" + w["id"])["data"]
            except Exception:
                wkeys = []
            for k in wkeys:
                keys.append({**k, "workspace": w["name"]})

        # group_by=workspace returns every row account-wide (all workspaces) with
        # workspace_id, model and cost -> one source for model AND workspace series.
        act = or_get("/activity?group_by=workspace")["data"]
        ws_name = {w["id"]: w["name"] for w in workspaces}

        def agg(field):
            out = defaultdict(lambda: defaultdict(lambda: {"cost": 0.0, "tokens": 0, "requests": 0}))
            for it in act:
                day = (it.get("date") or "")[:10]
                if not day:
                    continue
                ident = it.get(field) or "unbekannt"
                slot = out[day][ident]
                slot["cost"] += it.get("usage") or 0.0
                slot["tokens"] += (it.get("prompt_tokens") or 0) + (it.get("completion_tokens") or 0)
                slot["requests"] += it.get("requests") or 0
            return {d: {k: v for k, v in m.items()} for d, m in out.items()}

        for day, models in agg("model").items():
            hist["daily_model"][day] = models
        for day, rows in agg("workspace_id").items():
            hist["daily_workspace"][day] = {ws_name.get(k, k): v for k, v in rows.items() if k != "unbekannt"} or rows

        # Per-key daily series: only `api_key_hash` actually filters (api_key/api_key_id
        # are silently ignored); sum of all keys == account total, checked on live data.
        name_count = defaultdict(int)
        for k in keys:
            name_count[k.get("name")] += 1
        daily_key = defaultdict(dict)
        for k in keys:
            label = k.get("name") or "unbekannt"
            if name_count[label] > 1 and k.get("workspace"):
                label = f"{label} · {k['workspace']}"
            try:
                rows = or_get("/activity?api_key_hash=" + k["hash"])["data"]
            except Exception:
                continue
            per_day = defaultdict(lambda: {"cost": 0.0, "tokens": 0, "requests": 0})
            for it in rows:
                day = (it.get("date") or "")[:10]
                if not day:
                    continue
                slot = per_day[day]
                slot["cost"] += it.get("usage") or 0.0
                slot["tokens"] += (it.get("prompt_tokens") or 0) + (it.get("completion_tokens") or 0)
                slot["requests"] += it.get("requests") or 0
            for day, v in per_day.items():
                daily_key[day][label] = v
        for day, rows in daily_key.items():
            hist["daily_key"][day] = rows

        hist["credits"] = {**credits, "fetched_at": datetime.now(timezone.utc).isoformat()}
        collect()
        hist["workspaces"] = [{"id": w["id"], "name": w["name"]} for w in workspaces]
        hist["keys"] = [
            {"name": k.get("name"), "workspace": k.get("workspace"), "usage": k.get("usage"),
             "usage_monthly": k.get("usage_monthly"), "limit": k.get("limit"),
             "limit_remaining": k.get("limit_remaining"), "limit_reset": k.get("limit_reset"),
             "disabled": k.get("disabled"),
             "created_at": k.get("created_at"), "last_used_at": k.get("last_used_at")}
            for k in keys]
        hist["updated_at"] = datetime.now(timezone.utc).isoformat()
        _prune(hist)
        save_json(HISTORY_FILE, hist)
        _state["last_ok"] = datetime.now(timezone.utc).isoformat()
        _state["last_error"] = None
        return {"status": "ok"}
    except Exception as e:
        _state["last_error"] = str(e)
        return {"status": "error", "error": str(e)}
    finally:
        with _lock:
            _state["fetching"] = False


def build_payload():
    hist = load_json(HISTORY_FILE, None)
    if not hist:
        return {"empty": True}
    today = datetime.now(TZ).date()
    today_s = today.isoformat()
    # Build daily fallbacks from the compact hourly counter history. OpenRouter's
    # activity endpoint may not publish today's row until later; use sampled totals
    # for missing days and make today's sampled total authoritative while it grows.
    hourly_days = defaultdict(lambda: {"cost": 0.0, "keys": defaultdict(float)})
    for hour, bucket in _hourly.items():
        day = hour[:10]
        daily = hourly_days[day]
        daily["cost"] += float(bucket.get("total") or 0.0)
        for name, value in (bucket.get("keys") or {}).items():
            daily["keys"][name] += float(value or 0.0)
    daily_model = {day: dict(rows) for day, rows in hist.get("daily_model", {}).items()}
    daily_key = {day: dict(rows) for day, rows in hist.get("daily_key", {}).items()}
    # Today's total is known from the local counters, but the activity API cannot
    # attribute it to models until it publishes the completed daily rows.
    today_meta = {"date": today_s, "provisional": False}
    for day, sample in hourly_days.items():
        amount = round(sample["cost"], 6)
        if amount <= 0:
            continue
        # Today is updated from the five-minute sampler; older dates only fill
        # gaps until the official daily activity row arrives.
        if day == today_s:
            daily_model[day] = {"__today_hourly__": {
                "cost": amount, "tokens": 0, "requests": 0}}
            today_meta["provisional"] = True
        elif day not in daily_model:
            daily_model[day] = {"__today_hourly__": {
                "cost": amount, "tokens": 0, "requests": 0}}
        if day == today_s or day not in daily_key:
            key_rows = {name: {"cost": round(value, 6), "tokens": 0, "requests": 0}
                        for name, value in sample["keys"].items() if value > 0}
            daily_key[day] = key_rows or {"__today_hourly__": {
                "cost": amount, "tokens": 0, "requests": 0}}
    months = []
    d = today.replace(day=1)
    for _ in range(3):
        months.append(d.strftime("%Y-%m"))
        d = (d - timedelta(days=1)).replace(day=1)
    months.reverse()
    earliest = min(daily_model.keys()) if daily_model else None
    monthly = []
    for m in months:
        cost = sum(v["cost"] for day, models in daily_model.items()
                   if day.startswith(m) for v in models.values())
        partial = bool(earliest and earliest.startswith(m) and earliest > m + "-01")
        monthly.append({"month": m, "cost": round(cost, 4), "partial": partial})

    model_totals = defaultdict(float)
    ws_totals = defaultdict(float)
    key_totals = defaultdict(float)
    for models in hist["daily_model"].values():
        for name, v in models.items():
            model_totals[name] += v["cost"]
    for rows in hist.get("daily_workspace", {}).values():
        for name, v in rows.items():
            ws_totals[name] += v["cost"]
    for rows in hist.get("daily_key", {}).values():
        for name, v in rows.items():
            key_totals[name] += v["cost"]
    return {
        "empty": False,
        "updated_at": hist.get("updated_at"),
        "credits": hist.get("credits"),
        "keys": hist.get("keys", []),
        "workspaces": hist.get("workspaces", []),
        "monthly": monthly,
        "daily_model": daily_model,
        "daily_workspace": hist.get("daily_workspace", {}),
        "daily_key": daily_key,
        "today": today_meta,
        "hourly": hourly_today(),
        "hourly_note": "Last 24 hours (rolling), hourly values condensed from 5-minute counter samples. Model breakdown is only available per day.",
        "totals": {"model": dict(sorted(model_totals.items(), key=lambda x: -x[1])),
                   "workspace": dict(sorted(ws_totals.items(), key=lambda x: -x[1])),
                   "key": dict(sorted(key_totals.items(), key=lambda x: -x[1]))},
        "state": {"fetching": _state["fetching"], "last_ok": _state["last_ok"],
                  "last_error": _state["last_error"]},
    }


scheduler_stop = threading.Event()
scheduler = None


def get_interval():
    cfg = load_json(CONFIG_FILE, {})
    try:
        return max(1, int(cfg.get("refresh_minutes") or os.environ.get("REFRESH_MINUTES", "60")))
    except Exception:
        return 60


def scheduler_loop():
    while not scheduler_stop.is_set():
        refresh()
        for _ in range(get_interval() * 60):
            if scheduler_stop.wait(1):
                return


class Handler(BaseHTTPRequestHandler):
    server_version = "openrouter-status"

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def _path(self):
        return self.path.split("?", 1)[0]

    def do_GET(self):
        p = self._path()
        if p in ("/", "/index.html"):
            try:
                lang = UI_LANG
                if "lang=" in self.path:
                    q = self.path.split("?", 1)[1]
                    for part in q.split("&"):
                        if part.startswith("lang="):
                            v = part[5:].lower()
                            if v in ("en", "de"):
                                lang = v
                with open(os.path.join(BASE, "static", "index.html"), "rb") as f:
                    html = f.read().replace(b"<!--UI_LANG-->",
                                            f'<script>window.__UI_LANG__="{lang}"</script>'.encode())
                    self._send(200, html, "text/html; charset=utf-8")
            except OSError:
                self._send(500, {"error": "index.html missing"})
        elif p == "/api/data":
            self._send(200, build_payload())
        elif p == "/api/status":
            self._send(200, _state)
        elif p == "/api/health":
            self._send(200, {"status": "ok"})
        elif p == "/api/config":
            self._send(200, {"refresh_minutes": get_interval(), "version": APP_VERSION})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        p = self._path()
        if p == "/api/refresh":
            self._send(200, refresh())
            return
        if p == "/api/config":
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode() or "{}")
            except Exception:
                body = {}
            try:
                minutes = max(1, int(body.get("refresh_minutes", 60)))
            except Exception:
                self._send(400, {"error": "refresh_minutes must be an integer"})
                return
            cfg = load_json(CONFIG_FILE, {})
            cfg["refresh_minutes"] = minutes
            save_json(CONFIG_FILE, cfg)
            self._send(200, {"ok": True, "refresh_minutes": minutes})
            return
        self._send(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        pass


def sampler_loop():
    while not scheduler_stop.is_set():
        collect()
        for _ in range(SAMPLE_SECONDS):
            if scheduler_stop.wait(1):
                return


_hourly.update(load_json(HOURLY_FILE, {}) or {})
_last = load_json(STATE_FILE, None) or None

scheduler = threading.Thread(target=scheduler_loop, daemon=True)
scheduler.start()
sampler = threading.Thread(target=sampler_loop, daemon=True)
sampler.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    server.daemon_threads = True
    server.serve_forever()
