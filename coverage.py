"""Coverage (B7): the share of Sydney's cinema screens whose showtimes are on the page.

Every Sydney cinema is in venues.yaml with its screen count, including those we
don't scrape (Dendy, Reading…, marked `scraped: false`). A cinema counts as
covered when tonight's data has sessions there, so a scraper that failed, or a
cinema that is closed (Event Bondi), counts as uncovered, as SPEC.md asks.
Cinemas whose screen count isn't known yet are left out of both sides and listed.
"""


def coverage(venues: dict[str, dict], rows: list[dict]) -> dict:
    """venues: load_venues(); rows: data.json's showings."""
    showing = {row["venue"] for row in rows}
    counted = {slug: v["screens"] for slug, v in venues.items() if v.get("screens")}
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
    }
