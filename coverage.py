"""Coverage (B7): the share of Sydney's cinema screens whose showtimes are on the page.

Every Sydney cinema is in venues.yaml with its screen count, including those we
don't scrape (Dendy, Reading…, marked `scraped: false`). A cinema counts as
covered when tonight's data has sessions there, so a scraper that failed, or a
cinema whose sessions are missing, counts as uncovered, as SPEC.md asks. A cinema
marked `closed: true` is left out of both sides (Harvey, 2026-10-19), unless it has
sessions again. Cinemas whose screen count isn't known yet are left out too, and listed.
The figure is in data.json only; the page doesn't show it.
"""


def coverage(venues: dict[str, dict], rows: list[dict]) -> dict:
    """venues: load_venues(); rows: data.json's showings."""
    showing = {row["venue"] for row in rows}
    counted = {
        slug: v["screens"]
        for slug, v in venues.items()
        if v.get("screens") and (not v.get("closed") or slug in showing)
    }
    covered = {slug: screens for slug, screens in counted.items() if slug in showing}
    total = sum(counted.values())
    return {
        "screens_covered": sum(covered.values()),
        "screens_total": total,
        "percent": round(100 * sum(covered.values()) / total) if total else None,
        "cinemas_covered": len(covered),
        "cinemas_total": len(counted),
        "uncovered": sorted(venues[slug]["name"] for slug in counted if slug not in covered),
        "unknown_screens": sorted(slug for slug, v in venues.items() if not v.get("screens")),
        "closed": sorted(
            v["name"] for slug, v in venues.items() if v.get("closed") and slug not in showing
        ),
    }
