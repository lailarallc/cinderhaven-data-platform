"""Seed generator for scan_data with velocity delist signals.

Generates weekly POS scan data (sku × store × week_ending) covering
~2 years. Most SKU-store combinations have healthy velocity. A curated
subset of 3-5 SKUs per retailer have organically low/declining velocity
to trigger realistic delist risk signals in the Velocity Decision Tool.

Delist-risk patterns:
  - Low baseline units_sold (1-3 per week vs healthy 5-20)
  - Sparse weeks (gaps in reporting — missing weeks)
  - Declining trend over time (units drop quarter over quarter)
  - Different underperforming SKUs at different retailers

Delist thresholds stay at realistic CPG industry values (10-15 USPW).
The data tells the story — no artificial threshold inflation.

Requires seed_shared.py to have been run first (stores, products exist).

Usage:
    python generation/seed_scan_data.py
"""
from __future__ import annotations

import io
import psycopg2
from datetime import date, timedelta

from seed_config import (
    ALL_SKUS, CHANNEL_VELOCITY_MULT, DATABASE_URL, RETAILERS, SEASONALITY,
    WINDOW_START, WINDOW_END, init_rng,
    SKU_ARCHETYPES, ARCHETYPE_VELOCITY_MULT,
    get_sku_seasonal,
)

# Map each retailer to 3-5 SKUs that will underperform at that retailer.
# Different SKUs struggle at different retailers — realistic pattern.
DELIST_RISK_SKUS = {
    "RET-WALMART": ["CHP-SC-008", "CHP-PS-007", "CHP-AS-009", "CHP-SC-010"],
    "RET-COSTCO": ["CHP-AS-003", "CHP-PS-006", "CHP-SC-005"],
    "RET-WHOLEFOODS": ["CHP-PS-001", "CHP-AS-010", "CHP-SC-003", "CHP-AS-005"],
    "RET-SPROUTS": ["CHP-AS-006", "CHP-PS-004", "CHP-SC-007"],
    "RET-KROGER": ["CHP-SC-002", "CHP-PS-008", "CHP-AS-004", "CHP-SC-009"],
    "RET-REGIONAL": ["CHP-PS-010", "CHP-AS-007", "CHP-SC-006"],
}

# 1-2 SKUs per retailer in the warning zone: above threshold but declining.
# These started healthy and are losing velocity — early warning signal.
BORDERLINE_SKUS = {
    "RET-WALMART": ["CHP-AS-002", "CHP-SC-004"],
    "RET-COSTCO": ["CHP-PS-009", "CHP-SC-007"],
    "RET-WHOLEFOODS": ["CHP-SC-002", "CHP-AS-008"],
    "RET-SPROUTS": ["CHP-SC-001", "CHP-PS-003"],
    "RET-KROGER": ["CHP-AS-005", "CHP-SC-001"],
    "RET-REGIONAL": ["CHP-PS-001", "CHP-SC-009"],
}


def get_week_endings(start: date, end: date) -> list[date]:
    """Generate Saturday week-ending dates covering the window."""
    weeks = []
    current = start + timedelta(days=(5 - start.weekday()) % 7)
    while current <= end:
        weeks.append(current)
        current += timedelta(weeks=1)
    return weeks


def generate_healthy_velocity(rng, sku_info, week: date, volume_tier: str,
                              channel_mult: float = 1.0,
                              archetype_mult: float = 1.0,
                              decline_factor: float = 1.0,
                              seasonal: float | None = None) -> tuple[int, float]:
    """Generate scan data for a SKU-store-week, scaled by archetype."""
    base_units = {"high": 15, "medium": 8, "low": 4}[volume_tier]
    if seasonal is None:
        seasonal = SEASONALITY.get(week.month, 1.0)

    line_mult = {
        "Artisan Sauces": 1.2,
        "Pantry Staples": 1.0,
        "Specialty Condiments": 0.85,
    }.get(sku_info["product_line"], 1.0)

    adjusted = base_units * seasonal * line_mult * channel_mult * archetype_mult * decline_factor
    std_dev = base_units * 0.3 * channel_mult * max(archetype_mult, 0.5)
    units = max(1, int(rng.gauss(adjusted, std_dev)))
    unit_price = sku_info["msrp"]
    dollars = round(units * unit_price * rng.uniform(0.85, 1.05), 2)
    return units, dollars


