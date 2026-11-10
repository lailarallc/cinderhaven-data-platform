-- One probe row so the dump test runs against a populated truth schema (CI dbt-quarantine).
INSERT INTO truth.defect_ledger (sku, defect_type) VALUES ('probe', 'probe');
