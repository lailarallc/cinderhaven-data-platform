"""The coverage gate (plan U5): the realism gate's teeth, run first by generation/seed_all.py.

    python scripts/check_anchor_coverage.py        exit 1 on any blocking finding

Reads only the vendored bundle (vendor/realism/) and the seeders' source, never
their runtime values. Arms, each naming every row or constant it fails:

- bundle         every file's SHA-256 matches the MANIFEST, and the MANIFEST
                 records a CLEAN spec gate. The spec gate's rules are not
                 re-implemented: its record is the proof. Its checks below
                 BLOCK with findings print every run.
- seeder keys    every module-level constant in generation/seed_*.py whose typed
                 value holds a number is in seed_config.COVERAGE_KEYS, keyed,
                 exempt or owed; a key naming an absent row and an entry naming a
                 constant that no longer exists fail.
- seeder prints  a keyed constant's typed values are printed in its row, by the
                 spec gate's own typed-constant rule (vendored check_anchors.py,
                 constant_publication). An owed entry naming a row its values are
                 now printed in fails until the note is removed.
- first-order    while the MANIFEST records the spec gate's first-order check at
                 BLOCK: some row carries first_order, and every such row is
                 owner-signed at its current fingerprint (the spec gate's
                 fingerprint_str) with verified_by empty. Otherwise it prints.
- effective      a row a key names whose effective_from postdates the generated
  dating         span's end fails; so does a dated period outside its row's span.
- reverse        the numeric rows no key names, printed, never blocking.

Also here: not_for_citation(), which U12 applies at relock (ruling 4, spec
DECISIONS 2026-10-23): a figure is marked while any row in its depends_on
closure is unpinned and practitioner-estimate, owner-judgment or Tier B.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "realism"
GENERATION = ROOT / "generation"
KEY_TABLE = "COVERAGE_KEYS"
SOFT_CLASSES = ("practitioner-estimate", "owner-judgment")


@dataclass
class Report:
    blocking: dict[str, list[str]] = field(default_factory=dict)  # arm -> findings
    printed: dict[str, list[str]] = field(default_factory=dict)   # arm -> lines shown every run

    def block(self, arm: str, findings: list[str]) -> None:
        self.blocking.setdefault(arm, []).extend(findings)

    def show(self, arm: str, lines: list[str]) -> None:
        self.printed.setdefault(arm, []).extend(lines)


# ── the bundle ──────────────────────────────────────────────────────

def arm_bundle(vendor: Path, manifest: dict, report: Report) -> bool:
    """True when the bundle may be read: every hash matches and the spec gate was CLEAN."""
    bad = []
    for name, want in sorted(manifest.get("files", {}).items()):
        path = vendor / name
        got = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        if got != want:
            bad.append(f"{name}: SHA-256 {got or 'missing'} where the MANIFEST records {want}")
    gate = manifest.get("spec_gate", {})
    if not gate.get("clean") or gate.get("blocking_findings", 1) != 0:
        bad.append(f"MANIFEST: the spec gate at {manifest.get('spec_commit', '?')[:12]} was not CLEAN "
                   f"({gate.get('blocking_findings')} blocking findings)")
    report.block("bundle", bad)
    report.show("bundle", [f"spec gate {c['level'].lower()}: {c['name']} ({c['findings']})"
                           for c in gate.get("checks", []) if c["level"] != "BLOCK" and c["findings"]])
    return not bad


def load_spec_gate(vendor: Path):
    """The vendored spec gate as a module: figure_fingerprint and the typed-constant rule, never a copy."""
    spec = importlib.util.spec_from_file_location("vendored_check_anchors", vendor / "check_anchors.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── the seeders' constants and the key table ────────────────────────

def seeder_constants(sources: dict[str, str], ca) -> dict[str, tuple]:
    """{"module.NAME": (module, name, items, kinds)} for every module-level constant whose typed value holds a
    number, read from source by the spec gate's reader. The key table itself is the gate's input, not a figure."""
    out = {}
    for module, src in sorted(sources.items()):
        for name, _line, _ids, _how, _ex, _owed, kinds in ca.generator_constants(module, src):
            if module == "seed_config" and name == KEY_TABLE:
                continue
            items = ca.typed_items(kinds)
            if items:
                out[f"{module}.{name}"] = (module, name, items, kinds)
    return out


def read_keys(seed_config_src: str) -> dict:
    for node in ast.parse(seed_config_src).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == KEY_TABLE for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError(f"seed_config.py has no {KEY_TABLE}")


def span_end(seed_config_src: str) -> date:
    """WINDOW_END as typed in seed_config.py: the generated span's end."""
    for node in ast.parse(seed_config_src).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "WINDOW_END" for t in node.targets):
            return date(*(a.value for a in node.value.args))
    raise ValueError("seed_config.py has no WINDOW_END")


