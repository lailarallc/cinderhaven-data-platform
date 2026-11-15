"""Verify reference/canonical_values.yml against the world, and emit the two artifacts consumers vendor.

Every numeric key in the yml (outside `meta` and `supersedes`) is a documented figure. Each must have a producer,
a `metric.basis.period|value` line from sql/canonical_gather.sql, and each is compared at the precision the yml
stores it: the live value, rounded half-up to the yml literal's decimal places, must equal it exactly. There is no
tolerance and no hand-kept list of values (plan U19: "every documented figure read from the yml; every silent skip
a failure").

The gather comes from one of two places:
    python scripts/verify_canonical.py --gather FILE   # a saved gather output: the reader workflow's step
                                                        # (verify-production-figures.yml) for production
    DATABASE_URL=... python scripts/verify_canonical.py # a direct connection; prod_guard refuses production,
                                                        # which is read only through the cinderhaven_ci_reader
                                                        # workflow (owner, 2026-11-14)

Each of these fails (exit 1), never skips: no gather source; psycopg2 missing for a connection; a query error; a
gather line that is not `key|number`; a documented figure the gather does not produce; a value that differs at the
yml's precision. Gather keys the yml does not hold are listed and do not fail.

The artifacts (reference/canonical_values.json, reference/supersedes.txt) are emitted on every run, before the
comparison, from the yml alone. This does NOT edit the canon.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent.parent
CANONICAL_YAML = ROOT / "reference" / "canonical_values.yml"
GATHER_SQL = ROOT / "sql" / "canonical_gather.sql"
NOT_FIGURES = ("meta", "supersedes")

if not CANONICAL_YAML.exists():
    print(f"canonical file not found at {CANONICAL_YAML} -- a hard failure, not a skip.", file=sys.stderr)
    sys.exit(1)
try:
    import yaml
except ImportError:
    print("PyYAML not installed. pip install pyyaml", file=sys.stderr)
    sys.exit(1)

_cv = yaml.safe_load(CANONICAL_YAML.read_text(encoding="utf-8"))


class _ExactLoader(yaml.SafeLoader):
    """Floats load as Decimal of their literal text, so 11.00 keeps its two places."""


_ExactLoader.add_constructor(
    "tag:yaml.org,2002:float",
    lambda loader, node: Decimal(loader.construct_scalar(node).replace("_", "")),
)


class VerifyError(RuntimeError):
    pass


def documented(text: str) -> dict[str, Decimal]:
    """key -> value (Decimal, carrying the literal's precision) for every numeric leaf outside NOT_FIGURES."""
    out: dict[str, Decimal] = {}

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, path + [str(k)])
        elif isinstance(node, bool):
            return
        elif isinstance(node, int):
            out[".".join(path)] = Decimal(node)
        elif isinstance(node, Decimal):
            out[".".join(path)] = node

    tree = yaml.load(text, Loader=_ExactLoader)
    walk({k: v for k, v in tree.items() if k not in NOT_FIGURES}, [])
    return out


def parse_gather(lines) -> dict[str, Decimal]:
    """`key|value` lines -> key -> Decimal. A malformed or non-numeric line is a failure, not a skip."""
    out: dict[str, Decimal] = {}
    bad = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith(("=", "#")):
            continue
        key, sep, val = line.partition("|")
        if not sep or not re.fullmatch(r"[\w.]+", key):
            bad.append(line)
            continue
        if key.startswith("window."):  # data windows: dates, by design not figures
            continue
        try:
            out[key] = Decimal(val)
        except InvalidOperation:
            bad.append(line)
    if bad:
        raise VerifyError("gather lines that are not key|number: " + "; ".join(bad[:5]))
    return out


def gather_statements(sql: str) -> list[str]:
    sql = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("\\"))
    sql = re.sub(r"--[^\n]*", "", sql)
    return [s for s in sql.split(";") if s.strip()]


def gather_from_db(url: str) -> list[str]:
    sys.path.insert(0, str(ROOT / "scripts"))
    import prod_guard

    prod_guard.check(url)  # production is read through the reader workflow, never a direct connection
    try:
        import psycopg2
    except ImportError as e:
        raise VerifyError("psycopg2 not installed: a connection was asked for and cannot be made") from e
    conn = psycopg2.connect(url)
    try:
        cur = conn.cursor()
        lines = []
        for stmt in gather_statements(GATHER_SQL.read_text(encoding="utf-8")):
            cur.execute(stmt)  # a query error raises; nothing is recorded as a string
            lines += [str(r[0]) for r in cur.fetchall()]
        return lines
    finally:
        conn.close()


