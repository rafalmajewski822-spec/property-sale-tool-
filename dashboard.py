"""
dashboard.py
=============
Local web dashboard for the Property Sale Diagnostic tool.

Run with:
    streamlit run dashboard.py

Then open the URL it prints (usually http://localhost:8501) in your browser.

Workflow:
  1. Paste the property's Rightmove/Zoopla/OnTheMarket link (kept for
     reference/click-through only - it is NOT scraped, see note below).
  2. Fill in the listing details from the page (price, description, photo
     count, days listed, any price changes).
  3. Click "Generate report".
  4. Review the on-screen diagnosis, then download the Word report to send
     to the seller.

Why you paste details in rather than the tool fetching them automatically:
Rightmove/Zoopla/OnTheMarket do not offer a public API for reading listing
data, and scraping their pages breaks their Terms of Service. Everything
else (comparable sold prices, area price trend) is pulled live and
automatically from free official HM Land Registry data.
"""

import io
from datetime import date, datetime

import streamlit as st

from report_engine import ListingInput, PriceChange, build_report
from generate_docx_report import generate_report_docx

st.set_page_config(page_title="Property Sale Diagnostic", page_icon="🏠", layout="wide")

st.title("🏠 Property Sale Diagnostic")
st.caption(
    "Paste in a stalled listing's details to get a seller-ready report on why it hasn't sold "
    "and what to do about it - backed by live HM Land Registry sold-price data."
)

with st.form("listing_form"):
    st.subheader("Listing link (for reference only)")
    listing_url = st.text_input(
        "Rightmove / Zoopla / OnTheMarket URL",
        placeholder="https://www.rightmove.co.uk/properties/123456789",
    )

    st.subheader("Property")
    col1, col2, col3 = st.columns(3)
    with col1:
        address = st.text_input("Address", placeholder="12 Example Street, Sometown")
        postcode = st.text_input("Postcode", placeholder="SW1A 1AA")
    with col2:
        region_for_trend = st.text_input(
            "Local authority / region (for price trend)", placeholder="Westminster",
            help="Use the local authority name, e.g. 'Westminster', 'Manchester', 'Leeds'.",
        )
        property_type = st.selectbox(
            "Property type", ["Detached", "Semi-Detached", "Terraced", "Flat/Maisonette", "Other"]
        )
    with col3:
        bedrooms = st.number_input("Bedrooms", min_value=0, max_value=15, value=3)
        date_listed = st.date_input("Date first listed", value=date.today())

    st.subheader("Pricing")
    col1, col2 = st.columns(2)
    with col1:
        asking_price = st.number_input("Current asking price (£)", min_value=0, value=500000, step=5000)
    with col2:
        original_asking_price = st.number_input(
            "Original asking price (£) - same as current if never reduced",
            min_value=0, value=500000, step=5000,
        )

    st.caption("Price change history (optional) - add each reduction on its own line as YYYY-MM-DD, price")
    price_history_text = st.text_area(
        "Price changes", placeholder="2026-04-15, 525000\n2026-05-20, 500000", height=80
    )

    st.subheader("Presentation")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        photo_count = st.number_input("Number of photos", min_value=0, max_value=100, value=15)
    with col2:
        has_floorplan = st.checkbox("Has floorplan")
    with col3:
        has_virtual_tour = st.checkbox("Has virtual tour / video")
    with col4:
        epc_rating = st.selectbox("EPC rating (if known)", ["", "A", "B", "C", "D", "E", "F", "G"])

    description_text = st.text_area(
        "Listing description (paste the full text)", height=150,
        placeholder="Paste the property description from the listing here...",
    )

    st.subheader("Agency details (optional, shown on the report)")
    col1, col2 = st.columns(2)
    with col1:
        agency_name = st.text_input("Agency name")
    with col2:
        agent_contact = st.text_input("Agent contact (phone/email)")

    submitted = st.form_submit_button("Generate report", type="primary")

if submitted:
    if not address or not postcode:
        st.error("Please fill in at least the address and postcode.")
        st.stop()

    price_changes = []
    for line in price_history_text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d_str, p_str = [x.strip() for x in line.split(",")]
            price_changes.append(PriceChange(
                changed_on=datetime.strptime(d_str, "%Y-%m-%d").date(),
                new_price=int(p_str),
            ))
        except Exception:
            st.warning(f"Couldn't parse price-change line: '{line}' - skipped. Use format: YYYY-MM-DD, price")

    listing = ListingInput(
        address=address,
        postcode=postcode,
        region_for_trend=region_for_trend or postcode.split()[0],
        property_type=property_type,
        bedrooms=int(bedrooms),
        asking_price=int(asking_price),
        original_asking_price=int(original_asking_price),
        date_listed=date_listed,
        listing_url=listing_url,
        price_changes=price_changes,
        description_text=description_text,
        photo_count=int(photo_count),
        has_floorplan=has_floorplan,
        has_virtual_tour=has_virtual_tour,
        epc_rating=epc_rating or None,
        agent_name=agency_name,
    )

    with st.spinner("Pulling comparable sold prices and area trend from HM Land Registry..."):
        report = build_report(listing, fetch_live_data=True)

    st.success("Report generated.")

    st.header(report.listing.address)
    st.write(report.headline_summary)

    colA, colB, colC, colD = st.columns(4)
    colA.metric("Days on market", report.days_on_market)
    colB.metric("Asking price", f"£{report.listing.asking_price:,.0f}")
    if report.comparable_median:
        colC.metric("Local median (sold)", f"£{report.comparable_median:,.0f}")
    if report.price_vs_median_pct is not None:
        colD.metric("vs. median", f"{report.price_vs_median_pct:+.1f}%")

    if report.comparable_count == 0:
        st.info(
            "No Land Registry comparables were found for this postcode/period - check the "
            "postcode, or the Land Registry service may be temporarily unreachable from this "
            "network. The rest of the analysis below still applies."
        )

    st.subheader("Findings")
    severity_icon = {"critical": "🔴", "warning": "🟠", "positive": "🟢", "info": "🔵"}
    order = {"critical": 0, "warning": 1, "info": 2, "positive": 3}
    for f in sorted(report.findings, key=lambda x: order.get(x.severity, 9)):
        with st.container(border=True):
            st.markdown(f"{severity_icon.get(f.severity, '')} **{f.headline}**")
            if f.detail:
                st.write(f.detail)

    st.subheader("Recommended action plan")
    for i, step in enumerate(report.action_plan, start=1):
        st.markdown(f"{i}. {step}")

    if report.comparables_sample:
        st.subheader("Comparable sales used")
        st.table([{
            "Sold": s.date_sold, "Price": f"£{s.price:,.0f}",
            "Type": s.property_type, "Address": s.address,
        } for s in report.comparables_sample])

    # Generate the Word document and offer it for download
    output_path = "/tmp/property_sale_review.docx"
    generate_report_docx(report, output_path, agency_name=agency_name, agent_contact=agent_contact)
    with open(output_path, "rb") as f:
        st.download_button(
            "📄 Download Word report for the seller",
            data=f.read(),
            file_name=f"Property_Sale_Review_{report.listing.address.split(',')[0].replace(' ', '_')}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
