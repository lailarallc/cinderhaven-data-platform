{#
  Path 5's check (plan U4; DECISIONS#u4-custody-shape): refuse to build as a
  superuser, or as a login with USAGE on the truth schema. A superuser ignores
  every grant, so the quarantine means nothing under one. Dagster runs this
  before its build; if it fires in production, Dagster's credential moved off
  its own login (cinderhaven_dagster), which is what it is there to catch.

    dbt run-operation assert_scoped_login
#}
{% macro assert_scoped_login() %}
  {% set q %}
    select r.rolname,
           r.rolsuper,
           case when exists (select 1 from pg_namespace where nspname = 'truth')
                then has_schema_privilege(current_user, 'truth', 'USAGE') else false end as truth_usage
    from pg_roles r where r.rolname = current_user
  {% endset %}
  {% if execute %}
    {% set row = run_query(q).rows[0] %}
    {% if row[1] %}
      {{ exceptions.raise_compiler_error("Refusing to build: dbt is connected as " ~ row[0] ~ ", a superuser. "
         ~ "Dagster's profile must use its own login in cinderhaven_dbt (DECISIONS#u4-custody-shape).") }}
    {% endif %}
    {% if row[2] %}
      {{ exceptions.raise_compiler_error("Refusing to build: " ~ row[0] ~ " holds USAGE on the truth schema.") }}
    {% endif %}
    {{ log("assert_scoped_login: " ~ row[0] ~ " is not a superuser and has no truth access", info=True) }}
  {% endif %}
{% endmacro %}