def at_precision(live: Decimal, doc: Decimal) -> Decimal:
    return live.quantize(Decimal(1).scaleb(doc.as_tuple().exponent), rounding=ROUND_HALF_UP)


def compare(docs: dict[str, Decimal], live: dict[str, Decimal]) -> tuple[list[str], list[str]]:
    """(failures, keys the gather has and the yml does not)."""
    bad = []
    for key in sorted(docs):
        if key not in live:
            bad.append(f"{key}: documented {docs[key]}, no producer in canonical_gather.sql")
            continue
        got = at_precision(live[key], docs[key])
        if got != docs[key]:
            bad.append(f"{key}: documented {docs[key]}, live {live[key]} ({got} at the yml's precision)")
    return bad, sorted(set(live) - set(docs))


def _platform_head() -> str:
    """Short git SHA of the platform repo, for JSON provenance. '' if unavailable."""
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def emit_artifacts() -> None:
    """Derive the two machine-readable artifacts from the YAML SSOT.

    Runs on EVERY invocation (independent of DB reachability):
      reference/canonical_values.json — the full canon as JSON, with a
        `_generated` provenance header. Repos vendor this via
        scripts/refresh_canonical.py; their test_canonical_regression.* read it.
      reference/supersedes.txt — one retired token per line (from the YAML
        `supersedes:` block). The per-repo drift gate greps against this file.
    """
    generated = date.today().isoformat()
    head = _platform_head()

    payload = {
        "_generated": {
            "source": "reference/canonical_values.yml",
            "generator": "scripts/verify_canonical.py",
            "generated": generated,
            "platform_head": head,
            "verified_against_production": _cv.get("meta", {}).get(
                "verified_against_production"
            ),
        },
        **_cv,
    }
    json_path = ROOT / "reference" / "canonical_values.json"
    json_path.write_text(
        json.dumps(payload, indent=1, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )

    supersedes = _cv.get("supersedes", []) or []
    tokens = [str(e["token"]) for e in supersedes if isinstance(e, dict) and e.get("token")]
    if not tokens:
        print(
            "WARNING: canonical_values.yml has no `supersedes:` tokens — "
            "supersedes.txt would be empty, which disables the drift gate. "
            "Refusing to emit an empty gate file.",
            file=sys.stderr,
        )
    else:
        sup_path = ROOT / "reference" / "supersedes.txt"
        header = (
            "# Retired Cinderhaven figures/strings — generated from "
            "canonical_values.yml `supersedes:` by verify_canonical.py.\n"
            f"# generated {generated} | platform {head or 'unknown'}\n"
            "# The drift gate fails a build on any hit (excluding history/"
            "SUPERSEDES docs and per-repo allowlists). Do not edit by hand.\n"
        )
        sup_path.write_text(header + "\n".join(tokens) + "\n", encoding="utf-8")
        print(f"  emitted {sup_path.name} ({len(tokens)} retired tokens)")
    print(f"  emitted {json_path.name} (canon as JSON, head={head or 'unknown'})")


def run(gather_file: Path | None) -> int:
    print("  Emitting derived artifacts ...")
    emit_artifacts()
    try:
        if gather_file is not None:
            lines = gather_file.read_text(encoding="utf-8").splitlines()
            source = f"gather file {gather_file}"
        elif os.environ.get("DATABASE_URL"):
            lines = gather_from_db(os.environ["DATABASE_URL"])
            source = "a direct connection (DATABASE_URL)"
        else:
            raise VerifyError("no gather source: pass --gather FILE or set DATABASE_URL. Nothing was compared.")
        live = parse_gather(lines)
    except Exception as e:  # every way of not measuring is a failure
        print(f"\nFAIL: {e.__class__.__name__}: {e}")
        return 1
    docs = documented(CANONICAL_YAML.read_text(encoding="utf-8"))
    bad, extra = compare(docs, live)
    print(f"\n  source: {source}")
    print(f"  documented figures: {len(docs)}; produced: {len(set(docs) & set(live))}; failures: {len(bad)}")
    if extra:
        print(f"  gathered, not documented (not a failure): {', '.join(extra)}")
    for b in bad:
        print(f"  FAIL {b}")
    if bad:
        return 1
    print("\n  OK -- every documented figure is produced and equal at the yml's precision.")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--gather", type=Path, help="a saved canonical_gather.sql output (key|value lines)")
    args = p.parse_args(argv)
    return run(args.gather)


if __name__ == "__main__":
    sys.exit(main())
