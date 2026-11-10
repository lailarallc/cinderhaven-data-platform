"""The import ban (plan U4): the answer key by another route.

The seeders reproduce what truth holds: compute_defect_profile(seed=DEFECT_SEED)
reproduces every defect the defect ledger will hold. So no scan-root module may
import a seed_* module, the generation package, U15's loader realism_bundle, or
anything under vendor/realism/, nor read a file there. Lift Math's ban named
promo-response's modules and matched only the last dotted name, so
`from seed_config import compute_defect_profile` passed it; this one does not.

Also here: generation/'s membership, so the ban's pattern and the directory
cannot drift apart.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from quarantine.truth_gate import TruthAccessViolation, assert_no_generator_access

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "truth_gate"
SCAN_ROOTS = ("scripts", "orchestration")

#: List 4: empty here. U5 adds its two scripts/ files that read the vendored
#: registry, each by path, each with a platform DECISIONS entry.
IMPORT_BAN_EXEMPT: tuple = ()

#: generation/ holds the seeders, the vendored guard and U15's loader, each named.
GENERATION_NON_SEEDERS = ("prod_guard.py", "realism_bundle.py")


def test_the_scan_roots_do_not_import_the_generators():
    assert_no_generator_access(*(ROOT / r for r in SCAN_ROOTS), exclude=IMPORT_BAN_EXEMPT)


@pytest.mark.parametrize("fixture", [
    "violation_imports_seed_config.py",       # from seed_config import compute_defect_profile
    "violation_imports_seed_module.py",
    "violation_imports_generation_package.py",
    "violation_imports_vendor_realism.py",
    "violation_reads_vendor_realism.py",      # a read counts, not only an import
    "violation_imports_realism_bundle.py",
])
def test_the_ban_rejects(fixture):
    with pytest.raises(TruthAccessViolation):
        assert_no_generator_access(FIX / fixture)


def test_the_ban_passes_a_clean_estimator():
    assert_no_generator_access(FIX / "clean_estimator.py")


def test_the_ban_raises_when_any_one_root_is_empty(tmp_path):
    (tmp_path / "a").mkdir(), (tmp_path / "b").mkdir()
    (tmp_path / "a" / "ok.py").write_text("x = 1\n")
    with pytest.raises(ValueError, match="empty"):
        assert_no_generator_access(tmp_path / "a", tmp_path / "b")


def test_every_module_in_generation_is_a_seeder_or_named():
    strays = [p.name for p in (ROOT / "generation").glob("*.py")
              if not p.name.startswith("seed_") and p.name not in GENERATION_NON_SEEDERS]
    assert strays == [], f"generation/ holds modules the import ban's pattern does not name: {strays}"


def test_the_membership_check_fails_on_a_stray_module(tmp_path):
    (tmp_path / "helpers.py").write_text("")
    strays = [p.name for p in tmp_path.glob("*.py")
              if not p.name.startswith("seed_") and p.name not in GENERATION_NON_SEEDERS]
    assert strays == ["helpers.py"]


def test_the_import_ban_exemption_list_matches_the_logged_decision():
    assert IMPORT_BAN_EXEMPT == (), "the import-ban exemption list changed: that needs a DECISIONS entry"
