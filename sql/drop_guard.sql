-- drop_guard.sql: may a rebuild drop what this instance holds? (plan U2)
--
-- One row per refusal, zero rows to pass: the shape of
-- tests/test_costing_integrity.sql. deploy-costing.yml's Step 0 runs it before
-- seed_all.py drops raw, costing, copack's five tables, truth and the
-- public_* schemas; the harness proves it against fixtures (tests/test_drop_guard.py).
--
-- Inputs, as session settings (SET drop_guard.<name> = '...') before this file:
--   force_recreate  'true' lets a populated raw, costing, copack or truth be
--                   dropped. It overrides nothing else.
--   expected        comma-separated schema.relation the platform defines:
--                   sql/raw_schema.sql's tables and dbt's manifest relations.
--   raw_reference   JSON {table: [column, ...]}: sql/raw_schema.sql at the
--                   platform commit before U8's first DDL edit. Its tables
--                   count as expected too.
--   leftover        comma-separated schema.relation a consumer wrote and U19
--                   moves; each passes the platform-relation and column arms.
--                   Empty until U12 fills it from the read map.
-- A missing expected or raw_reference refuses: the guard does not guess.
--
-- Every relation and column is read from pg_class, pg_namespace and
-- pg_attribute, which every role can read, never from information_schema,
-- which shows a login only what it may select. truth is read through
-- public.truth_populated() (sql/truth_roles.sql): a boolean, never a count,
-- and no refusal prints one.

CREATE OR REPLACE FUNCTION pg_temp.drop_guard() RETURNS TABLE (refusal text)
LANGUAGE plpgsql AS $$
DECLARE
    force    boolean := coalesce(current_setting('drop_guard.force_recreate', true), '') = 'true';
    exp_in   text    := current_setting('drop_guard.expected', true);
    ref_in   text    := current_setting('drop_guard.raw_reference', true);
    left_in  text    := coalesce(current_setting('drop_guard.leftover', true), '');
    expected text[];
    leftover text[];
    ref      jsonb;
    r        record;
    held     boolean;
    missing  text;
    extra    text;
BEGIN
    IF coalesce(exp_in, '') = '' THEN
        refusal := 'input missing: drop_guard.expected (raw_schema.sql tables and the dbt manifest)';
        RETURN NEXT;
    END IF;
    IF coalesce(ref_in, '') = '' THEN
        refusal := 'input missing: drop_guard.raw_reference (the pre-regen raw_schema.sql columns)';
        RETURN NEXT;
    END IF;
    IF coalesce(exp_in, '') = '' OR coalesce(ref_in, '') = '' THEN
        RETURN;
    END IF;
    ref := ref_in::jsonb;
    leftover := array(SELECT btrim(x) FROM unnest(string_to_array(left_in, ',')) x WHERE btrim(x) <> '');
    expected := array(SELECT btrim(x) FROM unnest(string_to_array(exp_in, ',')) x WHERE btrim(x) <> '')
                || array(SELECT 'raw.' || k FROM jsonb_object_keys(ref) k);

    -- Arm 1: the generated tables. Populated refuses unless force_recreate;
    -- a table this login cannot read refuses, since its state is unknown.
    FOR r IN SELECT c.oid, n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE c.relkind IN ('r', 'p')
               AND (n.nspname IN ('raw', 'costing')
                    OR (n.nspname = 'copack' AND c.relname IN ('co_packers', 'production_lines',
                        'sku_production_config', 'production_schedule', 'sku_inventory')))
             ORDER BY 2, 3 LOOP
        IF NOT has_table_privilege(r.oid, 'SELECT') THEN
            refusal := format('unreadable: %I.%I (cannot tell whether it holds rows)', r.nspname, r.relname);
            RETURN NEXT;
            CONTINUE;
        END IF;
        EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I.%I)', r.nspname, r.relname) INTO held;
        IF held AND NOT force THEN
            refusal := format('populated: %I.%I (re-dispatch with force_recreate to drop it)', r.nspname, r.relname);
            RETURN NEXT;
        END IF;
    END LOOP;

    -- Arm 2: truth. No schema, nothing to destroy. Present: populated refuses
    -- unless force_recreate; a state that cannot be read refuses outright.
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'truth') THEN
        BEGIN
            EXECUTE 'SELECT public.truth_populated()' INTO held;
        EXCEPTION WHEN OTHERS THEN
            held := NULL;
        END;
        IF held IS NULL THEN
            refusal := 'truth: schema present, populated state unreadable (public.truth_populated())';
            RETURN NEXT;
        ELSIF held AND NOT force THEN
            refusal := 'truth: populated (re-dispatch with force_recreate to drop it)';
            RETURN NEXT;
        END IF;
    END IF;

    -- Arm 3: anything in public, raw or the public_* schemas the platform does
    -- not define is a consumer writer's. force_recreate does not override it.
    FOR r IN SELECT n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f') AND NOT c.relispartition
               AND n.nspname IN ('public', 'raw', 'public_staging', 'public_intermediate', 'public_marts')
               AND NOT (n.nspname || '.' || c.relname) = ANY (expected)
               AND NOT (n.nspname || '.' || c.relname) = ANY (leftover)
             ORDER BY 1, 2 LOOP
        refusal := format('not the platform''s: %I.%I (absent from raw_schema.sql and the dbt manifest; '
                          'name it in the leftover list once U19 records it)', r.nspname, r.relname);
        RETURN NEXT;
    END LOOP;

    -- Arm 4: a platform raw table whose columns differ from the pre-regen
    -- reference, either way. force_recreate does not override it.
    FOR r IN SELECT c.oid, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'raw' AND c.relkind IN ('r', 'p') AND ref ? c.relname
               AND NOT ('raw.' || c.relname) = ANY (leftover)
             ORDER BY 2 LOOP
        SELECT string_agg(col, ', ' ORDER BY col) INTO missing
          FROM jsonb_array_elements_text(ref -> r.relname) col
         WHERE col NOT IN (SELECT attname FROM pg_attribute WHERE attrelid = r.oid AND attnum > 0 AND NOT attisdropped);
        SELECT string_agg(attname::text, ', ' ORDER BY attname) INTO extra
          FROM pg_attribute WHERE attrelid = r.oid AND attnum > 0 AND NOT attisdropped
           AND attname::text NOT IN (SELECT jsonb_array_elements_text(ref -> r.relname));
        IF missing IS NOT NULL OR extra IS NOT NULL THEN
            refusal := format('columns differ from the pre-regen reference: raw.%I (missing: %s; extra: %s)',
                              r.relname, coalesce(missing, 'none'), coalesce(extra, 'none'));
            RETURN NEXT;
        END IF;
    END LOOP;
END $$;

SELECT refusal FROM pg_temp.drop_guard();
