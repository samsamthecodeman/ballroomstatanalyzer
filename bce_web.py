#!/usr/bin/env python3
"""
bce_web.py - Ballroom Stats Analyzer: interactive website for ballroomcompexpress.com dancer analysis.

Runs a small web server on your computer and opens the dashboard in your browser.
The server does the scraping (browsers aren't allowed to read ballroomcompexpress.com
directly from another page), and the page lets you search a dancer, filter by style,
level, category or partner, and explore head-to-head records.

Needs bce_analyze.py in the same folder, plus:  pip install requests beautifulsoup4
On your computer:   python bce_web.py            (opens your browser; Ctrl+C here to stop)
As a public site:   python bce_web.py --public   (behind nginx; see DEPLOY.md)
"""
from __future__ import annotations

import ipaddress
import json
import re
import signal
import socket
import sys
import time
import urllib.request
import threading
import traceback
import uuid
import webbrowser
import bce_export
# Optional "Most Dance Partners" feature: uncomment the hooks below to re-enable.
# import bce_partners
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
try:
    import bce_analyze as core
except ImportError as exc:
    sys.exit(f"Couldn't load bce_analyze.py ({exc}).\n"
             "Put bce_analyze.py in the same folder as bce_web.py, and run:  pip install requests beautifulsoup4")

FETCHER: core.Fetcher | None = None  # created in main()
CACHE_MAINTAINER = None
SEARCH_ACTIVE = threading.Event()
LOOKUP_ACTIVE = threading.Event()
LOOKUP_SLOT = threading.Semaphore(1)
LOOKUP_RECENT = {}
# PARTNER_LEADERBOARD = bce_partners.PartnerLeaderboard()
JOBS: dict[str, dict] = {}
INSTANCE = uuid.uuid4().hex  # lets us confirm the browser will reach this program, not another one
JOBS_LOCK = threading.Lock()

