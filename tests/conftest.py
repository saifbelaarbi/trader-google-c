"""Shared pytest setup.

Puts ``ftbot/strategies`` on ``sys.path`` so the dependency-free research helpers
(``research_sizing``) can be imported directly in tests without installing
freqtrade or the TA-Lib C library.
"""

import sys
from pathlib import Path

_STRATEGIES_DIR = Path(__file__).resolve().parents[1] / "ftbot" / "strategies"
if str(_STRATEGIES_DIR) not in sys.path:
    sys.path.insert(0, str(_STRATEGIES_DIR))
