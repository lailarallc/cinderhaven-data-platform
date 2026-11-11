-- Cinderhaven roles: who may read and write each generated schema (plan U4).
--
-- Applied once per cluster by the administrator connection, and idempotent:
-- running it twice leaves one set of roles. CREATE ROLE is cluster-level, so
-- DROP SCHEMA never removes a role. Every role here is NOLOGIN; logins are
-- members of these roles, so grants live in one place.
--
-- Production is applied by the owner, running a script a session hands over;
-- no session applies this to production (owner, 2026-11-09).
--
--   cinderhaven_generator  owns raw, costing, copack, voidfinder and truth; the only
--                          role with write on truth; a member of cinderhaven_dbt
--                          (seed_all.py drops the dbt schemas on every run)
--   cinderhaven_dbt        reads raw, costing, copack; builds the dbt schemas; no USAGE on truth
--   cinderhaven_reader     SELECT on raw, costing, copack, voidfinder, the dbt schemas; no USAGE on truth
--   cinderhaven_validator  SELECT on truth and every generated schema; writes nothing.
--                          NOLOGIN everywhere; only the harness gives it LOGIN, on its own instance
--
-- Named in the plan and not created here: cinderhaven_preserve_hash (a login U12
-- creates, granted by each owning repo) and cinderhaven_counterfactual (Phase 4).

DO $$
DECLARE r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['cinderhaven_generator', 'cinderhaven_dbt',
                             'cinderhaven_reader', 'cinderhaven_validator'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE', r);
        END IF;
    END LOOP;
END $$;

GRANT cinderhaven_dbt TO cinderhaven_generator;

-- The generator and the dbt role create schemas; nothing else does.
DO $$
BEGIN
    EXECUTE format('GRANT CONNECT, CREATE ON DATABASE %I TO cinderhaven_generator, cinderhaven_dbt',
                   current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO cinderhaven_reader, cinderhaven_validator',
                   current_database());
END $$;

-- On a host whose schemas predate the roles (production until U12), hand raw
-- and costing and their tables to the generator and grant on what exists.
-- copack and voidfinder are written by other repos' logins (production's copack
-- is owned by flypgadmin, 2026-11-11), and writer repos keep writing their own
-- tables (owner, 2026-11-11): their owners stay, and they get read grants only.
-- Elsewhere the grants travel with each schema's own DDL.
DO $$
DECLARE s text; t record;
BEGIN
    FOREACH s IN ARRAY ARRAY['raw', 'costing', 'copack', 'voidfinder'] LOOP
        IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = s) THEN
            IF s IN ('raw', 'costing') THEN
                EXECUTE format('ALTER SCHEMA %I OWNER TO cinderhaven_generator', s);
                FOR t IN SELECT c.relname, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                         WHERE n.nspname = s AND c.relkind IN ('r', 'p', 'v', 'm') LOOP
                    EXECUTE format('ALTER %s %I.%I OWNER TO cinderhaven_generator',
                                   CASE t.relkind WHEN 'v' THEN 'VIEW' WHEN 'm' THEN 'MATERIALIZED VIEW'
                                                  ELSE 'TABLE' END, s, t.relname);
                END LOOP;
            END IF;
            EXECUTE format('GRANT USAGE ON SCHEMA %I TO cinderhaven_reader, cinderhaven_validator', s);
            EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO cinderhaven_reader, cinderhaven_validator', s);
            EXECUTE format('GRANT SELECT ON ALL SEQUENCES IN SCHEMA %I TO cinderhaven_reader', s);
            IF s <> 'voidfinder' THEN
                EXECUTE format('GRANT USAGE ON SCHEMA %I TO cinderhaven_dbt', s);
                EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO cinderhaven_dbt', s);
            END IF;
        END IF;
    END LOOP;
END $$;

-- The dbt schemas keep their owner (path 5; owner, 2026-11-11): another repo
-- (dimension-weight-integrity) writes its own relations into them until U12
-- moves it to its own schema, and writer repos keep their own tables. The dbt
-- role gets CREATE and USAGE (with grant option, for dbt's on-run-end grant).
-- Only the relations this project's dbt builds change owner, and that list
-- comes from cinderhaven/models, so scripts/apply_truth_roles.py makes those
-- transfers in the same transaction; every other relation keeps its owner.
-- dbt's +grants and on-run-end hook keep the readers' grants after each build.
DO $$
DECLARE s text;
BEGIN
    FOREACH s IN ARRAY ARRAY['public_staging', 'public_intermediate', 'public_marts'] LOOP
        IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = s) THEN
            EXECUTE format('GRANT USAGE ON SCHEMA %I TO cinderhaven_dbt WITH GRANT OPTION', s);
            EXECUTE format('GRANT CREATE ON SCHEMA %I TO cinderhaven_dbt', s);
            EXECUTE format('GRANT USAGE ON SCHEMA %I TO cinderhaven_reader, cinderhaven_validator', s);
            EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO cinderhaven_reader, cinderhaven_validator', s);
        END IF;
    END LOOP;
END $$;

-- truth_populated(): one boolean, false where truth does not exist. It lives in
-- public, not truth: truth is dropped on every rebuild and the reader has no
-- USAGE on it, so a guard that probed truth directly would fail on permission.
-- SECURITY DEFINER, owned by the generator; it returns a boolean and nothing
-- else, never a count (an aggregate of truth is truth).
CREATE OR REPLACE FUNCTION public.truth_populated() RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE t record; found boolean := false;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'truth') THEN
        RETURN false;
    END IF;
    FOR t IN SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'truth' AND c.relkind = 'r' LOOP
        EXECUTE format('SELECT EXISTS (SELECT 1 FROM truth.%I)', t.relname) INTO found;
        IF found THEN
            RETURN true;
        END IF;
    END LOOP;
    RETURN false;
END $$;
ALTER FUNCTION public.truth_populated() OWNER TO cinderhaven_generator;
REVOKE ALL ON FUNCTION public.truth_populated() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.truth_populated() TO cinderhaven_reader, cinderhaven_validator, cinderhaven_generator;
