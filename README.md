# Property Sale Diagnostic

A local web dashboard + report generator for estate agents: paste in a
stalled listing's details and get a seller-ready "why hasn't this sold, and
what to do about it" report, backed by live HM Land Registry data.

## What this is (and isn't)

- **Is:** a tool that combines free official UK property data (Land
  Registry sold prices, UK House Price Index) with the listing's own
  details and a documented set of estate-agency best-practice rules, to
  produce a diagnostic report and Word document for sellers.
- **Isn't:** connected to Rightmove/Zoopla/OnTheMarket's internal systems.
  They don't provide a public API, and scraping their pages breaks their
  Terms of Service - so this tool doesn't do that. You paste in the
  listing's own details (price, description, days on market, photo count,
  price history) instead. See `methodology.md` for the full reasoning and
  all the scoring rules used.

## Setup

Requires Python 3.9+.

```bash
pip install -r requirements.txt
```

## Running the dashboard

```bash
streamlit run dashboard.py
```

This opens a local web page (usually `http://localhost:8501`) with a form:
paste in the listing link (for reference) and the property's details, click
**Generate report**, and you'll get:

- An on-screen diagnosis (pricing vs. local comparables, days-on-market
  read, presentation issues, market trend context)
- A prioritised action plan
- A downloadable Word report formatted for the seller

## Checking the data connections work

Before relying on it for a real client, run this once from a terminal on a
machine with normal internet access (this checks Land Registry connectivity
directly, without the dashboard):

```bash
python data_sources.py "SW1A 1AA" "Westminster"
```

You should see a handful of comparable sales and a price trend printed. If
you get connection errors, check your network/firewall isn't blocking
`landregistry.data.gov.uk`.

## Putting it on the web, free (step by step, no coding required)

This uses **Streamlit Community Cloud** - free hosting made by the people
who make Streamlit. You'll do everything through your web browser; no
command line needed.

**Step 1 - Create a GitHub account** (skip if you already have one)
Go to `github.com` → click **Sign up** → follow the prompts (email,
password, username). It's free.

**Step 2 - Create a new repository (a project folder on GitHub)**
1. Once logged in, click the **+** icon top-right → **New repository**.
2. Give it a name, e.g. `property-sale-tool`.
3. Leave it set to **Public** (Community Cloud's free tier needs this,
   unless you connect a private repo - see the note below).
4. Click **Create repository**.

**Step 3 - Upload the tool's files**
1. On your new repository's page, click **Add file** → **Upload files**.
2. Unzip the file I gave you (`property_report_tool_v2.zip`) on your
   computer first.
3. Drag in every file from inside that unzipped folder (`dashboard.py`,
   `data_sources.py`, `report_engine.py`, `generate_docx_report.py`,
   `requirements.txt`, `README.md`, `methodology.md`, and the
   `sample_output` folder) - drop them straight into the upload box so
   they land in the root of the repository, not nested inside another
   folder.
4. Scroll down, click **Commit changes**.

**Step 4 - Sign up for Streamlit Community Cloud**
1. Go to `share.streamlit.io`.
2. Click **Continue to sign-in** → **Continue with GitHub**.
3. Approve GitHub's sign-in prompts, then accept Streamlit's terms.

**Step 5 - Connect your GitHub account (if not done 