def _row_named(entry: dict):
    return entry.get("key") or entry.get("row")


def arm_keys(consts: dict, keys: dict, index: dict, report: Report) -> None:
    bad = []
    for c in sorted(consts):
        if c not in keys:
            bad.append(f"{c}: a numeric constant neither keyed, exempt nor owed")
    for c, entry in sorted(keys.items()):
        if c not in consts:
            bad.append(f"{c}: a key-table entry for a constant that no longer exists")
            continue
        forms = [f for f in ("key", "exempt", "owed") if f in entry]
        if len(forms) != 1:
            bad.append(f"{c}: entry carries {forms or 'no form'}; exactly one of key, exempt, owed")
            continue
        if "owed" in entry and not (str(entry["owed"]).startswith("U") and entry.get("why")):
            bad.append(f"{c}: an owed entry names its unit and why")
        if "exempt" in entry and not entry["exempt"]:
            bad.append(f"{c}: an exempt entry gives its reason")
        rid = _row_named(entry)
        if rid is not None and rid not in index:
            bad.append(f"{c}: names {rid}, which is not in the vendored registry")
    report.block("seeder keys", bad)
    report.show("seeder keys", [f"exempt {c}: {e['exempt']}" for c, e in sorted(keys.items()) if "exempt" in e])
    owed: dict[str, list[str]] = {}
    for c, e in sorted(keys.items()):
        if "owed" in e:
            owed.setdefault(e["owed"], []).append(f"{c} ({e['why']})")
    for unit in sorted(owed, key=lambda u: int(u[1:]) if u[1:].isdigit() else 0):
        report.show("seeder keys", [f"owed to {unit} ({len(owed[unit])}): " + "; ".join(owed[unit])])


def arm_prints(consts: dict, keys: dict, index: dict, ca, report: Report) -> None:
    bad = []
    for c, entry in sorted(keys.items()):
        rid = _row_named(entry)
        if c not in consts or rid not in index or "exempt" in entry:
            continue
        module, name, items, kinds = consts[c]
        missing, _old = ca.constant_publication(module, name, [rid], items, index, kinds)
        if "key" in entry and missing:
            bad.extend(f"{c}: keyed to {rid}, which does not print {why}" for _p, why in missing)
        if "owed" in entry and not missing:
            bad.append(f"{c}: owed to {entry['owed']}, but {rid} now prints every value: paid, remove the note")
        if "start" in entry and not ca._exact_scales(float(entry["start"]), ca._printed_figures(index[rid])[1]):
            bad.append(f"{c}: its pre-window start {entry['start']} is not a start value {rid} registers")
    report.block("seeder prints", bad)


# ── first-order (R16; restated 2026-11-12) ──────────────────────────

def arm_first_order(manifest: dict, index: dict, ca, report: Report) -> None:
    record = next((c for c in manifest.get("spec_gate", {}).get("checks", [])
                   if c["name"] == ca.FIRST_ORDER_SIGNED_CHECK), None)
    bad = []
    flagged = [rid for rid, r in sorted(index.items()) if r.get("first_order") is True]
    for rid in flagged:
        r = index[rid]
        if r.get("verified_by") is not None:
            bad.append(f"{rid}: first-order and carries verified_by {r['verified_by']!r}")
        if not r.get("owner_signed"):
            bad.append(f"{rid}: first-order and not owner-signed")
        elif r.get("signed_figures") != ca.fingerprint_str(r):
            bad.append(f"{rid}: signed at {r.get('signed_figures')}, the row is now {ca.fingerprint_str(r)}")
    if record is not None and record["level"] == "BLOCK":
        if not flagged:
            bad.insert(0, "no row carries first_order: true; a gate keyed to an unset flag passes on nothing")
        report.block("first-order", bad)
    else:
        report.show("first-order", ["(the MANIFEST records the spec gate's first-order check below BLOCK; printed)"]
                    + bad)
    report.show("first-order", [f"{len(flagged)} first-order rows"])