def generate_delist_risk_velocity(rng, sku_info, week: date, volume_tier: str,
                                  week_index: int, total_weeks: int,
                                  channel_mult: float = 1.0,
                                  seasonal: float | None = None) -> tuple[int, float] | None:
    """Generate declining/sparse velocity for delist-risk SKUs.

    Returns None to simulate a missing week (sparse reporting).
    """
    sparsity_rate = 0.15 + 0.15 * (week_index / total_weeks)
    if rng.random() < sparsity_rate:
        return None

    base = rng.uniform(1.5, 3.5) * channel_mult

    decline_factor = 1.0 - 0.5 * (week_index / total_weeks)
    decline_factor = max(0.2, decline_factor)

    if seasonal is None:
        seasonal = SEASONALITY.get(week.month, 1.0)
    units = max(1, int(base * decline_factor * seasonal + rng.gauss(0, 0.5 * channel_mult)))

    unit_price = sku_info["msrp"]
    dollars = round(units * unit_price * rng.uniform(0.80, 1.0), 2)
    return units, dollars


# Per-retailer target velocity for borderline SKUs (just above threshold).
# These values land in the warning zone: threshold < velocity < 1.5 * threshold.
_BORDERLINE_TARGETS = {
    "RET-WALMART": 3.0,     # threshold 2.5, warning zone 2.5-3.75
    "RET-COSTCO": 12.0,     # threshold 10.0, warning zone 10.0-15.0
    "RET-WHOLEFOODS": 2.1,  # threshold 1.5, warning zone 1.5-2.25 (higher to survive int rounding)
    "RET-KROGER": 3.0,      # threshold 2.5, warning zone 2.5-3.75
    "RET-SPROUTS": 2.1,     # threshold 1.5, warning zone 1.5-2.25
    "RET-REGIONAL": 2.1,    # threshold 1.5, warning zone 1.5-2.25
}


def generate_borderline_velocity(rng, sku_info, week: date, volume_tier: str,
                                 week_index: int, total_weeks: int,
                                 target_v: float) -> tuple[int, float]:
    """Generate velocity that starts healthy and declines into the warning zone.

    Recent weeks produce velocity near target_v (just above threshold).
    Earlier weeks produce higher velocity (so trailing > current = declining).
    No seasonality — a product losing traction doesn't bounce back for holidays.
    Low noise so the decline signal is clear in the 8-week rolling averages.
    """
    progress = week_index / total_weeks
    period_mult = 3.0 - 2.0 * progress

    base = target_v * period_mult
    units = max(1, int(rng.gauss(base, base * 0.08)))

    unit_price = sku_info["msrp"]
    dollars = round(units * unit_price * rng.uniform(0.88, 1.02), 2)
    return units, dollars


