# The Senate JOLT

A beginner FastAPI MVP that scrapes official Senate pages, detects procedural activity, stores alerts in SQLite, and shows them in a local web UI.

## What it does

- Scrapes these Senate pages:
  - `https://www.senate.gov/legislative/floor_activity_pail.htm`
  - `https://www.senate.gov/legislative/Congressional_Records/Daily_Digest.htm`
  - `https://www.congress.gov/`
  - `https://www.radiotv.senate.gov/`
  - `https://ebbs.senate.gov/`
  - `https://www.senate.gov/legislative/votes_new.htm`
- Extracts visible text from the page
- Detects meaningful Senate events such as cloture, motion to proceed, roll call votes, confirmed nominations, unanimous consent, executive session, and legislative session
- Saves alerts to `data/senate_wire.db`
- Prevents duplicate alerts from being saved on every refresh
- Displays alerts on `http://127.0.0.1:8000`

## Run locally

1. Open a terminal
2. Change into the project folder:
   ```bash
   cd /Users/findingrb/Desktop/senate-wire
   ```
3. Install dependencies:
   ```bash
   python3 -m pip install -r requirements.txt
   ```
4. Start the app:
   ```bash
   uvicorn app.main:app --reload
   ```
5. Open your browser to:
   ```text
   http://127.0.0.1:8000
   ```

You can also click the "Refresh Alerts" button on the page to pull the latest Senate activity immediately.

## Project structure

- `app/main.py` - FastAPI app and startup background scraper
- `app/scraper.py` - page scraper, visible text extraction, duplicate prevention
- `app/parser.py` - detects Senate procedural phrases and returns alerts
- `app/database.py` - SQLite database model and initialization
- `templates/index.html` - webpage template
- `static/style.css` - page styling
- `data/senate_wire.db` - SQLite database file created at runtime

## Notes

- The page route only reads from the database; it does not scrape again on every reload.
- The scraper runs in the background every 5 minutes and only stores new alerts.
- If you change the parser rules, restart the app and delete `data/senate_wire.db` to reset the database.
