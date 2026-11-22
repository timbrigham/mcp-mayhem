"""Make `reservoir_core` and `reservoir_server` importable when running pytest from here."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