# Settings for running as a public website (--public). On your own computer none of these limits apply.
CONFIG = {
    "public": False,
    "require_id": False,     # public mode: searches need a dancer ID (a name-only search reads every event)
    "max_per_hour": 20,      # public mode: searches one visitor can start per hour
    "max_queue": 20,         # public mode: searches allowed to wait in line
    "max_total_per_hour": 200,  # public mode: searches the whole site will start per hour, from everyone
    "visitor_id": "ip",      # "ip", or "ip+browser" when visitors' addresses can't be seen (Docker Desktop)
    "trusted_proxies": [],   # addresses allowed to tell us the visitor's real address (nginx's X-Real-IP)
}
PROXY_PRESETS = {
    "local": ["127.0.0.0/8", "::1/128"],
    # nginx reaching a Docker container arrives from Docker's private network
    "private": ["127.0.0.0/8", "::1/128", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"],
}


def parse_proxies(spec: str) -> list:
    nets = []
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        for item in PROXY_PRESETS.get(part, [part]):
            nets.append(ipaddress.ip_network(item, strict=False))
    return nets
SCAN_SLOT = threading.Semaphore(1)   # public mode: one search reads Ballroom Comp Express at a time
QUEUE: list[str] = []                # job ids waiting for the slot, in order
RECENT: dict[str, list[float]] = {}  # visitor -> times they started searches
ALL_STARTS: list[float] = []         # every search started, for the site-wide hourly cap
VISITOR_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
JOB_TTL = 30 * 60                    # forget finished searches after 30 minutes


def log(msg: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def cleanup_jobs() -> None:
    now = time.time()
    with JOBS_LOCK:
        for jid in [j for j, job in JOBS.items() if job.get("finished") and now - job["finished"] > JOB_TTL]:
            del JOBS[jid]
        for ip in list(RECENT):
            RECENT[ip] = [t for t in RECENT[ip] if now - t < 3600]
            if not RECENT[ip]:
                del RECENT[ip]
        ALL_STARTS[:] = [t for t in ALL_STARTS if now - t < 3600]


def run_job(job_id: str, job: dict, params: dict) -> None:
    def prog(stage, done, total, message):
        if job["cancel"]:
            raise core.Cancelled()
        job.update(stage=stage, done=done, total=total, message=message)

    have_slot = False
    try:
        if CONFIG["public"]:  # wait our turn so the site never runs two scans at once
            got = SCAN_SLOT.acquire(blocking=False)
            while not got:
                if job["cancel"]:
                    raise core.Cancelled()
                with JOBS_LOCK:
                    ahead = max(1, QUEUE.index(job_id)) if job_id in QUEUE else 1
                job.update(stage="queue", message=f"Waiting in line: {ahead} search{'es' if ahead != 1 else ''} ahead of yours...")
                got = SCAN_SLOT.acquire(timeout=1)
            have_slot = True
            SEARCH_ACTIVE.set()
            with JOBS_LOCK:
                if job_id in QUEUE:
                    QUEUE.remove(job_id)
        job.update(stage="start", message="Looking up saved results...")
        import bce_sources
        data = bce_sources.collect(params, FETCHER, progress=prog)
    except core.Cancelled:
        job["state"] = "cancelled"
        return
    except ValueError as exc:
        job.update(state="error", error=str(exc))
        return
    except Exception as exc:  # surface anything unexpected to the page
        traceback.print_exc()
        job.update(state="error", error=f"{type(exc).__name__}: {exc}")
        return
    finally:
        job["finished"] = time.time()
        with JOBS_LOCK:
            if job_id in QUEUE:
                QUEUE.remove(job_id)
        if have_slot:
            SEARCH_ACTIVE.clear()
            SCAN_SLOT.release()

    events = []
    for rec, results in data["raw_events"]:
        # PARTNER_LEADERBOARD.add_entries(results)
        ev = asdict(rec)
        ev["field"] = [{"entry": entry, "people": core.split_people(entry),
                        "place": r["place"], "made_final": r["made_final"]}
                       for entry, r in results.items()]
        ev["final_percentile"] = bce_export.finals_percentile(ev)
        events.append(ev)
    job["result"] = {
        "status": data["status"],
        "name": data.get("name") or params.get("name") or "",
        "aid": data.get("aid", params.get("aid")),
        "source": params.get("source", "bce"),
        "warnings": data.get("warnings", []),
        "alternatives": data.get("alternatives", []),
        "matched_as": sorted(data["spellings"]),
        "suggestions": data["suggestions"],
        "comps_scanned": data["comps_scanned"],
        "events_scanned": data.get("events_scanned", 0),
        "events": events,
    }
    job["state"] = "done"
    if CONFIG["public"]:
        log(f"search finished: {data['status']}, {len(events)} events")


class Handler(BaseHTTPRequestHandler):
    server_version = "CompHistory"
    sys_version = ""

    def log_message(self, *args):  # keep the terminal quiet
        pass

    def visitor(self) -> str:
        ip = self.client_address[0]
        try:
            addr = ipaddress.ip_address(ip)
            if any(addr in net for net in CONFIG["trusted_proxies"]):
                real = (self.headers.get("X-Real-IP") or "").strip()
                try:
                    ip = str(ipaddress.ip_address(real))
                except ValueError:
                    pass
        except ValueError:
            pass
        if CONFIG["visitor_id"] == "ip+browser":
            # Docker Desktop can hide visitors' addresses, making everyone look alike; the page sends a
            # random ID kept in that browser so visitors still get their own limits.
            token = (self.headers.get("X-Visitor") or "").strip().lower()
            if VISITOR_TOKEN_RE.match(token):
                return f"{ip}|{token}"
        return ip

    def _send(self, code: int, body, ctype="application/json", filename=None):
        data = body if isinstance(body, bytes) else (
            body.encode("utf-8") if isinstance(body, str) else json.dumps(body).encode("utf-8"))
        self.send_response(code)
        self.send_header("Content-Type", ctype if ctype == "application/pdf" else f"{ctype}; charset=utf-8")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/ping":
            return self._send(200, {"app": "comp-history", "instance": INSTANCE})
        if url.path == "/api/config":
            return self._send(200, {"requireId": CONFIG["require_id"], "public": CONFIG["public"]})
        if url.path == "/api/cache/status":
            return self._send(200, {"enabled": CACHE_MAINTAINER is not None,
                                    **(FETCHER.store.status() if FETCHER else {})})
        if url.path == "/api/dancers":
            query = (parse_qs(url.query).get("q", [""])[0]).strip()
            if not 3 <= len(query) <= 80:
                return self._send(400, {"error": "Enter between 3 and 80 characters."})
            who = self.visitor()
            now = time.time()
            with JOBS_LOCK:
                for key in list(LOOKUP_RECENT):
                    LOOKUP_RECENT[key] = [t for t in LOOKUP_RECENT[key] if now - t < 60]
                    if not LOOKUP_RECENT[key]:
                        del LOOKUP_RECENT[key]
                recent = LOOKUP_RECENT.get(who, [])
                if len(recent) >= 20:
                    return self._send(429, {"error": "Please pause before looking up more names, or enter a dancer ID."})
                LOOKUP_RECENT.setdefault(who, []).append(now)
            if not LOOKUP_SLOT.acquire(blocking=False):
                return self._send(503, {"error": "Name lookup is busy. Try again shortly or enter a dancer ID."})
            LOOKUP_ACTIVE.set()
            try:
                return self._send(200, {"dancers": core.search_dancers(query, FETCHER)})
            except ValueError as exc:
                return self._send(503, {"error": str(exc)})
            except Exception:
                traceback.print_exc()
                return self._send(503, {"error": "Name lookup is unavailable. You can still enter a dancer ID."})
            finally:
                LOOKUP_ACTIVE.clear()
                LOOKUP_SLOT.release()
        # if url.path == "/api/partner-leader":
        #     return self._send(200, PARTNER_LEADERBOARD.snapshot())
        if url.path in ("/", "/index.html"):
            return self._send(200, PAGE, "text/html")
        if url.path == "/api/status":
            job = JOBS.get(parse_qs(url.query).get("id", [""])[0])
            if not job:
                return self._send(404, {"error": "That search has expired. Run it again."})
            out = {k: job.get(k) for k in ("state", "stage", "done", "total", "message", "error")}
            if job["state"] == "done":
                out["result"] = job["result"]
            return self._send(200, out)
        self._send(404, {"error": "Not found"})

    def do_POST(self):
        url = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        if length > 10_000:
            return self._send(413, {"error": "Request too large"})
        try:
            params = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(params, dict):
                raise ValueError
        except ValueError:
            return self._send(400, {"error": "Bad request"})
        if url.path == "/api/export":
            cleanup_jobs()
            job = JOBS.get(str(params.get("id", "")))
            if not job or job.get("visitor") != self.visitor():
                return self._send(404, {"error": "These results have expired. Run the search again to export."})
            if job.get("state") != "done":
                return self._send(409, {"error": "Wait for the search to finish before exporting."})
            fmt = params.get("format")
            if fmt not in ("csv", "pdf"):
                return self._send(400, {"error": "Choose CSV or PDF."})
            filters = params.get("filters", {})
            try:
                result = job["result"]
                events = bce_export.select_events(result, filters)
                body = bce_export.csv_report(events) if fmt == "csv" else bce_export.pdf_report(result, events, filters)
            except ValueError as exc:
                return self._send(400, {"error": str(exc)})
            except Exception:
                traceback.print_exc()
                return self._send(500, {"error": "The export could not be created. Please try again."})
            return self._send(200, body, "text/csv" if fmt == "csv" else "application/pdf",
                              filename=bce_export.filename(result.get("name"), fmt))
        if url.path == "/api/start":
            cleanup_jobs()
            name = str(params.get("name") or "").strip()[:100]
            aid = str(params.get("aid") or "").strip()[:12]
            source = params.get("source", "bce")
            if source not in ("bce", "o2cm", "all"):
                return self._send(400, {"error": "Choose Ballroom Comp Express, O2CM, or Unified data."})
            params["partner"] = str(params.get("partner") or "").strip()[:100]
            params["cids"] = str(params.get("cids") or "").strip()[:200]
            if source == "o2cm":
                first = str(params.get("first") or "").strip()[:80]
                last = str(params.get("last") or "").strip()[:80]
                if first and last:
                    name = f"{first} {last}"
                codes = [part.strip().lower() for part in params["cids"].split(",") if part.strip()]
                if any(not re.fullmatch(r"[a-z0-9_-]{2,30}", code) for code in codes):
                    return self._send(400, {"error": "O2CM competition codes are comma-separated, for example mit26, big23."})
                params.update(first=first, last=last, o2_comps=codes or None)
            if source == "all" and params["cids"]:
                return self._send(400, {"error": "Select one source to filter by competition IDs or codes."})
            if name.isdigit() and not aid:
                name, aid = "", name
            if aid and not aid.isdigit():
                return self._send(400, {"error": "A dancer ID is a number, like 10062."})
            if source == "bce" and CONFIG["require_id"] and not aid:
                return self._send(400, {"error": "This site searches by dancer ID. Add the dancer’s ID; the box explains how to find it."})
            if not core.norm(name) and not aid:
                return self._send(400, {"error": "Type a dancer’s name or dancer ID first."})
            params["name"], params["aid"] = name, int(aid) if aid else None
            who = self.visitor()
            if CONFIG["public"]:
                now = time.time()
                with JOBS_LOCK:
                    mine = [j for j in JOBS.values() if j.get("visitor") == who and j["state"] == "running"]
                    starts = RECENT.get(who, [])
                    if mine:
                        return self._send(429, {"error": "You already have a search running. Wait for it to finish or stop it first."})
                    if len(starts) >= CONFIG["max_per_hour"]:
                        return self._send(429, {"error": "You’ve run a lot of searches in the last hour. Try again a little later."})
                    if len(QUEUE) >= CONFIG["max_queue"]:
                        return self._send(503, {"error": "The site is busy right now. Try again in a few minutes."})
                    if len(ALL_STARTS) >= CONFIG["max_total_per_hour"]:
                        return self._send(503, {"error": "The site has had a lot of searches this hour. Try again later."})
                    RECENT.setdefault(who, []).append(now)
                    ALL_STARTS.append(now)
            job_id = uuid.uuid4().hex
            job = {"state": "running", "stage": "start", "done": 0, "total": 0, "visitor": who,
                   "message": "Starting...", "error": None, "result": None, "cancel": False}
            with JOBS_LOCK:
                JOBS[job_id] = job
                if CONFIG["public"]:
                    QUEUE.append(job_id)
            if CONFIG["public"]:
                log(f"search started ({'dancer ID' if aid else 'name'})")
            threading.Thread(target=run_job, args=(job_id, job, params), daemon=True).start()
            return self._send(200, {"id": job_id})
        if url.path == "/api/cancel":
            job = JOBS.get(str(params.get("id", "")))
            if job and job.get("visitor") == self.visitor():
                job["cancel"] = True
            return self._send(200, {"ok": True})
        self._send(404, {"error": "Not found"})


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ballroom Stats Analyzer</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,400;14..32,500;14..32,600;14..32,700&display=swap" rel="stylesheet">
<script>
(() => {
  let theme;
  try { theme = localStorage.getItem("bsa-theme"); } catch {}
  document.documentElement.dataset.theme = theme === "light" || theme === "dark" ? theme
    : window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
})();
</script>
<style>
/* Ballroom Stats Analyzer: Swiss / International Typographic Style.
   12-column grid, flush-left type, hierarchy by size and weight, red accents and green first places. */
:root {
  color-scheme: light;
  --bg: #FFFFFF;
  --ink: #000000;
  --grey: #6B6B6B;
  --hair: #D6D6D6;
  --tint: #F2F2F2;
  --red: #E4002B;
  --on-red: #FFFFFF;
  --first-place: #15803D;
  --on-first-place: #FFFFFF;
  --font: "Inter", "Helvetica Neue", Helvetica, Arial, sans-serif;
  --gutter: 24px;
  --margin: 40px;
}
:root[data-theme="dark"] {
    color-scheme: dark;
    --bg: #000000;
    --ink: #FFFFFF;
    --grey: #A0A0A0;
    --hair: #3A3A3A;
    --tint: #181818;
    --red: #FF3347;
    --on-red: #000000;
    --first-place: #4ADE80;
    --on-first-place: #000000;
}
@media (max-width: 700px) { :root { --margin: 16px; --gutter: 16px; } }

* { box-sizing: border-box; }
html, body { margin: 0; background: var(--bg); color: var(--ink); }
body { font: 400 16px/1.5 var(--font); font-feature-settings: "tnum" 1, "cv11" 1; -webkit-font-smoothing: antialiased; }
a { color: inherit; text-decoration-thickness: 1px; text-underline-offset: 3px; }
a:hover { color: var(--red); }
button, input, select { font: inherit; color: inherit; }
:focus-visible { outline: 2px solid var(--red); outline-offset: 2px; }
.hidden { display: none !important; }
.theme-toggle { position: fixed; bottom: 20px; right: 20px; z-index: 100; width: 44px; height: 44px; display: grid; place-items: center; border: 1px solid var(--hair); border-radius: 50%; background: var(--bg); color: var(--ink); cursor: pointer; box-shadow: 0 2px 8px #0003; }
.theme-toggle:hover { border-color: var(--ink); }
.theme-toggle svg { width: 22px; height: 22px; }
code { font: inherit; background: var(--tint); padding: 0 4px; }

/* ---------- grid ---------- */
.wrap { max-width: 1360px; margin: 0 auto; padding: 0 var(--margin); }
.grid { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); column-gap: var(--gutter); }
.c-all { grid-column: 1 / -1; }
.c-head { grid-column: 1 / span 3; }
.c-body { grid-column: 4 / span 9; }
@media (max-width: 900px) { .c-head, .c-body { grid-column: 1 / -1; } }

/* ---------- header ---------- */
header.bar { border-bottom: 1px solid var(--ink); }
header.bar .wrap { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); column-gap: var(--gutter); align-items: center; padding-top: 18px; padding-bottom: 18px; }
.brand { grid-column: 1 / span 3; font-weight: 700; font-size: 17px; letter-spacing: -0.01em; line-height: 1.2; text-decoration: none; justify-self: start; }
form.search { grid-column: 4 / span 9; display: flex; gap: 12px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }
.search-hint { grid-column: 4 / -1; margin: 8px 0 0; color: var(--grey); font-size: 13px; line-height: 1.5; text-align: right; }
@media (max-width: 900px) { .brand, form.search, .search-hint { grid-column: 1 / -1; } form.search { justify-content: flex-start; margin-top: 12px; } .search-hint { text-align: left; } }
form.search input[type=text] { width: 240px; max-width: 100%; height: 40px; padding: 0 12px; border: 1px solid var(--ink); border-radius: 0; background: var(--bg); }
form.search input[type=text].aid { width: 130px; }
.source-toggle { display: flex; gap: 3px; flex-wrap: wrap; }
.source-toggle button { background: var(--bg); color: var(--ink); border: 1px solid var(--hair); padding: 9px 12px; font: inherit; font-size: 13px; cursor: pointer; }
.source-toggle button[aria-pressed=true] { background: var(--ink); color: var(--bg); border-color: var(--ink); }
form.search input::placeholder, .tools input::placeholder { color: var(--grey); }

.btn { height: 40px; padding: 0 20px; border: 1px solid var(--ink); border-radius: 0; background: var(--ink); color: var(--bg); font-weight: 600; cursor: pointer; }
.btn:hover { background: var(--red); border-color: var(--red); color: var(--on-red); }
.btn.quiet { background: transparent; color: var(--ink); }
.btn.quiet:hover { background: var(--ink); border-color: var(--ink); color: var(--bg); }
.btn:disabled { opacity: .4; cursor: default; }
.linkbtn { background: none; border: 0; padding: 0; color: var(--ink); cursor: pointer; text-decoration: underline; text-decoration-thickness: 1px; text-underline-offset: 3px; font-size: 14px; }
.linkbtn:hover { color: var(--red); }

details.opts { position: relative; }
details.opts summary { cursor: pointer; list-style: none; height: 40px; display: flex; align-items: center; font-size: 14px; text-decoration: underline; text-decoration-thickness: 1px; text-underline-offset: 3px; }
details.opts summary::-webkit-details-marker { display: none; }
details.opts .panel { position: absolute; right: 0; top: calc(100% + 8px); z-index: 5; width: 320px; background: var(--bg); border: 1px solid var(--ink); padding: 20px; display: grid; gap: 16px; }
@media (max-width: 900px) { details.opts .panel { right: auto; left: 0; } }
.panel label { display: grid; gap: 6px; font-size: 13px; color: var(--grey); }
.panel label.check { display: grid; grid-template-columns: auto 1fr; gap: 10px; align-items: start; color: var(--ink); font-size: 14px; }
.panel input[type=text] { height: 36px; padding: 0 10px; border: 1px solid var(--ink); border-radius: 0; background: var(--bg); color: var(--ink); }
.hint { font-size: 13px; color: var(--grey); }
.search-hint { margin: 8px 0 0; font-size: 13px; color: var(--grey); }
input[type=checkbox] { accent-color: var(--ink); width: 16px; height: 16px; margin: 2px 0 0; }

/* ---------- start screen ---------- */
main.wrap { padding-top: 56px; padding-bottom: 96px; }
.empty h1 { grid-column: 1 / span 10; font-size: clamp(48px, 8.5vw, 128px); line-height: .95; letter-spacing: -0.045em; font-weight: 700; margin: 0 0 48px; }
.empty .intro { grid-column: 4 / span 6; border-top: 2px solid var(--ink); padding-top: 16px; }
.empty p { margin: 0 0 16px; max-width: 62ch; }
.empty .intro p:first-child { font-size: 20px; line-height: 1.4; letter-spacing: -0.01em; }
.empty .partner-joke { margin-top: 28px; font-size: 13px; color: var(--grey); }
@media (max-width: 900px) { .empty h1, .empty .intro { grid-column: 1 / -1; } }

/* ---------- progress ---------- */
.status { grid-column: 4 / span 6; border-top: 2px solid var(--ink); padding-top: 16px; }
@media (max-width: 900px) { .status { grid-column: 1 / -1; } }
.status .msg { margin: 0 0 16px; font-size: 20px; line-height: 1.4; letter-spacing: -0.01em; max-width: 50ch; }
.track { height: 4px; background: var(--hair); margin-bottom: 20px; }
.track div { height: 100%; width: 0; background: var(--red); transition: width .3s linear; }
.error { color: var(--red); }

/* ---------- dancer ---------- */
.who { grid-column: 1 / -1; }
.who h1 { font-size: clamp(52px, 9vw, 136px); line-height: .92; letter-spacing: -0.05em; font-weight: 700; margin: 0 0 20px; overflow-wrap: anywhere; }
.who .sub { color: var(--grey); margin: 0 0 32px; font-size: 16px; }
.who .alt { margin-top: -24px; color: var(--ink); }
.who .alt button { margin-left: 12px; }
.exports { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; margin: -16px 0 28px; }
.exports .note { flex-basis: 100%; margin: 0; }

.marks { grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: 2px; margin-bottom: 14px; }
.mark, .sw { display: inline-grid; place-items: center; border: 0; padding: 0; background: var(--tint); color: var(--grey); }
.mark { width: 28px; height: 32px; font: 600 13px/1 var(--font); cursor: pointer; }
.mark.gap { width: 12px; background: none; cursor: default; }
.sw { width: 12px; height: 12px; margin-right: 6px; vertical-align: -1px; }
.mark.final, .sw.final { background: var(--bg); color: var(--ink); box-shadow: inset 0 0 0 1.5px var(--ink); }
.mark.p1, .sw.p1 { background: var(--first-place); color: var(--on-first-place); box-shadow: none; }
.mark.p2, .sw.p2 { background: var(--ink); color: var(--bg); box-shadow: none; }
.mark.p3, .sw.p3 { background: var(--grey); color: var(--bg); box-shadow: none; }
.mark:hover { outline: 2px solid var(--red); outline-offset: 1px; }
.mark.p1:hover, .mark.p1:focus-visible { outline-color: var(--first-place); }
.legend { grid-column: 1 / -1; display: flex; gap: 8px 24px; flex-wrap: wrap; font-size: 13px; color: var(--grey); margin-bottom: 48px; }
.legend .legend-note { margin-left: auto; }
@media (max-width: 900px) { .legend .legend-note { margin-left: 0; } }

.stats { grid-column: 1 / -1; display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); column-gap: var(--gutter); row-gap: 28px; border-top: 2px solid var(--ink); padding-top: 16px; margin-bottom: 64px; }
@media (max-width: 900px) { .stats { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 520px) { .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
.stat b { display: block; font-size: clamp(32px, 4vw, 56px); line-height: 1; letter-spacing: -0.04em; font-weight: 700; margin-bottom: 8px; }
.stat span { display: block; font-size: 13px; color: var(--grey); line-height: 1.35; max-width: 18ch; }

/* ---------- bands and sections: heading on the left 3 columns, content on the right 9 ---------- */
.band, section { grid-column: 1 / -1; display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); column-gap: var(--gutter); border-top: 2px solid var(--ink); padding-top: 16px; margin-bottom: 72px; }
.band { margin-bottom: 72px; }
.sec-head h2, .band-head h2 { font-size: 24px; line-height: 1.15; letter-spacing: -0.025em; font-weight: 700; margin: 0 0 12px; }
.sec-head .note, .band-head .note { font-size: 14px; color: var(--grey); margin: 0 0 24px; max-width: 34ch; }
@media (max-width: 900px) { .sec-head .note { max-width: 62ch; } }
.sec-body { min-width: 0; }
section.collapsed { margin-bottom: 24px; }
section.collapsed .sec-body, section.collapsed .sec-head .note { display: none !important; }
section.collapsed .sec-head h2 { margin: 0; }

.sec-toggle { all: unset; cursor: pointer; display: inline-flex; align-items: baseline; gap: 12px; }
.sec-toggle:hover { color: var(--red); }
.sec-toggle:focus-visible { outline: 2px solid var(--red); outline-offset: 4px; }
.sec-toggle::before { content: ""; width: 8px; height: 8px; border-right: 2px solid currentColor; border-bottom: 2px solid currentColor; transform: translateY(-4px) rotate(45deg); flex: none; }
section.collapsed .sec-toggle::before { transform: translateY(-1px) rotate(-45deg); }

.note { font-size: 14px; color: var(--grey); }

/* ---------- filters ---------- */
.filters { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 16px var(--gutter); align-items: end; }
.filters .linkbtn { justify-self: start; height: 36px; }
.filters label { display: grid; gap: 6px; font-size: 13px; color: var(--grey); }
.filters label.check-inline { display: flex; align-items: center; gap: 8px; min-height: 36px; color: var(--ink); }
select { height: 36px; padding: 0 30px 0 10px; border: 1px solid var(--ink); border-radius: 0; background-color: var(--bg); color: var(--ink); appearance: none; -webkit-appearance: none;
  background-image: linear-gradient(45deg, transparent 50%, currentColor 50%), linear-gradient(135deg, currentColor 50%, transparent 50%);
  background-position: calc(100% - 15px) 15px, calc(100% - 10px) 15px; background-size: 5px 5px; background-repeat: no-repeat; }
.filters select { width: 100%; min-width: 0; text-overflow: ellipsis; }
.band-tools { margin-top: 4px; }

/* ---------- tabs and tools ---------- */
.tabs { display: flex; flex-wrap: wrap; gap: 4px 22px; margin-bottom: 16px; }
.tabs button { border: 0; background: none; padding: 6px 0 5px; cursor: pointer; font-size: 14px; color: var(--grey); border-bottom: 2px solid transparent; }
.tabs button:hover { color: var(--ink); }
.tabs button[aria-pressed=true] { color: var(--ink); font-weight: 600; border-bottom-color: var(--ink); }
.tab-row { display: grid; grid-template-columns: 64px 1fr; gap: 12px; align-items: start; }
.tab-row > .hint { padding-top: 7px; }
.tools { display: flex; flex-wrap: wrap; gap: 12px 20px; align-items: center; margin-bottom: 20px; }
.tools label.hint { display: inline-flex; gap: 8px; align-items: center; }
.tools input[type=search] { height: 36px; padding: 0 10px; border: 1px solid var(--ink); border-radius: 0; background: var(--bg); width: 190px; min-width: 150px; }
.tools input[type=checkbox] { margin: 0; }
.check-inline { display: inline-flex; gap: 8px; align-items: center; }

/* ---------- tables ---------- */
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 15px; }
th, td { padding: 10px 16px 10px 0; text-align: left; vertical-align: baseline; border-bottom: 1px solid var(--hair); white-space: nowrap; }
th:last-child, td:last-child { padding-right: 0; }
th { font-size: 13px; font-weight: 500; color: var(--grey); border-bottom: 2px solid var(--ink); padding-top: 0; }
th.sort { cursor: pointer; user-select: none; }
th.sort:hover { color: var(--ink); }
th.sort[aria-sort=ascending], th.sort[aria-sort=descending] { color: var(--ink); }
th.sort[aria-sort=ascending]::after { content: " ↑"; }
th.sort[aria-sort=descending]::after { content: " ↓"; }
td.num, th.num { text-align: right; }
td.wrap-ok { white-space: normal; min-width: 240px; }
tr.click { cursor: pointer; }
tr.click:hover td { background: var(--tint); }
tr.flash td { background: var(--tint); box-shadow: inset 0 -2px 0 var(--red); }
tr.detail td { background: var(--tint); white-space: normal; padding: 12px 16px; font-size: 14px; }
.detail ul { margin: 0; padding-left: 18px; }
.detail li { margin: 2px 0; }
.w { color: var(--ink); font-weight: 600; }
.l { color: var(--red); font-weight: 600; }
.bar-cell { display: flex; align-items: center; gap: 10px; }
.bar-cell i { display: block; height: 4px; background: var(--ink); }
.limit-foot:not(:empty) { margin-top: 12px; font-size: 13px; color: var(--grey); }
.h2h-foot .note { margin-top: 12px !important; }

