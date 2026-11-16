"""The one import of the realism bundle (plan U15).

`vendor/realism/` holds byte copies, at one gate-clean spec commit, of the four
spec generators, the registry and its enums, the spec gate, and `outputs.json`:
every entry function's return, written by the spec gate's own `--export` after
its clean run. The MANIFEST names that one commit, a SHA-256 per file, the memo
key and the pinned trial's digest.

load() refuses unless every file hashes to its MANIFEST entry and the memo key,
recomputed here from the vendored generators in the spec gate's own cache-key
form, matches the MANIFEST's. It never solves: the solved account factor
travels in outputs.json, and the one generator call at seed time is group 11's
replay of the pinned trial, given that factor.

Generation-path only. No other module in generation/ imports a group module or
reads vendor/realism/ (tests/test_realism_bundle.py), and U4's ban keeps the
scan roots off both (quarantine/truth_gate.py).
"""
from __future__ import annotations

import copy
import hashlib
import importlib
import importlib.util
import inspect
import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "realism"
MANIFEST = "MANIFEST.json"
OUTPUTS = "outputs.json"
GATE = "check_anchors.py"
#: trial 0, registered by index before any of its outcomes was read (owner, 2026-10-14,
#: spec DECISIONS#u18-rulings); another trial only by an owner ruling with its reason
PINNED_TRIAL = 0
#: the printed entry each accessor reads, by the label the spec gate reads it under
AP_SCHEDULE = ("group9_ledger", "A9.11", "the AP-run schedule, A10.19's note in it, $M")


class BundleError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gate_module(vendor: Path):
    """The vendored spec gate, imported under a private name (it defines the memo key's form and the JSON codec)."""
    name = "realism_gate_" + hashlib.sha256(str(vendor.resolve()).encode()).hexdigest()[:12]
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, vendor / GATE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        sys.modules[name] = mod
    return sys.modules[name]


def memo_key(generators: Path, gate) -> str:
    """The spec gate's own cache key (its `_outputs`): the SHA-256 of the generators it lists, read as text, in its
    order, then of `_outputs_compute`'s source. Full hex; the gate names its cache file by the first 20."""
    h = hashlib.sha256()
    for rel in gate.GENERATORS:
        h.update((generators / Path(rel).name).read_text(encoding="utf-8").encode("utf-8"))
    h.update(inspect.getsource(gate._outputs_compute).encode("utf-8"))
    return h.hexdigest()


