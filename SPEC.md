# SPEC — Sydney Cinema Guide (v2 final, 2026-11-01)

## Problem
Finding what's on in Sydney means visiting every cinema's site in turn. Paris has
a single page for this (Paris Ciné Info); Sydney does not.

## Product (v2)
One page, two views in the header nav:
- **This week ahead** (default): today and the next 6 days, Sydney time, one heading "This week ahead".
- **All showings**: every session in the 14-day horizon, one flat list, heading "All Showings".
One row per film per view (poster, title, year · director · rating · runtime, type tag, "N sessions · M cinemas" summed over the view); expanding a row shows day tabs for the days that film has sessions and the sessions beneath, at natural height. Sort: Relevant (default), Popular, A–Z, Release date, Rating, with a reverse control. Pagination by film, 5 / 10 / 20 per page (default 5). Filters: film, director, cinema, type, date, release year, region.
Look: navy palette, gold accent, nothing boxed except the filter bar and the session box (design mocks in `design/v2/`, DECISIONS 2026-11-01). No footer.
Dropped: Retrospectives / New-this-week views, day and week grouping, the "Partial" tag and the Wednesday note, the light palette tried on 2026-10-29.

## Not in v2
Accounts, saved lists, notifications, reviews, non-Sydney cities, mobile app.
Dendy Newtown (its only data path is robots-disallowed — see DECISIONS.md).
Outdoor/seasonal cinemas (Moonlight, Westpac OpenAir, Mov'in Bed) until a season is live.

## Users
Harvey first. Then Sydney cinephiles. Revenue via ticket referral links where a
venue or ticketing platform offers one; otherwise none in v1.

## Data sources (confirmed 2026-10-15 — details and keys in DECISIONS.md)
| Venue | Method | Status |
|---|---|---|
| Hoyts (~12 Sydney sites) | JSON API | in v1 |
| Palace Central, Norton St, Moore Park | JSON embedded in cinema page (`__NEXT_DATA__`) | in v1 |
| Hayden Orpheum | JSON API | in v1 |
| Ritz Randwick | HTML, dated pages | in v1 (first scraper) |
| Golden Age | HTML | in v1 |
| Roseville | Veezi sessions page (HTML) | in v1 |
| Event (all Sydney sites) | HTML, printable week view | in v1 |
| Reading (Rhodes, Auburn, Rouse Hill…) | unknown — site blank from non-AU IP | retest from AU; else uncovered |
| Dendy Newtown | GraphQL only, robots-disallowed | not in v1 |
| Moonlight (seasonal) | WPGraphQL, off-season | deferred to summer |
| TMDB | REST API, read-access token | enrichment |

Venues removed since v0: Chauvel (closed Jan 2026), Palace Verona (closed Feb 2024),
Cinema Paris (now Palace Moore Park). Dendy is one entity (Newtown only).

Each showing carries: venue, film title, start time (Australia/Sydney), session id,
booking URL, venue-reported attributes (format, captions, NFT, event), and once
enriched: TMDB id, year, director, rating. Hoyts, Palace and Orpheum also share a
Vista movie id (`HO000…`) — stored, used for matching before TMDB lookup.

## Rules for scrapers
Respect robots.txt. Identify with a descriptive User-Agent and contact address.
At most 1 request/second per host. Never fetch purchase/ticketing pages; link out only.

## The one number
Coverage: % of Sydney screens whose showtimes appear on the page, measured weekly.
v1 target: ≥ 80% of screens; 100% of independents that are scrapeable within the
rules above (Dendy excluded and reported as uncovered).

## Success for v2
Harvey uses it instead of venue sites for two consecutive weeks; one other person does too.
