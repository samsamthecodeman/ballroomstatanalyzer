# Ballroom Stats Analyzer

Explore a dancer's competition history using results from [Ballroom Comp Express](https://ballroomcompexpress.com/). Search by dancer ID, compare placements across competitions, analyze matchups, and export results from a browser dashboard or command-line tool.

Built with Python, a lightweight HTTP server, and vanilla JavaScript. Run it locally or deploy it with Docker behind an HTTPS reverse proxy.

## Features

- **Competition history:** event placements, wins, podiums, finals, average placement, and percentage of the field beaten.
- **Performance trends:** competition-by-competition charts and breakdowns by category, style, dance, level, division, partner, and age group.
- **Matchup analysis:** head-to-head comparisons by dancer or couple, plus opponents placed above and below you.
- **Judging categories:** separate couple-judged, leader-judged, follower-judged, and solo events.
- **Filters:** narrow results by category, style, level, division, and partner; optionally exclude uncontested events with exactly one entry.
- **YCN points estimates:** role-specific calculations, event-by-event explanations, and configurable interpretations of ambiguous level names.
- **Downloads:** CSV event data and PDF reports with summary statistics and paginated event tables.
- **Persistent caching:** reuse previously downloaded results across searches and Docker container updates.
- **Public hosting controls:** queued searches, request pacing, dancer-ID requirements, and per-visitor search limits.
- **Windows deployment:** optional daily updates from GitHub through Task Scheduler.

## Quick start

### Run with Python

Python **3.12** is recommended; the Docker image uses Python 3.12. Git is required to clone the repository.

```bash
git clone https://github.com/samsamthecodeman/ballroomstatanalyzer.git
cd ballroomstatanalyzer
python -m venv .venv
```

Activate the virtual environment:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

Install dependencies and start the dashboard:

```bash
python -m pip install -r requirements.txt
python bce_web.py
```

The app opens a browser automatically. Its default address is **http://localhost:8765**; local mode tries another port if that one is occupied. Stop the server with **Ctrl+C**.

### Run with Docker

With Docker Desktop or Docker Engine running:

```bash
docker build -t ballroom-stats-analyzer .
docker run -d --name ballroom-stats-analyzer -p 127.0.0.1:8765:8765 -v ballroom-stats-cache:/data/cache ballroom-stats-analyzer
```

Open **http://localhost:8765**. This binds access to the host's loopback interface and stores downloaded pages in a named Docker volume. The image runs in public mode, so searches require a dancer ID.

If port 8765 is occupied, use `-p 127.0.0.1:8766:8765` and open port 8766 instead.

## Using the dashboard

1. Find your dancer ID on Comp Express: open a competition's results, select your name in the dancer selector, and copy the number after `aid=` in the URL.
2. Enter the ID in the dashboard. You can also supply a name to help identify the dancer.
3. Run the analysis, then use the filters and section tabs to explore the results.
4. Choose **Export CSV** or **Export PDF** beneath the dancer's name to download matching events.

Exports include **all events matching the active filters**, regardless of the on-screen row limit. The PDF contains summary statistics and an event table; it does not include the dashboard's YCN calculations or opponent-comparison tables. Exporting does not fetch more pages from Comp Express. Completed search results expire from server memory after approximately 30 minutes; rerun the search if an export reports that the results expired.

**Exclude uncontested events** removes events with exactly one entry, whether that entry is a couple or an individual. Events with unknown entry counts remain visible. The setting also applies to exports and the YCN section; the other dashboard filters do not affect YCN points.

In the **Dance** breakdown, a multi-dance event contributes its overall placement to each listed dance. These are event-level placements, not separate marks for each dance.

## Command-line analysis

Search by dancer ID:

```bash
python bce_analyze.py --aid 10062
```

Limit the competitions and write report files:

```bash
python bce_analyze.py --aid 10062 --cids 150-250 --out output/report
```

The output directory contains `events.csv`, `head_to_head.csv`, and `summary.json`. The CLI also supports partner filtering, approximate name matching, and an optional chart with `--plot` (requires `matplotlib`).

See all available options:

```bash
python bce_analyze.py --help
python bce_web.py --help
```

Prefer dancer IDs. A name-only search can inspect every event across the site and take hours on an empty cache. Public mode disables name-only searches unless explicitly enabled with `--allow-name-search`.

## Hosting and configuration

See [SETUP-WINDOWS.md](SETUP-WINDOWS.md) for the Windows hosting walkthrough. The supplied Compose configuration contains four services:

| Service | Purpose |
| --- | --- |
| `app` | Dashboard and analysis server, listening on container port 8765 |
| `nginx` | Optional bundled HTTPS reverse proxy on ports 80 and 443 |
| `certbot` | Issues and renews certificates using Cloudflare DNS validation |
| `ddns` | Optional DNS updater, enabled only through the `direct-hosting` profile |

Copy `.env.example` to `.env` and supply your own values before using Compose:

```powershell
Copy-Item .env.example .env
```

| Variable | Purpose |
| --- | --- |
| `DOMAIN` | Hostname used by the bundled proxy and certificate service |
| `EMAIL` | Contact email for certificate issuance |
| `CF_API_TOKEN` | Cloudflare token for certificate validation and optional DNS updates |
| `CF_ZONE_ID` | Optional explicit Cloudflare zone ID for the DNS updater |
| `DDNS_INTERVAL` | DNS update interval in seconds; defaults to 300 |

**Deployment-specific binding:** `docker-compose.yml` currently includes `100.83.246.24:8765:8765`, the original deployment's Tailscale address. Remove that mapping or replace it with an address assigned to your own host before running Compose elsewhere. The localhost mapping can remain.

