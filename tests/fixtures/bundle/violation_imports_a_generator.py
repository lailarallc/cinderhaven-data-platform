"""A scan-root module that puts the bundle on its path and imports a generator by bare name (must be rejected)."""
import sys

sys.path.insert(0, "vendor/realism")
import group10_floors  # noqa: E402
