"""Plan U2: one catalog. The SKU sets other paths key on live in seed_config.py.

Fast tier: reads source files and imports seed_config; no database.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

GEN = Path(__file__).resolve().parent.parent / "generation"


def sku_literals(source: str) -> list[str]:
    """Module-level names assigned a container literal holding a CHP- SKU code."""
    out = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and not isinstance(node.value, (ast.Constant, ast.Name, ast.Call)):
            if any(isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("CHP-")
                   for n in ast.walk(node.value)):
                out += [t.id for t in node.targets if isinstance(t, ast.Name)]
    return out


def test_no_generator_but_seed_config_assigns_a_sku_list_literal():
    found = {p.name: sku_literals(p.read_text(encoding="utf-8")) for p in sorted(GEN.glob("seed_*.py"))
             if p.name != "seed_config.py"}
    assert {k: v for k, v in found.items() if v} == {}, "SKU list literals outside seed_config.py"


def test_the_check_catches_each_form_the_lists_took_before_u2():
    forms = ['ALL_SKUS = [\n    "CHP-AS-001", "CHP-AS-002",\n]',
             'CLUSTER_SKUS = ["CHP-AS-001", "CHP-AS-002"]',
             'DELIST_RISK_SKUS = {\n    "RET-WALMART": ["CHP-SC-008"],\n}',
             'NEVER_SCATTER_ASSIGNMENTS = [\n    ("RET-WALMART", "CHP-DG-007", date(2025, 10, 24)),\n]',
             'CURATED_SKUS = {\n    # a comment\n    "CHP-SC-008",\n} | set(CLUSTER_SKUS)']
    missed = [f.split(" =")[0] for f in forms if not sku_literals(f)]
    assert missed == [], f"check misses: {missed}"


def test_product_master_history_keeps_its_own_sku_order():
    sys.path.insert(0, str(GEN))
    import seed_config
    order = seed_config.PRODUCT_MASTER_HISTORY_SKUS
    lines = [s[4:6] for s in order]
    assert lines == sorted(lines) and lines[0] == "AS" and lines[-1] == "SC", \
        f"expected AS, DG, PS, SB, SC order, got {list(dict.fromkeys(lines))}"
    assert len(order) == 50 == len(set(order))


# -- deploy-costing.yml: the pre-relock refusal (plan U2) --------------------

WORKFLOW = GEN.parent / ".github" / "workflows" / "deploy-costing.yml"


def _steps():
    import yaml
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    assert list(jobs) == ["rebuild"], f"one job expected, found {list(jobs)}"
    return jobs["rebuild"]["steps"]


def test_deploy_costing_refuses_before_any_step_runs():
    # The refusal is step one: no checkout, no proxy, no psql ahead of it.
    first = _steps()[0]
    assert "uses" not in first and first["run"].strip().endswith("exit 1"), first
    assert "U12" in first["name"], first["name"]


def test_deploy_costing_writes_production_only_through_seed_all_with_the_override_on_that_step():
    steps = _steps()
    overridden = [s["name"] for s in steps if "ALLOW_PROD_DB" in (s.get("env") or {})]
    assert len(overridden) == 1 and "seed_all.py" in overridden[0], overridden
    runs = "\n".join(s.get("run", "") for s in steps)
    assert "seed_costing.py" not in runs and "costing_schema.sql" not in runs


def test_deploy_costing_runs_the_drop_guard_before_the_rebuild_on_python_3_13():
    steps = _steps()
    names = [s.get("name", s.get("uses", "")) for s in steps]
    guard = next(i for i, s in enumerate(steps) if "sql/drop_guard.sql" in s.get("run", ""))
    rebuild = next(i for i, s in enumerate(steps) if "generation/seed_all.py" in s.get("run", ""))
    assert guard < rebuild, names
    pins = [s["with"]["python-version"] for s in steps if "setup-python" in s.get("uses", "")]
    assert pins == ["3.13"], pins
