"""Make the project root importable so from src.component import ...
works whether pytest is invoked from the project root or from within an
IDE that uses a different working directory."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
