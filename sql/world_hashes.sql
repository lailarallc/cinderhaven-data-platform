-- World hashes (plan U2): one row per generated table, its row count and an
-- order-independent content hash, the md5-over-sorted-rows form of
-- deploy-costing.yml's protected-table hashes. Read-only.
--
-- Covers raw, costing, copack and voidfinder. Never truth: a hash of truth is
-- an aggregate of it, and an aggregate of truth is truth (plan U4, path 7).
-- Characterize off the shared host only: production holds other repos' writes.
--
--   psql -tA -F '|' -f sql/world_hashes.sql
SELECT n.nspname || '.' || c.relname AS table_name,
       (xpath('/row/n/text()', x))[1]::text::bigint AS row_count,
       (xpath('/row/h/text()', x))[1]::text AS content_hash
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
CROSS JOIN LATERAL query_to_xml(
    format('SELECT count(*) AS n, md5(coalesce(string_agg(t::text, %L ORDER BY t::text), %L)) AS h FROM %I.%I t',
           '|', '', n.nspname, c.relname),
    false, true, '') AS x
WHERE n.nspname IN ('raw', 'costing', 'copack', 'voidfinder')
  AND c.relkind IN ('r', 'p') AND NOT c.relispartition
ORDER BY 1;
