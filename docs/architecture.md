# Cinderhaven Data Platform — Architecture

```mermaid
graph LR
    subgraph Sources
        A1[("One catalog<br/>generation/seed_config.py")]
        A2[("Generators<br/>generation/seed_*.py · run seed")]
    end

    subgraph Ingestion
        B["The one entry point<br/>generation/seed_all.py"]
    end

    subgraph "Postgres on Fly.io"
        direction TB
        subgraph raw["raw · 41 tables"]
            C1["catalogue · retailers · stores<br/>distributors · DTC channels"]
            C2["orders · shipments · receipts<br/>pack records · scan data"]
            C3["deductions · disputes · evidence<br/>remittances · chargebacks"]
            C4["shopify orders · refunds<br/>payouts · chargebacks"]
        end
        CO["costing · 8 tables"]
        CP["copack · 5 tables"]
        VF["voidfinder · 1 table"]
        TR["truth · 6 tables<br/>generator writes · validator reads"]
    end

    subgraph "dbt transformation"
        direction TB
        D["Staging<br/>41 views"]
        E["Intermediate<br/>14 views"]
        F["Marts<br/>32 tables"]
    end

    subgraph Orchestration
        G["Dagster<br/>dbt assets · daily schedule"]
    end

    subgraph Quality
        H["dbt build<br/>371 tests"]
        I["Harness<br/>tests/harness.py · 30 run seeds"]
    end

    A1 --> B
    A2 --> B
    B --> raw
    B --> CO
    B --> CP
    B --> VF
    B --> TR
    raw --> D
    D --> E
    E --> F
    G -. "orchestrates" .-> D
    H -. "validates" .-> F
    I -. "rebuilds and judges" .-> B

    style Sources fill:#1a1a2e,stroke:#e94560,color:#fff
    style raw fill:#16213e,stroke:#0f3460,color:#fff
```

Counts are run seed 0's world as the harness builds it (2026-11-14). Truth's
tables are named, never counted by row (plan U4).

## Pipeline flow

1. **Sources** — one catalogue, `generation/seed_config.py`, read by every
   generator in `generation/`. `CINDERHAVEN_RUN_SEED` picks the world; run
   seed 0 is today's (plan U2).

2. **Ingestion** — `generation/seed_all.py` is the only write path. In order:
   DDL for raw, truth, costing and copack's five tables; the raw generators
   (shared, retailer, distributor, DTC, scan data, void patterns); product
   master history; copack; a dbt staging build; costing, which reads staging;
   the full `dbt build`; `verify_counts`. dbt is handed the instance the run
   seeded and refuses another.

3. **Schemas** — `raw` 41 tables; `costing` 8; `copack` 5 (that repo's
   snapshot tables are left alone); `voidfinder.store_addresses`; `truth` 6,
   which the generator owns and writes, the validator reads, and no other role
   can reach. Run seed 0 writes 2,305,509 rows outside truth.

4. **Staging** — 41 dbt views over `raw`: type casting, renaming, null
   handling.

5. **Intermediate** — 14 dbt views: the unions across channels, the deduction
   crosswalk, partner resolution, DTC order economics, loaded contribution and
   shelf-space cost by SKU.

6. **Marts** — 32 dbt tables: 7 dimensions, 19 facts, 6 marts (channel
   contribution, three reconciliations, quarterly SPPD, SKU scan totals).

7. **Quality** — `dbt build` runs 371 tests, among them 13 singular tests
   (five are bands). `tests/test_costing_integrity.sql` checks costing's
   referential and rollup integrity. `tests/harness.py` rebuilds the world on
   a local instance; `tests/seed_runs.py` rebuilds it at run seeds 0–29 and
   saves each seed's gates, world hashes and band values.

8. **Orchestration** — Dagster loads every dbt model as an asset and checks
   its login is scoped (`assert_scoped_login`) before building. Its daily
   schedule is 6 AM UTC; nothing runs that schedule against production today.

9. **CI** — `.github/workflows/`: `ci.yml` (fast tier and the truth
   quarantine), `canonical-drift.yml`, `verify-production-figures.yml` (as the
   reader login), and `deploy-costing.yml`, which refuses every dispatch until
   plan U12.
