# Ballroom Stats Analyzer

Explore your ballroom competition history, track progress, and compare results with other dancers.

**[Visit Ballroom Stats Analyzer →](https://bsa.sam-moran.com)**

Ballroom Stats Analyzer uses results from [Ballroom Comp Express](https://ballroomcompexpress.com/) to turn a dancer's competition history into an interactive dashboard. This repository contains the source code for the website and its maintenance tools.

## Features

- **Competition history:** view placements, wins, podiums, finals, average placement, and percentage of the field beaten.
- **Performance trends:** track results over time and compare statistics by category, style, dance, level, division, partner, and age group.
- **Matchup analysis:** explore head-to-head comparisons by dancer or couple, plus opponents placed above and below you.
- **Judging categories:** distinguish couple-judged, leader-judged, follower-judged, and solo events.
- **Filters:** narrow results by category, style, level, division, and partner, and optionally exclude uncontested events.
- **YCN points estimates:** review role-specific calculations, event-by-event explanations, and interpretations of ambiguous level names.
- **Exports:** download event results as CSV or a formatted PDF report.

## Getting started

1. Open **[bsa.sam-moran.com](https://bsa.sam-moran.com)**.
2. Start typing your name and choose the matching dancer from the suggestions. Locations and IDs help distinguish people with the same name.
3. The dancer ID fills automatically. You can also enter an ID directly: on Comp Express, select a dancer in a competition's results and copy the number after `aid=` in the URL.
4. Select **Analyze**, then explore the charts, tables, and filters.

The website resolves selected names to dancer IDs to keep analyses focused and reduce traffic to Comp Express. A shared results index speeds up repeat searches. A first-time dancer lookup or results not yet cached may still need downloads. If someone else is running an analysis, your search may wait in the queue.

## Understanding your results

### Filters and uncontested events

Use the filters to focus on a particular category, style, level, division, or partner.

**Exclude uncontested events** removes events with exactly one entry, whether that entry is a couple or an individual. Events with unknown entry counts remain visible. This setting applies to statistics, charts, event lists, exports, and the YCN section.

The other dashboard filters do not affect YCN points, so filtering the main results does not hide relevant events from the points calculation.

### Dance breakdowns

In **Where they're strongest → Dance**, compare event count, wins, finals rate, average placement, and field beaten for each dance.

A multi-dance event contributes its overall placement to each listed dance. These are event-level placements rather than separate marks for each dance.

### YCN points

The YCN section estimates points using the rules implemented in the application. It separates leader and follower roles, explains how individual events counted, and lets you adjust ambiguous level names.

Treat these totals as a reference when reviewing your competition history. They are not an official eligibility determination. LilacDB totals are not imported automatically and may include competitions outside Comp Express.

## Exporting results

After an analysis completes, select **Export CSV** or **Export PDF** beneath the dancer's name.

| Format | Contents |
| --- | --- |
| CSV | Detailed event rows, including competition, judging category, style, level, partner, role, placement, entry count, and source URL |
| PDF | Summary statistics and a paginated event table, with first-place results highlighted in green |

Both formats include **all events matching your current filters**, regardless of the on-screen row limit. The PDF does not include the dashboard's YCN calculations or opponent-comparison tables.

Exports use the completed analysis and make no additional requests to Comp Express. Completed results expire from server memory after approximately 30 minutes; rerun the search if an export reports that the results expired.

## Data freshness and responsible use

The website shares a persistent, indexed results database across searches. A resumable background job populates historical competition results and checks for updates **Saturday at 11:59 p.m. Central**. It yields to visitor analyses and name lookups, with background downloads spaced at least two seconds apart in addition to the shared request limiter.

The initial historical population can take hours or longer. Searches continue working while it fills, fetching missing pages when needed. Known dancer memberships and parsed event results are reused, so repeat analyses can run entirely from the local index. A previously unseen dancer may still require an ID-specific lookup to identify their events accurately.

| Cached data | Refresh policy |
| --- | --- |
| Competition indexes and dancer overview pages | Weekly, or on demand when not yet cached |
| Competitions ending within the last 30 days | Weekly refresh of listings and event results |
| Competitions reaching 30 days old | One final refresh, then retained indefinitely |
| Competitions with unknown dates | Continue checking weekly |

Dates use the end of a multi-day competition. Corrections made after the 30-day window can be refreshed manually by the maintainer. Failed refreshes preserve the last successful results, and background population resumes from saved progress after a restart. Missed weekly runs are picked up when the website resumes.

Changing filters and exporting completed results make no upstream requests. Name suggestions use Comp Express's public dancer search and cache successful query responses for a week.

The website currently runs one analysis at a time, with other searches queued. Its configured defaults allow 20 search starts per visitor per hour and 200 across the website. Outbound request starts are spaced at least 0.6 seconds apart across download workers. These limits count searches, not the number of pages downloaded, and an uncached search can still read many pages.

Please avoid repeatedly starting the same analysis and use the cached results and exports where possible.

## Report an issue

Found an incorrect classification, missing result, or another problem? Open an [issue](https://github.com/samsamthecodeman/ballroomstatanalyzer/issues) with:

- The dancer ID and relevant Comp Express competition/event URLs or IDs.
- What the website displayed and what you expected instead.
- Steps to reproduce the issue and, if useful, a screenshot.

For classification problems, include the full event title and whether the couple, leader, or follower was judged. Do not include private credentials or API tokens.

## Limitations

- Coverage depends on available Comp Express results and the pages included in the analysis.
- Judging categories, roles, and levels may require interpretation, especially on older event layouts. Source-format changes can affect parsing.
- Name-based comparisons may conflate different people with the same name or separate spelling variants.
- Cached event pages may not reflect later source corrections.
- Website restarts interrupt active searches. Availability depends on the maintained hosting infrastructure and the upstream results website.

## Development and contributing

The website uses Python, a lightweight HTTP server, vanilla JavaScript, and ReportLab for PDF generation. The maintained Docker image uses Python 3.12.

For code contributions, work on a branch and run the relevant checks before opening a pull request. In your development environment:

```bash
python -m pip install -r requirements.txt
python -m pip install pypdf
python -m unittest -v test_event_category test_exports test_partners test_cache test_autodeploy
```

With Node.js installed, run the dashboard logic checks:

```bash
node test_filters.cjs
node test_lookup.cjs
```

The tests cover judging categories, exports, filters, dance breakdowns, and partner counting. Windows deployment tests use disposable local Git repositories and a fake Docker executable; they skip on other platforms and do not change the live website.

### Source layout

```text
bce_analyze.py         Fetching, parsing, classification, and analysis
bce_web.py             HTTP server and embedded dashboard HTML/CSS/JavaScript
bce_export.py          CSV and PDF generation
bce_store.py           Shared SQLite results index and dancer search plans
bce_cache.py           Historical population and weekly results maintenance
bce_partners.py        Preserved partner leaderboard implementation (disabled)
Dockerfile            Website application image
docker-compose.yml    Hosting service configuration
nginx/                Reverse-proxy configuration
ddns/                 DNS maintenance utility
scripts/              Windows deployment and scheduling tools
test_*.py             Python regression and integration tests
test_filters.cjs      JavaScript dashboard checks
```

### Maintainer operations

Deployment files and the [Windows operations guide](SETUP-WINDOWS.md) document the infrastructure used to maintain the hosted website. They contain deployment-specific configuration.

The production updater checks GitHub's `main` branch each morning at **8:00 a.m. Central**, builds changed code, and replaces the app container after checking its health. It skips uncommitted changes, preserves the local configuration and cached results, and records deployment logs in `tmp/auto-deploy/`.

Credentials, caches, generated reports, and deployment logs are excluded from Git. The optional "Most Dance Partners" calculation remains in the source with its activation hooks commented out.

Inspect cache progress on the hosting machine:

```bash
docker compose exec -T app python bce_cache.py
```

Request a fresh copy of a competition, including an older frozen competition:

```bash
docker compose exec -T app python bce_cache.py --refresh 173
```

The running background worker processes the request when available. `--no-background-cache` disables automatic population and weekly refresh; `--background-delay` controls its extra pacing. The SQLite database and HTML pages share the persistent cache volume.

## License

This repository does not currently include a `LICENSE` file.
