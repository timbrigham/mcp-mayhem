"""Put the package root on sys.path so ``import core`` / ``import consumers``
works when running pytest from this directory without an editable install."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
