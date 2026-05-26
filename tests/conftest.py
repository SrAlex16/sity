from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

os.environ.setdefault("SITY_PROJECT_ROOT", str(ROOT))
os.environ.setdefault("SITY_AI_PROVIDER", "mock")
