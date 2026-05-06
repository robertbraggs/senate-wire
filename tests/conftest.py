import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault('SENATE_WIRE_DATABASE_URL', f"sqlite:///{ROOT / 'tests' / '.test_senate_wire.db'}")
os.environ.setdefault('DISABLE_SOURCE_REFRESHER', 'true')