/* YCN */
tr.grp td { font-size: 13px; font-weight: 600; color: var(--ink); padding-top: 20px; border-bottom: 1px solid var(--ink); }
th.pt, td.pt { text-align: center; min-width: 72px; padding-right: 0; }
td.pt-zero { color: var(--hair); }
td.pt-some { font-weight: 600; }
td.pt-out { background: var(--ink); color: var(--bg); font-weight: 700; }
.sw.sw-out { background: var(--ink); }
.ycn-legend { display: flex; flex-wrap: wrap; gap: 8px 24px; font-size: 13px; color: var(--grey); margin: 12px 0 4px; }
.ycn-lilac { margin: 16px 0 0; max-width: 72ch; }
details.ycn-more { margin-top: 24px; border-top: 1px solid var(--ink); padding-top: 12px; }
details.ycn-more summary { cursor: pointer; font-weight: 600; font-size: 15px; }
details.ycn-more summary:hover { color: var(--red); }
.lvl-row { display: grid; grid-template-columns: minmax(160px, 1.2fr) 120px minmax(150px, 1fr) 2fr; gap: 8px 16px; align-items: center; padding: 10px 0; border-bottom: 1px solid var(--hair); font-size: 14px; }
.lvl-row select { min-width: 140px; }
@media (max-width: 700px) { .lvl-row { grid-template-columns: 1fr 1fr; } }
ul.ycn-log { margin: 10px 0; padding-left: 18px; font-size: 14px; max-width: 90ch; }
ul.ycn-log li { margin: 4px 0; }

/* chart */
svg.chart { width: 100%; height: auto; display: block; }
svg.chart text { fill: var(--grey); font: 12px var(--font); }
svg.chart .grid { stroke: var(--hair); stroke-width: 1; }
svg.chart .line { fill: none; stroke: var(--ink); stroke-width: 2; }
svg.chart .dot { fill: var(--bg); stroke: var(--ink); stroke-width: 2; cursor: pointer; }
svg.chart .dot:hover, svg.chart .dot:focus { fill: var(--red); stroke: var(--red); outline: none; }
.chart-tip { min-height: 1.5em; font-size: 14px; color: var(--grey); margin-top: 12px; }

@media (prefers-reduced-motion: reduce) { .track div { transition: none; } }
</style>

<body>
<header class="bar"><div class="wrap">
  <a class="brand" href="/" aria-label="Ballroom Stats Analyzer home">Ballroom Stats Analyzer</a>
  <form class="search" id="searchForm">
    <div class="source-toggle" role="group" aria-label="Results source">
      <button type="button" id="sourceBce" aria-pressed="false" title="Ballroom Comp Express">BCE</button>
      <button type="button" id="sourceO2cm" aria-pressed="false">O2CM</button>
      <button type="button" id="sourceAll" aria-pressed="true">Unified data</button>
    </div>
    <input type="hidden" id="source" value="all">
    <input type="text" id="name" placeholder="Name or dancer ID" aria-label="Name or dancer ID" aria-describedby="dancerLookupStatus" list="dancerSuggestions" autocomplete="off">
    <datalist id="dancerSuggestions"></datalist>
    <input type="text" id="aid" class="aid" aria-label="Ballroom Comp Express dancer ID" title="Ballroom Comp Express dancer ID" readonly hidden>
    <details class="opts">
      <summary>Options</summary>
      <div class="panel">
        <label class="check"><input type="checkbox" id="fuzzy"> <span>Match similar spellings<br><span class="hint">Finds “Jon” when you type “John”.</span></span></label>
        <label>Only with partner<input type="text" id="partner" placeholder="Optional"></label>
        <label><span id="competitionFilterLabel">Comp ids to scan</span><input type="text" id="cids" placeholder="All, or e.g. 150-250"></label>
      </div>
    </details>
    <button class="btn" id="goBtn" type="submit">Analyze</button>
  </form>
  <p class="search-hint" id="dancerLookupStatus" role="status" aria-live="polite">Type at least 3 characters and choose a dancer, or enter a dancer ID.</p>
</div></header>

<main class="wrap">
  <div id="emptyView" class="empty grid">
    <h1>Every heat, every final, every rival.</h1>
    <div class="intro">
      <p>Explore competition results from Ballroom Comp Express and O2CM, including placements over time and the dancers they’ve shared a floor with.</p>
      <p id="idNote">Start typing a dancer’s name and choose a match to fill their ID automatically. You can also paste a dancer ID from a Ballroom Comp Express results URL (the number after <code>aid=</code>).</p>
      <p id="nameOnlyNote" class="note">A name on its own works too, but the site doesn’t list who danced where, so the first name search reads every event on the site and can take a few hours. Pages are saved on your computer, so searching again is quick.</p>
      <p id="partnerJoke" class="partner-joke hidden" title="Distinct partners counted by name in cached event results, including other entrants. Not a ranking of the entire Ballroom Comp Express website."><span id="partnerLeader"></span></p>
    </div>
  </div>

  <div id="statusView" class="grid hidden">
    <div class="status">
      <p class="msg" id="statusMsg">Starting…</p>
      <div class="track"><div id="statusBar"></div></div>
      <button class="btn quiet" id="cancelBtn" type="button">Stop search</button>
    </div>
  </div>

  <div id="resultView" class="grid hidden">
    <div class="who">
      <h1 id="whoName"></h1>
      <p class="sub" id="whoSub"></p>
      <p class="note hidden" id="sourceNotice"></p>
      <p class="sub alt hidden" id="whoAlt"></p>
      <div class="exports">
        <button class="btn quiet" id="exportCsv" type="button">Export CSV</button>
        <button class="btn quiet" id="exportPdf" type="button">Export PDF</button>
        <p class="note" id="exportStatus" role="status" aria-live="polite">Exports include all events matching the current filters.</p>
      </div>
    </div>
    <div class="marks" id="marks" aria-label="Placement in every event, in order"></div>
    <div class="legend">
      <span><i class="sw p1"></i>1st</span>
      <span><i class="sw p2"></i>2nd</span>
      <span><i class="sw p3"></i>3rd</span>
      <span><i class="sw final"></i>Made the final</span>
      <span><i class="sw"></i>Out before the final</span>
      <span class="legend-note">Each square is one event. Click one to find it below.</span>
    </div>
    <div class="stats" id="stats"></div>
    <div class="c-all" style="margin-bottom:28px">
      <label>Field beaten: <select id="fieldMode" aria-label="Field beaten calculation"><option value="total">Total field beaten</option><option value="finals">Field beaten in finals</option></select></label>
      <p class="note">“Field beaten” measures your placement on a scale from 100% for first to 0% for last: (field size − place) ÷ (field size − 1). Total uses every entry in the event; finals uses only the published finalists. For example, third of 12 scores 82% overall; third in a six-entry final scores 60%. Tied places share a score; a one-entry field scores 100%.</p>
      <p class="note">Finals mode shows — for non-finalists or unavailable final data and leaves them out of field-beaten averages. This toggle updates the summary, trend, breakdowns, and event table; other statistics stay the same. Averages give each event equal weight. CSV exports include both measures (Percentile is the total-field score).</p>
    </div>

    <div class="band">
      <div class="band-head c-head">
        <h2>Filters</h2>
        <p class="note">Narrow results and exports. YCN points follows the event-exclusion checkboxes.</p>
      </div>
      <div class="c-body">
        <div class="filters" id="filters"></div>
        <div class="band-tools tools" style="margin:16px 0 0"><button type="button" class="linkbtn" id="collapseAll">Collapse all sections</button></div>
      </div>
    </div>

    <section data-sec="compare">
      <header class="sec-head c-head"><h2>Compare dancers</h2><p class="note">Compare another dancer using the same results source, dashboard filters, and field-beaten mode. Overall histories may cover different events and dates.</p></header>
      <div class="sec-body c-body">
        <form id="compareForm" class="tools">
          <label>Other dancer <input id="compareName" type="text" placeholder="Name or dancer ID" aria-label="Other dancer name or ID" list="compareSuggestions" autocomplete="off" required></label>
          <datalist id="compareSuggestions"></datalist>
          <button type="submit" class="btn" id="compareGo">Compare</button>
          <button type="button" class="btn quiet hidden" id="compareStop">Stop comparison</button>
          <button type="button" class="linkbtn" id="compareClear">Clear comparison</button>
        </form>
        <p id="compareStatus" class="note" role="status" aria-live="polite">Look up another dancer to compare their results with yours.</p>
        <p id="compareWarnings" class="note"></p>
        <div id="compareStats" class="scroll"></div>
        <p id="compareMeetings" class="note"></p>
        <div id="compareEvents" class="scroll"></div>
        <p class="note">Head-to-head matches use the same provider, competition, and event IDs. Dancing in the same entry counts as “Together,” not a win or loss. Differently listed events across providers are not guessed to be the same event. Exports above contain the primary dancer’s results.</p>
      </div>
    </section>

    <section data-sec="chart">
      <header class="sec-head c-head">
        <h2>Over time</h2>
        <p class="note">Share of the field they finished ahead of, averaged per comp.</p>
      </header>
      <div class="sec-body c-body">
        <div id="chart"></div>
        <div class="chart-tip" id="chartTip"></div>
      </div>
    </section>

    <section data-sec="breakdown">
      <header class="sec-head c-head">
        <h2>Where they’re strongest</h2>
        <p class="note">The same stats, split up. Use Sort by or click a column heading to reorder.</p>
      </header>
      <div class="sec-body c-body">
        <div class="tabs" id="bdTabs"></div>
        <p class="note hidden" id="bdDanceNote">Multi-dance events count once for each listed dance, using the overall event placement.</p>
        <div class="tools"><label class="hint">Sort by <select id="bdSort" aria-label="Sort the breakdown table"></select></label><label class="hint">Show <select class="limit" data-t="breakdown" aria-label="How many rows to show"><option value="5">Top 5</option><option value="10">Top 10</option><option value="25">Top 25</option><option value="all">All</option></select></label></div>
        <div class="scroll" id="bdTable"></div>
        <div class="limit-foot" id="foot-breakdown"></div>
      </div>
    </section>

    <section data-sec="ycn">
      <header class="sec-head c-head">
        <h2>YCN points</h2>
        <p class="note">From the Ballroom Comp Express results above, using <a href="https://ballroom.mit.edu/ycn-proficiency-points/" target="_blank" rel="noopener">MIT’s single-ladder YCN rules</a>, the same rules LilacDB follows. Seven or more points in a level closes that level for that dance. Honors the event-exclusion checkboxes; other filters do not affect YCN points.</p>
      </header>
      <div class="sec-body c-body">
        <div class="tab-row"><span class="hint">Role</span><div class="tabs" id="ycnRoles"></div></div>
        <div class="tools"><label class="hint check-inline"><input type="checkbox" id="ycnAdultOnly" checked> Only adult and collegiate events</label></div>
        <div class="scroll" id="ycnTable"></div>
        <div class="ycn-lilac note" id="ycnLilac"></div>
        <details class="ycn-more" id="ycnLevelsBox"><summary id="ycnLevelsSummary">Level names</summary>
          <p class="note">Some level names mean different things at different comps. Choose what each one means at that comp; your choices are saved.</p>
          <div id="ycnLevels"></div>
        </details>
        <details class="ycn-more"><summary>How each event counted</summary><div id="ycnEvents"></div></details>
      </div>
    </section>

    <section data-sec="h2h">
      <header class="sec-head c-head">
        <h2>Head-to-head</h2>
        <p class="note">Every time they and another dancer were placed in the same event. Click a row to see those events.</p>
      </header>
      <div class="sec-body c-body">
        <div class="tabs" id="h2hBy"></div>
        <div class="tools">
          <input type="search" id="h2hSearch" placeholder="Find an opponent" aria-label="Find an opponent">
          <label class="hint">At least <select id="h2hMin"><option>1</option><option>2</option><option selected>3</option><option>5</option><option>10</option></select> meetings</label>
          <label class="hint">Show <select class="limit" data-t="h2h" aria-label="How many rows to show"><option value="5">Top 5</option><option value="10">Top 10</option><option value="25">Top 25</option><option value="all">All</option></select></label>
        </div>
        <div class="scroll" id="h2hTable"></div>
        <div class="limit-foot" id="foot-h2h"></div>
      </div>
    </section>

    <section data-sec="rivals">
      <header class="sec-head c-head">
        <h2>Placed above and below</h2>
        <p class="note" id="rivNote"></p>
      </header>
      <div class="sec-body c-body">
        <div class="tab-row"><span class="hint">Style</span><div class="tabs" id="rivStyles"></div></div>
        <div class="tab-row"><span class="hint">Dance</span><div class="tabs" id="rivDances"></div></div>
        <div class="tools">
          <label class="hint check-inline"><input type="checkbox" id="rivSingle"> Single-dance events only</label>
          <label class="hint">Sort by <select id="rivSort" aria-label="Sort the placed above and below table"></select></label>
          <input type="search" id="rivSearch" placeholder="Find a couple" aria-label="Find a couple">
          <label class="hint">At least <select id="rivMin"><option>1</option><option selected>2</option><option>3</option><option>5</option></select> meetings</label>
          <label class="hint">Show <select class="limit" data-t="rivals" aria-label="How many rows to show"><option value="5">Top 5</option><option value="10">Top 10</option><option value="25">Top 25</option><option value="all">All</option></select></label>
        </div>
        <div class="scroll" id="rivTable"></div>
        <div class="limit-foot" id="foot-rivals"></div>
      </div>
    </section>

    <section data-sec="events">
      <header class="sec-head c-head">
        <h2>Every event</h2>
        <p class="note" id="evNote"></p>
      </header>
      <div class="sec-body c-body">
        <div class="tools"><label class="hint">Show <select class="limit" data-t="events" aria-label="How many rows to show"><option value="5">Top 5</option><option value="10">Top 10</option><option value="25">Top 25</option><option value="all">All</option></select></label></div>
        <div class="scroll" id="evTable"></div>
        <div class="limit-foot" id="foot-events"></div>
      </div>
    </section>
  </div>
</main>

