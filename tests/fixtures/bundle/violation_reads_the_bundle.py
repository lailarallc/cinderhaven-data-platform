"""A scan-root module that reads the bundle's outputs directly (must be rejected by U4's ban)."""
import json
from pathlib import Path

OUT = json.loads(Path("vendor/realism/outputs.json").read_text())
