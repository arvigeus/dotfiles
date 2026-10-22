# Lets `python3 -m unittest tests/test_x.py` resolve the shared `support` module.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
