"""Make `guard_coverage` and the test helpers importable when running pytest from here."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "tests"))