<button type="button" id="themeToggle" class="theme-toggle" aria-label="Switch color theme" title="Switch color theme">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.4 1.4m11.2 11.2L19 19M5 19l1.4-1.4M17.6 6.4 19 5"/></svg>
</button>
<script>
const themeToggle = document.getElementById("themeToggle");
function updateThemeToggle() {
  const dark = document.documentElement.dataset.theme === "dark";
  themeToggle.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
  themeToggle.title = dark ? "Switch to light mode" : "Switch to dark mode";
}
themeToggle.addEventListener("click", () => {
  const theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem("bsa-theme", theme); } catch {}
  updateThemeToggle();
});
updateThemeToggle();
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const norm = (s) => (s || "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
const avg = (a) => a.length ? a.reduce((x, y) => x + y, 0) / a.length : null;
const r1 = (x) => x == null ? "–" : (Math.round(x * 10) / 10).toString();
const pct = (x) => x == null ? "–" : Math.round(x) + "%";

const state = {
  fieldMode: "total",
  data: null, filters: {style: "", level: "", category: "", division: "", partner: "", excludeUncontested: false, excludeThreeCouplePodiums: false},
  bdKey: "category", bdSort: {key: "events", dir: -1},
  limits: {breakdown: "all", h2h: "10", rivals: "10", events: "25"}, collapsed: {}, ycnLevels: {}, ycnRole: "",
  rivStyle: "", rivDance: "", rivSort: {key: "above", dir: -1}, rivOpen: null, h2hBy: "dancer", h2hSort: {key: "meetings", dir: -1}, evSort: {key: "order", dir: 1},
  openOpp: null, jobId: null, resultJobId: null, timer: null,
};
$("fieldMode").addEventListener("change", (event) => {
  state.fieldMode = event.target.value;
  if (state.data) render();
});

// ---------------- Collapsing sections and row limits (remembered between visits) ----------------
const PREFS_KEY = "bce-comp-history-ui-v1";
function loadPrefs() {
  try {
    const p = JSON.parse(localStorage.getItem(PREFS_KEY) || "{}");
    if (p.limits) Object.assign(state.limits, p.limits);
    if (p.collapsed) state.collapsed = p.collapsed;
    if (p.ycnLevels) state.ycnLevels = p.ycnLevels;
  } catch { /* storage unavailable: use defaults */ }
}
function savePrefs() {
  try { localStorage.setItem(PREFS_KEY, JSON.stringify({limits: state.limits, collapsed: state.collapsed, ycnLevels: state.ycnLevels})); } catch { /* ignore */ }
}
function applyLimit(rows, t) {
  const lim = state.limits[t];
  return lim === "all" ? rows : rows.slice(0, Number(lim));
}
function renderFoot(t, shown, total, noun) {
  $("foot-" + t).innerHTML = shown < total
    ? `Showing ${shown} of ${total} ${noun}. <button type="button" class="linkbtn" data-showall="${t}">Show all</button>` : "";
}
function setCollapsed(sec, collapsed) {
  const el = document.querySelector(`section[data-sec="${sec}"]`);
  if (!el) return;
  el.classList.toggle("collapsed", collapsed);
  el.querySelector(".sec-toggle")?.setAttribute("aria-expanded", String(!collapsed));
  state.collapsed[sec] = collapsed;
  savePrefs();
  updateCollapseAll();
}
function updateCollapseAll() {
  const secs = [...document.querySelectorAll("section[data-sec]")];
  const allCollapsed = secs.every((x) => x.classList.contains("collapsed"));
  $("collapseAll").textContent = allCollapsed ? "Expand all sections" : "Collapse all sections";
}
loadPrefs();
document.querySelectorAll("section[data-sec]").forEach((sec) => {
  const h2 = sec.querySelector("h2");
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "sec-toggle";
  btn.setAttribute("aria-expanded", "true");
  btn.textContent = h2.textContent;
  h2.textContent = "";
  h2.appendChild(btn);
  btn.addEventListener("click", () => setCollapsed(sec.dataset.sec, !sec.classList.contains("collapsed")));
  if (state.collapsed[sec.dataset.sec]) { sec.classList.add("collapsed"); btn.setAttribute("aria-expanded", "false"); }
});
updateCollapseAll();
$("collapseAll").addEventListener("click", () => {
  const secs = [...document.querySelectorAll("section[data-sec]")];
  const collapse = !secs.every((x) => x.classList.contains("collapsed"));
  secs.forEach((x) => setCollapsed(x.dataset.sec, collapse));
});
document.querySelectorAll("select.limit").forEach((sel) => {
  sel.value = state.limits[sel.dataset.t];
  sel.addEventListener("change", () => { state.limits[sel.dataset.t] = sel.value; savePrefs(); if (state.data) render(); });
});
document.addEventListener("click", (ev) => {
  const b = ev.target.closest("button[data-showall]");
  if (!b) return;
  const t = b.dataset.showall;
  state.limits[t] = "all";
  document.querySelector(`select.limit[data-t="${t}"]`).value = "all";
  savePrefs(); render();
});

// A random ID for this browser, so a public site can give each visitor their own search limits
const VISITOR_ID = (() => {
  const fresh = () => [...crypto.getRandomValues(new Uint8Array(16))].map((b) => b.toString(16).padStart(2, "0")).join("");
  try {
    let v = localStorage.getItem("bce-visitor-id");
    if (!/^[0-9a-f]{32}$/.test(v || "")) { v = fresh(); localStorage.setItem("bce-visitor-id", v); }
    return v;
  } catch { return fresh(); }
})();

// Public sites can require a dancer ID (a name-only search reads every event on Ballroom Comp Express)
async function loadPartnerLeader(attempt = 0) {
  try {
    const response = await fetch("/api/partner-leader");
    if (!response.ok) return;
    const leader = await response.json();
    if (!leader.ready) {
      if (attempt < 30) setTimeout(() => loadPartnerLeader(attempt + 1), 2000);
      return;
    }
    if (!leader.names.length) return;
    const extra = leader.tied > leader.names.length ? ` + ${leader.tied - leader.names.length} tied` : "";
    $("partnerLeader").textContent = `Most Dance Partners: ${leader.names.join(" / ")}${extra}`;
    $("partnerJoke").classList.remove("hidden");
  } catch { /* Optional splash message should never prevent a search. */ }
}
// Optional "Most Dance Partners" feature: uncomment alongside the Python hooks.
// loadPartnerLeader();

fetch("/api/config").then((r) => r.json()).then((c) => {
  state.requireId = !!c.requireId;
  if (state.requireId) {
    $("nameOnlyNote").remove();
  }
}).catch(() => {});

// ---------------- Search & progress ----------------
const selectedSource = () => $("source").value;
const dancerLookup = {matches: new Map(), selectedName: "", timer: null, sequence: 0};
function chooseDancer(dancer) {
  $("name").value = dancer.name;
  $("aid").value = dancer.id;
  $("aid").hidden = false;
  dancerLookup.selectedName = dancer.name;
  $("dancerSuggestions").replaceChildren();
  $("dancerLookupStatus").textContent = `Selected ${dancer.name} · ID ${dancer.id}${dancer.location ? " · " + dancer.location : ""}`;
}
async function lookupDancers(query) {
  const sequence = ++dancerLookup.sequence;
  if (query.length < 3 || /^\d+$/.test(query)) return [];
  $("dancerLookupStatus").textContent = "Finding matching dancers…";
  try {
    const response = await fetch("/api/dancers?q=" + encodeURIComponent(query), {headers: {"X-Visitor": VISITOR_ID}});
    const result = await response.json();
    if (sequence !== dancerLookup.sequence) return [];
    if (!response.ok) throw new Error(result.error || "Name lookup is unavailable. Enter a dancer ID instead.");
    dancerLookup.matches.clear();
    const options = result.dancers.map((dancer) => {
      const option = document.createElement("option");
      option.value = `${dancer.name} — ID ${dancer.id}`;
      option.label = dancer.location || `Dancer ID ${dancer.id}`;
      dancerLookup.matches.set(option.value, dancer);
      return option;
    });
    $("dancerSuggestions").replaceChildren(...options);
    $("dancerLookupStatus").textContent = options.length
      ? "Choose a matching dancer from the suggestions to fill their ID."
      : "No matching dancers found. Try a different spelling or enter a dancer ID.";
    return result.dancers;
  } catch (error) {
    if (sequence === dancerLookup.sequence) $("dancerLookupStatus").textContent = error.message;
    return [];
  }
}
$("name").addEventListener("input", () => {
  clearTimeout(dancerLookup.timer);
  const value = $("name").value.trim();
  const selected = dancerLookup.matches.get(value);
  if (selected) { ++dancerLookup.sequence; chooseDancer(selected); return; }
  if (dancerLookup.selectedName && value !== dancerLookup.selectedName) {
    $("aid").value = "";
    $("aid").hidden = true;
    dancerLookup.selectedName = "";
  }
  ++dancerLookup.sequence;
  $("dancerSuggestions").replaceChildren();
  if (selectedSource() !== "o2cm" && value.length >= 3 && !/^\d+$/.test(value)) {
    dancerLookup.timer = setTimeout(() => lookupDancers(value), 500);
  } else {
    $("dancerLookupStatus").textContent = selectedSource() === "o2cm"
      ? "Enter the full registration name or a Ballroom Comp Express dancer ID. For compound surnames, use Last name, First name."
      : "Type at least 3 characters and choose a dancer, or enter a dancer ID.";
  }
});
function updateSource() {
  const o2cm = selectedSource() === "o2cm";
  ++dancerLookup.sequence; clearTimeout(dancerLookup.timer);
  dancerLookup.matches.clear();
  $("dancerSuggestions").replaceChildren();
  $("name").setAttribute("list", o2cm ? "" : "dancerSuggestions");
  $("fuzzy").disabled = o2cm;
  $("dancerLookupStatus").textContent = o2cm
    ? "Enter a full name or Ballroom Comp Express dancer ID. For compound surnames, use Last name, First name."
    : selectedSource() === "all"
    ? "Type at least 3 characters and choose a dancer"
    : "Type a name and choose a dancer, or enter a Ballroom Comp Express dancer ID.";
  $("cids").disabled = selectedSource() === "all";
  if ($("cids").disabled) $("cids").value = "";
  $("cids").placeholder = o2cm ? "All, or mit26, big23" : "All, or e.g. 150-250";
  $("competitionFilterLabel").textContent = o2cm ? "O2CM competition codes" : "Comp ids to scan";
  $("idNote").textContent = o2cm
    ? "Enter the full name used for O2CM registration. A Ballroom Comp Express ID can also resolve the name. Check the returned partners and competitions."
    : "Search by name or dancer ID. Unified data includes both providers; shared partnerships help distinguish matching names.";
  for (const [id, value] of [["sourceBce", "bce"], ["sourceO2cm", "o2cm"], ["sourceAll", "all"]]) {
    $(id).setAttribute("aria-pressed", String(selectedSource() === value));
  }
}
$("source").addEventListener("change", updateSource);
for (const [id, value] of [["sourceBce", "bce"], ["sourceO2cm", "o2cm"], ["sourceAll", "all"]]) {
  $(id).addEventListener("click", () => { $("source").value = value; updateSource(); });
}
updateSource();

$("searchForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  let name = $("name").value.trim(), aid = dancerLookup.selectedName === $("name").value.trim() ? $("aid").value.trim() : "";
  const source = selectedSource();
  if (/^\d+$/.test(name)) { aid = name; name = ""; }
  if (!name && !aid) { $("name").focus(); return; }
  if (source === "bce" && aid && !/^\d+$/.test(aid)) return fail("A dancer ID is a number, like 10062.");
  if (source !== "o2cm" && state.requireId && !aid) {
    clearTimeout(dancerLookup.timer);
    $("goBtn").disabled = true;
    const matches = await lookupDancers(name);
    $("goBtn").disabled = false;
    const exact = matches.filter((dancer) => norm(dancer.name) === norm(name));
    if (exact.length === 1) {
      chooseDancer(exact[0]);
      name = exact[0].name; aid = String(exact[0].id);
    } else if (source === "bce") { $("name").focus(); return; }
  }
  $("goBtn").disabled = true;
  show("statusView");
  setStatus("Starting…", 0);
  try {
    const res = await fetch("/api/start", {method: "POST", headers: {"Content-Type": "application/json", "X-Visitor": VISITOR_ID},
      body: JSON.stringify({source, name, aid, fuzzy: $("fuzzy").checked,
                            partner: $("partner").value.trim(), cids: $("cids").value.trim()})});
    const j = await res.json();
    if (!res.ok) throw new Error(j.error || "The search didn’t start.");
    state.jobId = j.id;
    state.slowSearch = source === "bce" && !aid;
    poll();
  } catch (err) {
    fail(err.message.includes("fetch") ? "The local server isn’t running. Start it with: python bce_web.py" : err.message);
  }
});

$("cancelBtn").addEventListener("click", async () => {
  if (!state.jobId) return;
  await fetch("/api/cancel", {method: "POST", headers: {"Content-Type": "application/json", "X-Visitor": VISITOR_ID}, body: JSON.stringify({id: state.jobId})});
  setStatus("Stopping…", null);
});

async function poll() {
  clearTimeout(state.timer);
  let j;
  try { j = await (await fetch("/api/status?id=" + state.jobId)).json(); }
  catch { return fail("Lost contact with the local server. Is the terminal window running bce_web.py still open?"); }
  if (j.state === "running") {
    const share = j.total ? j.done / j.total : 0;
    const overall = j.stage === "comps" ? share * 0.35 : j.stage === "events" ? 0.35 + share * 0.65 : 0.02;
    const note = state.slowSearch && j.stage === "events" ? " Searching by name reads every event on the site; adding a dancer ID is much faster." : "";
    setStatus((j.message || "Working…") + note, overall);
    state.timer = setTimeout(poll, 300);
  } else if (j.state === "done") {
    $("goBtn").disabled = false;
    state.resultJobId = state.jobId;
    handleResult(j.result);
  } else if (j.state === "cancelled") {
    $("goBtn").disabled = false;
    show(state.data ? "resultView" : "emptyView");
  } else {
    fail(j.error || "The search stopped unexpectedly.");
  }
}

function setStatus(msg, frac) {
  $("statusMsg").textContent = msg;
  $("statusMsg").classList.remove("error");
  $("cancelBtn").classList.remove("hidden");
  $("statusBar").parentElement.classList.remove("hidden");
  if (frac != null) $("statusBar").style.width = Math.max(2, Math.round(frac * 100)) + "%";
}
function fail(msg) {
  $("goBtn").disabled = false;
  show("statusView");
  $("statusMsg").textContent = msg;
  $("statusMsg").classList.add("error");
  $("cancelBtn").classList.add("hidden");
  $("statusBar").parentElement.classList.add("hidden");
}
function show(id) {
  for (const v of ["emptyView", "statusView", "resultView"]) $(v).classList.toggle("hidden", v !== id);
}