If you already use Nginx Proxy Manager or another reverse proxy, start only the app:

```bash
docker compose up -d --build --no-deps app
```

Forward to the app over **HTTP on port 8765** using an address the proxy can reach. Configure HTTPS on the public proxy. Public DNS must resolve to your public ingress; a Tailscale address alone is not reachable by visitors outside your tailnet. Leave the bundled DNS updater disabled when another service manages your public routing.

For direct hosting with the bundled proxy, review the router, DNS, and certificate steps in the Windows guide. To explicitly include the optional DNS updater:

```bash
docker compose --profile direct-hosting up -d --build
```

The bundled certificate command accepts the Let's Encrypt Subscriber Agreement during initial issuance. Keep `.env` private; it is excluded from Git along with caches, generated reports, and temporary files.

### Public-mode defaults

| Setting | Default |
| --- | --- |
| Minimum interval between outbound request starts | 0.6 seconds, shared across workers |
| Concurrent searches | 1, with other searches queued |
| Search starts per visitor | 20 per hour |
| Search starts across the application | 200 per hour |
| Search identifier | Dancer ID required |

These defaults apply when running with `--public`. Configure them with the arguments in `docker-compose.yml`, such as `--delay`, `--max-per-hour`, and `--max-total-per-hour`. Search limits count searches, not upstream pages. The local web app and CLI default to a 0.4-second request interval.

## Caching and upstream traffic

The application downloads results when a search needs them. Merely opening the dashboard, changing filters, or exporting completed results does not request additional Comp Express pages.

| Cached data | Rechecked on a search after |
| --- | --- |
| Competition indexes and dancer overview pages | 1 hour |
| Competition event-list pages | 24 hours |
| Individual event results | Kept indefinitely |

Caches live in `bce_cache/` for a normal local run and `/data/cache` in the Docker container. The named Docker volume preserves them when the app container is rebuilt. Individual event results may therefore remain stale if the source is corrected later; the CLI's `--refresh` option bypasses its cache.

First-time searches can still generate substantial traffic. At the public-mode default, continuous uncached downloads can approach 100 request starts per minute. Failed requests may be retried, and there is no separate hourly cap on upstream page requests. Coordinate public use with Comp Express and avoid repeated full-site scans.

## Updates and automatic deployment

To update an existing checkout manually:

```bash
git pull --ff-only origin main
```

If the pull succeeds, rebuild and replace the app:

```bash
docker compose up -d --build --no-deps app
docker compose ps app
```

For Windows, install the optional daily deployment task from the project folder:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Install-AutoDeploy.ps1 -At 08:00
```

It checks `origin/main` daily at **8:00 a.m. in the PC's local time zone**. The user must be signed in and Docker Desktop must be running; Task Scheduler attempts missed runs when available. The updater:

- Skips uncommitted or untracked source changes and refuses divergent history.
- Builds only when the deployed commit differs, then replaces only the app container and waits for its health check.
- Keeps the local `.env` and cached results; an app restart interrupts active searches.
- Writes logs and the last successful commit to `tmp/auto-deploy/`.
- Retries unsuccessful deployments on the next scheduled run. Failed builds preserve the running container; failed health checks can require manual recovery.

See the [automatic-update instructions](SETUP-WINDOWS.md#automatic-updates-from-github-optional) for logs, a check-only command, and how to disable the task.

## Development and tests

Install the app dependencies, then the PDF inspection dependency used by the tests:

```bash
python -m pip install -r requirements.txt
python -m pip install pypdf
python -m unittest -v test_event_category test_exports test_partners test_autodeploy
```

With Node.js installed, run the browser-logic checks:

```bash
node test_filters.cjs
```

The tests cover judging categories, CSV/PDF downloads, filter behavior, dance breakdowns, and partner counting. Windows deployment integration tests use disposable local Git repositories and a fake Docker executable; they skip on other platforms and do not change the live application.

### Project structure

```text
bce_analyze.py         Fetching, parsing, classification, analysis, and CLI
bce_web.py             HTTP server and embedded dashboard HTML/CSS/JavaScript
bce_export.py          CSV and PDF generation
bce_partners.py        Optional partner leaderboard (currently disabled)
Dockerfile            Application image
docker-compose.yml    Application and optional hosting services
nginx/                Bundled reverse-proxy configuration
ddns/                 Optional Cloudflare DNS updater
scripts/              Windows deployment and Task Scheduler installation
test_*.py             Python regression and integration tests
test_filters.cjs      JavaScript dashboard checks
SETUP-WINDOWS.md      Windows hosting and operations guide
```

The optional "Most Dance Partners" feature is preserved in source but disabled. Its import, initialization, collection, route, startup scan, and browser invocation are commented out in `bce_web.py`.

## Limitations

- Coverage depends on available Comp Express results and the pages included in a search.
- Judging categories, roles, and levels may require interpretation, especially on older event layouts. Source-format changes can affect parsing.
- YCN points are estimates based on the implemented rules and selected level mappings; they are not an official eligibility determination. LilacDB totals are not imported automatically.
- Name-based comparisons may conflate different people with the same name or separate spelling variants.
- The dashboard uses Python's built-in HTTP server. For public hosting, run it behind an HTTPS reverse proxy with the public-mode controls enabled.

## Contributing

Open an [issue](https://github.com/samsamthecodeman/ballroomstatanalyzer/issues) with a reproducible example, expected behavior, and relevant Comp Express competition/event URLs or IDs. Do not include API tokens or your `.env` file.

For changes, create a branch, add regression coverage when appropriate, run the relevant tests, and open a pull request describing the behavior and validation.

## License

This repository does not currently include a `LICENSE` file.
