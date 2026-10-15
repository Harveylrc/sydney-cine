# SPEC — Sydney Ciné Info

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

## Users
Harvey first. Then Sydney cinephiles. Revenue via ticket referral links where a
venue or ticketing platform offers one; otherwise none in v1.

## Data sources (to be confirmed in planning — this is the feasibility question)
- Chains: Hoyts, Event, Palace, Dendy, Reading
- Independents: Ritz Randwick, Hayden Orpheum, Golden Age, Chauvel, Roseville,
  Dendy Newtown, Cinema Paris, Moonlight/outdoor (seasonal)
- Enrichment: TMDB
For each: does it have an API, a feed, structured HTML, or only JS-rendered pages?
Record findings in DECISIONS.md.

## The one number
Coverage: % of Sydney screens whose showtimes appear on the page, measured weekly.
v1 target: ≥ 80% of screens; 100% of independents.

## Success for v1
Harvey uses it instead of venue sites for two consecutive weeks.