function handleResult(res) {
  if (res.status === "no_all_results") return fail("No matching results were found across the selected sources. " + (res.warnings || []).join(" "));
  if (res.status === "no_o2_results") return fail("No O2CM results matched that exact name and filters. Check the spelling, partner, and competition codes.");
  if (res.status === "bad_aid") return fail(`Couldn’t open the results page for dancer ID ${res.aid}. Check the number and try again.`);
  if (res.status === "no_aid_comps") return fail(`Dancer ID ${res.aid} has no competition results on the site${$("cids").value.trim() ? " in the comp ids you entered" : ""}. Check the number.`);
  if (res.status === "no_comps") return fail("Couldn’t load any competition results. Check your internet connection and try again.");
  if (res.status === "no_events") {
    const s = res.suggestions.length ? ` Similar names in the results: ${res.suggestions.join(", ")}.` : "";
    return fail(`Read ${res.events_scanned} events and didn’t find “${res.name || "that dancer"}”.${s} Check the spelling as it appears on the site, or turn on “Match similar spellings” in Options.`);
  }
  res.events.forEach((e, i) => { e.order = i; });
  clearComparison();
  $("aid").value = res.aid || "";
  $("aid").hidden = !res.aid;
  dancerLookup.selectedName = res.aid ? $("name").value.trim() : "";
  state.data = res;
  $("sourceNotice").textContent = (res.warnings || []).join(" ");
  $("sourceNotice").classList.toggle("hidden", !(res.warnings || []).length);
  state.filters = {style: "", level: "", category: "", division: "", partner: "", excludeUncontested: false, excludeThreeCouplePodiums: false};
  state.openOpp = null;
  state.rivOpen = null;
  state.rivStyle = "";
  state.rivDance = "";
  state.ycnRole = "";
  buildFilters();
  show("resultView");
  renderAlternatives(res);
  render();
}

function renderAlternatives(res) {
  const box = $("whoAlt");
  if (!res.alternatives || !res.alternatives.length) { box.classList.add("hidden"); return; }
  box.innerHTML = `Not ${esc(res.name)}? These dancers were also in every event:` +
    res.alternatives.slice(0, 6).map((a) => `<button type="button" class="linkbtn" data-alt="${esc(a)}">${esc(a)}</button>`).join("");
  box.classList.remove("hidden");
  box.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    $("name").value = b.dataset.alt;
    $("aid").value = res.aid || "";
    dancerLookup.selectedName = b.dataset.alt;
    $("searchForm").requestSubmit();
  }));
}

// ---------------- Computation ----------------
async function exportResults(format) {
  if (!state.data || !state.resultJobId) return;
  $("exportCsv").disabled = $("exportPdf").disabled = true;
  $("exportStatus").textContent = `Preparing ${format.toUpperCase()}…`;
  try {
    const response = await fetch("/api/export", {method: "POST",
      headers: {"Content-Type": "application/json", "X-Visitor": VISITOR_ID},
      body: JSON.stringify({id: state.resultJobId, format, filters: {...state.filters}})});
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || "The export failed. Please try again.");
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = response.headers.get("Content-Disposition")?.match(/filename="([^"]+)"/)?.[1] || `results.${format}`;
    document.body.appendChild(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    $("exportStatus").textContent = `${format.toUpperCase()} downloaded. Includes all events matching the current filters.`;
  } catch (error) {
    $("exportStatus").textContent = error.message;
  } finally {
    $("exportCsv").disabled = $("exportPdf").disabled = false;
  }
}
$("exportCsv").addEventListener("click", () => exportResults("csv"));
$("exportPdf").addEventListener("click", () => exportResults("pdf"));

function passesEventExclusions(e) {
  const f = state.filters;
  const threeCouplePodium = e.entries === 3 && e.place != null && e.place >= 1 && e.place <= 3 &&
    e.category !== "Solo" && e.role !== "Solo";
  return (!f.excludeUncontested || e.entries !== 1) && (!f.excludeThreeCouplePodiums || !threeCouplePodium);
}

function filterEvents(events) {
  const f = state.filters;
  return events.filter((e) =>
    (!f.style || e.style === f.style) && (!f.level || e.level === f.level) &&
    (!f.category || e.category === f.category) && (!f.division || e.division === f.division) && (!f.partner || (e.partner || "(solo)") === f.partner) &&
    passesEventExclusions(e));
}
function filtered() { return filterEvents(state.data.events); }

function fieldBeaten(e) {
  return state.fieldMode === "finals" ? e.final_percentile ?? null : e.percentile;
}
function summary(evs) {
  const placed = evs.filter((e) => e.place != null);
  return {
    events: evs.length,
    wins: placed.filter((e) => e.place === 1).length,
    podiums: placed.filter((e) => e.place <= 3).length,
    finals: evs.filter((e) => e.made_final).length,
    avgPlace: avg(placed.map((e) => e.place)),
    avgField: avg(evs.map((e) => e.entries)),
    avgPct: avg(evs.map(fieldBeaten).filter((value) => value != null)),
  };
}

function headToHead(evs, by) {
  const map = new Map();
  for (const e of evs) {
    if (e.place == null) continue;
    const own = new Set(e.field.find((f) => f.entry === e.entry)?.people.map(norm) || []);
    for (const f of e.field) {
      if (f.entry === e.entry || f.place == null) continue;
      const opps = by === "couple" ? [f.entry] : f.people;
      for (const o of opps) {
        const k = norm(o);
        if (!k || own.has(k)) continue;
        let h = map.get(k);
        if (!h) { h = {key: k, name: o, meetings: 0, wins: 0, losses: 0, ties: 0, finals: 0, list: []}; map.set(k, h); }
        h.meetings++;
        if (e.place < f.place) h.wins++; else if (e.place > f.place) h.losses++; else h.ties++;
        if (e.made_final && f.made_final) h.finals++;
        h.list.push({e, theirs: f.place, theirEntry: f.entry});
      }
    }
  }
  for (const h of map.values()) {
    const d = h.wins + h.losses;
    h.winPct = d ? 100 * h.wins / d : null;
  }
  return [...map.values()];
}

// ---------------- Dancer comparison ----------------
const comparison = {data: null, job: null, sequence: 0, lookupSequence: 0, timer: null, matches: new Map(), selected: null};
function comparisonBusy(busy) {
  $("compareGo").disabled = busy;
  $("goBtn").disabled = busy;
  $("compareStop").classList.toggle("hidden", !busy);
}
function clearComparison() {
  ++comparison.sequence; ++comparison.lookupSequence;
  clearTimeout(comparison.timer);
  if (comparison.job) fetch("/api/cancel", {method: "POST", headers: {"Content-Type": "application/json", "X-Visitor": VISITOR_ID}, body: JSON.stringify({id: comparison.job})}).catch(() => {});
  comparison.job = null; comparison.data = null; comparison.selected = null; comparison.matches.clear();
  $("compareName").value = "";
  $("compareSuggestions").replaceChildren();
  $("compareStatus").textContent = "Look up another dancer to compare their results with yours.";
  comparisonBusy(false); renderComparison();
}
async function comparisonLookup(query) {
  const sequence = ++comparison.lookupSequence;
  const response = await fetch("/api/dancers?q=" + encodeURIComponent(query), {headers: {"X-Visitor": VISITOR_ID}});
  const data = await response.json();
  if (sequence !== comparison.lookupSequence) return [];
  if (!response.ok) throw new Error(data.error || "Name lookup failed. Try a dancer ID.");
  comparison.matches.clear();
  $("compareSuggestions").replaceChildren(...data.dancers.map(dancer => {
    const option = document.createElement("option");
    option.value = `${dancer.name} — ID ${dancer.id}`; option.label = dancer.location || "Ballroom Comp Express";
    comparison.matches.set(option.value, dancer); return option;
  }));
  return data.dancers;
}
$("compareName").addEventListener("input", () => {
  clearTimeout(comparison.timer); ++comparison.lookupSequence;
  const query = $("compareName").value.trim(), match = comparison.matches.get(query);
  comparison.selected = match || null;
  if (match) {
    $("compareName").value = match.name;
    $("compareStatus").textContent = `Selected ${match.name} · BCE ID ${match.id}`;
    $("compareSuggestions").replaceChildren(); return;
  }
  $("compareSuggestions").replaceChildren();
  if (query.length >= 3 && !/^\d+$/.test(query) && state.data?.source !== "o2cm") {
    comparison.timer = setTimeout(() => comparisonLookup(query).catch(error => { $("compareStatus").textContent = error.message; }), 500);
  }
});
$("compareClear").addEventListener("click", clearComparison);
$("compareStop").addEventListener("click", () => {
  clearComparison(); $("compareStatus").textContent = "Comparison stopped.";
});
$("compareForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.data) return;
  const sequence = ++comparison.sequence;
  ++comparison.lookupSequence; clearTimeout(comparison.timer);
  let name = $("compareName").value.trim(), aid = comparison.selected?.name === name ? String(comparison.selected.id) : "";
  const source = state.data.source || "bce";
  if (!name) return;
  if (/^\d+$/.test(name)) { aid = name; name = ""; }
  comparison.data = null; renderComparison();
  comparisonBusy(true); $("compareStatus").textContent = "Looking up comparison dancer…";
  try {
    if (!aid && source !== "o2cm") {
      let matches;
      try { matches = await comparisonLookup(name); }
      catch (error) { if (source === "bce") throw error; matches = []; }
      if (sequence !== comparison.sequence) return;
      const exact = matches.filter(dancer => norm(dancer.name) === norm(name));
      if (exact.length === 1) { aid = String(exact[0].id); name = exact[0].name; }
      else if (source === "bce") throw new Error("Choose a matching dancer suggestion or enter their BCE ID.");
    }
    if ((aid && state.data.aid && String(state.data.aid) === aid) ||
        (source === "o2cm" && !aid && norm(name) === norm(state.data.name))) throw new Error("Choose a different dancer to compare with yourself.");
    const response = await fetch("/api/start", {method: "POST", headers: {"Content-Type": "application/json", "X-Visitor": VISITOR_ID},
      body: JSON.stringify({source, name, aid, fuzzy: false, partner: "", cids: ""})});
    const started = await response.json();
    if (!response.ok) throw new Error(started.error || "The comparison could not start.");
    if (sequence !== comparison.sequence) {
      fetch("/api/cancel", {method: "POST", headers: {"Content-Type": "application/json", "X-Visitor": VISITOR_ID}, body: JSON.stringify({id: started.id})}).catch(() => {}); return;
    }
    comparison.job = started.id;
    async function check() {
      try {
        const response = await fetch("/api/status?id=" + encodeURIComponent(started.id));
        const job = await response.json();
        if (sequence !== comparison.sequence) return;
        if (!response.ok) throw new Error(job.error || "The comparison expired. Try again.");
        if (job.state === "running") {
          $("compareStatus").textContent = job.message || "Loading comparison…";
          comparison.timer = setTimeout(check, 500); return;
        }
        comparison.job = null;
        if (job.state !== "done") throw new Error(job.error || "Comparison stopped.");
        if (job.result.status !== "ok" || !job.result.events.length) throw new Error("No comparison results found. Check the name, source, or dancer ID. " + (job.result.warnings || []).join(" "));
        if (job.result.aid && state.data.aid && String(job.result.aid) === String(state.data.aid)) throw new Error("Both searches resolved to the same dancer. Choose another profile.");
        comparison.data = job.result;
        $("compareStatus").textContent = `Comparing ${state.data.name} with ${job.result.name}.`;
        renderComparison(); comparisonBusy(false);
      } catch (error) { if (sequence === comparison.sequence) { comparison.job = null; $("compareStatus").textContent = error.message; comparisonBusy(false); } }
    }
    check();
  } catch (error) { if (sequence === comparison.sequence) { $("compareStatus").textContent = error.message; comparisonBusy(false); } }
});
function sharedComparisonEvents(ours, theirs) {
  const key = event => JSON.stringify([event.source || "bce", String(event.cid), String(event.eid)]);
  const index = new Map(theirs.map(event => [key(event), event]));
  return ours.flatMap(event => {
    const other = index.get(key(event));
    if (!other) return [];
    const together = norm(event.entry) === norm(other.entry);
    const outcome = together ? "Together" : event.place == null || other.place == null ? "Unplaced"
      : event.place < other.place ? "Win" : event.place > other.place ? "Loss" : "Tie";
    return [{event, other, outcome}];
  });
}
function renderComparison() {
  for (const id of ["compareStats", "compareMeetings", "compareEvents", "compareWarnings"]) $(id).textContent = "";
  if (!comparison.data || !state.data) return;
  const ours = filtered(), theirs = filterEvents(comparison.data.events);
  const a = summary(ours), b = summary(theirs);
  $("compareWarnings").textContent = (comparison.data.warnings || []).join(" ");
  const metrics = [
    ["Events", a.events, b.events], ["Competitions", new Set(ours.map(e=>e.cid)).size, new Set(theirs.map(e=>e.cid)).size],
    ["Wins", a.wins, b.wins], ["Win rate", pct(a.events ? 100*a.wins/a.events : null), pct(b.events ? 100*b.wins/b.events : null)],
    ["Top-3 finishes", a.podiums, b.podiums], ["Finals", a.finals, b.finals],
    ["Finals rate", pct(a.events ? 100*a.finals/a.events : null), pct(b.events ? 100*b.finals/b.events : null)],
    ["Average place", r1(a.avgPlace), r1(b.avgPlace)], ["Average entry count", r1(a.avgField), r1(b.avgField)],
    [state.fieldMode === "finals" ? "Finals field beaten" : "Total field beaten", pct(a.avgPct), pct(b.avgPct)]
  ];
  $("compareStats").innerHTML = `<table><thead><tr><th>Metric</th><th>${esc(state.data.name)} (you)</th><th>${esc(comparison.data.name)}</th></tr></thead><tbody>${metrics.map(row=>`<tr>${row.map((value,i)=>`<${i?'td':'th'}>${esc(value)}</${i?'td':'th'}>`).join('')}</tr>`).join('')}</tbody></table>`;
  const shared = sharedComparisonEvents(ours, theirs);
  const count = outcome => shared.filter(row=>row.outcome===outcome).length;
  $("compareMeetings").textContent = `${shared.length} shared events after filters: ${count("Win")} wins, ${count("Loss")} losses, ${count("Tie")} ties, ${count("Together")} together, ${count("Unplaced")} without comparable placements. Outcomes are from your perspective.`;
  $("compareEvents").innerHTML = shared.length ? `<table><thead><tr><th>Date / competition</th><th>Event</th><th>Your place</th><th>Their place</th><th>Outcome</th></tr></thead><tbody>${shared.map(({event:e,other,outcome})=>`<tr><td>${esc(e.date || "Date unknown")} / ${esc(e.comp)}</td><td><a href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.event)}</a></td><td>${e.place ?? "–"}</td><td>${other.place ?? "–"}</td><td>${outcome}</td></tr>`).join('')}</tbody></table>` : `<p class="note">No shared event IDs were found in these filtered histories. You can still compare their overall statistics above.</p>`;
}

