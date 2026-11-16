"""A scan-root module that imports U15's loader the way a seeder does (must be rejected by U4's ban)."""
from realism_bundle import load

schedule = load().ap_schedule()
