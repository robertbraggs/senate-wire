import hashlib
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from app.parser import normalize_line, is_generic_line
from app.database import SessionLocal, SourceSnapshot

SOURCES = [
    {
        'name': 'Senate Daily Press',
        'url': 'https://www.dailypress.senate.gov/'
    },
    {
        'name': 'Senate Democrats Floor',
        'url': 'https://www.democrats.senate.gov/floor'
    }
]


def clean_content(html: str, source_name: str) -> str:
    soup = BeautifulSoup(html, 'html.parser')
    # Remove script and style tags only
    for tag in soup(['script', 'style', 'noscript']):
        tag.decompose()

    # Get all visible text
    text = soup.get_text(separator='\n')
    
    # Minimal filtering: keep lines with Senate-related keywords or times
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line or len(line) < 5:
            continue
        
        lower_line = line.lower()
        # Keep if contains Senate keywords or time references
        if any(kw in lower_line for kw in ['senate', 'vote', 'cloture', 'resolution', 'nomination', 'confirmation', 'leader', 'floor']):
            lines.append(line)
        elif any(time_fmt in lower_line for time_fmt in ['a.m.', 'p.m.', 'a.m', 'p.m']):
            lines.append(line)
    
    return '\n'.join(lines)


def compute_hash(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def run_scrape() -> int:
    db = SessionLocal()
    saved_count = 0

    combined_text = []
    for source in SOURCES:
        try:
            response = requests.get(source['url'], timeout=20)
            response.raise_for_status()
            cleaned = clean_content(response.text, source['name'])
            combined_text.append(f"Source: {source['name']}\n{cleaned}")
        except Exception as e:
            print(f'Error scraping {source["url"]}: {e}')

    full_text = '\n\n'.join(combined_text)
    content_hash = compute_hash(full_text)

    snapshot = db.query(SourceSnapshot).filter_by(source_url=SOURCES[0]['url']).first()  # Use first source URL as key
    if snapshot and snapshot.content_hash == content_hash:
        snapshot.checked_at = datetime.utcnow()
        snapshot.extracted_text = full_text
        db.commit()
        return saved_count

    if snapshot:
        snapshot.content_hash = content_hash
        snapshot.extracted_text = full_text
        snapshot.checked_at = datetime.utcnow()
    else:
        snapshot = SourceSnapshot(
            source_name=SOURCES[0]['name'],
            source_url=SOURCES[0]['url'],
            content_hash=content_hash,
            extracted_text=full_text,
            checked_at=datetime.utcnow()
        )
        db.add(snapshot)

    db.commit()
    saved_count = 1
    db.close()
    return saved_count