// ---------------- Rendering ----------------
function render() {
  $("fieldMode").value = state.fieldMode;
  const evs = filtered();
  const d = state.data;
  $("whoName").textContent = d.name;
  const comps = new Set(evs.map((e) => e.cid));
  const dates = evs.map((e) => e.date).filter(Boolean).sort();
  const span = dates.length ? `, ${fmtDate(dates[0])} to ${fmtDate(dates[dates.length - 1])}` : "";
  const alias = d.matched_as.filter((m) => norm(m) !== norm(d.name));
  $("whoSub").textContent = `${comps.size} comp${comps.size === 1 ? "" : "s"}${span}.` +
    (d.source === "all" ? " Sources: Ballroom Comp Express + O2CM." : d.source === "o2cm" ? " Source: O2CM." : " Source: Ballroom Comp Express.") +
    (alias.length ? ` Listed as ${alias.join(", ")}.` : "") +
    (isFiltered() ? " Filters are on." : "");
  renderMarks(evs);
  renderStats(evs);
  renderChart(evs);
  renderBreakdown(evs);
  renderH2H(evs);
  renderRivals(evs);
  renderYcn();
  renderEvents(evs);
  renderComparison();
}
const isFiltered = () => Object.values(state.filters).some(Boolean);
function fmtDate(iso) {
  const [y, m, dd] = iso.split("-").map(Number);
  return new Date(y, m - 1, dd).toLocaleDateString(undefined, {month: "short", year: "numeric"});
}

function renderMarks(evs) {
  let html = "", lastCid = null;
  for (const e of evs) {
    if (lastCid !== null && e.cid !== lastCid) html += `<span class="mark gap" aria-hidden="true"></span>`;
    lastCid = e.cid;
    const cls = e.place === 1 ? "p1" : e.place === 2 ? "p2" : e.place === 3 ? "p3" : e.made_final ? "final" : "";
    const label = `${e.comp}: ${e.event}. Placed ${e.place ?? "?"} of ${e.entries}`;
    html += `<button class="mark ${cls}" data-order="${e.order}" title="${esc(label)}" aria-label="${esc(label)}">${e.place ?? "?"}</button>`;
  }
  $("marks").innerHTML = html;
}
$("marks").addEventListener("click", (ev) => {
  const b = ev.target.closest(".mark[data-order]");
  if (!b) return;
  setCollapsed("events", false);
  let row = document.querySelector(`#evTable tr[data-order="${b.dataset.order}"]`);
  if (!row) {
    state.limits.events = "all"; savePrefs(); render();
    row = document.querySelector(`#evTable tr[data-order="${b.dataset.order}"]`);
  }
  if (!row) return;
  row.scrollIntoView({behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center"});
  row.classList.add("flash");
  setTimeout(() => row.classList.remove("flash"), 1800);
});

function renderStats(evs) {
  const s = summary(evs);
  const finalsPct = s.events ? Math.round(100 * s.finals / s.events) : 0;
  const items = [
    [s.events, "events"], [s.wins, "wins"], [s.podiums, "top-3 finishes"],
    [`${s.finals}`, `finals made (${finalsPct}%)`], [r1(s.avgPlace), "average place"],
    [pct(s.avgPct), state.fieldMode === "finals" ? "of the finals field beaten, on average" : "of the total field beaten, on average"],
  ];
  $("stats").innerHTML = items.map(([v, l]) => `<div class="stat"><b>${esc(v)}</b><span>${esc(l)}</span></div>`).join("");
}

function buildFilters() {
  const evs = state.data.events;
  const CAT_ORDER = ["Couple-judged", "Mixed proficiency – leader judged", "Mixed proficiency – follower judged", "Solo"];
  const opts = (key) => {
    const vals = [...new Set(evs.map((e) => key === "partner" ? (e.partner || "(solo)") : e[key]))];
    return key === "category" ? vals.sort((a, b) => CAT_ORDER.indexOf(a) - CAT_ORDER.indexOf(b)) : vals.sort();
  };
  const defs = [["category", "Category"], ["style", "Style"], ["level", "Level"], ["division", "Division"], ["partner", "Partner"]];
  $("filters").innerHTML = defs.map(([k, label]) =>
    `<label>${label}<select data-f="${k}"><option value="">All</option>${opts(k).map((o) => `<option>${esc(o)}</option>`).join("")}</select></label>`
  ).join("") + `<label class="check-inline" title="Hide events with exactly one entry (one couple or individual)."><input type="checkbox" id="excludeUncontested"${state.filters.excludeUncontested ? " checked" : ""}>Exclude uncontested events</label>` +
    `<label class="check-inline" title="Exclude finishes of 1st, 2nd, or 3rd when exactly three couples competed. Solo events remain included."><input type="checkbox" id="excludeThreeCouplePodiums"${state.filters.excludeThreeCouplePodiums ? " checked" : ""}>Exclude top-3 finishes in 3-couple events</label>` +
    `<button class="linkbtn" id="resetF" type="button">Clear filters</button>`;
  $("filters").querySelectorAll("select").forEach((s) => s.addEventListener("change", () => {
    state.filters[s.dataset.f] = s.value; state.openOpp = null; render();
  }));
  for (const key of ["excludeUncontested", "excludeThreeCouplePodiums"]) {
    $(key).addEventListener("change", (event) => {
      state.filters[key] = event.target.checked;
      state.openOpp = null; state.rivOpen = null; render();
    });
  }
  $("resetF").addEventListener("click", () => {
    $("filters").querySelectorAll("select").forEach((s) => { s.value = ""; });
    $("excludeUncontested").checked = false;
    $("excludeThreeCouplePodiums").checked = false;
    state.filters = {style: "", level: "", category: "", division: "", partner: "", excludeUncontested: false, excludeThreeCouplePodiums: false}; render();
  });
}

function renderChart(evs) {
  const byComp = new Map();
  for (const e of evs) {
    if (!byComp.has(e.cid)) byComp.set(e.cid, {cid: e.cid, comp: e.comp, date: e.date, evs: []});
    byComp.get(e.cid).evs.push(e);
  }
  const pts = [...byComp.values()].map((c) => ({...c, s: summary(c.evs)})).filter((c) => c.s.avgPct != null);
  if (!pts.length) { $("chart").innerHTML = `<p class="note">No placements to chart with these filters.</p>`; $("chartTip").textContent = ""; return; }
  const W = 960, H = 320, L = 44, R = 8, T = 12, B = 34;
  const x = (i) => pts.length === 1 ? (L + W - R) / 2 : L + i * (W - L - R) / (pts.length - 1);
  const y = (v) => T + (100 - v) * (H - T - B) / 100;
  let g = "";
  for (const v of [0, 25, 50, 75, 100]) g += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${v}%</text>`;
  const line = pts.map((p, i) => `${x(i)},${y(p.s.avgPct)}`).join(" ");
  const dots = pts.map((p, i) => `<circle class="dot" r="5" cx="${x(i)}" cy="${y(p.s.avgPct)}" data-i="${i}" tabindex="0"><title>${esc(p.comp)}: ${Math.round(p.s.avgPct)}%</title></circle>`).join("");
  const first = pts[0], last = pts[pts.length - 1];
  const lbl = (p) => esc(p.date ? fmtDate(p.date) : p.comp.slice(0, 18));
  const xl = `<text x="${L}" y="${H - 8}">${lbl(first)}</text>` + (pts.length > 1 ? `<text x="${W - R}" y="${H - 8}" text-anchor="end">${lbl(last)}</text>` : "");
  $("chart").innerHTML = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Average percentile by comp">${g}<polyline class="line" points="${line}"/>${dots}${xl}</svg>`;
  const tip = (i) => {
    const p = pts[i];
    $("chartTip").textContent = `${p.comp}${p.date ? " (" + fmtDate(p.date) + ")" : ""}: ${p.s.events} events, ${p.s.wins} wins, beat ${Math.round(p.s.avgPct)}% of the field.`;
  };
  $("chart").querySelectorAll(".dot").forEach((d) => {
    d.addEventListener("mouseenter", () => tip(+d.dataset.i));
    d.addEventListener("focus", () => tip(+d.dataset.i));
  });
  // trend
  const ys = pts.map((p) => p.s.avgPct), n = ys.length;
  if (n >= 2) {
    const xm = (n - 1) / 2, ym = avg(ys);
    let num = 0, den = 0;
    ys.forEach((v, i) => { num += (i - xm) * (v - ym); den += (i - xm) ** 2; });
    const slope = num / den;
    const word = slope > 1 ? "improving" : slope < -1 ? "slipping" : "holding steady";
    $("chartTip").textContent = `Trend: ${word} (${slope >= 0 ? "+" : ""}${slope.toFixed(1)} points per comp). Hover a point for details.`;
  } else {
    $("chartTip").textContent = "Hover the point for details.";
  }
}

function renderBreakdown(evs) {
  const keys = [["category", "Category"], ["style", "Style"], ["dance", "Dance"], ["level", "Level"], ["division", "Division"], ["partner", "Partner"], ["age", "Age group"]];
  $("bdDanceNote").classList.toggle("hidden", state.bdKey !== "dance");
  $("bdTabs").innerHTML = keys.map(([k, l]) => `<button type="button" data-k="${k}" aria-pressed="${state.bdKey === k}">${l}</button>`).join("");
  $("bdTabs").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { state.bdKey = b.dataset.k; renderBreakdown(filtered()); }));
  const groups = new Map();
  for (const e of evs) {
    const values = state.bdKey === "dance"
      ? ((e.dances || []).length ? [...new Set(e.dances)] : ["Unknown dance"])
      : [state.bdKey === "partner" ? (e.partner || "(solo)") : e[state.bdKey]];
    for (const k of values) {
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(e);
    }
  }
  const rows = [...groups.entries()].map(([k, g]) => {
    const s = summary(g);
    return {k, events: s.events, wins: s.wins, finalsPct: s.events ? 100 * s.finals / s.events : null,
            avgPlace: s.avgPlace, avgPct: s.avgPct};
  });
  const {key, dir} = state.bdSort;
  rows.sort((a, b) => cmp(a, b, key, dir) || b.events - a.events || String(a.k).localeCompare(String(b.k)));
  const label = keys.find(([k]) => k === state.bdKey)[1];
  $("bdSort").value = `${key}:${dir}`;
  const cols = [["k", label], ["events", "Events", 1], ["wins", "Wins", 1], ["finalsPct", "Finals", 1], ["avgPlace", "Avg place", 1], ["avgPct", "Field beaten"]];
  const shownB = applyLimit(rows, "breakdown");
  renderFoot("breakdown", shownB.length, rows.length, "rows");
  $("bdTable").innerHTML = `<table><thead>${sortHeader(cols, state.bdSort, "b")}</thead><tbody>` +
    shownB.map((r) => `<tr><td>${esc(r.k)}</td><td class="num">${r.events}</td><td class="num">${r.wins}</td><td class="num">${pct(r.finalsPct)}</td><td class="num">${r1(r.avgPlace)}</td><td><div class="bar-cell"><i style="width:${Math.round((r.avgPct || 0) * 0.8)}px"></i>${pct(r.avgPct)}</div></td></tr>`).join("") +
    `</tbody></table>`;
}

const BD_SORTS = [
  ["events", -1, "Most events"], ["events", 1, "Fewest events"],
  ["wins", -1, "Most wins"], ["wins", 1, "Fewest wins"],
  ["finalsPct", -1, "Highest finals rate"], ["finalsPct", 1, "Lowest finals rate"],
  ["avgPlace", 1, "Best average place"], ["avgPlace", -1, "Worst average place"],
  ["avgPct", -1, "Most of the field beaten"], ["avgPct", 1, "Least of the field beaten"],
  ["k", 1, "A to Z"], ["k", -1, "Z to A"],
];
$("bdSort").innerHTML = BD_SORTS.map(([k, d, l]) => `<option value="${k}:${d}">${l}</option>`).join("");
$("bdSort").addEventListener("change", () => {
  const [k, d] = $("bdSort").value.split(":");
  state.bdSort = {key: k, dir: Number(d)};
  renderBreakdown(filtered());
});
$("bdTable").addEventListener("click", (ev) => {
  const th = ev.target.closest("th[data-b]");
  if (!th) return;
  const k = th.dataset.b, cur = state.bdSort;
  // First click shows the best first: A to Z for names, lowest for average place, highest otherwise
  state.bdSort = {key: k, dir: cur.key === k ? -cur.dir : (k === "k" || k === "avgPlace" ? 1 : -1)};
  renderBreakdown(filtered());
});

function sortHeader(cols, sort, attr) {
  return `<tr>${cols.map(([k, l, num]) => `<th class="sort${num ? " num" : ""}" data-${attr}="${k}" aria-sort="${sort.key === k ? (sort.dir > 0 ? "ascending" : "descending") : "none"}">${l}</th>`).join("")}</tr>`;
}
function cmp(a, b, key, dir) {
  const va = a[key], vb = b[key];
  if (va == null && vb == null) return 0;
  if (va == null) return 1;
  if (vb == null) return -1;
  return (typeof va === "string" ? va.localeCompare(vb) : va - vb) * dir;
}

