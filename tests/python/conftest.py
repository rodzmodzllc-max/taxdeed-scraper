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


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_discovery_guard_leak():
    """A test that runs a discovery script's main() installs the process-wide
    discovery guard (harvesters/governance/discovery_guard.py). Remove it
    afterwards so it cannot refuse requests in an unrelated later test."""
    yield
    from harvesters.governance import discovery_guard as DG
    DG.uninstall()
