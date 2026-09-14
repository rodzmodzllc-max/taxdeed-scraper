"""Makes the repo root importable as `harvesters.governance....` regardless
of where pytest is invoked from (matches this repo's existing pattern of
each script computing its own path relative to __file__ rather than
trusting cwd - see e.g. texas_harvester.py's `HERE = Path(__file__).parent`).
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