function renderH2H(evs) {
  $("h2hBy").innerHTML = [["dancer", "By dancer"], ["couple", "By couple"]].map(([k, l]) => `<button type="button" data-k="${k}" aria-pressed="${state.h2hBy === k}">${l}</button>`).join("");
  $("h2hBy").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { state.h2hBy = b.dataset.k; state.openOpp = null; renderH2H(filtered()); }));
  const all = headToHead(evs, state.h2hBy);
  const min = +$("h2hMin").value, q = norm($("h2hSearch").value);
  let rows = all.filter((h) => h.meetings >= min && (!q || h.key.includes(q)));
  const {key, dir} = state.h2hSort;
  rows.sort((a, b) => cmp(a, b, key, dir) || b.meetings - a.meetings || a.name.localeCompare(b.name));
  const totW = all.reduce((s, h) => s + h.wins, 0), totL = all.reduce((s, h) => s + h.losses, 0);
  const cols = [["name", state.h2hBy === "couple" ? "Opponent couple" : "Opponent"], ["meetings", "Met", 1], ["wins", "Won", 1], ["losses", "Lost", 1], ["ties", "Tied", 1], ["winPct", "Win rate", 1], ["finals", "Finals together", 1]];
  const shown = applyLimit(rows, "h2h");
  renderFoot("h2h", shown.length, rows.length, "opponents");
  let body = shown.map((h) => {
    const open = state.openOpp === h.key;
    let tr = `<tr class="click" data-k="${esc(h.key)}" aria-expanded="${open}"><td>${esc(h.name)}</td><td class="num">${h.meetings}</td><td class="num${h.wins ? " w" : ""}">${h.wins}</td><td class="num${h.losses ? " l" : ""}">${h.losses}</td><td class="num">${h.ties}</td><td class="num">${pct(h.winPct)}</td><td class="num">${h.finals}</td></tr>`;
    if (open) {
      tr += `<tr class="detail"><td colspan="7"><ul>${h.list.map(({e, theirs, theirEntry}) => {
        const res = e.place < theirs ? `<span class="w">won</span>` : e.place > theirs ? `<span class="l">lost</span>` : "tied";
        return `<li>${esc(e.comp)}, ${esc(e.event)}: ${res}, ${e.place} vs ${theirs}${state.h2hBy === "dancer" ? ` (${esc(theirEntry)})` : ""}</li>`;
      }).join("")}</ul></td></tr>`;
    }
    return tr;
  }).join("");
  if (!shown.length) body = `<tr><td colspan="7">No opponents match. Lower the meetings minimum or clear the search.</td></tr>`;
  const foot = totW + totL ? `<p class="note" style="margin:10px 0 0">Overall: beat ${totW} and lost to ${totL} (${Math.round(100 * totW / (totW + totL))}%) across ${all.length} opponents.</p>` : "";
  $("h2hTable").innerHTML = `<table><thead>${sortHeader(cols, state.h2hSort, "h")}</thead><tbody>${body}</tbody></table>`;
  document.querySelectorAll(".h2h-foot").forEach((n) => n.remove());
  if (foot) { const div = document.createElement("div"); div.className = "h2h-foot"; div.innerHTML = foot; $("h2hTable").after(div); }
}
$("h2hTable").addEventListener("click", (ev) => {
  const th = ev.target.closest("th[data-h]");
  if (th) {
    const k = th.dataset.h, s = state.h2hSort;
    state.h2hSort = {key: k, dir: s.key === k ? -s.dir : (k === "name" ? 1 : -1)};
    return renderH2H(filtered());
  }
  const tr = ev.target.closest("tr.click");
  if (tr) { state.openOpp = state.openOpp === tr.dataset.k ? null : tr.dataset.k; renderH2H(filtered()); }
});
$("h2hSearch").addEventListener("input", () => renderH2H(filtered()));
$("h2hMin").addEventListener("change", () => renderH2H(filtered()));

// ---------------- YCN points (MIT single-ladder rules) ----------------
const YCN_LEVELS = ["Pre-Bronze", "Bronze", "Silver", "Gold", "Novice", "Pre-Champ", "Champ"];
const YCN_STYLES = ["International Standard", "International Latin", "American Smooth", "American Rhythm"];
const YCN_AGES = ["Adult", "Collegiate", "Other"];
const CAT_LEAD = "Mixed proficiency – leader judged", CAT_FOLLOW = "Mixed proficiency – follower judged";
const YCN_DANCE_ORDER = ["Waltz", "Tango", "Viennese Waltz", "Foxtrot", "Quickstep", "Samba", "Cha Cha", "Rumba", "Paso Doble", "Jive", "Swing", "Bolero", "Mambo"];

// Which YCN level an event counts at. Clear names are read directly; names that differ between
// comps ("Beginning", "Intermediate"...) use the choice saved for that comp, or a starting guess.
function ycnLevelOf(e) {
  const t = (e.event || "").toLowerCase();
  const fixed = (level) => ({level, word: null});
  if (/master of syllabus/.test(t)) return fixed("Gold");
  if (/pre[- ]?champ/.test(t)) return fixed("Pre-Champ");
  if (/\bchamp(ionship)?\b/.test(t)) return fixed("Champ");
  if (/\bnovice\b/.test(t)) return fixed("Novice");
  if (/pre[- ]?bronze/.test(t) || /\bnewcomer\b/.test(t)) return fixed("Pre-Bronze");
  let word = null, def = null;
  if (/\bgold bar\b/.test(t)) { word = "Gold Bar"; def = "Gold"; }
  else if (/\bbronze\b/.test(t)) return fixed("Bronze");
  else if (/\bsilver\b/.test(t)) return fixed("Silver");
  else if (/\bgold\b/.test(t)) return fixed("Gold");
  else if (/\bbeginning\b/.test(t)) { word = "Beginning"; def = "Bronze"; }
  else if (/\bbeginner\b/.test(t)) { word = "Beginner"; def = "Bronze"; }
  else if (/\bintermediate\b/.test(t)) { word = "Intermediate"; def = "Silver"; }
  else if (/\badvanced\b/.test(t)) { word = "Advanced"; def = "Gold"; }
  else if (/\bsyllabus\b/.test(t)) return fixed("Bronze");
  else if (/\bopen\b/.test(t)) return fixed("Pre-Champ");
  if (!word) return {level: null, word: null};
  const key = `${e.cid}|${word}`;
  const chosen = state.ycnLevels[key];
  return {level: chosen === undefined ? def : (chosen || null), word, key, def, chosen};
}

// Points for one placing, at the level danced (d = 0), one below (d = 1), or further below (d >= 2)
function ycnAward(place, d, quarter) {
  if (place > 6) return 0;
  if (d === 0) return ({1: 3, 2: 2, 3: 1})[place] || (quarter ? 1 : 0);
  if (d === 1) return ({1: 6, 2: 4, 3: 2})[place] || (quarter ? 2 : 0);
  return 7;
}

function ycnCompute(evs, role) {
  const adultOnly = $("ycnAdultOnly").checked;
  const table = new Map(), log = [];
  for (const e of evs) {
    if (role && e.role !== role && e.role !== "Solo") continue;
    const lv = ycnLevelOf(e);
    let why = null;
    if (e.role === "Solo" || e.category === "Solo") why = "Solo event";
    else if (e.division === "Pro/Am") why = "Pro/Am event";
    else if (!YCN_STYLES.includes(e.style)) why = `${e.style} isn’t a YCN style`;
    else if (adultOnly && !YCN_AGES.includes(e.age)) why = `${e.age} age group`;
    else if (e.category === CAT_LEAD && e.role !== "Leader") why = "Leader-judged event, danced as follower";
    else if (e.category === CAT_FOLLOW && e.role !== "Follower") why = "Follower-judged event, danced as leader";
    else if (!lv.level) why = lv.word ? `“${lv.word}” is set not to count at this comp` : "Level not recognized";
    else if (!(e.dances || []).length) why = "Dances not recognized";
    else if ((e.rounds_in_event || 1) < 2) why = "No semifinal was danced";
    else if (!e.made_final || e.place == null) why = "Didn’t make the final";
    else if (e.place > 6) why = `Placed ${e.place}th in the final`;
    if (why) { log.push({e, lv, why}); continue; }
    const quarter = (e.rounds_in_event || 1) >= 3;
    const top = YCN_LEVELS.indexOf(lv.level), award = {};
    for (let i = top; i >= 0; i--) {
      const pts = ycnAward(e.place, top - i, quarter);
      if (pts) award[YCN_LEVELS[i]] = pts;
    }
    if (!Object.keys(award).length) { log.push({e, lv, why: `Placed ${e.place}th; 4th–6th only earn points when a quarterfinal was danced`}); continue; }
    for (const dance of e.dances) {
      const k = `${e.style}|${dance}`;
      if (!table.has(k)) table.set(k, {style: e.style, dance, pts: {}, src: {}});
      const row = table.get(k);
      for (const [level, pts] of Object.entries(award)) {
        row.pts[level] = (row.pts[level] || 0) + pts;
        (row.src[level] = row.src[level] || []).push(`${e.comp}: ${e.event}, placed ${e.place} (+${pts})`);
      }
    }
    log.push({e, lv, award, quarter});
  }
  return {table, log};
}

