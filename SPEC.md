# SPEC — Sydney Ciné Info (v1, 2026-10-15)

## Problem
Finding what's on in Sydney means visiting every cinema's site in turn. Paris has
a single page for this (Paris Ciné Info); Sydney does not.

## Product (v1)
One page. Every current and upcoming showing in Greater Sydney, enriched with year,
director and ratings, filterable by: film, director, film type (new release /
retrospective / festival / special), showing date, release date. Grouped views:
"new this week", "retrospectives", "last chance".

## Not in v1
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

## Success for v1
Harvey uses it instead of venue sites for two consecutive weeks.
