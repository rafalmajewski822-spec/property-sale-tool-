# Methodology

This tool does not have access to a secret proprietary database of "top
broker" knowledge - no such thing exists as a free/legal data source. What it
does is combine:

1. **Free, official UK government data** - HM Land Registry Price Paid Data
   (every England & Wales sale since 1995) and the UK House Price Index, for
   objective comparable prices and area trend.
2. **The listing's own details**, entered by the agent (asking price,
   description, photos, days on market, price change history).
3. **A codified set of scoring rules** based on widely published UK estate
   agency and property-portal best practice. These are documented below so
   you can see exactly why the tool says what it says, and adjust the
   thresholds in `report_engine.py` (`CONFIG` dict at the top) to match your
   own agency's house view.

## The rules, and why

**Pricing vs. comparable median**
A property priced more than ~5-10% above what similar homes have actually
sold for nearby is the single most common reason a listing stalls: buyers
and buyer's agents check sold prices too, and portals de-prioritise/buyers
mentally filter out obviously optimistic listings. Source thresholds are
configurable (`overpriced_warning_pct`, `overpriced_critical_pct`).

**Days on market**
- The first ~2 weeks ("golden fortnight") get the most views of the whole
  listing lifetime - both portal algorithms and buyer saved-search alerts
  favour freshly listed properties.
- Past ~6 weeks with no offer, the natural interest curve has passed and
  continued inaction is a signal, not just bad luck.
- Past ~3 months, industry convention is that a genuine relaunch (new
  photography, rewritten description, price reset, sometimes coming off
  the market briefly before relisting) outperforms simply waiting.

**Price reductions**
Multiple small reductions read as a seller under pressure and invite
lowball offers in anticipation of further cuts. A single, decisive
reprice to the comparable median is standard professional advice over a
series of small drops - though any reduction does refresh portal
visibility to buyers with matching saved searches.

**Presentation**
- Fewer than ~10 photos consistently under-performs; 20+ professional
  photos covering every room, exterior and garden/parking is the
  well-established minimum for serious listings.
- Floorplans are heavily used by buyers when shortlisting viewings,
  especially for flats/maisonettes.
- Virtual tours/video aren't essential but increase time-on-listing and
  help pre-qualify remote/time-poor buyers.
- Descriptions under ~120 words, or ones leaning on generic filler phrases
  ("must be seen", "chain free", "immaculate throughout"), read as
  low-effort and are skimmed past. Specific detail (room dimensions, what
  was renovated and when, real distances to schools/transport) converts
  better and reads as more credible.

**Market context**
A falling local market (from UK HPI annual change) makes overpricing even
less forgiving; a rising market suggests the lack of a sale is more likely
about the listing itself than broader conditions.

## Data sources in detail

| Source | What it provides | Cost | Coverage |
|---|---|---|---|
| HM Land Registry Price Paid Data | Individual sold prices, dates, property type | Free | England & Wales |
| HM Land Registry UK House Price Index | Area-level average price & % change trend | Free | UK-wide |
| EPC Register | Energy rating, floor area (optional, needs free API key) | Free (registration) | England & Wales |
| Listing details | Price, description, photos, days on market | You provide | N/A |

Rightmove, Zoopla and OnTheMarket are deliberately **not** scraped - they
don't offer a public API for this kind of use, and their Terms of Service
prohibit automated scraping. If you want live listing/competitor data pulled
in automatically (not just the property you're reporting on), a paid
aggregator such as PropertyData, Homedata or Street Data combines Land
Registry/EPC data with licensed portal listing feeds - see README.md.