# ── effective dating ────────────────────────────────────────────────

def _as_date(v):
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def arm_effective(keys: dict, index: dict, end: date, report: Report) -> None:
    bad = []
    for c, entry in sorted(keys.items()):
        rid = _row_named(entry)
        if rid not in index:
            continue
        r = index[rid]
        start = _as_date(r["effective_from"]) if r.get("effective_from") else None
        if start and start > end:
            bad.append(f"{c}: {rid}'s effective_from {start} postdates the generated span's end {end}")
        stop = _as_date(r["effective_to"]) if r.get("effective_to") else end
        for p_start, _v in entry.get("periods", []):
            p = _as_date(p_start)
            if (start and p < start) or p > min(stop, end):
                bad.append(f"{c}: period from {p} lies outside {rid}'s effective span {start} to {min(stop, end)}")
    report.block("effective dating", bad)


# ── the reverse direction ───────────────────────────────────────────

def reverse(keys: dict, index: dict, enums: dict, report: Report) -> None:
    named = {_row_named(e) for e in keys.values()} - {None}
    numeric = [rid for rid, r in sorted(index.items()) if r.get("unit") not in enums["definition_units"]]
    left = [rid for rid in numeric if rid not in named]
    report.show("reverse", [f"{len(left)} of {len(numeric)} numeric rows named by no seeder key and no vendored "
                            f"generator: {' '.join(left)}"])


# ── not-for-citation (U12 applies it at relock) ─────────────────────

def not_for_citation(ids, index: dict) -> tuple[bool, list[str]]:
    """(marked, the rows that mark it) for a figure derived from `ids`, over their depends_on closure."""
    seen, stack, marking = set(), list(ids), []
    while stack:
        rid = stack.pop()
        if rid in seen or rid not in index:  # a package item (N23) is not a row
            continue
        seen.add(rid)
        r = index[rid]
        if r.get("status") != "pinned" and (r.get("evidence_class") in SOFT_CLASSES or r.get("tier") == "B"):
            marking.append(rid)
        stack.extend(r.get("depends_on") or [])
    return bool(marking), sorted(marking)


# ── running it ──────────────────────────────────────────────────────

def check(vendor: Path = VENDOR, generation: Path = GENERATION, manifest: dict | None = None,
          sources: dict | None = None, rows: list | None = None) -> Report:
    """Every arm over the bundle and the seeders. The overrides take in-memory broken copies (the tests)."""
    report = Report()
    manifest = manifest if manifest is not None else json.loads((vendor / "MANIFEST.json").read_text("utf-8"))
    if not arm_bundle(vendor, manifest, report):
        return report  # nothing in an unverified bundle is read
    ca = load_spec_gate(vendor)
    rows = rows if rows is not None else yaml.safe_load((vendor / "anchors.yml").read_text("utf-8"))
    enums = yaml.safe_load((vendor / "anchor_enums.yml").read_text("utf-8"))
    index = {r["anchor_id"]: r for r in rows}
    sources = sources if sources is not None else {p.stem: p.read_text("utf-8")
                                                   for p in sorted(generation.glob("seed_*.py"))}
    keys = read_keys(sources["seed_config"])
    consts = seeder_constants(sources, ca)
    arm_keys(consts, keys, index, report)
    arm_prints(consts, keys, index, ca, report)
    arm_first_order(manifest, index, ca, report)
    arm_effective(keys, index, span_end(sources["seed_config"]), report)
    reverse(keys, index, enums, report)
    return report


def main() -> int:
    report = check()
    print("anchor coverage gate")
    for arm, lines in report.printed.items():
        for line in lines:
            print(f"   {arm:16s} {line}")
    n = sum(len(f) for f in report.blocking.values())
    for arm, findings in report.blocking.items():
        for f in findings:
            print(f"   BLOCK {arm}: {f}")
    print("CLEAN -- no blocking findings" if not n else f"{n} BLOCKING findings")
    return 1 if n else 0


if __name__ == "__main__":
    sys.exit(main())