def trial_digest(trial_json) -> str:
    """SHA-256 of a trial's JSON form (outputs.json's own encoding), keys sorted, no whitespace."""
    return hashlib.sha256(json.dumps(trial_json, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def verify(vendor: Path = VENDOR) -> dict:
    """The MANIFEST, once every file it names hashes to its entry; BundleError naming the first file that does not."""
    m = json.loads((vendor / MANIFEST).read_text(encoding="utf-8"))
    for name, want in sorted(m["files"].items()):
        got = sha256(vendor / name) if (vendor / name).is_file() else None
        if got != want:
            raise BundleError(f"vendor/realism/{name}: SHA-256 {got or 'missing'}, the MANIFEST records {want}; "
                              f"re-vendor with scripts/vendor_realism.py, never edit a vendored file")
    return m


class Bundle:
    """The bundle's accessors. Seeders plan their rows from one of these (`plan(bundle)`); a test may patch it."""

    def __init__(self, vendor: Path, manifest: dict, outputs: dict, modules: dict, gate):
        self.vendor, self.manifest, self.outputs = vendor, manifest, outputs
        self._m, self._gate = modules, gate
        self._overrides: dict = {}
        self._trial = None

    # ---- printed outputs and series (outputs.json)
    def printed(self, generator: str, anchor: str, label: str):
        key = ("printed", generator, anchor, label)
        if key in self._overrides:
            return self._overrides[key]
        return self.outputs["generators"][generator]["printed"][anchor][label]

    def series(self, name: str):
        key = ("series", name)
        if key in self._overrides:
            return self._overrides[key]
        return self.outputs["generators"]["group8_dtc"]["series"][name]

    def solved_factor(self) -> float:
        return self.printed("group10_floors", "A11.27", self._gate.FACTOR)

    def ap_schedule(self) -> list:
        """The AP runs the noted daily ledger pays (U16): day, then $M due, held and paid at that run."""
        return self.printed(*AP_SCHEDULE)

    # ---- the generators' typed inputs and integer rules, read from the vendored modules
    def constant(self, module: str, name: str):
        key = ("constant", module, name)
        if key in self._overrides:
            return self._overrides[key]
        return getattr(self._m[module], name)

    def supplier_terms(self, supplier: str) -> int:
        """A9.11's supplier terms in days, by group 10's supplier class (ingredients, glass, co-packers)."""
        return self.constant("group10_floors", "SUPPLIER_TERMS")[supplier]

    def ap_run(self, invoice_day):
        """The AP run that pays an invoice raised on `invoice_day`: group 9's own rule, the run nearest the invoice's
        DPO day (A9.11; the earlier on a tie)."""
        g = self._m["group9_ledger"]
        dpo = self.constant("group9_ledger", "DPO")
        days = self.constant("group9_ledger", "AP_RUN_DAYS")
        if (dpo, days) == (g.DPO, g.AP_RUN_DAYS):
            return g._ap_run(invoice_day + timedelta(dpo))
        saved = g.AP_RUN_DAYS
        try:                        # a patched bundle: the generator's rule on the patched inputs
            g.AP_RUN_DAYS = days
            return g._ap_run(invoice_day + timedelta(dpo))
        finally:
            g.AP_RUN_DAYS = saved

    def largest_remainder(self, *args, **kwargs):
        return self._m["group10_floors"].largest_remainder(*args, **kwargs)

    # ---- the pinned trial
    def trial(self) -> dict:
        """The pinned trial's catalogue lifecycle, replayed on the generator's own stream with the memo's factor, and
        refused unless it hashes to the digest the MANIFEST records from the spec side's export."""
        if self._trial is None:
            F, L = self._m["group10_floors"], self._m["group11_compliance"]
            acct = self.solved_factor()
            solve = L.solve_account_factor

            def refused(*a, **kw):
                raise BundleError("the bundle replays the pinned trial on the memo's factor; it never solves")
            L.solve_account_factor = refused
            F._SOLVED["acct"] = acct
            try:
                replay = L.catalogue_draws(acct=acct, trials=PINNED_TRIAL + 1, replay=PINNED_TRIAL)["replay"]
            finally:
                L.solve_account_factor = solve
            as_json = json.loads(json.dumps(replay, default=self._gate._encode))
            want = self.manifest["pinned_trial"]["digest"]
            if trial_digest(as_json) != want:
                raise BundleError(f"trial {PINNED_TRIAL}'s replay hashes to {trial_digest(as_json)}, "
                                  f"the spec side recorded {want}")
            self._trial = json.loads(json.dumps(as_json), object_hook=self._gate._decode)
        return self._trial

    # ---- the probe method's patched copy (the perturbation test)
    def patched(self, key: tuple, value) -> "Bundle":
        """A copy with one output or typed input replaced: ("printed", gen, anchor, label), ("series", name) or
        ("constant", module, name)."""
        b = copy.copy(self)
        b._overrides = dict(self._overrides)
        b._overrides[key] = value
        b._trial = None
        return b


_LOADED: dict = {}


def load(vendor: Path = VENDOR) -> Bundle:
    """The bundle, once per process: verified, memo-keyed, the four generators imported from vendor/realism/."""
    vendor = Path(vendor).resolve()
    if vendor in _LOADED:
        return _LOADED[vendor]
    m = verify(vendor)
    gate = gate_module(vendor)
    key = memo_key(vendor, gate)
    if key != m.get("memo_sha256"):
        raise BundleError(f"the memo key of the vendored generators is {key}, the MANIFEST records "
                          f"{m.get('memo_sha256')}; the bundle refuses to load rather than solve")
    text = (vendor / OUTPUTS).read_text(encoding="utf-8")
    outputs = json.loads(text, object_hook=gate._decode)
    if outputs.get("commit") != m["spec_commit"]:
        raise BundleError(f"outputs.json was exported at {outputs.get('commit')}, the MANIFEST names "
                          f"{m['spec_commit']}")
    if str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))   # the byte copies import each other by bare module name
    modules = {}
    for rel in gate.GENERATORS:
        name = Path(rel).stem
        mod = importlib.import_module(name)
        if Path(mod.__file__).resolve().parent != vendor:
            raise BundleError(f"{name} imported from {mod.__file__}, not from vendor/realism/")
        modules[name] = mod
    _LOADED[vendor] = Bundle(vendor, m, outputs, modules, gate)
    return _LOADED[vendor]
