"""
data_sources.py
================
Free / official UK data connectors for the Property Sale Diagnostic tool.

No API key required for any of these. Everything here calls publicly
documented, official UK government data services:

  - HM Land Registry Price Paid Data (comparable sold prices)
    https://landregistry.data.gov.uk  (linked data / SPARQL)
  - HM Land Registry UK House Price Index (area price trend)
    https://landregistry.data.gov.uk/app/ukhpi
  - EPC Register (Energy Performance Certificates)
    https://epc.opendatacommunities.org (being replaced by
    https://get-energy-performance-data.communities.gov.uk - see note below)

IMPORTANT: Rightmove, Zoopla and OnTheMarket do NOT provide a public API for
pulling listing data. Scraping their pages breaks their Terms of Service.
This tool does not attempt to scrape them. Listing details (asking price,
description, days listed, price changes, photo count) are supplied by the
agent directly - see the dashboard form.

Every function here is defensive: if a live call fails (network issue, an
endpoint changing shape, being offline, etc.) it returns an empty result
with an explanatory `error` field rather than raising, so the report
generator can carry on and simply note "data unavailable" for that section.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import requests

USER_AGENT = "PropertySaleDiagnostic/1.0 (agent tool; contact: set-your-email)"
TIMEOUT = 20

LR_SPARQL_ENDPOINT = "https://landregistry.data.gov.uk/landregistry/query"
EPC_API_BASE = "https://epc.opendatacommunities.org/api/v1/domestic"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def normalise_postcode(postcode: str) -> str:
    return re.sub(r"\s+", " ", postcode.strip().upper())


def outcode_of(postcode: str) -> str:
    """'SW1A 1AA' -> 'SW1A'"""
    pc = normalise_postcode(postcode)
    return pc.split(" ")[0]


def _sparql_get(query: str) -> Optional[dict]:
    try:
        resp = requests.get(
            LR_SPARQL_ENDPOINT,
            params={"query": query},
            headers={"Accept": "application/sparql-results+json", "User-Agent": USER_AGENT},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # noqa: BLE001 - deliberately broad, this is a best-effort fetch
        return {"error": str(exc)}


# --------------------------------------------------------------------------
# 1. Land Registry Price Paid Data - comparable sold prices
# --------------------------------------------------------------------------

@dataclass
class ComparableSale:
    address: str
    postcode: str
    price: int
    date_sold: str
    property_type: str
    new_build: bool


def get_comparable_sales(postcode: str, months_back: int = 36, limit: int = 50) -> dict:
    """
    Pull recent sold-price comparables for the postcode area from HM Land
    Registry Price Paid Data (free, official, covers England & Wales).

    Returns dict with keys: sales (list[ComparableSale]), median_price,
    count, area (outcode used), error (if any).
    """
    outcode = outcode_of(postcode)
    cutoff = (date.today() - timedelta(days=months_back * 30)).isoformat()

    query = f"""
    PREFIX lrppi: <http://landregistry.data.gov.uk/def/ppi/>
    PREFIX lrcommon: <http://landregistry.data.gov.uk/def/common/>
    SELECT ?paon ?saon ?street ?town ?postcode ?amount ?transdate ?propertyType ?newBuild
    WHERE {{
      ?transx lrppi:pricePaid ?amount ;
              lrppi:transactionDate ?transdate ;
              lrppi:propertyAddress ?addr ;
              lrppi:propertyType ?propertyTypeUri ;
              lrppi:newBuild ?newBuild .
      ?addr lrcommon:postcode ?postcode .
      OPTIONAL {{ ?addr lrcommon:paon ?paon }}
      OPTIONAL {{ ?addr lrcommon:saon ?saon }}
      OPTIONAL {{ ?addr lrcommon:street ?street }}
      OPTIONAL {{ ?addr lrcommon:town ?town }}
      BIND(STRAFTER(STR(?propertyTypeUri), "common/") AS ?propertyType)
      FILTER(REGEX(?postcode, "^{outcode}"))
      FILTER(?transdate >= "{cutoff}"^^<http://www.w3.org/2001/XMLSchema#date>)
    }}
    ORDER BY DESC(?transdate)
    LIMIT {limit}
    """

    result = _sparql_get(query)
    if not result or "error" in result:
        return {
            "sales": [],
            "median_price": None,
            "count": 0,
            "area": outcode,
            "error": result.get("error") if result else "No response from Land Registry",
        }

    try:
        bindings = result["results"]["bindings"]
    except (KeyError, TypeError):
        return {"sales": [], "median_price": None, "count": 0, "area": outcode,
                 "error": "Unexpected response shape from Land Registry"}

    sales: list[ComparableSale] = []
    for b in bindings:
        addr_parts = [b.get(k, {}).get("value") for k in ("paon", "saon", "street", "town")]
        address = ", ".join(p for p in addr_parts if p)
        sales.append(ComparableSale(
            address=address or "(address withheld)",
            postcode=b.get("postcode", {}).get("value", outcode),
            price=int(float(b["amount"]["value"])),
            date_sold=b["transdate"]["value"][:10],
            property_type=b.get("propertyType", {}).get("value", "unknown"),
            new_build=b.get("newBuild", {}).get("value") == "true",
        ))

    prices = [s.price for s in sales]
    return {
        "sales": sales,
        "median_price": statistics.median(prices) if prices else None,
        "count": len(sales),
        "area": outcode,
        "error": None,
    }


# --------------------------------------------------------------------------
# 2. UK House Price Index - area trend (rising / flat / falling, % YoY)
# --------------------------------------------------------------------------

def region_slug(region_name: str) -> str:
    """'Greater London' -> 'greater-london' (matches LR id/region/ convention)."""
    return re.sub(r"[^a-z0-9]+", "-", region_name.strip().lower()).strip("-")


def get_area_price_trend(region_name: str, months: int = 13) -> dict:
    """
    Pull the UK House Price Index time series for a region/local authority
    from HM Land Registry's linked-data UK HPI dataset (free, official).

    `region_name` should be a local authority or region name, e.g.
    "Manchester", "Greater London", "Bristol", "United Kingdom".

    Returns dict with keys: region, series (list of {month, average_price,
    annual_change_pct}), latest, trend_summary, error.
    """
    slug = region_slug(region_name)
    region_uri = f"http://landregistry.data.gov.uk/id/region/{slug}"

    query = f"""
    PREFIX ukhpi: <http://landregistry.data.gov.uk/def/ukhpi/>
    SELECT ?refMonth ?avgPrice ?annualChange ?monthlyChange
    WHERE {{
      ?item ukhpi:refRegion <{region_uri}> ;
            ukhpi:refPeriod ?refMonth ;
            ukhpi:averagePrice ?avgPrice ;
            ukhpi:percentageAnnualChange ?annualChange ;
            ukhpi:percentageMonthlyChange ?monthlyChange .
    }}
    ORDER BY DESC(?refMonth)
    LIMIT {months}
    """

    result = _sparql_get(query)
    if not result or "error" in result:
        return {
            "region": region_name,
            "series": [],
            "latest": None,
            "trend_summary": None,
            "error": result.get("error") if result else "No response from Land Registry UK HPI",
        }

    try:
        bindings = result["results"]["bindings"]
    except (KeyError, TypeError):
        return {"region": region_name, "series": [], "latest": None, "trend_summary": None,
                 "error": "Unexpected response shape from UK HPI"}

    if not bindings:
        return {"region": region_name, "series": [], "latest": None, "trend_summary": None,
                 "error": f"No UK HPI data found for region slug '{slug}'. Try a different "
                          f"area name (e.g. the local authority instead of a neighbourhood)."}

    series = [{
        "month": b["refMonth"]["value"][:7],
        "average_price": int(float(b["avgPrice"]["value"])),
        "annual_change_pct": round(float(b["annualChange"]["value"]), 1),
        "monthly_change_pct": round(float(b["monthlyChange"]["value"]), 1),
    } for b in bindings]

    latest = series[0]
    if latest["annual_change_pct"] > 1:
        trend = "rising"
    elif latest["annual_change_pct"] < -1:
        trend = "falling"
    else:
        trend = "flat"

    return {
        "region": region_name,
        "series": series,
        "latest": latest,
        "trend_summary": trend,
        "error": None,
    }


# --------------------------------------------------------------------------
# 3. EPC Register (optional - energy rating / floor area / construction)
# --------------------------------------------------------------------------

def get_epc_data(postcode: str, epc_api_email: Optional[str] = None,
                  epc_api_key: Optional[str] = None) -> dict:
    """
    Look up EPC data for a postcode. Requires a free API key from the EPC
    Register (https://epc.opendatacommunities.org - being migrated to
    https://get-energy-performance-data.communities.gov.uk during 2026).

    If no key is supplied, this returns error=None but records=[] with a
    note, so the report generator treats EPC as "not provided" rather than
    failing. The agent can also just type the EPC rating straight into the
    dashboard form if they already know it (usually printed on the listing).
    """
    if not epc_api_email or not epc_api_key:
        return {"records": [], "error": None,
                 "note": "No EPC API credentials supplied - skipped. You can also just enter "
                         "the EPC rating shown on the listing directly in the form."}

    import base64
    token = base64.b64encode(f"{epc_api_email}:{epc_api_key}".encode()).decode()
    try:
        resp = requests.get(
            f"{EPC_API_BASE}/search",
            params={"postcode": normalise_postcode(postcode)},
            headers={"Authorization": f"Basic {token}", "Accept": "application/json",
                      "User-Agent": USER_AGENT},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return {"records": data.get("rows", []), "error": None, "note": None}
    except Exception as exc:  # noqa: BLE001
        return {"records": [], "error": str(exc),
                 "note": "EPC lookup failed - the opendatacommunities EPC service is being "
                         "retired during 2026 in favour of get-energy-performance-data."
                         "communities.gov.uk. Enter the EPC rating manually if needed."}


if __name__ == "__main__":
    # Quick manual self-test - run this file directly on a machine with normal
    # internet access (not inside a locked-down sandbox) to sanity check the
    # live endpoints, e.g.:
    #   python data_sources.py "SW1A 1AA" "Westminster"
    import sys

    pc = sys.argv[1] if len(sys.argv) > 1 else "SW1A 1AA"
    region = sys.argv[2] if len(sys.argv) > 2 else "Westminster"

    print(f"--- Comparable sales near {pc} ---")
    comps = get_comparable_sales(pc)
    print(f"Found {comps['count']} sales, median £{comps['median_price']}, error={comps['error']}")
    for s in comps["sales"][:5]:
        print(f"  {s.date_sold}  £{s.price:,}  {s.property_type}  {s.address}")

    print(f"\n--- Price trend for {region} ---")
    trend = get_area_price_trend(region)
    print(f"Trend: {trend['trend_summary']}, latest={trend['latest']}, error={trend['error']}")