def main():
    print("Connecting to Postgres...")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    cur = conn.cursor()

    rng = init_rng(seed=400)

    # Load stores from DB
    cur.execute("SELECT store_id, retailer_id, volume_tier FROM raw.stores")
    stores = cur.fetchall()
    print(f"Loaded {len(stores)} stores")

    # Build lookup
    sku_map = {p["sku"]: p for p in ALL_SKUS}
    weeks = get_week_endings(WINDOW_START, WINDOW_END)
    total_weeks = len(weeks)
    print(f"Generating scan data for {total_weeks} weeks...")

    # Load distribution_log to know which SKUs are authorized at which stores
    cur.execute("SELECT sku, store_id, authorized_date, deauthorized_date FROM raw.distribution_log")
    dist_log = cur.fetchall()
    authorized = {}
    for sku, store_id, auth_date, deauth_date in dist_log:
        auth = auth_date if isinstance(auth_date, date) else (date.fromisoformat(auth_date) if auth_date else WINDOW_START)
        deauth = deauth_date if isinstance(deauth_date, date) else (date.fromisoformat(deauth_date) if deauth_date else WINDOW_END + timedelta(days=365))
        if not deauth:
            deauth = WINDOW_END + timedelta(days=365)
        authorized[(sku, store_id)] = (auth, deauth)

    print(f"Loaded {len(authorized)} distribution authorizations")

    arch_rng = init_rng(seed=450)
    sku_vel_mult = {}
    for p in ALL_SKUS:
        archetype = SKU_ARCHETYPES.get(p["sku"], "moderate")
        low, high = ARCHETYPE_VELOCITY_MULT.get(archetype, (0.9, 1.8))
        sku_vel_mult[p["sku"]] = arch_rng.uniform(low, high)

    # Normalize so distribution-weighted mean velocity is 1.0
    # (archetype multipliers average ~1.82× without this correction)
    sku_slot_count = {}
    for (sku, store_id) in authorized:
        sku_slot_count[sku] = sku_slot_count.get(sku, 0) + 1
    weighted_vel = sum(sku_vel_mult.get(sku, 1.0) * count for sku, count in sku_slot_count.items())
    total_slots = sum(sku_slot_count.values())
    weighted_mean = weighted_vel / total_slots if total_slots > 0 else 1.0
    sku_vel_mult = {sku: v / weighted_mean for sku, v in sku_vel_mult.items()}
    print(f"Velocity normalization: weighted_mean={weighted_mean:.4f}, total_slots={total_slots}")

    CHUNK_SIZE = 50000
    rows_buf = []
    total_rows = 0

    for week_idx, week in enumerate(weeks):
        for store_id, retailer_id, volume_tier in stores:
            store_skus = [
                sku for sku in sku_map
                if (sku, store_id) in authorized
                and authorized[(sku, store_id)][0] <= week <= authorized[(sku, store_id)][1]
            ]

            delist_skus = set(DELIST_RISK_SKUS.get(retailer_id, []))
            border_skus = set(BORDERLINE_SKUS.get(retailer_id, []))
            ch_mult = CHANNEL_VELOCITY_MULT.get(retailer_id, 1.0)
            border_target = _BORDERLINE_TARGETS.get(retailer_id, 2.0)

            for sku in store_skus:
                sku_info = sku_map[sku]
                seasonal = get_sku_seasonal(sku, week.month)

                if sku in delist_skus:
                    result = generate_delist_risk_velocity(
                        rng, sku_info, week, volume_tier or "medium",
                        week_idx, total_weeks, ch_mult,
                        seasonal=seasonal,
                    )
                    if result is None:
                        continue
                    units, dollars = result
                elif sku in border_skus:
                    units, dollars = generate_borderline_velocity(
                        rng, sku_info, week, volume_tier or "medium",
                        week_idx, total_weeks, border_target
                    )
                else:
                    archetype = SKU_ARCHETYPES.get(sku, "moderate")
                    decline = 1.0
                    if archetype == "at_risk":
                        progress = week_idx / total_weeks
                        decline = 1.3 - 0.9 * progress
                    elif archetype == "fading":
                        progress = week_idx / total_weeks
                        decline = 1.3 - 0.9 * progress
                    units, dollars = generate_healthy_velocity(
                        rng, sku_info, week, volume_tier or "medium", ch_mult,
                        archetype_mult=sku_vel_mult[sku],
                        decline_factor=decline,
                        seasonal=seasonal,
                    )

                rows_buf.append((sku, store_id, str(week), units, dollars))

                if len(rows_buf) >= CHUNK_SIZE:
                    buf = io.StringIO()
                    for row in rows_buf:
                        buf.write("\t".join(str(v) for v in row) + "\n")
                    buf.seek(0)
                    sql = "COPY raw.scan_data (sku, store_id, week_ending, units_sold, dollars_sold) FROM STDIN WITH (FORMAT text)"
                    cur.copy_expert(sql, buf)
                    total_rows += len(rows_buf)
                    rows_buf = []
                    if total_rows % 200000 == 0:
                        print(f"  ...{total_rows:,} rows written")

    # Flush remaining
    if rows_buf:
        buf = io.StringIO()
        for row in rows_buf:
            buf.write("\t".join(str(v) for v in row) + "\n")
        buf.seek(0)
        sql = "COPY raw.scan_data (sku, store_id, week_ending, units_sold, dollars_sold) FROM STDIN WITH (FORMAT text)"
        cur.copy_expert(sql, buf)
        total_rows += len(rows_buf)

    conn.commit()
    print(f"\n  scan_data: {total_rows:,} rows committed")

    # Print delist-risk summary
    print("\nDelist-risk SKU assignments:")
    for rid, skus in DELIST_RISK_SKUS.items():
        names = [sku_map[s]["product_name"] for s in skus if s in sku_map]
        print(f"  {rid}: {', '.join(names)}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
