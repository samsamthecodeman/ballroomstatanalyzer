# Ballroom Stats Analyzer

Explore your ballroom competition history, track progress, and compare results with other dancers.

**[Visit Ballroom Stats Analyzer →](https://bsa.sam-moran.com)**

Ballroom Stats Analyzer uses results from [Ballroom Comp Express](https://ballroomcompexpress.com/) and [O2CM](https://results.o2cm.com/) to turn a dancer's competition history into an interactive dashboard. This repository contains the source code for the website and its maintenance tools.

## Features

- **Individual or couple analysis:** choose Individual for a dancer’s full history, or Couple to analyze only two dancers’ shared entries across BCE and O2CM. Type at least three characters to choose a cached partnership and fill both names, or enter names manually. The second field also suggests known partners. Couple mode starts head-to-head comparisons by opposing couple; mixed-event roles and YCN points remain specific to the first dancer.
- **Competition history:** view placements, wins, podiums, finals, average placement, and percentage of the field beaten.
- **Performance trends:** track results over time and compare statistics by category, style, dance, level, division, and partner.
- **Matchup analysis:** explore head-to-head comparisons by dancer or couple, plus opponents placed above and below you.
- **Compare dancers:** add multiple dancers for side-by-side statistics and a list of shared events with wins, losses, ties, and entries danced together.
- **Upcoming competitions:** paste a public BCE heat-sheet link to find familiar opponents in your entered rounds, with past meetings by dancer and exact partnership.
- **Leaderboard:** rank published names by total wins at verified Texas or U.S. national venues, with year, category, style, level, name, and uncontested-event filters.
- **Competition scores:** browse cached BCE and O2CM competitions, dancer results, and event placements, finals status, and rounds danced, with links to official judges' marks.
- **Judging categories:** distinguish couple-judged, leader-judged, follower-judged, and solo events.
- **Filters:** narrow results by category, style, level, division, and partner, and optionally exclude uncontested events.
- **YCN points estimates:** review role-specific calculations, event-by-event explanations, and interpretations of ambiguous level names.
- **Exports:** download event results as CSV or a formatted PDF report.

## Getting started

1. Open **[bsa.sam-moran.com](https://bsa.sam-moran.com)**.
2. Search your name or dancer ID; the website always combines BCE and O2CM.
3. Enter your full name or Ballroom Comp Express dancer ID in the **Name or dancer ID** box. Ballroom Comp Express suggestions include locations and IDs to distinguish people with the same name. To find an ID, open a dancer's Ballroom Comp Express results and copy the number after `aid=` in the URL.
4. Select **Analyze**, then explore the charts, tables, and filters.

The website resolves selected names to dancer IDs to keep analyses focused and reduce traffic to Ballroom Comp Express. A shared results index speeds up repeat searches. A first-time dancer lookup or results not yet cached may still need downloads. If someone else is running an analysis, your search may wait in the queue.

Positive performance metrics such as wins, podiums, finals, win rates, and field beaten use green in both themes. Age group is not a breakdown or sorting option.

## Understanding your results

### Leaderboard and competition scores

The website always combines **BCE and O2CM**; there are no provider toggles. The leaderboard ranks total wins at verified **Texas** or **U.S. national** venues, rather than by dancer residence. **Couple-judged** is the default category. Styles include separate **Social** and **Country** options. The Style menu supports multiple checked styles (any selected style matches); no checked styles includes all styles. The table omits provider columns while retaining the provider selection controls. It supports year, judging-category, style, level, name, and uncontested-event filters. Equal win totals share a rank. Couple-judged wins credit both partners; mixed leader/follower events credit only the judged dancer. O2CM events with unverified mixed roles and team events are excluded. Published names are grouped, not verified identities, so identical names may refer to different people.

Coverage is limited to cached results with verified venue metadata. BCE venue states come from its competition search. O2CM venues can be supplied in the shared venue cache; a small source-linked event-year registry supplies verified starting points. Unknown venues are excluded and counted in the coverage notice. This is an unofficial ranking, not comprehensive coverage of every U.S. competition. Exact cross-provider result mirrors count once; differently titled duplicates may remain separate.

In **Competition scores**, enter a dancer name and select **Load my competitions**, then choose from competitions found in that dancer’s result history. An unrestricted completed analysis is reused by default. Newly discovered competitions appear even before the general catalog refreshes. All result entries from every competition are shown immediately, with dates and competition names. Select a specific competition or event to narrow the list, or return to **All my competitions**. The table includes partners, placements, finals status, and rounds danced, without a Source column. Official result links remain available. Multiple same-name entries are shown with an ambiguity warning. Alternatively, choose one event to inspect the whole field. A unique cross-provider competition pair with the same published name and date is grouped under Unified data. Official links show judges' marks and subsequent corrections. These sections use the cache and do not crawl other dancers' histories while browsing.

### Comparing dancers

After analyzing your own results, open **Compare dancers**, enter another dancer's name or BCE ID, and select **Add dancer**. Repeat to compare yourself with three or more dancers in the same table. Each dancer has an expandable head-to-head section and a remove button. Choose a suggestion when multiple people share a name. The comparison uses the combined result history, the dashboard filters, and the selected field-beaten calculation. Overall statistics can cover different competitions and dates; shared-event outcomes require matching provider, competition, and event IDs. Entries danced together are shown separately from wins, losses, and ties. Stopping a search keeps the dancers already loaded. Remove individual dancers or use **Clear all dancers** without losing the primary dashboard. Exports contain the primary dancer's results.

### Upcoming competitions

Analyze yourself, then paste a public BCE heat-sheet or schedule link into **Upcoming competition** and select **Check opponents**. Your registered rounds are joined to published entrants. The report shows prior meetings, wins/losses/ties, past entries together, and up to ten recent shared-event results per dancer. Exact-partnership statistics are separate from a dancer's history with any partner. Conditional callbacks are excluded, and revised published times are used. The report flags unpublished or ambiguous data and past session dates; verify the official schedule before competing.

This feature uses all events in your completed analysis, regardless of dashboard filters, and excludes results from the competition being checked. It does not download every opponent's full history or predict results. Ambiguous registered names and multiple same-name historical entries are not silently combined. Public schedule pages are cached for 15 minutes, independently of the historical-results refresh policy. You do not need to provide BCE credentials. Exports contain historical results.

### O2CM results

Enter the full name used at registration in the shared search box; O2CM is always included alongside BCE. For compound surnames, use `Last name, First name`. A Ballroom Comp Express ID can also resolve the name to search on O2CM; it is not an O2CM identifier. Optional competition codes, such as `mit26`, and the partner filter can narrow a search.

**Unified data**, selected by default, combines exact-name matches across both providers. Whenever multiple profiles match, shared partnerships are used to resolve the identity. If there is no unique partnership-supported match, choose a Ballroom Comp Express suggestion or enter a dancer ID. In ambiguous searches, only O2CM events with verified shared partners are included. O2CM's public name-history search can include other people with the same name and may omit additional competitor records for double-entered dancers, so review the returned competitions and partners.

Each event retains its source and scoresheet link. Identical cross-source records are counted once; differently titled versions of the same event may still appear separately. Use Competition scores to narrow results to an individual competition. If one provider is unavailable, Unified data keeps the other provider's results and displays a warning.

O2CM results include the published overall placements, tied places, field sizes, finals, and source scoresheet links. Cached competition pages are shared across name searches; known histories participate in weekly refresh, recent competitions are refreshed, and older competitions are retained after a final successful refresh at the 30-day cutoff. The date is the date published in O2CM's dancer history. Initial searches download only competitions in the requested history; a full O2CM historical crawl is not enabled.

Leader/follower roles are unverified in this importer, so O2CM results do not currently contribute to YCN points. Ambiguous mixed/proficiency events are marked **Unclassified**, rather than guessed. CSV and PDF exports identify O2CM as the source. If O2CM is unavailable from the hosting server, searches report the problem or use an existing successful cache with a warning; failures do not replace valid cached data.

### Filters and uncontested events

Use the filters to focus on a particular category, style, level, division, or partner.

**Exclude uncontested events** removes events with exactly one entry, whether that entry is a couple or an individual. Events with unknown entry counts remain visible. This setting applies to statistics, charts, event lists, exports, and the YCN section.

**Exclude top-3 finishes in 3-couple events** removes events where you placed first, second, or third out of exactly three couples. It applies to statistics, charts, event lists, exports, and the YCN section. Solo events, unknown entry counts, and unknown placements remain included. Both exclusion checkboxes are optional and can be reset with **Clear filters**.

The other dashboard filters do not affect YCN points, so filtering the main results does not hide relevant events from the points calculation.

### Dance breakdowns

In **Where they're strongest → Dance**, compare event count, wins, finals rate, average placement, and field beaten for each dance.

A multi-dance event contributes its overall placement to each listed dance. These are event-level placements rather than separate marks for each dance.

### YCN points

The YCN section estimates points using the rules implemented in the application. It separates leader and follower roles, explains how individual events counted, and lets you adjust ambiguous level names.

Treat these totals as a reference when reviewing your competition history. They are not an official eligibility determination. LilacDB totals are not imported automatically and may include competitions outside Ballroom Comp Express.

## Exporting results

After an analysis completes, select **Export CSV** or **Export PDF** beneath the dancer's name.

| Format | Contents |
| --- | --- |
| CSV | Detailed event rows, including competition, judging category, style, level, partner, role, placement, entry count, and source URL |
| PDF | Summary statistics and a paginated event table, with first-place results highlighted in green |

Both formats include **all events matching your current filters**, regardless of the on-screen row limit. The PDF does not include the dashboard's YCN calculations or opponent-comparison tables.

Exports use the completed analysis and make no additional requests to Ballroom Comp Express. Completed results expire from server memory after approximately 30 minutes; rerun the search if an export reports that the results expired.

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

Dancer membership refreshes also check published competitions from the past 30 days directly, because BCE's dancer overview can lag behind competition-specific results. Previously verified competitions are preserved when omitted from that overview. Manual competition refreshes update known dancer listings too; normal repeat searches continue to use the shared index without these additional checks.

Changing filters and exporting completed results make no upstream requests. Name suggestions use Ballroom Comp Express's public dancer search and cache successful query responses for a week.

The website currently runs one analysis at a time, with other searches queued. Its configured defaults allow 20 search starts per visitor per hour and 200 across the website. Outbound request starts are spaced at least 0.6 seconds apart across download workers. These limits count searches, not the number of pages downloaded, and an uncached search can still read many pages.

Please avoid repeatedly starting the same analysis and use the cached results and exports where possible.

## Report an issue

Found an incorrect classification, missing result, or another problem? Open an [issue](https://github.com/samsamthecodeman/ballroomstatanalyzer/issues) with:

- The dancer ID and relevant Ballroom Comp Express competition/event URLs or IDs.
- What the website displayed and what you expected instead.
- Steps to reproduce the issue and, if useful, a screenshot.

For classification problems, include the full event title and whether the couple, leader, or follower was judged. Do not include private credentials or API tokens.

## Limitations

- Coverage depends on available Ballroom Comp Express results and the pages included in the analysis.
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
python -m unittest -v test_event_category test_exports test_partners test_cache test_o2cm test_autodeploy
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
bce_o2cm.py            O2CM name-history and competition-results importer
bce_sources.py         Unified search and partnership-based source matching
bce_upcoming.py        Public heat sheets and upcoming-opponent history
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
