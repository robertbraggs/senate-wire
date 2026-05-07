# The Senate JOLT

A FastAPI Senate press logistics dashboard for Capitol Hill reporters, producers, and gallery-adjacent press users. It translates public Senate floor, committee, and media-event sources into practical coverage windows, locations, and watch items without political analysis or outcome predictions.

## What it does

- Scrapes these Senate pages:
  - `https://www.senate.gov/legislative/floor_activity_pail.htm`
  - `https://www.senate.gov/legislative/Congressional_Records/Daily_Digest.htm`
  - `https://www.congress.gov/`
  - `https://www.radiotv.senate.gov/`
  - `https://ebbs.senate.gov/`
  - `https://www.senate.gov/legislative/votes_new.htm`
- Extracts visible text from the page
- Flags logistics-relevant coverage items such as vote windows, floor schedule changes, committee/hearing locations, media events, stakeouts, and leadership/procedure cues that may affect press positioning
- Saves alerts to `data/senate_wire.db`
- Prevents duplicate alerts from being saved on every refresh
- Displays a press logistics dashboard on `http://127.0.0.1:8000`

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

You can also click the refresh control on the page to pull the latest public Senate logistics inputs immediately.

## Project structure

- `app/main.py` - FastAPI app, dashboard rendering, and logistics labels
- `app/scraper.py` - page scraper, visible text extraction, duplicate prevention
- `app/parser.py` - detects Senate procedural phrases that may affect coverage logistics and returns alerts
- `app/database.py` - SQLite database model and initialization
- `templates/index.html` - webpage template
- `static/style.css` - page styling
- `data/senate_wire.db` - SQLite database file created at runtime

## Notes

- The page route only reads from the database; it does not scrape again on every reload.
- The refresher runs in the background and only stores new logistics-relevant alerts.
- If you change parser rules, restart the app and delete `data/senate_wire.db` to reset local runtime data.