function renderYcn() {
  if (!state.data) return;
  const all = state.data.events.filter(passesEventExclusions);
  const roles = ["Leader", "Follower"].filter((r) => all.some((e) => e.role === r));
  if (!roles.length) {
    $("ycnTable").innerHTML = `<p class="note" style="margin:10px">${all.some((e) => e.source === "o2cm") ? "YCN points are unavailable for O2CM results because leader/follower roles are unverified." : "No couple events to count."}</p>`;
    for (const id of ["ycnRoles", "ycnEvents", "ycnLevels", "ycnLilac"]) $(id).innerHTML = "";
    $("ycnLevelsSummary").textContent = "Level names (none need checking)";
    document.querySelectorAll(".ycn-legend").forEach((node) => node.remove());
    return;
  }
  if (!roles.includes(state.ycnRole)) {
    state.ycnRole = roles.slice().sort((a, b) => all.filter((e) => e.role === b).length - all.filter((e) => e.role === a).length)[0];
  }
  $("ycnRoles").innerHTML = roles.map((r) => `<button type="button" data-k="${r}" aria-pressed="${state.ycnRole === r}">${r === "Leader" ? "Lead" : "Follow"} (${all.filter((e) => e.role === r).length})</button>`).join("");
  const {table, log} = ycnCompute(all, state.ycnRole);

  const rows = [...table.values()].sort((a, b) =>
    YCN_STYLES.indexOf(a.style) - YCN_STYLES.indexOf(b.style) || YCN_DANCE_ORDER.indexOf(a.dance) - YCN_DANCE_ORDER.indexOf(b.dance));
  let body = "", lastStyle = null;
  for (const r of rows) {
    if (r.style !== lastStyle) { body += `<tr class="grp"><td colspan="${YCN_LEVELS.length + 1}">${esc(r.style)}</td></tr>`; lastStyle = r.style; }
    body += `<tr><td>${esc(r.dance)}</td>` + YCN_LEVELS.map((lv) => {
      const n = r.pts[lv] || 0;
      const cls = n >= 7 ? "pt-out" : n > 0 ? "pt-some" : "pt-zero";
      const tip = n ? ` title="${esc((r.src[lv] || []).join("\n"))}"` : "";
      return `<td class="pt ${cls}"${tip}>${n || "·"}</td>`;
    }).join("") + `</tr>`;
  }
  if (!rows.length) body = `<tr><td colspan="${YCN_LEVELS.length + 1}">No points yet as ${state.ycnRole === "Leader" ? "a leader" : "a follower"}. Open “How each event counted” below to see why each event didn’t give points.</td></tr>`;
  $("ycnTable").innerHTML = `<table><thead><tr><th>Dance</th>${YCN_LEVELS.map((l) => `<th class="pt">${l}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table>`;
  document.querySelectorAll(".ycn-legend").forEach((n) => n.remove());
  $("ycnTable").insertAdjacentHTML("afterend", `<div class="ycn-legend"><span><i class="sw sw-out"></i>7 or more: that level is closed for this dance</span><span>Hover a number to see where the points came from</span></div>`);

  // LilacDB comparison
  $("ycnLilac").innerHTML = `LilacDB comparison isn’t connected yet. You can <a href="https://db.lilacdancecenter.com/proficiency" target="_blank" rel="noopener">look up ${esc(state.data.name)} on LilacDB</a> to compare by hand; its totals can be higher because it also includes comps that weren’t run on Ballroom Comp Express.`;

  // Level names that depend on the comp
  const amb = new Map();
  for (const e of all) {
    const lv = ycnLevelOf(e);
    if (lv.word && !amb.has(lv.key)) amb.set(lv.key, {lv, e, n: 0});
    if (lv.word) amb.get(lv.key).n++;
  }
  const unset = [...amb.values()].filter((a) => a.lv.chosen === undefined).length;
  $("ycnLevelsSummary").textContent = amb.size ? `Level names (${unset ? unset + " using a starting guess" : "all set"})` : "Level names (none need checking)";
  $("ycnLevels").innerHTML = amb.size ? [...amb.values()].map(({lv, e, n}) => {
    const cur = lv.chosen === undefined ? lv.def : lv.chosen;
    const opts = YCN_LEVELS.map((l) => `<option value="${l}"${cur === l ? " selected" : ""}>${l}</option>`).join("") + `<option value=""${cur === "" ? " selected" : ""}>Don’t count</option>`;
    return `<div class="lvl-row"><div>${esc(e.comp)}</div><div><strong>${esc(lv.word)}</strong></div><div><select data-key="${esc(lv.key)}" aria-label="${esc(lv.word)} at ${esc(e.comp)} means">${opts}</select></div><div class="hint">${lv.chosen === undefined ? "Starting guess. " : ""}${n} event${n === 1 ? "" : "s"}, e.g. ${esc(e.event)}</div></div>`;
  }).join("") : `<p class="note">Every level name in these results is unambiguous.</p>`;
  if (unset && !$("ycnLevelsBox").dataset.touched) $("ycnLevelsBox").open = true;

  // Event-by-event log
  const counted = log.filter((x) => x.award), skipped = log.filter((x) => x.why);
  const fmtAward = (a) => YCN_LEVELS.filter((l) => a[l]).reverse().map((l) => `${l} ${a[l]}`).join(", ");
  $("ycnEvents").innerHTML =
    `<p class="note" style="margin:8px 0 0">${counted.length} event${counted.length === 1 ? "" : "s"} gave points; ${skipped.length} didn’t.</p>` +
    (counted.length ? `<ul class="ycn-log">${counted.map(({e, lv, award, quarter}) => `<li>${esc(e.comp)}, ${esc(e.event)}: placed ${e.place}${quarter ? " (with a quarterfinal)" : ""}, read as ${esc(lv.level)}. ${esc(e.dances.join(", "))}: ${esc(fmtAward(award))}</li>`).join("")}</ul>` : "") +
    (skipped.length ? `<p class="note" style="margin:10px 0 0">No points:</p><ul class="ycn-log">${skipped.map(({e, why}) => `<li>${esc(e.comp)}, ${esc(e.event)}: ${esc(why)}</li>`).join("")}</ul>` : "");
}
$("ycnRoles").addEventListener("click", (ev) => {
  const b = ev.target.closest("button[data-k]");
  if (b) { state.ycnRole = b.dataset.k; renderYcn(); }
});
$("ycnAdultOnly").addEventListener("change", renderYcn);
$("ycnLevelsBox").addEventListener("toggle", () => { $("ycnLevelsBox").dataset.touched = "1"; });
$("ycnLevels").addEventListener("change", (ev) => {
  const sel = ev.target.closest("select[data-key]");
  if (!sel) return;
  state.ycnLevels[sel.dataset.key] = sel.value;
  savePrefs();
  renderYcn();
});

// ---------------- Placed above and below (opposing couples) ----------------
function rivalsData(evs) {
  const map = new Map();
  for (const e of evs) {
    if (e.place == null) continue;
    for (const f of e.field) {
      if (f.entry === e.entry || f.place == null) continue;
      const k = norm(f.entry);
      let r = map.get(k);
      if (!r) { r = {key: k, name: f.entry, met: 0, above: 0, below: 0, tied: 0, gapSum: 0, last: "", list: []}; map.set(k, r); }
      r.met++;
      if (f.place < e.place) r.above++; else if (f.place > e.place) r.below++; else r.tied++;
      r.gapSum += e.place - f.place;  // positive: that couple finished this many places ahead
      if (e.date && e.date > r.last) r.last = e.date;
      r.list.push({e, theirs: f.place});
    }
  }
  return [...map.values()].map((r) => ({...r, abovePct: 100 * r.above / r.met, belowPct: 100 * r.below / r.met, gap: r.gapSum / r.met}));
}
function gapText(g) {
  if (Math.abs(g) < 0.05) return "even";
  return `${Math.abs(g).toFixed(1)} ${g > 0 ? "ahead" : "behind"}`;
}
const RIV_SORTS = [
  ["above", -1, "Most often placed above"], ["below", -1, "Most often placed below"],
  ["abovePct", -1, "Highest share placed above"], ["belowPct", -1, "Highest share placed below"],
  ["met", -1, "Most meetings"], ["gap", -1, "Furthest ahead on average"], ["gap", 1, "Furthest behind on average"],
  ["last", -1, "Most recently met"], ["name", 1, "A to Z"],
];
$("rivSort").innerHTML = RIV_SORTS.map(([k, d, l]) => `<option value="${k}:${d}">${l}</option>`).join("");

function renderRivals(evs) {
  // Style tabs: All styles, then each style this dancer has events in (most events first)
  const counts = new Map();
  for (const e of evs) counts.set(e.style, (counts.get(e.style) || 0) + 1);
  const styles = [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([st]) => st);
  if (state.rivStyle && !counts.has(state.rivStyle)) state.rivStyle = "";
  $("rivStyles").innerHTML = [["", `All styles (${evs.length})`], ...styles.map((st) => [st, `${st} (${counts.get(st)})`])]
    .map(([k, l]) => `<button type="button" data-k="${esc(k)}" aria-pressed="${state.rivStyle === k}">${esc(l)}</button>`).join("");
  let scoped = state.rivStyle ? evs.filter((e) => e.style === state.rivStyle) : evs;
  if ($("rivSingle").checked) scoped = scoped.filter((e) => (e.dances || []).length === 1);

  // Dance tabs: dances found in the events above, in the usual order
  const DANCE_ORDER = ["Waltz", "Tango", "Viennese Waltz", "Foxtrot", "Quickstep", "Samba", "Cha Cha", "Rumba", "Paso Doble", "Jive",
    "Swing", "Bolero", "Mambo", "West Coast Swing", "Hustle", "Salsa", "Bachata", "Merengue", "Argentine Tango", "Nightclub Two-Step", "Polka", "Peabody"];
  const dCounts = new Map();
  for (const e of scoped) for (const d of e.dances || []) dCounts.set(d, (dCounts.get(d) || 0) + 1);
  const dances = [...dCounts.keys()].sort((a, b) => DANCE_ORDER.indexOf(a) - DANCE_ORDER.indexOf(b));
  if (state.rivDance && !dCounts.has(state.rivDance)) state.rivDance = "";
  $("rivDances").innerHTML = [["", `All dances (${scoped.length})`], ...dances.map((d) => [d, `${d} (${dCounts.get(d)})`])]
    .map(([k, l]) => `<button type="button" data-k="${esc(k)}" aria-pressed="${state.rivDance === k}">${esc(l)}</button>`).join("");
  if (state.rivDance) scoped = scoped.filter((e) => (e.dances || []).includes(state.rivDance));

  const min = +$("rivMin").value, q = norm($("rivSearch").value);
  let rows = rivalsData(scoped).filter((r) => r.met >= min && (!q || r.key.includes(q)));
  const {key, dir} = state.rivSort;
  rows.sort((a, b) => cmp(a, b, key, dir) || b.met - a.met || a.name.localeCompare(b.name));
  $("rivSort").value = `${key}:${dir}`;
  const who = esc(state.data.name || "this dancer");
  const scope = [state.rivDance, state.rivStyle].filter(Boolean).join(", ");
  const multiNote = state.rivDance && !$("rivSingle").checked ? " Multi-dance events count toward each of their dances, using the overall placement." : "";
  $("rivNote").innerHTML = `Opposing couples ${who} has met${scope ? ` in ${esc(scope)}` : ""}, and how often each finished ahead or behind. A partnership counts as its own couple. Click a row to see the events.${multiNote}`;

  const cols = [["name", "Couple"], ["met", "Met", 1], ["above", "Placed above", 1], ["below", "Placed below", 1], ["tied", "Tied", 1],
                ["abovePct", "Above %", 1], ["gap", "Typical gap", 1], ["last", "Last met", 1]];
  const shown = applyLimit(rows, "rivals");
  renderFoot("rivals", shown.length, rows.length, "couples");
  let body = shown.map((r) => {
    const open = state.rivOpen === r.key;
    let tr = `<tr class="click" data-k="${esc(r.key)}" aria-expanded="${open}"><td>${esc(r.name)}</td><td class="num">${r.met}</td>` +
      `<td class="num${r.above ? " l" : ""}">${r.above}</td><td class="num${r.below ? " w" : ""}">${r.below}</td><td class="num">${r.tied}</td>` +
      `<td class="num">${pct(r.abovePct)}</td><td class="num">${gapText(r.gap)}</td><td class="num">${r.last ? esc(fmtDate(r.last)) : "–"}</td></tr>`;
    if (open) {
      tr += `<tr class="detail"><td colspan="8"><ul>${r.list.map(({e, theirs}) => {
        const res = theirs < e.place ? `<span class="l">placed above</span>` : theirs > e.place ? `<span class="w">placed below</span>` : "tied";
        return `<li>${esc(e.comp)}, ${esc(e.event)}: ${res} (they were ${theirs}, ${who} was ${e.place})</li>`;
      }).join("")}</ul></td></tr>`;
    }
    return tr;
  }).join("");
  if (!shown.length) body = `<tr><td colspan="8">No couples with at least ${min} meeting${min === 1 ? "" : "s"}${scope ? " in " + esc(scope) : ""}. Lower the minimum, clear the search, or pick another tab.</td></tr>`;
  $("rivTable").innerHTML = `<table><thead>${sortHeader(cols, state.rivSort, "r")}</thead><tbody>${body}</tbody></table>`;
}
$("rivStyles").addEventListener("click", (ev) => {
  const b = ev.target.closest("button[data-k]");
  if (!b) return;
  state.rivStyle = b.dataset.k; state.rivOpen = null; renderRivals(filtered());
});
$("rivDances").addEventListener("click", (ev) => {
  const b = ev.target.closest("button[data-k]");
  if (!b) return;
  state.rivDance = b.dataset.k; state.rivOpen = null; renderRivals(filtered());
});
$("rivSingle").addEventListener("change", () => { state.rivOpen = null; renderRivals(filtered()); });
$("rivSort").addEventListener("change", () => {
  const [k, d] = $("rivSort").value.split(":");
  state.rivSort = {key: k, dir: Number(d)}; renderRivals(filtered());
});
$("rivTable").addEventListener("click", (ev) => {
  const th = ev.target.closest("th[data-r]");
  if (th) {
    const k = th.dataset.r, cur = state.rivSort;
    state.rivSort = {key: k, dir: cur.key === k ? -cur.dir : (k === "name" ? 1 : -1)};
    return renderRivals(filtered());
  }
  const tr = ev.target.closest("tr.click");
  if (tr) { state.rivOpen = state.rivOpen === tr.dataset.k ? null : tr.dataset.k; renderRivals(filtered()); }
});
$("rivSearch").addEventListener("input", () => renderRivals(filtered()));
$("rivMin").addEventListener("change", () => renderRivals(filtered()));

function renderEvents(evs) {
  const cols = [["order", "Date", 0], ["comp", "Comp"], ["event", "Event"], ["partner", "Partner"], ["place", "Place", 1], ["entries", "Of", 1], ["percentile", "Field beaten", 1]];
  const {key, dir} = state.evSort;
  const rows = evs.map((e) => ({...e, percentile: fieldBeaten(e)})).sort((a, b) => cmp(a, b, key, dir) || a.order - b.order);
  $("evNote").textContent = `${evs.length} event${evs.length === 1 ? "" : "s"}. Click a heading to sort; event names link to the official results.`;
  const shownE = applyLimit(rows, "events");
  renderFoot("events", shownE.length, rows.length, "events");
  $("evTable").innerHTML = `<table><thead>${sortHeader(cols, state.evSort, "e")}</thead><tbody>` +
    shownE.map((e) => `<tr data-order="${e.order}"><td>${esc(e.date ? fmtDate(e.date) : "–")}</td><td>${esc(e.comp)}</td><td class="wrap-ok"><a href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.event)}</a></td><td>${esc(e.partner || "(solo)")}</td><td class="num">${e.place ?? "–"}${e.made_final ? "" : " <span class=\"hint\">(out)</span>"}</td><td class="num">${e.entries}</td><td class="num">${pct(e.percentile)}</td></tr>`).join("") +
    `</tbody></table>`;
}
$("evTable").addEventListener("click", (ev) => {
  const th = ev.target.closest("th[data-e]");
  if (!th) return;
  const k = th.dataset.e, s = state.evSort;
  state.evSort = {key: k, dir: s.key === k ? -s.dir : (["place", "order", "comp", "event", "partner"].includes(k) ? 1 : -1)};
  renderEvents(filtered());
});
</script>
</body>
</html>
"""


class ExclusiveServer(ThreadingHTTPServer):
    """On Windows, Python's default lets two programs share a port; claim it exclusively instead."""
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows only
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def answers_as_us(url: str) -> bool:
    for _ in range(10):
        try:
            with urllib.request.urlopen(url + "api/ping", timeout=2) as r:
                return json.load(r).get("instance") == INSTANCE
        except Exception:
            time.sleep(0.2)
    return False


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Ballroom Stats Analyzer: a website for ballroomcompexpress.com results")
    ap.add_argument("--public", action="store_true",
                    help="Run as a public website: no browser, one search at a time, per-visitor limits, "
                         "dancer ID required (see --allow-name-search)")
    ap.add_argument("--host", default="127.0.0.1",
                    help="Address to listen on (default 127.0.0.1; keep this behind nginx)")
    ap.add_argument("--port", type=int, default=None, help="Port to listen on (default 8765)")
    ap.add_argument("--cache", default=str(HERE / "bce_cache"), help="Folder for saved pages")
    ap.add_argument("--delay", type=float, default=None,
                    help="Seconds between requests to Ballroom Comp Express (default 0.4, or 0.6 with --public)")
    ap.add_argument("--allow-name-search", action="store_true",
                    help="With --public, also allow name-only searches (these read every event on the site)")
    ap.add_argument("--no-background-cache", action="store_true",
                    help="Disable historical population and weekly results refresh")
    ap.add_argument("--background-delay", type=float, default=2.0,
                    help="Minimum seconds between background downloads (default 2; shared foreground limit also applies)")
    ap.add_argument("--max-per-hour", type=int, default=20, help="With --public, searches per visitor per hour")
    ap.add_argument("--max-total-per-hour", type=int, default=200,
                    help="With --public, searches the whole site will start per hour, from everyone")
    ap.add_argument("--visitor-id", choices=["ip", "ip+browser"], default="ip",
                    help="How to tell visitors apart for the limits: by address (default), or by address plus a "
                         "random ID kept in each browser (use this with Docker Desktop, which can hide addresses)")
    ap.add_argument("--trust-proxy", default="local",
                    help="Who may pass along the visitor's address (nginx's X-Real-IP): 'local' (nginx on this "
                         "machine, the default), 'private' (nginx reaching a Docker container), or "
                         "comma-separated addresses/ranges")
    args = ap.parse_args()
    try:
        trusted = parse_proxies(args.trust_proxy)
    except ValueError as exc:
        sys.exit(f"--trust-proxy: {exc}")

    global FETCHER, CACHE_MAINTAINER
    delay = args.delay if args.delay is not None else (0.6 if args.public else 0.4)
    FETCHER = core.Fetcher(args.cache, delay=delay, refresh=False)
    # threading.Thread(target=PARTNER_LEADERBOARD.load_cache, args=(args.cache,), daemon=True).start()

    if args.public:
        CONFIG.update(public=True, require_id=not args.allow_name_search,
                      max_per_hour=args.max_per_hour, trusted_proxies=trusted,
                      max_total_per_hour=args.max_total_per_hour, visitor_id=args.visitor_id)
        if not args.no_background_cache:
            from bce_cache import CacheMaintainer
            CACHE_MAINTAINER = CacheMaintainer(FETCHER,
                busy=lambda: SEARCH_ACTIVE.is_set() or LOOKUP_ACTIVE.is_set(), delay=args.background_delay, log=log)
            threading.Thread(target=CACHE_MAINTAINER.run, daemon=True).start()

        def stop(*_):  # "docker stop" and systemd send SIGTERM; shut down cleanly instead of waiting to be killed
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, stop)
        port = args.port or 8765
        try:
            server = ThreadingHTTPServer((args.host, port), Handler)
        except OSError as exc:
            sys.exit(f"Couldn't listen on {args.host}:{port} ({exc}). Is another copy already running?")
        server.daemon_threads = True
        log(f"Ballroom Stats Analyzer (public mode) listening on http://{args.host}:{port}/  cache: {Path(args.cache).resolve()}")
        log("Dancer ID required for searches." if CONFIG["require_id"] else "Name-only searches are allowed.")
        log(f"Trusting visitor addresses passed along by: {args.trust_proxy}; telling visitors apart by: {args.visitor_id}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            log("Stopped.")
        return

    # On your own computer: find a free port, confirm it's really us answering, open the browser
    server = url = None
    ports = [args.port] if args.port else [8765, 8766, 8767, 8780, 8790, 18765, 28765]
    for port in ports:
        try:
            candidate = ExclusiveServer((args.host, port), Handler)
        except OSError:
            continue
        threading.Thread(target=candidate.serve_forever, daemon=True).start()
        test_url = f"http://127.0.0.1:{port}/"
        if answers_as_us(test_url):
            server, url = candidate, test_url
            break
        candidate.shutdown()
        candidate.server_close()
        print(f"Port {port} is taken by another program; trying another.")
    if server is None:
        sys.exit("Couldn't start the dashboard: every port tried is in use or blocked. "
                 "Try closing other local servers, or restart your computer, then run this again.")
    print()
    print(f"  Ballroom Stats Analyzer is running. Open this address in your browser:  {url}")
    print("  (The browser tab will be titled \"Ballroom Stats Analyzer\".)")
    print()
    print("Leave this window open while you use the site. Press Ctrl+C to stop.")
    webbrowser.open(url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.shutdown()
        print("\nStopped.")


if __name__ == "__main__":
    main()
