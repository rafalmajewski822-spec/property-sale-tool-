"""
report_engine.py
=================
Turns (listing details + free official UK data) into a structured
"why hasn't it sold" diagnosis and action plan for a seller.

The scoring rules encoded here are drawn from widely published UK estate
agency best practice (Rightmove/Zoopla portal research on listing
performance, and standard agency sales methodology) - not a secret
proprietary dataset. They are documented in methodology.md alongside this
file so any agent using the tool can see exactly why a recommendation was
made, and adjust the thresholds (see CONFIG below) to match their own
house view.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from data_sources import get_area_price_trend, get_comparable_sales

# --------------------------------------------------------------------------
# Tunable thresholds - the "methodology". See methodology.md for the
# reasoning behind each of these.
# --------------------------------------------------------------------------
CONFIG = {
    "overpriced_warning_pct": 5,      # >5% above comparable median = caution
    "overpriced_critical_pct": 10,    # >10% above median = likely the core issue
    "critical_early_window_days": 14, # the "golden fortnight" of a new listing
    "stale_days_threshold": 42,       # ~6 weeks with no offer is a red flag
    "long_stale_days_threshold": 90,  # 3 months+ needs a serious reset
    "min_good_photo_count": 20,
    "low_photo_count": 10,
    "min_description_words": 120,
    "vague_phrases": [
        "must be seen", "won't last long", "chain free", "viewing essential",
        "early viewing recommended", "a credit to the current owners",
        "immaculate throughout", "must be viewed",
    ],
}


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------

@dataclass
class PriceChange:
    changed_on: date
    new_price: int


@dataclass
class ListingInput:
    address: str
    postcode: str
    region_for_trend: str      # local authority / region name for HPI lookup
    property_type: str         # Detached / Semi-Detached / Terraced / Flat
    bedrooms: int
    asking_price: int
    original_asking_price: int
    date_listed: date
    listing_url: str = ""
    price_changes: list[PriceChange] = field(default_factory=list)
    description_text: str = ""
    photo_count: int = 0
    has_floorplan: bool = False
    has_virtual_tour: bool = False
    epc_rating: Optional[str] = None
    agent_name: str = ""
    seller_name: str = ""


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

@dataclass
class Finding:
    severity: str   # "critical" | "warning" | "positive" | "info"
    headline: str
    detail: str


@dataclass
class ReportResult:
    listing: ListingInput
    days_on_market: int
    comparable_median: Optional[int]
    comparable_count: int
    comparables_sample: list
    price_vs_median_pct: Optional[float]
    area_trend: Optional[dict]
    findings: list[Finding]
    action_plan: list[str]
    headline_summary: str


# --------------------------------------------------------------------------
# Core analysis
# --------------------------------------------------------------------------

def _pct_over_median(asking: int, median: Optional[int]) -> Optional[float]:
    if not median:
        return None
    return round((asking - median) / median * 100, 1)


def _word_count(text: str) -> int:
    return len(text.split())


def _score_pricing(listing: ListingInput, pct_over: Optional[float]) -> list[Finding]:
    findings = []
    if pct_over is None:
        findings.append(Finding(
            "info", "No local comparable sales found",
            "We couldn't find enough recent Land Registry sold-price comparables for this "
            "postcode area to benchmark the asking price. Widen the search area or check the "
            "postcode is correct.",
        ))
        return findings

    if pct_over >= CONFIG["overpriced_critical_pct"]:
        findings.append(Finding(
            "critical", f"Priced {pct_over}% above the local sold-price median",
            f"The asking price of £{listing.asking_price:,} is {pct_over}% above the median "
            f"of comparable sales in {listing.postcode}. This is the single most common reason "
            f"a property doesn't sell: buyers and their agents can see the comparables too, and "
            f"a price this far above them usually means the listing is filtered out of buyer "
            f"searches entirely, or dismissed on the first viewing.",
        ))
    elif pct_over >= CONFIG["overpriced_warning_pct"]:
        findings.append(Finding(
            "warning", f"Priced {pct_over}% above the local sold-price median",
            f"This is a meaningful premium over what similar properties have actually sold for "
            f"recently. It may be justified by genuine upgrades or a stronger plot/position - "
            f"but if there isn't a clear, visible reason for the premium in the listing itself, "
            f"buyers will assume it's just optimistic pricing.",
        ))
    elif pct_over <= -5:
        findings.append(Finding(
            "info", f"Priced {abs(pct_over)}% below the local sold-price median",
            "The asking price is at or below the local market - pricing is unlikely to be why "
            "this hasn't sold. Look at presentation, marketing and days-on-market factors below.",
        ))
    else:
        findings.append(Finding(
            "positive", "Priced in line with the local market",
            f"At {pct_over:+.1f}% versus the comparable median, the price itself looks "
            f"reasonable. The reasons this hasn't sold are more likely to be presentation, "
            f"marketing or timing - see below.",
        ))
    return findings


def _score_days_on_market(listing: ListingInput, dom: int) -> list[Finding]:
    findings = []
    if dom <= CONFIG["critical_early_window_days"]:
        findings.append(Finding(
            "info", f"Only {dom} days on the market so far",
            "Still within the normal early window where interest is naturally highest - it's "
            "early to draw firm conclusions, but worth acting on any presentation issues now "
            "while the listing is still 'fresh' to portal algorithms and buyer alerts.",
        ))
    elif dom <= CONFIG["stale_days_threshold"]:
        findings.append(Finding(
            "warning", f"{dom} days on the market",
            "The initial burst of interest that any new listing gets has passed. If enquiries "
            "have dropped off, that's a signal the current price/presentation isn't converting "
            "views into viewings.",
        ))
    elif dom <= CONFIG["long_stale_days_threshold"]:
        findings.append(Finding(
            "critical", f"{dom} days on the market - well past the typical selling window",
            "Portal search algorithms and buyer saved-search alerts favour recently listed or "
            "recently-reduced properties. A listing sitting untouched this long is increasingly "
            "invisible to new buyers, even if it's a good property at a fair price.",
        ))
    else:
        findings.append(Finding(
            "critical", f"{dom} days on the market - a full relaunch is needed",
            "At this point, simply waiting is very unlikely to produce a sale. The standard "
            "professional response is a genuine relaunch: new photography, a rewritten "
            "description, a reset asking price, and (often) coming off the market for a short "
            "period before relisting as a 'new instruction' with a clean listing history.",
        ))
    return findings


def _score_price_changes(listing: ListingInput) -> list[Finding]:
    findings = []
    n = len(listing.price_changes)
    if n == 0:
        return findings
    total_drop = listing.original_asking_price - listing.asking_price
    total_drop_pct = round(total_drop / listing.original_asking_price * 100, 1) if listing.original_asking_price else 0

    if n >= 3:
        findings.append(Finding(
            "critical", f"{n} separate price reductions totalling {total_drop_pct}%",
            "Multiple small reductions read to buyers as a seller under pressure, and invite "
            "lowball offers in anticipation of a further cut. A single, confident reset to a "
            "realistic price (backed by the comparables) is almost always more effective than "
            "repeated small drops.",
        ))
    else:
        findings.append(Finding(
            "warning", f"{n} price reduction(s) totalling {total_drop_pct}%",
            "Reductions can refresh portal visibility (Rightmove/Zoopla flag reduced listings "
            "to buyers with matching saved searches), but if the reduced price still isn't near "
            "the comparable median, it may need to go further.",
        ))
    return findings


def _score_presentation(listing: ListingInput) -> list[Finding]:
    findings = []

    if listing.photo_count == 0:
        pass
    elif listing.photo_count < CONFIG["low_photo_count"]:
        findings.append(Finding(
            "critical", f"Only {listing.photo_count} photos",
            f"Listings with fewer than {CONFIG['low_photo_count']} photos consistently "
            f"under-perform - buyers scroll past quickly if they can't see enough of the "
            f"property. Aim for {CONFIG['min_good_photo_count']}+ professional photos covering "
            f"every room, the exterior, and any garden/parking.",
        ))
    elif listing.photo_count < CONFIG["min_good_photo_count"]:
        findings.append(Finding(
            "warning", f"{listing.photo_count} photos - a bit light",
            f"Most well-performing listings run to {CONFIG['min_good_photo_count']}+ photos. "
            f"A few extra shots (especially of any recently updated areas) is a very cheap fix.",
        ))
    else:
        findings.append(Finding(
            "positive", f"{listing.photo_count} photos - good coverage", "",
        ))

    if not listing.has_floorplan:
        findings.append(Finding(
            "warning", "No floorplan",
            "Floorplans are one of the most-used features by serious buyers when shortlisting "
            "viewings, particularly for flats and any property where layout/flow matters. "
            "Adding one is inexpensive and quick.",
        ))

    if not listing.has_virtual_tour:
        findings.append(Finding(
            "info", "No virtual tour / video walkthrough",
            "Not essential, but a short video or 3D tour increases time spent on the listing "
            "and pre-qualifies viewers before they book an in-person visit - useful for out-of-"
            "area or time-poor buyers.",
        ))

    wc = _word_count(listing.description_text)
    if wc < CONFIG["min_description_words"]:
        findings.append(Finding(
            "warning", f"Description is short ({wc} words)",
            "A thin description leaves buyers guessing. Include specific room dimensions, what "
            "has been updated and when, nearby schools/transport/amenities, and anything that "
            "explains the asking price (period features, plot size, recent works, etc.).",
        ))

    lowered = listing.description_text.lower()
    used_vague = [p for p in CONFIG["vague_phrases"] if p in lowered]
    if used_vague:
        findings.append(Finding(
            "info", "Description leans on generic estate-agent phrases",
            f"Phrases like {', '.join(repr(p) for p in used_vague)} are so common that buyers "
            f"tend to skim past them. Replacing them with specific, concrete detail (exact "
            f"measurements, what's actually been renovated, real distances to the station/"
            f"school) reads as more credible and is more memorable.",
        ))

    return findings


def _headline(findings: list[Finding], listing: ListingInput) -> str:
    criticals = [f for f in findings if f.severity == "critical"]
    if criticals:
        top = criticals[0]
        return (f"The main obstacle to selling {listing.address} appears to be: {top.headline}. "
                f"See the full breakdown and action plan below.")
    warnings = [f for f in findings if f.severity == "warning"]
    if warnings:
        return (f"{listing.address} doesn't have one single glaring problem, but a combination "
                f"of smaller factors below is likely dampening interest.")
    return (f"{listing.address} looks well priced and well presented. The remaining "
            f"recommendations below are refinements, not fixes for a fundamental problem.")


def _build_action_plan(findings: list[Finding], listing: ListingInput) -> list[str]:
    plan = []
    by_headline = {f.headline: f for f in findings}

    criticals = [f for f in findings if f.severity == "critical"]
    warnings = [f for f in findings if f.severity == "warning"]

    for f in criticals + warnings:
        if "above the local sold-price median" in f.headline:
            plan.append("Reprice to within 0-3% of the comparable sold-price median identified "
                        "in this report, rather than relying on further incremental cuts.")
        elif "price reductions" in f.headline or "reduction(s)" in f.headline:
            plan.append("Make one confident, final price reset rather than another small "
                        "reduction - and communicate it as a deliberate repositioning, not "
                        "desperation.")
        elif "days on the market" in f.headline and ("relaunch" in f.detail or "invisible" in f.detail):
            plan.append("Refresh the listing: new lead photo, updated description, and (if "
                        "possible) a short period off-market before relisting as a fresh "
                        "instruction to reset portal visibility and buyer alerts.")
        elif "photos" in f.headline:
            plan.append("Commission professional photography (or reshoot key rooms) - "
                        f"target {CONFIG['min_good_photo_count']}+ images.")
        elif "floorplan" in f.headline.lower():
            plan.append("Add a floorplan - typically same-day turnaround from most local "
                        "floorplan services.")
        elif "description is short" in f.headline.lower():
            plan.append("Rewrite the description with specific detail: room dimensions, dates "
                        "of any renovation, distances to schools/stations, and what makes this "
                        "property different from the comparables.")

    # de-duplicate while preserving order
    seen = set()
    deduped = []
    for p in plan:
        if p not in seen:
            deduped.append(p)
            seen.add(p)

    if not deduped:
        deduped.append("Keep monitoring portal views/enquiries weekly and revisit pricing "
                       "against fresh comparables if enquiries don't pick up within 2-3 weeks.")

    return deduped


def build_report(listing: ListingInput, fetch_live_data: bool = True) -> ReportResult:
    """
    Run the full pipeline: fetch comparables + area trend (if
    fetch_live_data), score the listing, and produce a structured result
    ready to hand to generate_docx_report.py.
    """
    comps = {"sales": [], "median_price": None, "count": 0, "error": None}
    trend = None

    if fetch_live_data:
        comps = get_comparable_sales(listing.postcode)
        trend = get_area_price_trend(listing.region_for_trend)

    dom = (date.today() - listing.date_listed).days
    pct_over = _pct_over_median(listing.asking_price, comps.get("median_price"))

    findings: list[Finding] = []
    findings += _score_pricing(listing, pct_over)
    findings += _score_days_on_market(listing, dom)
    findings += _score_price_changes(listing)
    findings += _score_presentation(listing)

    if trend and trend.get("trend_summary"):
        if trend["trend_summary"] == "falling":
            findings.append(Finding(
                "warning", f"Local prices in {listing.region_for_trend} are falling "
                           f"({trend['latest']['annual_change_pct']}% annually)",
                "A softening market makes overpricing even less forgiving - buyers have more "
                "choice and are more price-sensitive right now.",
            ))
        elif trend["trend_summary"] == "rising":
            findings.append(Finding(
                "info", f"Local prices in {listing.region_for_trend} are rising "
                        f"({trend['latest']['annual_change_pct']}% annually)",
                "A rising market works in the seller's favour, which makes it more likely that "
                "presentation or pricing (rather than a genuinely soft market) explains the "
                "lack of a sale.",
            ))

    action_plan = _build_action_plan(findings, listing)
    headline = _headline(findings, listing)

    return ReportResult(
        listing=listing,
        days_on_market=dom,
        comparable_median=comps.get("median_price"),
        comparable_count=comps.get("count", 0),
        comparables_sample=comps.get("sales", [])[:8],
        price_vs_median_pct=pct_over,
        area_trend=trend,
        findings=findings,
        action_plan=action_plan,
        headline_summary=headline,
    )
