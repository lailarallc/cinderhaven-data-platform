"""dbt assets loaded into Dagster.

Uses dagster-dbt to automatically create one Dagster asset per dbt model,
preserving the full dependency graph (staging → intermediate → marts).
"""

from dagster import AssetExecutionContext
from dagster_dbt import DbtCliResource, dbt_assets, DagsterDbtTranslator

from . import prod_guard
from .project import DBT_PROJECT_DIR, DBT_PROFILES_DIR, DBT_EXECUTABLE


dbt_resource = DbtCliResource(
    project_dir=str(DBT_PROJECT_DIR),
    profiles_dir=str(DBT_PROFILES_DIR),
    dbt_executable=DBT_EXECUTABLE,
)

# Parse the dbt manifest at load time so Dagster knows the asset graph.
dbt_manifest_path = dbt_resource.cli(
    ["--quiet", "parse"],
    target_path=DBT_PROJECT_DIR / "target",
).target_path.joinpath("manifest.json")


@dbt_assets(manifest=dbt_manifest_path)
def cinderhaven_dbt_assets(context: AssetExecutionContext, dbt: DbtCliResource):
    """Materialize all dbt models as Dagster assets."""
    # dbt connects on its own. Target is the `cinderhaven` profile in ~/.dbt/profiles.yml.
    prod_guard.check(host="localhost", port=5432)
    # Path 5 (plan U4): refuse a superuser or a login with truth access before
    # building. Landed after the owner created cinderhaven_dagster (2026-11-10).
    dbt.cli(["run-operation", "assert_scoped_login"], manifest=dbt_manifest_path).wait()
    yield from dbt.cli(["build"], context=context).stream()
