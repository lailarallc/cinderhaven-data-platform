#!/usr/bin/env python3
"""The registry gate for reference/anchors.yml, and for the prose that cites it.

WHY THIS EXISTS
---------------
Every check below was written after a defect, and most of them after the same
defect happened twice. Twelve multi-agent audits and roughly 900 subagents found
what these deterministic checks find in under a second - and the audits will not
run against generated data. DECISIONS.md 2026-09-06 makes them blocking work
rather than future work; DECISIONS.md 2026-09-04 is why the enums are read from
reference/anchor_enums.yml instead of the registry's header comment, which had
declared an enum conflict two days after it was resolved.

    python scripts/check_anchors.py            # the gate; exit 1 on any BLOCK
    python scripts/check_anchors.py --all      # also print the passing checks
    python scripts/check_anchors.py --no-cache # recompute group 11's generator values (minutes)

WHAT IS AND IS NOT MECHANISED
-----------------------------
Three of the four checks named on 2026-09-06 are here in full: one value per
named quantity, no value borrowed after its owning group retired it, and (with
the direction test below) depends_on completeness. The fourth - "every worked
number in a value field reproduces from that row's depends_on rows" - is NOT
mechanisable in general: it asks a checker to re-derive prose arithmetic. What
stands in for it is the generator cross-check, which imports the group-9
generator and asserts that every series it computes appears verbatim in the
registry row and the sourcing doc that publish it. That is the reproducible
half, and the half that has actually drifted.
"""
import calendar
import datetime
import hashlib
import io
import math
import os
import random
import re
import sys

import yaml
from fractions import Fraction
from statistics import NormalDist

NORM = NormalDist()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY = "reference/anchors.yml"
ENUMS = "reference/anchor_enums.yml"
WORKLIST = "docs/anchors/ANCHOR-WORKLIST.md"
DECISIONS = "DECISIONS.md"
EXCEPTIONS = "reference/depends_on_exceptions.yml"
GROUP9_DOC = "docs/anchors/sourcing/group-9-cost-structure.md"
GROUP10_DOC = "docs/anchors/sourcing/group-10-survivability.md"
GROUP11_DOC = "docs/anchors/sourcing/group-11-compliance.md"
GROUP1_DOC = "docs/anchors/sourcing/group-1-revenue.md"
GROUP7_DOC = "docs/anchors/sourcing/group-7-store-universe.md"
GROUP3_DOC = "docs/anchors/sourcing/group-3-price-waterfall.md"
GROUP4_DOC = "docs/anchors/sourcing/group-4-trade-deductions.md"
GROUP5_DOC = "docs/anchors/sourcing/group-5-po-lifecycle.md"
GROUP8_DOC = "docs/anchors/sourcing/group-8-dtc.md"
# 03's five pre-registered acceptance gates print value + anchor (owner, 2026-10-03, U6): the one requirements-doc
# site the gate watches, because a gate without a number is not a gate and a number unwatched drifts
REGEN_SCOPE_DOC = "docs/brainstorms/realism-regen-2026/03-regen-scope.md"
TEXT_ARTIFACTS = [REGISTRY, ENUMS, WORKLIST, DECISIONS, "PLAN.md", "HANDOFF.md",
                  "FAILURES.md", "CLAUDE.md", "README.md"]

RESULTS = []
BLOCK, WARN, INFO = "BLOCK", "WARN", "INFO"
PRINT_RULE_CHECK = "figures printed past the print rule's precision (DECISIONS#print-rule)"

TRIPLE = re.compile(r"-?\d+\.\d+\s*/\s*-?\d+\.\d+\s*/\s*-?\d+\.\d+")
ANCHOR_ID = re.compile(r"\bA\d+\.\d+\b")


def rd(rel):
    with io.open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def report(level, name, messages):
    RESULTS.append((level, name, list(messages)))


def slugify(heading):
    """GitHub's heading anchor: lowercase, drop punctuation, EACH space a hyphen.

    Per character, not per run. "A1.01 - Company" deletes the em dash and keeps
    both spaces that surrounded it, so the slug carries a double hyphen.
    """
    s = re.sub(r"[^\w\s-]", "", heading.strip().lower())
    return re.sub(r"\s", "-", s).strip("-")


def series(values, places=3):
    """A failure message's figures, at the check's own precision -- which may be ONE precision or one per value,
    and each value may be a scalar or a (lo, hi) range, because carries_exact accepts all three. It formatted
    only the scalar-and-one-precision case until 2026-09-22, so an entry with per-value places crashed the gate
    in its own error path: the check had found the defect and died reporting it."""
    each = list(places) if isinstance(places, (list, tuple)) else [places] * len(values)
    out = []
    for v, p in zip(values, each):
        fmt = "%." + str(p) + "f"
        out.append("-".join(fmt % x for x in v) if isinstance(v, (list, tuple)) else fmt % v)
    return " / ".join(out)


def carries(haystack, values):
    """Does this prose publish this series, at the precision the prose chose?

    One series is written many ways: "3.104 / 5.220 / 7.228", "$3.84 / $4.62 /
    $5.02M", "0.1% in y1, 2.6% in y2", and transposed into a table by year.

    EACH NUMBER IS COMPARED AT ITS OWN WRITTEN PRECISION. "4.412" is a claim to three
    decimals and is checked at three; "5.3%" is a claim to one and is checked at one.
    The first version fell back to the LOOSEST precision that matched, which let a
    restatement through whenever old and new agreed after rounding - NWC 4.412
    against a generator computing 4.408 passed at two decimals, and the gate stayed
    green over a published figure that no longer reproduced.

    Two tiers, the second weaker on purpose: a CONSECUTIVE RUN first (catches a
    restated figure and a reordered one), then EVERY VALUE SOMEWHERE (for tables that
    transpose a series; still catches a restatement, not a reordering).
    """
    toks = re.findall(r"-?\d+\.(\d+)|(-?\d+\.\d+)", norm(haystack))
    nums = []
    for m in re.finditer(r"-?\d+\.(\d+)", norm(haystack)):
        nums.append((float(m.group(0)), len(m.group(1))))

    def hit(value, num):
        written, places = num
        return round(value, places) == round(written, places)

    n = len(values)
    for i in range(len(nums) - n + 1):
        if all(hit(values[j], nums[i + j]) for j in range(n)):
            return True
    return all(any(hit(v, num) for num in nums) for v in values)


def norm(text):
    """Unicode minus and arrow to ASCII, so prose and generator output compare."""
    return (text.replace(u"−", "-").replace(u"→", "->")
                .replace(u" ", " "))


_FIELD_STEP = re.compile(r"([A-Za-z_]+)(?:\[(\d+)\])?")


def field_text(row, field):
    """A row's text at `field`: a top-level field ("plausibility_anchor"), or a path into its list of records
    ("sources[0].figure"); empty names `value`. THE ONE COPY of this rule: check_group11_figures and
    probe_figure_checks both call it. They kept a copy each until 2026-09-30, and the address form one was not
    taught broke it (FAILURES 2026-09-22)."""
    node = row
    for step in (field or "value").split("."):
        m = _FIELD_STEP.fullmatch(step)
        node = node[m.group(1)]
        if m.group(2) is not None:
            node = node[int(m.group(2))]
    return node


def sentences(text):
    return re.split(r"(?<=[.;])\s+", norm(text or ""))


# ------------------------------------------------------------------ the checks
def check_schema(rows, enums):
    """Every row carries every field, and every enum value is legal."""
    required = ["anchor_id", "tier", "drives", "status", "owner", "two_endpoint",
                "unit", "value", "effective_from", "independence",
                "evidence_class", "sourcing_note"]
    bad = []
    for r in rows:
        rid = r.get("anchor_id", "<no id>")
        for f in required:
            if f not in r:
                bad.append("%s: missing field %s" % (rid, f))
            elif r[f] in (None, ""):
                bad.append("%s: %s is empty" % (rid, f))
        for f in ("tier", "status", "independence", "evidence_class", "unit"):
            if f in r and r[f] not in enums[f]:
                bad.append("%s: %s = %r is not in anchor_enums.yml" % (rid, f, r[f]))
        if not re.match(r"^A\d+\.\d+$", str(rid)):
            bad.append("%s: anchor_id is not A<group>.<n>" % rid)
    report(BLOCK, "schema and enums", bad)


def check_denominator(rows, enums):
    """A proportion with no denominator is not a number.

    The structural rule that replaced three incompatible prose scopes.
    """
    need = set(enums["denominator_required"])
    report(BLOCK, "denominators on proportions",
           ["%s: unit %s with no denominator" % (r["anchor_id"], r["unit"])
            for r in rows if r["unit"] in need and not r.get("denominator")])


def check_depends_resolve(rows, index, enums):
    """Every depends_on id is a registered anchor or a package item."""
    pkg = re.compile(enums["package_item_pattern"])
    bad = []
    for r in rows:
        for u in r.get("depends_on") or []:
            if u not in index and not pkg.match(str(u)):
                bad.append("%s: depends_on %s resolves to nothing" % (r["anchor_id"], u))
    report(BLOCK, "depends_on resolves", bad)


def check_cycles(rows, index):
    """A derivation cycle means no row inside it can be evaluated."""
    colour, found = {}, []

    def walk(node, path):
        colour[node] = 1
        for nxt in index.get(node, {}).get("depends_on") or []:
            if nxt not in index:
                continue
            if colour.get(nxt) == 1:
                cycle = path[path.index(nxt):] + [nxt] if nxt in path else [node, nxt]
                found.append(" -> ".join(cycle))
            elif colour.get(nxt, 0) == 0:
                walk(nxt, path + [nxt])
        colour[node] = 2

    for r in rows:
        if colour.get(r["anchor_id"], 0) == 0:
            walk(r["anchor_id"], [r["anchor_id"]])
    report(BLOCK, "no derivation cycles", found)


def check_tier_a(rows, enums):
    """Tier A is published evidence REQUIRED and AVAILABLE.

    Membership in the published subset, not a sixth evidence_class value, and
    never `independence`, which does not satisfy the gate.
    """
    pub = set(enums["published_subset"])
    bad = []
    for r in rows:
        if r["tier"] != "A":
            continue
        if r["evidence_class"] not in pub:
            bad.append("%s: Tier A with evidence_class %s, outside the published subset"
                       % (r["anchor_id"], r["evidence_class"]))
        for f in ("source_url", "source_date"):
            if not r.get(f):
                bad.append("%s: Tier A with no %s" % (r["anchor_id"], f))
    report(BLOCK, "Tier A gate", bad)


NO_URL_MARK = "No URL recorded"


def check_tier_a_non_vendor(rows):
    """U14's non-vendor check (owner, 2026-10-23, DECISIONS#u14): every Tier A row's primary carries a URL and an
    `independence` that is neither `vendor` nor `none`. A `sources` entry with no URL may stand beside that primary
    only as a reading record, its `measured` opening "No URL recorded"; it is never the row's evidence. YAML null
    parses to None, never the string 'None'."""
    bad = []
    for r in rows:
        if r.get("tier") != "A":
            continue
        if r.get("source_url") is None or r.get("independence") in ("vendor", "none"):
            bad.append("%s: Tier A primary is %s with independence %s -- it needs a URL and a non-vendor source"
                       % (r["anchor_id"], "URL-less" if r.get("source_url") is None else "addressed",
                          r.get("independence")))
        for e in r.get("sources") or []:
            if e.get("source_url") is None and not str(e.get("measured") or "").startswith(NO_URL_MARK):
                bad.append("%s: a sources entry with no URL is not marked %r -- it reads as evidence"
                           % (r["anchor_id"], NO_URL_MARK))
    report(BLOCK, "Tier A primary is addressed and not a vendor", bad)


def check_tier_d(rows, enums):
    """A Tier D row has no source, so it must carry its reasoning."""
    bad = []
    for r in rows:
        if r["tier"] != "D":
            continue
        for f in ("rationale", "decision_ref", "plausibility_anchor"):
            if not r.get(f):
                bad.append("%s: Tier D with no %s" % (r["anchor_id"], f))
    report(BLOCK, "Tier D carries its reasoning", bad)

    unsigned = [r["anchor_id"] for r in rows
                if r["tier"] == "D" and r["unit"] not in enums["definition_units"]
                and not r.get("owner_signed")]
    report(INFO, "numeric Tier D rows not yet owner-signed, so not pinnable",
           ["%d rows, first twelve: %s" % (len(unsigned), ", ".join(unsigned[:12]))]
           if unsigned else [])


def check_sourcing_slugs(rows):
    """A sourcing_note that points at no heading points at nothing."""
    cache, bad = {}, []
    for r in rows:
        note = r.get("sourcing_note") or ""
        if "#" not in note:
            bad.append("%s: sourcing_note has no #slug" % r["anchor_id"])
            continue
        path, slug = note.split("#", 1)
        if path not in cache:
            try:
                cache[path] = set(slugify(m) for m in
                                  re.findall(r"^#+\s+(.*)$", rd(path), re.M))
            except IOError:
                cache[path] = None
        if cache[path] is None:
            bad.append("%s: sourcing_note file %s does not exist" % (r["anchor_id"], path))
        elif slug not in cache[path]:
            bad.append("%s: no heading in %s slugs to #%s" % (r["anchor_id"], path, slug))
    report(BLOCK, "sourcing-note slugs resolve", bad)


def check_decision_refs(rows):
    """A decision_ref whose target does not exist is a dangling cite."""
    anchors = set(re.findall(r'<a id="([^"]+)"></a>', rd(DECISIONS)))
    bad = []
    for r in rows:
        ref = r.get("decision_ref")
        if not ref:
            continue
        if not ref.startswith(DECISIONS + "#"):
            bad.append("%s: decision_ref %s is not a %s anchor"
                       % (r["anchor_id"], ref, DECISIONS))
        elif ref.split("#", 1)[1] not in anchors:
            bad.append("%s: decision_ref #%s has no target"
                       % (r["anchor_id"], ref.split("#", 1)[1]))
    report(BLOCK, "decision_ref targets exist", bad)


def check_line_endings(artifacts=None):
    """CRLF, tabs and trailing whitespace, which corrupt diffs and reviews."""
    bad = []
    for rel in (artifacts or TEXT_ARTIFACTS):
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            continue
        raw = io.open(path, "rb").read()
        if b"\r\n" in raw:
            bad.append("%s: %d CRLF line endings" % (rel, raw.count(b"\r\n")))
        if b"\t" in raw:
            bad.append("%s: contains tab characters" % rel)
        trailing = sum(1 for ln in raw.split(b"\n") if ln.rstrip() != ln)
        if trailing:
            bad.append("%s: %d lines with trailing whitespace" % (rel, trailing))
    report(BLOCK, "line endings and whitespace", bad)


def check_worklist_parity(index, text=None):
    """Assert the list, never the count.

    The worklist and the registry are two renderings of one set. Eleven per-group
    counts once summed to 209 against 252 rows, because each was a number someone
    typed rather than a length someone measured.
    """
    text = rd(WORKLIST) if text is None else text
    listed = dict(re.findall(r"^\|\s*`(A\d+\.\d+)`\s*\|\s*\*\*([ABD])\*\*",
                             text, re.M))
    # THE STATUS CELL, compared since U4 (2026-10-01): the parity read the tier alone, and 227 of 278 Status cells had
    # drifted from the registry's `status` with the check clean. The sixth cell of the row is the status.
    status = dict(re.findall(r"^\|\s*`(A\d+\.\d+)`\s*\|(?:[^|\n]*\|){4}\s*([^|\n]*?)\s*\|", text, re.M))
    bad = []
    for rid in sorted(set(index) - set(listed)):
        bad.append("%s: in the registry, absent from the worklist" % rid)
    for rid in sorted(set(index) & set(listed)):
        if index[rid]["tier"] != listed[rid]:
            bad.append("%s: tier %s in the registry, %s in the worklist"
                       % (rid, index[rid]["tier"], listed[rid]))
        if rid not in status:
            bad.append("%s: the worklist row has no Status cell to read" % rid)
        elif index[rid].get("status") != status[rid]:
            bad.append("%s: status %s in the registry, %s in the worklist"
                       % (rid, index[rid].get("status"), status[rid]))
    report(BLOCK, "worklist parity", bad)

    # The header's own total against the length of the tables beneath it. This is
    # the eighth instance in the package of a count contradicting the list it
    # summarises, and the first seven were all found by reading rather than by a
    # check -- including this one, on the day group 10 added a row.
    claimed = re.search(r"\*\*Anchors to verify\*\* \| \*\*(\d+)\*\*", text)
    report(BLOCK, "worklist header total equals its tables",
           [] if not claimed or int(claimed.group(1)) == len(listed) else
           ["the header claims %s anchors; the eleven group tables hold %d"
            % (claimed.group(1), len(listed))])

    pending = sorted(set(listed) - set(index))
    groups = sorted(set(p.split(".")[0] for p in pending))
    report(INFO, "worklist rows with no registry row yet, by group",
           ["%d rows across %s - the groups whose sitting has not run"
            % (len(pending), ", ".join(groups))] if pending else [])


def _reaches(index, a, b, seen=None):
    seen = seen or set()
    for u in index.get(a, {}).get("depends_on") or []:
        if u == b:
            return True
        if u not in seen and _reaches(index, u, b, seen | set([u])):
            return True
    return False


def check_depends_completeness(rows, index, exceptions):
    """A row that names an anchor which moves it must depend on that anchor.

    A9.02 omitted five registered rows that moved it, and nineteen dimensions of
    audit each checking a part missed it. THE DIRECTION TEST: a named row that
    itself depends (transitively) on this row is a DOWNSTREAM CONSUMER, not an
    upstream, and naming it is not a dependency - that alone removes eleven of
    the thirty-five raw hits without a judgement call.

    The residual is ratcheted, not waived, and the ratchet only turns one way.
    reference/depends_on_exceptions.yml holds the pairs open when the check was
    written; a NEW omission fails immediately, the list may not grow past its
    own `ceiling`, every pair must carry the phrase it was carried for, and a
    pair that no longer violates BLOCKS as a stale exception -- so fixing a row
    forces deleting its pair rather than leaving it to be tidied later.
    """
    entries = exceptions.get("open") or []
    ceiling = exceptions.get("ceiling")
    allowed = set((e["row"], e["names"]) for e in entries)
    rule = []
    if ceiling is not None and len(entries) > ceiling:
        rule.append("%s lists %d pairs against a ceiling of %d -- the ratchet only shrinks"
                    % (EXCEPTIONS, len(entries), ceiling))
    for e in entries:
        if not (e.get("reason") or "").strip():
            rule.append("%s: %s names %s with no reason recorded"
                        % (EXCEPTIONS, e["row"], e["names"]))
    new, known, live = [], 0, set()
    for r in rows:
        # a derived row stays derived for this check when it is pinned (U14, 2026-11-06): pinning replaced its status
        if r["status"] != "derived" and r.get("pinned_from") != "derived":
            continue
        rid = r["anchor_id"]
        named = set(ANCHOR_ID.findall(r["value"] or "")) - set([rid])
        for m in sorted(named - set(r.get("depends_on") or [])):
            if m not in index or _reaches(index, m, rid):
                continue
            live.add((rid, m))
            if (rid, m) in allowed:
                known += 1
            else:
                new.append("%s names %s and does not depend on it" % (rid, m))
    for row, name in sorted(allowed - live):
        rule.append("%s: %s / %s is listed but no longer violates -- delete the pair "
                    "and lower the ceiling" % (EXCEPTIONS, row, name))
    report(BLOCK, "depends_on completeness", new)
    report(BLOCK, "the depends_on ratchet only shrinks", rule)
    report(INFO, "depends_on debt carried in %s" % EXCEPTIONS,
           ["%d of %d pairs open, each needing a ruling" % (known, ceiling)] if known else [])


def check_one_value_per_quantity(rows):
    """Append-without-strike.

    A correction appended to a value field without removing what it corrects
    leaves two live answers to one question. The checkable shape: two different
    three-part series inside ONE sentence, with no marker in that sentence saying
    which of them is retired.
    """
    labelled_series = re.compile(r"([A-Za-z][A-Za-z ,'-]{3,40}?)\s*(?:is|are|=|:)?\s*"
                                 + TRIPLE.pattern.join(("(", ")")))
    bad = []
    for r in rows:
        seen = {}
        for m in labelled_series.finditer(norm(r["value"] or "")):
            label = re.sub(r"\s+", " ", m.group(1)).strip().lower()
            # strip EVERY leading filler word, not one: "and the peak need" and
            # "the peak need" have to normalise to the same label or the check
            # cannot see the repetition it exists to find.
            label = re.sub(r"^((and|the|of|a|an|in|to|at|or|with|plus|less|"
                           r"is|are|its|their|for|on|by)\s+)+", "", label)
            if len(label) < 4:
                continue
            seen.setdefault(label, set()).add(re.sub(r"\s+", "", m.group(2)))
        for label in sorted(seen):
            if len(seen[label]) > 1:
                bad.append("%s: '%s' is given as %s"
                           % (r["anchor_id"], label, " and ".join(sorted(seen[label]))))
    report(WARN, "one value per named quantity", bad)


# Generator constants that MIRROR a registry row. Each entry names the row, how to read its numbers
# out of the row's prose, and the generator attributes that must equal them.
#
# This exists because A5.38 was transcribed into TWO generators and they diverged: group 9 took the
# owner's DPI-acquisition ruling of 2026-09-15 and group 10 did not, so group 10 ran a whole window on
# KeHE 8/7.5/7 and DPI 2/2/2 against the registered 8/9.5/9 and 2/0/0. Both copies summed to 100 in
# every year, so no total caught it, and the generator cross-check could not: it asks whether the ROWS
# carry what the GENERATOR computes, never whether the generator's INPUTS match the registry. A stale
# input is internally consistent all the way down (FAILURES 2026-09-17).
A538_ACCOUNTS = [("Walmart", "Walmart"), ("Kroger", "Kroger"), ("Whole Foods direct", "WF"),
                 ("Regional", "Regional"), ("UNFI", "UNFI"), ("KeHE", "KeHE"), ("DPI", "DPI"),
                 ("small accounts", "small"), ("Sprouts direct", "Sprouts"), ("Costco", "Costco")]


def _a538_registered(index):
    """The account mix as A5.38's own prose states it, in percent."""
    text = " ".join(str(index["A5.38"]["value"]).split())
    out = {}
    for label, key in A538_ACCOUNTS:
        m = re.search(re.escape(label) + r"\s+(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)", text)
        if m:
            out[key] = [float(m.group(i)) for i in (1, 2, 3)]
    return out


# A6.26's mapping, A6.13's rates and A6.31's group-5 inputs, transcribed into group10_floors on 2026-09-18
# when A6.26, A6.31 and A6.15 became generator outputs. Checked from the day they exist, so the transcriptions
# that made those rows computable do not become the next SHARE.
A626_TYPES = [("short_ship", "short_ship"), ("late/OTIF", "late_otif"), ("label/ASN", "label_pallet_asn"),
              ("damaged", "damaged_unsaleables"), ("spoilage", "spoilage_shortdated"), ("pricing", "pricing_error"),
              ("receiving_miscount", "receiving_miscount"), ("post_audit", "post_audit"), ("overage", "overage"),
              ("other", "other")]
A626_CONTROLS = {"po_ack": "po_acknowledgment", "edi": "edi_reconciliation", "item_setup": "item_setup_preflight",
                 "receiving_audit": "receiving_audit", "price_book": "price_book_governance",
                 "three_way": "three_way_match", "none": "none"}
A613_CONTROLS = ("item_setup_preflight", "edi_reconciliation", "po_acknowledgment", "receiving_audit",
                 "three_way_match", "price_book_governance")


def _a626_registered(index):
    """A6.26's type -> control mapping as its own prose states it, % of each type's bucket-2 dollars."""
    text = " ".join(str(index["A6.26"]["value"]).split())
    m = re.search(r"Mapping:(.*?)\. RESULT", text)
    out = {}
    for seg in (m.group(1).split(";") if m else []):
        seg = re.sub(r"\([^)]*\)", "", seg).strip()
        for label, key in A626_TYPES:
            if seg.startswith(label + " "):
                out[key] = dict((A626_CONTROLS.get(c, c), float(w))
                                for c, w in re.findall(r"([a-z_]+)\s+(\d+)", seg[len(label):]))
    return out


def _first(index, anchor, pattern):
    """The first number a pattern captures in a row's prose, or None."""
    m = re.search(pattern, " ".join(str(index[anchor]["value"]).split()))
    return float(m.group(1)) if m else None


def _a6_mirrors(index, F):
    """A6.26's mapping, A6.13's rates and A6.31's inputs against group10_floors' transcriptions."""
    bad = []
    reg = _a626_registered(index)
    for key, want in sorted(reg.items()):
        got = dict((c, float(w)) for c, w in F.A626_MAP.get(key, {}).items())
        if got != want:
            bad.append("group10_floors.A626_MAP[%r] = %s; A6.26 registers %s" % (key, got, want))
    missing = sorted(set(F.A626_MAP) - set(reg))
    if missing:
        bad.append("A6.26's prose no longer states a mapping for: %s -- the mirror check cannot read it"
                   % ", ".join(missing))
    for c in A613_CONTROLS:
        want = _first(index, "A6.13", re.escape(c) + r"\s+(\d\.\d+)")
        if want is None or F.A613_RATE.get(c) != want:
            bad.append("group10_floors.A613_RATE[%r] = %s; A6.13 registers %s" % (c, F.A613_RATE.get(c), want))
    for label, got, anchor, pattern in (
            # y1 too since U4: A5.11's in-full and internal fill derive from BOTH endpoints (owner, 2026-09-25)
            ("A512_Y1['rr']", F.A512_Y1["rr"], "A5.12", r"retailer_reduction ([\d.]+) ->"),
            ("A512_Y1['cr']", F.A512_Y1["cr"], "A5.12", r"cinderhaven_reduction ([\d.]+) ->"),
            ("A512_Y1['ff']", F.A512_Y1["ff"], "A5.12", r"fill_failure ([\d.]+) ->"),
            ("A512_Y3['rr']", F.A512_Y3["rr"], "A5.12", r"retailer_reduction [\d.]+ -> ([\d.]+)"),
            ("A512_Y3['cr']", F.A512_Y3["cr"], "A5.12", r"cinderhaven_reduction [\d.]+ -> ([\d.]+)"),
            ("A512_Y3['ff']", F.A512_Y3["ff"], "A5.12", r"fill_failure [\d.]+ -> ([\d.]+)"),
            ("A511_WELL_RUN['internal']", F.A511_WELL_RUN["internal"], "A5.11", r"WELL-RUN endpoint: internal ([\d.]+)"),
            ("A511_WELL_RUN['on_time']", F.A511_WELL_RUN["on_time"], "A5.11",
             r"WELL-RUN endpoint: internal [\d.]+ / scored [\d.]+ / on-time ([\d.]+)"),
            ("ONTIME[2]", F.ONTIME[2], "A5.11", r"On-time \(prepaid, Walmart clock\): [\d.]+% / [\d.]+% / ([\d.]+)%"),
            ("SPOILAGE_REMOVAL", F.SPOILAGE_REMOVAL, "A6.31", r"spoilage ([\d.]+) \(practitioner")):
        want = _first(index, anchor, pattern)
        if want is None or got != want:
            bad.append("group10_floors.%s = %s; %s registers %s" % (label, got, anchor, want))
    return bad


_LOCATOR_ID = re.compile(r"A\\?\d+\\?\.\\?\d+")
_LOCATOR_DATE = re.compile(r"\d{4}\\?-\d{2}")
_LOCATOR_MAGNITUDE = re.compile(r"\\?\d+\\?\.\\?\d+|\d+\s*\\?%|\\?\$\s*\\?\d")


def check_locator_hygiene(figures=None, locators=None):
    """RULE 1 (owner, 2026-09-18): a locator anchors on sentence CONTENT and nothing else.

    A locator that names an anchor id, a date or a literal magnitude has a half-life, and each
    of the three has already been found going stale or silent in this file:

      AN ID.        Four locators named the entry that superseded a figure -- `reads-group-11\\):`.
                    Each broke the moment those bullets were themselves superseded, which is a
                    supersede marker's whole purpose. Worse than breaking: the locator went on
                    matching the OLD bullet alone, so a figure stale through two restatements
                    ($0.10M -> $0.27M -> $0.50M in DECISIONS#A9.13) sat behind a green check
                    until the locator was rewritten. That is the failure this rule exists for.
      A DATE.       The same half-life, for the same reason.
      A MAGNITUDE.  `\\$2\\.945 a jar` pins the locator to the figure it is supposed to find
                    independently, so the anchor moves whenever the value does. Thirteen were
                    found and rewritten with the figure replaced by a wildcard, keeping WHERE and
                    dropping WHAT.

    A bare ordinal is content, not a magnitude: "bucket 2" and "Bucket 3 =" name a thing, and
    fifty locators use them legitimately. The pattern below wants a decimal, or an integer
    carrying a percent or a currency sign.
    """
    bad = []
    locators = MIRROR_LOCATORS if locators is None else locators
    phrases = [] if figures and locators is MIRROR_LOCATORS else \
        [("%s.%s%s" % (m, n, p), None, None, None, None, at[0])
         for (m, n), (_, locs, _) in sorted(locators.items()) for p, at in locs.items()]
    for label, _vals, _where, _places, _pairs, after in list(figures or group11_figures()) + phrases:
        if not after:
            continue
        for kind, pat in (("an anchor id", _LOCATOR_ID), ("a date", _LOCATOR_DATE),
                          ("a literal magnitude", _LOCATOR_MAGNITUDE)):
            if pat.search(after):
                bad.append("%s: the locator names %s -- %r" % (label, kind, after))
    report(BLOCK, "locators anchor on sentence content only", bad)


def _a801_mirror(index, G, F):
    """A8.01's headline DTC share against the `S_DTC` both generators transcribe.

    A8.01 was the last live member of the A5.38 mirror class: `S_DTC = 0.10` sits in
    group9_ledger and group10_floors, each commented `# A8.01`, with nothing comparing
    either copy to the row. PROBED 2026-09-21 -- restating A8.01 to 12% left the WHOLE
    GATE CLEAN, because every figure downstream is computed FROM the copies and is
    internally consistent with them. The headline of the row that moves every wholesale
    denominator in the package was watched by nothing at all.
    """
    want = _first(index, "A8.01", r"DTC SHARE OF GROSS[^=]*= (\d+(?:\.\d+)?)%")
    if want is None:
        return ["A8.01's prose no longer states a DTC share of gross -- the mirror cannot read it"]
    bad = []
    for name, got in (("group9_ledger.S_DTC", getattr(G, "S_DTC", None)),
                      ("group10_floors.S_DTC", getattr(F, "S_DTC", None))):
        if got is None:
            bad.append("%s is gone; A8.01 registers %s%% of gross" % (name, want))
        elif round(got * 100.0, 6) != round(want, 6):
            bad.append("%s = %s (%.6g%% of gross); A8.01 registers %s%%" % (name, got, got * 100.0, want))
    return bad


def _a1101_mirror(index, G):
    """A11.01's current-state marketplace share against the `AMAZON_SHARE` group 9 transcribes.

    The last member of the transcription class this pass has been closing: `AMAZON_SHARE`
    sat in group9_ledger commented `# A11.01` with nothing comparing it to the row, and
    group11_compliance reads it through `G.` rather than keeping a second copy -- so one
    edge, not two. It is worth an edge anyway: on 2026-09-21 A11.01's own sentence gained
    "IN THE CURRENT STATE" around these very numbers, and an edit that reaches a row's
    figures is exactly what a mirror exists to survive.
    """
    text = " ".join(str(index["A11.01"]["value"]).split())
    m = re.search(r"at (\d+(?:\.\d+)?) / (\d+(?:\.\d+)?) / (\d+(?:\.\d+)?)% of it IN THE CURRENT STATE", text)
    if not m:
        return ["A11.01's prose no longer states a current-state marketplace share -- the mirror cannot read it"]
    want = [float(m.group(i)) for i in (1, 2, 3)]
    got = getattr(G, "AMAZON_SHARE", None)
    if got is None:
        return ["group9_ledger.AMAZON_SHARE is gone; A11.01 registers %s%% of A8.01's share" % want]
    got = [round(x * 100.0, 6) for x in got]
    if got != [round(x, 6) for x in want]:
        return ["group9_ledger.AMAZON_SHARE = %s (%s%% of A8.01's share); A11.01 registers %s%%"
                % (getattr(G, "AMAZON_SHARE"), got, want)]
    return []


def _band_midpoint(text):
    """The midpoint of a band written '+/-N' or '+A-B' (or 'A-B'), or None if the text is neither."""
    m = re.fullmatch(r"\+/-(\d+(?:\.\d+)?)", text.strip())
    if m:
        return 0.0
    m = re.fullmatch(r"\+?(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)", text.strip())
    return (float(m.group(1)) + float(m.group(2))) / 2.0 if m else None


def _a415_mirror(index, G):
    """A4.15's two endpoints against the `OVERSETTLE` and `OVERSETTLE_ACHIEVABLE` group 9 transcribes (2026-09-23).

    `OVERSETTLE_ACHIEVABLE` entered group9_ledger with A9.02's derived achievable (81f7705) commented `# A4.15`, and
    achievable()'s settlement term is the P&L at it against the P&L at `OVERSETTLE`: the difference between two
    transcriptions of one row, which nothing compared to the row. Each is its band's midpoint, as the row says of the
    current one, so the mirror reads both bands and the printed midpoint.
    """
    text = " ".join(str(index["A4.15"]["value"]).split())
    bad = []
    m = re.search(r"current \+(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)% -> achievable within ([^%]+)%", text)
    mid = re.search(r"carries the MIDPOINT, (\d+(?:\.\d+)?)%", text)
    if not m or not mid:
        return ["A4.15's prose no longer states its two endpoints and the midpoint the P&L carries -- the mirror "
                "cannot read them"]
    current = (float(m.group(1)) + float(m.group(2))) / 2.0
    got = round(G.OVERSETTLE * 100.0, 6)
    if not got == round(current, 6) == round(float(mid.group(1)), 6):
        bad.append("group9_ledger.OVERSETTLE = %s (%s%%); A4.15's current band %s-%s%% has midpoint %s and the row "
                   "prints %s%%" % (G.OVERSETTLE, got, m.group(1), m.group(2), current, mid.group(1)))
    achievable = _band_midpoint(m.group(3))
    got = getattr(G, "OVERSETTLE_ACHIEVABLE", None)
    if achievable is None:
        bad.append("A4.15's achievable band %r is not a band the mirror can read" % m.group(3))
    elif got is None:
        bad.append("group9_ledger.OVERSETTLE_ACHIEVABLE is gone; A4.15's achievable midpoint is %s%%" % achievable)
    elif round(got * 100.0, 6) != round(achievable, 6):
        bad.append("group9_ledger.OVERSETTLE_ACHIEVABLE = %s (%s%%); A4.15's achievable band %s%% has midpoint %s%%"
                   % (got, got * 100.0, m.group(3), achievable))
    return bad


def _a811_mirror(index, G):
    """A8.11's own-site contribution before marketing, y1 -> y3 current and y3 achievable, against
    `group9_ledger.dtc_contribution()`.

    New with the derived achievable (81f7705): the DTC term is own-site dollars times the step between the two, so
    a restatement of either end of A8.11 moved A9.02's achievable with the gate clean. Since U4 the generator
    DERIVES both by the row's own construction (owner, 2026-10-01); it typed (0.19, 0.34) before, which reproduced
    only on the margin rounded to 68%. The row prints whole percents, so each is compared at 0 places.
    """
    text = " ".join(str(index["A8.11"]["value"]).split())
    cur = re.search(r"contribution before marketing (\d+(?:\.\d+)?)% -> (\d+(?:\.\d+)?)%", text)
    ach = re.search(r"-> contribution (\d+(?:\.\d+)?)%", text)
    if not cur or not ach:
        return ["A8.11's prose no longer states its contribution and its achievable one -- the mirror cannot read "
                "them"]
    printed = [float(cur.group(1)), float(cur.group(2)), float(ach.group(1))]
    c = G.dtc_contribution()
    computed = [c["current"][0] * 100, c["current"][2] * 100, c["achievable"] * 100]
    if [float("%.0f" % x) for x in computed] != printed:
        return ["A8.11 prints contribution %s%% -> %s%% and %s%% achievable; dtc_contribution() gives %s" % (
            tuple("%g" % x for x in printed) + (" / ".join("%.2f" % x for x in computed),))]
    return []


def _achievable_input_mirrors(index, G, F):
    """The registered constants G.achievable() reads beyond its two new ones, against the rows that register them.

    Checked 2026-09-23. A4.31's invalid share of gross, A4.06's achievable filing rate and A4.07's achievable
    recovery set the bucket-1 residual that comes off A6.15's pool, and the A6.15 entries read them only as A6.15's
    own prose prints them -- a transcription compared with a copy, not with its row. A4.01's line is what the pool
    replaces, and it is transcribed in BOTH generators with nothing comparing the two. A4.14's rate card sets the
    over-settlement the settlement term removes. A1.01's ladder is the achievable's denominator and every P&L line's
    base, and it too sits in both generators with nothing comparing either copy to the row: $25M grown 30 / 25 / 15%,
    each year exact, never rounded (owner, 2026-09-25: exact wins). Until U4 the generators carried 46.719 and this
    check rounded the ladder to $1K to match them. S_DTC and AMAZON_SHARE, which size own-site dollars, are
    _a801_mirror's and _a1101_mirror's; A6.15's pool is watched where A6.15 prints it.
    """
    from decimal import Decimal
    bad = []
    a101 = re.search(r"\$(\d+(?:\.\d+)?)M at window start; growth (\d+(?:\.\d+)?)% / (\d+(?:\.\d+)?)% / "
                     r"(\d+(?:\.\d+)?)%", " ".join(str(index["A1.01"]["value"]).split()))
    if not a101:
        bad.append("A1.01's prose no longer states the start and the growth ladder -- the mirror cannot read them")
    else:
        level, want = Decimal(a101.group(1)), []
        for g in a101.groups()[1:]:
            level = level * (1 + Decimal(g) / 100)
            want.append(float(level))
        for name, const in (("group9_ledger.GROSS", G.GROSS), ("group10_floors.GROSS", F.GROSS)):
            if list(const) != want:
                bad.append("%s = %s; A1.01's ladder gives %s" % (name, const, want))
    a401 = re.search(r"y1 / y2 / y3: (\d+(?:\.\d+)?)% / \d+(?:\.\d+)?% / (\d+(?:\.\d+)?)% of gross",
                     " ".join(str(index["A4.01"]["value"]).split()))
    if not a401:
        bad.append("A4.01's prose no longer states its y1 and y3 rates -- the mirror cannot read them")
    else:
        for name, const in (("group9_ledger.OPDED", G.OPDED), ("group10_floors.OPDED", F.OPDED)):
            got = [round(const[0] * 100.0, 6), round(const[2] * 100.0, 6)]
            if got != [round(float(a401.group(1)), 6), round(float(a401.group(2)), 6)]:
                bad.append("%s = %s; A4.01 registers %s%% in y1 and %s%% in y3"
                           % (name, const, a401.group(1), a401.group(2)))
    if [round(x, 9) for x in G.OPDED] != [round(x, 9) for x in F.OPDED]:
        bad.append("group9_ledger.OPDED = %s and group10_floors.OPDED = %s: two transcriptions of A4.01 disagree"
                   % (G.OPDED, F.OPDED))
    for label, got, anchor, pattern in (
            ("group9_ledger.TRADE", G.TRADE * 100.0, "A4.14", r"Total rate-card trade (\d+(?:\.\d+)?)% of gross"),
            ("group10_floors.INVALID_TRADE", F.INVALID_TRADE * 100.0, "A4.31", r"~ (\d+(?:\.\d+)?)% of gross, DERIVED"),
            ("group10_floors.F_ACHIEVABLE", F.F_ACHIEVABLE * 100.0, "A4.06",
             r"Achievable endpoint: (\d+(?:\.\d+)?)% dollar-weighted on bucket 1"),
            ("group10_floors.R1_ACHIEVABLE", F.R1_ACHIEVABLE, "A4.07",
             r"-> (\d+(?:\.\d+)?) dollar recovery on disputed bucket-1 dollars")):
        want = _first(index, anchor, pattern)
        if want is None or round(got, 6) != round(want, 6):
            bad.append("%s = %s; %s registers %s" % (label, round(got, 6), anchor, want))
    return bad


def _a906_mirror(index, F):
    """A9.06's dispute FTE against group10_floors.A906_DISPUTE_FTE, which A4.06's FTE-needed figure reads
    (fte_for_count_rate). The gate carried the copy until 2026-09-23; the owner moved it into the generator."""
    m = re.search(r"dispute share is (\d+(?:\.\d+)?) FTE \(y1, y2\) / (\d+(?:\.\d+)?) \(y3\)",
                  " ".join(str(index["A9.06"]["value"]).split()))
    if not m:
        return ["A9.06's prose no longer states the clerk's dispute FTE by year -- the mirror cannot read it"]
    want = (float(m.group(1)), float(m.group(1)), float(m.group(2)))
    if tuple(round(x, 6) for x in F.A906_DISPUTE_FTE) != tuple(round(x, 6) for x in want):
        return ["group10_floors.A906_DISPUTE_FTE = %s; A9.06 registers %s" % (F.A906_DISPUTE_FTE, want)]
    return []


def _a301_mirror(index, G):
    """A3.01's layered cost against group 9's `COST_12` (2026-09-23).

    The owner ruled that 2.61 is the registered layered cost, 2.10 + 0.15 + 0.36, each layer to the cent: "+7% +
    17%" was a description that rounded, not a formula (DECISIONS#restating-the-21). `COST_12 = 2.61` was a
    transcription of the row that nothing compared to it. Checked in Decimal, because a cent is the rule
    (#exactness-has-no-exception); neither layer, 0.147 or 0.357, sits on a half-cent, so the rounding mode is moot.
    """
    from decimal import Decimal, ROUND_HALF_UP
    text = " ".join(str(index["A3.01"]["value"]).split())
    man = re.search(r"MANUFACTURED cost \([^)]*\) = (\d+\.\d+)", text)
    lay = re.search(r"freight-in (\d+)% \+ overhead (\d+)%, each layer to the cent: (\d+\.\d+) \+ (\d+\.\d+) \+ "
                    r"(\d+\.\d+) = (\d+\.\d+)", text)
    if not man or not lay:
        return ["A3.01's prose no longer states the manufactured cost and its cent layers -- the mirror cannot read "
                "them"]
    bad = []
    cent = Decimal("0.01")
    base = Decimal(man.group(1))
    pf, po, l0, l1, l2, total = (Decimal(x) for x in lay.groups())
    for name, layer, share in (("freight-in", l1, pf), ("overhead", l2, po)):
        want = (base * share / 100).quantize(cent, rounding=ROUND_HALF_UP)
        if layer != want:
            bad.append("A3.01's %s layer prints %s; %s%% of %s is %s to the cent" % (name, layer, share, base, want))
    if l0 != base:
        bad.append("A3.01's layer sum starts at %s; its manufactured cost is %s" % (l0, base))
    if l0 + l1 + l2 != total:
        bad.append("A3.01's layers %s + %s + %s sum to %s, not the %s printed" % (l0, l1, l2, l0 + l1 + l2, total))
    if Decimal(repr(G.COST_12)) != total:
        bad.append("group9_ledger.COST_12 = %s; A3.01 registers %s" % (G.COST_12, total))
    if Decimal(repr(G.COST_MANUFACTURED)) != base:   # A3.29's rolled standard reads it (U21)
        bad.append("group9_ledger.COST_MANUFACTURED = %s; A3.01 registers a manufactured cost of %s"
                   % (G.COST_MANUFACTURED, base))
    return bad


def _a1130_mirror(index, G):
    """A11.30's ACoS band, in its value and its plausibility anchor, against the point group 9 carries (2026-09-23).

    The row signs the point at the band's midpoint, and the restatement of 2026-09-23 wrote the band into the
    plausibility anchor as figures where it had been words ("a fifth to a third"). `ACOS` is watched as a figure;
    this ties it to the band it is the midpoint of, and the two printings of the band to each other.
    """
    val = re.search(r"ACoS (\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)% OF AMAZON SALES",
                    " ".join(str(index["A11.30"]["value"]).split()))
    pa =re.search(r"ACoS of (\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)% of the sale",
                   " ".join(str(index["A11.30"].get("plausibility_anchor") or "").split()))
    if not val or not pa:
        return ["A11.30's value or plausibility anchor no longer states the ACoS band -- the mirror cannot read it"]
    bad = []
    if val.groups() != pa.groups():
        bad.append("A11.30 states the ACoS band as %s-%s%% in its value and %s-%s%% in its plausibility anchor"
                   % (val.group(1), val.group(2), pa.group(1), pa.group(2)))
    mid = (float(val.group(1)) + float(val.group(2))) / 2.0
    if round(G.ACOS * 100.0, 6) != round(mid, 6):
        bad.append("group9_ledger.ACOS = %s; A11.30 signs the point at its band's midpoint, %s%%" % (G.ACOS, mid))
    if [round(x * 100.0, 6) for x in G.ACOS_BAND] != [round(float(x), 6) for x in val.groups()]:   # A11.32's band (U21)
        bad.append("group9_ledger.ACOS_BAND = %s; A11.30 states %s-%s%%" % (G.ACOS_BAND, val.group(1), val.group(2)))
    return bad


def _group7_mirrors(index, F):
    """A3.25's targets, A3.08's endings, A3.28's tolerance, A7.08's ramps and A7.03's band against the
    constants `group10_floors` transcribes for the scan identity (2026-09-22). Checked from the day they exist,
    so the transcriptions that made A3.08, A7.29 and A7.03 computable do not join the unmirrored 153."""
    bad = []
    for label, key in (("Walmart", "Walmart"), ("Kroger", "Kroger"), ("Sprouts", "Sprouts"),
                       ("Whole Foods", "WF"), ("Regional", "Regional"), ("Costco", "Costco")):
        want = _first(index, "A3.25", re.escape(label) + r" (\d+(?:\.\d+)?)[,.]")
        if want is None or F.A325_TARGET.get(key) != want:
            bad.append("group10_floors.A325_TARGET[%r] = %s; A3.25 registers %s" % (key, F.A325_TARGET.get(key), want))
    text = " ".join(str(index["A3.08"]["value"]).split())
    for label, key in (("WF", "WF"), ("Sprouts", "Sprouts"), ("Kroger", "Kroger"), ("Regional", "Regional"),
                       ("Walmart", "Walmart"), ("Costco", "Costco")):
        m = re.search(re.escape(label) + r" [\d./=]+ -> [\d.]+ \(([.\d/]+)\)", text)
        want = sorted(float("0" + e) for e in m.group(1).split("/")) if m else None
        if want is None or sorted(F.A308_ENDINGS.get(key, ())) != want:
            bad.append("group10_floors.A308_ENDINGS[%r] = %s; A3.08 registers %s" % (key, F.A308_ENDINGS.get(key), want))
    want = _first(index, "A3.28", r"within (\d+(?:\.\d+)?) point")
    if want is None or F.A328_TOLERANCE != want:
        bad.append("group10_floors.A328_TOLERANCE = %s; A3.28 registers %s" % (F.A328_TOLERANCE, want))
    text = " ".join(str(index["A7.08"]["value"]).split())
    m = re.search(r"Walmart ([\d.]+) y2 / ([\d.]+) y3, Sprouts ([\d.]+) y2 / ([\d.]+) y3, Costco ([\d.]+) y3, "
                  r"independents ([\d.]+) y2 / ([\d.]+) y3", text)
    got = F.A708_RAMP
    if not m:
        bad.append("A7.08's prose no longer states the ramp shares -- the mirror cannot read it")
    else:
        v = [float(x) for x in m.groups()]
        want = {"Walmart": [1.0, v[0], v[1]], "Sprouts": [1.0, v[2], v[3]], "Costco": [1.0, 1.0, v[4]],
                "independents": [1.0, v[5], v[6]]}
        if got != want:
            bad.append("group10_floors.A708_RAMP = %s; A7.08 registers %s" % (got, want))
    # A7.14's rate and episode shape, read by void_episodes() for A7.15 (2026-09-24); y2 is the midpoint
    text = " ".join(str(index["A7.14"]["value"]).split())
    m = re.search(r"not on shelf: (\d+)% / [\d.]+% / (\d+)% y1 / y2 / y3", text)
    e = re.search(r"median (\d+) days, (\d+)% >2 weeks", text)
    if not m or F.A714_NOT_ON_SHELF != [int(m.group(1)) / 100.0, (int(m.group(1)) + int(m.group(2))) / 200.0,
                                         int(m.group(2)) / 100.0]:
        bad.append("group10_floors.A714_NOT_ON_SHELF = %s; A7.14 reads %s"
                   % (F.A714_NOT_ON_SHELF, m.groups() if m else None))
    if not e or F.A714_EPISODE_DAYS != (float(e.group(1)), 14.0, int(e.group(2)) / 100.0):
        bad.append("group10_floors.A714_EPISODE_DAYS = %s; A7.14 reads %s"
                   % (F.A714_EPISODE_DAYS, e.groups() if e else None))
    # A7.30 (owner, 2026-09-24): the y1 point is a constant, the later years derive; both are read from the row
    text = " ".join(str(index["A7.30"]["value"]).split()) if "A7.30" in index else ""
    m = re.search(r"y1 / y2 / y3: ([\d.]+) / ([\d.]+) / ([\d.]+)%", text)
    if not m:
        bad.append("A7.30's prose no longer states its series -- the mirror cannot read it")
    else:
        want = [float(x) for x in m.groups()]
        got = [float(x) * 100 for x in F.wf_leg_share()]
        if F.A730_WF_LEG_Y1 * 100 != want[0] or any(round(g, 1) != w for g, w in zip(got, want)):
            bad.append("group10_floors' A7.30 series is %s (y1 constant %s); A7.30 registers %s"
                       % (["%.1f" % g for g in got], F.A730_WF_LEG_Y1, want))
    m = re.search(r"sell (\d+)-(\d+) units per store per week", str(index["A7.03"].get("plausibility_anchor")))
    if not m or F.A703_BAND != (float(m.group(1)), float(m.group(2))):
        bad.append("group10_floors.A703_BAND = %s; A7.03's plausibility band reads %s"
                   % (F.A703_BAND, m.groups() if m else None))
    # A7.04's door plan and the plan it was grown from, A7.13's bars and A3.06's ceilings, added 2026-09-22 with the
    # level ruling. A704_DOORS had been transcribed TWICE inside group10_floors (RETAIL_DOORS beside it, nothing
    # comparing them); one transcription now, and this is what watches it.
    text = " ".join(str(index["A7.04"]["value"]).split())
    for label, const, pattern in (
            ("A704_DOORS", F.A704_DOORS, r"y1 / y2 / y3: Walmart ([\d,]+) / ([\d,]+) / ([\d,]+); Kroger ([\d,]+) / "
                                         r"([\d,]+) / ([\d,]+); Whole Foods ([\d,]+) / ([\d,]+) / ([\d,]+); Regional "
                                         r"([\d,]+) / ([\d,]+) / ([\d,]+); distributor-served independents and "
                                         r"natural chains ([\d,]+) / ([\d,]+) / ([\d,]+); Sprouts ([\d,]+) / ([\d,]+) "
                                         r"/ ([\d,]+); Costco ([\d,]+) / ([\d,]+) / ([\d,]+)"),
            ("A704_BASE", F.A704_BASE, r"ONE - Walmart ([\d,]+) / ([\d,]+) / ([\d,]+); Kroger ([\d,]+) / ([\d,]+) / "
                                       r"([\d,]+); Whole Foods ([\d,]+) / ([\d,]+) / ([\d,]+); Regional ([\d,]+) / "
                                       r"([\d,]+) / ([\d,]+); independents ([\d,]+) / ([\d,]+) / ([\d,]+); Sprouts "
                                       r"([\d,]+) / ([\d,]+) / ([\d,]+)")):
        m = re.search(pattern, text)
        if not m:
            bad.append("A7.04's prose no longer states the plan %s mirrors -- the mirror cannot read it" % label)
            continue
        got = [int(x.replace(",", "")) for x in m.groups()]
        keys = ["Walmart", "Kroger", "WF", "Regional", "independents", "Sprouts"] + (["Costco"] if label == "A704_DOORS" else [])
        want = sum((list(const[k]) for k in keys), [])
        if got != want:
            bad.append("group10_floors.%s = %s; A7.04 registers %s" % (label, want, got))
    text = " ".join(str(index["A7.13"]["value"]).split())
    for acct, label in (("Walmart", "Walmart"), ("Kroger", "Kroger"), ("Sprouts", "Sprouts"),
                        ("WF", "Whole Foods"), ("Regional", "Regional"), ("independents", "distributors")):
        m = re.search(re.escape(label) + r" (\d+(?:\.\d+)?)", text)
        if not m or F.A713_BARS.get(acct) != float(m.group(1)):
            bad.append("group10_floors.A713_BARS[%r] = %s; A7.13 registers %s"
                       % (acct, F.A713_BARS.get(acct), m.group(1) if m else None))
    text = " ".join(str(index["A3.06"]["value"]).split())
    for banner, label in (("Walmart", "Walmart"), ("Kroger", "Kroger"), ("Sprouts", "Sprouts"),
                          ("WF", "Whole Foods"), ("Regional", "Regional"), ("Costco", "Costco")):
        m = re.search(re.escape(label) + r" \d+(?:\.\d+)?-(\d+(?:\.\d+)?)", text)
        if not m or F.A306_CEILING.get(banner) != float(m.group(1)):
            bad.append("group10_floors.A306_CEILING[%r] = %s; A3.06's band top reads %s"
                       % (banner, F.A306_CEILING.get(banner), m.group(1) if m else None))
    return bad


def check_door_plan_minimum(index):
    """A7.04's plan is the SMALLEST whole-door plan grown from the 2026-09-05 one that clears A5.28's floor.

    The owner's level ruling of 2026-09-22 (DECISIONS#A7.04-door-plan) is a RULE, not a set of numbers: the doors
    grow by the minimum that clears the floor, Sprouts capped at its filed universe and Costco left alone. This
    re-solves that minimum and compares, so a later edit to the doors, to A5.38's mix, to A7.28's share or to
    anything else that moves A7.03's y3 mean fails the gate rather than leaving the plan quietly non-minimal.

    THE SEARCH IS EXACT AND SHARES NO TOLERANCE WITH WHAT IT CHECKS (corrected 2026-09-22,
    DECISIONS#A7.04-exact-integer-search). The rule had been written as "the smallest single FACTOR, each count
    rounded up", and no such factor exists: Walmart y3 and the independents' y3 need f > 9/8 while seven other
    lines need f <= 9/8, so the feasible interval is empty. The plan that was registered existed only inside
    `math.ceil(d * f - 1e-9)`, and this check re-solved with that same epsilon -- rule and check agreeing only
    with each other, which is the `quarter_risk` shape FAILURES records on 2026-09-21.

    What makes it exact: `ceil(d * f) = n` exactly when `(n-1)/d < f <= n/d`, so the plan is constant on the
    half-open interval between consecutive breakpoints `n/d` and takes its value at the RIGHT endpoint. The
    breakpoints are enumerated as Fractions, the counts are ceiled in integer arithmetic, and the answer is a
    PLAN -- the scale is only how the plan is indexed. More doors lower the mean and nothing else in the identity
    moves with them, so feasibility is monotone in the index and a bisection over the breakpoints is sound; the
    certificate is printed rather than assumed, by requiring the plan below the answer to FAIL the floor.
    """
    from fractions import Fraction
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import group10_floors as F
    import group11_compliance as H
    bound = H.cadence_bound()["sigma_at_mid"]
    target = F.A703_TOP_QUINTILE * 0.2 / NORM.cdf(bound - NORM.inv_cdf(0.8))

    def plan(f):
        """The whole-door plan at scale f, an exact Fraction. Integer ceil, no epsilon."""
        out = {}
        for b, v in F.A704_BASE.items():
            if b in F.A704_SCALED:
                out[b] = [min(-((-d * f.numerator) // f.denominator), F.A704_UNIVERSE.get(b, 10 ** 9)) if d else 0
                          for d in v]
            else:
                out[b] = list(v)
        return out

    def y3_mean(doors):
        saved = F.A704_DOORS
        F.A704_DOORS = doors
        try:
            return F.scan_identity()[2]["upw"]
        finally:
            F.A704_DOORS = saved
    steps = sorted(set(Fraction(n, d) for b in F.A704_SCALED for d in F.A704_BASE[b] if d
                       for n in range(d + 1, 2 * d + 1)))
    bad = []
    if y3_mean(plan(steps[-1])) > target:
        report(BLOCK, "the door plan is the minimum that clears A5.28's floor",
               ["no plan up to twice the 2026-09-05 one clears A5.28's floor at %.6f" % target])
        return
    lo, hi = -1, len(steps) - 1                   # lo fails the floor (index -1 is the unscaled base), hi clears
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if y3_mean(plan(steps[mid])) <= target:
            hi = mid
        else:
            lo = mid
    want = plan(steps[hi])
    below = plan(steps[lo]) if lo >= 0 else dict((b, list(v)) for b, v in F.A704_BASE.items())
    if y3_mean(below) <= target:                  # the certificate: the step below must fail, or it is not minimal
        bad.append("the search is not minimal -- the plan one step below also clears the floor: %s" % below)
    if dict((k, list(v)) for k, v in F.A704_DOORS.items()) != want:
        bad.append("A7.04's plan is not the minimum that clears A5.28's floor: the minimum is %s, the plan is %s"
                   % (want, dict((k, list(v)) for k, v in F.A704_DOORS.items())))
    got = y3_mean(F.A704_DOORS)
    if got > target:
        bad.append("A7.03's y3 mean is %.6f against A5.28's floor at %.6f -- the plan no longer clears it"
                   % (got, target))
    report(BLOCK, "the door plan is the minimum that clears A5.28's floor", bad)


def check_generator_mirrors(index):
    """A generator constant that mirrors a registry row must equal it."""
    bad = []
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import group9_ledger as G
        import group10_floors as F
    except Exception as exc:                                  # pragma: no cover - import failure
        report(BLOCK, "generator constants mirror the registry", ["generators did not import: %s" % exc])
        return
    bad.extend(_a6_mirrors(index, F))
    bad.extend(_a801_mirror(index, G, F))
    bad.extend(_a1101_mirror(index, G))
    bad.extend(_group7_mirrors(index, F))
    # 2026-09-23: A9.02's derived achievable and the restated 21 (DECISIONS#restating-the-21)
    bad.extend(_a415_mirror(index, G))
    bad.extend(_a811_mirror(index, G))
    bad.extend(_achievable_input_mirrors(index, G, F))
    bad.extend(_a906_mirror(index, F))
    bad.extend(_a301_mirror(index, G))
    bad.extend(_a1130_mirror(index, G))
    bad.extend(_a201_line_mirror(F))
    reg = _a538_registered(index)
    missing = [k for _, k in A538_ACCOUNTS if k not in reg]
    if missing:
        bad.append("A5.38's prose no longer states a mix for: %s -- the mirror check cannot read it"
                   % ", ".join(missing))
    for name, const, scale in (("group9_ledger.SHARE", getattr(G, "SHARE", {}), 1.0),
                               ("group10_floors.SHARE", getattr(F, "SHARE", {}), 100.0)):
        for key, want in sorted(reg.items()):
            got = const.get(key)
            if got is None:
                bad.append("%s has no line for %s; A5.38 registers %s" % (name, key, want))
                continue
            got = [round(x * scale, 6) for x in got]
            if got != [round(x, 6) for x in want]:
                bad.append("%s[%r] = %s; A5.38 registers %s" % (name, key, got, want))
    for y in range(3):
        tot = sum(v[y] for v in reg.values())
        if abs(tot - 100.0) > 1e-9:
            bad.append("A5.38's own y%d mix sums to %s, not 100" % (y + 1, tot))
    report(BLOCK, "generator constants mirror the registry", bad)


# EVERY generator constant that names a registry row must publish its value there (owner, 2026-09-25; U2 of the
# closure plan). The hand-written mirrors above cover 78 constants; the rest were a class the gate could not see --
# doctoring A4.05's short_ship 26 -> 21 IN THE ROW left the gate CLEAN, exit 0, because group10_floors.A405_SHARE
# kept its own 26 and nothing compared them. This reads every module-level constant whose comment names an anchor
# -- on its own line; else on the comment lines of its assignment or the comment lines straight after it; else in
# the comment block directly above -- and requires each numeric value to be PRINTED in that row's figure-publishing
# fields (FINGERPRINTED_FIELDS). A constant that is not a figure is excluded by an explicit "mirror-exempt:" on its
# own comment line -- "NAME[i]" in the reason scopes it to that element -- and the exemptions are PRINTED, never
# skipped silently.
#
# A PRINT COUNTS ONLY IF IT RESOLVES THE VALUE (adversarial review, 2026-09-25). The first version rounded the value
# to the printed figure's own places under every scale, so with the scales that shrink a value a bare "0", "1" or
# "2" stood for almost anything: 364 of 765 leaves survived every mutation, and a registry row stripped to
# "0 accounts." left the check silent.
#
# OPTION C (owner, 2026-09-28; DECISIONS#option-c) replaced the rounding path. A typed value -- read from the
# code's syntax, never the module's runtime value -- is published only by a figure it EQUALS, in the FIRST row the
# constant names, at ONE unit scale shared with its siblings (a list's elements, a dict's values, a set's members;
# a tuple's positions and a dict(...)'s keywords are records, each its own). Typed arithmetic is published by its
# result or else by the literals typed into it, and a repeat count is a typed literal. `dict(...)` of literals is
# a dict; a constant with no row of its own takes its section divider's; a typed constant naming no row at all
# BLOCKS; a note scopes only the paths leading it, for the targets it names; the constants whose small integers
# repeat inside one row are read at POSITIONAL LOCATORS (MIRROR_LOCATORS). A value a closure unit already schedules
# carries "mirror-owed: Un -- why": it WARNS until the row prints it, then BLOCKS as paid. An adversarial review of
# the first draft confirmed 44 defects; each is fixed and is a self-test case. What C did not prove was identity
# outside the locators: 280 of 1,622 one-unit moves passed, each onto a figure its row printed for another
# quantity. THE IDENTITY SITTING (owner, 2026-09-29; DECISIONS#identity-sitting) closed them: a typed list prints as
# ONE consecutive run (the series rule), arithmetic whose result is unprinted is published only by its literals as
# one run in the typed order (the operand run), and keyed values and lone scalars are read beside their labels
# (MIRROR_LOCATORS). check_constant_drift BLOCKS from then: every typed value, moved one unit, fails.
#
# THE HISTORY MOVE (owner, 2026-09-25; done 2026-09-29, DECISIONS#history-move): a row's retired figures live in its
# `history` field, which no figure check reads. A value printed ONLY there -- RECOVERY's $0.053 was A4.08's "it was
# $0.053" -- is listed as a warning: the row states it only in the past tense.
GENERATOR_MODULES = ("group8_dtc", "group9_ledger", "group10_floors", "group11_compliance")
MIRROR_EXEMPT = "mirror-exempt:"
MIRROR_OWED = "mirror-owed:"
CLOSURE_PLAN = "docs/plans/2026-09-24-001-fix-package-contradiction-closure-plan.md"
_MIRROR_SCALES = (1.0, 100.0, 0.01, 1000.0, 0.001, 1e6, 1e-6)


def _span_comments(lines, first, last):
    """(line number, text) of every comment in lines[first-1:last], tokenized as ONE span, so a '#' inside a string
    -- a triple-quoted one crossing lines included -- is never read as a comment."""
    import tokenize
    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO("\n".join(lines[first - 1:last]) + "\n").readline):
            if tok.type == tokenize.COMMENT:
                out.append((first + tok.start[0] - 1, tok.string[1:]))
    except (tokenize.TokenError, IndentationError):
        pass
    return out


_COMPUTED = ("Name", "Call", "Attribute", "Subscript", "comprehension", "Lambda", "IfExp", "Starred", "NamedExpr",
             "Await", "JoinedStr")
_NOTE = re.compile(r"(%s|%s)" % (MIRROR_EXEMPT, MIRROR_OWED))
# one subscript of a written path: a quoted key (which may hold a "]"), or an index
_SEG = re.compile(r"\[(?:'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|[^\]'\"]*)\]")


def _dict_call(node):
    """`dict(rr=4.0, cr=3.5)`: a dict of literals written as a call, read as the dict it is (option C, 2026-09-28).
    As a Call it was taken for computed, so A512_Y3 and A511_WELL_RUN were listed and never compared."""
    import ast
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict"
            and not node.args and bool(node.keywords) and all(k.arg for k in node.keywords))


def _literal_key(node):
    """(ok, key) for a dict key or set element written as a literal -- -1 included, which is not an ast.Constant."""
    import ast
    try:
        return True, ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False, None


def _sequence(node):
    """(element nodes, [(count, its node)], "list"/"tuple") of a list or tuple literal built from literals, `+` and
    `* n` -- `["in"] * 8 + ["co"] * 3` -- or None. Each repeat count is TYPED (option C review, 2026-09-28): it was
    read nowhere, so CLUB_DESIGN_MODE's eight in-house club designs could move with the check silent."""
    import ast
    if isinstance(node, (ast.List, ast.Tuple)):
        if any(isinstance(e, ast.Starred) for e in node.elts):
            return None
        return list(node.elts), [], "list" if isinstance(node, ast.List) else "tuple"
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a, b = _sequence(node.left), _sequence(node.right)
        return (a[0] + b[0], a[1] + b[1], a[2]) if a and b and a[2] == b[2] else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        for seq, cnt in ((node.left, node.right), (node.right, node.left)):
            s = _sequence(seq)
            if s and isinstance(cnt, ast.Constant) and type(cnt.value) is int:
                return s[0] * cnt.value, s[1] * cnt.value + [(cnt.value, cnt)], s[2]
    return None


def _operands(node, src):
    """(value, as typed) of each number typed into an arithmetic element, a unary minus kept with its literal."""
    import ast
    if isinstance(node, ast.Constant):
        ok = isinstance(node.value, (int, float)) and not isinstance(node.value, bool)
        return [(node.value, ast.get_source_segment(src, node) or repr(node.value))] if ok else []
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant):
        return [(-v, "-" + t) for v, t in _operands(node.operand, src)]
    return [x for c in ast.iter_child_nodes(node) for x in _operands(c, src)]


def _element_kinds(node, src, path="", group="", origin=None):
    """One entry per element of an assignment's value, read from its SYNTAX, never its runtime value:
    (path, sibling group, typed, typed value, operands, node, as typed, origin).

    THE CHECK COVERS TRANSCRIPTIONS -- numbers typed into code -- not values computed from other values (owner,
    2026-09-25): a computed value is compared with its row by the figure checks, and a date-derived count (TARGETS'
    months, NATIONAL's live shares) has no printed figure to be compared with. An element is TYPED when its syntax
    holds nothing but literals and arithmetic; a name, a call or a subscript anywhere in it makes it computed --
    except `dict(...)` of keywords, which is a dict. The typed value is evaluated from the syntax, so a later rebind
    or mutation of the module global cannot stand in for what was typed.

    SIBLINGS SHARE ONE UNIT SCALE (option C). A list's elements, a {...} dict's values and a set's members are one
    quantity across years, accounts or members: they share a group, and y1 at x100 beside y2 at x1 is two
    coincidences, not a series. A TUPLE is a record -- OCCSP's share, $ cap and count -- and so is `dict(...)`,
    whose keywords are field names (A11.20's TARGET: survival 0.71, months 24): each position or field is its own
    group. `operands` is None for a bare literal; for typed ARITHMETIC it lists the literals typed into it, which
    publish it when its result is not printed. A repeat count is an element of its own, path "<xN>"."""
    import ast
    base = path if origin is None else origin
    seq = _sequence(node)
    if seq is not None:
        elts, counts, kind = seq
        out, first = [], {}
        for i, e in enumerate(elts):
            first.setdefault(id(e), i)
            sub = "%s[%d]" % (path, i)
            out.extend(_element_kinds(e, src, sub, group + ("[*]" if kind == "list" else "[%d]" % i),
                                      "%s[%d]" % (base, first[id(e)]) if counts or origin is not None else None))
        for j, (n, cnode) in enumerate(counts):
            out.append(("%s<x%d>" % (path, j), "%s<x%d>" % (path, j), True, float(n), None, cnode,
                        ast.get_source_segment(src, cnode) or str(n), None))
        return out
    if isinstance(node, ast.Dict) and None not in node.keys:
        keys = [_literal_key(k) for k in node.keys]
        if all(ok for ok, _ in keys):
            return [k for (_, key), v in zip(keys, node.values)
                    for k in _element_kinds(v, src, "%s[%r]" % (path, key), group + "[:]",
                                            None if origin is None else "%s[%r]" % (origin, key))]
    if _dict_call(node):
        return [k for kw in node.keywords
                for k in _element_kinds(kw.value, src, "%s[%r]" % (path, kw.arg), group + "[%r]" % kw.arg,
                                        None if origin is None else "%s[%r]" % (origin, kw.arg))]
    if isinstance(node, ast.Set):
        keys = [_literal_key(e) for e in node.elts]
        if all(ok for ok, _ in keys):
            return [k for (_, key), e in zip(keys, node.elts)
                    for k in _element_kinds(e, src, "%s{%r}" % (path, key), group + "{*}",
                                            None if origin is None else "%s{%r}" % (origin, key))]
    typed = not any(type(n).__name__ in _COMPUTED for n in ast.walk(node))
    try:
        value = eval(compile(ast.Expression(body=node), "<typed>", "eval"), {"__builtins__": {}}) if typed else None
    except Exception:                                  # arithmetic that does not evaluate is not a transcription
        typed = False
    if not typed:
        return [(path, group, False, None, None, node, None, origin)]
    literal = isinstance(node, ast.Constant) or (isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub)
                                                 and isinstance(node.operand, ast.Constant))
    return [(path, group, True, value, None if literal else _operands(node, src), node,
             ast.get_source_segment(src, node), origin)]


def _typed(path, kinds):
    """Is the runtime leaf at `path` inside a typed element? Paths are whole subscripts, so a prefix is an
    ancestor."""
    return any(k[2] and (path == k[0] or path.startswith(k[0] + "[") or path.startswith(k[0] + "{"))
               for k in kinds)


def typed_items(kinds):
    """The typed values C compares, one per number: (path, value, group, operands, node, as typed, origin). A typed
    element whose value is not a number -- a string label, None -- publishes nothing; one whose value is a
    container (arithmetic on tuples) contributes each number in it."""
    out = []
    for path, group, typed, value, ops, node, text, origin in kinds:
        if not typed or isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            out.append((path, float(value), group, ops, node, text, origin or path))
        elif value is not None and not isinstance(value, str):
            out.extend((p, v, group + g, None, None, None, origin or path) for p, v, g in _leaves(value, path))
    return out


def _canon(path):
    """A written path ("['a'][0]", '["a"][0]') in the one form the check writes: each key as its repr."""
    import ast
    out = ""
    for seg in _SEG.findall(path):
        try:
            key = ast.literal_eval(seg[1:-1])
        except (ValueError, SyntaxError):
            return None
        out += "[%r]" % (key,)
    return out


def _under(path, scope):
    """Is `path` at or below the written path `scope`? Canonical paths end each segment with a bracket or a brace,
    so a string prefix is an ancestor exactly."""
    return path == scope or path.startswith(scope + "[") or path.startswith(scope + "{") or \
        path.startswith(scope + "<") or scope == ""


_DIVIDER = re.compile(r"#\s*-{4,}")


def _comment_lines(src):
    """{line: text} of every line that is a comment and nothing else, by the tokenizer: a line of a string that
    begins with '#' is not one."""
    import tokenize
    out = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT and not tok.line[:tok.start[1]].strip():
                out[tok.start[0]] = tok.string
    except (tokenize.TokenError, IndentationError):
        pass
    return out


def _targets(t, value):
    """(name, value node, computed?) for each name an assignment target binds; nested tuples are unpacked."""
    import ast
    if isinstance(t, ast.Name):
        return [(t.id, value, False)]
    if isinstance(t, ast.Starred):
        return [(n, v, True) for n, v, _ in _targets(t.value, value)]
    if isinstance(t, (ast.Tuple, ast.List)):
        same = isinstance(value, (ast.Tuple, ast.List)) and len(value.elts) == len(t.elts) and \
            not any(isinstance(e, ast.Starred) for e in t.elts)
        return [x for i, e in enumerate(t.elts) for x in _targets(e, value.elts[i] if same else value)] if same \
            else [(n, v, True) for e in t.elts for n, v, _ in _targets(e, value)]
    return []


def _notes_for(name, notes):
    """(applies, scoped paths, text) of each note that concerns `name`. A note whose leading list names only other
    targets -- "A, B = ...  # mirror-exempt: A[0], a pad" -- is not B's."""
    out = []
    for text in notes:
        lead = re.match(r"(?:\s*[A-Za-z_]\w*(?:%s)+\s*,?)+" % _SEG.pattern, text)
        if not lead:
            out.append(([], text))
            continue
        mine = [m.group(2) for m in re.finditer(r"([A-Za-z_]\w*)((?:%s)+)" % _SEG.pattern, lead.group(0))
                if m.group(1) == name]
        if mine:
            out.append((mine, text[lead.end():]))
    return out


def generator_constants(modname, src=None):
    """(name, line, [anchor ids], how, exempt notes, owed notes, element kinds) for EVERY module-level binding.

    The row is named on the assignment's own line; else on its other lines' comments or the comment lines straight
    after it; else by the SUBJECT line of the comment block directly above -- the first line of the block that names
    a row, because the rest of such a block cites rows as context ("A3.01 ... not here"), and pooling them let
    ROSTER pass on another row's figures; else, the fallback (option C, 2026-09-28), by the "# ----" divider that
    titles the section the assignment sits in -- the nearest one above it. A constant that names no row at all is
    returned with no ids: the check requires a typed figure to name one or carry an exemption.

    NOTES. "mirror-exempt:" and "mirror-owed:" are read across the assignment's own comment and its continuation as
    ONE stream: a note runs to the next note or the end, wherever the line breaks. The rows NAMED are those before
    the first note -- a note's reason may cite rows ("U4 names A7.10") and they are prose. Each note is returned as
    (scoped paths, text) for the targets its leading list names, or for every target when it leads with none.
    """
    import ast
    src = rd("scripts/%s.py" % modname) if src is None else src
    lines = src.split("\n")          # the AST counts "\n" alone; splitlines() also breaks on a form feed
    cmt = _comment_lines(src)
    out = []
    for node in ast.parse(src).body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        named = [x for t in (node.targets if isinstance(node, ast.Assign) else [node.target])
                 for x in _targets(t, node.value)]
        if not named:
            continue
        comments = _span_comments(lines, node.lineno, node.end_lineno)
        own = " ".join(c for n, c in comments if n == node.lineno)
        span = [c for n, c in comments if n != node.lineno]
        j = node.end_lineno
        while j + 1 in cmt and lines[j].startswith((" ", "\t")):
            span.append(cmt[j + 1][1:])
            j += 1
        parts = _NOTE.split(" ".join([own] + span))
        notes = dict((m, [" ".join(t.split()) for mm, t in zip(parts[1::2], parts[2::2]) if mm == m])
                     for m in (MIRROR_EXEMPT, MIRROR_OWED))
        ids, how = _unique(ANCHOR_ID.findall(_NOTE.split(own)[0])), "own line"
        if not ids and not _NOTE.search(own):
            ids, how = _unique(ANCHOR_ID.findall(_NOTE.split(" ".join(span))[0])), "continuation"
        if not ids:
            # a "# ---- ..." divider titles a whole section, not the constant under it, so the block stops there
            k, above = node.lineno - 1, []
            while k in cmt and lines[k - 1].startswith("#") and not _DIVIDER.match(lines[k - 1]):
                above.insert(0, cmt[k][1:])
                k -= 1
            subject = next((l for l in above if ANCHOR_ID.search(l)), "")
            ids, how = _unique(ANCHOR_ID.findall(subject)), "block above"
        if not ids:
            k = node.lineno - 1
            while k >= 1 and not (k in cmt and lines[k - 1].startswith("#") and _DIVIDER.match(lines[k - 1])):
                k -= 1
            if k >= 1:
                ids, how = _unique(ANCHOR_ID.findall(lines[k - 1])), "divider, line %d" % k
        for nm, value, computed in named:
            kinds = [("", "", False, None, None, value, None, None)] if computed else _element_kinds(value, src)
            out.append((nm, node.lineno, ids, how if ids else "no row", _notes_for(nm, notes[MIRROR_EXEMPT]),
                        _notes_for(nm, notes[MIRROR_OWED]), kinds))
    return out


def _unique(seq):
    seen = []
    for x in seq:
        if x not in seen:
            seen.append(x)
    return seen


def _leaves(v, path="", group=""):
    """(path, value, group) for every number in a runtime value; the path is written as its subscript, "[0]",
    "['in']" or, for a set member, "{3}". Used for what the syntax cannot type: the computed elements the check
    lists, and a typed element whose value is a container."""
    if isinstance(v, bool):
        return []
    if isinstance(v, (int, float)):
        return [(path, float(v), group)]
    if isinstance(v, dict):
        return [x for k, e in v.items() for x in _leaves(e, "%s[%r]" % (path, k), group + "[:]")]
    if isinstance(v, list):
        return [x for i, e in enumerate(v) for x in _leaves(e, "%s[%d]" % (path, i), group + "[*]")]
    if isinstance(v, tuple):
        return [x for i, e in enumerate(v) for x in _leaves(e, "%s[%d]" % (path, i), group + "[%d]" % i)]
    if isinstance(v, (set, frozenset)):
        return [x for e in sorted(v, key=repr) for x in _leaves(e, "%s{%r}" % (path, e), group + "{*}")]
    return []


def _figures_as_numbers(text):
    """(value, decimal places) for every figure fingerprint_figures reads in `text`."""
    out = []
    for tok in fingerprint_figures(text):
        t = tok.replace(",", "")
        try:
            out.append((float(t), len(t.split(".")[1]) if "." in t else 0))
        except ValueError:
            pass
    return out


def _printed_figures(row):
    """(all, present): the figures of the row's publishing fields and its history, and those of the publishing
    fields alone."""
    present = [x for f in FINGERPRINTED_FIELDS for x in _figures_as_numbers(row.get(f))]
    return present + _figures_as_numbers(row.get("history")), present


def _row_sentences(row):
    """(present, past): the sentences of the row's figure-publishing fields, and of its `history` field. STRUCTURAL
    from the history move (2026-09-29): which sentences are past is where they sit, not a word they carry."""
    present = [s for f in FINGERPRINTED_FIELDS for s in sentences(_unwrap(str(row.get(f) or "")))]
    past = sentences(_unwrap(str(row.get("history") or ""))) if row.get("history") else []
    return present, past


def _run_in(match, n, sents):
    """Is there, in one of `sents`, a run of n CONSECUTIVE figures with match(j, figure) true at each place j?"""
    for s in sents:
        figs = [x for x, _ in _figures_as_numbers(s)]
        for i in range(len(figs) - n + 1):
            if all(match(j, figs[i + j]) for j in range(n)):
                return True
    return False


def _series_of(members):
    """{parent path: [members in index order]} for each typed LIST of two or more numbers among `members` -- a
    year-list, a band. A list of records (GA_SPLIT's tuples) is not a series: its numbers are fields, not places; nor
    is a dict, whose values share a scale under the group mark "[:]" -- PACK_MIX's keys 1, 2, 3 write paths a list
    would. An exempt element is out of the series and the rest keep their order."""
    lists = {}
    for it in members:
        m = re.match(r"(.*)\[(\d+)\]$", it[0])
        if m and it[2].endswith("[*]"):
            lists.setdefault(m.group(1), []).append((int(m.group(2)), it))
    return dict((p, [it for _, it in sorted(els, key=lambda e: e[0])]) for p, els in lists.items() if len(els) >= 2)


def _same(x, v):
    """x equals the printed v: exactly, or to a relative 1e-9, which absorbs 0.0525 x 100 = 5.2499... and nothing
    a print could state. A printed 0 publishes only a 0."""
    return x == v or (v != 0 and abs(x - v) <= 1e-9 * abs(v))


def _exact_scales(value, figs):
    """The unit scales at which `value` IS one of `figs`. NO ROUNDING PATH (option C, owner 2026-09-28): the half-up
    path let GROSS[2]'s 46.719 pass on A1.01's 46.7. The scaled value is compared unrounded -- settling it at nine
    places first let a printed 0 publish anything under 0.0005 at x1e-6 (review, 2026-09-28)."""
    return [s for s in _MIRROR_SCALES if any(_same(value * s, v) for v, _ in figs)]


def _fmt(v):
    """A value as typed-looking text: 2, 46.719, 46.70001 -- never %g's six digits, which printed 46.70001 as 46.7."""
    return str(int(v)) if float(v).is_integer() and abs(v) < 1e15 else repr(float(v))


# POSITIONAL LOCATORS (option C, owner 2026-09-28). Where one row prints the same small integers for several
# quantities, "the value is printed somewhere in the row" proves nothing: REVIEWS_PER_YEAR['Kroger'] passed at 1, 2
# or 3, and AUTH's Kroger 10 could move onto 11 with the row printing both. A located constant is read AT ITS PLACE:
# each leaf names a phrase that must occur in exactly one present sentence of the first named row (from a word
# boundary), the ordinals of the figures after it that must ALL equal the leaf -- ROSTER's y1-y2 warehouse count is
# printed twice, "5 / 5 / 6" -- and, where the clause is a chain ("6 -> 7 -> 8", "5 / 5 / 6"), how many figures the
# chain holds, so a flat count restated as a chain fails instead of reading its y1. `labels` pins the text beside a
# located number (ROSTER's role names), so swapping two roles' counts cannot pass. A leaf of a located constant with
# no locator FAILS. Phrases follow RULE 1 (check_locator_hygiene): content only, no ids, dates or magnitudes.
_ROSTER_AT = (("warehouse", "warehouse & shipping", (0, 1), (2,), 3),
              ("sales_mgr", "sales manager", (0,), (1,), 2), ("acct_mgr", "account managers", (0,), (1,), 2),
              ("ops_planner", "operations planners", (0,), (1,), 2), ("controller", "controller", (0,), (1,), 2),
              ("bookkeeper", "bookkeeper", (0,), (1,), 2), ("clerk", "clerks", (0,), (1,), 2),
              ("mktg_mgr", "marketing manager", (0,), (1,), 2), ("dtc_coord", "DTC coordinators", (0,), (1,), 2),
              ("ceo", "CEO", (0,), (1,), 2), ("coo", "COO", (0,), (1,), 2))
# ROSTER's roles in its order: label, phrase in A9.04, the y1-y2 ordinals, the y3 ordinal, the chain's length
_AUTH_AT = (("Walmart", "Walmart", 3), ("Kroger", "Kroger", 3), ("WF", "Whole Foods", 3),
            ("Regional", "Regional", 3), ("Sprouts", "Sprouts", 1), ("Costco", "Costco", 1))
# A7.26 prints each banner's per-door authorization as one "y1 -> y2 -> y3" chain; a flat count is printed once
MIRROR_LOCATORS = {
    ("group9_ledger", "ROSTER"): (1.0, dict(
        [("['y12'][%d][1]" % i, (r"%s(?= \d)" % p, a, n)) for i, (_, p, a, b, n) in enumerate(_ROSTER_AT)]
        + [("['y3'][%d][1]" % i, (r"%s(?= \d)" % p, b, n)) for i, (_, p, a, b, n) in enumerate(_ROSTER_AT)]),
        dict([("['%s'][%d][0]" % (k, i), lab) for k in ("y12", "y3") for i, (lab, _, _, _, _) in
              enumerate(_ROSTER_AT)])),
    ("group10_floors", "AUTH"): (1.0, dict(
        ("[%r][%d]" % (k, y), (r"%s(?= \d+ ->)" % p if n == 3 else r"%s(?= \d)" % p, (y if n == 3 else 0,), n))
        for k, p, n in _AUTH_AT
        for y in range(3)), {}),
    # UNFI's 2% is A5.15's "short-ship chargeback 2% of shorted value" -- and, unlocated, it passed on "after 2
    # weeks" in the clause before it.
    ("group10_floors", "FINE_SHORT"): (100.0, {"['UNFI']": (r"short-ship chargeback", (0,), None),
                                               "['KeHE']": (r"KeHE: fill", (1,), None),
                                               "['Costco']": (r"Costco: case-by-case[^;]*?short-ship", (0,), None)},
                                       {}),
    # REVIEWS_PER_YEAR's entry is gone with the constant (U4, owner 2026-10-01): nothing read it, and only the annual
    # category review runs A7.12's floor.
}
# LABELLED LOCATORS (identity sitting, owner 2026-09-29). The series rule closes a year-list; what it cannot close is
# a KEYED value -- a share by deduction type, days by account, a G&A line by name -- and a lone scalar, each of which
# passed on any equal figure its row printed for another quantity (GA_SPLIT's insurance, software/IT and other are
# all 0.4, so a permutation passed). Each is read beside its label. A phrase is content only (RULE 1); where a row
# prints a label in two sentences, the phrase carries the lead that tells them apart, never a figure.
def _at(phrase, *ordinals, **kw):
    """One locator: the phrase, the ordinals read after it (default the first), and optionally the chain's length
    (`width`) and a scale of the leaf's own (`scale`)."""
    loc = (phrase, ordinals or (0,), kw.get("width"))
    return loc + (kw["scale"],) if "scale" in kw else loc


def _keyed(paths_phrases, **kw):
    """{"[key]": _at(phrase)} for a dict of scalars, each key read at its label."""
    return dict(("[%r]" % k, _at(p, **kw)) for k, p in paths_phrases)


def _keyed_series(paths_phrases, n=3, flat=(), chain=True):
    """{"[key][y]": ...} for a dict of year-lists read at their label as one chain of n (or, with `chain` off, as n
    figures whose separators are words: "416 y1 -> 572 y2"); a key in `flat` prints its one count once, and a chain
    there fails (AUTH's rule)."""
    out = {}
    for k, p in paths_phrases:
        for y in range(n):
            out["[%r][%d]" % (k, y)] = _at(p, 0, width=1) if k in flat else _at(p, y, width=n if chain else None)
    return out


_GA_AT = (("rent", r"rent(?= \d)"), ("insurance", r"insurance(?= \d)"), ("software_it", r"software/IT(?= \d)"),
          ("professional", r"professional fees(?= \d)"), ("travel", r"travel(?= \d)"),
          ("bad_debt", r"bad debt(?= \d)"), ("other", r"other(?= \d)"))
_A405_LABEL = (("short_ship", r"short_ship(?= \d)"), ("late_otif", r"late/OTIF fines(?= \d)"),
               ("damaged_unsaleables", r"damaged/unsaleables(?= \d)"),
               ("spoilage_shortdated", r"spoilage/short-dated(?= \d)"),
               ("receiving_miscount", r"receiving_miscount(?= \d)"), ("label_pallet_asn", r"label/pallet/ASN(?= \d)"),
               ("pricing_error", r"pricing_error(?= \d)"), ("post_audit", r"post-audit(?= \d)"),
               ("overage", r"OVERAGE(?= \d)"), ("other", r"other(?= \d)"))
_A432_LABEL = (("short_ship", "short_ship"), ("late_otif", "late/OTIF"), ("damaged_unsaleables", "damaged"),
               ("spoilage_shortdated", "spoilage"), ("receiving_miscount", "receiving_miscount"),
               ("label_pallet_asn", "label/pallet/ASN"), ("pricing_error", "pricing_error"),
               ("post_audit", "post-audit"), ("overage", "overage"), ("other", "other"))
# A6.26 prints each deduction type's clause as "<type> <control> n / <control> n"; a control is read inside its
# type's clause, so pricing's three_way and post-audit's cannot stand in for each other
_A626_TYPE = {"short_ship": "short_ship", "late_otif": "late/OTIF", "label_pallet_asn": "label/ASN",
              "damaged_unsaleables": "damaged", "spoilage_shortdated": "spoilage", "pricing_error": "pricing",
              "receiving_miscount": "receiving_miscount", "post_audit": "post_audit", "overage": "overage",
              "other": "other"}
_A626_CONTROL = {"po_acknowledgment": "po_ack", "edi_reconciliation": "edi", "item_setup_preflight": "item_setup",
                 "receiving_audit": "receiving_audit", "price_book_governance": "price_book",
                 "three_way_match": "three_way", "none": "none"}
_A626_MAP_AT = {
    "short_ship": ("po_acknowledgment", "none"), "late_otif": ("po_acknowledgment", "edi_reconciliation", "none"),
    "label_pallet_asn": ("edi_reconciliation", "item_setup_preflight"),
    "damaged_unsaleables": ("receiving_audit", "none"),
    "spoilage_shortdated": ("item_setup_preflight", "receiving_audit", "none"),
    "pricing_error": ("price_book_governance", "three_way_match"), "receiving_miscount": ("receiving_audit",),
    "post_audit": ("three_way_match", "price_book_governance"), "overage": ("po_acknowledgment", "receiving_audit"),
    "other": ("none",)}
_A308_AT = (("WF", "WF", 1), ("Sprouts", "Sprouts", 2), ("Kroger", "Kroger", 2), ("Regional", "Regional", 2),
            ("Walmart", "Walmart", 3), ("Costco", "Costco", 1))
_CYCLE = r"ONE ORDER CYCLE, IN DAYS:[^;]*?"
_RECIPE_KIND = (("sauce", r"sauce recipes(?= \d)"), ("condiment jar", r"condiment jar recipes(?= \d)"),
                ("condiment tub", r"condiment tub recipes(?= \d)"), ("dried", r"dried recipes(?= \d)"),
                ("snack", r"snack recipes(?= \d)"))
MIRROR_LOCATORS.update({
    # ---- group 9
    ("group9_ledger", "TRADE"): (100.0, {"": _at("rate-card trade")}, {}),
    ("group9_ledger", "ASK"): (100.0, {"[1]": _at(r"the ask is \+"), "[2]": _at(r"\) and \+")}, {}),
    # "stated terms / actual days to pay": the actual days are the second figure after the account
    ("group9_ledger", "DAYS_TO_PAY"): (1.0, dict(
        [("[%r]" % k, _at(p, 1)) for k, p in (
            ("Walmart", "Walmart net"), ("Kroger", "Kroger net"), ("WF", "Whole Foods net"),
            ("Regional", "Regional net"), ("KeHE", "KeHE net"), ("DPI", "DPI net"), ("small", "small accounts net"),
            ("Sprouts", "Sprouts net"), ("Costco", "Costco net"))]
        + [("['UNFI']", _at("UNFI net", 4))]), {}),
    ("group9_ledger", "DAYS_DTC"): (1.0, {"": _at("DTC card settlement")}, {}),
    # A8.11's construction since U4 (owner, 2026-10-01): payment, and A8.12's and A8.13's achievables
    ("group9_ledger", "PAYMENT"): (100.0, {"": _at("and payment")}, {}),
    ("group9_ledger", "SHIPPING_ACHIEVABLE"): (100.0, {"": _at("zone skipping ->")}, {}),
    ("group9_ledger", "THREEPL_ACHIEVABLE"): (100.0, {"": _at("Achievable:")}, {}),
    # U4's restatements printed figures these constants' one-unit drifts land on: A11.25's "28 times" and A9.14's
    # November peak inventory (owner, 2026-10-01); each is read at its place
    ("group9_ledger", "WALMART_OREGON"): (1.0, {"[0]": _at("Supercenters,"), "[1]": _at("Supercenters,", 1)}, {}),
    ("group9_ledger", "SPREAD"): (100.0, {"": _at("Rate: prime +")}, {}),
    ("group9_ledger", "INV_SUBLIMIT"): (1.0, {"": _at("at the November peak", 3)}, {}),
    ("group9_ledger", "DPO"): (1.0, {"": _at(r"DPO(?= \d)")}, {}),
    ("group10_floors", "DPO"): (1.0, {"": _at(r"DPO(?= \d)")}, {}),
    ("group9_ledger", "BROKER_RATE"): (100.0, {"": _at("Commission")}, {}),
    # a lone arithmetic result may take any scale, and 2 x 2,500 x 11 = 55,000 read x0.001 as the broker share's 55
    ("group9_ledger", "BROKER_RETAINER"): (1.0, {"": _at(r"retainer \$[\d,]+/month each,")}, {}),
    ("group9_ledger", "SUPPLIES_PCT"): (100.0, {"": _at("outside storage only,")}, {}),
    ("group9_ledger", "GA_PCT"): (100.0, {"": _at(r"G&A(?= \d)")}, {}),
    ("group9_ledger", "GA_SPLIT"): (100.0, dict(("[%d][1]" % i, _at(p)) for i, (_, p) in enumerate(_GA_AT)),
                                    dict(("[%d][0]" % i, lab) for i, (lab, _) in enumerate(_GA_AT))),
    ("group9_ledger", "BRAND_MARKETING_PCT"): (100.0, {"": _at(r"paid \+")}, {}),
    ("group11_compliance", "BAD_DEBT"): (100.0, {"": _at(r"bad debt(?= \d)")}, {}),
    ("group9_ledger", "FBA_STORAGE_UNIT"): (1.0, {"": _at("monthly storage about")}, {}),
    ("group9_ledger", "FBA_INBOUND_UNIT"): (1.0, {"": _at("inbound placement about")}, {}),
    ("group9_ledger", "RETURNLESS_SHARE"): (100.0, {"": _at("returnless refunds about")}, {}),
    ("group9_ledger", "INSPECTION"): (1.0, {"[0]": _at(r"and(?= \d+ BILLABLE INSPECTION HOURS)"),
                                            "[1]": _at(r"Inspection(?= \$)")}, {}),
    ("group9_ledger", "GLASS_RATE"): (1.0, {"": _at("glass at")}, {}),
    ("group9_ledger", "GLASS_RATE_2026"): (1.0, {"": _at("prints glass bottles and jars at")}, {}),
    ("group9_ledger", "INELIGIBLE_90D"): (100.0, {"": _at(r"invoices > \d+ days \(")}, {}),
    ("group9_ledger", "SPRING_PCT"): (100.0, {"": _at("falls below the greater of")}, {}),
    ("group9_ledger", "DEFAULT_BUMP"): (100.0, {"": _at(r"default rate \+\d+bp \(")}, {}),
    ("group9_ledger", "DISTRIB"): (100.0, {"": _at("owner tax distributions at")}, {}),
    ("group9_ledger", "ORGANIC_SHARE"): (100.0, {"": _at("organic ~")}, {}),
    # A8.15's formula, read in its order: the unfiled share, the eligible rate, the recovery (the rate's 2.6 at
    # x100 had passed at 2.5 on the "25%" filed share)
    ("group9_ledger", "CARRIER_CLAIMS"): (1.0, {"[0]": _at("claim dollars ="),
                                                "[1]": _at("claim dollars =", 1, scale=100.0),
                                                "[2]": _at("claim dollars =", 2)}, {}),
    ("group9_ledger", "PACK_MIX"): (100.0, {"[1]": _at("over JARS rather than orders:"), "[2]": _at("singles,"),
                                            "[3]": _at("2-packs,")}, {}),
    ("group9_ledger", "PACK_LB"): (1.0, {"[1]": _at("case over", 1), "[2]": _at("the 2-pack weighs"),
                                         "[3]": _at("and the 3-pack")}, {}),
    # ---- group 8 (U4's slice, 2026-10-02): each input read beside its label, since A8.03 and A8.05 print several
    # small rates and counts and A8.04 prints its CNP band beside its own rate
    ("group8_dtc", "CB_PEAK"): (100.0, {"[0]": _at("ratio that drifts"), "[1]": _at("ratio that drifts", 1),
                                        "[2]": _at("ratio that drifts", 2)}, {}),
    ("group8_dtc", "CB_RATE"): (100.0, {"": _at("Chargeback rate")}, {}),
    ("group8_dtc", "LAG"): (1.0, {"": _at("DISPUTE LAG OF")}, {}),
    ("group8_dtc", "FEB"): (1.0, {"": _at("February")}, {}),
    ("group8_dtc", "MIX_BAND"): (100.0, {"": _at("band ±")}, {}),
    ("group8_dtc", "VDMP"): (100.0, {"['ratio']": _at(r"Visa VDMP \([^)]*\):"),
                                     "['count']": _at(r"Visa VDMP \([^)]*\):", 1, scale=1.0)}, {}),
    # A5.07's probabilistic floor (owner, 2026-10-05): the expected count that earns a per-year floor, read at its label
    ("group10_floors", "A507_PER_YEAR_EXPECTED"): (1.0, {"": _at("expects >=")}, {}),
    # A5.07's order-level rates, its line split and its late-cancel cap, each at its label (2026-10-06: the per-account
    # line rates put neighbours a one-unit move could land on)
    ("group10_floors", "A507_RATE"): (100.0, {"['order_retailer']": _at("Cancellations: order-level", 1),
                                              "['order_cinderhaven']": _at("Cancellations: order-level", 2)}, {}),
    ("group10_floors", "A507_LINE_SPLIT"): (1.0, {"['line_retailer']": _at("split retailer"),
                                                  "['line_cinderhaven']": _at("split retailer", 1)}, {}),
    ("group10_floors", "LATE_CANCEL_DAYS"): (1.0, {"": _at("AT EVERY ACCOUNT: a PO more than")}, {}),
    # ---- group 10
    ("group10_floors", "POS"): (1.0, dict(
        _keyed_series([("Walmart", "Walmart weekly per DC"), ("Sprouts", "Sprouts biweekly")], 3, chain=False),
        **_keyed_series([("Kroger", "Kroger biweekly"), ("WF", "Whole Foods biweekly"),
                         ("Regional", "Regional weekly"), ("UNFI", "UNFI weekly")], 3,
                        flat=("Kroger", "WF", "Regional", "UNFI")),
        # KeHE is a chain since its fifth DC orders from y2 (U4): 208 / 260 / 260, not a flat 208
        **_keyed_series([("KeHE", "KeHE weekly"), ("Costco", "Costco monthly per depot"), ("DPI", "DPI biweekly")],
                        3)), {}),
    # A5.37's lines per PO, a constant since U4 computes A5.02's lines (po_lines). Its 8 and 10 repeat across accounts
    # and the row prints cases per line by account in the next sentence, so Costco's 2 drifted onto 1 unseen: each
    # value is read beside its account, in the clause that ends ";" -- the cases-per-line clause runs on commas
    ("group10_floors", "A537_LINES"): (1.0, dict(
        _keyed([(k, r"%s(?= \d+;)" % p) for k, p in (
            ("Walmart", "Walmart"), ("Kroger", "Kroger"), ("WF", "Whole Foods"), ("Sprouts", "Sprouts"),
            ("Regional", "Regional"), ("Costco", "Costco"), ("UNFI", "UNFI"), ("KeHE", "KeHE"), ("DPI", "DPI"))]),
        **_keyed([("small", r"small accounts(?= \d)")])), {}),
    # A7.04's filed store counts, each beside its banner: a value-only restatement of Costco's 614 passed the whole gate
    # once U4 read it for the %ACV, because 614 also prints in A7.04's `figure` field (U4's verifier)
    ("group10_floors", "A704_UNIVERSE"): (1.0, _keyed([
        ("Walmart", r"\((?=[\d,]+ Supercenters,)"), ("Kroger", r"Kroger(?= [\d,]+ supermarkets)"),
        ("WF", r"Whole Foods ~(?=\d+ U\.S\.)"), ("Sprouts", r"Sprouts(?= \d+ in)"), ("Costco", r"Costco(?= \d+ U\.S\.)")]),
        {}),
    # A6.02's field counts and per-action rates, read beside their labels (DECISIONS#u14): the row's 4 and 2 also
    # print as exponents, and its two desks' rates sit one clause apart
    ("group10_floors", "A602_FIELDS"): (1.0, _keyed([("mechanical", r"keyed order line has ~"),
                                                     ("cognitive", r"date\) and ~")]), {}),
    ("group10_floors", "A602_RATES"): (1.0, dict(
        [("['character'][%d]" % i, _at(r"rushed, untrained:", i, width=2)) for i in range(2)]
        + [("['disciplined'][%d]" % i, _at(r"a disciplined desk \(", i, width=2)) for i in range(2)]), {}),
    # A9.16's weights and its contract's olive share, each beside its input's name (DECISIONS#u14): the row prints
    # 16 twice (fruit and vegetables, spices) and 7 twice (olive oil, freight-in)
    ("group9_ledger", "A916_WEIGHTS"): (1.0, _keyed([
        ("fruitveg", r"tomato and produce(?= \d)"), ("olive", r"\(tomato and produce \d+, olive oil(?=\s+\d)"),
        ("sugar", r"sugar(?= \d+, spices)"), ("glass", r"\(glass(?= \d+, caps)"), ("truck", r"freight-in(?= \d)"),
        ("labor", r"conversion labor(?= \d)")]), {}),
    ("group9_ledger", "A916_CONTRACT"): (1.0, _keyed([
        ("share", r"CONTRACT TERMS:(?= \d)"), ("ingredients", r"ingredients(?= \d+% \(tomato)"),
        ("olive", r"\(tomato and produce \d+, olive oil(?=\s+\d)")]), {}),
    ("group10_floors", "DCS"): (1.0, dict(
        _keyed([("UNFI", r"UNFI(?= \d)"), ("Costco", r"Costco(?= \d)"), ("Kroger", r"Kroger(?= \d)"),
                ("WF", "Whole Foods direct"), ("Sprouts", "Sprouts direct"), ("Regional", r"Regional(?= \d)")],
               width=1),
        **_keyed_series([("KeHE", r"KeHE(?= \d)"), ("DPI", r"DPI(?= \d)")], 3)), {}),
    ("group10_floors", "AUTH_ALL"): (1.0, _keyed_series(
        [(k, r"%s(?= \d+ ->)" % p) for k, p, n in _AUTH_AT if n == 3]
        + [("independents", r"independents(?= \d+ ->)")]
        + [(k, r"%s(?= \d)" % p) for k, p, n in _AUTH_AT if n == 1],
        3, flat=[k for k, _, n in _AUTH_AT if n == 1]), {}),
    # Costco's per-door authorization IS the two club designs it accepts: the same quantity, read at one place
    ("group10_floors", "CLUB_ACCEPTED"): (1.0, {"": _at(r"Costco(?= \d)", width=1)}, {}),
    ("group10_floors", "A405_SHARE"): (1.0, _keyed(_A405_LABEL), {}),
    ("group10_floors", "A405_OTIF_SHARE"): (100.0, {"": _at(r"late/OTIF fines(?= \d)")}, {}),
    ("group10_floors", "A432_WEIGHTS"): (1.0, _keyed_series([(k, r"%s(?= \d)" % p) for k, p in _A432_LABEL], 3),
                                         {}),
    ("group10_floors", "SIGMA_DOOR"): (1.0, {"": _at("THE VALUE IS OWNER-SIGNED:")}, {}),
    ("group10_floors", "SIGMA_DOOR_BAND"): (1.0, {"[0]": _at("inside the band of"),
                                                  "[1]": _at("inside the band of", 1)}, {}),
    ("group10_floors", "LAUNCHES_PER_YEAR"): (1.0, {"": _at(r"launches,(?= \d+ per year)")}, {}),
    ("group11_compliance", "LAUNCHES_A_YEAR"): (1.0, {"": _at(r"launches,(?= \d+ per year)")}, {}),
    ("group10_floors", "RETAILERS_BAND"): (1.0, {"[0]": _at("each authorized at"),
                                                 "[1]": _at("each authorized at", 1)}, {}),
    ("group11_compliance", "PRE_QUARTERS"): (1.0, {"": _at("three in each year's")}, {}),
    ("group10_floors", "PROD_LEAD_WEEKS"): (1.0, {"[0]": _at(r"co-pack(?= \d+-\d+ weeks)"),
                                                  "[1]": _at(r"co-pack(?= \d+-\d+ weeks)", 1)}, {}),
    ("group10_floors", "RUN_FLOOR"): (1.0, {"['in']": _at("a recipe's live sizes together,"),
                                            "['co']": _at("a recipe's live sizes together,", 1)}, {}),
    ("group10_floors", "SUPPLIER_TERMS"): (1.0, _keyed([("ingredients", "ingredients net"), ("glass", "glass net"),
                                                        ("co-packers", "co-packers net")]), {}),
    # U16 (2026-10-21): the daily ledger's AP cadence and late fee, each at the clause of the row it names
    ("group9_ledger", "AP_RUN_DAYS"): (1.0, {"[0]": _at(r"twice monthly \(the"),
                                             "[1]": _at(r"twice monthly \(the", 1)}, {}),
    ("group9_ledger", "LATE_FEE_MONTH"): (100.0, {"": _at("owner-signed practitioner: a")}, {}),
    ("group9_ledger", "HOLD_MISSES"): (1.0, {"": _at("past due or")}, {}),
    # A9.13's "Dec 31" (U16) reads as 0.31 at the 0.01 scale: capex is read at its own label
    ("group9_ledger", "CAPEX"): (1.0, {"": _at(r"maintenance capex \$")}, {}),
    ("group10_floors", "INHOUSE_LEAD_WEEKS"): (1.0, {"[0]": _at("available inventory: in-house"),
                                                     "[1]": _at("available inventory: in-house", 1)}, {}),
    ("group10_floors", "ALLOCATION_SHARE"): (100.0, {"": _at("Cinderhaven-initiated: allocation_shortage")}, {}),
    # U18 Q6 (2026-10-19): A4.31's operands, each at the clause of the row it names
    ("group10_floors", "A418_PHANTOM"): (100.0, {"[0]": _at("phantom promotions"), "[1]": _at("phantom promotions", 1)},
                                         {}),
    ("group10_floors", "A418_DOUBLE"): (100.0, {"[0]": _at("double-funding"), "[1]": _at("double-funding", 1)}, {}),
    ("group10_floors", "WRONG_RATE"): (100.0, {"": _at(r"(?=\d+% of billback and MCB claims, band)")}, {}),
    # 2026-10-20: D0's signed band, at A9.13's clause for D0 -- unlocated, a 1.4 anywhere in the row stood in for it
    ("group10_floors", "D0_BAND"): (1.0, {"[0]": _at("net standing draw at window start", 1),
                                          "[1]": _at("net standing draw at window start", 2)}, {}),
    # U18 Q5 (2026-10-15): slotting's typed counts, each at the one clause that prints it
    ("group9_ledger", "FREE_FILL_CASES"): (1.0, {"": _at(r"(?=\d+ case per store per new SKU)")}, {}),
    ("group9_ledger", "KROGER_DIVISIONS"): (1.0, {"": _at(r"Kroger(?= \d+ authorized divisions)")}, {}),
    ("group10_floors", "CALL_PIK"): (1.0, {"": _at(r"coupon(?= \d+% a year PIK)")}, {}),
    ("group10_floors", "SUPPLIER_DAYS"): (1.0, {"[0]": _at("late fee from"), "[1]": _at("^PRIORITY LOSS at"),
                                                "[2]": _at("CREDIT HOLD at")}, {}),
    ("group10_floors", "VIABILITY_CASES"): (1.0, {"": _at(r"^(?=\d+ case/DC/week)")}, {}),
    ("group10_floors", "A703_BAND"): (1.0, {"[0]": _at("against the registered"),
                                            "[1]": _at("against the registered", 1)}, {}),
    ("group10_floors", "A714_EPISODE_DAYS"): (1.0, {"[0]": _at("episode duration log-normal, median"),
                                                    "[1]": _at("episode duration log-normal, median", 3),
                                                    "[2]": _at("episode duration log-normal, median", 1,
                                                               scale=100.0)}, {}),
    # A7.14's supplier-caused share reads the U.S. rate and GMA's upstream share (owner, 2026-11-03, DECISIONS#u14)
    ("group10_floors", "A714_US"): (1.0, {"[0]": _at(r"average's", scale=100.0),
                                          "[1]": _at(r"at GMA's", scale=100.0)}, {}),
    ("group10_floors", "A626_MAP"): (1.0, dict(
        ("[%r][%r]" % (t, c), _at(r"%s (?:\w+ \d+ / )*%s(?= \d)" % (_A626_TYPE[t], _A626_CONTROL[c])))
        for t, cs in _A626_MAP_AT.items() for c in cs), {}),
    ("group10_floors", "A308_ENDINGS"): (1.0, dict(
        ("[%r][%d]" % (k, i), _at(r"%s [^(;]*-> [^(;]*\(" % p, i)) for k, p, n in _A308_AT for i in range(n)), {}),
    ("group10_floors", "A502_CYCLE_DAYS"): (1.0, dict(
        [("['%s']" % k, _at(_CYCLE + "KeHE(?= \\d)")) for k in ("Walmart", "UNFI", "KeHE")]
        + [("['Kroger']", _at(_CYCLE + "Kroger(?= \\d)")), ("['Costco']", _at(_CYCLE + "Costco(?= \\d)"))]), {}),
    ("group10_floors", "LAUNCH_K"): (1.0, {"": _at("k =")}, {}),
    ("group10_floors", "A1018_TOPK"): (1.0, {"": _at("k =")}, {}),
    # RECIPES: A2.01 prints its roster by kind -- each repeat count beside its kind -- and the sizes a recipe
    # carries, 2 for all but the spice's 1; the recipe names are pinned so a size cannot move between them
    ("group10_floors", "RECIPES"): (1.0, dict(
        [("[%d][1]" % i, _at(r"spice x") if i == 13 else _at(r"x(?= \d+ sizes)")) for i in range(20)]
        + [("<x%d>" % j, _at(p)) for j, (_, p) in enumerate(_RECIPE_KIND)]),
        {"[13][0]": "spice"}),
    # ---- group 11
    ("group11_compliance", "A209"): (1.0, _keyed([
        ("star", r"star(?= \d)"), ("gem", r"hidden gem(?= \d)"), ("moderate", r"moderate(?= \d)"),
        ("question", r"question(?= \d)"), ("at_risk", r"at-risk(?= \d)"), ("fading", r"fading(?= \d)"),
        ("wide_dead", r"wide-dead(?= \d)")]), {}),
    ("group11_compliance", "A528_RUNS"): (1.0, {"['A'][0]": _at(r"A items(?= \d+-)"),
                                                "['A'][1]": _at(r"A items(?= \d+-)", 1),
                                                "['C'][0]": _at(r"C items(?= \d+-)"),
                                                "['C'][1]": _at(r"C items(?= \d+-)", 1)}, {}),
    ("group11_compliance", "TARGET"): (100.0, {"['survival']": _at(r"BRANDED(?= \d)"),
                                               "['months']": _at("gone by", scale=1.0),
                                               "['band'][0]": _at("Category success in the", 1),
                                               "['band'][1]": _at("Category success in the", 2)}, {}),
    ("group11_compliance", "STANTON"): (100.0, {"['survival']": _at("sampled from Mintel GNPD,"),
                                                "['months']": _at(r"at least(?= \d+ months after launch)", scale=1.0)}, {}),
    ("group11_compliance", "PACESETTER_SURVIVED"): (100.0, {"": _at("FoodNavigator-USA, reported")}, {}),
    ("group11_compliance", "PACESETTER_YEARS"): (1.0, {"[0]": _at("Pacesetters 'from"),
                                                       "[1]": _at("Pacesetters 'from", 1)}, {}),
    ("group11_compliance", "LAMBDA"): (1.0, {"": _at(r"LAMBDA(?= \d)")}, {}),
    ("group11_compliance", "SIGMA_PRED"): (1.0, {"": _at("THE VALUE IS OWNER-SIGNED:")}, {}),
    ("group11_compliance", "A713_SHARES"): (100.0, {"[0]": _at("THE PRACTITIONER"),
                                                    "[1]": _at("THE PRACTITIONER", 1)}, {}),
    ("group11_compliance", "GUARANTEED_SALE_MONTHS"): (1.0, {"": _at("section 6a a")}, {}),
    ("group11_compliance", "PRUNE_SHARE"): (100.0, {"": _at("discontinue a size below")}, {}),
    ("group11_compliance", "PRUNE_QUARTERS"): (1.0, {"": _at("discontinue a size below", 1)}, {}),
})


_CHAIN = re.compile(r"[\s:=(]*\d[\d,]*(?:\.\d+)?%?(?:\s*(?:->|/|→)\s*\d[\d,]*(?:\.\d+)?%?)*")


def _after_phrase(row, phrase, with_past=False):
    """The text after each match of `phrase` -- from a word boundary -- in the present sentences of the row's
    figure-publishing fields; with `with_past`, in its history sentences too."""
    pat = re.compile((r"(?<!\w)" if re.match(r"\w", phrase) else "") + phrase)
    now, then = _row_sentences(row)
    return [s[mm.end():] for s in now + (then if with_past else []) for mm in pat.finditer(s)]


def _located_sentence(row, phrase):
    """The rest of the ONE present sentence that carries `phrase` -- else of the one sentence, history included --
    or None."""
    after = _after_phrase(row, phrase)
    if len(after) != 1:
        after = _after_phrase(row, phrase, with_past=True)
    return after[0] if len(after) == 1 else None


def _located(row, phrase, ordinals, width, with_past=False):
    """(figures at the ordinals, matches, chain length) after `phrase` in the ONE present sentence that carries it;
    the figures are None unless the phrase matched exactly once."""
    after = _after_phrase(row, phrase, with_past)
    if len(after) != 1:
        return None, len(after), None
    figs = _figures_as_numbers(after[0])
    chain = _CHAIN.match(after[0])
    return ([figs[o][0] if o < len(figs) else None for o in ordinals], 1,
            len(_figures_as_numbers(chain.group(0))) if chain else 0)


def _choose_scale(members, every):
    """One scale for a sibling group: the one at which every plain member is printed, preferring the one that
    publishes the most arithmetic members by their result; else, when no scale holds every plain member, the one
    that holds the most members. Returns (scale, {member path: scales})."""
    at = dict((it[0], set(_exact_scales(it[1], every))) for it in members)
    plain = [it[0] for it in members if it[3] is None]
    arith = [it[0] for it in members if it[3] is not None]
    fits = [s for s in _MIRROR_SCALES if all(s in at[p] for p in plain)]
    pool = fits or _MIRROR_SCALES
    return max(pool, key=lambda s: (sum(1 for p in plain if s in at[p]), sum(1 for p in arith if s in at[p]))), at


def constant_publication(module, name, ids, items, index, kinds=(), owed=()):
    """(missing, history_only) for one constant under option C, over its typed `items` (typed_items, exemptions
    already removed): each unprinted value as (path, phrase), and each value printed only in a sentence that also
    carries a retired figure.

    Every typed value must EQUAL a figure printed in the FIRST row the constant names, at one unit scale shared with
    its siblings; a typed list, as one consecutive run (the series rule). Typed arithmetic is published by its
    result, printed exactly at its group's scale, or else by the literals typed into it printed as one run in the
    typed order -- A9.17 prints the tariff blend's parts, not its nine-place sum. A located constant
    is read at its locators instead (MIRROR_LOCATORS). `owed` holds the written paths a mirror-owed note scopes: an
    owed element holds its place in a series by any figure, so a debt to a closure unit does not also fail its
    paid siblings. Pure, so the probe can call it on a moved value."""
    row = index.get(ids[0]) if ids else None
    if row is None:
        return [], []
    every, present = _printed_figures(row)
    missing, old = [], []
    if (module, name) in MIRROR_LOCATORS:
        scale, at, labels = MIRROR_LOCATORS[(module, name)]
        typed_text = dict((k[0], k[3]) for k in kinds if k[2])
        for p, lab in sorted(labels.items()):
            if typed_text.get(p) != lab:
                missing.append((p, "%s%s is %r where its locator expects %r -- the count beside it is read as %s's"
                                % (name, p, typed_text.get(p), lab, lab)))
        for p, v, _, _, _, _, _ in items:
            if p not in at:
                missing.append((p, "%s%s = %s has no locator in %s -- nowhere it is printed as itself"
                                % (name, p, _fmt(v), ids[0])))
                continue
            # a locator may carry its own scale, for a record whose fields are different units (A7.14's median
            # days beside its tail share)
            phrase, ordinals, width = at[p][:3]
            sc = at[p][3] if len(at[p]) > 3 else scale
            got, n, chain = _located(row, phrase, ordinals, width)
            past = False
            if n != 1:
                # printed only in a history sentence: a WARNING, as for an unlocated constant, until the history
                # sitting splits the clause (A4.05's "short_ship 26 (was 22)")
                got2, n2, chain2 = _located(row, phrase, ordinals, width, with_past=True)
                if n2 == 1:
                    got, n, chain, past = got2, n2, chain2, True
            if n != 1:
                missing.append((p, "%s%s: its locator %r is in %d present sentences of %s, not one"
                                % (name, p, phrase, n, ids[0])))
            elif width is not None and chain != width:
                missing.append((p, "%s%s: %s prints a chain of %d at its locator %r, where %d are read"
                                % (name, p, ids[0], chain, phrase, width)))
            elif any(g is None or not _same(v * sc, g) for g in got):
                missing.append((p, "%s%s = %s: %s prints %s at its locator (%r, figures %s)"
                                % (name, p, _fmt(v), ids[0], " / ".join("nothing" if g is None else _fmt(g)
                                                                         for g in got), phrase, ordinals)))
            elif past:
                old.append("%s%s = %s" % (name, p, _fmt(v)))
        return missing, old
    now, then = _row_sentences(row)
    groups = {}
    for it in items:
        groups.setdefault(it[2], []).append(it)
    for members in groups.values():
        s, at = _choose_scale(members, every)
        # THE SERIES RULE (identity sitting, owner 2026-09-29). A typed list -- a year-list, a band -- is printed as
        # ONE run of consecutive figures in one present sentence, in its order, at its group's scale. "Somewhere in
        # the row" let each year move onto a figure printed for another quantity: OPDED's y2 5.25 sat in a sentence
        # of its own, and A5.32's KeHE 4 / 5 / 5 was two figures in words. An arithmetic element holds its place in
        # the run by its result or by any figure -- its literals are read below, as their own run.
        for parent, els in _series_of(members).items():
            def at_place(j, f, els=els):
                p, v, _, ops = els[j][:4]
                return any(q is not None and _under(p, q) for q in owed) or \
                    ops is not None and not _same_in(v * s, every) or _same(v * s, f)
            if _run_in(at_place, len(els), now):
                continue
            if _run_in(at_place, len(els), then):
                old.append("%s%s as a series" % (name, parent))
                continue
            text = " / ".join(_fmt(it[1] * s) for it in els)
            missing.extend((it[0], "%s%s = %s is not printed as one series (%s at x%s, consecutive, one present "
                                   "sentence)" % (name, it[0], _fmt(it[1]), text, _fmt(s))) for it in els)
        for p, v, grp, ops, _, _, _ in members:
            if s in at[p]:
                if not _same_in(v * s, present):
                    old.append("%s%s = %s" % (name, p, _fmt(v)))
                continue
            if ops is None:
                missing.append((p, "%s%s = %s%s" % (name, p, _fmt(v), " (printed at x%s, its siblings at x%s)"
                                                    % (_fmt(sorted(at[p])[0]), _fmt(s)) if at[p] else "")))
                continue
            # THE OPERAND RUN (identity sitting). Arithmetic whose result is not printed is published by the literals
            # typed into it printed as ONE run, in the typed order, each at its own scale -- A9.17's "0.07 x 15% x
            # 5/12 + ...". Each literal "somewhere in the row" let BROKER_RETAINER's 12 move to 11 on an 11 A9.09
            # prints for something else.
            def lit(j, f, ops=ops):
                return bool(_exact_scales(ops[j][0], [(f, 0)]))
            if _run_in(lit, len(ops), now):
                continue
            if _run_in(lit, len(ops), then):
                old.append("%s%s's typed %s" % (name, p, " ".join(t for _, t in ops)))
                continue
            missing.append((p, "%s%s = %s, arithmetic: its result is not printed, nor its typed %s as one run"
                            % (name, p, _fmt(v), ", ".join(t for _, t in ops))))
    return missing, old


def _same_in(x, figs):
    return any(_same(x, v) for v, _ in figs)


def _unit_done(plan):
    """The closure units whose section opens a line with **DONE -- the convention U1 and U2 use."""
    done = set()
    for m in re.finditer(r"^### (U\d+)\.(.*?)(?=^### |\Z)", plan, re.M | re.S):
        if re.search(r"^\*\*DONE", m.group(2), re.M):
            done.add(m.group(1))
    return done


def check_generator_constants_published(index, sources=None):
    """Every typed generator constant names a row, and publishes each of its typed values there, exactly.

    `sources` ({module: source text}) replaces the three generators -- the self-test's synthetic modules."""
    gp = "every generator constant that names a row publishes its value there"
    gn = "every typed generator constant names a row or states why it does not"
    bad, unnamed, past_only, exempted, computed, owing = [], [], [], [], [], []
    plan = rd(CLOSURE_PLAN)
    units, done = set(re.findall(r"^### (U\d+)\.", plan, re.M)), _unit_done(plan)
    try:
        if sources is None:
            sys.path.insert(0, os.path.join(ROOT, "scripts"))
            spaces = dict((m, vars(__import__(m))) for m in GENERATOR_MODULES)
        else:
            spaces = {}
            for m, src in sources.items():
                spaces[m] = {}
                exec(compile(src, m, "exec"), spaces[m])
    except Exception as exc:                                  # pragma: no cover - import failure
        report(BLOCK, gp, ["generators did not import: %s" % exc])
        return
    seen = set()
    for m in spaces:
        for name, line, ids, how, exempts, oweds, kinds in generator_constants(m, None if sources is None
                                                                               else sources[m]):
            seen.add((m, name))
            where = "%s.%s (line %d)" % (m, name, line)
            items = typed_items(kinds)
            whole_exempt = any(not sc for sc, _ in exempts)
            ex_paths = [_canon(q) for sc, _ in exempts for q in sc]
            for sc, text in exempts:
                reason = re.split(r"\. | -- ", text.strip().lstrip(",;- "))[0].rstrip(".")
                exempted.append("%s%s: %s" % (where, " " + ", ".join(name + q for q in sc) if sc else "",
                                              reason or "NO REASON GIVEN"))
                if not reason:
                    bad.append("%s is mirror-exempt with no reason -- an exemption states why" % where)
            for q in ex_paths + [_canon(q) for sc, _ in oweds for q in sc]:
                if q is None or not any(_under(p, q) for p, _, _, _, _, _, _ in items):
                    bad.append("%s's note names a path the constant does not type -- %s" % (where, q))
            if whole_exempt:
                if oweds:
                    bad.append("%s is both mirror-exempt as a whole and mirror-owed -- a value is a figure owed to a "
                               "unit, or not a figure" % where)
                continue
            items = [it for it in items if not any(_under(it[0], q) for q in ex_paths if q is not None)]
            if not ids:
                if items:
                    unnamed.append("%s = %s is typed and names no row -- name the row that prints it, or state "
                                   "\"mirror-exempt:\" and why it is not a figure" % (where, repr(spaces[m].get(name))[:60]))
                continue
            unknown = [i for i in ids if i not in index]
            if unknown:
                bad.append("%s names %s, which the registry does not hold" % (where, ", ".join(unknown)))
            runtime = _leaves(spaces[m].get(name))
            derived = [p for p, _, _ in runtime if not _typed(p, kinds)]
            if derived:
                computed.append("%s: %s" % (where, "the whole constant" if len(derived) == len(runtime)
                                            else ", ".join(name + p for p in derived[:6])
                                            + (" and %d more" % (len(derived) - 6) if len(derived) > 6 else "")))
            missing, old = constant_publication(m, name, ids, items, index, kinds,
                                                [_canon(q) for sc, _ in oweds for q in sc] or
                                                ([""] if oweds else []))
            # OWED (owner, 2026-09-28): a typed value C finds unprinted, whose print a closure unit already schedules.
            # It WARNS, naming the unit, until the row prints it; a path the row prints, in whole or in part, BLOCKS
            # as paid, and so does a debt to a unit marked DONE -- a debt cannot outlive its payment or its payer.
            for sc, text in oweds:
                unit = re.match(r"\s*,?\s*(U\d+)\b", text)
                unit, reason = (unit.group(1), text[unit.end():].strip().lstrip("-").strip()) if unit else (None, text)
                if unit not in units:
                    bad.append("%s is mirror-owed to %r, which is not a unit of %s -- an owed value names the "
                               "closure unit that prints it" % (where, unit or text[:20], CLOSURE_PLAN))
                elif unit in done:
                    bad.append("%s is mirror-owed to %s, which is DONE -- print the value%s and remove the note"
                               % (where, unit, " and add its locators" if (m, name) in MIRROR_LOCATORS else ""))
                if not reason:
                    bad.append("%s is mirror-owed with no reason -- the note states what is owed" % where)
                for q in [_canon(x) for x in sc] or [""]:
                    under = [it[0] for it in items if q is not None and _under(it[0], q)]
                    due = [p for p in under if any(p == mp for mp, _ in missing)]
                    if under and not due:
                        bad.append("%s is mirror-owed to %s for %s, and %s now prints it -- the debt is paid; remove "
                                   "the note" % (where, unit, name + q, ids[0]))
                    elif len(due) < len(under):
                        bad.append("%s is mirror-owed to %s for %s, and %s already prints %s -- narrow the note to "
                                   "what is unpaid" % (where, unit, name + q, ids[0],
                                                       ", ".join(name + p for p in under if p not in due)))
                    if due:
                        owing.append("%s, owed to %s (%s): %s%s" % (
                            where, unit, reason, "; ".join(msg for mp, msg in missing if mp in due)[:400],
                            " -- its payment cannot be seen until %s adds its locators" % unit
                            if (m, name) in MIRROR_LOCATORS and not MIRROR_LOCATORS[(m, name)][1] else ""))
                    missing = [(mp, msg) for mp, msg in missing if mp not in due]
            if missing:
                bad.append("%s names %s first (%s), which does not print it: %s"
                           % (where, ids[0], how, "; ".join(msg for _, msg in missing[:6])
                              + (" and %d more" % (len(missing) - 6) if len(missing) > 6 else "")))
            if old:
                past_only.append("%s: %s -- printed only in a clause that also carries a retired figure, in %s"
                                 % (where, ", ".join(old[:6]), ids[0]))
    if sources is None:
        for key in sorted(set(MIRROR_LOCATORS) - seen):
            bad.append("MIRROR_LOCATORS names %s.%s, which no generator binds -- a renamed constant reverts to the "
                       "unlocated reading silently" % key)
    report(BLOCK, gp, bad)
    report(BLOCK, gn, unnamed)
    report(WARN, "generator constants owed to a closure unit: named, dated to the unit, not yet printed", owing)
    report(WARN, "no generator constant is published only by a row's history", past_only)
    report(INFO, "generator constants exempt from the mirror, each with its reason", exempted)
    report(INFO, "generator constants (or elements) computed from other values: the figure checks cover them, "
                 "this check covers what is typed", computed)


def _typed_unit(text, v):
    """One unit of the precision a value was typed at, from its source text: "26" -> 1, "0.10" -> 0.01,
    "1e-05" -> 1e-05."""
    from decimal import Decimal, InvalidOperation
    try:
        return float(Decimal(1).scaleb(Decimal(str(text).replace("_", "").lstrip("-")).as_tuple().exponent))
    except (InvalidOperation, ValueError, TypeError):
        return float(Decimal(1).scaleb(Decimal(repr(float(v))).as_tuple().exponent))


def _reeval(node, j, new):
    """The arithmetic element `node` evaluated with its j-th typed literal replaced by `new` -- how a moved
    literal moves the result."""
    import ast
    import copy
    tree = copy.deepcopy(node)
    lits = []

    def walk(n):
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub) and isinstance(n.operand, ast.Constant) and \
                isinstance(n.operand.value, (int, float)) and not isinstance(n.operand.value, bool):
            lits.append((n, True))
            return
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            lits.append((n, False))
            return
        for c in ast.iter_child_nodes(n):
            walk(c)
    walk(tree)
    target, neg = lits[j]
    if neg:
        target.operand.value = -new
    else:
        target.value = new
    return float(eval(compile(ast.Expression(body=tree), "<moved>", "eval"), {"__builtins__": {}}))


def constant_drift(index, sources=None):
    """OPTION C's mutation probe (owner, 2026-09-28; FAILURES 2026-09-25): (values, moves, survivors).

    Each covered typed value -- a literal, a literal typed into arithmetic (its result recomputed), a repeat count
    -- is moved one unit of the precision it was TYPED at, up and down, and the check must report something it did
    not report before; a literal repeated by `* n` moves in every copy at once. A located leaf is also moved onto
    every other figure in its locator's sentence. A SURVIVOR is a move the check accepts: the moved number is
    printed in the same row, at the same scale, as some other quantity. C left 280 of them; the identity sitting
    (2026-09-29) closed them, and check_constant_drift blocks on any that returns."""
    import copy
    survivors, moves, values = [], 0, 0
    mods = sources or dict((m, None) for m in GENERATOR_MODULES)
    for m in mods:
        for name, line, ids, how, exempts, oweds, kinds in generator_constants(m, mods[m]):
            if not ids or ids[0] not in index or any(not sc for sc, _ in exempts):
                continue
            skip = [_canon(q) for sc, _ in exempts + oweds for q in sc] + (["" ] if any(not sc for sc, _ in oweds)
                                                                        else [])
            items = [it for it in typed_items(kinds) if not any(q is not None and _under(it[0], q) for q in skip)]
            base = set(p for p, _ in constant_publication(m, name, ids, items, index, kinds)[0])
            by_origin = {}
            for it in items:
                by_origin.setdefault(it[6], []).append(it)
            for origin, copies in by_origin.items():
                p, v, grp, ops, node, text, _ = copies[0]
                paths = set(c[0] for c in copies)
                trials = []
                if ops is None:
                    u = _typed_unit(text, v)
                    trials = [("%s -> %s" % (_fmt(v), _fmt(v + d)), dict((q, (v + d, None)) for q in paths))
                              for d in (u, -u)]
                    loc = MIRROR_LOCATORS.get((m, name), (None, {}, {}))
                    if p in loc[1]:
                        sc = loc[1][p][3] if len(loc[1][p]) > 3 else loc[0]
                        for f in _figures_as_numbers(_located_sentence(index[ids[0]], loc[1][p][0]) or ""):
                            x = f[0] / sc
                            if not _same(x, v):
                                trials.append(("%s onto %s" % (_fmt(v), _fmt(x)), dict((q, (x, None)) for q in paths)))
                else:
                    for j, (o, t) in enumerate(ops):
                        u = _typed_unit(t, o)
                        for d in (u, -u):
                            r = _reeval(node, j, o + d)
                            trials.append(("typed %s -> %s" % (t, _fmt(o + d)),
                                           dict((q, (r, [(o + d if jj == j else oo, tt)
                                                         for jj, (oo, tt) in enumerate(ops)])) for q in paths)))
                values += 1
                for label, change in trials:
                    moves += 1
                    moved = [(q, change[q][0], g, change[q][1] if q in change else o_, nd, tx, og)
                             if q in change else (q, vv, g, o_, nd, tx, og)
                             for q, vv, g, o_, nd, tx, og in items]
                    got = set(pp for pp, _ in constant_publication(m, name, ids, moved, index, kinds)[0])
                    if got == base:
                        survivors.append((m, name, ids[0], p, label))
    return values, moves, survivors


DRIFT_CHECK = "no typed value survives a one-unit drift: each is printed as itself"


def check_constant_drift(index, sources=None):
    """The probe's survivors. Printed as a warning from option C (owner, 2026-09-28), when 280 of 1,622 moves passed,
    each onto a figure its row printed for another quantity. The identity sitting (2026-09-29) closed them -- the
    series rule, the operand run and labelled locators -- and the check BLOCKS from then: a warning that has been
    emptied refills silently, one coincidental constant at a time."""
    values, moves, survivors = constant_drift(index, sources)
    per = {}
    for m, name, rid, p, label in survivors:
        per.setdefault((m, name, rid), []).append("%s%s %s" % (name, p, label))
    lines = ["%d of %d one-unit moves pass, in %d constants (%d typed values probed): each lands on a figure its "
             "row prints for another quantity -- print it as one series, or add its locator"
             % (len(survivors), moves, len(per), values)] if survivors else []
    lines.extend("%s.%s (%s): %d -- %s" % (m, n, r, len(v), "; ".join(v[:3]) + (" ..." if len(v) > 3 else ""))
                 for (m, n, r), v in sorted(per.items(), key=lambda kv: -len(kv[1])))
    report(BLOCK, DRIFT_CHECK, lines)


def check_tier_a_verified(rows):
    """R12 of the regen plan, restated (owner, 2026-11-12, DECISIONS#u17-start): no outside reviewer looks at any row,
    so `verified_by` stays empty and a Tier A row rests on its record and the owner's signature. Printed, never
    blocking: the list says what rests on the owner alone, not what is owed."""
    open_ = sorted(r["anchor_id"] for r in rows if r.get("tier") == "A" and not r.get("verified_by"))
    report(INFO, "Tier A rows resting on owner signature, no outside reviewer",
           ["%d of %d: %s" % (len(open_), sum(1 for r in rows if r.get("tier") == "A"), ", ".join(open_))]
           if open_ else [])


TIER_A_RECORD = "docs/anchors/TIER-A-VERIFICATION.md"
PINNED_RECORD_CHECK = "every pinned row stands on a U14 record that holds"
_RECORD_HOLDS = re.compile(r"\*\*HOLDS\*\*|Verdict: HOLDS(?:\.\*\*|\*\*)|Corrected \(owner|Ruled \(owner")
_RECORD_UNREAD = re.compile(r"unread this batch")     # a verdict on a source U14 could not read clears nothing
_RECORD_UNPINNED = re.compile(r"\bNot\s+pinned\b")     # a ruling that holds a row out of the pin (U14 batch 8, 2026-11-06)
_RECORD_RULING = re.compile(r"^- \*\*(?:Ruled|Corrected) \(owner.*?(?=^- |\Z)", re.M | re.S)


def _last_ruling(block):
    """The owner's latest ruling line in a record block: a later ruling overturns an earlier one (A4.05, held out on
    2026-11-06 and pinned the same day on its base's ruling), so only the last one can hold a row out of the pin."""
    rulings = _RECORD_RULING.findall(block)
    return rulings[-1] if rulings else ""


def check_pinned_records(index, record=None):
    """U14's record check (regen plan U14; owner, 2026-10-23, ruling 4, DECISIONS#u14). `status: pinned` is a claim, and
    the record backs it: a row pinned on a record has a `### <id>` heading in TIER-A-VERIFICATION.md whose block holds
    (a clean verdict, or the owner's correction or ruling recorded under it); a Tier D row pinned on its signature and
    decision is named in the record's Tier D list, carries a resolving `decision_ref`, and, if numeric, a signature
    whose fingerprint is current. A short record that ends in a FINDING does not pin its row."""
    text = rd(TIER_A_RECORD) if record is None else record
    heads = list(re.finditer(r"^### (A\d+\.\d+)\b", text, re.M))
    blocks = {}
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        nxt = re.compile(r"^## ", re.M).search(text, m.end(), end)
        blocks[m.group(1)] = text[m.end():nxt.start() if nxt else end]
    d_list = re.search(r"^### The Tier D rows, pinned[^\n]*\n(.*?)(?=^#{2,3} |\Z)", text, re.M | re.S)
    d_ids = set(re.findall(r"A\d+\.\d+", d_list.group(1))) if d_list else set()
    bad = []
    for rid, r in sorted(index.items()):
        if r.get("status") != "pinned":
            continue
        if rid in blocks:
            if not _RECORD_HOLDS.search(blocks[rid]) or _RECORD_UNREAD.search(blocks[rid]):
                bad.append("%s is pinned, and its U14 record does not hold" % rid)
            elif _RECORD_UNPINNED.search(_last_ruling(blocks[rid])):
                bad.append("%s is pinned, and its U14 record rules it not pinned" % rid)
        elif r.get("tier") == "D" and rid in d_ids:
            if not r.get("decision_ref"):
                bad.append("%s is pinned on its decision, and carries no decision_ref" % rid)
            if r.get("unit") not in ("definition", "formula", "date-range") and (
                    not r.get("owner_signed") or r.get("signed_figures") != fingerprint_str(r)):
                bad.append("%s is pinned on its signature, and the signature is missing or lapsed" % rid)
        else:
            bad.append("%s is pinned, and TIER-A-VERIFICATION.md has no record of it" % rid)
    report(BLOCK, PINNED_RECORD_CHECK, bad)


U14_FIRST_ORDER = frozenset("A1.01 A1.02 A8.01 A5.38 A1.05 A3.04 A3.02 A4.14 A4.01 A4.02 A4.07 "
                            "A9.11 A9.02 A9.14 A10.19 A5.11 A9.04".split())   # R16 of the regen plan
FIRST_ORDER_FLAG_CHECK = "the rows flagged first_order are R16's ruled rows, by id"


def check_first_order_flag(index):
    """U17 (regen plan; owner, 2026-10-07, DECISIONS#u10-restatement): the platform reads `first_order` from the
    vendored registry, and the ruling is the list of ids, so the flag must equal it. A row unflagged to clear a check,
    or flagged outside the ruling, is reported by id; no count is asserted."""
    flagged = set(rid for rid, r in index.items() if r.get("first_order") is True)
    bad = ["%s is ruled first-order (R16), and the registry does not flag it" % rid
           for rid in sorted(U14_FIRST_ORDER - flagged)]
    bad += ["%s is flagged first_order, and R16 does not rule it" % rid for rid in sorted(flagged - U14_FIRST_ORDER)]
    bad += ["%s: first_order is %r; it is true or absent" % (rid, r["first_order"])
            for rid, r in sorted(index.items()) if "first_order" in r and r["first_order"] is not True]
    report(BLOCK, FIRST_ORDER_FLAG_CHECK, bad)


FIRST_ORDER_SIGNED_CHECK = "every first-order row is owner-signed at its current fingerprint, verified_by empty (U17)"


def check_first_order_signed(index):
    """U17's close (owner, 2026-11-12, DECISIONS#u17-start): the first-order rows are owner-reviewed, not externally
    verified. Each row flagged `first_order` carries `owner_signed` with `signed_figures` equal to its fingerprint now
    (a carry the gate admits rewrites both, DECISIONS#signature-carry), and `verified_by` empty: no row claims an
    outside reviewer. It replaces the `verified_by` restatement R16 first specified, which fell away with the
    reviewers."""
    bad = []
    for rid, r in sorted(index.items()):
        if r.get("first_order") is not True:
            continue
        if r.get("verified_by") is not None:
            bad.append("%s is first-order and carries verified_by %r; no outside review took place"
                       % (rid, r["verified_by"]))
        if not r.get("owner_signed"):
            bad.append("%s is first-order and not owner-signed" % rid)
        elif r.get("signed_figures") != fingerprint_str(r):
            bad.append("%s is first-order; its signature is at %s and the row is now %s: the owner re-signs"
                       % (rid, r.get("signed_figures"), fingerprint_str(r)))
    report(BLOCK, FIRST_ORDER_SIGNED_CHECK, bad)


SET_RECORD_CHECK = "every row in U14's set has its record, and every two_endpoint record states both endpoints"
_ENDPOINTS = re.compile(r"^- \*\*Endpoints\.\*\*(.*?)(?=^- |\Z)", re.M | re.S)
_ENDPOINT_CURRENT = re.compile(r"\bCurrent:(.*?)(?=\b(?:Well-run|Achievable|Counterfactual):|\Z)", re.S)
_ENDPOINT_SECOND = re.compile(r"\b(?:Well-run|Achievable|Counterfactual):(.*)", re.S)


def u14_set(index):
    """U14's ruled set (owner, 2026-10-09; regen plan U18): every Tier A row, every two_endpoint row, R16's first-order
    rows, and one hop of depends_on from the first-order rows. Enumerated from the registry, never counted, so a
    flag that moves moves the set (docs/plans/u18-working/u14_set.py prints the same list)."""
    s = set(rid for rid, r in index.items()
            if r.get("tier") == "A" or r.get("two_endpoint") or rid in U14_FIRST_ORDER)
    for fo in U14_FIRST_ORDER:
        s.update(d for d in (index.get(fo, {}).get("depends_on") or []) if d in index)
    return s


def check_set_records(index, record=None):
    """U14's record check (2) (regen plan U14; blocking from the commit that closes U14): every row in the set has its
    `### <id>` heading in TIER-A-VERIFICATION.md, and every two_endpoint row's block carries an `- **Endpoints.**`
    line naming both endpoints, `Current:` and `Well-run:` / `Achievable:` / `Counterfactual:`, each with its source or
    derivation in parentheses. The check proves both are stated and attributed; whether the attribution is honest is
    the record's, read by the owner at each batch (DECISIONS#u14, batch 8: the bar)."""
    text = rd(TIER_A_RECORD) if record is None else record
    heads = list(re.finditer(r"^### (A\d+\.\d+)\b", text, re.M))
    blocks = {}
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        nxt = re.compile(r"^## ", re.M).search(text, m.end(), end)
        blocks[m.group(1)] = text[m.end():nxt.start() if nxt else end]
    bad = []
    for rid in sorted(u14_set(index)):
        if rid not in blocks:
            bad.append("%s is in U14's set, and TIER-A-VERIFICATION.md has no heading for it" % rid)
            continue
        if not index[rid].get("two_endpoint"):
            continue
        m = _ENDPOINTS.search(blocks[rid])
        cur = _ENDPOINT_CURRENT.search(m.group(1)) if m else None
        sec = _ENDPOINT_SECOND.search(m.group(1)) if m else None
        if not (cur and sec and "(" in cur.group(1) and "(" in sec.group(1)):
            bad.append("%s is two_endpoint, and its record does not state both endpoints, each with its source or "
                       "derivation" % rid)
    report(BLOCK, SET_RECORD_CHECK, bad)


def check_retired_figures(rows):
    """No value borrowed after its owning group retired it.

    A series named inside a passage that marks it withdrawn must not reappear as
    live text elsewhere. Restricted to three-part series, which are distinctive
    enough that a collision is a finding rather than a coincidence.
    """
    kill = re.compile(r"(?i)\b(withdrawn|withdraws|retired|struck|superseded|"
                      r"no longer|the earlier|the first version|the first draft|"
                      r"corrected \d{4})\b")
    retired, live = {}, {}
    for r in rows:
        for s in sentences(r["value"]):
            bucket = retired if kill.search(s) else live
            for t in TRIPLE.findall(s):
                bucket.setdefault(re.sub(r"\s+", "", t), set()).add(r["anchor_id"])
        # the history field is retired by construction (DECISIONS#history-move) -- except a series the row itself
        # still prints live, which a history entry names as what REPLACED the retired one ("restated to 34.9 /
        # 28.3 / 25.8%")
        mine = set(re.sub(r"\s+", "", t) for f in FINGERPRINTED_FIELDS for t in TRIPLE.findall(norm(str(r.get(f) or ""))))
        for t in TRIPLE.findall(norm(str(r.get("history") or ""))):
            if re.sub(r"\s+", "", t) not in mine:
                retired.setdefault(re.sub(r"\s+", "", t), set()).add(r["anchor_id"])
    bad = ["%s: retired in %s, still live in %s"
           % (t, ", ".join(sorted(retired[t])), ", ".join(sorted(live[t])))
           for t in sorted(set(retired) & set(live))]
    report(WARN, "no retired figure reappears live", bad)


# CROSS-ROW CREDITS (U3, owner 2026-09-30). A row that CREDITS another row with a figure -- "A9.14's 9.81%",
# "33% of wholesale (A5.38)" -- must find it among that row's PRESENT figures. The history move's six stale copies
# were found by hand; this is the general scan. A credit is the possessive or a trailing single-id parenthesis, and
# the figures credited are ONE CHAIN: a figure and whatever follows it by "/", "->" or an unspaced range dash. The
# chain stops at an operator, so "A7.28's 0.60 - 1,536,621" credits A7.28 with 0.60 and the rest is the crediting
# row's own arithmetic (owner: a credited derivation is a credit to a rule's operands). A credited number absent
# from the source is the defect, whatever surrounds it. The copy may print fewer places than the source (12.06
# for 12.058), never more; the sign is not compared ("a loss of 2.16%"). Registry to registry only -- the sourcing
# docs' copies are U6's surface.
_CR_FIG = r"-?\$?\d[\d,]*(?:\.\d+)?(?:\s?(?:%|pt|bp|x|M|K|B)(?![A-Za-z]))?(?:\s+y\d\b)?"
_CR_CHAIN = _CR_FIG + r"(?:(?:\s*/\s*|\s*->\s*|(?<=[\d%])-(?=\$?\d))" + _CR_FIG + r")*"
_CR_POSSESSIVE = re.compile(r"\b(A\d+\.\d+)'s\s+(?:[A-Za-z][A-Za-z-]*\s+){0,3}?(" + _CR_CHAIN + ")")
_CR_PAREN = re.compile(r"(?<![\w.$-])(" + _CR_CHAIN + r")\s*(?:[a-z][a-z-]*\s+){0,3}?\((A\d+\.\d+)\)")
CREDIT_CHECK = "a figure one row credits to another is printed there"
# (crediting row, source row, figure as printed): the closure unit that corrects it. Reported WARN until that unit
# is marked DONE in the closure plan, then BLOCK -- the `mirror-owed:` convention, for registry prose.
CREDIT_OWED = {}                           # empty since U4 paid A11.25's credit of A2.08's 1.08 (UNIT_LB, not 13/12)


def _rounds_to(pool, x, places):
    """Is some figure of `pool`, at some unit scale, `x` at x's printed places? Copy-side rounding only."""
    tol = 0.5 * 10 ** -places + 1e-9 * max(1.0, abs(x))
    return any(abs(abs(v * s) - abs(x)) <= tol for s in _MIRROR_SCALES for v in pool)


def credited_figures(rows):
    """[(crediting row, source row, printed figure, verdict, span)] for every credit in a present sentence. The
    verdict is ok, STALE (the source prints it only in its history) or UNPRINTED."""
    index = dict((r["anchor_id"], r) for r in rows)
    out = []
    for r in rows:
        for s in _row_sentences(r)[0]:
            s = norm(s)
            hits = [(m.group(1), m.group(2), m.group(0)) for m in _CR_POSSESSIVE.finditer(s)]
            hits += [(m.group(2), m.group(1), m.group(0)) for m in _CR_PAREN.finditer(s)]
            for src, chain, span in hits:
                if src == r["anchor_id"] or src not in index:
                    continue
                every, present = _printed_figures(index[src])
                now = [v for v, _ in present]
                past = [v for v, _ in every[len(present):]]
                for tok in fingerprint_figures(chain):
                    t = tok.replace(",", "")
                    x, places = float(t), len(t.split(".")[1]) if "." in t else 0
                    verdict = ("ok" if _rounds_to(now, x, places) else
                               "STALE" if _rounds_to(past, x, places) else "UNPRINTED")
                    out.append((r["anchor_id"], src, t.lstrip("-"), verdict, span))
    return out


def check_cross_row_credits(rows, owed=None):
    owed = CREDIT_OWED if owed is None else owed
    done = _unit_done(rd(CLOSURE_PLAN))
    bad, owing, seen = [], [], set()
    for row, src, fig, verdict, span in credited_figures(rows):
        if verdict == "ok" or (row, src, fig) in seen:
            continue
        seen.add((row, src, fig))
        msg = "%s credits %s with %s, which %s -- \"%s\"" % (
            row, src, fig, "it prints only as history" if verdict == "STALE" else "it does not print", span)
        unit = owed.get((row, src, fig))
        if unit and unit not in done:
            owing.append("%s (owed to %s)" % (msg, unit))
        else:
            bad.append(msg + (" (owed to %s, which is DONE)" % unit if unit else ""))
    stale = [k for k in owed if k not in seen]
    bad += ["CREDIT_OWED lists %s crediting %s with %s, which is no longer a finding -- remove it" % k
            for k in sorted(stale)]
    report(BLOCK, CREDIT_CHECK, bad)
    report(WARN, "credits owed to a later closure unit", owing)


def check_history_reach(rows):
    """INFORMATIONAL (owner, 2026-09-30): a figure retired to row Y's history, and not among Y's present figures,
    printed in a present sentence of another row that names Y. Sentence-level, so mostly coincidence; it is here for
    the copies that never wrote "Y's"."""
    index = dict((r["anchor_id"], r) for r in rows)
    out = []
    for r in rows:
        for s in _row_sentences(r)[0]:
            for src in sorted(set(ANCHOR_ID.findall(s))):
                if src == r["anchor_id"] or src not in index:
                    continue
                every, present = _printed_figures(index[src])
                now = set(v for v, _ in present)
                past = set(v for v, _ in every[len(present):]) - now
                for x, _ in _figures_as_numbers(s):
                    if x in past and not any(_same(x * k, v) for k in _MIRROR_SCALES for v in now):
                        out.append("%s prints %s beside %s, which %s retired" % (r["anchor_id"], _fmt(x), src, src))
    report(INFO, "a figure another row retired, printed beside its id", sorted(set(out)))


GROUP2_DOC ="docs/anchors/sourcing/group-2-catalog.md"
NUMBER_WORDS = {"ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14}
# group10_floors.A201_LINE, recipe kind by line, is what A2.01's Test A rate (test_a_rate) is counted over.
# _a201_line_mirror compares it with the doc table's Recipes and Club columns, so a recipe moved to another line in the
# doc cannot leave the rate stale. The gate carried the map until 2026-09-23; the owner moved it into the generator.


def _a201_line_mirror(F, text=None):
    """Group 2's line table against the recipe-to-line map the gate carries for A2.01's Test A rate (2026-09-23).

    Per line, the table's Recipes column must equal the recipes group 10 carries on that line and its Club column
    the club designs on them. A recipe kind the map does not name, or a table line it does not reach, is reported
    rather than skipped.
    """
    text = rd(GROUP2_DOC) if text is None else text
    m = re.search(r"^\| Line \| Manufacturing \| Recipes \| Size points \| Designs \| Club \| Ladder\? \|$"
                  r"\n^\|[-|]+\|$\n(.*?)^\| \| \|", text, re.M | re.S)
    if not m:
        return ["%s: the line table the recipe-to-line map mirrors was not found" % GROUP2_DOC]
    table = {}
    for r in m.group(1).split("\n"):
        if r.startswith("| "):
            cells = [c.strip() for c in r.strip("|").split("|")]
            table[cells[0]] = (int(re.match(r"\d+", cells[2]).group(0)), int(cells[5]))
    unknown = sorted(set(kind for kind, _, _ in F.RECIPES) - set(F.A201_LINE))
    if unknown:
        return ["group10_floors.RECIPES carries recipe kinds the line map does not name: %s" % ", ".join(unknown)]
    bad = []
    for line in sorted(set(F.A201_LINE.values()) | set(table)):
        got = (sum(1 for kind, _, _ in F.RECIPES if F.A201_LINE[kind] == line),
               sum(1 for r in F.CLUB_RECIPE if F.A201_LINE[F.RECIPES[r][0]] == line))
        if table.get(line) != got:
            bad.append("%s: group 2's line table gives recipes / club designs %s; group10_floors on the gate's line "
                       "map gives %s" % (line, table.get(line), got))
    return bad


def check_catalogue_table(index, text=None):
    """Group 2's catalogue table, its prose, and A2.04 state one set of counts.

    The same shape as the worklist header check, applied to the one table-and-prose
    pair that drifted: the line table showed ten club SKUs while its own prose and
    A2.04 said eleven, because the table never marked the 33.8 fl oz oil as club.
    The count was a number someone typed beside a table rather than a sum someone
    measured from it. So the SKU and Club columns are summed here and every place
    that states those totals is checked against the sums:

      - the table's own totals row;
      - the headline's window-start count, which is SKUs minus club;
      - the Club bullet's "N of M designs";
      - A2.04's registered club count.

    The vocabulary is the 2026-09-17 ruling's: the table column and the club bullet count DESIGNS,
    the headline counts the SKUs sellable at window start, and the two differ by the club count.
    """
    text = rd(GROUP2_DOC) if text is None else text
    bad = []
    m = re.search(r"^\| Line \| Manufacturing \| Recipes \| Size points \| Designs \| Club \| Ladder\? \|$"
                  r"\n^\|[-|]+\|$\n(.*?)^\| \| \| \*\*(\d+)\*\* \| \| \*\*(\d+)\*\* \| \*\*(\d+)\*\* \|",
                  text, re.M | re.S)
    if not m:
        report(BLOCK, "catalogue table agrees with its prose and A2.04",
               ["%s: the line table with a Club column and a totals row was not found" % GROUP2_DOC])
        return
    rows = [r for r in m.group(1).split("\n") if r.startswith("| ")]
    skus = clubs = 0
    for r in rows:
        cells = [c.strip() for c in r.strip("|").split("|")]
        skus += int(re.match(r"\d+", cells[4]).group(0))
        clubs += int(cells[5])
    recipes_total, skus_total, club_total = int(m.group(2)), int(m.group(3)), int(m.group(4))
    if skus != skus_total:
        bad.append("line table Designs column sums to %d; its totals row says %d" % (skus, skus_total))
    if clubs != club_total:
        bad.append("line table Club column sums to %d; its totals row says %d" % (clubs, club_total))
    head = re.search(r"\*\*(\d+) recipes, (\d+) SKUs at window start", text)
    if not head:
        bad.append("headline window-start count not found")
    elif int(head.group(2)) != skus - clubs:
        bad.append("headline says %s SKUs at window start; the table gives %d - %d = %d"
                   % (head.group(2), skus, clubs, skus - clubs))
    bullet = re.search(r"\*\*Club\*\* is (\d+) of (\d+) designs", text)
    if not bullet:
        bad.append("Club bullet 'N of M SKUs' not found")
    elif (int(bullet.group(1)), int(bullet.group(2))) != (clubs, skus):
        bad.append("Club bullet says %s of %s; the table gives %d of %d"
                   % (bullet.group(1), bullet.group(2), clubs, skus))
    a204 = re.match(r"(\w+) distinct club DESIGNS", " ".join(str(index["A2.04"]["value"]).split()))
    registered = NUMBER_WORDS.get(a204.group(1).lower()) if a204 else None
    if registered is None:
        bad.append("A2.04's club count could not be read")
    elif registered != clubs:
        bad.append("A2.04 registers %d club designs; the table's Club column sums to %d" % (registered, clubs))
    report(BLOCK, "catalogue table agrees with its prose and A2.04", bad)


def check_no_shared_nodes(rows):
    """No two rows share one object -- that is, the registry carries no YAML alias.

    FOUND BY HITTING IT, 2026-09-21. `A3.04` defined `depends_on: &id001` and `A3.06`
    aliased it with `*id001`, so both rows held ONE list. The house splice re-emits a single
    row through `yaml.safe_dump` and splices it into its own line span (FAILURES 2026-09-18/19):
    re-emitting the DEFINING row expands the anchor, the alias in the other row is then
    undefined, and the registry stops parsing. The backfill below tripped exactly that.

    Identity, not syntax: a regex for `&name` / `*name` would have to tell an anchor from an
    asterisk in prose, and the hazard is not the syntax but the SHARING, which is what makes a
    single-row rewrite unsound.
    """
    seen, bad = {}, []
    for r in rows:
        for field, v in r.items():
            if isinstance(v, (list, dict)):
                owner = seen.setdefault(id(v), (r.get("anchor_id"), field))
                if owner[0] != r.get("anchor_id"):
                    bad.append("%s.%s and %s.%s are ONE object -- a YAML alias. Write both out in "
                               "full: re-emitting either row alone orphans the other."
                               % (owner[0], owner[1], r.get("anchor_id"), field))
    report(BLOCK, "no two rows share one object (no YAML aliases)", bad)


SIGNED_FIGURES = "signed_figures"
# The fields that publish a row's figures (owner, 2026-09-23). `value` alone was the first form, and A11.28's
# variance shares moved from 9.9 / 33.3 to 10.2 / 34.2 inside its `plausibility_anchor` with the signature
# standing. `figure` and `measured` state what a source says, so a number there is a claim the signature
# vouches for. NOT covered, by ruling: `rationale` is the reasoning, and `sources[]` quotes someone else's text.
# DECISIONS#fingerprint-every-figure-field.
FINGERPRINTED_FIELDS = ("value", "plausibility_anchor", "figure", "denominator", "measured")

# The fingerprint's own reader (owner, 2026-09-23): "a fingerprint that can't see a range's upper bound or x.48
# isn't a fingerprint". _NUMBER's lookbehind skips any digit after '-', a letter or '.', so it read "10-15%" as
# 10, "2x18" as 2 and ".48" as nothing -- 148 figures in signed rows' fingerprinted fields that could move with
# the signature standing. The figure checks keep _NUMBER; they read ranges through _RANGE.
_FP_DIGITS = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?|\.\d+")
# _BLANKED with one difference: a requirement pointer (03:150) is blanked only where no digit or point is glued to
# its front. The shared pattern read A10.16's "2.86:1" as a pointer, "86:1", and left the fingerprint only the 2, so
# the cadence ratio could move with the signature standing (generator read of 2026-09-23). The figure checks keep
# _BLANKED unchanged.
_FP_BLANKED = re.compile(r"\b\d{4}-\d{2}(?:-\d{2})?\b|(?<![\d.])\b\d{2}:\d+(?:/\d+)*|\bA\d+\.\d+\b")


def fingerprint_figures(text):
    """Every figure a reader sees in `text`, as printed, in order.

    After `_unwrap` and `_BLANKED` (a date, an anchor id or a requirement pointer is not a figure), each digit run
    is a figure UNLESS a letter is glued to its front -- N23, y3, p10 and R7 are identifiers, not magnitudes --
    except the multiplication sign of an NxM, where the letter is a standalone x or X after a digit or a space.
    A minus is kept as a sign where it cannot be a range dash: not after a digit, a letter or a closing bracket.
    So "10-15%" reads 10 and 15, "2x18" reads 2 and 18, "x.48" reads .48, and "-1.21" reads -1.21.
    """
    t = _FP_BLANKED.sub("#", _unwrap(str(text or "")))
    out = []
    for m in _FP_DIGITS.finditer(t):
        i, tok = m.start(), m.group()
        c = t[i - 1] if i else ""
        if c.isalpha() or c == "_":
            if not (c in "xX" and (i < 2 or not (t[i - 2].isalpha() or t[i - 2] == "_"))):
                continue
        if c and c in "-\u2212" and (i < 2 or not (t[i - 2].isalnum() or t[i - 2] in ")]%")):
            tok = "-" + tok
        out.append(tok)
    return out


def figure_fingerprint(row):
    """(count, 12-hex digest) of the figures a row PUBLISHES, across FINGERPRINTED_FIELDS.

    `fingerprint_figures` reads each field; the multiset is SORTED, so reordering prose is not a change and a
    reflow cannot move it -- only the numbers themselves are.

    THE FIELDS ARE POOLED, NOT TAGGED. The multiset is the union of the fields' figures, so a figure moving
    between fields with nothing else changing is not a change. It is still a figure the row publishes, which is
    what a signature covers.
    """
    figs = sorted(n for field in FINGERPRINTED_FIELDS for n in fingerprint_figures(row.get(field)))
    return len(figs), hashlib.sha256("|".join(figs).encode("utf-8")).hexdigest()[:12]


def fingerprint_str(row):
    return "%d:%s" % figure_fingerprint(row)


# THE CARRY (owner, 2026-10-19, DECISIONS#signature-carry). A signature carries forward when the only fingerprinted
# field that changed is `value`, and each of its figures equals the figure at the last OWNER signature at the
# precision the row now prints -- or, for a reprint that only adds precision, at the precision the owner signed
# (owner, 2026-11-10, DECISIONS#u17-start). The comparison is always against the owner-signed figures, stored at signature time
# and never updated by a carry, so drift accumulated over several carries lapses. The gate re-fingerprints the row
# and writes the carry to its `history`. Any other fingerprint change lapses as before.
SIGNED_VALUE = "signed_value"     # "<owner_signed>|fig|fig|..." -- `value`'s figures in text order at signature
SIGNED_REST = "signed_rest"       # the count and digest of every OTHER fingerprinted field's figures at signature


def _rest_fingerprint(row):
    figs = sorted(n for field in FINGERPRINTED_FIELDS if field != "value" for n in fingerprint_figures(row.get(field)))
    return "%d:%s" % (len(figs), hashlib.sha256("|".join(figs).encode("utf-8")).hexdigest()[:12])


def signature_snapshot(row):
    """What a row stores when the owner signs it: the fields the carry compares against."""
    return {SIGNED_VALUE: "|".join([str(row.get("owner_signed"))] + fingerprint_figures(row.get("value"))),
            SIGNED_REST: _rest_fingerprint(row)}


def _same_at_print(signed, now):
    """The two are one figure at the coarser of their precisions.

    A coarser or equal reprint: `signed` rounded to the precision `now` prints is `now` (DECISIONS#signature-carry).
    A reprint that only adds precision: `now` rounded to the precision `signed` printed is `signed` (owner,
    2026-11-10, DECISIONS#u17-start). Either way the comparison is against the owner-signed figure.
    """
    s, n = signed.replace(",", ""), now.replace(",", "")
    ds, dn = len(s.partition(".")[2]), len(n.partition(".")[2])
    if (s[0] == "-") != (n[0] == "-"):
        return False
    if dn <= ds:
        return ("%.*f" % (dn, float(s))).lstrip("-") == n.lstrip("-")
    return ("%.*f" % (ds, float(n))).lstrip("-") == s.lstrip("-")


def signature_carry(row):
    """(carried pairs, None) when the row's signature carries; (None, reason) when it lapses."""
    snap_v, snap_r = row.get(SIGNED_VALUE), row.get(SIGNED_REST)
    if not (snap_v and snap_r):
        return None, "no owner-signed figures stored"
    signed_at, _, figs = str(snap_v).partition("|")
    if signed_at != str(row.get("owner_signed")):
        return None, "the stored figures predate the signature of %s" % row.get("owner_signed")
    if _rest_fingerprint(row) != str(snap_r):
        return None, "a fingerprinted field other than value changed"
    old, new = (figs.split("|") if figs else []), fingerprint_figures(row.get("value"))
    if len(old) != len(new):
        return None, "value gained or lost a figure"
    pairs = [(a, b) for a, b in zip(old, new) if a != b]
    for a, b in pairs:
        if not _same_at_print(a, b):
            return None, "value moved %s -> %s against the owner-signed figure" % (a, b)
    return pairs, None


def _write_carry(rid, now, pairs, today):
    """Re-fingerprint `rid` and append the carry to its history, in reference/anchors.yml's text."""
    path = os.path.join(ROOT, REGISTRY)
    with io.open(path, encoding="utf-8") as f:
        s = f.read()
    a = s.index("- anchor_id: %s\n" % rid)
    b = s.find("\n- anchor_id: ", a + 1)
    b = len(s) if b == -1 else b + 1
    block = s[a:b]
    row = yaml.safe_load(block)[0]
    note = ("SIGNATURE CARRIED %s (DECISIONS#signature-carry): value reprinted %s, each equal at the coarser precision "
            "to the figure owner-signed %s." % (today, ", ".join("%s -> %s" % p for p in pairs), row.get("owner_signed")))
    history = ("%s %s" % (row["history"], note)) if row.get("history") else note
    text = yaml.dump({"history": history}, default_style="'", width=115, allow_unicode=True, sort_keys=False)
    text = text.replace("'history':", "  history:", 1)
    text = "\n".join(l if l.startswith("  history:") else "    " + l.lstrip() for l in text.rstrip("\n").split("\n")) + "\n"
    block = re.sub(r"(?m)^  signed_figures: .*$", "  signed_figures: %s" % now, block, count=1)
    m = re.compile(r"(?m)^  history: ").search(block)
    if m:
        k = re.compile(r"(?m)^  [a-z_]+:").search(block, m.end())
        block = block[:m.start()] + text + block[k.start():]
    else:
        k = re.compile(r"(?m)^  [a-z_]+:").search(block, block.index("\n  value: ") + 3)
        block = block[:k.start()] + text + block[k.start():]
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.write(s[:a] + block + s[b:])


def check_signed_figures(rows, write=False, today=None):
    """A signature covers the figures the row published when it was signed.

    DECISIONS#a-moved-figure-clears-the-signature (owner, 2026-09-21): if the set of
    figures a row publishes changes at all -- a value moving, a figure added, a figure
    retired -- the signature LAPSES. That ruling was WORDING, and wording relies on a
    session remembering to diff the row before it commits. THIS IS THE CONTROL. Every
    signed row records `signed_figures` -- the count and a digest of its figure multiset at
    signature time, over every field in FINGERPRINTED_FIELDS -- and the gate recomputes it
    every run.

    It CATCHES; it does not diagnose. The digest cannot say which figure moved. The count
    beside it narrows the question (a changed count is an addition or a retirement, an equal
    count a move) and `git show <base>:reference/anchors.yml` answers the rest. The message
    carries the fingerprint to paste when the change is a genuine re-signature, so the gate
    stays read-only and nothing is computed by hand.

    THE ONE WRITE (owner, 2026-10-19, DECISIONS#signature-carry): a change `signature_carry` admits -- `value` alone,
    each figure equal to the owner-signed one at the precision now printed -- is carried, not lapsed. With `write`
    (the gate's own run, never the self-test) the row is re-fingerprinted and the carry appended to its history.
    Every signed row stores `signature_snapshot`'s two fields at signature; a row missing them, or holding a
    snapshot from before its signature date, fails, so a re-signature cannot leave the comparison pointing at an
    older signature.
    """
    bad, carried = [], []
    for r in rows:
        rid, signed, rec = r.get("anchor_id"), r.get("owner_signed"), r.get(SIGNED_FIGURES)
        if not signed:
            if rec:
                bad.append("%s carries %s but is not signed -- a fingerprint with no signature "
                           "records nothing" % (rid, SIGNED_FIGURES))
            continue
        now = fingerprint_str(r)
        if not rec:
            bad.append("%s is signed %s and carries no %s; set it to %s"
                       % (rid, signed, SIGNED_FIGURES, now))
            continue
        if str(rec) != now:
            pairs, why = signature_carry(r)
            if pairs:
                carried.append("%s: %s, owner-signed %s, fingerprint %s -> %s"
                               % (rid, ", ".join("%s -> %s" % p for p in pairs), signed, rec, now))
                if write:
                    _write_carry(rid, now, pairs, today or str(__import__("datetime").date.today()))
                continue
            bad.append("%s: the figures moved since it was signed %s -- %s published now against %s then (no carry: "
                       "%s). Re-sign it and set %s to %s, or restore the figures."
                       % (rid, signed, now.split(":")[0], str(rec).split(":")[0], why, SIGNED_FIGURES, now))
            continue
        snap = signature_snapshot(r)
        if str(r.get(SIGNED_VALUE)).partition("|")[0] != str(signed) or not r.get(SIGNED_REST):
            bad.append("%s is signed %s and stores no owner-signed figures from that signature; set %s to %r and "
                       "%s to %s" % (rid, signed, SIGNED_VALUE, snap[SIGNED_VALUE], SIGNED_REST, snap[SIGNED_REST]))
    report(BLOCK, "a signed row still publishes the figures it was signed on", bad)
    report(INFO, "signatures carried forward: value reprinted at a coarser or finer precision "
                 "(DECISIONS#signature-carry, #u17-start)",
           carried)


# THE HISTORY BRIDGE RETIRED WITH THE MOVE (owner, 2026-09-25: "it retires with the move"; moved 2026-09-29,
# DECISIONS#history-move). It found sentences carrying a history word and a figure, so the move knew what to take;
# it over-read (a formula's "while the cost was live") and under-read (a wordless "55 / 50 / 47 -> 55 / 52 / 49"),
# and a word pattern is the kind of check this package retires. What it protected is now structural: a row's
# retired figures sit in `history`, which the fingerprint, the figure checks and the constants check do not read.


def check_survivability_flag(rows):
    """A10.01 says the gate prints the flagged metric set. This is that print.

    The row's claim is only true if something prints it; a row asserting a
    mechanism nobody implemented is the defect this package keeps finding.
    """
    flagged = sorted(r["anchor_id"] for r in rows if r.get("survivability_metric"))
    report(INFO, "survivability_metric set (A10.01's enumeration, read from the flag)",
           ["%d rows: %s" % (len(flagged), ", ".join(flagged))] if flagged else
           ["no row carries survivability_metric -- A10.01's set is empty"])


# The closed-form probability surface of the generators, enumerated rather than counted
# (DECISIONS 2026-09-06, assert-the-list-never-the-count). DECISIONS#closed-form-carries-a-draw
# says every one of these carries a draw; this list is what makes that a CHECK and not a note.
# A form added to a generator without a case here is named by the gate, by name, every run.
CLOSED_FORM_SURFACE = {
    "group10_floors.quarter_risk": "the quarter mean, a named pair, and any adjacent pair in a year",
    "group10_floors.below_floor": "a log-normal tail at a stated ARITHMETIC mean",
    "group11_compliance.recall_odds": "at least one recall in a three-year window",
    # ---- NOT YET COVERED. Each needs its own derivation before a draw can be trusted to
    # judge it, and the reason is written down so a later session does not re-discover it:
    "group10_floors.floor_crossings": "the authorized-only conditional -- a CONTINUUM quantile "
                                      "argument applied at 39 SKUs, so a finite-N draw and the "
                                      "form may differ for a reason that is not a defect",
    "group10_floors.top_dollar_share": "the MIXTURE's top-q Lorenz share, the count cut and the dollars "
                                       "above it -- it replaced Phi(sigma - Phi^-1(1 - q)) when the draw "
                                       "caught that form understating concentration (ruled 2026-09-21)",
    "group10_floors.noncompliant_share": "P(late or short) on three readings of an unregistered overlap",
    "group10_floors.late_days": "a geometric truncated at A5.07's cancel cap, per account at A10.11's means",
    "group11_compliance.accept_weight": "selection on a forecast carrying sigma_pred's error, and "
                                        "cut_log's marginal identity with it",
    "group11_compliance.tercile_ratio": "top-tercile over bottom-tercile MEAN of a log-normal",
}


CLOSED_FORM_SEED = 20260921
CLOSED_FORM_SIGMAS = 4.0


def _closed_form_cases():
    """Every closed-form probability in the generators, with a draw of its own mechanism.

    A case is (name, [(outcome label, what the closed form claims), ...], a one-trial draw
    returning one number per outcome, trials). The closed form claims the MEAN of each
    outcome, so an indicator tests a probability and a value tests a parameterisation with
    the same machinery.

    THE DRAW IS BUILT FROM THE MECHANISM, NEVER FROM THE FORM. quarter_risk is simulated
    from twelve MONTHLY draws, so one case proves the sd / sqrt(3) quarter mean and the
    adjacency counting together instead of assuming the first in order to test the second.

    Parameters are the registered call sites wherever the draw can resolve them, plus one
    deliberately high-probability point for quarter_risk, because a wrong adjacency form and
    a right one converge as p -> 0 and separate as p -> 1/2. THAT POINT IS A TEST PARAMETER
    AND NOT A REGISTERED MAGNITUDE; nothing in the package reads it.
    """
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import group10_floors as F
    import group11_compliance as L
    cases = []

    def quarters(rng, mean, sd, line):
        return [sum(rng.gauss(mean, sd) for _ in range(3)) / 3.0 < line for _ in range(4)]

    def quarter_case(label, mean, sd, line, n):
        p, pair, year = F.quarter_risk(mean, sd, line)

        def draw(rng, mean=mean, sd=sd, line=line):
            q = quarters(rng, mean, sd, line)
            return (q[0], q[0] and q[1], any(q[i] and q[i + 1] for i in range(3)))

        return ("group10_floors.quarter_risk, %s" % label,
                [("one quarter below the line", p), ("a named adjacent pair", pair),
                 ("any adjacent pair in the year", year)], draw, n)

    cases.append(quarter_case("A10.03's on-time line, y3", F.ONTIME[2], F.SD_ONTIME, 80.0, 120000))
    # The line put AT the mean, so p is one half and the retired form stands 7.8 points away
    # from this one. At A10.03's own y1 the two agree to five decimals -- a call site is not
    # by itself a test of the form it calls.
    cases.append(quarter_case("the line at the mean (a test point, not a registered figure)",
                              F.ONTIME[2], F.SD_ONTIME, F.ONTIME[2], 60000))

    def floor_case(label, mean, floor, sigma, n):
        closed = F.below_floor(mean, floor, sigma)
        mu = math.log(mean) - sigma ** 2 / 2

        def draw(rng, mu=mu, sigma=sigma, floor=floor):
            x = rng.lognormvariate(mu, sigma)
            return (x < floor, x)

        # The second outcome is the parameterisation, not the tail: below_floor claims a
        # log-normal whose ARITHMETIC mean is `mean`, and reading that as the median is the
        # standing way to get this function wrong. The draw measures the mean and says so.
        return ("group10_floors.below_floor, %s" % label,
                [("share below the floor", closed), ("the arithmetic mean it claims", mean)], draw, n)

    for t_ in range(3):
        cases.append(floor_case("Kroger's floor, y%d" % (t_ + 1), F.VELOCITY_INDEX[t_],
                                F.VELOCITY_FLOOR["Kroger"], F.SIGMA_VELOCITY, 150000))
    cases.append(floor_case("UNFI's y3 viability ratio", 1.0,
                            F.viability_crossings(2)["UNFI"]["ratio"], F.SIGMA_VELOCITY, 150000))

    # A10.17's amount MIXTURE, the form the draw corrected on 2026-09-21. One draw of X serves
    # all three years: for each filed q, the count share and the dollar share on the far side of
    # that year's cut, which together test the quantile solve and the conditional-mean formula.
    # BOTH ARE ASSERTED BELOW THE CUT, and that is not a presentation choice: X*1{X <= cut} is
    # bounded by the cut while X*1{X > cut} carries the whole tail, so the below-cut estimator
    # has a third of the standard deviation and needs an EIGHTH of the draws for the same
    # discrimination (sd 0.525 against 1.484 at y1). Same claim, read from the other side.
    # The mixture's own mean rides along: the shares divide by it, so a wrong mean would cancel
    # out of them, and only a direct outcome can see it.
    M = F.deduction_mixture()
    qs = F.filing_cascade()["by_count"]
    cuts = [F._mixture_quantile(M["parts"], 1 - q) for q in qs]
    shares = [F.top_dollar_share(q, M) for q in qs]
    cum, acc = [], 0.0
    for _, w, _, _, _, _ in M["parts"]:
        acc += w
        cum.append(acc)

    def mix_draw(rng, parts=M["parts"], cum=cum, acc=acc, cuts=cuts, mean=M["mean"]):
        u = rng.random() * acc
        i = min(j for j, c in enumerate(cum) if u <= c)
        _, _, mu, sg, _, _ = parts[i]
        x = math.exp(mu + sg * rng.gauss(0, 1))
        out = []
        for c in cuts:
            out.append(x <= c)
            out.append(x / mean if x <= c else 0.0)
        out.append(x / mean)
        return tuple(out)

    outcomes = []
    for t_ in range(3):
        outcomes.append(("y%d count share BELOW the cut" % (t_ + 1), 1 - qs[t_]))
        outcomes.append(("y%d dollars BELOW the cut, share of the mean" % (t_ + 1), 1 - shares[t_]))
    outcomes.append(("the mixture's own mean, over itself", 1.0))
    # 300,000 puts the retired single-log-normal form 1.7x to 2.1x outside the band in every
    # year; at 100,000 y1 would only just fire, and y1 is the arm with the smallest error.
    cases.append(("group10_floors.top_dollar_share, A10.17's amount mixture at the filed q",
                  outcomes, mix_draw, 300000))

    rate = L.recall_odds()["mean"]

    def recall_draw(rng, rate=rate):
        return (any(rng.random() < rate for _ in range(3)),)

    cases.append(("group11_compliance.recall_odds, the three-year window",
                  [("at least one recall in the window", L.recall_odds()["window"])], recall_draw, 600000))
    return cases


def check_closed_forms(cases=None):
    """A closed-form probability is a claim nobody in this package has been asked to check.

    FAILURES / DECISIONS#closed-form-carries-a-draw, 2026-09-21: quarter_risk read the year
    risk as 1 - (1 - p^2)^3, which treats (Q1,Q2), (Q2,Q3) and (Q3,Q4) as independent when Q2
    and Q3 each sit in two of them. A10.03 is watched and its figure check PASSED, because the
    row had been written from the generator's output. Every other check here verifies agreement
    between two artefacts; none of them can see a formula that is simply wrong. Agreement
    between a formula and a draw is evidence of a different kind.

    Each outcome is compared against the draw's own CLOSED_FORM_SIGMAS-sigma band. The seed is
    fixed, so a run is reproducible and the check cannot flake. For an indicator the band is
    floored at sqrt(k + 1) / n, so a case that never fires still has a width -- and a form
    below that width is reported UNRESOLVED rather than passed, because a draw that cannot see
    a quantity has not testified about it.
    """
    bad, unresolved = [], []
    table = cases if cases is not None else _closed_form_cases()
    for name, outcomes, draw, n in table:
        rng = random.Random(CLOSED_FORM_SEED)
        k = len(outcomes)
        tot, sq, binary = [0.0] * k, [0.0] * k, [True] * k
        for _ in range(n):
            for j, x in enumerate(draw(rng)):
                x = float(x)
                tot[j] += x
                sq[j] += x * x
                if x not in (0.0, 1.0):
                    binary[j] = False
        for j, (label, closed) in enumerate(outcomes):
            m = tot[j] / n
            se = math.sqrt(max(sq[j] / n - m * m, 0.0) / n)
            if binary[j]:
                se = max(se, math.sqrt(tot[j] + 1.0) / n)
            band = CLOSED_FORM_SIGMAS * se
            if abs(closed) < band and abs(m) < band:
                unresolved.append("%s -- %s: the form gives %.3e, under the draw's own width %.3e at %d "
                                  "trials; the draw cannot testify either way" % (name, label, closed, band, n))
            elif abs(closed - m) > band:
                bad.append("%s -- %s: the closed form gives %.6f; %d trials of the mechanism give %.6f, "
                           "outside the draw's own %.0f-sigma band of %.6f"
                           % (name, label, closed, n, m, CLOSED_FORM_SIGMAS, band))
    report(BLOCK, "closed forms agree with a draw of their mechanism", bad)
    report(INFO, "closed forms the draw cannot resolve", unresolved)
    # The rule is a CHECK, not a note: the surface is enumerated above, and a form on it with
    # no case here is named every run until it has one. Driven off `cases` and not off
    # `cases is None`, so the self-test can hand it a short list and watch it fire.
    covered = set(n.split(",")[0].strip() for n, _, _, _ in table)
    report(WARN, "every closed form carries a draw",
           ["%s -- %s" % (k, CLOSED_FORM_SURFACE[k])
            for k in sorted(CLOSED_FORM_SURFACE) if k not in covered])


EQUITY_CALL_CHECK = "the equity call finances the y3 funding gap"
SMALL_CHANNEL_CHECK = "the small-account channel is inside the wholesale roll-up"


def check_small_channel(share=None):
    """The small-account tier is a channel, not a retailer (owner, 2026-10-09; DECISIONS#u10-restatement), so its
    revenue reaches the figures that include it -- A1.01's ladder, A1.02, A5.38's denominator, the ledger -- only
    through group 9's wholesale line. This fires if the tier's share is missing or zero in any window year, if its
    dollars are not positive, or if A5.38's shares stop summing to the whole wholesale line, which is how a tier
    dropped from the roll-up would show. `share` replaces group 9's SHARE -- the self-test's doctored copies."""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import group9_ledger as G
    share = G.SHARE if share is None else share
    bad = []
    years = range(len(G.GROSS))
    if "small" not in share:
        bad.append("A5.38's shares carry no small-account tier: its revenue is absent from the wholesale roll-up")
    for t in years:
        s = share.get("small", [0] * len(G.GROSS))[t]
        if s <= 0:
            bad.append("y%d: the small-account tier's share is %s -- the channel is empty" % (t + 1, s))
        total = sum(v[t] for v in share.values())
        if abs(total - 100) > 1e-9:
            bad.append("y%d: A5.38's shares sum to %s, not 100 -- a channel is missing from the wholesale roll-up"
                       % (t + 1, total))
        if s > 0 and not G.GROSS[t] * (1 - G.S_DTC) * s / 100.0 * 1e6 > 0:
            bad.append("y%d: the small-account tier's dollars are not positive" % (t + 1))
    report(BLOCK, SMALL_CHANNEL_CHECK, bad)


SLOTTING_GUARD_CHECK = "slotting stays outside A4.05's types and A4.01's and A4.14's rates"


def check_slotting_outside_rates(types=None, pnl=None):
    """A4.05 and A4.14 exclude slotting by rule, so A4.29's deducted share is a `slotting` row outside A4.05's ten and
    outside A4.01's and A4.14's denominators (owner, 2026-10-14, DECISIONS#u18-rulings Q5): a slotting dollar inside
    either rate moves a first-order rate for the wrong reason. This fires if A4.05's type mix carries slotting, or if
    group 9's net revenue does not equal gross less A4.14's trade, A4.01's deductions and the settlement overage, with
    slotting's deducted share and free-fill taken off separately -- i.e. if either rate absorbed a slotting dollar.
    `types` replaces group 10's A4.05 shares and `pnl` group 9's P&L -- the self-test's doctored copies."""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import group9_ledger as G
    import group10_floors as F
    types = F.A405_SHARE if types is None else types
    P = G.pnl() if pnl is None else pnl
    bad = []
    if any("slotting" in k for k in types):
        bad.append("A4.05's type mix carries slotting: A4.01's deduction rate would count A4.29's deducted share")
    for t in range(3):
        S = P["slotting"][t]
        rates_only = G.GROSS[t] * (1 - G.TRADE - G.OPDED[t]) - P["over"][t]
        if abs(P["net"][t] + S["deducted"] + S["free_fill"] - rates_only) > 1e-9:
            bad.append("y%d: net revenue is not gross less A4.14's and A4.01's rates and the overage, with slotting off "
                       "separately -- a rate absorbed slotting dollars" % (t + 1))
    report(BLOCK, SLOTTING_GUARD_CHECK, bad)


CARD_NETWORK_CHECK = "no card-network program reaches its floor at any corner of A8.21's band"


def check_card_network_floors(floors=None):
    """The own-site channel has no network episode in the window (A8.03), and the margin is a near-miss: VDMP's most
    Visa disputes in a month is 92.4 against 100 at the 65% corner (owner, 2026-10-13, DECISIONS#u18-rulings Q2).
    A later move that pushed a peak past a floor would put a network episode nobody wrote into the data, so this
    runs group 8's network test on A8.03's drift at every corner of A8.21's band and fires if VDMP or ECM fires, if
    VDMP's count or ECM's ratio reaches its floor, or if VAMP's disputes reach its count. `floors` replaces group 8's
    (VDMP count, ECM ratio, VAMP count) -- the self-test's lowered copies."""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import group8_dtc as D
    vdmp_n, ecm_r, vamp_n = floors or (D.VDMP["count"], D.ECM["ratio"], D.VAMP_COUNT)
    bad = []
    for visa, res in sorted(D.corners().items()):
        at = "Visa %.0f%%" % (visa * 100)
        if res["vdmp"] or res["visa_max"]["count"] >= vdmp_n:
            bad.append("%s: VDMP sees %.1f Visa disputes in a month against its floor of %s" % (at, res["visa_max"]["count"], vdmp_n))
        if res["ecm"] or res["mc_max"]["ratio"] >= ecm_r:
            bad.append("%s: ECM's ratio reaches %.2f%% against %.2f%%" % (at, res["mc_max"]["ratio"] * 100, ecm_r * 100))
        if res["vamp_disputes_max"] >= vamp_n:
            bad.append("%s: VAMP sees %.1f disputes against its %s" % (at, res["vamp_disputes_max"], vamp_n))
    report(BLOCK, CARD_NETWORK_CHECK, bad)


def check_equity_call(index):
    """A10.19's REGISTERED size funds what it was registered for (U8, owner, 2026-10-06; on U16's daily ledger,
    2026-10-22, DECISIONS#u16-daily-ledger).

    The size is read from the row as printed, never from the generator, and run through the daily ledger: from its
    derived date and from the counterfactual's, availability net of any supplier stretch must hold A9.14's y3
    springing trigger to 31 December y3, and the counterfactual must leave the window no hold. A row that prints a
    smaller call than the window needs fails here, whatever the generator would compute. The row and group 10's doc
    name the date group 10 derives. August 1 y3 and April 1 y3, retired 2026-10-22, are not checked.
    """
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import group9_ledger as G
    import group10_floors as F
    bad = []
    m = re.search(r"\$([\d.]+)M at the signed D0", " ".join(norm(index["A10.19"]["value"]).split()))
    if not m:
        report(BLOCK, EQUITY_CALL_CHECK, ["A10.19 no longer prints its size at the signed D0 -- the check cannot read it"])
        return
    size = float(m.group(1))
    # the print is a ceiling (owner, 2026-10-27, DECISIONS#u14): the first three-figure amount at or above the bisected
    # size -- not the nearest, which can fall short, and not a cent more
    need = F.call_size(F.CALL_DATE)
    if abs(size - F.note(need)) > 1e-9:
        bad.append("A10.19 prints $%.2fM; the first three-figure amount at or above its bisected $%.4fM is $%.2fM"
                   % (size, need, F.note(need)))
    date = "DATE: %s" % _dated(F.CALL_DATE)
    for where, text in (("A10.19", index["A10.19"]["value"]), (GROUP10_DOC, rd(GROUP10_DOC))):
        if date not in " ".join(norm(text).split()).replace("**", ""):
            bad.append("%s does not say %r -- group 10 dates the call to %s" % (where, date, F.CALL_DATE))
    trig = max(G.SPRING_PCT * G.COMMITMENT[2], G.AVAIL_HARD)
    cf = F.counterfactual_date()
    for when, what in ((F.CALL_DATE, "its derived date"), (cf, "the counterfactual's")):
        L = G.daily_ledger(call=(size, when))
        tight = F._tightest(L, when)
        if tight < trig - 1e-9:
            bad.append("A10.19's $%.2fM on %s, %s, leaves %.3f against the %.2f trigger -- the call does not finance "
                       "the window" % (size, when, what, tight, trig))
        if when == cf and F.holds(L):
            bad.append("A10.19's counterfactual on %s leaves a hold on %s" % (cf, F.holds(L)[0]))
    report(BLOCK, EQUITY_CALL_CHECK, bad)


DAILY_FLOWS_CHECK = "the daily ledger's flows reconcile to ledger()'s at $1K"
DAILY_BEFORE_NOTE_CHECK = "every daily balance before A10.19's note is the line's own, bit for bit"
DAILY_SAWTOOTH_CHECK = "the daily ledger pays on the AP runs, and its largest outflows fall there"
DAILY_PART_HELD_CHECK = "a part-held run holds the newest invoices and only when the line is spent"
DAILY_TOLERANCE = 0.001        # U18's fifth input (owner-signed 2026-10-20): $1K, the printed precision


def check_daily_flows(L=None):
    """The daily ledger's annual flows are ledger()'s (U18's fifth input; flows only, owner, 2026-10-21): EBITDA and
    capex in every window year within $1K. Distributions are zero in both: the daily ledger raises on a positive
    pre-tax year, because no row registers a distribution date. Balances are not compared: Dec 31 is the daily
    ledger's position, and ledger()'s year-end figures are annual means."""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import group9_ledger as G
    L = _pv("the daily ledger on the line's own cash") if L is None else L
    ebitda = _pv("EBITDA, $M")
    bad = []
    for t in range(3):
        for what, daily, annual in (("EBITDA", L["eb"][t], ebitda[t]), ("capex", L["capex"][t], G.CAPEX)):
            if abs(daily - annual) > DAILY_TOLERANCE:
                bad.append("y%d %s: the daily ledger sums %.4f, ledger() %.4f -- %.1fK apart, past the $1K tolerance"
                           % (t + 1, what, daily, annual, abs(daily - annual) * 1000))
    report(BLOCK, DAILY_FLOWS_CHECK, bad)


def check_daily_before_note(pairs=None):
    """Every daily balance before A10.19's note is identical, bit for bit, with and without it (FAILURES 2026-10-07):
    the note moves nothing it has not yet paid. Read on its derived date and on the counterfactual's. `pairs` is
    [(without, with, date)], the self-test's doctored ledgers."""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import group10_floors as F
    if pairs is None:
        E, Q = F.equity_call(), F.equity_call(when=F.counterfactual_date())
        pairs = [(E["before"], E["after"], E["date"]), (Q["before"], Q["after"], Q["date"])]
    bad = []
    for base, noted, when in pairs:
        for k, d in enumerate(base["day"]):
            if d >= when or len(bad) >= 5:
                break
            for series in ("draw", "late", "ap", "avail"):
                if base[series][k] != noted[series][k]:
                    bad.append("%s on %s: %r without the note, %r with it, before the note lands on %s"
                               % (series, d, base[series][k], noted[series][k], when))
                    break
    report(BLOCK, DAILY_BEFORE_NOTE_CHECK, bad)


AP_SCHEDULE_CHECK = "group 9's doc prints the AP-run schedule the daily ledger pays"


def check_ap_schedule(doc=None):
    """The AP-run schedule U15's seeders read is a printed output (U16): group 9's sourcing doc carries, between its
    markers, exactly the table group10_floors.ap_schedule_table() renders -- read since U21 from group 9's outputs(),
    the schedule the seeders import, in the table's own form."""
    doc = rd(GROUP9_DOC) if doc is None else doc
    rows = ["| run | due $K | paid $K | held $K |", "|---|---|---|---|"]
    for r in _pv("the AP-run schedule, A10.19's note in it, $M"):
        rows.append("| %s | %.0f | %.0f | %.0f |" % (r["day"], r["due"] * 1000, r["paid"] * 1000, r["held"] * 1000))
    m = re.search(r"<!-- ap-schedule:start -->\n(.*?)\n<!-- ap-schedule:end -->", doc, re.S)
    bad = []
    if not m:
        bad.append("%s carries no AP-run schedule between its markers" % GROUP9_DOC)
    else:
        want, got = rows, m.group(1).split("\n")
        diff = [(w, g) for w, g in zip(want, got) if w != g]
        if len(want) != len(got) or diff:
            bad.append("%s's AP-run schedule: %d rows against the generator's %d; first difference %r, generator %r"
                       % (GROUP9_DOC, len(got), len(want), diff[0][1] if diff else None, diff[0][0] if diff else None))
    report(BLOCK, AP_SCHEDULE_CHECK, bad)


PACKET_DOC = "docs/anchors/FIRST-ORDER-PACKET.md"
PNL_FOOTS_CHECK = "every printed P&L bridge subtracts to its own totals at printed precision (DECISIONS#u17-start)"
_PNL_NUM = r"(−?-?[\d,]+\.\d+)"
_PNL_LINES = {
    # group 9's fenced block: two-space lines are the chain, four-space lines the detail an "= opex" line totals
    GROUP9_DOC: re.compile(r"^(  |    )(?=\S)([−=]?) *(\S.*?)\s+" + r"\s+".join([_PNL_NUM] * 3) + r"(?:\s|$)"),
    # the packet's EBITDA table: every line is the chain
    PACKET_DOC: re.compile(r"^\| ()([−=]?) *([^|]+?) \| " + r" \| ".join([_PNL_NUM] * 3) + r" \|\s*$"),
}


def _pnl_blocks(path, text):
    """The P&L bridges a document prints, each a list of (detail, sign, label, values, places). Group 9's is the fenced
    block that opens on gross invoiced; the packet's is the table under its EBITDA heading."""
    if path == GROUP9_DOC:
        m = re.search(r"```\n( +y1 +y2 +y3\n  gross invoiced.*?)\n```", text, re.S)
    else:
        m = re.search(r"\n## 13\. EBITDA\n\n(.*?)\n\n", text, re.S)
    if not m:
        return None
    out, lines = [], m.group(1).split("\n")
    for i, line in enumerate(lines):
        g = _PNL_LINES[path].match(line)
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if not g and line.strip() and len(nxt) - len(nxt.lstrip()) > len(line) - len(line.lstrip()):
            g = _PNL_LINES[path].match(line + " " + nxt.lstrip())     # a label wrapped onto a deeper line
        if g:
            vals = [g.group(k).replace("−", "-").replace(",", "") for k in (4, 5, 6)]
            out.append((g.group(1) == "    ", g.group(2), g.group(3).strip(), [float(v) for v in vals],
                        max(len(v.partition(".")[2]) for v in vals)))
    return out


def check_pnl_foots(texts=None):
    """Each printed P&L bridge subtracts to its own totals (owner, 2026-11-11, DECISIONS#u17-start: the packet's
    EBITDA table printed gross profit, opex and EBITDA with the two lines between them missing). Down the chain, an
    unsigned first line opens it, a "−" line subtracts, and an "=" line is a total the lines since the last total must
    reach; the chain resumes from the printed total. An "=" line under detail lines totals the detail and is itself
    subtracted. A total and its k lines are each rounded to the printed place, so they may differ by up to (k + 1)
    half-units of it and no more; anything wider is a missing or wrong line, not rounding."""
    texts = dict((p, rd(p)) for p in (GROUP9_DOC, PACKET_DOC)) if texts is None else texts
    bad = []
    for path, text in sorted(texts.items()):
        block = _pnl_blocks(path, text)
        if not block or block[0][1] or len(block) < 3:
            bad.append("%s: no P&L bridge found where the check reads it" % path)
            continue
        run, k, detail = list(block[0][3]), 0, []
        for is_detail, sign, label, vals, places in block[1:]:
            if is_detail:
                detail.append((vals, places))
                continue
            half = 0.5 * 10 ** -places
            if sign == "=" and detail:
                for y in range(3):
                    s = sum(d[0][y] for d in detail)
                    if abs(s - vals[y]) > (len(detail) + 1) * half + 1e-9:
                        bad.append("%s: %r y%d prints %.*f; its %d detail lines sum to %.*f"
                                   % (path, label, y + 1, places, vals[y], len(detail), places, s))
                detail = []
                run = [run[y] - vals[y] for y in range(3)]
                k += 1
            elif sign == "=":
                for y in range(3):
                    if abs(run[y] - vals[y]) > (k + 1) * half + 1e-9:
                        bad.append("%s: %r y%d prints %.*f; the %d lines above it give %.*f, a gap of %.*f"
                                   % (path, label, y + 1, places, vals[y], k, places, run[y], places, run[y] - vals[y]))
                run, k = list(vals), 0
            elif sign == "−":
                run = [run[y] - vals[y] for y in range(3)]
                k += 1
            else:
                bad.append("%s: %r carries no sign inside the bridge" % (path, label))
        if k:
            bad.append("%s: the bridge ends on %d lines no total reaches" % (path, k))
    report(BLOCK, PNL_FOOTS_CHECK, bad)


PACKET_FIGURES_CHECK = "the owner's review packet prints only what its rows and the generators print (DECISIONS#u17-start)"
PACKET_PAGES = ("A1.01 A1.02 A8.01 A5.38 A1.05 A3.04 A3.02 A4.14 A4.01 A4.02 A4.07 "
                "A9.11 A9.02 A9.14 A10.19 A5.11 A9.04").split()          # page n is R16's row n, in the packet's order
# A figure a page takes from somewhere other than its own row, with that source: another row (its figures and its
# outputs()), or a row's section of the desk-review record. Each is checked against its source, not waved through.
PACKET_CREDITS = {
    "A1.02": [("desk", "A1.02", "26.5 15.2 19.4 39.2 28.5 25.3"),           # the comparables' growth
              ("row", "A9.02", "34 50 103 172"), ("desk", "A9.02", "472 759")],   # and their scale
    "A8.01": [("desk", "A8.01", "8.2")],                                      # the association's e-commerce share
    "A5.38": [("row", "A1.01", "47")],                                        # "$25-47M", a check question
    "A1.05": [("desk", "A1.05", "12.6")],                                     # the club figure the desk corrected
    "A3.04": [("desk", "A3.04", "22 20 13.6")],                               # the distributor-margin finding
    "A9.02": [("row", "A1.01", "33")],                                        # "$33-47M", a check question
    "A9.04": [("row", "A9.01", "20 49"), ("row", "A1.01", "33")],             # the non-production subset; BLS's class
}
_PACKET_STRUCTURE = re.compile(r"\[[^\]]*\]\([^)]*\)|\b[Yy]ears? \d( / \d)*\b|\b(?:19|20)\d\d\b|\bpages? \d+\b")


def _packet_pages(text):
    """Page body by number, from the packet's "## n. Title" headings; the heading line itself is not a figure."""
    parts = re.split(r"\n## (\d+)\. [^\n]*\n", text)
    return dict((int(parts[k]), parts[k + 1].split("\n## ")[0]) for k in range(1, len(parts) - 1, 2))


def _packet_pool(index, anchor, desk=False):
    """The figures a source prints: a row's fingerprinted fields and every value outputs() prints under it, or the
    row's section of the desk-review record."""
    if desk:
        out = []
        for m in re.finditer(r"\n### ([^\n]*)\n(.*?)(?=\n##)", rd(TIER_A_RECORD), re.S):
            if re.search(r"\b%s\b" % re.escape(anchor), m.group(1)):
                out += [x for x, _ in _figures_as_numbers(m.group(2))]
        return out
    out = [x for x, _ in _printed_figures(index[anchor])[1]]

    def flat(v):
        if isinstance(v, bool):
            return
        if isinstance(v, (int, float)):
            out.append(float(v))
        elif isinstance(v, dict):
            for x in v.values():
                flat(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                flat(x)
    for _, a, v in _printed().values():
        if a == anchor:
            flat(v)
    return out


def _in_pool(tok, pool):
    """At the packet's printed precision -- within half a unit of the last printed place, so a tie prints either way
    (32.5 as 33) -- as printed or as a fraction printed as a percent."""
    t = tok.replace(",", "")
    half = 0.5 * 10 ** -len(t.partition(".")[2])
    w = float(t)
    return any(abs(x * s - w) <= half + 1e-9 for x in pool for s in (1, 100))


def packet_outputs_digest(anchor):
    """12 hex of everything outputs() prints under `anchor`, label by label: the generator half of what a page was
    prepared against."""
    import json
    import hashlib
    items = sorted((label, v) for label, (_, a, v) in _printed().items() if a == anchor)
    blob = json.dumps(items, default=_encode, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12] if items else "none"


def _packet_pins(text):
    """The packet's "Prepared against" table: page -> (anchor, fingerprint, outputs digest)."""
    out = {}
    for m in re.finditer(r"^\| (\d+) \| (A\d+\.\d+) \| [^|]* \| `(\d+:[0-9a-f]{12})` \| `([0-9a-f]{12}|none)` \|", text,
                         re.M):
        out[int(m.group(1))] = (m.group(2), m.group(3), m.group(4))
    return out


def check_packet_figures(index, text=None, credits=None):
    """The packet the owner signs from is a watched document (owner, 2026-11-11, DECISIONS#u17-start): row 13 lost
    two lines in copying and nothing read it. Every figure on page n, at the precision the page prints it, equals a
    figure row n's fingerprinted fields print or a value outputs() prints under row n, read as printed or as a
    fraction printed as a percent; or it is one of PACKET_CREDITS, checked against the source named there. Year
    labels, calendar years, page references and links are structure, not figures.

    Membership, not position: a figure moved onto another figure its row prints passes (114 of 428 one-unit moves
    did, 2026-11-11, mostly small integers). So the packet is also PINNED: its "Prepared against" table names, page
    by page, the row's fingerprint and the digest of what outputs() prints under the row when the page was last
    checked, and the gate blocks when either has moved. A row or a generator that moves under a page makes the
    page stale, whatever its figures happen to match; re-check the page, then re-pin it. Page 13's bridge is
    pinned by check_pnl_foots besides."""
    text = rd(PACKET_DOC) if text is None else text
    pages = _packet_pages(text)
    bad = []
    pins = _packet_pins(text)
    for n, anchor in enumerate(PACKET_PAGES, 1):
        pin = pins.get(n)
        now = (anchor, fingerprint_str(index[anchor]), packet_outputs_digest(anchor))
        if pin is None:
            bad.append("page %d (%s): no row in the packet's Prepared-against table" % (n, anchor))
        elif pin != now:
            bad.append("page %d (%s) was prepared against %s, outputs %s; the row is now %s, outputs %s: re-check "
                       "the page, then re-pin it" % (n, anchor, pin[1], pin[2], now[1], now[2]))
    if sorted(pages) != list(range(1, len(PACKET_PAGES) + 1)) or set(PACKET_PAGES) != U14_FIRST_ORDER:
        bad.append("%s's pages are %s; the check reads %d, one per first-order row"
                   % (PACKET_DOC, sorted(pages), len(PACKET_PAGES)))
    for n, anchor in enumerate(PACKET_PAGES, 1):
        if n not in pages:
            continue
        own = _packet_pool(index, anchor)
        credited = {}
        for kind, src, toks in (PACKET_CREDITS if credits is None else credits).get(anchor, []):
            pool = _packet_pool(index, src, desk=kind == "desk")
            for tok in toks.split():
                if not _in_pool(tok, pool):
                    bad.append("page %d (%s): the credit %s is not in %s's %s" % (n, anchor, tok, src,
                                                                             "desk record" if kind == "desk" else "row"))
                credited[tok] = src
        for tok in fingerprint_figures(_PACKET_STRUCTURE.sub(" ", pages[n])):
            if not _in_pool(tok, own) and tok.lstrip("-") not in credited:
                bad.append("page %d (%s) prints %s; neither the row, its outputs, nor a credit carries it"
                           % (n, anchor, tok))
    report(BLOCK, PACKET_FIGURES_CHECK, bad)


def check_daily_sawtooth(L=None):
    """A9.12's sawtooth (U16): payments leave on the AP runs A9.11 registers, the 1st and 16th, one run each, and every
    invoice is scheduled to the run nearest its DPO day; each year's largest daily outflow falls on a run day and
    exceeds every other day's. A ledger that spreads the year's flows evenly has no such day, and fails."""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import group9_ledger as G
    L = _pv("the daily ledger on the line's own cash") if L is None else L
    bad = []
    runs = [r["day"] for r in L["run_detail"]]
    want = [datetime.date(y, m, n) for y in (2023, 2024, 2025) for m in range(1, 13) for n in G.AP_RUN_DAYS]
    if runs != want:
        bad.append("the runs paid are %d, not the %d the 1st and 16th give; first stray %s"
                   % (len(runs), len(want), next((r for r, w in zip(runs, want) if r != w), None)))
    d = datetime.date(2023, 1, 1)
    while d < datetime.date(2026, 1, 1):
        due = d + datetime.timedelta(G.DPO)
        run = G._ap_run(due)
        near = min(abs(n) for n in range(-16, 17) if (due + datetime.timedelta(n)).day in G.AP_RUN_DAYS)
        if run.day not in G.AP_RUN_DAYS or abs((run - due).days) != near:
            bad.append("an invoice of %s is scheduled to %s, not the run nearest its DPO day %s" % (d, run, due))
            break
        d += datetime.timedelta(1)
    for t in range(3):
        ks = [k for k, x in enumerate(L["day"]) if x.year == 2023 + t and k]
        out = [(L["draw"][k] - L["draw"][k - 1], L["day"][k]) for k in ks]
        on = max(v for v, x in out if x.day in G.AP_RUN_DAYS)
        off = max(v for v, x in out if x.day not in G.AP_RUN_DAYS)
        if not on > off + 1e-9:
            bad.append("y%d's largest outflow on a run day is %.4f, against %.4f on another day -- no sawtooth"
                       % (t + 1, on, off))
    report(BLOCK, DAILY_SAWTOOTH_CHECK, bad)


def check_daily_part_held(L=None, noted=None):
    """A part-held run (U18's third input: the oldest paid first) holds only invoices at least as new as every
    invoice it paid in full, and holds only when the line is spent; with A10.19's note, every held invoice is paid by
    31 December y3, by a dated collection or by the note."""
    L = _pv("the daily ledger on the line's own cash") if L is None else L
    noted = _pv("the daily ledger, A10.19's note in it") if noted is None else noted
    bad = []
    for r in L["run_detail"]:
        if r["held"] <= 1e-9:
            continue
        if r["newest_paid"] is not None and r["newest_paid"] > r["oldest_held"]:
            bad.append("the %s run paid an invoice of %s in full and held one of %s -- not oldest first"
                       % (r["day"], r["newest_paid"], r["oldest_held"]))
        if r["room"] > DAILY_TOLERANCE:
            bad.append("the %s run held %.4f with %.4f of the line unspent" % (r["day"], r["held"], r["room"]))
    if not L["run_detail"] or not any(r["held"] > 1e-9 for r in L["run_detail"]):
        bad.append("the line's own ledger part-holds no run; A9.13 prints part-held runs")
    if noted["late"][-1] > 1e-9:
        bad.append("with the note, %.4f of held invoices is still unpaid on %s" % (noted["late"][-1], noted["day"][-1]))
    report(BLOCK, DAILY_PART_HELD_CHECK, bad)


def _dated(d):
    """A window date as the rows print it: 'December 1 y2'."""
    return "%s %d y%d" % (calendar.month_name[d.month], d.day, d.year - 2022)


DAILY_DATES_CHECK = "the dates U16's daily ledger derives are the dates the rows print"


def check_daily_dates(index, doc10=None):
    """Every date U16's daily ledger derives is printed where its row says it (owner, 2026-10-22).

    A carried figure sees only a date's day; this check reads the whole date, month and window year, as the rows print
    it, built from the generator: A10.07's dated consequences, from the words for each state the chain reaches; A10.19's
    date, its band ends, its edge and its counterfactual; A9.13's springs, first part-held run, hold and call; A9.12's
    trough. A state the chain reaches that the rows have no words for fails rather than passes. Since U21 the dates
    are read from group 10's outputs(), the dates the seeders import."""
    bad = []
    D = _dated
    DT = _pv("the dates U16's daily ledger derives")
    call, hold, cf, band, edge_date, springs = (DT[k] for k in ("call", "hold", "counterfactual", "band", "edge",
                                                                "springs"))
    peaks, troughs = DT["peak_days"], DT["trough_runs"]
    want = {"A10.19": ["DATE: %s" % D(call), "hold on %s" % D(hold),
                       "ends date the note %s and %s" % (D(band[0]), D(band[1])),
                       "the note dates %s" % D(edge_date), "the same note on %s" % D(cf)],
            "A10.07": ["note lands %s" % D(call), "the same note on %s" % D(cf)],
            "A9.13": ["dates the springs to %s, %s and %s" % tuple(D(s) for s in springs),
                      "the first on %s" % D(DT["first_held"]), "ceiling touch, on %s" % D(springs[0]),
                      "dated %s, the day after the daily ledger's first credit hold on %s" % (D(call), D(hold)),
                      "a call on %s is the counterfactual" % D(cf),
                      "first hold lands %s, so A10.19 lands %s" % (D(hold), D(call))],
            "A9.02": ["dated %s by the daily ledger's %s y%d hold notice"
                      % (D(call), calendar.month_name[hold.month], hold.year - 2022), "landed %s" % D(cf)]}
    if len(set((d.month, d.day) for d in peaks)) != 1 or len(set((d.month, d.day) for d in troughs)) != 1:
        bad.append("A9.12 prints one peak run and one trough day for every window year; the daily ledger gives %s"
                   % [(str(p), str(q)) for p, q in zip(peaks, troughs)])
    else:
        want["A9.12"] = ["need peaks on the %d %s AP run" % (peaks[0].day, calendar.month_name[peaks[0].month]),
                         "first at the run of %s %d" % (calendar.month_name[troughs[0].month], troughs[0].day)]
        want["A9.13"].append("falls first at the run of %s %d, A9.12's trough day"
                             % (calendar.month_name[troughs[0].month], troughs[0].day))
    # A10.07's words for each year's state: the line's own cash for y1 and y2, the note's for y3
    for t, f in enumerate(DT["chain_first"]):
        key = tuple(f[k] is not None for k in ("priority", "fee", "hold"))
        words = {(False, False, False): "y%d carries no supplier consequence" % (t + 1),
                 (True, False, False): "y%d reaches PRIORITY LOSS on %s and stops short of the late fee"
                                       % (t + 1, D(f["priority"])) if f["priority"] else None,
                 (True, True, True): "y%d reaches priority loss on %s, the LATE FEE on %s and THE CREDIT HOLD on %s"
                                     % ((t + 1,) + tuple(D(f[k]) for k in ("priority", "fee", "hold")))
                 if all(f.values()) else None}.get(key)
        if words is None:
            bad.append("A10.07's y%d: the daily ledger gives %s, a state the row has no words for" % (t + 1, f))
        else:
            want["A10.07"].append(words)
    # The hold line is "at 45" (past >= 45, A10.07 and both generators). The edge retired 2026-10-27 (owner,
    # DECISIONS#u14): under the contract-weighted index y2's hold reaches at every AP timing, and the rows say so
    edge, line = DT["hold_edge"], DT["hold_line"]
    at_edge, every = edge[0] < line <= edge[1], all(e >= line for e in edge)
    if not (at_edge or every):
        bad.append("y2's worst days past terms at the three AP timings are %s against the %d-day line: the hold "
                   "reaches at none of them, a state the rows have no words for" % (edge, line))
    texts = dict((rid, " ".join(norm(index[rid]["value"]).split())) for rid in want)
    for rid, phrases in want.items():
        for p in phrases:
            if p not in texts[rid]:
                bad.append("%s does not say %r" % (rid, p))
    for rid in ("A10.07", "A10.19"):
        if at_edge and "HOLD IS AT THE EDGE" not in texts[rid]:
            bad.append("%s does not say the y2 hold is at the edge" % rid)
        if every and "HOLD REACHES AT EVERY AP TIMING" not in texts[rid]:
            bad.append("%s does not say the y2 hold reaches at every AP timing" % rid)
        if every and "HOLD IS AT THE EDGE" in texts[rid]:
            bad.append("%s still calls the y2 hold at the edge; it reaches at every AP timing, %s against %d"
                       % (rid, edge, line))
    d10 = " ".join(norm(doc10 if doc10 is not None else rd(GROUP10_DOC)).split()).replace("**", "")
    for p in ["DATE: %s" % D(call)] + want["A10.07"][2:]:
        if p not in d10:
            bad.append("%s does not say %r" % (GROUP10_DOC, p))
    report(BLOCK, DAILY_DATES_CHECK, bad)


def check_group10_figures(index):
    """The group-10 counts in the doc and the rows are the generator's, verbatim.

    Same contract as the group-9 cross-check: nothing is hardcoded here, the
    numbers are computed and then looked for in the prose that publishes them. Since U21 every value is read from
    group 10's outputs(), under the entry's own label.
    """
    doc = norm(rd(GROUP10_DOC))
    # A10.07's three series and A10.11's fines read through carries() until U4 (2026-10-01), which let a second, stale
    # "31.0 days clears the fee threshold by one day" stand beside the restated series. They are anchored below.
    published = [
        ("A10.03 quarter risk, on-time vs 80",
         PRINTED, "A10.03", 1),
        ("A10.03 pair risk in a year",
         PRINTED, "A10.03", 1),
        ("A10.08 breadth, SKUs per month",
         PRINTED, "A10.08", 1),
    ]
    bad = []
    for label, vals, owner, places in _resolved(published):
        if not carries(index[owner]["value"], vals):
            _UNFOUND.add(label)
            bad.append("%s: the generator computes %s; %s does not carry it"
                       % (label, series(vals, places), owner))
        if not carries(doc, vals):
            _UNFOUND.add(label)
            bad.append("%s: the generator computes %s; %s does not carry it"
                       % (label, series(vals, places), GROUP10_DOC))
    anchored = [
        ("A10.13 tie-out tolerance", PRINTED, 2, r"to within\s+", "A10.13"),
        ("A10.13 the in-flight term inside it", PRINTED, 2, r"and so [^=]{0,30}= ", "A10.13"),
        ("A10.13 delist-to-last-PO lag, the four accounts",
         PRINTED, 0, r"Walmart <=\s*", "A10.13"),
        ("A10.13 the lag's parts, lead time plus one cycle",
         PRINTED,
         0, r"in days - Walmart\s+", "A10.13"),
        ("A10.13 the OTIF-to-fill gap by year", PRINTED, 2, r"in-full,?\s+", "A10.13"),
        ("A10.13 the band that derivation gives", PRINTED, 2, r"giv(?:es|ing) a band of\s+", "A10.13"),
    ]
    anchored += [
        ("A10.04 the 90 line's distance in quarterly sd",
         PRINTED, 2, r"90 (?:drop )?line sits\s+", "A10.04"),
        ("A10.04 a stated y1 pair, as one in N", PRINTED, 0,
         r"in y1 is therefore a \**1 in\s+", "A10.04"),
        ("A10.04 the y3 risks, a stated pair then any adjacent pair",
         PRINTED, 2,
         r"a stated pair is\s+", "A10.04"),
    ]
    anchored += [
        ("A10.08 the breadth mode by year", PRINTED, 0,
         # the row writes it in caps for emphasis and the doc in prose; one pattern, scoped
         # case-insensitive, rather than bending either text to the other.
         r"(?i:the mode is)\s+", "A10.08"),
        ("A10.08 a three-SKU month, exactly", PRINTED, 2,
         r"three-SKU month is\s+", "A10.08"),
        ("A10.08 the y3 mode's own probability", PRINTED, 2,
         r"against the mode's\s+", "A10.08"),
        ("A10.08 at least three out", PRINTED, 2,
         r"at least three are out in\s+", "A10.08"),
    ]
    anchored += [
        ("A7.28 the coverage parts, then the coverage",
         PRINTED, 1, r"(?i:direct measured)\s+", "A7.28", GROUP7_DOC),
        ("A10.18 cuts by account, then the authorizations",
         PRINTED, 0,
         r"cuts by account\s+", "A10.18", GROUP10_DOC),
    ]
    anchored += [
        ("A10.13 the gap's window mean", PRINTED, 2, r"(?i:window mean above zero,)\s+", "A10.13"),
        ("A7.28 the assortment ratio, door-weighted then unweighted",
         PRINTED, 3, r"door-weighted\s+", "A7.28", GROUP7_DOC),
    ]
    anchored += [
        ("A3.08 Kroger's stepped shelf", PRINTED, 2, r"(?i:kroger alone steps):?\s+", "A3.08",
         GROUP3_DOC),
        ("A3.08 realized margins by banner and year",
         PRINTED, 1,
         r"(?:y3: WF|natural\) \|)\s+", "A3.08", GROUP3_DOC),
        ("A3.28 the tolerance window its step pattern holds over", PRINTED, 2,
         r"any tolerance from\s+", "A3.28", GROUP3_DOC),
        ("A7.29 the y3 markup by account",
         PRINTED, 3,
         r"\(the 2025 base\): Walmart [\d.]+/[\d.]+ = ", "A7.29", GROUP7_DOC),
        ("A7.29 Walmart's markup by year", PRINTED, 3, r"(?i:going back:) Walmart\s+", "A7.29", GROUP7_DOC),
        ("A7.29 Whole Foods' markup by year", PRINTED, 3, r"[\d.]+, Whole Foods\s+", "A7.29", GROUP7_DOC),
        ("A7.29 Kroger's markup by year", PRINTED, 3, r"(?i:kroger's falls),\s+", "A7.29", GROUP7_DOC),
        ("A7.29 the weighted markup", PRINTED, 3, r"(?i:weighted):\s+", "A7.29", GROUP7_DOC),
        ("A7.03 the markup it reads", PRINTED, 3, r"(?:x markup|series\))\s+", "A7.03", GROUP7_DOC),
        ("A7.03 measured retail $M", PRINTED, 1, r"(?:\) = \$|retail \$M\s+)", "A7.03",
         GROUP7_DOC),
        ("A7.03 measured units, millions", PRINTED, 2, r"(?:computes:|÷ #\))\s+", "A7.03",
         GROUP7_DOC),
        # the live grid moved to A7.26 on 2026-09-22: A7.03's sentence about it is HISTORY (the retired denominator),
        # and a check that rewrote history every time the grid grew would have silently falsified it.
        ("A7.26 every live door-SKU-week in the grid", PRINTED, 0,
         r"(?:ramp\)\s+)", "A7.26", GROUP7_DOC),
        ("A7.04 the grown door plan by banner",
         PRINTED, 0,
         r"(?i:y1 / y2 / y3): Walmart\s+", "A7.04", GROUP7_DOC),
        ("A7.04 the 2026-09-05 plan it was grown from",
         PRINTED, 0,
         r"(?i:plan is the)[^A-Za-z]*(?i:one)[^A-Za-z]*Walmart\s+", "A7.04", GROUP7_DOC),
        ("A7.04 the door totals",
         PRINTED, 0,
         r"(?i:totals?)\s+", "A7.04", GROUP7_DOC),
        ("A7.04 Supercenters per Walmart DC on the grown plan",
         PRINTED, 0,
         r"(?i:now carry)\s+", "A7.04", GROUP7_DOC),
        # THE LADDER TABLE AT THE HEAD OF THE GROUP-7 DOC, added 2026-09-22. Four of its rows were watched by the
        # entries above and three were not, and the three sat stale through the door correction while their
        # neighbours moved -- the same "two transcriptions, nothing comparing them" the A704_DOORS mirror closed
        # inside the generator. The paragraph locators cannot reach these: `door-SKUs (x A7.26)` puts A7.26's own
        # digits between the locator and the first figure, so the chain is not anchored and the paragraph matches
        # instead. Each row is anchored on its own label.
        ("A7.04 the door totals, the doc's ladder table",
         PRINTED, 0,
         r"authorized doors \([^)]*\)\s+", None, GROUP7_DOC),
        ("A7.26 door-SKUs, the doc's ladder table",
         PRINTED, 0,
         r"door-SKUs \([^)]*\)\s+", None, GROUP7_DOC),
        ("A7.26 scan rows a year and the window, the doc's ladder table",
         PRINTED,
         [0, 0, 0, 1], r"scan rows / year \([^)]*\)\s+", None, GROUP7_DOC),
        # A7.14's supplier-caused share, derived from the brand (owner, 2026-11-03, DECISIONS#u14)
        ("A7.14 supplier-caused share of the not-on-shelf weeks by year, %", PRINTED, 1,
         r"rate above 7\.9%,\s+so\s+", "A7.14", None),
        ("A7.14's supplier-caused share as A7.15 plants it, %", PRINTED, 1,
         r"share of the gap-weeks is #'s,\s+|their share is #'s,\s+", "A7.15", GROUP7_DOC),
        ("A7.15 gap-weeks and episodes a year (thousands), and episodes per door-SKU",
         PRINTED, [0, 0, 0, 0, 0, 0, 1, 1, 1],
         r"(?:grid =|gap-weeks)\s+", "A7.15", GROUP7_DOC),
        ("A7.28 coverage at the reporting band's ends, 50% then 70%",
         PRINTED, [1, 1, 1, 0, 1, 1, 1],
         r"(?:coverage would be|coverage is)\s+", "A7.28", GROUP7_DOC),
        ("A7.05 format mix at y3 by authorized doors, shares",
         PRINTED, 0, r"(?i:conventional supermarket)\s+", "A7.05", GROUP7_DOC),
        ("A7.05 format mix at y3 by authorized doors, counts",
         PRINTED, 0,
         r"(?i:counts)\s+", "A7.05", GROUP7_DOC),
        ("A3.16 the 60 drained stores as a share of one Walmart DC's stores, y2",
         PRINTED, 0,
         r"stores drained \(~", "A3.16", "docs/anchors/sourcing/group-3-price-waterfall.md"),
        ("A7.26 door-SKUs on the grown plan",
         PRINTED, 0,
         r"(?i:door-SKUs)\s+", "A7.26", GROUP7_DOC),
        ("A7.26 scan rows a year, and the window",
         PRINTED,
         [0, 0, 0, 1], r"(?i:rows)\s+", "A7.26", GROUP7_DOC),
        ("A7.03 mass velocity and its derived bands, each year's own",
         PRINTED, 2,
         r"(?i:mass \(walmart\))\s+", "A7.03", GROUP7_DOC),
        ("A7.03 grocery velocity and its derived bands, each year's own",
         PRINTED, 2,
         r"(?i:grocery \([^)]*\))\s+", "A7.03", GROUP7_DOC),
        ("A7.03 natural velocity, against the registered band", PRINTED, 2,
         r"(?i:independents\))\s+", "A7.03", GROUP7_DOC),
        ("A7.03 the three channel breaches",
         PRINTED,
         2, r"(?i:mass at)\s+", "A7.03", GROUP7_DOC),
        ("A3.08 margin above A3.06's ceiling, y1 and y2",
         PRINTED, 1,
         r"(?i:y1 / y2)[^:]*: Regional\s+", "A3.08", GROUP3_DOC),
        ("A7.03 measured live door-SKU-weeks", PRINTED, 0,
         r"(?:independents at #'s [\d.]+ -|measured live door-SKU-weeks)\s+", "A7.03", GROUP7_DOC),
        ("A7.03 velocity, units per SKU per store per week", PRINTED, 2,
         r"(?:VELOCITY|store / week|scan_identity\(\)`:)\s+", "A7.03", GROUP7_DOC),
        ("A7.03 dollars per measured door-SKU-week", PRINTED, 2,
         r"(?:and \$|\$ per measured door-SKU-week\s+)", "A7.03", GROUP7_DOC),
        ("A7.03 implied reporting door-SKUs at the band midpoint", PRINTED, 0,
         r"(?:\bare|imply)\s+", "A7.03", GROUP7_DOC),
        ("A7.03 its measured live door-SKUs on A7.26's grid beside them", PRINTED, 0,
         r"against\s+(?=[\d,]+\s*/)", "A7.03", GROUP7_DOC),
        ("A7.03 the implied-to-registered ratio", PRINTED, 2, r"#'s grid\),\s+", "A7.03",
         GROUP7_DOC),
        ("A7.07 measured door-SKU-weeks and units, growth y1 to y3",
         PRINTED, 1, r"door-SKU-weeks \+", "A7.07", GROUP7_DOC),
        ("A7.07 velocity by year", PRINTED, 2, r"live door-SKU-week\s+", "A7.07", GROUP7_DOC),
        ("A7.07 the headline, units, then y2", PRINTED, 1, r"u/s/w,\s+", "A7.07",
         GROUP7_DOC),
        # A10.03's unwatched derivation, watched on first restatement (owner, 2026-09-24): the row alone prints it
        ("A10.03 A5.17's below-target shares, in-full then on-time",
         PRINTED, 0,
         r"below-target shares are\s+", "A10.03", None),
        ("A10.03 the quarter mean's sd", PRINTED, 2, r"sqrt\(3\) =\s+", "A10.03", None),
        ("A10.03 two consecutive quarters below the line",
         PRINTED, 1,
         r"two consecutive quarters\s+", "A10.03", None),
        ("A7.07 dollars beside it", PRINTED, [2, 2, 1, 1],
         r"(?i:dollars beside it): \$", "A7.07", GROUP7_DOC),
    ]
    pen = _pv("A7.20 household penetration in units")
    # A10.07's annual ladder left the row on U16's restatement (2026-10-22): A10.07 prints the daily chain, watched in
    # _restated_21_figures and check_daily_dates, and A9.13 prints the ladder as the annual-mean reading
    anchored += [
        ("A10.11 y3 fines: the total, then by account",
         PRINTED, [4, 4, 4, 4, 4, 5, 5],
         r"derive to\s+\$", "A10.11", None),
        ("A10.11 y3 fines by account, then the total, group 10's table",
         PRINTED, [4, 4, 4, 4, 5, 5, 4],
         r"non-compliant case value \| \$", None, GROUP10_DOC),
        ("A10.11 y3 fines as a share of the pool", PRINTED, 2, r"which is\s+|That is \*\*", "A10.11"),
        # 1.025143 sits 0.00014 above the 1.025 rounding edge: a small move in the fines flips the printed 1.03
        ("A10.11 the ratio of A4.05's late/OTIF share to the fines", PRINTED, 2,
         r"a ratio of\s+\**(?=\d)", "A10.11"),
        ("A10.11 Walmart's fine, then the correlated and exclusive totals",
         PRINTED, 4,
         r"Walmart's fine at\s+\$", "A10.11"),
        ("A10.11 Walmart's non-compliant case share", PRINTED, 1,
         r"case share at\s+", "A10.11"),
        ("A10.11 Kroger's E[days | fined], then the late-cancel shares at Kroger, Walmart and Regional",
         PRINTED, [4, 2, 2, 2],
         r"E\[days \| fined\] is\s+", "A10.11"),
        ("A10.11 late cancels a year", PRINTED, 2, r"late cancels run\s+",
         "A10.11"),
        ("A10.11 the lateness means: Walmart, Kroger, Regional",
         PRINTED, 1, r"with means Walmart\s+",
         "A10.11"),
        # 90 and 85 are Walmart's program lines (A10.02), which main() prints the same way
        ("A10.08 Walmart in-full below its tolerance line, share of months",
         PRINTED, 0,
         r"in-full below \d+(?: in| \|)\s+", "A10.08"),
        ("A10.08 Walmart on-time below its tolerance line, share of months",
         PRINTED, 0,
         r"on-time below \d+(?: in| \|)\s+", "A10.08"),
        ("A10.13 the raw band, before the zero clip", PRINTED, 2, r"(?<![a-z])raw\s+", "A10.13"),
        # A7.04's %ACV, one entry per banner: the prints are labelled, not a chain. Walmart's reads A7.01's Supercenter
        # grocery ACV, solved so the formats sum to the banner's grocery (owner, 2026-10-23, DECISIONS#u14-walmart-acv)
        # A6.02's manual-to-EDI ratio is a band on A6.32's unsourced EDI rate (owner, 2026-10-23, DECISIONS#u14)
        # ...and its per-line rate is a band on the reading of a cognitive field (owner, 2026-10-25, DECISIONS#u14)
        ("A6.02 manual line error at the character, across the reading band, %", PRINTED, 1,
         r"keystroke action rather than his complex thought, gives (?=[\d.]+% to)", "A6.02", GROUP6_DOC),
        ("A6.02 manual line error disciplined, across the reading band, %", PRINTED, 1,
         r"a line at the character and (?=[\d.]+% to)", "A6.02", GROUP6_DOC),
        ("A6.02 manual-to-EDI ratio at the character, across both bands", PRINTED, [1, 0],
         r"across both bands, (?=[\d.]+x to)", "A6.02", GROUP6_DOC),
        ("A6.02 manual-to-EDI ratio disciplined, across both bands", PRINTED, [1, 0],
         r"per line at the character and (?=[\d.]+x to)", "A6.02", GROUP6_DOC),
        ("A6.16 manual-vs-EDI spread floor, derived", PRINTED, 0, r"top of #'s band, ~(?=\d+x)", "A6.16",
         GROUP6_DOC),
        ("A6.02 manual-to-EDI ratio at A6.32's point, character then disciplined", PRINTED, 0,
         r"disciplined, (?=\d+x and)", "A6.02", GROUP6_DOC),
        # A9.16's index on its registered contract terms (owner, 2026-10-25, DECISIONS#u14)
        ("A9.16 COGS inflation by year, contract-weighted, %", PRINTED, 2, r"COGS INFLATION, CONTRACT-WEIGHTED,\s+\+?",
         "A9.16", GROUP9_DOC),
        ("A9.16 cost level in 2023 and 2024, 2025 = 1", PRINTED, 4, r"cost level, 2025 = 1,\s+", "A9.16", GROUP9_DOC),
        # ...and as the two rows that apply it print it; both carried the retired series unread (owner, 2026-11-02)
        ("A9.16 cost level relative to 2025, as A3.01 prints it", PRINTED, 3, r"index relative to 2025 \(", "A3.01",
         None),
        ("A9.16 cost level relative to 2025, as A9.02 prints it", PRINTED, 3, r"index relative to 2025 \(", "A9.02",
         None),
        # A1.01's second endpoint is a band (owner, 2026-10-23, DECISIONS#u14); its top holds A1.02's y1 rate
        ("A1.01 the second endpoint's band top, sustained y1 growth, $M", PRINTED, 1, r"at sustained \d+%, \$(?=\d)",
         "A1.01", GROUP1_DOC),
        ("A7.04 %ACV at y3, Walmart", PRINTED, 0, r"Walmart ~(?=\d+, in a band of)", "A7.04", GROUP7_DOC),
        ("A7.04 %ACV at y3, Walmart's band top", PRINTED, 0, r"in a band of \d+ to (?=\d+)", "A7.04", GROUP7_DOC),
        ("A7.01 Supercenter grocery ACV, $M", PRINTED, 1, r"Supercenters ~\$(?=\d)", "A7.01", GROUP7_DOC),
        ("A7.01 a Supercenter against a Sprouts box", PRINTED, 1, r"Supercenter runs ~(?=\d)", "A7.01", GROUP7_DOC),
        ("A7.04 %ACV at y3, Kroger", PRINTED, 0, r"(?<=, )Kroger ~(?=\d+, Whole Foods ~)", "A7.04", GROUP7_DOC),
        ("A7.04 %ACV at y3, Whole Foods", PRINTED, 0, r"(?<=, )Whole Foods ~(?=\d+ to \d+ across)", "A7.04",
         GROUP7_DOC),
        # batch 1 of U14's record (owner, 2026-10-23, DECISIONS#u14): Whole Foods' store band, Walmart's filed grocery,
        # Costco's U.S. segment revenue
        ("A7.04 %ACV at y3, Whole Foods at the band's low", PRINTED, 0, r"Whole Foods ~\d+ to (?=\d+ across)", "A7.04",
         GROUP7_DOC),
        ("A7.01 Walmart U.S. grocery, % of net sales", PRINTED, 2, r"of net sales of \$[\d.]+B, filed, ", "A7.01",
         GROUP7_DOC),
        ("A7.01 Costco U.S. revenue a warehouse, $M", PRINTED, 0, r"Costco U\.S\. \$(?=\d+M \(club)", "A7.01",
         GROUP7_DOC),
        ("A7.04 %ACV at y3, Sprouts", PRINTED, 0, r"(?<=, )Sprouts ~(?=\d+, Costco ~)", "A7.04", GROUP7_DOC),
        ("A7.04 %ACV at y3, Costco", PRINTED, 0, r"(?<=, )Costco ~(?=\d+\. )", "A7.04", GROUP7_DOC),
        ("A7.20 household penetration in units", PRINTED, 2, r"give penetration\s+", "A7.20", GROUP7_DOC),
    ]
    quarters = _pv("A10.03 the quarter table, by year: one quarter, two consecutive, a pair in the year")
    anchored += [("A10.03 the quarter table, y%d: one quarter, two consecutive, a pair in the year" % (t + 1),
                  quarters[t], 1, r"\| y%d, on-time mean [\d.]+ \|\s+\**" % (t + 1), None, GROUP10_DOC)
                 for t in range(3)]
    anchored = _resolved([e if len(e) == 6 else e + (GROUP10_DOC,) for e in anchored])
    # `owner` is None where the figure lives in a doc alone -- the ladder table at the head of the group-7 doc
    # publishes rows no registry row states in that form. A row check against an owner that does not carry the
    # quantity would be a check written to pass.
    for label, vals, places, after, owner, docpath in anchored:
        # `docpath` is None where the figure lives in a row alone (A10.03's derivation, 2026-09-24)
        for where, text in (([(owner, index[owner]["value"])] if owner else [])
                            + ([(docpath, rd(docpath))] if docpath else [])):
            if not carries_exact(norm(text), vals, places, after=after):
                _UNFOUND.add(label)
                bad.append("%s: the generator computes %s; %s does not carry it"
                           % (label, series(vals, places), where))
    # A10.07's verdict words (U4, 2026-10-01) read the annual ladder until U16 (2026-10-22); the daily chain's words
    # and dates are check_daily_dates'.
    # A7.04's "the cap does not bind" is true only while Sprouts' y3 doors sit under its filed universe
    doors, universe = _pv("A7.04's Sprouts doors in y3, then the universe its cap reads")
    for where, text, phrase in (("A7.04", index["A7.04"]["value"], "CAP DOES NOT BIND"),
                                (GROUP7_DOC, rd(GROUP7_DOC), "cap does not bind")):
        if doors >= universe and phrase in " ".join(norm(text).split()):
            bad.append("A7.04's Sprouts doors reach %d of its %d stores in y3; %s still says %r"
                       % (doors, universe, where, phrase))
    # A7.20 names the years its penetration sits above its own plausibility band, read from the row
    band = re.search(r"(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)% plausibility band", norm(index["A7.20"]["value"]))
    if not band:
        bad.append("A7.20 no longer prints its plausibility band -- the years above it cannot be read")
    else:
        above = ["y%d" % (t + 1) for t in range(3) if pen[t] > float(band.group(2))]
        for where, text in (("A7.20", index["A7.20"]["value"]), (GROUP7_DOC, rd(GROUP7_DOC))):
            flat = " ".join(norm(text).split())
            words = "In %s it sits above" % " and ".join(
                [", ".join(above[:-1]), above[-1]] if len(above) > 1 else above) if above else None
            if words and words not in flat:
                bad.append("A7.20's penetration %s sits above the %s%% band top in %s; %s does not say %r"
                           % (series(pen, 2), band.group(2), ", ".join(above), where, words))
            elif not words and "it sits above" in flat:
                bad.append("A7.20's penetration %s sits inside the band in every year; %s still says it sits above"
                           % (series(pen, 2), where))
    report(BLOCK, "doc / registry / generator agree, group 10", bad)


_BLANKED = re.compile(r"\b\d{4}-\d{2}(?:-\d{2})?\b|\b\d{2}:\d+(?:/\d+)*|\bA\d+\.\d+\b")
_NUMBER = re.compile(r"(?<![\w.,-])-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\d]|[.,]\d)")
_RANGE = re.compile(r"(?<![\w.,-])(\d[\d,]*(?:\.\d+)?)\s*%?\s*[-–]\s*\$?(\d[\d,]*(?:\.\d+)?)(?![\d]|[.,]\d)")


_WRAP = re.compile(r"\s*\n[ \t]*>?[ \t]*")


def _unwrap(text):
    r"""One space wherever a line break and its continuation markers were.

    RULE 2 (owner, 2026-09-18): the line-wrap hazard is the MATCHER'S, not the locator's. A
    locator written as "y3 funding gap" failed on a marker that wrapped between "y3" and
    "funding", because a blockquote continuation inserts "> ", which is not whitespace and no
    `\s+` will absorb. Every locator in this file carries literal spaces, so ANY of them could
    break on a reflow -- a hazard tracked from 2026-09-15 and left open until it bit.

    Normalising here closes the class for every entry at once, instead of asking each locator to
    anticipate where a line might wrap. Runs of whitespace collapse to one space as well, so a
    locator never has to care whether prose was rewrapped.
    """
    return re.sub(r"[ \t]+", " ", _WRAP.sub(" ", text))


def carries_exact(text, values, places, window=160, pairs=False, after=None, gap=2):
    """A stricter carries() for group 11: each value as its own number token, at THAT TOKEN'S precision.

    SINCE U5 (owner, 2026-10-02, DECISIONS#print-rule) a token carries a value at the precision it is
    printed at (token_matches): 43 carries 43.06. `places` is the precision the site prints, and a
    token at any other precision carries nothing, so "0.94" cannot cover 0.9512 where the site prints
    three decimals. Matching at the prose's precision is what carries() once did and why
    this function was written: "every 0.1 lb" stood in for a lambda of 0.0851, and an h_m table's
    "0.06" for a moved lambda. What holds against that now is the rest of this function -- whole
    number tokens, the series in order, each within `window` characters of the one before, and a
    lone value anchored by `after` -- and probe_figure_checks, which moves each value one unit at the
    precision actually printed.

    THE SERIES MUST BE CONSECUTIVE: no number written at either link's precision may sit
    between two links. A chain that could skip numbers passed a value moved onto its
    neighbour - Kroger's 7.18% moved to the brand pool's 7.27% one table row down, a
    registered DSO onto the preview series printed after it, and y3's recall rate onto y1's,
    two decimals, ahead of a one-decimal window share.

    Dates (2014-03-27), requirement pointers (07:98) and anchor ids (A7.13) are blanked first,
    and a digit after a letter, a point, a comma or a hyphen is not a number: a y1 range once
    passed on the 27 of a date, and "y1" and "N27" supplied digits. With `pairs`, each value is
    a (low, high) range written as ONE token - "27-45%", "1.79-2.38x". `after` anchors a lone
    value: its token must begin within `gap` characters after a match of that pattern, because
    a single number is always somewhere in a long doc. An empty series fails.
    """
    return carried_tokens(text, values, places, window, pairs, after, gap) is not None


def carried_tokens(text, values, places, window=160, pairs=False, after=None, gap=2):
    """carries_exact's match, returning the tokens that carry the series (or None): the print-rule report and
    probe_figure_checks read the precision actually printed from them."""
    if not values:
        return None
    text = _unwrap(text)
    text = _BLANKED.sub("#", text)
    each = list(places) if isinstance(places, (list, tuple)) else [places] * len(values)
    anchors = [m.end() for m in re.finditer(after, text)] if after else None

    def anchored(pos):
        return anchors is None or any(0 <= pos - e <= gap for e in anchors)

    return _carried(text, values, each, window, pairs, anchored)


def sig_figs(tok):
    """Significant figures a token prints: 43.06 -> 4, 0.70 -> 2, 62,292 -> 5, 350 -> 2."""
    s = tok.replace(",", "").lstrip("-")
    digits = s.replace(".", "").lstrip("0")
    return len(digits) if "." in s else len(digits.rstrip("0"))


def token_matches(tok, v, places=None):
    """A printed token carries a value AT THE TOKEN'S OWN PRECISION (owner, 2026-10-02, DECISIONS#print-rule): 43
    carries 43.06 and 8.452 carries 8.4519; a fixed decimal count of the check's own is never used. A whole number
    ending in zeros is also read at its significant figures, never fewer than two: 350 carries 354.9, 62,000
    carries 62,292.

    THE SITE'S PRECISION (owner, 2026-10-02, refining the ruling): `places` is the precision the watched site
    prints, and a token at any other precision carries nothing. Coarser: 0.94 would cover 0.9512, and the first
    probe of the unrestricted matcher found 255 such stand-ins across 32 watched sites. Finer: 0.358 printed
    elsewhere would cover a whole-number figure moved onto it, and the floored matcher's probe found 10. A site
    converted to the print rule lowers its watch's `places` in the same edit; a negative `places` is a whole number
    read at its significant figures (62,000 at -3)."""
    s = tok.replace(",", "")
    d = len(s.partition(".")[2])
    if places is not None:
        if places >= 0:
            return d == places and ("%.*f" % (d, v)) == s
        return d == 0 and abs(round(v, places) - float(s)) < 1e-9
    if ("%.*f" % (d, v)) == s:
        return True
    if d == 0 and s.endswith("0") and float(s) != 0:
        sf = max(2, len(s.lstrip("-").rstrip("0")))
        mag = math.floor(math.log10(abs(float(s))))
        return abs(round(v, sf - 1 - mag) - float(s)) < 1e-9 and math.floor(math.log10(abs(v) or 1)) == mag
    return False


def token_unit(tok):
    """One unit of a printed token's own precision: 0.01 for 8.45, 1 for 62,292, 10 for 350, 1,000 for 62,000."""
    s = tok.replace(",", "")
    d = len(s.partition(".")[2])
    if d:
        return 10.0 ** -d
    zeros = len(s) - len(s.rstrip("0")) if float(s) != 0 else 0
    return 10.0 ** min(zeros, max(0, len(s.lstrip("-")) - 2))


def _carried(text, values, each, window, pairs, anchored):
    """The tokens a series is carried by, in order -- strings, or (low, high) pairs -- or None. carries_exact's
    matcher; probe_figure_checks reads the tokens to take a one-unit move at the precision actually printed."""
    if pairs:
        rng = [(m.start(), m.end(), m.group(1), m.group(2)) for m in _RANGE.finditer(text)]

        def dec(s):
            return len(s.partition(".")[2])

        def chain_r(k, i, got):
            if k == len(values):
                return got
            for j in range(i, len(rng)):
                st, en, lo, hi = rng[j]
                if k and st - rng[i - 1][1] > window:
                    return None
                if (k or anchored(st)) and token_matches(lo, values[k][0], each[k]) and token_matches(
                        hi, values[k][1], each[k]):
                    out = chain_r(k + 1, j + 1, got + [(lo, hi)])
                    if out is not None:
                        return out
                if k and dec(lo) == dec(hi) and dec(lo) in (dec(got[-1][0]), each[k]):
                    return None
                if not k:
                    continue
            return None
        return chain_r(0, 0, [])

    toks = [(m.start(), m.end(), m.group(0), len(m.group(0).partition(".")[2])) for m in _NUMBER.finditer(text)]

    def chain(k, i):
        if k == len(values) - 1:
            return [toks[i][2]]
        for j in range(i + 1, len(toks)):
            if toks[j][0] - toks[i][1] > window:
                return None
            if token_matches(toks[j][2], values[k + 1], each[k + 1]):
                rest = chain(k + 1, j)
                if rest is not None:
                    return [toks[i][2]] + rest
            if toks[j][3] in (toks[i][3], each[k + 1]):
                return None
        return None
    for i, t in enumerate(toks):
        if token_matches(t[2], values[0], each[0]) and anchored(t[0]):
            got = chain(0, i)
            if got is not None:
                return got
    return None


# ---------------------------------------------------------------- #drawn-precision, the tag the gate enforces
#
# A drawn figure prints only the decimals that disjoint seeds hold (DECISIONS#drawn-precision). These two
# constants ARE that tag: every entry below that publishes a solved factor or one of A7.13's shares reads
# them rather than a literal, so the precision is stated once and cannot drift entry by entry.
#
# MEASURED, four disjoint seed sets of 6,000 (slice 1, 2026-09-16, re-measured in slice 5 with the factor
# held at its signed value; the full table is at DECISIONS#drawn-precision-applied):
#   the account factor      0.5953-0.6004  -> the third decimal does not hold; two do
#   A7.13's 90-day share    50.42-50.71%   -> the first decimal does not hold, and NEITHER DOES THE WHOLE
#                                             PERCENT: the range straddles 50.5. The owner ruled whole
#                                             percents on 2026-09-16 with the first half of that measured;
#                                             the straddle is slice 5's finding and is recorded, not hidden.
#                                             The gate checks the CANONICAL seed, so it stays deterministic.
#   A7.13's two-year share  58.96-59.18%   -> whole percents hold
#   launches gone by 24 mo  32.64-33.03%   -> whole percents hold
P_FACTOR = 2            # a solved log-sd: 0.60, not 0.599
P_SHARE = 0             # a drawn share of listings: 50%, not 50.5%

_GROUP11 = []
_GROUP11_FACTS = []
GENERATORS = ("scripts/group9_ledger.py", "scripts/group10_floors.py", "scripts/group11_compliance.py",
              "scripts/group8_dtc.py")   # U16: the daily ledger reads A8.17's month shape, so group 8 feeds the cache


PRINTED = object()   # an entry's value, read from the generators' outputs() under the entry's own label (U21)
_PRINTED = {}        # label -> (generator, anchor, value), built once a process from outputs()
_READ, _MISSING, _UNFOUND = set(), set(), set()   # labels the figure checks read, asked for unprinted, did not find


def _encode(o):
    """outputs() through JSON exactly: floats by repr, Fractions as numerator and denominator, dates by ISO day."""
    if isinstance(o, Fraction):
        return {"__fraction__": [o.numerator, o.denominator]}
    if isinstance(o, datetime.date):
        return {"__date__": o.isoformat()}
    raise TypeError("outputs() carries a %s, which does not cross JSON" % type(o).__name__)


def _decode(d):
    if "__fraction__" in d:
        return Fraction(*d["__fraction__"])
    if "__date__" in d:
        return datetime.date(*(int(x) for x in d["__date__"].split("-")))
    return d


def _outputs_compute():
    """The four generators' outputs(), the one object the gate's figure checks read and the platform's seeders import
    (U21). About fifteen minutes cold: group 10's call solves the account factor on the window's own carried sets,
    and group 11's takes the solved factor, which it must never solve again -- the gate holds it to that here."""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import group8_dtc as D
    import group9_ledger as G
    import group10_floors as F
    import group11_compliance as L
    o10 = F.outputs()
    acct = o10["printed"]["A11.27"][FACTOR]
    solve = L.solve_account_factor

    def refused(*a, **kw):
        raise AssertionError("group 11's outputs(acct) solved the account factor it was given")
    L.solve_account_factor = refused
    try:
        o11 = L.outputs(acct)
    finally:
        L.solve_account_factor = solve
    return dict(group8_dtc=D.outputs(), group9_ledger=G.outputs(), group10_floors=o10, group11_compliance=o11)


def _outputs():
    """_outputs_compute's object, cached on disk.

    The draw takes minutes and the gate runs after every edit. The cache key is the SHA-256 of the four generators'
    source and of _outputs_compute's own, so a change to either recomputes; the cache lives in the system temp
    directory, never in the repository; --no-cache recomputes regardless. A first run and a cached run read one form:
    the object passes through JSON either way, exactly (_encode).
    """
    import hashlib
    import inspect
    import json
    import tempfile
    h = hashlib.sha256()
    for rel in GENERATORS:
        h.update(rd(rel).encode("utf-8"))
    h.update(inspect.getsource(_outputs_compute).encode("utf-8"))
    path = os.path.join(tempfile.gettempdir(), "cinderhaven-check-anchors", "outputs-%s.json" % h.hexdigest()[:20])
    if "--no-cache" not in sys.argv and os.path.exists(path):
        with io.open(path, encoding="utf-8") as f:
            return json.load(f, object_hook=_decode)
    text = json.dumps(_outputs_compute(), default=_encode)
    if not os.path.isdir(os.path.dirname(path)):
        os.makedirs(os.path.dirname(path))
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return json.loads(text, object_hook=_decode)


def _printed():
    """Every printed value by its entry's label: label -> (generator, anchor, value). A label two entries print under
    is listed once in _PRINTED_TWICE, which check_entry_outputs reports."""
    if not _PRINTED:
        for gen, out in sorted(_outputs().items()):
            for anchor, entries in sorted(out["printed"].items()):
                for label, value in entries.items():
                    if label in _PRINTED:
                        _PRINTED_TWICE.add(label)
                    _PRINTED[label] = (gen, anchor, value)
    return _PRINTED


_PRINTED_TWICE = set()


def _pv(label):
    """A printed value by its entry's label: the one door from a figure check to a generator (U21). None, and
    recorded, when no generator prints it."""
    P = _printed()
    if label not in P:
        _MISSING.add(label)
        return None
    _READ.add(label)
    return P[label][2]


def _resolved(entries):
    """Entries with PRINTED replaced by the printed value under their label; an entry whose label no generator prints
    is dropped here and reported by check_entry_outputs, never checked against nothing."""
    out = []
    for e in entries:
        if e[1] is PRINTED:
            v = _pv(e[0])
            if v is None:
                continue
            e = (e[0], v) + tuple(e[2:])
        out.append(e)
    return out


GROUP6_DOC = "docs/anchors/sourcing/group-6-error-ledger.md"
A626_ROW_ORDER = ("po_acknowledgment", "edi_reconciliation", "receiving_audit", "item_setup_preflight",
                  "price_book_governance", "three_way_match", "none")
A626_DOC_ORDER = ("po_acknowledgment", "edi_reconciliation", "price_book_governance", "receiving_audit",
                  "item_setup_preflight", "three_way_match", "none")
A606_DOC_ORDER = {"b2": ("short_ship", "label_pallet_asn", "pricing_error", "damaged_unsaleables", "spoilage_shortdated",
                         "late_otif", "receiving_miscount", "post_audit", "other", "overage"),
                  "b1": ("pricing_error", "receiving_miscount", "post_audit", "short_ship", "damaged_unsaleables", "other",
                         "spoilage_shortdated", "label_pallet_asn", "overage", "late_otif")}


def _a901_opex_figures(E):
    """A9.01's opex ladder: every line, the total, the Establish check and the two moved figures.

    Registered as a generator output 2026-09-18. Until then the ladder was the literal
    OPEX = [7.280, 8.452, 9.763] at group9_ledger.py:65 and NOTHING watched any of its thirty
    magnitudes - not the seven lines, not the total, not the Establish check, not the percentages of
    gross. It is the largest surface this gate has ever been blind to.

    NOT CHECKED, named so the gap is visible: the G&A decomposition's seven SHARES (1.0, 0.4, 0.4,
    0.5, 0.3, 0.2, 0.4), which are the practitioner line's own definition rather than an output, and
    A9.04's headcount and A9.05's loaded rates, which are inputs registered in their own rows.
    """
    D9 = GROUP9_DOC
    fees = _pv("marketplace_fees(t)'s seven components by year, $M")
    return [
        # ---- the ladder, line by line, in A9.01's row. Each locator is the phrase that publishes it.
        ("A9.01 non-production payroll", PRINTED, ("A9.01",), 3, False,
         r"warehouse heads are IN it\)\s+"),
        ("A9.01 broker commission and retainers", PRINTED, ("A9.01",), 3, False,
         r"BROKER COMMISSION AND RETAINERS \(#\)\s+"),
        ("A9.01 marketing", PRINTED, ("A9.01",), 3, False,
         r"MARKETING \(# paid \+ [\d.]+% brand\)\s+"),
        ("A9.01 outbound freight", PRINTED, ("A9.01",), 3, False, r"LESS THE AMAZON PARCEL\s+"),
        ("A9.01 warehousing supplies", PRINTED, ("A9.01",), 4, False,
         r"equipment and outside storage only, [\d.]+% of gross\s+"),
        ("A9.01 DTC 3PL, own-site orders", PRINTED, ("A9.01",), 3, False, r"DTC 3PL \(#\)\s+"),
        ("A9.01 marketplace", PRINTED, ("A9.01",), 3, False, r"MARKETPLACE \(# \+ # \+ #\)\s+"),
        ("A9.01 G&A", PRINTED, ("A9.01",), 3, False, r"other [\d.]+ =\s+"),
        # ---- A11.31's FBA fee and the parcel it lets the freight line carve out, registered 2026-09-18
        ("A11.31's FBA fulfilment, peak uplift included", PRINTED, ("A9.01", "A11.31"), 3, False,
         r"at the non-peak rate, and \$|FBA fulfilment at \$[\d.]+ a jar\s+"),
        ("A11.31's FBA fulfilment at the non-peak rate, which the row publishes beside it",
         PRINTED, ("A11.31",), 3, False, r"units that is \$"),
        # Two entries, not one: both texts print the fee a jar BEFORE the charge, and A11.31 puts the
        # uplift between them, so no single series reads consecutively off either.
        ("A11.31's peak charge on the window's days", PRINTED, ("A9.01", "A11.31"), [5, 5, 4], False,
         r"on the window's 92 days(?: is)? \$?"),
        ("A11.31's peak fee a jar", PRINTED, ("A9.01", "A11.31"), 3, False,
         r"the peak uplift inside it at \$|weighted \$"),
        ("A11.31's fee a jar, weighted over A11.03's mix", PRINTED, ("A11.31",), 3, False,
         r"WEIGHTED OVER THE MIX, 20 / 30 / 50 of JARS: \$"),
        ("A11.31's three pack fees, single / 2-pack / 3-pack", PRINTED, ("A11.31",), 2, False,
         r"the three fees in order: \$"),
        ("A11.22's referral blended over A11.03's mix, $M", PRINTED, ("A9.01",), 3, False,
         r"BLENDED AT [\d.]+% over #'s owner-signed pack mix,\s+"),
        ("A11.22's referral blended over A11.03's mix, $K", PRINTED,
         ("A11.22",), 1, False, r"blend is [^=]{0,40}= [\d.]+%, giving \$"),
        ("the Amazon parcel carved out of the freight line", PRINTED, ("A9.01",), 3, False,
         r"on Amazon's dollars,\s+"),
        # the reading not applied, unwatched until the owner asked for it (2026-11-10, DECISIONS#u17-start)
        ("the carve at A5.24's flat rate, the reading not applied", PRINTED, ("A9.01",), [4, 4, 3], False,
         r"flat [\d.]+% instead would remove\s+"),
        # ---- the total and its share of gross, which the row and the doc both publish
        ("A9.01 total opex and its share of gross", PRINTED, ("A9.01",), [3, 3, 3, 1, 1, 1], False,
         r"TOTAL OPEX\s+"),
        # the P&L block prints the share of gross y1 -> y3 beside each line; U4 restated both and nothing read them
        ("A9.01 total opex and its share of gross y1 -> y3, group 9's P&L block", PRINTED, (D9,),
         [3, 3, 3, 1, 1], False, r"= opex\s+"),
        ("A9.01's marketing line and its share of gross y1 -> y3, group 9's P&L block",
         PRINTED, (D9,),
         [3, 3, 3, 1, 1], False, r"marketing \(# own-site \+ [\d.]+% brand\)\s+"),
        # the payroll line went unread through U14's batch 3 and stayed stale (owner, 2026-11-02, DECISIONS#u14)
        ("A9.01's payroll line and its share of gross y1 -> y3, group 9's P&L block",
         PRINTED, (D9,), [3, 3, 3, 1, 1], False, r"non-production payroll \(#×#\)\s+"),
        # ---- the Establish check: the numerator, then the shares of A9.02's NET revenue
        ("A9.01's Establish check and its shares of net revenue", PRINTED,
         ("A9.01",), [3, 3, 3, 2, 2, 2], False, r"\+ supplies =\s+"),
        ("A9.01's warehouse payroll, the Establish numerator's first term", PRINTED,
         ("A9.01",), 3, False, r"the heads x #\)\s+"),
        ("A9.01's Establish shares, group 9's doc", PRINTED, (D9,), 2, False,
         r"payroll \+ rent \+ supplies \(\s*"),
        # ---- the marketplace line's two halves, and A11.30's signed point
        ("A11.30's advertising, A9.01 and its own row", PRINTED, ("A9.01", "A11.30"), 3, False,
         r"ACoS\s+|#'s y2\)\.\s+\$"),
        ("A11.30's ACoS point", PRINTED, ("A11.30", "A9.01"), 0, False,
         r"advertising at a\s+|SIGNED AT THE\s+"),
        # ---- A9.09's restated broker share, in both rows that print it
        ("A9.09's broker-managed share, restated on A5.38's DPI move",
         PRINTED, ("A9.09",), 0, False, r"broker-managed accounts\s+=\s+"),
        # ---- marketplace_fees(t)'s other four components (U21): A9.01 printed them and nothing read them
        ("A11.31's storage, A9.01's marketplace line", fees["storage"], ("A9.01", "A11.31"), [5, 5, 4], False,
         r"\d, storage\s+|days of supply, \$"),
        ("A11.31's inbound placement, A9.01's marketplace line", fees["inbound"], ("A9.01", "A11.31"), 4, False,
         r"inbound placement\s+|about \$[\d.]+ a unit, \$"),
        # at three figures in $M (owner, 2026-10-23, DECISIONS#print-three-figures): 0.020 for $0.0195M tied. A11.31's
        # own copy was unread and still at two figures until DECISIONS#u14 (owner, 2026-10-23)
        ("A11.31's returnless refunds, A9.01's marketplace line", fees["returnless"], ("A9.01", "A11.31"), 4, False,
         r"returnless refunds\s+|both the unit and the sale, \$"),
        ("A11.22's Professional plan, A9.01's marketplace line", fees["plan"][:1], ("A9.01",), 6, False,
         r"Professional\s+plan\s+"),
    ]


def _a6_chain_figures(E):
    """A6.26 -> A6.31 / A6.15 -> A4.08, A6.11, A9.06: every place the chain is printed, registered 2026-09-18.

    A6.26 went stale on A6.06's restatement of 2026-09-17 in the same commit, because A6.06 was watched and A6.26
    was not (DECISIONS#check-downstream-of-your-own-fix); the sweep that restated it found A6.06's own paragraph
    in the group-6 doc and A4.08's y3 deltas there stale since 2026-09-12. `E` builds a DECISIONS target.
    NOT CHECKED, named so the gap is visible: A6.11's sums (~5.6 / ~4.8), which add A6.11's own non-deduction
    residuals to A6.15's pools in prose; the requirements documents' ~41%; and the retired figures each
    RESTATED passage names.
    """
    D6, D9, D10 = GROUP6_DOC, GROUP9_DOC, GROUP10_DOC
    table_p = []           # the block's places: coverage, rate, their product, by control in the doc's order
    for c in A626_DOC_ORDER:
        table_p += [1, 2, 0 if c == "none" else 2]
    return [
        # ---- A6.26: the coverage vector and its `none` decomposition
        ("A6.26's coverage vector, row", PRINTED, ("A6.26",), 1, False,
         r"share of bucket-2 dollars:\s+po_acknowledgment\s+"),
        ("A6.26's `none` by type, then reachable and structural, row", PRINTED,
         ("A6.26",), 1, False, r"decomposes by type:\s+short_ship\s+"),
        ("A6.26's coverage vector, group 6's doc", PRINTED, (D6,), 1, False,
         r"rounded integers\):\s+\*\*po_acknowledgment\s+"),
        ("A6.26's `none` by type, group 6's doc", PRINTED, (D6,), 1, False,
         r"The `none` share decomposes: short_ship\s+"),
        ("A6.26's `none` share, group 6's doc", PRINTED, (D6,), 0, False, r"The `none` share is\s+"),
        ("A6.26's `none` share, the decision", PRINTED, (E("A6.26"),), 0, False, r"comes out near\s+"),
        ("the block: A6.26 x A6.13 by control, then controls-only prevention", PRINTED, (D6,),
         table_p + [1], False, r"benchmark rate\s+caught\s+po_acknowledgment\s+"),
        ("the block: `none` by type, reachable and unreachable", PRINTED, (D6,), 1,
         False, r"`none` by type: short_ship\s+"),
        # ---- A6.31: the reachable base and the lever
        ("A6.31's reachable base, the `none` share and the structural types, row",
         PRINTED, ("A6.31",), 1, False, r"REACHABLE base \(short_ship\s+"),
        ("A6.31's removal by type, weighted, in points, and the full sum, row",
         PRINTED, ("A6.31",), [3, 3, 2, 3, 1, 3, 3, 3], False,
         r"registered well-run endpoints:\s+short_ship\s+"),
        ("A6.31's `none` by type, group 6's doc", PRINTED, (D6,), 1, False,
         r"decomposes by type \(#\): short_ship\s+"),
        ("A6.31's removal by type, weighted, in points, and the full sum, group 6's doc",
         PRINTED, (D6,), [3, 3, 2, 1, 1, 3, 3, 3],
         False, r"not from an asserted share: short_ship\s+"),
        ("the block: A6.31's weighted removal, its points, and full prevention",
         PRINTED, (D6,), 1, False, r"from #'s endpoints\)\s+"),
        # ---- A6.15: the pool, the buckets, both tiers
        ("A6.15's pool and its buckets, row", PRINTED, ("A6.15",), [2, 3, 3, 3], False, r"# \+ # =\s+"),
        ("A6.15's bucket-1 residual, row", PRINTED, ("A6.15",),
         [3, 1, 3, 3], False, r"Bucket 1 =\s+"),
        ("A6.15's two tiers: prevention and bucket-2 residual, row", PRINTED, ("A6.15",), [3, 2, 3, 2],
         False, r"shares x # rates =\s+"),
        ("A6.15's bucket 3, row", PRINTED, ("A6.15",), 3, False, r"Bucket 3 =\s+"),
        ("A6.15's well-run pools, row", PRINTED, ("A6.15",), 2, False, r"Well-run pool: controls-only\s+"),
        ("A6.15's bucket-2 share of the well-run pool, row", PRINTED, ("A6.15",), 0, False,
         r"Bucket-2 share of the well-run pool: controls-only\s+"),
        ("the block: bucket-1 residual", PRINTED, (D6,), [3, 2, 3, 2],
         False, r"bucket-1 residual\s+=\s+"),
        ("the block: bucket-2 residual by tier", PRINTED, (D6,), [3, 3, 3, 2, 2], False,
         r"bucket-2 residual\s+=\s+"),
        ("the block: bucket 3", PRINTED, (D6,), [2, 2, 3], False, r"bucket-3 structural =\s+"),
        ("the block: well-run pools and bucket 2's share of them", PRINTED, (D6,), [2, 2, 0, 0], False,
         r"well-run pool\s+=\s+"),
        ("A6.15's bucket-2 residuals and the pool, group 6's doc", PRINTED, (D6,), 2, False,
         r"Bucket 2's residual is\s+"),
        ("A6.15's bucket 3, group 6's doc", PRINTED, (D6,), 3, False, r"held at its current\s+"),
        ("A4.02's bucket 2 in gross, group 6's doc", PRINTED, (D6,), 3, False, r"of the bucket pool,\s+"),
        # ---- A6.11, which adds its residuals to A6.15's pools
        ("A6.15's controls-only pool in A6.11, row", PRINTED, ("A6.11",), 2, False, r"controls-only = # pool\s+"),
        ("A6.15's full pool in A6.11, row", PRINTED, ("A6.11",), 2, False, r"full \(with #\) =\s+"),
        ("A6.15's controls-only pool in A6.11, group 6's doc", PRINTED, (D6,), 2, False, r"controls-only = #'s pool\s+"),
        ("A6.15's full pool in A6.11, group 6's doc", PRINTED, (D6,), 2, False, r"full \(with #\) =\s+"),
        # ---- A4.08: achievable pair, current, y3 deltas; and the rows and docs that print them
        ("A4.08's achievable pair at each tier's prevention, row", PRINTED,
         ("A4.08",), 3, False, r"controls-only \(prevention\s+"),
        ("A4.08's current, row", PRINTED, ("A4.08",), 3, False, r"concentration = \$"),
        ("A4.08's y3 deltas, per dollar and in $K, row",
         PRINTED, ("A4.08",), [3, 3, 0, 0], False,
         r"of gross\):\s+\$"),
        ("A4.08's achievable pair, group 6's doc", PRINTED, (D6,), 2, False,
         r"prevention = \*\*\$"),
        ("A4.08's y3 deltas, group 6's doc",
         PRINTED, (D6,),
         [3, 3, 2, 2, 0, 0], False, r"\*\*y3 deltas\*\*\s+\S+\s+\$"),
        ("A4.08's y3 deltas, group 6's list of what it resolves",
         PRINTED, (D6,),
         [3, 3, 0, 0, 2, 2], False, r"\*\*y3 deltas\*\* \$"),
        ("A4.08's achievable pair, the pool and the y3 deltas, A9.06",
         PRINTED, ("A9.06",), [3, 3, 2, 3, 3], False,
         r"achievable endpoints \$"),
        ("A4.08's current, A9.06", PRINTED, ("A9.06",), 3, False, r"[\d.]+ = \$(?=[\d.]+ / )"),
        # group 9's doc prints it twice, and both went stale unread (U14 short record, owner, 2026-11-03, DECISIONS#u14)
        ("A4.08's current, group 9's doc, the flag and the closing list", PRINTED, (D9,), 3, False,
         r"current term on those rates is \$|current\*\* becomes \$"),
        ("A4.08's y3 deltas and the pool, group 9's doc", PRINTED, (D9,),
         [3, 3, 2], False, r"achievable endpoints are \*\*\$"),
        ("A4.08's y3 deltas, group 9's list of what it closes", PRINTED, (D9,), 3, False,
         r"with y3 deltas \$"),
        ("A4.08's y3 deltas, group 10's doc", PRINTED, (D10,), 3, False, r"since restated to \$"),
        ("A4.08's y3 deltas, the A10.17-bands decision", PRINTED, (E("A10.17-bands"),), 3, False,
         r"since restated to \$"),
        # ---- A6.06's paragraph in the group-6 doc, which the row's restatement of 2026-09-17 left behind
        ("A6.06 bucket 2 in the group-6 doc", PRINTED, (D6,),
         [1] + [0] * 10, False, r"Bucket 2 \("),
        ("A6.06 bucket 1 in the group-6 doc", PRINTED, (D6,),
         [1] + [0] * 10, False, r"Bucket 1 \("),
        # ---- the decision that records the restatement prints its results as current
        ("A6.26's `none`, the chain decision", PRINTED, (E("A6.26-chain"),), 1, False, r"none[^.]{0,40}?[\d.]+ -> \*\*"),
        ("controls-only prevention, the chain decision", PRINTED, (E("A6.26-chain"),), 3, False, r"controls-only[^.]{0,60}?[\d.]+ -> \*\*"),
        ("full prevention, the chain decision", PRINTED, (E("A6.26-chain"),), 3, False, r"Full prevention is\s+"),
        ("A6.15's well-run pools, the chain decision", PRINTED, (E("A6.26-chain"),), 2, False,
         r"well-run pools are \*\*"),
        ("A4.09's achievable pair, the chain decision", PRINTED,
         (E("A6.26-chain"),), 2, False, r"achievable pair is\s+\*\*"),
        ("A4.08's controls-only endpoint, the chain decision", PRINTED, (E("A6.26-chain"),), 3, False,
         r"controls-only endpoint is \*\*\$"),
        ("A4.08's y3 deltas in $K, the chain decision", PRINTED,
         (E("A6.26-chain"),), 0, False, r"deltas \*\*~\$"),
    ]


D05 = "docs/brainstorms/realism-regen-2026/05-spec-r6-po-lifecycle.md"


def _restated_21_figures(E):
    """THE 21 RESTATED ROWS, watched 2026-09-23: every derived figure DECISIONS#restating-the-21 and A9.02's derived
    achievable (81f7705) put into a row or a doc, where no entry already watched it.

    The restatement put each row's figures back on the generator; nothing held them there. A mutation pass over
    every restated passage, one unit on each figure, found most of them read by no check -- A9.02's COGS, its price
    band, the whole of its new achievable block, A9.13's gap and ladder, the group-4 and group-5 docs' copies. The
    group-9 and group-10 checks read with carries(), and probe_figure_checks has never read those lists, so the
    entries are here, where every one of them is probed (#probe-before-trust). Each points at the row that owns the
    quantity and at the present-tense sentences that copy it, never at a dated record
    (#watched-figure-present-tense). What is not watched is named, with its price, in group11_figures' docstring.
    The inputs these entries read beyond the generators' outputs are mirrored in check_generator_mirrors:
    group10_floors' A906_DISPUTE_FTE and A201_LINE, and the constants G.achievable() takes from A1.01, A4.01, A4.06, A4.07, A4.14,
    A4.15, A4.31 and A8.11. Four literals stay in the values, each named where it is used: the price band's corners
    and the capex band's ends, which group 9's _values() runs; the 25% count rate A4.06 tests; and A7.28's 0.7
    band top. Since U21 every value is computed in the generators' _printed_restated_21 and read here under the
    entry's label; the entries keep their places and locators.
    """
    D2, D3, D4, D5, D7, D9, D10 = GROUP2_DOC, GROUP3_DOC, GROUP4_DOC, GROUP5_DOC, GROUP7_DOC, GROUP9_DOC, GROUP10_DOC
    reg = dict((r["anchor_id"], r) for r in yaml.safe_load(rd(REGISTRY)))
    m16 = re.search(r"(\d+)% y1 -> (\d+)% y3", str(reg["A7.16"]["value"]))
    m19 = re.search(r"per-category monthly range ([\d.]+)-([\d.]+)", str(reg["A7.19"]["value"]))
    if not (m16 and m19):
        raise AssertionError("A7.16 or A7.19 no longer prints the figure 03's gate copies; re-anchor the watch")
    promo03 = [float(m16.group(1)), float(m16.group(2))]
    season03 = (float(m19.group(1)), float(m19.group(2)))
    # A10.19 and A10.07 on U16's daily ledger (owner, 2026-10-22, DECISIONS#u16-daily-ledger): the months the locators
    # name are the derived dates' own, read from group 10's outputs like the figures
    DT = _pv("the dates U16's daily ledger derives")
    MON = calendar.month_name
    D8 = GROUP8_DOC
    out = [
        # ---- A9.02: the P&L lines the restatement moved
        ("A9.02's COGS, $M, the row and group 9's P&L block", PRINTED, ("A9.02", D9), 3, False,
         r"(?:less COGS, slotting's in-kind share at cost inside it,|back-cast price\))\s+"),
        # 2026-10-20 (U18): A9.13's working-capital growth by component, y2 then y3, in its plausibility_anchor
        ("A9.13's working-capital growth by component, y2 then y3",
         PRINTED, ("A9.13:plausibility_anchor",), 3, False,
         r"In y2 receivables add\s+"),
        # U18 Q5 (2026-10-15): slotting off net, then net revenue; the invoiced share below gross profit
        ("A9.02's slotting deducted, free-fill, then net revenue, the row",
         PRINTED, ("A9.02",), 3,
         False, r"deducted share at Kroger and Regional\s+"),
        ("A9.02's slotting deducted, free-fill, then net revenue, group 9's P&L block",
         PRINTED, (D9,), 3,
         False, r"slotting deducted \(#, #\)\s+"),
        ("A9.02's slotting invoiced, the row and group 9's P&L block", PRINTED,
         ("A9.02", D9), 3, False, r"(?:an expense,|slotting invoiced \(#\))\s+"),
        # U18 Q6 (2026-10-19): A4.31 derived from A4.18's events and A4.33's wrong-rate billbacks
        ("A4.31's derived share of billback+MCB dollars, then of gross", PRINTED,
         ("A4.31",), [2, 3], False, r"at the wrong rate\) =\s+"),
        ("A4.31's event terms: phantom, then double-funded, at A4.18's midpoints",
         PRINTED, ("A4.31",), 1, False, r"band, |at the midpoint of its [^,]*, "),
        ("A4.31's and A4.33's wrong-rate term, % of billback+MCB dollars",
         PRINTED, ("A4.31", "A4.33"), 2,
         False, r"of the authorized claim,\s+|% x \d+% =\s+"),
        ("A4.31's dollars by window year", PRINTED, ("A4.31",), 3, False,
         r"that is \$"),
        ("A10.14's deduction floor: the bucket pool, A4.01's y3 line, A4.31's invalid share, the row and group 10's doc",
         PRINTED, ("A10.14", D10), [2, 2, 3],
         False, r"deductions\s+\**"),
        ("A6.04's invalid MCB claim rate, A4.31's share, the row and group 6's doc", PRINTED,
         ("A6.04", "docs/anchors/sourcing/group-6-error-ledger.md"), 1, False, r"invalid MCB claim\s+"),
        ("A4.33's overbill: the spread in points, then its share of the authorized claim",
         PRINTED, ("A4.33",), [1, 0], False, r"band midpoints:\s+"),
        ("A4.17's free-fill doors at the distributor-served independents, then A7.04's doors",
         PRINTED, ("A4.17",), 0, False,
         r"over the catalogue times #'s doors,\s+"),
        ("A9.02's wholesale COGS ratio, the row and A3.02's copy", PRINTED, ("A9.02", "A3.02"), 2, False,
         r"wholesale COGS ratio\s+(?:of\s+)?"),
        ("A9.02's wholesale COGS ratio, group 9's P&L block", PRINTED, (D9,), 1, False, r"wholesale ratio\s+"),
        ("A9.02's price band, EBITDA % of gross at the low corner then the high, the row and group 9's doc", PRINTED,
         ("A9.02", D9), 2, False, r"give-back\) EBITDA is\s+|low corner EBITDA is\s+"),
        ("y3 EBITDA at every point of the price band, A9.02 and group 9's doc", PRINTED, ("A9.02", D9), 2, False,
         r"y3 is\s+(?=[-\d.]+% at EVERY point)|y3 sits at\s+"),
        ("EBITDA as a percent of gross, group 9's A9.02 paragraph", PRINTED, (D9,), 2, False,
         r"derived, with a tolerance\.\**\s+"),
        ("the y3 funding gap's band, A9.02", PRINTED, ("A9.02",), 2, False, r"funding gap runs \$"),
        # ---- A9.02's ACHIEVABLE, derived by group9_ledger.achievable() on 2026-09-23 and printed nowhere a check read
        ("A9.02's achievable, the deduction term: A4.01's line, the bucket pool, A4.31's residual, then each tier's"
         " pool less it, the line, the points and $M",
         PRINTED,
         ("A9.02",), [1, 2, 3, 3, 3, 3, 1, 3, 3, 3, 3, 3, 3, 3], False, r"charges # alone,\s+"),
        ("A9.02's achievable, settlement then own-site DTC, then the total at each tier against y3 EBITDA",
         PRINTED,
         ("A9.02",), [3, 3, 0, 0, 3, 1, 3, 3, 0, 3, 2, 3, 2, 3, 2], False, r"over-settlement goes,\s+"),
        # The OWED sentence's reading of A4.31 in A4.15's excess and A6.15's recovery on it, both from achievable()
        ("A9.02's achievable, owed: A4.31's residual, the full tier if A4.31 sits in A4.15's excess, and A6.15's"
         " recovery on A4.31", PRINTED, ("A9.02",), [3, 2, 3], False,
         r"clears the\s+"),
        ("A9.02's achievable, group 9's doc: the residual, the pool, the line, the three terms, then both tiers"
         " against y3 EBITDA",
         PRINTED,
         (D9,), [3, 3, 3, 1, 3, 3, 0, 0, 1, 3, 2, 3, 3, 2, 3], False, r"#'s bucket-1 residual \("),
        ("A9.02's achievable against current, then its deduction and settlement points of all its points, A9.13 and"
         " group 9's doc", PRINTED,
         ("A9.13", D9), 2, False, r"#'s achievable(?:,| is)\s+"),
        # ---- A9.13's ledger, restated to the generator
        ("A9.14's +200bp default-rate charge, y2 and y3, A9.13", PRINTED, ("A9.13",), 4, False,
         r"default rate -\s+"),
        ("A9.14's +200bp default-rate charge, y2 and y3, group 9's doc and the A9.14 fees marker",
         PRINTED, (D9, E("A9.14-fees")), 3, False, r"default rate,\s+|charges are\s+"),
        ("the y1 stub, dated on the daily ledger, $K, A9.13 and group 9's doc", PRINTED, ("A9.13", D9), 0,
         False, r"default rate costs\s+\$"),
        ("the y3 gap at capex 0.15 / 0.30 / 0.45, A9.13",
         PRINTED, ("A9.13",), 2, False,
         r"gives a y3 gap of\s+"),
        ("the y3 funding gap and its band, A9.13 and group 9's doc", PRINTED, ("A9.13", D9), 2,
         False, r"November peak of y3: \$|November y3 funding gap is\s+\**\$"),
        ("the y1 exceedance absorbed by payment timing: $M, days of COGS, share of an AP run, the run, days of"
         " invoicing", PRINTED,
         ("A9.13", D9), [3, 2, 1, 3, 1], False, r"The\s+(?=[\d.]+ is absorbed)"),
        ("y1's DPO and its days past the co-packers' net 30, A9.13 and group 9's doc", PRINTED,
         ("A9.13", D9), 1, False, r"DPO runs [\d.]+ -> \**"),
        ("the ladder group 10 inherits: days of COGS, then DPO, A9.13 and group 9's doc",
         PRINTED, ("A9.13", D9), [2, 2, 2, 1, 1, 1], False, r"shortfall in\s+\**"),
        ("the peak need over the base in y2 and y3, A9.13", PRINTED, ("A9.13",), 3, False,
         r"BASE as well \(\+"),
        ("the loan under the base at the y1 peak, A9.13 and group 9's doc", PRINTED, ("A9.13", D9), 3,
         False, r"loan sits\s+"),
        # ---- A9.14's rate and A9.13's FCCR, watched 2026-09-30. Until the owner's ruling of that day the all-in rates
        # built on the annual prime means were typed into PRIME_PLUS, and two of those means were wrong (8.36 and 7.38,
        # the latter September 2025's month). The ledger now reads the published months and COMPUTES the all-in rate, so the constants check no
        # longer sees the means or the rate; these entries do. A9.13's FCCR was read by no check at all, and stood at
        # -1.45 / -1.32 against the ledger's y2 and y3.
        ("A9.14's prime annual means, each the mean of its year's published months, the row and group 9's doc",
         PRINTED, ("A9.14", D9), 2, False, r"annual averages\s+(?:\d{4}\s+)?"),
        ("A9.14's prime annual means, the row's figure field", PRINTED, ("A9.14:figure",), 2, False,
         r"annual means\s+"),
        ("A9.14's prime annual means, group 9's sources table", PRINTED, (D9,), 2, False,
         r"Prime rate \|\s+\d{4} avg\s+\*\*"),
        # restated by hand on 2026-09-30, the first time it moved, so it is read from then on (owner)
        ("A9.14's prime annual means, its sources entry", PRINTED, ("A9.14:sources[0].figure",), 2, False,
         r"MPRIME \d{4} avg\s+"),
        ("A9.14's all-in rate, each year's mean plus the spread, the row and group 9's doc",
         PRINTED, ("A9.14", D9), 2, False, r"all-in\s+|Prime \+ [\d.]+% ->\s+"),
        ("A9.13's FCCR, the row and group 9's doc", PRINTED, ("A9.13", D9), 2, False, r"\(FCCR\s+"),
        ("A9.13's y1 FCCR where group 9's doc prints it alone", PRINTED, (D9,), 2, False,
         r"tested and fails \("),
        # The deductions working capital nets, watched 2026-09-30: the accrual stood at 0.638 / 0.767 against the
        # ledger's 0.628 / 0.740, read by no check, while the NWC beside it closed only on the ledger's figures.
        ("A9.13's accrual in unpaid invoices, then the residual net of recovery, the row and group 9's doc",
         PRINTED, ("A9.13", D9), 3, False,
         r"(?:unpaid invoices|accrual)\s+"),
        # ---- A9.12
        ("A9.12's Q4 build, +40% of finished goods, the row and group 9's doc", PRINTED, ("A9.12", D9), 3, False,
         r"(?:DTC peaks|of finished goods) =\s+"),
        ("A9.12's inventory at COGS, then AP, the row and group 9's doc", PRINTED, ("A9.12", D9), 3,
         False, r"Inventory\s+(?:at\s+COGS\s+)?"),
        # Watched 2026-10-01 (owner, #A9.17-tariff): the row printed 2.587 / 3.089 against the ledger's 2.599 / 3.116,
        # read by no check, while the build beside it was read.
        ("A9.12's finished goods, the row", PRINTED, ("A9.12",), 3, False, r"finished goods\s+(?=[\d.]+ / )"),
        # Watched 2026-10-01 (owner, #A9.17-tariff): the row and group 9's doc printed 8.564 / 9.790 against net
        # revenue less COGS of 8.452 / 9.554, read by no check, between two lines that were.
        ("A9.02's gross profit, net revenue less COGS, the row and group 9's doc",
         PRINTED, ("A9.02", D9), 3, False, r"gross profit\s+"),
        # ---- A11.31's plausibility anchor, and the own-site figures it compares a jar with
        ("A11.31's fee a jar against A3.18's price, and its share of it, the plausibility anchor",
         PRINTED, ("A11.31:plausibility_anchor",),
         [2, 2, 0], False, r"\$(?=[\d.]+ a jar against)"),
        ("A8.13's own-site 3PL on a one-time order and a jar, and A8.12's y1 parcel rate, in A11.31's plausibility"
         " anchor", PRINTED, ("A11.31:plausibility_anchor",), [2, 2, 2, 0], False,
         r"own-site 3PL runs \$"),
        # ---- A3.01, A3.02, A3.04
        ("EBITDA at the 2025 base, A3.01", PRINTED, ("A3.01",), 2, False, r"sized increases, EBITDA is\s+"),
        # The DTC term is the cost over the realized price of an own-site jar, blended at y3's S&S share: DTC_COGS's y3,
        # which derives per year from COST_12 and the jar prices since U4 (it was a 0.317 literal).
        ("A3.02's fully loaded cost over gross by channel, the row and group 3's doc",
         PRINTED,
         ("A3.02", D3), 0, False, r"(?:revenue by channel|numerator):\s+WF\s+"),
        ("A3.04's back-cast unit uplift, y1 and y2", PRINTED, ("A3.04",), 0, False,
         r"back-cast price raises y1 units by about\s+"),
        ("A3.04's back-cast unit uplift, whole then to one decimal, the correction marker",
         PRINTED, (E("A3.04-period"),), [0, 1, 0, 1], False,
         r"y1 units rise about\s+"),
        # ---- A4.06 and A9.06: the filing rates, and the FTE a 25% count rate would need
        ("A4.06's count rate at 25%: the FTE of filing it needs, then the FTE registered, A4.06 and group 4's doc",
         PRINTED, ("A4.06", D4), 2, False, r"would need\s+"),
        ("A4.06's count rate at 25%: the FTE of filing it needs, A9.06 and group 9's doc", PRINTED, ("A9.06", D9), 2,
         False, r"would need\s+"),
        ("A9.06's dispute FTE where group 4 cites it", PRINTED, (D4,), 2, False, r"registered at #\s+\("),
        ("A4.06's filing rate by count", PRINTED, ("A4.06",), 1, False, r"(?i:current, by window year):\s+\**"),
        ("A4.06's filing rate by dollar", PRINTED, ("A4.06",), 1, False, r"by COUNT (?:\([^)]*\) )?and "),
        # A ROW'S COPY OF ANOTHER ROW'S FIGURE is read against the generator too (owner, 2026-09-29): the history move
        # found A9.01 carrying A9.02's EBITDA and A9.13's gap from before A9.02 moved, and A9.08 A9.19's retired mean
        ("A9.01's copy of A9.02's EBITDA % of gross and A9.13's y3 funding gap", PRINTED, ("A9.01",), 2,
         False, r"EBITDA\s+(?=-[\d.]+% /)"),
        ("A9.08's mean deduction, A10.17's derived mean", PRINTED, ("A9.08", D9), 1, False,
         r"mean deduction\s+\$"),
        # ...and the two hand-printed arithmetics the move found stale or mis-scaled, now computed (watched, not priced)
        ("A5.02's y3 PO value, Walmart: share, POs, $K a PO, pallets",
         PRINTED,
         ("A5.02:plausibility_anchor", D5), [1, 0, 0, 1], False, r"Walmart at\s+"),
        ("A5.02's y3 PO value, Costco: share, POs, $K a PO, pallets",
         PRINTED,
         ("A5.02:plausibility_anchor", D5), [1, 0, 0, 1], False, r"Costco at\s+"),
        ("A8.15's unfiled carrier-claim dollars, $K", PRINTED, ("A8.15",), 0,
         False, r"orders x \$\d+ = \$"),
        ("A8.18's tickets, then their cost $K",
         PRINTED,
         ("A8.18",), 0, False, r"loaded rate\) ->\s+"),
        ("A4.06's filing rate by count, then by dollar, group 4's doc", PRINTED, (D4,), 1, False,
         r"(?i:current, by window year):\s+\**"),
        ("A9.06's dollar rate, the same capacity filing by size, A9.06 and group 9's doc", PRINTED, ("A9.06", D9), 1,
         False, r"capacity files\s+\**"),
        ("A9.06's dollar rate in group 9's closing list", PRINTED, (D9,), 1, False,
         r"\), (?=[\d.]+ / [\d.]+ / [\d.]+% by dollar overall)"),
        # ---- A10.17: the by-count rate at A9.19's first-registered $600, then at the derived mean; and the
        # absolute-band reading it rejects, beside sigma read as width
        ("A10.17's by-count filing rate at A9.19's first-registered $600, then at the derived mean, group 10's doc",
         PRINTED, (D10,), 1, False, r"filing rate from\s+"),
        # A10.17 prints the retired rate in its history and the current one live (owner, 2026-09-29): a row does
        # not print another row's retired figure as present
        ("A10.17's by-count filing rate at A9.19's first-registered $600, in its history", PRINTED,
         ("A10.17:history",), 1, False, r"filing rate was\s+"),
        ("A10.17's by-count filing rate at the derived mean", PRINTED, ("A10.17",), 1, False,
         r"puts the by-count filing rate at\s+"),
        # A10.17's three means that sat outside their own bands, moved to the band's log-normal mean (owner,
        # 2026-10-13, DECISIONS#u18-rulings Q1): computed by group10_floors.band_mean, so watched here, not typed
        ("A10.17's three moved means, late/OTIF, pricing_error and overage, each its band's log-normal mean",
         PRINTED, ("A10.17",), 2, False,
         r"take their band's log-normal mean: late/OTIF \$"),
        ("A10.17's bands read as absolute: the mean, then sigma read as width and read as absolute",
         PRINTED, ("A10.17", D10), [0, 4, 3], False,
         r"overall mean to \$"),
        # ---- A4.08, A4.09, A4.32 in group 4's doc, which the chain entries read in the rows only
        ("A4.08's current per bucket-pool dollar, with its formula's inputs, group 4's doc",
         PRINTED, (D4,), [2, 4, 2, 2, 3, 3, 3], False,
         r"f1\$ = f2\$ = f\$:\s+"),
        ("A4.08's achievable pair at each tier's prevention, with its formula's inputs, group 4's doc",
         PRINTED, (D4,), [2, 2, 3, 2, 3, 3, 3, 3], False, r"avoided = "),
        ("A4.09's current write-off, group 4's doc", PRINTED, (D4,), 2, False, r"the write-off is\s+\**"),
        ("A4.09's recovered bucket-1 share, then A4.07's rate it reads, group 4's doc",
         PRINTED, (D4,), 4, False, r"dollar-weighted recovery, is\s+"),
        ("A4.32 over the operational pool, then the bucket pool, group 4's doc", PRINTED,
         (D4,), 1, False, r"these give\s+"),
        # ---- A2.01 and A2.02
        ("A2.01's Test A pass rate, then the share that fails, the row and group 2's doc", PRINTED, ("A2.01", D2), 1,
         False, r"(?:that happens in|on different lines:)\s+\**"),
        ("A2.01's Test A: the sets of club designs Costco can accept, then those spanning two lines",
         PRINTED, ("A2.01",), 0, False, r"each of the\s+"),
        ("A2.01's Test A pass rate where group 10 lists it open", PRINTED, (D10,), 1, False,
         r"on different lines\s+—\s+"),
        ("A2.01's Test A pass rate and its sets, the Costco-assortment marker", PRINTED,
         (E("costco-assortment-withdrawn"),), [1, 0, 0], False, r"operative is\s+\**"),
        ("A2.01's window-start catalogue: recipes, those at two sizes, the spice at one, then the SKUs",
         PRINTED, ("A2.01",), 0, False, r"^"),
        ("A2.02's population: designs, then the sellable SKUs at window start, the row and the worklist",
         PRINTED, ("A2.02", WORKLIST), 0, False,
         r"^(?=[\d,]+ designs;)|RESTATED #:\s+(?=[\d,]+ DESIGNS after)"),
        # ---- A5.38, A7.28, A10.02, A10.05
        ("A5.38's surviving accounts that decline: small accounts in y2, then Whole Foods direct in y3", PRINTED,
         ("A5.38", D5), 2, False, r"(?i:small accounts fall)\s+"),
        # 0.7 is A7.28's signed band top, which no generator carries
        ("A7.28's assortment readings above the signed band's 0.7 top",
         PRINTED, ("A7.28", D7, E("A7.28-reporting-share")), 3,
         False, r"(?i:door-weighted y2 at)\s+|door-weighted y2 is\s+\**"),
        ("A10.02's live lines in y3: Whole Foods' 90 line's distance and adjacent-pair risk, then the on-time line's",
         PRINTED, ("A10.02", D10), [2, 2, 1], False,
         r"(?i:and sd: it sits)\s+"),
        ("A10.05's dollars a club-week, then the clubs they are spread over",
         PRINTED, ("A10.05", D10), 0, False,
         r"(?i:dollars per club-week), \$"),
        # ---- A10.16, A11.13, A11.26
        ("A10.16's plausibility at the registered sigma: p90 over p10, then the top decile's mean over the bottom's",
         PRINTED, ("A10.16",), [1, 0], False,
         r"where [\d.]+ gives\s+"),
        ("A11.13's multiples over the window, the envelope its plausibility keeps",
         PRINTED, ("A11.13",), 2,
         True, r"the swell would run\s+"),
        ("a declining size's recipe over its floor, A11.26 and its decision", PRINTED,
         ("A11.26", E("A11.26")), 1, False, r"selling a median\s+"),
    ]
    out += [
        # ---- group 9: the ledger's rows and group 9's doc. A9.13's five series were read by carries() in
        # check_generator_figures, and five went stale in one day because it could not tell which copy was meant.
        ("A9.12's cash conversion cycle, DSO + DIO - DPO, the row", PRINTED, ("A9.12",), 1, False, r"DSO \+ DIO - DPO =\s+"),
        ("A9.12's cash conversion cycle y1 -> y3, group 9's doc", PRINTED, (D9,), 0, False,
         r"DSO \+ DIO - DPO =\s+"),
        ("A9.12's trough: the mean DSO at which Q4 collects", PRINTED, ("A9.12", D9), 0, False,
         r"#'s DSO, about\s+"),
        ("A9.12's build on the line, in months", PRINTED, ("A9.12", D9), 1, False,
         r"DPO \+ DSO, about\s+"),
        ("A9.14's finished goods at the November peak", PRINTED, ("A9.14",), 3,
         False, r"at the November peak\s+"),
        ("A9.14's sizing: the projected y2 base, and the margin the $4.5M commitment clears it by",
         PRINTED, ("A9.14", D9), [3, 1], False,
         r"(?i)projected y2 peak base of \$"),
        ("A9.14's sizing, the November y1 amendment's present note: the y2 base, the margin, the upsize against the"
         " base examined, that base",
         PRINTED,
         (E("nov-y1-amendment"),), [3, 1, 1, 3], False, r"projected y2 base \$"),
        ("A9.14's base examined at the November y1 peak", PRINTED, ("A9.14", D9), 3, False,
         r"(?i)against the \$"),
        ("A9.14's y3 base", PRINTED, ("A9.14", D9), 3, False, r"y3 base of \$|y3's \$"),
        ("A9.14's November-peak base by year, group 9's doc", PRINTED, (D9,), 3, False,
         r"November-peak base\s+\**\$"),
        ("A9.14's November y1 peak need, the row", PRINTED, ("A9.14",), 2, False, r"peak need of \$"),
        ("A9.14's November y1 peak need, group 9's doc", PRINTED, (D9,), 3, False, r"November y1 peak of \$"),
        ("the peak need against the base from y2, A9.14 and group 9's doc",
         PRINTED, ("A9.14", D9), 3, False,
         r"FROM y2 ON: peak need\s+|passes it —\s+"),
        ("A9.13's cash from operations", PRINTED, ("A9.13", D9), 3, False, r"(?i)cash from operations\s+"),
        ("A9.13's standing draw at year end", PRINTED, ("A9.13", D9), 3, False,
         r"(?i)standing draw(?: at year end)?\s+"),
        ("A9.13's interest and fees", PRINTED, ("A9.13", D9), 3, False, r"actual/360\s+"),
        ("A9.13's peak need", PRINTED, ("A9.13", D9), 3, False, r"whole build =\s+|(?i:first half of November)\s+"),
        ("A9.13's excess availability", PRINTED, ("A9.13", D9), 3, False,
         r"#'s base\)\s+|(?i:excess availability)\s+\**"),
        ("A9.13's y1 commitment shortfall: the peak need, the base, the collateral unused",
         PRINTED, ("A9.13", D9), 3, False,
         r"peak need\s+(?=[\d.]+ against a)"),
        ("A9.02's EBITDA as a percent of gross, the row", PRINTED, ("A9.02",), 2, False, r"M = (?=-?[\d.]+% / )"),
        # the copy sat at 7.617 / 8.953 / 10.391 through U4's cascade, and the gate's only signal was a WARN
        ("A9.02's copy of A9.01's opex", PRINTED, ("A9.02",), 3, False, r"carried as a literal\)\s+"),
        ("A9.02's gross profit as a share of gross, y1 -> y3", PRINTED,
         ("A9.02",), 1, False, r"gross profit [\d.]+ / [\d.]+ / [\d.]+ \("),
        ("A9.02's gross profit and its shares of gross and net y1 -> y3, group 9's P&L block",
         PRINTED, (D9,), [3, 3, 3, 1, 1, 0, 0], False, r"gross profit\s+"),
        ("A9.02's EBITDA and its share of gross, group 9's P&L block", PRINTED, (D9,), [3, 3, 3, 2, 2, 2],
         False, r"= EBITDA\s+"),
        ("A9.02's EBITDA share of gross, group 9's headline", PRINTED, (D9,), 2, False, r"deepens:\s+"),
        ("group 11's costs, group 9's A9.02 paragraph", PRINTED, (D9,), 3, False,
         r"costs total\s+"),
        # its A9.01 paragraph's copy; the P&L block's is read by "group 11's costs, row by row" (one site, one entry)
        ("A11.12's write-offs as A9.02 reads them, group 9's doc", PRINTED, (D9,), 3,
         False, r"#'s write-offs\s+"),
        ("A9.02's DTC COGS by year", PRINTED, ("A9.02",), 2, False,
         r"#'s\s+(?=[\d.]+ / [\d.]+ / [\d.]+% on DTC)"),
        ("A9.02's derivation of A8.11's contribution: y3 margin, shipping, fulfilment, payment, achievable, current y3",
         PRINTED, ("A9.02",), 0, False, r"y3 margin of\s+"),
        # y3 is 8,092.46, near the print boundary
        ("A9.06's deduction counts", PRINTED, ("A9.06", D9), 0, False,
         r"against\s+\**(?=[\d,]+ / [\d,]+ / [\d,]+\** deductions)"),
        ("A9.08's loaded analyst: the wage share, then the loaded cost", PRINTED, ("A9.08",),
         [3, 0], False, r"wage share\s+"),
        ("A9.08's recovery per dispute-hour, bucket-1 then achievable, each beside the rate it reads, the row",
         PRINTED, ("A9.08",), [4, 0, 3, 0],
         False, r"on bucket-1 disputes at\s+"),
        ("A9.08's recovery per dispute-hour, bucket-1 then achievable, each beside the rate it reads, group 9's doc",
         PRINTED, (D9,), [0, 4, 0, 3], False,
         r"\$(?=[\d.]+/h on bucket-1 work)"),
        ("A9.08's hire-me return: the analyst's hourly cost, the bucket-1 recovery, the multiple",
         PRINTED, ("A9.08", D9), [0, 0, 1], False, r"An analyst at \$"),
        ("A9.15's deductions per invoice, y1 -> y3", PRINTED,
         ("A9.15", D9), 1, False, r"at\s+(?=[\d.]+ -> [\d.]+ deductions per invoice)"),
        ("A9.11's mix-weighted wholesale days, then blended at A8.01's DTC share",
         PRINTED, ("A9.11", D9), 2, False,
         r"days above\)\s+|days of gross —\s+"),
        ("A9.19's mean, median and sigma, group 9's doc", PRINTED, (D9,), [1, 1, 4],
         False, r"The mean is\s+\**\$"),
        ("A9.19's dollar shares of the largest half and the largest tenth, group 9's doc",
         PRINTED, (D9,), 1, False,
         r"largest half carries\s+\**"),
        ("A9.09's broker-managed share, group 9's doc", PRINTED, (D9,), 0, False,
         r"broker-managed\s+(?=\d)"),
        ("A9.09's broker cost, the row and group 9's doc", PRINTED, ("A9.09", D9), 3, False, r"Cost \**\$"),
        # ---- A8.11, derived exact since U4 (owner): the row's current and achievable are _a811_mirror's
        ("A8.11's DTC COGS by window year", PRINTED, ("A8.11",), 2, False, r"DTC COGS is\s+"),
        ("A8.11's blended product margin y1 -> y3, the row and group 8's doc",
         PRINTED, ("A8.11", GROUP8_DOC), 0, False, r"blended\s+"),
        ("A8.11's contribution before marketing y1 -> y3, group 8's doc",
         PRINTED, (GROUP8_DOC,), 0, False,
         r"contribution before marketing\s+"),
        # ...and the doc's opening summary, which capitalises it: the locator above never read it, and it kept 22% -> 19%
        ("A8.11's contribution before marketing y1 -> y3, group 8's opening summary",
         PRINTED, (GROUP8_DOC,), 0, False,
         r"Contribution before marketing\s+\**"),
        ("A8.11's achievable contribution, group 8's doc", PRINTED, (GROUP8_DOC,), 0, False,
         r"right-sized cartons\s+->\s+contribution\s+"),
        # ---- group 8's slice on scripts/group8_dtc.py (U4, 2026-10-02, DECISIONS#group8-slice): own-site counts, the
        # one-month dispute lag and each network on its own disputes
        ("A8.02's own-site orders: one-time, S&S, then total, the row and group 8's doc",
         PRINTED, ("A8.02", D8), 0,
         False, r"one-time\s+"),
        ("A8.02's new customers, the row and group 8's doc", PRINTED, ("A8.02", D8), 0,
         False, r"one-time orders =\s+|a growth brand — so\s+"),
        ("A8.03's own-site orders a month", PRINTED, ("A8.03", D8), 0, False,
         r"orders / 12 =\s+|generated\.\*\*\s+"),
        ("A8.03's chargebacks a month at A8.04's rate", PRINTED,
         ("A8.03", D8), 0, False, r"[=:]\s+(?=\d+ / \d+ / \d+ (?:a month )?on average)"),
        # A8.03's drift, one peak rate a window year (owner, 2026-10-13, DECISIONS#u18-rulings Q2)
        ("A8.03's peak-month chargebacks on the drift",
         PRINTED, ("A8.03", D8), 0, False,
         r"gift orders\)\s+|on average,\s+"),
        ("A8.03's Visa ratio in its worst month", PRINTED, ("A8.03", D8), 2,
         False, r"every January \(at most\s+"),
        ("A8.03's most Visa disputes VDMP sees at the signed mix", PRINTED,
         ("A8.03", D8), 1, False, r"in any month (?:VDMP covers )?is\s+"),
        ("A8.03's most Visa disputes VDMP sees at the band's worst corner, the watched near-miss",
         PRINTED, ("A8.03", D8), 1, False, r"mix and\s+"),
        ("A8.03's Mastercard ratio at most", PRINTED, ("A8.03", D8), 2,
         False, r"chargeback rate itself,\s+"),
        ("A8.03's most Visa disputes VAMP sees", PRINTED, ("A8.03", D8), 1,
         False, r"at most\s+"),
        ("A8.06's active own-site subscribers", PRINTED, ("A8.06", D8), 0,
         False, r"subscribers ~"),
        ("A8.10's paid spend, $K", PRINTED, ("A8.10", D8), 1, False,
         r"x \$\d+ = \$|paid marketing \$"),
        ("A8.10's y1 channel P&L across A3.26's band, $K", PRINTED,
         ("A8.10", D8), 1, False, r"band \$\+|band \(\+"),
        ("A8.10's y1 channel P&L at $22: one-time, S&S, paid spend, the result, $K",
         PRINTED, ("A8.10",), 1, False,
         r"one-time contribution \$"),
        ("A8.12's carrier-discount sensitivity: the S&S order, then the y1 P&L, $ and $K",
         PRINTED, ("A8.12", D8), [2, 1], False,
         r"S&S (?:contribution )?\$?\+"),
        ("A8.12's unrecovered surcharges, $K", PRINTED, ("A8.12", D8), 1, False,
         r"passed on (?:=|->|→) \**\$"),
        ("A8.17's flat month, then Q4's share of the year", PRINTED, ("A8.17", D8), [4, 2],
         False, r"flat at\s+"),
        # ---- 03's five pre-registered gates (U6, 2026-10-03): value + anchor, each read against its source. Test A and
        # the exits' pass mark are the draw's; the promo share and the seasonality band are A7.16's and A7.19's own
        # registered figures, read from the rows. "At least one pre-window quarter" is words, and A7.09 prints them.
        ("03's gate: Test A's pass rate (A2.01, A11.18)", PRINTED, (REGEN_SCOPE_DOC,), 1, False, r"passes in\s+"),
        ("03's gate: catalogue exits at R4's pass mark, the new-products row", PRINTED, (REGEN_SCOPE_DOC,), 0, False,
         r"floor; catalogue exits at or above\s+"),
        ("03's gate: catalogue exits at R4's pass mark, the gates row", PRINTED, (REGEN_SCOPE_DOC,), 0, False,
         r"floor / catalogue exits at or above\s+"),
        ("03's gate: the share of measured units on promotion, y1 then y3 (A7.16)", promo03, (REGEN_SCOPE_DOC,), 0,
         False, r"share of measured units on promotion\s+"),
        ("03's gate: the per-category monthly seasonality range (A7.19)", [season03], (REGEN_SCOPE_DOC,), 2, True,
         r"Monthly index\s+"),
        # ---- A5.07's probabilistic floor (owner, 2026-10-05): the window floors' miss odds, as group10_floors prints
        ("A5.07's window miss odds, retailer order cancels",
         PRINTED,
         ("A5.07",), [2, 1, 1, 0, 0, 0], False, r"retailer order cancels:\s+Kroger\s+"),
        ("A5.07's window miss odds, Cinderhaven order cancels",
         PRINTED,
         ("A5.07",), [1, 1, 1, 0, 0, 0, 0, 0], False, r"Cinderhaven order cancels:\s+UNFI\s+"),
        # line-level per account from A5.08's mix (owner, 2026-10-06): the rates, then the window floors' odds
        ("A5.07's line-level rates by account, retailer then Cinderhaven",
         PRINTED,
         ("A5.07",), [2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3, 2, 3, 2, 2, 2, 2], False,
         r"retailer / Cinderhaven: Walmart\s+"),
        ("A5.07's window miss odds, line-level: retailer then Cinderhaven, then Regional's Cinderhaven",
         PRINTED,
         ("A5.07",), [1, 1, 0, 0, 0, 0, 0, 0, 1], False, r"line-level, retailer then\s+Cinderhaven: Whole Foods\s+"),
    ] + [
        # 05:154's revision-presence odds (owner-signed 2026-10-20): each (leg, basis) group in the function's own
        # order, every leg at 1% and above, so a leg crossing 1% adds a value the doc must print
        ("05:154's revision-presence odds, %s, %s" % (name, basis), [n for _, n in grp], (D05,), 1, False,
         r"%s, %s, %s\s+" % (name, basis, grp[0][0]))
        for name, basis, grp in _pv("05:154's revision-presence groups: (leg, basis, [(account, one in N)]), by "
                                    "falling odds")
    ] + [
        ("A5.07's worst in-year miss under a per-year floor", PRINTED, ("A5.07",), 1, False,
         r"worst year's\s+miss is\s+"),
        # ---- disaster 1 at its own year's cost (U6, 2026-10-03): the week-32 y2 event prices at Walmart's 2024 cost,
        # A3.04 back-cast on its realized increase; the price is the y2 shelf over 12, so it holds while the cost moves
        ("A3.14's Walmart 2024 cost a unit, then its case cost", PRINTED, ("A3.14",), [2, 1], False,
         r"prices at Walmart's 2024 cost[^:]*:[^,]*,\s+"),
        ("A3.14's erroneous cost per each, the 2024 markup, the erroneous price",
         PRINTED, ("A3.14",), [3, 1, 2], False,
         r"Erroneous price = \(\$[\d.]+ / [\d,]+\) x \([\d.]+ / [\d.]+\) = \$"),
        ("A3.15's pricing_error deduction a unit at Walmart's 2024 cost", PRINTED, ("A3.15",), 2,
         False, r"x U_po = \$"),
        ("A3.14's 2024 case cost, group 3's doc", PRINTED, (D3,), 1, False, r"2024 case cost\*\*:[^=]*= \*\*\$"),
        ("A3.14's erroneous cost per each, group 3's doc", PRINTED, (D3,), 3, False,
         r"Erroneous cost per each \| [\d.]+ ÷ \d+ \| \*\*"),
        ("A3.14's 2024 markup, group 3's doc", PRINTED, (D3,), 1, False,
         r"realized item markup, 2024 \| [\d.]+ ÷ [\d.]+ \| "),
        ("A3.15's deduction a unit, group 3's doc", PRINTED, (D3,), 2, False,
         r"\*\*(?=[\d.]+ × U_po)"),
        # ---- groups 4 and 5 on group 10's generator
        ("A10.11's y3 fines where A4.05 and group 4 read them: the total, its share of the pool, the ratio",
         PRINTED,
         ("A4.05", D4), [4, 2, 2], False, r"derive\s+\**\$"),
        ("A5.07's late cancels: POs a year, then their share of POs, A5.07, A5.10 and group 5's doc",
         PRINTED, ("A5.07", "A5.10", D5), [2, 2, 2, 3, 3, 3], False,
         r"on-time:\s+\**|at every account,\s+"),
        ("A5.11's internal fill, exact", PRINTED, ("A5.11",), 4, False, r"capped at \d+\)\s+"),
        ("A5.11's retailer-scored in-full, exact", PRINTED, ("A5.11",), 4, False, r"over-ship\)\s+"),
        # A5.12's fifth term (owner, 2026-10-06): retailer_increase and its band on A5.04's +20-50%, then the identity's
        # aggregate short-ship and the two fills it moves, at the row's printed precision
        ("A5.12's retailer_increase and its band",
         PRINTED,
         ("A5.12",), [2, 1, 2, 2, 2, 1], False, r"retailer_increase\s+"),
        # over_ship's 0.3 / 0.5 are A5.13's, which no generator transcribes: two literals, named here
        ("A5.12's aggregate short-ship",
         PRINTED,
         ("A5.12",), [1, 0], False, r"os - ri =\s+"),
        ("A5.12's internal fill", PRINTED, ("A5.12",), 0, False, r"cr \+ ri\) =\s+"),
        ("A5.12's retailer-scored in-full", PRINTED, ("A5.12",), 0, False, r"rr \+ ri\) =\s+"),
        # ---- A10.19, the equity call, on U16's daily ledger (owner, 2026-10-22, DECISIONS#u16-daily-ledger): its size and
        # band, the edge, what it pays off, the Dec 31 draws and interest it leaves, its compounding coupon, and the
        # counterfactual. Dates as whole words are check_daily_dates'; their days are read here.
        ("A10.19's size at the signed D0, then its band over D0, and the day each band end dates the note",
         PRINTED, ("A10.19",),
         [2, 2, 2, 1, 0, 0], False, r"after it lands - \$"),
        ("A10.19's size and band, group 10's doc", PRINTED, (D10,), 2, False,
         r"after it lands — \$"),
        ("A10.19's cushion, A9.14's y3 trigger", PRINTED, ("A10.19",), 2, False, r"springing trigger, \$"),
        ("A10.19's hold day", PRINTED, ("A10.19",), 0, False, r"45-day hold on %s\s+" % MON[DT["hold"].month]),
        # the band's cost-index term (owner, 2026-10-25, DECISIONS#u14)
        ("A10.19's cost-index term, $M for CALL_COST_POINTS of A9.16's 2023 cost level", PRINTED, ("A10.19",), 3,
         False, r"COST-INDEX TERM:\s+\$"),
        ("A10.19's edge: y2's worst at the run before, the date and size it gives, then the run after",
         PRINTED, ("A10.19",), [0, 0, 2, 0], False, r"the worst is\s+"),
        # ...and group 10's doc beside the row: its paragraph went unread through U14's batch 3 and stayed stale
        # (owner, 2026-11-02, DECISIONS#u14: a print a cascade moved outside the gate's reach is watched once found)
        ("A10.19's release: the held invoices it pays, then the cash-in-advance orders", PRINTED,
         ("A10.19", D10), [2, 3], False, r"The note pays the\s+\$"),
        ("A10.19's Dec 31 draw in y2 and y3 with the note, its line interest and fees, then the annual ledger's",
         PRINTED, ("A10.19", D10), [3, 2, 3, 3, 3, 3], False, r"Dec 31 draw is\s+\$"),
        ("A10.19's coupon in y2 and y3, compounding, in $K", PRINTED,
         ("A10.19", D10), 0, False, r"THE COUPON: \$|The coupon:\*\* \$"),
        ("A10.19's y3 fixed-charge ratio with the note", PRINTED, ("A10.19", D10), 2, False,
         r"fixed-charge ratio of\s+"),
        ("A10.19's counterfactual: availability after it, y3 interest and fees, its coupon in y2 and y3",
         PRINTED,
         ("A10.19", D10), [3, 3, 0, 0], False, r"bottoms at\s+\$"),
        ("A10.19's counterfactual date, the row and A10.07", PRINTED, ("A10.19", "A10.07"), 0, False,
         r"the same note on %s\s+" % MON[DT["counterfactual"].month]),
        ("A9.02's below-EBITDA coupon in y2 and y3, then the counterfactual's, in $K",
         PRINTED,
         ("A9.02",), 0, False, r"compounding from that date,\s+\$"),
        # ---- A10.07 on the daily ledger: the oldest invoice's worst days, the consequences' days, the edge, the
        # release, the hold-cut fit net of cover with the gross slip beside it (owner, 2026-10-22)
        ("A10.07's oldest unpaid invoice at worst, y1 / y2 / y3, the line's own cash", PRINTED,
         ("A10.07",), 0, False, r"runs at worst\s+"),
        ("A10.07's y1 priority-loss day", PRINTED, ("A10.07",), 0, False,
         r"PRIORITY LOSS on %s\s+" % MON[DT["chain_first"][0]["priority"].month]),
        ("A10.07's y2 days: priority loss, the late fee, the hold",
         PRINTED, ("A10.07",), 0, False,
         r"y2 reaches priority loss on %s\s+" % MON[DT["chain_first"][1]["priority"].month]),
        ("A10.07's y2 edge: the run before, then the run after", PRINTED, ("A10.07",), 0,
         False, r"oldest invoice peaks at\s+"),
        ("A10.07's release: the held invoices the note pays, then the cash-in-advance orders", PRINTED,
         ("A10.07",), [2, 3], False, r"and pays the\s+\$"),
        ("A10.07's hold-cut fit: the co-packers' share", PRINTED, ("A10.07",), 0, False,
         r"the co-packers' "),
        ("A10.07's hold-cut fit: the co-pack lead it slips by", PRINTED,
         ("A10.07",), 0, True, r"\(#\) slips\s+"),
        ("A10.07's hold-cut fit: the cover in days, then the net cut's ends",
         PRINTED, ("A10.07",), [1, 0, 2], False,
         r"and the\s+(?=[\d.]+ days of finished goods)"),
        ("A10.07's hold-cut fit: y3's allocation_shortage budget, then A5.10's share and A5.12's rate",
         PRINTED, ("A10.07",), [2, 0, 1], False,
         r"allocation_shortage share of\s+"),
        ("A10.07's hold-cut fit: the gross co-pack slip the cover absorbed",
         PRINTED, ("A10.07",), 2, False,
         r"gross slip of\s+"),
        ("A10.07's hold-cut fit: the materials' share", PRINTED, ("A10.07",), 0, False,
         r"The materials' "),
        ("A10.07's hold-cut fit: the in-house lead the materials slip by",
         PRINTED, ("A10.07",), 0, True, r"slips in-house\s+"),
        ("A10.07's hold-cut fit: the materials' gross slip", PRINTED, ("A10.07",), 2, False,
         r"weeks,\s+(?=[\d.]+ to [\d.]+% gross)"),
        # ---- A9.13 and A9.12 on the daily ledger: Dec 31 positions, its own readings, the dated events
        ("A9.13's Dec 31 positions: the draw on the line, the stretch behind it, the need",
         PRINTED,
         ("A9.13",), 3, False, r"a draw on the line of\s+"),
        ("A9.13's Dec 31 AR, then AP", PRINTED, ("A9.13",), 3,
         False, r"; AR\s+"),
        ("A9.13's daily need at its peak run", PRINTED, ("A9.13",), 3, False, r"November run at\s+"),
        ("A9.13's daily line interest and fees", PRINTED, ("A9.13",), 3, False,
         r"line interest and fees run\s+"),
        ("A9.13's fixed-charge ratio on the daily interest",
         PRINTED, ("A9.13",), 2, False,
         r"ratio on that interest is\s+"),
        ("A9.13's late-fee reading", PRINTED, ("A9.13",), [0, 3, 3], False, r"not charged,\s+"),
        ("A9.13's spring days", PRINTED, ("A9.13",), 0, False,
         r"dates the springs to %s\s+" % MON[DT["springs"][0].month]),
        ("A9.13's part-held runs, then the first one's day", PRINTED,
         ("A9.13",), 0, False, r"part-holds\s+"),
        ("A9.12's trough day, every window year, A9.12 and A9.13", PRINTED,
         ("A9.12", "A9.13"), 0, False,
         r"first at the run of %s\s+" % MON[DT["trough_runs"][0].month]),
        ("A5.02's POs a year, group 5's doc", PRINTED, (D5,), 0,
         False, r"\*\*(?=[\d,]+ / [\d,]+ / [\d,]+ POs)"),
        ("A5.02's order lines a year at A5.37's means, group 5's doc", PRINTED, (D5,),
         0, False, r"POs;\s+"),
        ("A5.02's Walmart POs, group 5's doc", PRINTED, (D5,), 0, False,
         r"Walmart weekly per DC \("),
        ("A5.02's KeHE POs, group 5's doc", PRINTED, (D5,), 0, False, r"KeHE weekly \("),
        ("A5.02's small-account orders, group 5's doc", PRINTED, (D5,), 0, False,
         r"Faire-typical \$[\d,]+ order,\s+"),
        ("A5.32's Walmart DCs, group 5's doc", PRINTED, (D5,), 0, False,
         r"(?i:ship-to points)\*\*[^:]*:\s+Walmart\s+"),
        ("A5.32's KeHE DCs, group 5's doc", PRINTED, (D5,), 0, False,
         r"KeHE\s+(?=\d+ / \d+ / \d+, the fifth)"),
        ("A5.32's DPI DCs, group 5's doc", PRINTED, (D5,), 0, False,
         r"DPI\s+(?=\d+ / )"),
        ("A1.10's roster: retailers then distributors, A5.20", PRINTED, ("A5.20",), 0, False,
         r"retailers per #,\s+"),
        ("A1.10's roster: EDI partners, A5.20", PRINTED, ("A5.20",), 0, False, r"so\s+(?=\d+ / \d+ / \d+ partners)"),
        ("A1.10's roster: retailers, A4.27", PRINTED, ("A4.27",), 0, False, r"RETAILERS\s+"),
        ("A1.10's roster: distributors, A4.27", PRINTED, ("A4.27",), 0, False, r"DISTRIBUTORS\s+"),
        ("A1.10's roster: retailers then distributors, group 4's doc", PRINTED, (D4,), 0, False,
         r"retailers\s+(?=\d+ / \d+ / \d+ by window year)"),
        ("A1.10's roster: retailers, distributors, then partners, group 5's doc", PRINTED, (D5,), 0, False,
         r"retailers\s+(?=\d+ / \d+ / \d+ by window year)"),
        # ---- A10.02's dead in-full drop line (85, Walmart's program line), beside the live lines watched above
        ("A10.02's dead in-full drop line: y3's distance in quarterly sd, that sd, then y2's and y1's",
         PRINTED, ("A10.02", D10),
         [1, 2, 1, 1], False, r"(?i:every window year)\s+[-—]\s+\**"),
    ]
    # A4.05's type mix in group 4's doc, one table row per type: it sat at 22 / 12 / 8 from 2026-09-12 with the gate
    # clean, because the row's mirror reads A4.05 and nothing read the doc's table
    for label, key in (("short_ship", "short_ship"), ("late_delivery / OTIF fines", "late_otif"),
                       ("damaged / unsaleables", "damaged_unsaleables"), ("spoilage / short-dated", "spoilage_shortdated"),
                       ("receiving_miscount", "receiving_miscount"), ("label / pallet / ASN compliance", "label_pallet_asn"),
                       ("pricing_error", "pricing_error"), ("post-audit claims", "post_audit"),
                       ("**overage**", "overage"), ("other", "other")):
        out.append(("A4.05's type mix in group 4's doc, %s" % label.strip("*"),
                    [_pv("A4.05's type mix in group 4's doc, by type")[key]], (D4,), 0,
                    False, r"\| %s \|\s+\**" % re.escape(label)))
    # A5.38's account table in group 5's doc: shares, then dollars on A1.01's index. Every row, not only the two the
    # restatement moved: KeHE and DPI sat stale in it for eight days beside eight rows nothing watched either.
    # Sprouts and Costco print words in the index column, so they carry their shares alone.
    for label, key, places in (("Walmart", "Walmart", [0, 1, 1, 1, 1, 1]), ("Kroger", "Kroger", [0, 0, 1, 1, 1, 1]),
                               ("Whole Foods direct", "WF", [0, 0, 0, 1, 1, 1]),
                               ("Regional", "Regional", [0, 0, 0, 1, 1, 1]), ("UNFI", "UNFI", [0, 0, 0, 1, 1, 1]),
                               ("KeHE", "KeHE", [0, 1, 0, 1, 1, 1]), ("DPI", "DPI", [0, 0, 0, 1, 1, 1]),
                               ("Small accounts", "small", [0, 1, 1, 1, 1, 1]),
                               ("Sprouts direct", "Sprouts", [0, 1, 0]), ("Costco", "Costco", [0, 0, 1])):
        vals = _pv("A5.38's account table in group 5's doc: shares, then dollars on A1.01's index, by account")[key]
        vals = vals[:len(places)]
        out.append(("A5.38's account table in group 5's doc, %s" % label, vals, (D5,), places, False,
                    r"\| %s \|\s+(?=[\d.]+ \| [\d.]+ \| [\d.]+ \|)" % re.escape(label)))
    return out


def _amazon_basis_figures():
    """A3.29's rolled standard and A11.32's two bases and the gap between them (owner, 2026-10-12).

    The margin mart costs a jar at A3.29's standard, rolled once at January 2023; the P&L costs it at A3.01's landed
    cost at A9.16's index and A9.17's tariff, as pnl() does. The gap is a named defect, kept on purpose, so it is
    watched: a printed gap that is not landed less standard on Amazon's units fails. The standard is A3.01's
    manufactured cost times _cost_index()'s 2023 level, to the cent, and the window band runs A11.30's ACoS band:
    group 9 types both inputs since U21 (COST_MANUFACTURED and ACOS_BAND, which _a301_mirror and _a1130_mirror tie to
    their rows' prose) and computes every series in its outputs().
    """
    D = GROUP11_DOC
    return [
        ("A3.29's rolled standard, the mart's cost a jar", PRINTED, ("A3.29",), 2, False, r"ROLLED STANDARD: \$"),
        ("A11.32 on the mart's basis, by window year", PRINTED, ("A11.32", D), 2,
         False, r"(?:MART BASIS, BY WINDOW YEAR:|cogs_per_unit`\s+—\s+the channel is)\s+"),
        ("A11.32 over the window, the mart's all-time row", PRINTED, ("A11.32",), 2, False,
         r"band test read:\s+"),
        ("A11.32's window band, from A11.30's ACoS band", PRINTED, ("A11.32", D), 1,
         False, r"band\s+(?:is\s+)?"),
        ("A11.32 on the P&L's basis, by window year", PRINTED, ("A11.32", D), 1, False,
         r"tariff,\s+(?:BY WINDOW YEAR:|the channel is)\s+"),
        ("A11.32's gap, landed less standard on Amazon's units, points of Amazon sales",
         PRINTED, ("A11.32", D), 1, False,
         r"(?:THE GAP, BY WINDOW YEAR:|The gap,)\s+"),
        ("A11.32's gap in dollars, $K", PRINTED, ("A11.32",), 0, False, r"points of Amazon sales, \$"),
    ]


def group11_figures():
    """Group 11's computed figures and where each is published: (label, values, where, places, pairs, after).

    `where` names a registry row, a document path, or one DECISIONS entry as "DECISIONS.md#<id>", so a figure group 11
    derives is checked in every place that prints it - group 11's doc and rows, the rows and docs of groups 1, 2, 7, 9
    and 10 that the rulings of 2026-09-14 restated, and the entries that record them, the supersede markers included.
    An entry, not the whole log: an older entry printing a retired figure must not satisfy a check on a current one.
    Nothing is solved against a survival target since the second rulings: the lifecycle is DRAWN, and the one solve,
    the account factor's, runs on the window's own carried sets. A figure typed into A11.21 that the draw no longer produces fails, and so
    does a doc a restatement left behind. Computed once per process, because the self-test doctors the text, never the
    generator.

    NOT CHECKED, and named so the gap is visible: A11.23's MAPE-to-sigma conversions of the sources (37%, 46%, 60%),
    A11.25's population share and Walmart's 27 of 3,560 (registered inputs, not outputs), the Internet Archive dates,
    the rationalization table's integer cuts (group 10's report prints them), and the superseded figures the markers
    name as retired.

    AND, added 2026-09-22 with a price rather than a shrug: A11.27's BAND-END SOLVES -- the account factor and
    A7.13's 90-day share at door 0.50 and 0.60. Each end is a twelve-step bisection at 6,000 trials, about 26
    minutes, so watching both would take the gate's cold path from roughly fifteen minutes to over an hour. They
    are remeasured by hand when the level moves and both the row and the doc say they are not watched. Every other
    companion the 2026-09-22 verification found IS watched below; this is the one where the cost is the reason,
    and it is the owner's to overturn.

    AND, added 2026-09-23 with the restatement of the 21 (DECISIONS#restating-the-21), each with what watching it
    would cost. Every other figure the restatement moved is watched in the block headed THE 21 RESTATED ROWS or by
    a mirror in check_generator_mirrors:
      - A3.01's "2025 is the owner's call and the harshest of the three": no generator computes another base year.
        It needs a base-year argument on group9_ledger's _price_index, _cost_index and pnl() -- two more pnl()
        calls, milliseconds -- and the generator edit costs one cold group-11 recompute, about twelve minutes.
      - A5.38's 6% bound, in the row and the group-5 doc's constraint sentence: an owner input no generator holds.
        A gate constant mirrored against A5.38 and an entry on the doc's sentence, about fifteen lines, no runtime.
        The breach it frames, 6.25% and 4.17%, is watched.
      - A7.28's "five of the six": the above-band entry fails if a second reading crosses 0.7 or 0.723 falls back,
        not if a reading drops below 0.5. One boolean, no runtime, but a new check form: _GROUP11_FACTS reads group
        11's doc alone.
      - A10.02's two live lines without a figure -- Kroger's floor delists inside the window (A10.16), and the
        supplier line reaches its 45-day hold in y3 (A10.07): two booleans on group 10's printed delists and
        supplier_chain(), no runtime, in the same new form.
      - A10.08's reaction windows: Walmart, Kroger and Whole Foods 2 quarters, UNFI and KeHE 2 weeks to a
        corrective action plan, suppliers 45 days. No generator computes them; main() prints a string. One
        constant for A10.02's consecutive-period rule and a parser for A10.02's words ("two consecutive
        quarters"), which NUMBER_WORDS does not read; no runtime.
      - A4.32's "over-filled bucket 2 by ~21 points": no generator defines the natural mapping it is measured
        against, so the mapping has to be written as a function before anything can watch the figure.
      - A2.01's premise that the eleven club forecasts are i.i.d., which is what makes 37 of 55 pairs a
        probability: the entries count pairs and cannot see the draw. A split-line counter in group 11's _values() is
        free per trial and costs one cold recompute; a closed-form case drawing eleven i.i.d. forecasts runs in
        seconds with no cache change, but proves the arithmetic, not window_start.
      - PLAN.md's two copies of A2.01's 67.3%: one tuple element and no compute, but the gate has never read the
        plan for a figure, and its tasks are rewritten as they close.
      - "four-fifths", the share of A9.02's achievable gap that is deduction recovery and settlement, in A9.13 and
        group 9's doc: a word, not a number token. The two figures it summarises, 3.59 of 4.49 points, are
        watched; the word needs a one-line boolean of the same new form.

    AND, added 2026-10-01 with U4's restatements (DECISIONS#u4-cascade), each with its price. Every other figure U4
    restated is watched, in the blocks headed U4's RESTATEMENTS here and in check_group10_figures:
      - A9.08's blended $86/h, in the row and group 9's doc: A4.07's blended 0.34 has no computed value; R1_CURRENT
        and R1_ACHIEVABLE are the bucket-1 and achievable rates. It costs a blended-rate function on A4.07's mix in
        group10_floors and one cold recompute. The $129/h, $143/h, $72/h, $106,686 and the 1.8x beside it are
        watched, from hire_return().
      - A8.11's y1 band, 25% / 23% / 21% at $20 / $22 / $24, in the row and group 8's doc: it reads A8.12's printed
        y1 shipping band of 23.0 / 25.0 / 27.0%, which no generator computes, and group 8's own slice re-derives
        A8.12. And A8.11's per-order figures: in the row $12.63 / $9.57 COGS, $+0.18 and $13.58 contribution, a
        $36.975 paid first order and $-43; in group 8's doc $36.98, "+0.18" and "loses $43". They also sit in A8.10. No
        generator computes per-order contribution. The price: a moved jar price, case rate or AOV leaves all of them
        stale with the gate clean, until group 8's slice gives dtc_contribution() a shipping band and an order view.
      - PLAN.md's completed slice-4 item prints A10.16's delists as the slice produced them, 7.01 -> 12.29 and
        Kroger's 10.041: a dated record, not a copy of the draw, so nothing is owed. A U4 draft restated it to today's
        draw and the stale sweep put it back (2026-10-02).
    """
    if _GROUP11:
        return _GROUP11
    D, D1, D2, D7, D9, D10 = GROUP11_DOC, GROUP1_DOC, GROUP2_DOC, GROUP7_DOC, GROUP9_DOC, GROUP10_DOC

    def E(entry):
        return "%s#%s" % (DECISIONS, entry)
    E2, ES, ED, E25, EUS, E902, E109, E18 = (E(x) for x in (
        "A11.21-second-rulings", "sigma-within-set", "A2.09-decline", "A11.25", "undated-sources", "A9.02-reads-group-11",
        "A10.09-exits", "A10.18"))
    EDW = E("door-and-week")   # the entry that records the factor's restated target, 2026-09-16
    R21 = "A11.21"
    cad_mult_p = [2, 1, 1, 1, 2, 3, 3]
    _GROUP11.extend([
        # ---- A4.32 and A6.06, registered as generator outputs 2026-09-17. Both were derived rows
        # that nothing computed; A6.06 had drifted from A4.05's rebalance of 2026-09-12 unseen.
        ("A4.32 over the operational pool, then the bucket pool",
         PRINTED, ("A4.32",), [1, 1, 1, 2, 1, 1, 1],
         False, r"they give\s+"),
        ("A6.06 bucket 2, the within-bucket mix", PRINTED, ("A6.06",), 0, False,
         r"that is bucket 2:\s+short_ship\s+"),
        ("A6.06 bucket 1, the within-bucket mix", PRINTED, ("A6.06",), 0, False,
         r"that is bucket 1:\s+short_ship\s+"),
        # ---- A4.09, registered as derived 2026-09-17. It is two_endpoint and no generator emitted it,
        # which is why its recovered-bucket-1 share went stale unseen; both endpoints are watched now.
        ("A4.09's current write-off, and its achievable pair", PRINTED,
         ("A4.09",), 2, False, r"CURRENT, BY WINDOW YEAR:\s+"),
        ("A4.09's recovered bucket-1 share, the input that went stale", PRINTED, ("A4.09",), 4,
         False, r"recovered per dollar of bucket 1:\s+"),
    ])
    _GROUP11.extend(_a6_chain_figures(E))
    _GROUP11.extend(_a901_opex_figures(E))
    _GROUP11.extend(_amazon_basis_figures())
    _GROUP11.extend([
        # ---- the slice-1 entry: it prints these as current, so it is watched like the rows and docs
        ("the factor and the launch-free solve, the slice-1 decision", PRINTED, (EDW,), P_FACTOR,
         False, r"factor solves to\s+\**"),
        ("A7.13's two shares, the slice-1 decision", PRINTED, (EDW,), P_SHARE, False,
         r"# falls to\s+\**"),   # carries_exact blanks anchor ids, so the locator matches the blank
        ("the 24-month share, the slice-1 decision", PRINTED, (EDW,), P_SHARE, False, r"by 24 months to\s+\**"),
        ("catalogue exits, the slice-1 decision", PRINTED, (EDW,), 2, False, r"catalogue exits to\s+\**"),
        ("A10.16's floor delists, the slice-1 decision", PRINTED, (EDW,), 2, False, r"floor delists to\s+\**"),
        # ---- A11.21: the account factor, both populations
        ("the factor solved on the window, then the launch-free solve, the doc's summary", PRINTED,
         (D,), P_FACTOR, False, r"decline\s+included:\s+"),
        ("the factor on the window and the spread it leaves, doc", PRINTED, (D,), P_FACTOR, False,
         r"spread the account target:\s+\**"),
        ("the launch-free solve, the window's spread at it, and what the draw gives there, doc",
         PRINTED,
         (D,), [P_FACTOR, P_FACTOR, P_SHARE, P_SHARE, P_SHARE, 2, 2, 2], False, r"factor solves to\s+"),
        ("the factor on the window and the spread it leaves, row", PRINTED, (R21,), P_FACTOR, False,
         r"SOLVES TO\s+"),
        ("the launch-free solve and the window's spread at it, row", PRINTED, (R21,), P_FACTOR, False,
         r"it solves to\s+"),
        ("the factor, the launch-free solve and the window's spread at it, the owner's list",
         PRINTED, (D,), P_FACTOR, False, r"carried sets it is\s+"),
        ("the factor and its spread, the decision", PRINTED, (ES,), P_FACTOR, False, r"log-sd is\s+\**"),
        ("the launch-free solve and the window's spread at it, the decision", PRINTED, (ES,), P_FACTOR,
         False, r"measured, it is\s+"),
        ("the factor, the spread it leaves, window-start spreads and the launch-free solve, A10.16",
         PRINTED, ("A10.16",), [P_FACTOR, P_FACTOR, 2, 2, 2, 2, P_FACTOR], False, r"solves to\s+"),
        ("the factor and the launch-free solve, group 10's doc", PRINTED, (D10,), P_FACTOR, False,
         r"solves to\s+\**"),
        ("window-start spreads by account, group 10's doc", PRINTED, (D10,), 2, False, r"account\s+spreads\s+"),
        # ---- A5.28's bound, on the multiplier and on generated volume
        ("A5.28 on the multiplier", PRINTED, (D, R21, ES), cad_mult_p, False, r"cadence (?:of|is)\s+\**"),
        ("A5.28 on the multiplier, then on generated volume, the doc's summary",
         PRINTED, (D,), [2, 2, 1], False, r"cadence of\s+"),
        ("A5.28 on generated volume: the ratio, C runs, the sigmas at the widest and the midpoint",
         PRINTED, (D,), [2, 1, 2, 2],
         False, r"generates, [\d.]+ gives\s+"),
        ("A5.28 on generated volume, row", PRINTED, (R21,), [2, 1, 2, 2], False,
         r"VOLUME the same rule gives\s+"),
        ("A5.28 on generated volume, the decision", PRINTED,
         (ES,), [2, 1, 2], False, r"rule gives\s+"),
        ("A5.28 on both, the owner's list", PRINTED, (D,), [2, 2, 1, 2], False, r"multiplier,\s+"),
        ("A5.28 on the multiplier then on volume, group 10's doc", PRINTED, (D10,),
         [2, 1, 1, 1, 2], False, r"bound\s+—\s+"),
        # ---- A11.21: what derives
        ("the 24-month share, doc summary", PRINTED, (D,), P_SHARE, False, r"cuts remove\s+\**"),
        ("the 24-month share by sigma_pred, the doc's table", PRINTED,
         (D,), P_SHARE, False, r"24 months \|\s+"),
        ("A7.13 at the 90-day check by sigma_pred, the doc's table", PRINTED,
         (D,), P_SHARE, False, r"90-day check \|\s+"),
        ("A7.13 within two years by sigma_pred, the doc's table", PRINTED, (D,),
         P_SHARE, False, r"two years \|\s+"),
        ("R4's 10th percentile by sigma_pred, the doc's table", PRINTED, (D,), 0, False,
         r"percentile \|\s+"),
        ("the launches observed, and the points above 29%", PRINTED, (D,), [2, P_SHARE], False,
         r"share is over the\s+"),
        ("the 24-month share, the launches observed, then at sigma_pred 0.50 and 0.70, row",
         PRINTED, (R21,), [P_SHARE, 2, P_SHARE, P_SHARE], False,
         r"every trial:\s+"),
        ("the 24-month share at sigma_pred 0.50 and 0.70, A11.23", PRINTED, ("A11.23",), 1,
         False, r"# prints\s+"),
        ("the 24-month share, then at sigma_pred 0.50 and 0.70, the decision",
         PRINTED, (E2,), P_SHARE, False, r"seeded trials\)\.\s+\**"),
        ("the 24-month share, A11.24", PRINTED, ("A11.24",), P_SHARE, False, r"In #,\s+"),
        ("the 24-month share, group 10's owner list", PRINTED, (D10,), P_SHARE, False, r"#'s cuts,\s+"),
        ("A7.13 derived: 90-day share, Walmart, Kroger, Whole Foods, two-year", PRINTED, (D, R21, E2), P_SHARE, False,
         r"(?:# derives at|# DERIVES AT)\s+"),
        ("A7.13 derived, where A7.13 and group 7 print it", PRINTED, ("A7.13", D7), P_SHARE, False, r"no decay,\s+\**"),
        ("A7.13's two shares, the doc's summary", PRINTED, (D,), P_SHARE, False, r"practitioner shares\.\*\*\s+"),
        ("A7.13's two shares, the owner's list", PRINTED, (D,), P_SHARE, False, r"# at\s+"),
        ("A7.13 at the 90-day check at sigma_pred 0.50 and 0.70, then at the launch-free factor, the owner's list",
         PRINTED, (D,), P_SHARE, False, r"either input:\s+"),
        ("A7.13 by cohort: 2022's two shares, then the window's",
         PRINTED, (D, R21), P_SHARE, False,
         r"environment, give\s+"),
        ("A2.09's decliners among 39", PRINTED, (D,), 0, False,
         r"decliners\s+—\s+"),
        ("A2.09's decliners among 39, A2.09 and group 2", PRINTED, ("A2.09", D2),
         0, False, r"#'s draw,\s+"),
        ("A2.09's exits over the window, A2.09 and group 2", PRINTED, ("A2.09", D2), 2, False,
         r"run floor\s+[—-]\s+"),
        ("A2.09's exits over the window, the decision, at-risk", PRINTED, (ED,), 2, False, r"At-risk exits\s+"),
        ("A2.09's exits over the window, the decision, fading", PRINTED, (ED,), 2, False, r"and\s+fading\s+exits\s+"),
        # ---- the draw
        ("the exits table, row by row: 2022, window launches, at-risk, fading, other mature, A11.26's pruning, club"
         " packs, total", PRINTED, (D, D10), 2, False, None),
        ("in-window exits and their sum, then each source with the tail's recipe-mates, row",
         PRINTED, (R21,), 2, False, None),
        ("in-window exits and their sum, then each source, A10.09",
         PRINTED, ("A10.09",), 2, False, None),
        # ---- A11.26, the brand's own rationalization, and the counterfactual its plausibility rests on
        ("A11.26's prunes over the window and by year, then by kind: other mature, at-risk, fading, launches",
         PRINTED, (D, "A11.26"), 2,
         False, r"trials:\s+\**"),
        ("A11.26's prunes still carried at an account with a set when they went", PRINTED,
         (D, "A11.26"), 2, False, r"Only\s+"),
        ("the live catalogue at each year's start and at window end, with the rule", PRINTED,
         (D, "A11.26"), 2, False, r"With it the draw gives\s+"),
        ("the live catalogue without the rule, at each year's start and at window end",
         PRINTED, (D, "A11.26"), 2, False, r"inflates it to\s+"),
        ("the mature hazard with the rule, two decimals", PRINTED, (D, "A11.26"), 2, False,
         r"ith the rule the draw's hazard is\s+"),
        # The with-rule arm was watched in four places and the WITHOUT-rule arm in two, so A11.21's copy and the
        # group-11 doc's two others sat a restatement behind while the headline beside them moved (2026-09-22).
        ("the mature hazard without the rule", PRINTED, (D, "A11.26", R21, ED), 2, False,
         r"ithout the rule it is\s+|(?i:the rule off it is)\s+|(?i:off it is)\s+|\(#\), and\s+"),
        # An alternated entry passes on any one match in a site, so a doc that prints a figure twice needs an entry per
        # copy: group 11's owner list carried the 0.45 / 0.28 / 0.50% this arm printed before 2026-09-24 unread
        ("the mature hazard without the rule, group 11's owner list", PRINTED, (D,), 2, False,
         r"#\s+off\s+the\s+hazard\s+is\s+"),
        # ...and the doc's other three copies, one entry each (U4's verifier found the alternation above passing on
        # any one of them)
        ("the mature hazard without the rule, group 11's summary", PRINTED, (D,), 2, False,
         r"with the rule off it is\s+"),
        ("the mature hazard without the rule, group 11's A11.21 section", PRINTED, (D,), 2, False,
         r"with # off it is\s+"),
        ("the mature hazard without the rule, group 11's A11.26 section", PRINTED, (D,), 2, False,
         r"Without the rule it is\s+"),
        ("the mature hazard, group 11's summary", PRINTED, (D,), 1, False, r"the mature set's hazard is\s+"),
        ("the mature hazard, group 11's A11.21 section", PRINTED, (D,), 1, False,
         r"The draw's mature hazard is\s+\**"),
        ("exits over the window and by year without the rule, then R4's pass mark and median there",
         PRINTED, (D, "A11.26"), [2, 2, 2, 2, 0, 0], False,
         r"rule off the draw gives\s+"),
        ("catalogue exits a year, where the summaries print them", PRINTED, (D, D7, E18, E109), 2, False,
         r"drawn:\s+|#\s+—\s+\**|drawn per seed,\s+"),
        ("catalogue exits a year and over the window, the second rulings", PRINTED, (E2,), 2, False,
         r"catalogue exits\s+"),
        ("catalogue exits a year and over the window, group 10's summary table", PRINTED, (D10,), 2,
         False, r"drawn per seed\*\*\s+\|\s+\**"),
        ("launch exits through A11.24", PRINTED, (D, R21), 2, False, r"comes through #,\s+"),
        ("2022's launches that leave before the window", PRINTED, (D, R21, "A7.09", D7), 2, False,
         r"loses\s+|R4 counts[;,]\s+(?:and\s+)?"),
        ("the other mature sizes beside a declining recipe-mate, then all of them, doc", PRINTED,
         (D,), 2, False, r"left\s+—\s+and\s+"),
        ("the other mature sizes, then those beside a declining recipe-mate, the owner's list",
         PRINTED, (D,), 2, False, r"recipe\*\*,\s+"),
        ("R4: the 10th percentile, median, mean and pass mark", PRINTED, (D, R21),
         [0, 0, 2, 0], False, r"percentile of\s+\**"),
        ("R4's pass mark where the gate's readers print it", PRINTED, ("A10.09", "A1.10", D1, D7, D10, E2, E18), 0, False,
         r"10th\s+percentile,?\s+\**"),
        ("A1.10: launches and club packs added, then the net", PRINTED, (D, R21), 2, False, r"club packs,\s+"),
        ("A1.10's net where it is published", PRINTED, (D, "A1.10", D1, E2), 2, False, r"net derives at\s+|net\s+\**"),
        ("A10.18's cuts in the draw, then those on launches", PRINTED, (D, R21, E2, "A10.18"), 2, False,
         r"cuts are\s+|draw are\s+"),
        ("the mature hazard", PRINTED, (D, R21, "A11.20", ED), 1, False,
         r"hazard is\s+\**|mature hazard is\s+\**|against it:\s+\**|in the draw is\s+|mature hazard,\s+|start\s+—\s+is\s+"),
        ("the mature hazard, the owner's list", PRINTED, (D,), 1, False, r"hazard,\s+"),
        ("the mature hazard, group 11's A11.20 section", PRINTED, (D,), 1, False, r"against it:\s+\**"),
        ("a declining size's recipe over its floor", PRINTED, (D, ED), 1, False, r"a median\s+"),
        ("MAPE at 0.60", PRINTED, (D, "A11.23"), 0, False, r"MAPE of\s+"),
        ("MAPE at the band's ends", PRINTED, (D, "A11.23"), 0, True, r"band is\s+"),
        # ---- group 10 at the factor
        ("A10.09 the start-up cull: sizes, recipes, redraws", PRINTED,
         ("A10.09",), [3, 3, 2], False, r"units carries\s+\**"),
        ("A10.09 the start-up cull: sizes, recipes, group 10's doc", PRINTED, (D10,), 3,
         False, r"units carries\s+\**"),
        ("A10.09 the start-up redraws, group 10's doc", PRINTED, (D10,), 2, False, r"slot,\s+"),
        # The pre-window pair, watched 2026-09-22. Both figures were unwatched companions of restated headlines
        # and both had gone stale -- 0.48 against a drawn 0.50, 0.89 against 0.86. A7.09 carried the lost-launch
        # count TWICE, at 0.50 in the sentence the entry above reads and at 0.48 here, which is the defect the
        # package keeps finding; its second copy is retired rather than restated, because a quantity stated once
        # cannot disagree with itself.
        ("A10.09 the pre-window exits: 2022's lost launches and A10.16's pre-period delists",
         PRINTED, ("A10.09",), 2, False, r"\(item 2\): 2022's\s+"),
        ("A10.16's pre-period delists where A7.09 names them", PRINTED, ("A7.09",), 2, False,
         r"pre-period review adds\s+"),
        ("the start-up cull, the decision", PRINTED, (ES,), 3, False, r"cull is\s+"),
        ("A10.06 the start-up SKU-DC pairs", PRINTED, ("A10.06", D10), 2, False, r"carries\s+\**"),
        ("A10.06 pairs in the window, their sum, and those on exiting SKUs",
         PRINTED, ("A10.06", D10), 2, False, r"\(#\),\s+\**"),
        ("A10.06 pairs in the window, A10.09", PRINTED, ("A10.09",), 2, False, r"discontinuations,?\s+"),
        ("A10.06 pairs by year and over the window, group 10's summary table", PRINTED, (D10,), 2,
         False, r"\(#\)\s+\|\s+"),
        ("A10.16 floor delists: Kroger, Walmart, total", PRINTED, (D10,), 3, False, None),
        # This series and the one below are six figures at two decimals in the same document, and unanchored
        # they accepted each other's values (probe, SWAPPED). Both now name where they are published.
        ("A10.16's pre-period exits and the strikes it carries into y1: Kroger, Walmart, total",
         PRINTED, ("A10.16", D10), 2, False,
         r"own delists,\s+|own delists\s+—\s+\*\*"),
        ("A10.16 Kroger's floor delists, row", PRINTED, ("A10.16",), 3, False, r"give\s+"),
        ("A10.16 Walmart's floor delists, then the total, row", PRINTED, ("A10.16",), 3, False, r"gives\s+"),
        ("A10.16 authorized below the floor per review: Kroger, Walmart", PRINTED, (D10,), 2, False,
         r"two consecutive reviews\s+\|\s+"),
        ("A10.04 Kroger below the floor per review, then its delists", PRINTED, ("A10.04", D10),
         [2, 2, 2, 3], False, r"floor run\s+|below 60 run\s+\**"),
        # The locator names the figure that follows it: a bare possessive anchor reference hits nine times in
        # A10.09 alone, and one of those is the pre-period's 0.89 (probe, ONTO A NUMBER).
        ("A10.16's floor delists, cited in A10.09 and A10.18", PRINTED, ("A10.09", "A10.18"), 2, False,
         r"#'s\s+(?=[\d.]+\s+floor\s+delists)"),
        ("A10.16's floor delists, group 10's summary table", PRINTED, (D10,), 2, False,
         r"its own draw\s+(?:\|\s+){4}"),
        ("A10.16's floor delists, the decisions", PRINTED, (E18, E109, ES), 2, False,
         r"floor\s+delists\s+are\s+|factor,\s+are\s+"),
        ("A10.16's floor delists, group 11's findings", PRINTED, (D,), 2, False,
         r"#'s\s+(?=[\d.]+\s+is\s+its\s+own\s+draw)"),
        # A10.16's companions in group 11's doc, one entry per copy (U4, 2026-10-01): each sat beside a watched figure
        ("A10.16's pre-period delists and the strikes carried into y1, group 11's finding 1",
         PRINTED, (D,), 2, False, r"reviewed first,\s+"),
        ("A10.16's pre-period delists and the strikes carried into y1, group 11's owner list",
         PRINTED, (D,), 2, False, r"its\s+own\s+(?=[\d.]+\s+delists)"),
        ("A10.16's floor delists by banner, Kroger then Walmart, group 11's finding 1", PRINTED, (D,), 3,
         False, r"no launches\s+—\s+Kroger\s+"),
        ("A10.16's Kroger floor delists, group 11's owner list", PRINTED, (D,), 3, False,
         r"Kroger's\s+(?=[\d.]+\s+against)"),
        # the present sentence, not the record of 2026-09-16 beside it (7.01 -> 12.29, Kroger's 10.041)
        ("A10.16's floor delists, group 11's owner list", PRINTED, (D,), 2, False,
         r"#'s delists are\s+"),
        ("2022's launches that leave before the window, group 11's owner list", PRINTED, (D,), 2, False,
         r"2022's\s+(?=[\d.]+\s+lost\s+launches)"),
        # ---- A9.02 reads group 11, and group 9's own figures (2026-09-14 audit, #9)
        # Amazon's referral fee and plan MOVED to A9.01's marketplace line on 2026-09-18, so this block is
        # four rows and not five. They are watched by the opex entries below, in their new place.
        ("what A9.02 reads from group 11, row by row, then EBITDA",
         PRINTED,
         (D,), 4, False, None),
        ("group 11's costs, row by row, then EBITDA, group 9's P&L block",
         PRINTED,
         (D9,), 3, False, None),
        ("group 11's costs, A9.02 and group 9's doc", PRINTED, ("A9.02", D9), 3, False, r"registers\s+|costs take\s+"),
        ("EBITDA, $M, A9.02 (the row writes the sign before the dollar sign; the percent series carries it)",
         PRINTED, ("A9.02",), 3, False, r"EBITDA -\$"),
        ("EBITDA, $M", PRINTED, (D, E902), 3, False, r"window year:\s+|EBITDA\s+"),
        ("group 11's costs, EBITDA and the gap, revision 6 in the decision", PRINTED, (E902,),
         [3] * 6 + [2], False, r"Group 11's costs\s+"),
        # Three figures at one decimal, unanchored in a 65,000-character document, accepted five other series
        # (probe, SWAPPED). The locator is the sentence that publishes them, in each of the three places.
        ("Amazon's fees the P&L reads, $K", PRINTED, (D, "A11.01", "A11.22"), 1, False,
         r"blended at [\d.]+%\*\*: \*\*\$|BLENDED AT [\d.]+%, \$|blended at [\d.]+%: \$"),
        # The referral-band entry is RETIRED (owner, 2026-09-23). Every site it read -- A11.01, A11.22 and the group-11
        # doc -- prints the band as the dated record of what the P&L read before 2026-09-18, and a dated record carries
        # no watched figure (#watched-figure-present-tense).
        ("Amazon's dollars, own-site dollars and units", PRINTED,
         (D, "A11.01"), [3, 3, 3, 3, 3, 3, 0, 0, 0], False, None),
        ("Amazon's share of A8.01's 10%, and its share of y3 gross",
         PRINTED,
         (D, "A11.01", "A8.01"), [0, 0, 0, 1], False, None),
        ("EBITDA, its share of gross, the gap and its band, the decision", PRINTED, (E902,), [3] * 3 + [2] * 6, False, r"EBITDA\s+"),
        ("the y3 funding gap, doc", PRINTED, (D,), 2, False, r"funding gap is\s+\$|gap moves from \$[\d.]+M to \*\*\$"),
        ("the y3 funding gap, the undated-sources decision", PRINTED, (EUS,), 2, False, r"y3 funding gap\s+(?:is\s+)?\$"),
        ("y1 EBITDA, the undated-sources decision", PRINTED, (EUS,), 3, False, r"y1 EBITDA\s+"),
        ("the organic inspection hours", PRINTED, (D, "A11.09", E902), 0, False,
         r"the first included \(owner, [^)]*\); and\s+|organic inspection at\s+"),
        ("the organic inspection dollars", PRINTED, (D, "A11.09"), 0, False, r"at Tilth's \$[\d.]+,\s+\**\$"),
        ("DSO, A9.11 at the ruled 60 days", PRINTED, ("A11.04", D, "A9.11", D9, "A10.14", D10), 2, False,
         r"DSO\s+(?:is\s+)?\**"),
        ("AR on the restated DSO", PRINTED, ("A9.12", D9), 3, False, r"AR\s+"),
        # ...and on the filers' basis, beside it (U14 batch 7, owner, 2026-11-06, DECISIONS#u14)
        ("A9.11's DSO on net sales, the filers' basis", PRINTED, ("A9.11",), 1, False, r"ON NET SALES,\s+"),
        ("NWC, the pre-window balance, then its growth, A9.13", PRINTED, ("A9.13",), 3, False,
         r"=\s+(?=[\d.]+ / [\d.]+ / [\d.]+ against)"),
        ("NWC and the pre-window balance, group 9's doc", PRINTED, (D9,), 3, False, r"giving NWC\s+"),
        ("collateral unused behind the y1 draw", PRINTED, ("A9.13", D9), 3, False, r"so\s+(?=[\d.]+ of collateral)"),
        ("the y1 shortfall in days, share of an AP run, the run, days of invoicing",
         PRINTED, ("A9.13", D9), [2, 1, 3, 1], False, None),
        ("the upsize against the base examined", PRINTED, ("A9.14", D9), 1, False, r"\$[\d.]+M is\s+(?=[\d.]+%)|peak it is\s+"),
        ("the base passed from y2, unfunded", PRINTED, ("A9.14", D9), 2, False, r"leave\s+\$"),
        # ---- the supersede markers in DECISIONS, group 9
        ("EBITDA at the 2025 base, the markers", PRINTED, (E("A3.01-period"), E("A9.02"), E("A3.04-period")), 2, False,
         r"base\s+is\s+|window\s+year,\s+"),
        ("y3 EBITDA at every point of the band", PRINTED, (E("A3.22"),), 2, False,
         r"y3 is\s+(?=[-−\d.]+% of gross at every point)"),
        ("the y3 zero crossing in A4.15's band", PRINTED, (E("A4.15"), "A4.15"), 2, False,
         r"over-settlement of\s+"),
        ("the y1 exceedance in $M", PRINTED, (E("A9.13"),), 2, False,
         r"the\s+line\s+is\s+exceeded\s+in\s+y1\s+by\s+\$"),
        ("the y1 exceedance: $K, days, share of a run, the run, days of invoicing, DPO, days past terms",
         PRINTED, (E("nov-y1-amendment"),), [0, 2, 1, 0, 1, 1, 1], False, r"exceedance is\s+\**\$"),
        ("the collateral in $K, the marker", PRINTED, (E("nov-y1-amendment"),), 0, False,
         r"sits\s+\$(?=[\d,]+K\s+under\s+the\s+base)"),
        ("the ladder, DPO, and the base passed from y2, the marker", PRINTED,
         (E("nov-y1-amendment"),), [2, 2, 2, 1, 1, 1, 3, 3], False, r"ladder is\s+"),
        ("the gap, its band, then y1's exceedance and days, the A9.14 fees marker",
         PRINTED, (E("A9.14-fees"),), [2, 2, 2, 0, 2], False,
         r"funding gap is\s+\**\$"),
        ("the gap and its band, the A10.17 bands marker", PRINTED, (E("A10.17-bands"),), 2, False,
         r"gap is\s+\$"),
        # ---- Oregon (A11.25)
        ("A11.25 revenue test, 2024 gross $M", PRINTED, (D, "A11.25"), 1, False, r"invoice prices, is\s+\$"),
        ("A11.25 units into Oregon: Walmart", PRINTED, (D, "A11.25"), 0, False,
         r"\|\s+Walmart\s+\|\s+|2024:\s+Walmart\s+"),
        ("A11.25 units into Oregon: own-site DTC jars", PRINTED, (D, "A11.25"), 0, False,
         r"DTC jars\s+(?:\|\s+)?"),
        ("A11.25 units into Oregon: Amazon", PRINTED, (D, "A11.25"), 0, False,
         r"Amazon units\s+(?:\|\s+)?"),
        ("A11.25 units into Oregon: small accounts", PRINTED, (D, "A11.25"), 0, False,
         r"small accounts\s+\|\s+|small-account units\s+"),
        ("A11.25 units into Oregon: UNFI and KeHE", PRINTED, (D, "A11.25"), 0, False,
         r"UNFI and KeHE\s+\|\s+|UNFI's and KeHE's\s+"),
        ("A11.25 units into Oregon: DPI", PRINTED, (D, "A11.25", E25), 0, False, r"\|\s+DPI\s+\|\s+|DPI's\s+"),
        ("A11.25 units into Oregon, in all, doc", PRINTED, (D,), 0, False, r"\*\*total\*\*\s+\|\s+\*\*"),
        ("A11.25 units into Oregon, in all, row", PRINTED, ("A11.25",), 0, False, r"Oregon\s+\(#\)\.\s+"),
        ("A11.25 units into Oregon, in all, the decision", PRINTED, (E25,), 0, False,
         r"What derives, revision 6\.\*\*\s+"),
        ("A11.25 the ruled weight: lb, tons, without the distributors, the fee", PRINTED, (D,), [2, 1, 1, 0],
         False, r"\|\s+(?=[\d.]+ lb, as ruled)"),
        ("A11.25 packaging alone: lb a unit, tons, without the distributors, the fee",
         PRINTED, (D,), [2, 1, 1, 0], False,
         r"\|\s+(?=[\d.]+ lb, packaging alone)"),
        ("A11.25 the ruled weight's lb, row", PRINTED, ("A11.25",), 2, False, r"At #'s\s+"),
        ("A11.25 the ruled weight's tons, row", PRINTED, ("A11.25",), 1, False, r"that is\s+"),
        ("A11.25 packaging alone, then both readings without the distributors, row",
         PRINTED,
         ("A11.25",), [2, 1, 1, 1], False, None),
        ("A11.25 the fee at both weights, row", PRINTED, ("A11.25",), 0, False, r"is\s+\$"),
        ("A11.25 tons at both weights, the doc's summary", PRINTED, (D,), 1, False, r"reading:\s+"),
        ("A11.25 tons, the decision: both weights, then both without the distributors",
         PRINTED, (E25,), 1,
         False, None),
        # both fees: the decision printed a stale $1,952 for the packaging fee from 2026-09-24, and no check read it
        ("A11.25 the fee at both weights, the decision", PRINTED, (E25,), 0, False,
         r"pound, is\s+\$"),
        ("A11.25 the units over the ruling's 2,000 jars", PRINTED,
         (D, E25, "A11.25:plausibility_anchor"), 0, False, r"derive are\s+"),
        # ---- A2.08's packaging weight, a derived companion (UNIT_LB less NET_CONTENTS_LB), one entry per copy
        ("A2.08's packaging weight, where it derives", PRINTED, ("A2.08",), 2, False, r"net contents,\s+"),
        ("A2.08's packaging weight, the column it owes", PRINTED, ("A2.08",), 2, False, r"COLUMN\s+-\s+"),
        ("A2.08's packaging weight, A11.22's copy", PRINTED, ("A11.22",), 2, False, r"as against the\s+"),
        ("A2.08's two weights, group 11's owner list", PRINTED, (D,), 2, False,
         r"The filled unit,\s+"),
        # ---- A11.05's KeHE DCs, A5.32's 4 / 5 / 5 since KeHE takes the brand's DPI ship-to point
        ("A11.05's KeHE DCs, the row and group 11's doc", PRINTED, ("A11.05", D),
         0, False, r"its KeHE DCs,\s+|and KeHE's\s+"),
        # ---- the rest of group 11, carried sections
        ("A11.20 Pacesetter hazard",
         PRINTED,
         ("A11.20", D), 1, False, r"it is \*{0,2}"),
        ("A11.14 Kroger, row order: fines, other types, wholesale, rate, pool",
         PRINTED, ("A11.14",), [4] * 9 + [2] * 6, False, None),
        ("A11.29's copy of A11.14's Kroger deduction rate", PRINTED, ("A11.29",), 2, False,
         r"deduction rate, which derives at\s+"),
        ("A11.14 Kroger, table order: wholesale, fines, other types, rate, pool",
         PRINTED, (D,), [4] * 9 + [2] * 6, False, None),
        ("A11.15 repair dollars", PRINTED, ("A11.15", D), 2, False,
         r"dollars derive:\s+\$|GTIN check digit invalid\s+\|\s+\d+\s+\|\s+\$"),
        ("A11.13 distributor purchases", PRINTED, (D,), 3, False, r"purchases\s+\|\s+"),
        # the signed row kept $7.495M / $7.989M from 2026-09-24 because no check read it
        ("A11.13 the swell base at UNFI and KeHE, y2 and y3, row", PRINTED, ("A11.13",), 3,
         False, r"UNFI and KeHE is \$"),
        ("A11.13 swell, y1", PRINTED, ("A11.13",), 4, True, r"swell of \$"),
        ("A11.13 swell by year", PRINTED, (D,), 4, True, None),
        ("A11.13 swell's share of the type brand-wide, y1",
         PRINTED, ("A11.13",), 0, True, r"in y1 is "),
        ("A11.13 the type brand-wide, then at the distributors' share",
         PRINTED, (D,), 4, False, None),
        ("A11.13 swell against the type at the distributors' share, then retailers' damaged rate needed",
         PRINTED,
         ("A11.13", D), [2, 2, 2, 0, 0, 0], True, None),
        ("A11.12 inventory at COGS, then write-offs", PRINTED,
         ("A11.12", D), [3, 3, 3, 4, 4, 4], False, None),
        ("A11.11 the floor's reach", PRINTED, ("A11.11",), 1, False, None),
        ("A11.11 the mixture's median and mean, then the floor's reach",
         PRINTED, (D,), 1, False, r"median \$"),
        ("A11.08 units shipped, millions, row", PRINTED, ("A11.08",), 2, False, r"ships "),
        ("A11.08 units shipped, millions, doc", PRINTED, (D,), 2, False, r"jars \| "),
        ("A11.08 complaints, then a working day, row", PRINTED,
         ("A11.08",), [0, 0, 0, 1, 1, 1], False, None),
        ("A11.08 complaints, doc", PRINTED, (D,), 0, False, r"10,000 \| "),
        ("A11.08 complaints a working day, doc", PRINTED, (D,), 1, False, r"250 days \| "),
        ("A11.08 kettle lots", PRINTED, ("A11.08", D), 0, False, r"lots run |in-house share \| "),
        ("A11.08 recall rates, then odds over the window", PRINTED, ("A11.08", D), [2, 2, 2, 1], False, None),
        ("A11.04 the tier's dollars, $K", PRINTED, ("A11.04",), 0, False, r"the tier \$"),
        ("A11.04 dollars an order", PRINTED, ("A11.04", D), 0, False, r"which is \$|are \*\*\$"),
        # The restated order count and the value the asserted 120 implied: both are the generator's and both are
        # published in the row and the doc, and until the re-audit of slice 5 neither was watched. The count is
        # what the owner's item 7 ruling changed, so a drift here retires the ruling's own finding silently.
        ("A11.04 orders a year on the restated count", PRINTED, ("A11.04", D), 0, False,
         r"(?:ABOUT|about) \$[\d.]+\s+[-–—]\s+"),
        # a retired figure the generator still recomputes for the comparison: it lives in the row's history
        # (DECISIONS#history-move), and the check reads it there
        ("A11.04 the value the asserted 120 orders implied", PRINTED,
         ("A11.04:history", D), 0, False, r"implied\s+(?:small-account order\s+)?value was \$"),
        ("A11.04 Faire's fees as A9.02 reads them, $K", PRINTED, ("A11.04", D), 1, False,
         r"retailers\s+[—-]\s+\**\$"),
        ("A11.04 brand-wide bad debt $K, then against the tier",
         PRINTED, ("A11.04",), 1, False, None),
        ("A11.04 brand-wide bad debt against the tier", PRINTED, (D,), 1, False,
         r"would be \*\*(?!\$)"),
        ("A11.09 organic sales stand-in", PRINTED, ("A11.09", D), 2, False, r"\(\$|sales — \$"),
        ("A11.09 the organic certificate as A9.02 reads it, $", PRINTED, ("A11.09", D), 0, False,
         r"OCCSP:\s+\**\$|lands:\s+\$"),
        ("A11.19 buyer resets, then the share of quarters in a reset",
         PRINTED, ("A11.19", D), [3, 3, 3, 0], False,
         None),
        # ---- THE DERIVED COMPANIONS, watched 2026-09-22. Each is a figure computed FROM a watched headline and
        # printed beside it, and each went stale when its headline was restated -- a whole class the 53-agent
        # verification of 2026-09-22 found and no check could see, because the gate read the headline and the
        # companion sat one clause away. Watching them is the fix; restating them is only today's instance.
        ("A10.16's tail-band check: the bottom quintile at the catalogue multiplier",
         PRINTED, ("A10.16", D10), 2, False,
         r"bottom quintile\s+"),
        ("A10.16's cap reading: the A:C cadence on the multiplier, then on generated volume",
         PRINTED, ("A10.16",), 2, False,
         r"holds on the multiplier,\s+"),
        ("A11.28's variance shares: the week term, then the door term, of A7.03's variance",
         PRINTED,
         ("A11.28:plausibility_anchor", D), 1, False, r"the week term is\s+|it accounts for\s+"),
        ("A11.27's band-end solves: the account target at the door band's ends",
         PRINTED, ("A11.27", D), 3, False,
         r"ends give\s+"),
        ("A7.03's y3 mean where group 11 reads it, and the quintiles at both sigmas",
         PRINTED, (D,), 2, False,
         r"against a y3 mean of\s+"),
        ("A11.26's spread of the y3 carried sets", PRINTED, ("A11.26", D), 2, False,
         r"y3 (?:carried )?sets spread\s+"),
        ("A2.09's at-risk and fading sizes, as A11.26's rule takes them", PRINTED,
         ("A2.09", D2), 2, False, r"(?:which|it)\s+takes\s+"),
        ("A10.09's launch exits through A11.24, the window total, and A11.26's share of it",
         PRINTED, (D10,), 2, False,
         r"no national account carries them,\s+"),
        ("A7.13's causal arms: the index-100 and no-factor counterfactuals beside the baseline",
         PRINTED, ("A7.13", D),
         P_SHARE, False, r"everywhere the share is\s+"),
        ("A7.13's causal arms where group 7 prints the 90-day pair",
         PRINTED, (D7,),
         P_SHARE, False, r"index of 100 everywhere it is\s+"),
        ("A10.16's sigma-2.0 alternative: the spread, its first-draw cull, and this reading's",
         PRINTED, ("A10.16",), [3, 1, 3], False,
         r"spreads the carried sets\s+"),
        ("A10.16's Walmart cut: the modular's bottom quintile as an index",
         PRINTED, ("A10.16", D10), 1, False,
         r"modular quintile at index\s+|computes to index\s+|Walmart's\s+"),
    ])
    _GROUP11.extend(_restated_21_figures(E))
    _GROUP11_FACTS.extend([
        ("A7.13 does not land near its practitioner shares",
         PRINTED, "far from its practitioner shares"),
        ("the 24-month share sits inside the category band", PRINTED, "inside the category's 12–42%"),
        # Which population the factor is solved on was a reading until the owner ruled it on 2026-09-14;
        # the doc must still name the choice whenever the two solves disagree, so the sentence moves rather
        # than the check.
        ("the factor on the window differs from the launch-free solve", PRINTED,
         "the owner ruled the window's own sets the population on 2026-09-14"),
        ("the generated-volume cadence falls outside A5.28's 3-4 runs", PRINTED,
         "outside A5.28's 3–4"),
        ("the seven invariants hold in every quarter of every trial", PRINTED,
         "Seven invariants are checked, and hold, in every quarter of every trial"),
        ("A11.26 prunes more than a rounding", PRINTED,
         "The count is not near zero"),
        ("A11.26 is what brings the drawn catalogue back to A2.01's", PRINTED,
         "With the rule off the draw inflates it"),
        ("every launch exit comes through A11.24", PRINTED,
         "Every launch exit comes through A11.24"),
        ("no other mature exit was carried by a retailer", PRINTED,
         "none was carried by a retailer in the quarter it left"),
        ("EBITDA is a loss in every window year", PRINTED, "A small loss in every window year"),
        ("every Oregon reading passes one metric ton",
         PRINTED,
         "Every reading passes one metric ton"),
    ])
    _GROUP11[:] = _resolved(_GROUP11)
    _GROUP11_FACTS[:] = _resolved(_GROUP11_FACTS)
    return _GROUP11


def decision_entry(text, anchor):
    """One DECISIONS entry: from its <a id> to the next entry's, or to the next section heading."""
    start = text.index('<a id="%s"></a>' % anchor)
    ends = [i for i in (text.find('<a id="', start + 1), text.find("\n## ", start)) if i != -1]
    return text[start:min(ends) if ends else len(text)]


def check_group11_figures(index, doc=None, docs=None, entries=None, unfound=None):
    """Group 11's computed figures in the docs, the rows and DECISIONS are the generators', token for token.

    `doc` stands in for group 11's doc and `docs` for any other path's text, so the self-test can
    doctor either without touching a file; `entries` for group11_figures(), so it can move a value; `unfound`
    collects the labels a text does not carry (_UNFOUND, which check_entry_outputs reads, by default).
    """
    unfound = _UNFOUND if unfound is None else unfound
    texts = dict(docs or {})
    if doc is not None:
        texts[GROUP11_DOC] = doc
    normed = {}

    def text_of(where):
        if where not in normed:
            path, _, entry = where.partition("#")
            if path.endswith(".md"):
                body = texts[path] if path in texts else rd(path)
                normed[where] = norm(decision_entry(body, entry) if entry else body)
            else:
                # "A11.28:plausibility_anchor" names a FIELD. A row publishes figures outside `value` --
                # A11.28's variance decomposition is in its plausibility_anchor and nowhere else -- and a
                # check that reads `value` alone cannot see them. Naming the field keeps each entry's search
                # space exactly the text it means, rather than widening every entry to the whole row. A path
                # reaches into a list of records: "A9.14:sources[0].figure".
                rid, _, field = path.partition(":")
                normed[where] = norm(field_text(index[rid], field))
        return normed[where]
    bad, over = [], []
    for label, vals, where, places, pairs, after in (group11_figures() if entries is None else entries):
        each = list(places) if isinstance(places, (list, tuple)) else [places] * len(vals)
        fmt = ["%." + str(p) + "f" for p in each]
        shown = (", ".join("%s-%s" % (f % a, f % b) for (a, b), f in zip(vals, fmt)) if pairs
                 else " / ".join(f % v for v, f in zip(vals, fmt)))
        for w in where:
            toks = carried_tokens(text_of(w), vals, places, pairs=pairs, after=after)
            if toks is None:
                unfound.add(label)
                bad.append("%s: the generator computes %s; %s does not carry it" % (label, shown, w))
                continue
            for t in (x for tok in toks for x in (tok if pairs else (tok,))):
                dollars = re.search(r"\$[+-]?%s(?![\d])" % re.escape(t), text_of(w))
                if "." in t and sig_figs(t) > (3 if dollars else 2):
                    over.append("%s: %s prints %s" % (label, w, t))
    # THE PRINT RULE'S BACKLOG (DECISIONS#print-rule): a watched figure printed past its precision -- two significant
    # figures for a rate or a percentage, three for dollars in their unit ($355K, $4.39M). A count prints whole, so
    # only a token with a decimal point is listed. Existing prints convert when next touched; a registered input
    # among the watched values keeps its registered precision and is listed here regardless.
    report(INFO, PRINT_RULE_CHECK, sorted(set(over)))
    flat = re.sub(r"\s+", " ", text_of(GROUP11_DOC))
    for label, ok, words in _GROUP11_FACTS:
        if not ok:
            bad.append("%s: the generator no longer has that shape" % label)
        elif words not in flat:
            bad.append("%s: %s no longer says %r" % (label, GROUP11_DOC, words))
    report(BLOCK, "doc / registry / generator agree, group 11", bad)


ENTRY_OUTPUT_CHECK = "the figure checks read the generators only through outputs(), and read all it prints"
FIGURE_CHECKS = ("check_generator_figures", "check_group10_figures", "check_group11_figures", "group11_figures",
                 "_a901_opex_figures", "_a6_chain_figures", "_restated_21_figures", "_amazon_basis_figures",
                 "check_daily_dates", "check_ap_schedule")
FACTOR = "the SKU x account factor's log-sd, solved on the window's own carried sets"


def _generator_imports(src=None):
    """(function, line, module) for every generator a figure check imports: with no import there is no module to
    read past outputs(). The mechanics checks -- the daily ledger's flows, sawtooth and part-held runs, the
    note's dates bit for bit, the equity call, the card networks' floors, slotting outside the rates, the small
    channel, and the mirror and constants checks -- run the generator under a row's printed input or a doctored
    copy, which no printed object can answer, and are not figure checks."""
    import ast
    out = []
    for fn in ast.parse(src if src is not None else rd("scripts/check_anchors.py")).body:
        if isinstance(fn, ast.FunctionDef) and fn.name in FIGURE_CHECKS:
            for n in ast.walk(fn):
                if isinstance(n, (ast.Import, ast.ImportFrom)):
                    for m in [a.name for a in n.names] + [getattr(n, "module", None) or ""]:
                        if m.split(".")[0] in GENERATOR_MODULES:
                            out.append((fn.name, n.lineno, m.split(".")[0]))
    return out


def check_entry_outputs(printed=None, read=None, unfound=None, src=None):
    """U21's entry-output check: what the gate checks and what the seeders read are one object.

    It fails on a printed value that no figure check reads or that its check does not find in its row or doc; on a
    figure check that asks for a value no generator's outputs() prints; on a label two generators print; and on a
    figure check that imports a generator, the one way left to read past outputs(). `trial` and `series` sit outside
    it by construction: no row prints them. Group 10's solved factor is read by _outputs_compute, which hands it to
    group 11. `printed`, `read` and `unfound` stand in for the gate's own -- the self-test's doctored copies.
    """
    P = _printed() if printed is None else printed
    read = set(_READ if read is None else read) | {FACTOR}
    unfound = _UNFOUND if unfound is None else unfound
    bad = []
    for label in sorted(set(P) - read):
        bad.append("%s prints %r under %s, and no figure check reads it" % (P[label][0], label, P[label][1]))
    for label in sorted((read - set(P)) | (_MISSING if printed is None else set())):
        bad.append("a figure check reads %r, which no generator's outputs() prints" % label)
    for label in sorted(set(unfound) & set(P)):
        bad.append("%s's printed %r (%s) is not found where its figure check reads it" % (P[label][0], label,
                                                                                         P[label][1]))
    for label in sorted(_PRINTED_TWICE if printed is None else ()):
        bad.append("%r is printed by two generators" % label)
    for fn, line, mod in _generator_imports(src):
        bad.append("%s imports %s at line %d: a figure check reads generators only through outputs()" % (fn, mod, line))
    report(BLOCK, ENTRY_OUTPUT_CHECK, bad)


def check_generator_figures(index):
    """The doc, the registry and the generator publish one set of numbers.

    Stands in for "every worked number reproduces from depends_on", which cannot
    be mechanised. Nothing is hardcoded here: the series are COMPUTED by
    scripts/group9_ledger.py and then looked for in the prose that publishes
    them, so a restatement that misses a file fails rather than drifts. Since U21 they are read from group 9's
    outputs(), under each entry's own label.
    """
    doc = norm(rd(GROUP9_DOC))
    # A9.13's five ledger series and A9.02's EBITDA % of gross moved to anchored entries in _restated_21_figures on
    # U4 (2026-10-01): five of them went stale in one day because carries() could not tell which copy was meant.
    published = [
        ("net working capital", PRINTED, "A9.13"),
        ("borrowing base", PRINTED, "A9.14"),
    ]
    bad = []
    for label, vals, owner in _resolved(published):
        for where, text in ((owner, index[owner]["value"]), (GROUP9_DOC, doc)):
            if not carries(text, vals):
                _UNFOUND.add(label)
                bad.append("%s: the generator computes %s; %s does not carry it"
                           % (label, series(vals), where))
    report(BLOCK, "doc / registry / generator agree", bad)


# --------------------------------------------------------------- the self-test
def _isolated(fn, args, expect=None):
    """Run one check with its own results buffer and return what it reported.

    `expect` names the reported check that must fire. Two functions here report
    more than one check, and without naming the one under test a case would be
    credited by its neighbour's findings -- a proof that proves the wrong thing,
    which is the defect this whole file exists to catch.
    """
    global RESULTS
    saved, RESULTS = RESULTS, []
    try:
        fn(*args)
        if expect is not None:
            hit = [rep for rep in RESULTS if rep[1] == expect]
            if not hit:
                raise AssertionError("no check named %r was reported" % expect)
            return [m for _, _, msgs in hit for m in msgs]
        return [m for level, _, msgs in RESULTS if level in (BLOCK, WARN)
                for m in msgs]
    finally:
        RESULTS = saved


def self_test(rows, index, enums):
    """Prove every check can go red. A gate that cannot fail is not a gate.

    Each case breaks one thing in an in-memory copy and asserts that the check
    written for it reports. The registry on disk is never touched.
    """
    import copy

    def fresh():
        r = copy.deepcopy(rows)
        return r, dict((x["anchor_id"], x) for x in r)

    cases = []
    SCOPES = {}   # case name -> (message prefix, message suffix): the finding the case must produce, not any finding

    r, i = fresh(); r[0]["tier"] = "Z"
    cases.append(("schema and enums", check_schema, (r, enums)))

    r, i = fresh()
    next(x for x in r if x["unit"] in enums["denominator_required"])["denominator"] = None
    cases.append(("denominators", check_denominator, (r, enums)))

    r, i = fresh(); r[0]["depends_on"] = ["A99.99"]
    cases.append(("depends_on resolves", check_depends_resolve, (r, i, enums)))

    r, i = fresh()
    a, b = r[0]["anchor_id"], r[1]["anchor_id"]
    r[0]["depends_on"], r[1]["depends_on"] = [b], [a]
    cases.append(("cycles", check_cycles, (r, i)))

    r, i = fresh()
    next(x for x in r if x["tier"] == "A")["evidence_class"] = "owner-judgment"
    cases.append(("Tier A gate", check_tier_a, (r, enums)))

    # U14's non-vendor check: a vendor primary; a YAML-null primary URL (None, not 'None'); an unmarked URL-less entry
    r, i = fresh()
    next(x for x in r if x["tier"] == "A")["independence"] = "vendor"
    cases.append(("Tier A primary is addressed and not a vendor", check_tier_a_non_vendor, (r,)))
    r, i = fresh()
    next(x for x in r if x["tier"] == "A")["source_url"] = None
    cases.append(("Tier A primary is addressed and not a vendor, a null URL", check_tier_a_non_vendor, (r,)))
    r, i = fresh()
    next(x for x in r if x["tier"] == "A")["sources"] = [dict(source_url=None, figure="x", measured="read once",
                                                              independence="government")]
    cases.append(("Tier A primary is addressed and not a vendor, an unmarked entry", check_tier_a_non_vendor, (r,)))
    for n, tail in (("", "it needs a URL and a non-vendor source"), (", a null URL", "it needs a URL and a non-vendor source"),
                    (", an unmarked entry", "it reads as evidence")):
        SCOPES["Tier A primary is addressed and not a vendor" + n] = ("A", tail)

    r, i = fresh(); next(x for x in r if x["tier"] == "D")["rationale"] = None
    cases.append(("Tier D reasoning", check_tier_d, (r, enums)))

    r, i = fresh()
    r[0]["sourcing_note"] = "docs/anchors/sourcing/group-1-revenue.md#no-such-heading"
    cases.append(("sourcing-note slugs", check_sourcing_slugs, (r,)))

    r, i = fresh()
    next(x for x in r if x.get("decision_ref"))["decision_ref"] = "DECISIONS.md#no-such-id"
    cases.append(("decision_ref targets", check_decision_refs, (r,)))

    cases.append(("line endings", check_line_endings, (["scripts/fixtures/crlf-and-tabs.txt"],)))

    r, i = fresh(); i[r[0]["anchor_id"]]["tier"] = {"A": "B", "B": "D", "D": "A"}[r[0]["tier"]]
    cases.append(("worklist parity", check_worklist_parity, (i,)))

    r, i = fresh()
    d = next(x for x in r if x["status"] == "derived")
    d["value"] = (d["value"] or "") + " This row is moved by A1.01."
    d["depends_on"] = [u for u in (d.get("depends_on") or []) if u != "A1.01"]
    cases.append(("depends_on completeness", check_depends_completeness, (r, i, {}),
                  "depends_on completeness"))
    # U14 (2026-11-06): a derived row that is pinned stays under the check
    r, i = fresh()
    d = next(x for x in r if x.get("pinned_from") == "derived")
    d["value"] = (d["value"] or "") + " This row is moved by A1.01."
    d["depends_on"] = [u for u in (d.get("depends_on") or []) if u != "A1.01"]
    cases.append(("U14: a pinned derived row names an anchor it does not depend on", check_depends_completeness,
                  (r, i, {}), "depends_on completeness"))

    # The ratchet's own three rules: over ceiling, no reason, stale pair.
    r, i = fresh()
    cases.append(("depends_on ratchet", check_depends_completeness,
                  (r, i, {"ceiling": 0,
                          "open": [{"row": "A1.04", "names": "A1.01", "reason": ""},
                                   {"row": "A1.04", "names": "A9.99", "reason": "closed"}]}),
                  "the depends_on ratchet only shrinks"))

    r, i = fresh()
    r[0]["value"] = "the peak need is 1.000 / 2.000 / 3.000 and the peak need is 4.000 / 5.000 / 6.000."
    cases.append(("one value per quantity", check_one_value_per_quantity, (r,)))

    r, i = fresh()
    r[0]["value"] = "The earlier 1.000 / 2.000 / 3.000 is withdrawn."
    r[1]["value"] = "The ratio is 1.000 / 2.000 / 3.000 across the window."
    cases.append(("retired figure reappears", check_retired_figures, (r,)))

    # A row credits another with a figure the source does not print; and with one it prints only as history. Run on
    # the two rows the case edits, so the live registry's own findings cannot make a case fire without its edit.
    def pair(text, history=None):
        a, b = copy.deepcopy(rows[0]), copy.deepcopy(rows[1])
        if history:
            a["history"] = history
        b.update(dict((f, None) for f in FINGERPRINTED_FIELDS), value=text % a["anchor_id"])
        return [a, b]
    cases.append(("cross-row credit unprinted", check_cross_row_credits,
                  (pair("It reads %s's 123.457 / 234.568."), {}), CREDIT_CHECK))
    cases.append(("cross-row credit stale", check_cross_row_credits,
                  (pair("It reads 876.543 (%s).", "Retired: 876.543."), {}), CREDIT_CHECK))
    cases.append(("history reach", check_history_reach, (pair("Beside %s it prints 876.543.", "Retired: 876.543."),),
                  "a figure another row retired, printed beside its id"))

    r, i = fresh(); i["A9.13"]["value"] = "the ledger says nothing."
    cases.append(("doc / registry / generator", check_generator_figures, (i,)))

    # Third-decimal drift, the case the first carries() let through: a restated figure
    # that still agrees with the generator after rounding to two places. The figure is the
    # generator's y2 NWC, not a literal: the literal 4.408 went silent when group 9 restated. It read y1 until U4,
    # when y1 became 4.394 and A9.13's y3 gap $4.39M: carries()' every-value-somewhere tier took the gap for the
    # NWC and the case went SILENT (and 4.394 + 0.004 does not even agree at two places).
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import group9_ledger as G
    nwc = "%.3f" % G.working_capital(G.pnl()["cogs"])["nwc"][1]
    r, i = fresh()
    i["A9.13"] = dict(i["A9.13"], value=i["A9.13"]["value"].replace(nwc, "%.3f" % (float(nwc) + 0.004)))
    cases.append(("third-decimal drift", check_generator_figures, (i,),
                  "doc / registry / generator agree"))

    r, i = fresh()
    doctored = rd(GROUP2_DOC).replace("39 SKUs at window start", "40 SKUs at window start")
    cases.append(("catalogue table vs prose", check_catalogue_table, (i, doctored),
                  "catalogue table agrees with its prose and A2.04"))

    r, i = fresh(); i["A10.03"]["value"] = "the chain says nothing."
    cases.append(("group 10 figures", check_group10_figures, (i,)))

    # U8 (2026-10-06): A10.19's call doctored to zero leaves the y3 gap unfinanced, and the check must say so
    r, i = fresh()
    zeroed, hits = re.subn(r"\$[\d.]+M at the signed D0", "$0.00M at the signed D0", i["A10.19"]["value"])
    if hits != 1:
        raise AssertionError("A10.19 no longer prints its size at the signed D0; the U8 case has nothing to doctor")
    i["A10.19"] = dict(i["A10.19"], value=zeroed)
    cases.append(("U8: the equity call doctored to zero", check_equity_call, (i,), EQUITY_CALL_CHECK))
    # U14 (2026-10-27): A10.19 a cent above its ceiling finances the window, and the print rule must still catch it
    import group10_floors as F_note
    r, i = fresh()
    over = "$%.2fM at the signed D0" % (F_note.note(F_note.call_size(F_note.CALL_DATE)) + 0.01)
    raised, hits = re.subn(r"\$[\d.]+M at the signed D0", over, i["A10.19"]["value"])
    if hits != 1:
        raise AssertionError("A10.19 no longer prints its size at the signed D0; the U14 case has nothing to doctor")
    i["A10.19"] = dict(i["A10.19"], value=raised)
    cases.append(("U14: A10.19 printed a cent above the first three-figure amount at or above its size",
                  check_equity_call, (i,), EQUITY_CALL_CHECK))
    SCOPES[cases[-1][0]] = ("A10.19 prints $", "")
    # U16 (2026-10-22): A10.19's date back at August 1 y3, the annual interpolation's, the size untouched
    import group10_floors as F_date
    r, i = fresh()
    dated, hits = re.subn(r"DATE: %s" % _dated(F_date.CALL_DATE), "DATE: August 1 y3", i["A10.19"]["value"])
    if hits != 1:
        raise AssertionError("A10.19 no longer prints its derived date; the U16 case has nothing to doctor")
    i["A10.19"] = dict(i["A10.19"], value=dated)
    cases.append(("U16: A10.19 dated August 1 y3, not the day group 10 derives", check_equity_call, (i,),
                  EQUITY_CALL_CHECK))
    # U16 (2026-10-22): A10.07's y2 hold moved a month, its day untouched -- only the whole-date check can see it
    r, i = fresh()
    moved, hits = re.subn(r"THE CREDIT HOLD on November", "THE CREDIT HOLD on December", i["A10.07"]["value"])
    if hits != 1:
        raise AssertionError("A10.07 no longer prints its y2 hold; the U16 date case has nothing to doctor")
    i["A10.07"] = dict(i["A10.07"], value=moved)
    cases.append(("U16: A10.07's y2 hold a month late", check_daily_dates, (i,), DAILY_DATES_CHECK))
    # U14 (2026-11-03): a pinned row whose short record is doctored to a finding must not stand pinned
    r, i = fresh()
    rec = rd(TIER_A_RECORD)
    # The block doctored is one whose only hold claim is the short record's own verdict: a block that also carries the
    # owner's ruling line holds on that line, so doctoring its verdict alone proves nothing (batch 8, 2026-11-06).
    def _block(k):
        m = re.search(r"^### %s\b.*?(?=^#{2,3} |\Z)" % re.escape(k), rec, re.M | re.S)
        return m.group(0) if m else ""
    pinned = sorted(k for k, v in i.items() if v.get("status") == "pinned"
                    and re.search(r"^### %s\b[^\n]*\n- \*\*Short record" % re.escape(k), rec, re.M)
                    and not re.search(r"Corrected \(owner|Ruled \(owner", _block(k)))
    if not pinned:
        raise AssertionError("no pinned row carries a bare short record; the U14 record case has nothing to doctor")
    head = re.search(r"^### %s\b" % re.escape(pinned[0]), rec, re.M)
    cut = rec.index("**HOLDS**", head.end())
    cases.append(("U14: a pinned row's short record doctored to a finding", check_pinned_records,
                  (i, rec[:cut] + "**FINDING: doctored**" + rec[cut + len("**HOLDS**"):]), PINNED_RECORD_CHECK))
    # ...and a row the owner ruled not pinned, pinned anyway (batch 8: A2.11, A4.05, A5.21, A9.08)
    r, i = fresh()
    held = sorted(k for k, v in i.items() if v.get("status") != "pinned" and k in
                  re.findall(r"^### (A\d+\.\d+)\b", rec, re.M) and _RECORD_UNPINNED.search(_last_ruling(_block(k))))
    if not held:
        raise AssertionError("no record rules a row not pinned; the U14 not-pinned case has nothing to doctor")
    i[held[0]] = dict(i[held[0]], status="pinned")
    cases.append(("U14: a row its record rules not pinned, pinned", check_pinned_records, (i, rec),
                  PINNED_RECORD_CHECK))
    # U14's record check (2), the plan's four scenarios (2026-11-09)
    r, i = fresh()
    in_set = u14_set(i)

    def _drop_heading(k):
        out, hits = re.subn(r"^### %s\b" % re.escape(k), "### (heading removed)", rec, flags=re.M)
        if hits != 1:
            raise AssertionError("%s has no single heading; the U14 set case has nothing to doctor" % k)
        return out
    hop = sorted(k for k in in_set if i[k].get("tier") != "A" and not i[k].get("two_endpoint")
                 and k not in U14_FIRST_ORDER)
    if not hop:
        raise AssertionError("no row is in U14's set by the one hop alone; the set case has nothing to doctor")
    cases.append(("U14: a set row with no heading", check_set_records, (i, _drop_heading(hop[0])), SET_RECORD_CHECK))
    SCOPES[cases[-1][0]] = (hop[0] + " is in U14's set", "")
    pin_a = sorted(k for k in in_set if i[k].get("tier") == "A" and i[k].get("status") == "pinned")
    if not pin_a:
        raise AssertionError("no Tier A row is pinned; the U14 pinned-Tier-A case has nothing to doctor")
    cases.append(("U14: a pinned Tier A row with no heading", check_set_records, (i, _drop_heading(pin_a[0])),
                  SET_RECORD_CHECK))
    SCOPES[cases[-1][0]] = (pin_a[0] + " is in U14's set", "")
    two = sorted(k for k in in_set if i[k].get("two_endpoint"))
    if not two:
        raise AssertionError("no row is two_endpoint; the U14 endpoint case has nothing to doctor")
    one, hits = re.subn(r"(^### %s\b.*?^- \*\*Endpoints\.\*\*.*?)\b(?:Well-run|Achievable|Counterfactual):"
                        % re.escape(two[0]), r"\1Also:", rec, count=1, flags=re.M | re.S)
    if hits != 1:
        raise AssertionError("%s's record states no second endpoint; the U14 endpoint case has nothing to doctor" % two[0])
    cases.append(("U14: a two_endpoint record stating one endpoint", check_set_records, (i, one), SET_RECORD_CHECK))
    SCOPES[cases[-1][0]] = (two[0] + " is two_endpoint", "")
    outside = sorted(k for k in i if k not in in_set and not re.search(r"^### %s\b" % re.escape(k), rec, re.M))
    if not outside:
        raise AssertionError("every row has a heading; the U14 flag-flip case has nothing to doctor")
    r, i = fresh()
    i[outside[0]] = dict(i[outside[0]], two_endpoint=True)
    moved = u14_set(i) ^ in_set
    if moved != {outside[0]}:
        raise AssertionError("flipping %s's two_endpoint moved the set by %s, not by exactly that row"
                             % (outside[0], sorted(moved)))
    cases.append(("U14: a flag flipped onto a row outside the set", check_set_records, (i, rec), SET_RECORD_CHECK))
    SCOPES[cases[-1][0]] = (outside[0] + " is in U14's set", "")
    r, i = fresh()
    i[two[0]] = dict(i[two[0]], two_endpoint=False)
    moved = u14_set(i) ^ in_set
    if moved - {two[0]}:
        raise AssertionError("flipping %s's two_endpoint off moved other rows: %s" % (two[0], sorted(moved)))
    # U17's flag (2026-11-09): a ruled row unflagged, and a row outside the ruling flagged
    r, i = fresh()
    fo = sorted(U14_FIRST_ORDER)[0]
    i[fo] = dict((k, v) for k, v in i[fo].items() if k != "first_order")
    cases.append(("U17: a first-order row unflagged", check_first_order_flag, (i,), FIRST_ORDER_FLAG_CHECK))
    SCOPES[cases[-1][0]] = (fo + " is ruled first-order", "")
    r, i = fresh()
    stray = sorted(k for k in i if k not in U14_FIRST_ORDER)[0]
    i[stray] = dict(i[stray], first_order=True)
    cases.append(("U17: a row outside R16 flagged", check_first_order_flag, (i,), FIRST_ORDER_FLAG_CHECK))
    SCOPES[cases[-1][0]] = (stray + " is flagged first_order", "")
    # U17's close (2026-11-12): a first-order row unsigned, one claiming an outside reviewer, one signed at a
    # fingerprint the row no longer has
    for label, change in (("unsigned", dict(owner_signed=None)),
                          ("carrying verified_by", dict(verified_by="CFO, 2026-11-12")),
                          ("signed at a stale fingerprint", dict(signed_figures="1:000000000000"))):
        r, i = fresh()
        i[fo] = dict(i[fo], **change)
        cases.append(("U17: a first-order row " + label, check_first_order_signed, (i,), FIRST_ORDER_SIGNED_CHECK))
    # ...and the hold claim dropped from A10.19 while every timing still reaches the line (U14, 2026-10-27: the edge
    # claim retired with "at 45", so the case doctors the claim the rows now carry)
    r, i = fresh()
    dropped, hits = re.subn(r"HOLD REACHES AT EVERY AP TIMING", "HOLD", i["A10.19"]["value"])
    if hits != 1:
        raise AssertionError("A10.19 no longer says the y2 hold reaches at every timing; the case has nothing to doctor")
    i["A10.19"] = dict(i["A10.19"], value=dropped)
    cases.append(("U16: A10.19 no longer says the y2 hold reaches at every AP timing", check_daily_dates, (i,),
                  DAILY_DATES_CHECK))
    # U16 (2026-10-22): the daily ledger's own checks, each fed a doctored ledger
    DL16 = F_date._daily()
    E16 = F_date.equity_call()
    cases.append(("U16: y2's daily EBITDA $2K off ledger()'s", check_daily_flows,
                  (dict(DL16, eb=[DL16["eb"][0], DL16["eb"][1] + 0.002, DL16["eb"][2]]),), DAILY_FLOWS_CHECK))
    early = list(E16["after"]["draw"])
    early[10] += 1e-9
    cases.append(("U16: one day's draw moved before the note lands", check_daily_before_note,
                  ([(E16["before"], dict(E16["after"], draw=early), E16["date"])],), DAILY_BEFORE_NOTE_CHECK))
    Q16 = F_date.equity_call(when=F_date.counterfactual_date())
    early_q = list(Q16["after"]["late"])
    early_q[200] += 1e-9
    cases.append(("U16: one day's stretch moved before the counterfactual's note lands", check_daily_before_note,
                  ([(Q16["before"], dict(Q16["after"], late=early_q), Q16["date"])],), DAILY_BEFORE_NOTE_CHECK))
    sched = rd(GROUP9_DOC)
    row = re.search(r"\| 2024-12-01 \| [\d]+ \| [\d]+ \| [\d]+ \|", sched).group(0)
    cases.append(("U16: one AP run of the schedule doctored in group 9's doc", check_ap_schedule,
                  (sched.replace(row, row.replace("| 2024-12-01 |", "| 2024-12-02 |")),), AP_SCHEDULE_CHECK))
    # U17 (2026-11-11): the printed P&L bridges foot. The packet as the owner found it, the two lines between opex
    # and EBITDA missing; one of group 9's opex detail lines moved; and the rounding bound from both sides -- y1's
    # EBITDA a unit off, inside the rounding of its three lines and itself, stays quiet, three units off fires.
    pk, g9 = rd(PACKET_DOC), rd(GROUP9_DOC)
    gap_lines = re.findall(r"\| − (?:Slotting invoiced|Inventory write-offs)[^\n]*\n", pk)
    eb_row = re.search(r"\| = EBITDA \| −0\.\d{3} \|", pk)
    brokers = re.search(r"    brokers \(A9\.09\) +\d\.\d{3}", g9)
    if len(gap_lines) != 2 or not eb_row or not brokers:
        raise AssertionError("the packet's or group 9's P&L bridge changed shape; the U17 bridge cases have nothing "
                             "to doctor")
    dropped = pk
    for line in gap_lines:
        dropped = dropped.replace(line, "")
    cases.append(("U17: the packet's EBITDA table without the lines between opex and EBITDA", check_pnl_foots,
                  ({PACKET_DOC: dropped},), PNL_FOOTS_CHECK))
    b = brokers.group(0)
    cases.append(("U17: one of group 9's opex detail lines a cent of $M off", check_pnl_foots,
                  ({GROUP9_DOC: g9.replace(b, b[:-3] + "%03d" % (int(b[-3:]) + 10))},), PNL_FOOTS_CHECK))
    e = eb_row.group(0)

    def _eb_moved(units):
        v = int(e[-5:-2]) + units
        return pk.replace(e, e[:-5] + "%03d |" % v)
    if _isolated(check_pnl_foots, ({PACKET_DOC: _eb_moved(1)},), PNL_FOOTS_CHECK):
        raise AssertionError("check_pnl_foots fires on a total one unit off, inside its lines' rounding")
    cases.append(("U17: y1's EBITDA three units off, outside the rounding of its three lines and itself", check_pnl_foots,
                  ({PACKET_DOC: _eb_moved(3)},), PNL_FOOTS_CHECK))
    # U17 (2026-11-11): the packet is a watched document. A figure on a page that no source prints; a pin left behind
    # by its row; a credit its named source does not carry.
    ask = "**Check.** Is $25M growing"
    pin9 = re.search(r"^\| 9 \| A4\.01 \| [^|]* \| `\d+:([0-9a-f]{12})`", pk, re.M)
    if pk.count(ask) != 1 or not pin9:
        raise AssertionError("the packet's page 1 question or page 9's pin changed shape; the U17 packet cases have "
                             "nothing to doctor")
    cases.append(("U17: a figure on page 1 that neither its row nor its outputs print", check_packet_figures,
                  (index, pk.replace(ask, "**Check.** Is $913.27M growing")), PACKET_FIGURES_CHECK))
    h = pin9.group(1)
    cases.append(("U17: page 9 pinned to a fingerprint its row no longer has", check_packet_figures,
                  (index, pk.replace(h, h[::-1])), PACKET_FIGURES_CHECK))
    cases.append(("U17: a credit its named desk record does not carry", check_packet_figures,
                  (index, pk, dict(PACKET_CREDITS, **{"A8.01": [("desk", "A8.01", "8.3")]})), PACKET_FIGURES_CHECK))

    # U21: the entry-output check, run after the live gate so the labels its figure checks read are all in _READ.
    # One printed key dropped; one printed value moved a unit in the entry that reads it; a figure check importing
    # a generator.
    cogs = "A9.02's COGS, $M, the row and group 9's P&L block"

    def dropped_key():
        P = dict(_printed())
        del P[cogs]
        check_entry_outputs(printed=P, unfound=set())

    def moved_value():
        e = next(x for x in group11_figures() if x[0] == cogs)
        lost = set()
        check_group11_figures(index, entries=[(e[0], [e[1][0] + 1.0] + list(e[1][1:])) + tuple(e[2:])], unfound=lost)
        check_entry_outputs(unfound=lost)
    imports = rd("scripts/check_anchors.py").replace("def check_ap_schedule(doc=None):\n",
                                                     "def check_ap_schedule(doc=None):\n    import group10_floors\n", 1)
    cases.append(("U21: a printed key dropped", dropped_key, (), ENTRY_OUTPUT_CHECK))
    cases.append(("U21: a printed value moved one unit", moved_value, (), ENTRY_OUTPUT_CHECK))
    cases.append(("U21: a figure check imports a generator", check_entry_outputs, (None, None, set(), imports),
                  ENTRY_OUTPUT_CHECK))

    def _even(L):
        """ledger()'s annual figures spread evenly: each year's draw a straight line, no run held (U16's scenario)."""
        draw, ks = list(L["draw"]), {}
        for k, d in enumerate(L["day"]):
            ks.setdefault(d.year, []).append(k)
        for y, idx in ks.items():
            a, b = draw[idx[0]], draw[idx[-1]]
            for j, k in enumerate(idx):
                draw[k] = a + (b - a) * j / float(len(idx) - 1)
        return dict(L, draw=draw, run_detail=[dict(r, held=0.0) for r in L["run_detail"]])
    cases.append(("U16: ledger()'s year spread evenly has no sawtooth", check_daily_sawtooth, (_even(DL16),),
                  DAILY_SAWTOOTH_CHECK))
    cases.append(("U16: ledger()'s year spread evenly part-holds no run", check_daily_part_held,
                  (_even(DL16), E16["after"]), DAILY_PART_HELD_CHECK))
    swapped = [dict(r) for r in DL16["run_detail"]]
    first = next(r for r in swapped if r["held"] > 1e-9 and r["newest_paid"] and r["newest_paid"] < r["oldest_held"])
    first["newest_paid"], first["oldest_held"] = first["oldest_held"], first["newest_paid"]
    cases.append(("U16: a part-held run that held an older invoice than one it paid", check_daily_part_held,
                  (dict(DL16, run_detail=swapped), E16["after"]), DAILY_PART_HELD_CHECK))

    # 2026-10-09: the small-account channel dropped from, or emptied in, group 9's wholesale roll-up must fire
    no_small = {k: v for k, v in G.SHARE.items() if k != "small"}
    cases.append(("small-account channel dropped from the roll-up", check_small_channel, (no_small,),
                  SMALL_CHANNEL_CHECK))
    zero_small = dict(G.SHARE, small=[0] * len(G.GROSS))
    cases.append(("small-account channel emptied", check_small_channel, (zero_small,), SMALL_CHANNEL_CHECK))
    # the near-miss crossed: VDMP's floor lowered to 90, under the 92.4 the 65% corner reaches
    cases.append(("a card-network floor reached at a corner of A8.21's band", check_card_network_floors,
                  ((90, 0.015, 1500),), CARD_NETWORK_CHECK))
    # slotting leaking into A4.01's rate: A4.05's mix given a slotting type; and net revenue with the deducted share
    # folded back into the rates instead of taken off separately
    import group10_floors as F_slot
    import group9_ledger as G_slot
    leaked_types = dict(F_slot.A405_SHARE, slotting=1)
    cases.append(("slotting counted among A4.05's types", check_slotting_outside_rates, (leaked_types,),
                  SLOTTING_GUARD_CHECK))
    P_slot = G_slot.pnl()
    leaked_pnl = dict(P_slot, net=[P_slot["net"][t] + P_slot["slotting"][t]["deducted"] for t in range(3)])
    cases.append(("slotting's deducted share folded into A4.01's rate", check_slotting_outside_rates,
                  (None, leaked_pnl), SLOTTING_GUARD_CHECK))

    # Group 11's cases doctor the COMPUTED figure, not a literal: a literal goes silent the day a ruling moves it,
    # which is the staleness the header-total case below warns about. The account factor is solved on the draw.
    g11 = dict((f[0], f[1]) for f in group11_figures())
    acct = g11["the factor on the window and the spread it leaves, row"][0]

    def doctor(text, old, new):
        """Break one published claim, and FAIL LOUDLY if the claim is no longer there.

        Both cases below used to doctor `"%.3f" % acct` - the factor at three decimals. When
        #drawn-precision moved the factor to two (2026-09-16) that replace became a no-op and both cases
        went SILENT: the self-test reported 24 of 26 and the two checks it could no longer break were the
        ones guarding every group 11 figure. A silent case is worse than a missing one, so the doctoring
        now asserts, and the next time a precision or a phrase moves the self-test says so instead of
        quietly passing. The same failure, on a hardcoded 262 and then on "4.408", is in FAILURES.md.
        """
        if old not in text:
            raise AssertionError("self-test cannot doctor %r: the text no longer claims it" % old)
        return text.replace(old, new, 1)

    # A solved parameter restated in the row but not re-solved. The shift must be at least one unit of the
    # tag's own precision, or the doctored value rounds back to the published one.
    r, i = fresh()
    i["A11.21"] = dict(i["A11.21"], value=doctor(
        i["A11.21"]["value"], "SOLVES TO %.*f" % (P_FACTOR, acct), "SOLVES TO %.*f" % (P_FACTOR, acct + 0.01)))
    cases.append(("group 11 figures, row", check_group11_figures, (i,),
                  "doc / registry / generator agree, group 11"))

    # The doc side, where a long text once let "0.1 lb" stand in for a solved parameter.
    r, i = fresh()
    cases.append(("group 11 figures, doc", check_group11_figures,
                  (i, doctor(rd(GROUP11_DOC), "the account target: **%.*f**" % (P_FACTOR, acct),
                             "the account target: **%.*f**" % (P_FACTOR, acct - 0.03))),
                  "doc / registry / generator agree, group 11"))

    # A group 11 figure in another group's doc: group 10's tables keep y1's exit count from before the ruling.
    y1 = "**%.2f**" % g11["catalogue exits a year and over the window, group 10's summary table"][0]
    r, i = fresh()
    cases.append(("group 11 figures, another group's doc", check_group11_figures,
                  (i, None, {GROUP10_DOC: rd(GROUP10_DOC).replace(y1, "**1.60**")}),
                  "doc / registry / generator agree, group 11"))

    # A whole number, checked at no decimals: y1's complaints move by one.
    n = "%.0f" % g11["A11.08 complaints, then a working day, row"][0]
    r, i = fresh()
    i["A11.08"] = dict(i["A11.08"], value=re.sub(r"(?<![\d,])%s(?!\d)" % n, "%d" % (int(n) + 1),
                                                 i["A11.08"]["value"], count=1))
    cases.append(("group 11 whole number", check_group11_figures, (i,),
                  "doc / registry / generator agree, group 11"))

    # A range whose high end moves: checked as two numbers, y1's 27-40 passed on y3's "45-67".
    lo, hi = g11["A11.13 swell against the type at the distributors' share, then retailers' damaged rate needed"][3]
    r, i = fresh()
    i["A11.13"] = dict(i["A11.13"], value=i["A11.13"]["value"].replace("%.0f-%.0f" % (lo, hi), "%.0f-%.0f" % (lo, hi - 5)))
    cases.append(("group 11 range", check_group11_figures, (i,),
                  "doc / registry / generator agree, group 11"))

    # A lone figure is anchored to its phrase: the revenue test's gross moves by a million.
    b = "%.1f" % g11["A11.25 revenue test, 2024 gross $M"][0]
    r, i = fresh()
    cases.append(("group 11 anchored single", check_group11_figures,
                  (i, rd(GROUP11_DOC).replace("invoice prices, is $%s" % b,
                                              "invoice prices, is $%.1f" % (float(b) + 1))),
                  "doc / registry / generator agree, group 11"))

    # A9.13's FCCR and A9.14's rate, watched 2026-09-30, probed by RESTORING THE EXACT FIGURES the ruling of that day
    # retired: the FCCR the row printed for y2 and y3, the 2024 prime mean, and the all-in rate built on it. The text
    # searched for is the ledger's, so doctor() fails loudly if a row stops printing it. The doc is read normalised,
    # as the check reads it, so its Unicode minus is the ASCII one here.
    fc = tuple("%.2f" % x for x in g11["A9.13's FCCR, the row and group 9's doc"])
    r, i = fresh()
    i["A9.13"] = dict(i["A9.13"], value=doctor(i["A9.13"]["value"], "FCCR %s / %s / %s" % fc,
                                                "FCCR %s / -1.45 / -1.32" % fc[0]))
    cases.append(("group 9 FCCR, row", check_group11_figures, (i,), "doc / registry / generator agree, group 11"))
    r, i = fresh()
    cases.append(("group 9 FCCR, doc", check_group11_figures,
                  (i, None, {GROUP9_DOC: doctor(norm(rd(GROUP9_DOC)), "FCCR %s / %s / %s" % fc,
                                                "FCCR %s / -1.45 / -1.32" % fc[0])}),
                  "doc / registry / generator agree, group 11"))
    pm = ["%.2f" % (sum(m) / 12) for m in G.PRIME_MONTHLY]
    r, i = fresh()
    i["A9.14"] = dict(i["A9.14"], value=doctor(i["A9.14"]["value"], "2024 %s%%" % pm[1], "2024 8.36%"))
    cases.append(("group 9 prime mean, row", check_group11_figures, (i,), "doc / registry / generator agree, group 11"))
    r, i = fresh()
    src = [dict(s) for s in i["A9.14"]["sources"]]
    src[0]["figure"] = doctor(src[0]["figure"], "2024 avg %s" % pm[1], "2024 avg 8.36")
    i["A9.14"] = dict(i["A9.14"], sources=src)
    cases.append(("group 9 prime mean, sources", check_group11_figures, (i,),
                  "doc / registry / generator agree, group 11"))
    ai = ["%.2f" % (x * 100) for x in G.PRIME_PLUS]
    r, i = fresh()
    i["A9.14"] = dict(i["A9.14"], value=doctor(i["A9.14"]["value"], "all-in %s%% / %s%%" % (ai[0], ai[1]),
                                                "all-in %s%% / 9.86%%" % ai[0]))
    cases.append(("group 9 all-in rate, row", check_group11_figures, (i,), "doc / registry / generator agree, group 11"))
    ac = tuple("%.3f" % x for x in g11["A9.13's accrual in unpaid invoices, then the residual net of recovery, "
                                      "the row and group 9's doc"][:3])
    r, i = fresh()
    i["A9.13"] = dict(i["A9.13"], value=doctor(i["A9.13"]["value"], "invoices %s / %s / %s" % ac,
                                                "invoices %s / 0.638 / 0.767" % ac[0]))
    cases.append(("group 9 accrual, row", check_group11_figures, (i,), "doc / registry / generator agree, group 11"))
    fg = tuple("%.3f" % x for x in g11["A9.12's finished goods, the row"])
    r, i = fresh()
    i["A9.12"] = dict(i["A9.12"], value=doctor(i["A9.12"]["value"], "%s / %s / %s" % fg,
                                                "%s / 2.587 / 3.089" % fg[0]))
    cases.append(("group 9 finished goods, row", check_group11_figures, (i,),
                  "doc / registry / generator agree, group 11"))
    gp = tuple("%.3f" % x for x in g11["A9.02's gross profit, net revenue less COGS, the row and group 9's doc"])
    r, i = fresh()
    i["A9.02"] = dict(i["A9.02"], value=doctor(i["A9.02"]["value"], "gross profit %s / %s / %s" % gp,
                                                "gross profit %s / 8.564 / 9.790" % gp[0]))
    cases.append(("group 9 gross profit, row", check_group11_figures, (i,),
                  "doc / registry / generator agree, group 11"))

    # U4's watches (2026-10-01), each probed by RESTORING the figure U4 retired (#probe-before-trust). The text
    # searched for is the generator's, so doctor() fails loudly if a site stops printing it.
    g11a = "doc / registry / generator agree, group 11"
    g10a = "doc / registry / generator agree, group 10"
    cy = g11["A9.12's cash conversion cycle y1 -> y3, group 9's doc"]
    r, i = fresh()
    cases.append(("U4: A9.12's cycle back at 73 days in y3", check_group11_figures,
                  (i, None, {GROUP9_DOC: doctor(norm(rd(GROUP9_DOC)), "DSO + DIO - DPO = %.0f -> %.0f" % tuple(cy),
                                                "DSO + DIO - DPO = %.0f -> 73" % cy[0])}), g11a))
    fp = tuple("%.3f" % x for x in g11["A9.14's finished goods at the November peak"])
    r, i = fresh()
    i["A9.14"] = dict(i["A9.14"], value=doctor(i["A9.14"]["value"], "at the November peak %s / %s / %s" % fp,
                                                "at the November peak %s / 3.619 / 4.322" % fp[0]))
    cases.append(("U4: A9.14's peak finished goods back at 3.619 / 4.322", check_group11_figures, (i,), g11a))
    b2 = g11["A9.14's sizing: the projected y2 base, and the margin the $4.5M commitment clears it by"][0]
    r, i = fresh()
    i["A9.14"] = dict(i["A9.14"], value=doctor(i["A9.14"]["value"], "base of $%.3fM" % b2, "base of $4.605M"))
    cases.append(("U4: A9.14's projected y2 base back at $4.605M", check_group11_figures, (i,), g11a))
    ox = tuple("%.3f" % x for x in g11["A9.02's copy of A9.01's opex"])
    r, i = fresh()
    i["A9.02"] = dict(i["A9.02"], value=doctor(i["A9.02"]["value"], "carried as a literal) %s / %s / %s" % ox,
                                                "carried as a literal) 7.617 / 8.953 / 10.391"))
    cases.append(("U4: A9.02's opex copy back at 10.391", check_group11_figures, (i,), g11a))
    dp = tuple("%.1f" % x for x in g11["A9.15's deductions per invoice, y1 -> y3"])
    r, i = fresh()
    i["A9.15"] = dict(i["A9.15"], value=doctor(i["A9.15"]["value"], "at %s -> %s deductions per invoice" % dp,
                                                "at 1.9 -> 2.7 deductions per invoice"))
    cases.append(("U4: A9.15's deductions per invoice back at 1.9 -> 2.7", check_group11_figures, (i,), g11a))
    wm = tuple(int(x) for x in g11["A5.02's Walmart POs, group 5's doc"])
    r, i = fresh()
    cases.append(("U4: A5.02's Walmart y3 POs back at 728", check_group11_figures,
                  (i, None, {GROUP5_DOC: doctor(norm(rd(GROUP5_DOC)), "Walmart weekly per DC (%d y1 -> %d -> %d)" % wm,
                                                "Walmart weekly per DC (%d y1 -> %d -> 728)" % wm[:2])}), g11a))
    # A5.07's count as it read before U4 ruled the cap at every account: Kroger's late cancels alone
    import group10_floors as F10
    lc = [F10.late_cancels(t) for t in range(3)]
    r, i = fresh()
    i["A5.07"] = dict(i["A5.07"], value=doctor(
        i["A5.07"]["value"], "%.2f / %.2f / %.2f POs a year" % tuple(x["total"] for x in lc),
        "%.2f / %.2f / %.2f POs a year" % tuple(x["by_account"]["Kroger"] for x in lc)))
    cases.append(("U4: A5.07's late cancels back at Kroger's alone", check_group11_figures, (i,), g11a))
    sw = g11["A11.13 the swell base at UNFI and KeHE, y2 and y3, row"]
    r, i = fresh()
    i["A11.13"] = dict(i["A11.13"], value=doctor(i["A11.13"]["value"], "UNFI and KeHE is $%.3fM and $%.3fM" % tuple(sw),
                                                  "UNFI and KeHE is $7.495M and $7.989M"))
    cases.append(("U4: A11.13's swell base back at $7.495M", check_group11_figures, (i,), g11a))
    # U16 (2026-10-22): A10.07's y1 verdict back at the annual ladder's "short of every consequence"
    r, i = fresh()
    i["A10.07"] = dict(i["A10.07"], value=doctor(i["A10.07"]["value"], "y1 reaches PRIORITY LOSS on",
                                                  "y1 is past terms and short of every consequence, on"))
    cases.append(("U16: A10.07's y1 verdict back at the annual ladder's", check_daily_dates, (i,), DAILY_DATES_CHECK))
    r, i = fresh()
    i["A10.11"] = dict(i["A10.11"], value=doctor(i["A10.11"]["value"],
                                                  "derive to $%.4fM" % sum(F10.fines(2).values()),
                                                  "derive to $0.1561M"))
    cases.append(("U4: A10.11's y3 fines back at $0.1561M", check_group10_figures, (i,), g10a))
    pn = F10.penetration()
    r, i = fresh()
    i["A7.20"] = dict(i["A7.20"], value=doctor(i["A7.20"]["value"], "give penetration %.2f%% / %.2f%% / %.2f%%"
                                                % tuple(pn), "give penetration %.2f%% / %.2f%% / 2.36%%" % tuple(pn[:2])))
    cases.append(("U4: A7.20's y3 penetration back at 2.36%", check_group10_figures, (i,), g10a))
    # the worklist's Status cell, compared since U4: A7.10 flipped to a status the registry does not give it
    r, i = fresh()
    wl = rd(WORKLIST)
    a710 = re.search(r"^\| `A7\.10` \|.*$", wl, re.M).group(0)
    cases.append(("U4: the worklist's Status cell drifts from the registry", check_worklist_parity,
                  (i, wl.replace(a710, doctor(a710, "| %s |" % i["A7.10"]["status"], "| candidate |"))),
                  "worklist parity"))

    # A structure, not a figure: the generator stops leaving y2 short of exhaustion.
    def facts_broken(index):
        saved = list(_GROUP11_FACTS)
        try:
            _GROUP11_FACTS[:] = [(label, False, words) for label, _, words in saved]
            check_group11_figures(index)
        finally:
            _GROUP11_FACTS[:] = saved
    r, i = fresh()
    cases.append(("group 11 structural fact", facts_broken, (i,),
                  "doc / registry / generator agree, group 11"))

    # THE PRINT RULE (U5): a figure restated past two significant figures is reported -- A8.06's whole subscriber
    # counts restated at a decimal, its watch's `places` moved with it as the site-precision rule requires, so the
    # figures still match and only the report can see them
    import group8_dtc as D8T
    cb = [D8T.active_subscribers(t) for t in range(3)]
    r, i = fresh()
    i["A8.06"] = dict(i["A8.06"], value=doctor(i["A8.06"]["value"], "~{:,.0f} / {:,.0f} / {:,.0f}".format(*cb),
                                                "~%.1f / %.1f / %.1f" % tuple(cb)))

    def restated_at_a_decimal(index):
        group11_figures()
        saved = list(_GROUP11)
        try:
            _GROUP11[:] = [(lab, v, w, 1, pr, af) if lab == "A8.06's active own-site subscribers" and w == ("A8.06", D8)
                           else (lab, v, w, p, pr, af) for lab, v, w, p, pr, af in saved]
            if _GROUP11 == saved:
                raise AssertionError("A8.06's subscriber watch is gone; the print-rule case has nothing to restate")
            check_group11_figures(index)
        finally:
            _GROUP11[:] = saved
    D8 = GROUP8_DOC
    cases.append(("U5: a restated figure printed past two significant figures", restated_at_a_decimal, (i,),
                  PRINT_RULE_CHECK))
    # ...and U5's own scenarios for the matcher: compared at the token's precision, a real move still fires
    # ...and the floor: a token coarser than the site prints carries nothing (the 255 probes of 2026-10-02)
    for tok, v, p, ok in (("0.94", 0.940932, 2, True), ("0.94", 0.9512, 2, False), ("43", 43.06, 0, True),
                          ("8.452", 8.4519, 3, True), ("355", 354.9, 0, True), ("62,292", 62293.0, 0, False),
                          ("0.94", 0.9404, 3, False), ("62,000", 62292.0, 0, False), ("62,000", 62292.0, -3, True)):
        if token_matches(tok, v, p) != ok:
            raise AssertionError("token_matches(%r, %r, %r) should be %s" % (tok, v, p, ok))

    # EACH GROUP-11 CASE PROVES ITS OWN ENTRY (owner, 2026-09-30; U5). The check reports every finding under one
    # name, so a case credited on the name alone "fires" on any live finding without its edit. A case fires only on
    # a message from the entry it doctors, at the site it doctors: (entry label, site), the site as the message
    # names it. The runner refuses a check_group11_figures case with no scope, so a new case cannot skip this.
    D11, D10s, D9s, D5s = GROUP11_DOC, GROUP10_DOC, GROUP9_DOC, GROUP5_DOC
    SCOPES["group 11 structural fact"] = (_GROUP11_FACTS[0][0] + ": ", "the generator no longer has that shape")
    SCOPES["U5: a restated figure printed past two significant figures"] = (
        "A8.06's active own-site subscribers: A8.06 prints ", "%.1f" % cb[2])
    SCOPES.update((name, (label + ": ", "; %s does not carry it" % site)) for name, (label, site) in {
        "group 11 figures, row": ("the factor on the window and the spread it leaves, row", "A11.21"),
        "group 11 figures, doc": ("the factor on the window and the spread it leaves, doc", D11),
        "group 11 figures, another group's doc": ("catalogue exits a year and over the window, group 10's summary "
                                                  "table", D10s),
        "group 11 whole number": ("A11.08 complaints, then a working day, row", "A11.08"),
        "group 11 range": ("A11.13 swell against the type at the distributors' share, then retailers' damaged rate "
                           "needed", "A11.13"),
        "group 11 anchored single": ("A11.25 revenue test, 2024 gross $M", D11),
        "group 9 FCCR, row": ("A9.13's FCCR, the row and group 9's doc", "A9.13"),
        "group 9 FCCR, doc": ("A9.13's FCCR, the row and group 9's doc", D9s),
        "group 9 prime mean, row": ("A9.14's prime annual means, each the mean of its year's published months, the "
                                    "row and group 9's doc", "A9.14"),
        "group 9 prime mean, sources": ("A9.14's prime annual means, its sources entry", "A9.14:sources[0].figure"),
        "group 9 all-in rate, row": ("A9.14's all-in rate, each year's mean plus the spread, the row and group 9's "
                                     "doc", "A9.14"),
        "group 9 accrual, row": ("A9.13's accrual in unpaid invoices, then the residual net of recovery, the row and "
                                 "group 9's doc", "A9.13"),
        "group 9 finished goods, row": ("A9.12's finished goods, the row", "A9.12"),
        "group 9 gross profit, row": ("A9.02's gross profit, net revenue less COGS, the row and group 9's doc",
                                      "A9.02"),
        "U4: A9.12's cycle back at 73 days in y3": ("A9.12's cash conversion cycle y1 -> y3, group 9's doc", D9s),
        "U4: A9.14's peak finished goods back at 3.619 / 4.322": ("A9.14's finished goods at the November peak",
                                                                  "A9.14"),
        "U4: A9.14's projected y2 base back at $4.605M": ("A9.14's sizing: the projected y2 base, and the margin the "
                                                          "$4.5M commitment clears it by", "A9.14"),
        "U4: A9.02's opex copy back at 10.391": ("A9.02's copy of A9.01's opex", "A9.02"),
        "U4: A9.15's deductions per invoice back at 1.9 -> 2.7": ("A9.15's deductions per invoice, y1 -> y3", "A9.15"),
        "U4: A5.02's Walmart y3 POs back at 728": ("A5.02's Walmart POs, group 5's doc", D5s),
        "U4: A5.07's late cancels back at Kroger's alone": ("A5.07's late cancels: POs a year, then their share of "
                                                            "POs, A5.07, A5.10 and group 5's doc", "A5.07"),
        "U4: A11.13's swell base back at $7.495M": ("A11.13 the swell base at UNFI and KeHE, y2 and y3, row",
                                                    "A11.13"),
    }.items())

    r, i = fresh()
    # Doctor whatever total the header currently claims -- hardcoding it meant the
    # case went silent the moment group 10 added a row, which is the staleness this
    # check exists to catch, in the test for it.
    doctored = re.sub(r"(\*\*Anchors to verify\*\* \| \*\*)\d+(\*\*)",
                      r"\g<1>999\g<2>", rd(WORKLIST))
    cases.append(("worklist header total", check_worklist_parity, (i, doctored),
                  "worklist header total equals its tables"))

    # The mirror check. Doctor the ROW, not the generator: the generator is imported once per
    # process and a module-level constant cannot be put back, so doctoring it would leak into
    # every later case. Moving A5.38's own prose is the same disagreement seen from the other
    # side, and it is what the check exists to catch -- a registered input and a transcription
    # of it that no longer agree.
    r, i = fresh()
    i["A5.38"] = dict(i["A5.38"], value=str(i["A5.38"]["value"]).replace("KeHE 8/9.5/9", "KeHE 8/7.5/7"))
    # RULE 1's own proof. Three doctored locators, one per way a locator has gone stale here.
    def locators_named(kind):
        bad = {"id": r"A9\.01's ladder\s+", "date": r"restated 2026-09-18\s+",
               "magnitude": r"\$2\.945 a jar\s+"}[kind]
        return lambda: check_locator_hygiene([("doctored", [1.0], ("A9.01",), 3, False, bad)])
    for kind in ("id", "date", "magnitude"):
        cases.append(("locator names %s" % kind, locators_named(kind), (),
                      "locators anchor on sentence content only"))

    # ---- DECISIONS#probe-before-trust: the new check is probed by RESTORING THE EXACT VALUE
    # it should catch, not by an invented wrong number. Two cases, one per way this check can
    # fail: a wrong combinatorial form, and a wrong parameterisation of the same distribution.
    def closed_form_case(kind):
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import group10_floors as F
        mean, sd, line = F.ONTIME[2], F.SD_ONTIME, 80.0
        if kind == "combinatorics":
            _, pair, _ = F.quarter_risk(mean, sd, line)
            wrong = 1.0 - (1.0 - pair) ** 3          # THE 2026-09-21 DEFECT, restored exactly

            def draw(rng):
                q = [sum(rng.gauss(mean, sd) for _ in range(3)) / 3.0 < line for _ in range(4)]
                return (any(q[i] and q[i + 1] for i in range(3)),)

            return lambda: check_closed_forms(
                [("the retired adjacency form", [("year risk", wrong)], draw, 120000)])
        # The standing way to get a log-normal wrong: read the stated ARITHMETIC mean as the
        # median, so mu keeps the sigma^2 / 2 that belongs to it.
        idx, floor, sg = F.VELOCITY_INDEX[0], F.VELOCITY_FLOOR["Kroger"], F.SIGMA_VELOCITY
        wrong_mu = math.log(idx)

        def draw2(rng):
            x = rng.lognormvariate(wrong_mu, sg)
            return (x < floor, x)

        return lambda: check_closed_forms(
            [("the median read as the mean",
              [("share below the floor", F.below_floor(idx, floor, sg)),
               ("the arithmetic mean it claims", idx)], draw2, 150000)])

    # The level ruling of 2026-09-22 is a RULE, so its check is probed by RESTORING THE EXACT PLANS it
    # replaced: the 2026-09-05 doors, which no longer clear A5.28's floor, and the epsilon plan of the same
    # day, which clears the floor but is NOT in the family -- no single factor produces it. The second case is
    # the one the exact search was written for, and the old bisection passed it.
    def door_plan_case(doors):
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import group10_floors as F

        def run():
            saved = F.A704_DOORS
            F.A704_DOORS = dict((k, list(v)) for k, v in (doors or F.A704_BASE).items())
            try:
                check_door_plan_minimum(None)
            finally:
                F.A704_DOORS = saved
        return run
    cases.append(("the door plan before the ruling", door_plan_case(None), (),
                  "the door plan is the minimum that clears A5.28's floor"))
    cases.append(("the door plan the solver's epsilon produced", door_plan_case(
        {"Walmart": [1013, 1575, 2251], "Kroger": [1238, 1294, 1350], "WF": [450, 473, 507],
         "Regional": [90, 96, 102], "Sprouts": [0, 225, 440], "Costco": [0, 0, 60],
         "independents": [1575, 2025, 2476]}), (),
        "the door plan is the minimum that clears A5.28's floor"))

    def closed_form_mixture():
        """The retired single-log-normal Lorenz share, restored exactly (ruled out 2026-09-21)."""
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import group10_floors as F
        M = F.deduction_mixture()
        qs = F.filing_cascade()["by_count"]
        cuts = [F._mixture_quantile(M["parts"], 1 - q) for q in qs]
        retired = [NORM.cdf(M["sigma"] - NORM.inv_cdf(1 - q)) for q in qs]

        def draw(rng):
            u = rng.random() * sum(w for _, w, _, _, _, _ in M["parts"])
            acc = 0.0
            for _, w, mu, sg, _, _ in M["parts"]:
                acc += w
                if u <= acc:
                    break
            x = math.exp(mu + sg * rng.gauss(0, 1))
            return tuple(x / M["mean"] if x <= c else 0.0 for c in cuts)

        return lambda: check_closed_forms(
            [("the retired single-log-normal Lorenz share",
              [("y%d dollars below the cut" % (i + 1), 1 - retired[i]) for i in range(3)],
              draw, 300000)])

    cases.append(("closed form wrong: a mixture read as one log-normal", closed_form_mixture(), (),
                  "closed forms agree with a draw of their mechanism"))

    for kind in ("combinatorics", "parameterisation"):
        cases.append(("closed form wrong: %s" % kind, closed_form_case(kind), (),
                      "closed forms agree with a draw of their mechanism"))
    # And the coverage arm: a table that covers nothing must name the whole surface.
    cases.append(("closed form surface uncovered",
                  lambda: check_closed_forms([("nothing at all", [("x", 0.5)],
                                               lambda rng: (rng.random() < 0.5,), 400)]), (),
                  "every closed form carries a draw"))

    cases.append(("generator mirrors the registry", check_generator_mirrors, (i,),
                  "generator constants mirror the registry"))

    # A signature that no longer covers the row's figures. Every probe starts from a row RE-SIGNED IN MEMORY at its
    # own current fingerprint, so it fires on its doctoring and on nothing else -- until 2026-09-23 four of these
    # fired on rows the registry had lapsed, and so proved nothing (verification, wf_eb037b24-d7a).
    r, i4 = fresh()

    def resigned(rid, **edits):
        x = dict(i4[rid])
        x["owner_signed"] = x.get("owner_signed") or "2026-09-23"   # signed in memory too: a held row is unsigned
        x[SIGNED_FIGURES] = fingerprint_str(x)
        x.update(signature_snapshot(x))
        if _isolated(check_signed_figures, ([x],), "a signed row still publishes the figures it was signed on"):
            raise AssertionError("self-test base %s fires undoctored" % rid)
        x.update(edits)
        return x
    sf = "a signed row still publishes the figures it was signed on"
    a408 = i4["A4.08"]
    # THE CARRY (owner, 2026-10-19, DECISIONS#signature-carry), each side. A408's first figure printed to two or more
    # decimals is reprinted one decimal coarser: that alone CARRIES -- the check must stay silent and signature_carry
    # must name the pair. The same reprint with a figure added to the denominator LAPSES. And drift: a figure
    # owner-signed at 0.445 and reprinted 0.5 lapses, although 0.5 is what a carried 0.45 would round to -- the
    # comparison is against the owner-signed figure, never a carried one.
    tok = next(t for t in fingerprint_figures(a408["value"]) if len(t.partition(".")[2]) >= 2)
    coarse = "%.*f" % (len(tok.partition(".")[2]) - 1, float(tok))
    reprinted = re.sub(r"(?<![\d.])%s(?![\d])" % re.escape(tok), coarse, str(a408["value"]), count=1)
    carry_row = resigned("A4.08", value=reprinted)
    if _isolated(check_signed_figures, ([carry_row],), sf) or not signature_carry(carry_row)[0]:
        raise AssertionError("A4.08's %s reprinted %s does not carry its signature" % (tok, coarse))
    cases.append(("a carried reprint lapses once another fingerprinted field moves", check_signed_figures,
                  ([resigned("A4.08", value=reprinted, denominator=str(a408.get("denominator") or "") + " over 52 weeks")],),
                  sf))
    drift = resigned("A4.08", value=str(a408["value"]) + " A drift probe of 0.445.")
    drift[SIGNED_FIGURES] = fingerprint_str(drift)
    drift.update(signature_snapshot(drift))           # owner-signed with 0.445 in it
    if _isolated(check_signed_figures, ([dict(drift, value=str(drift["value"]).replace("of 0.445.", "of 0.45."))],), sf):
        raise AssertionError("the drift base: 0.445 reprinted 0.45 should carry")
    drift = dict(drift, value=str(drift["value"]).replace("of 0.445.", "of 0.5."))
    cases.append(("a figure owner-signed 0.445 drifts to 0.5 through a carried 0.45", check_signed_figures, ([drift],),
                  sf))
    # THE FINER REPRINT (owner, 2026-11-10, DECISIONS#u17-start), each side. Owner-signed at 0.45: a reprint at 0.454
    # only adds precision, rounds to 0.45 at the signed precision, and CARRIES; a reprint at 0.456 rounds to 0.46 and
    # LAPSES.
    fine = resigned("A4.08", value=str(a408["value"]) + " A precision probe of 0.45.")
    fine[SIGNED_FIGURES] = fingerprint_str(fine)
    fine.update(signature_snapshot(fine))             # owner-signed with 0.45 in it
    fine_ok = dict(fine, value=str(fine["value"]).replace("of 0.45.", "of 0.454."))
    if _isolated(check_signed_figures, ([fine_ok],), sf) or not signature_carry(fine_ok)[0]:
        raise AssertionError("the finer-reprint base: 0.45 reprinted 0.454 should carry")
    cases.append(("a figure owner-signed 0.45 reprinted finer at 0.456, which rounds to 0.46", check_signed_figures,
                  ([dict(fine, value=str(fine["value"]).replace("of 0.45.", "of 0.456."))],), sf))
    # A figure ADDED, the case the wording had to be widened to catch and the one A11.01 hit on 2026-09-21.
    cases.append(("a signed row gains a figure", check_signed_figures,
                  ([resigned("A4.08", value=str(a408["value"]) + " A stray magnitude of 1.2345 appears.")],), sf))
    # One probe per field the fingerprint was widened to (owner, 2026-09-23). The first restores the exact shares
    # that moved under A11.28's signature on 2026-09-22 with the gate clean (DECISIONS#probe-before-trust).
    pa = str(i4["A11.28"]["plausibility_anchor"])
    cases.append(("A11.28's variance shares restored to 9.9 / 33.3 in its plausibility_anchor", check_signed_figures,
                  ([resigned("A11.28", plausibility_anchor=pa.replace("10.2%", "9.9%").replace("34.2%", "33.3%"))],),
                  sf))
    for field, text in (("figure", " Source reads 7.25."), ("denominator", " over 52 weeks"),
                        ("measured", " Measured at 3.5.")):
        cases.append(("a signed row gains a figure in its %s" % field, check_signed_figures,
                      ([resigned("A4.08", **{field: str(a408.get(field) or "") + text})],), sf))
    # And the three shapes _NUMBER could not see, each on the row the verification found it in: a range's upper
    # bound (A11.28's 4-7%), a leading-dot decimal (A3.02's Walmart .48) and an NxM's second operand (A2.01's 2x18).
    for rid, field, was, now in (("A11.28", "plausibility_anchor", "4-7%", "4-9%"),
                                 ("A3.02", "value", "Walmart .48", "Walmart .52"),
                                 ("A2.01", "value", "2x18", "2x20"),
                                 ("A10.16", "value", "2.86:1", "2.87:1")):
        text = str(i4[rid][field])
        if was not in text:
            raise AssertionError("self-test: %r not found in %s.%s" % (was, rid, field))
        cases.append(("%s's %s moved unseen by the old reader" % (rid, was), check_signed_figures,
                      ([resigned(rid, **{field: text.replace(was, now, 1)})],), sf))
    a409 = dict(i4["A4.09"])
    a409.pop(SIGNED_FIGURES, None)
    # And a signature with no fingerprint at all, which is how the field goes missing on a new row.
    cases.append(("a signed row carries no fingerprint", check_signed_figures, ([a409],),
                  "a signed row still publishes the figures it was signed on"))
    # The YAML alias that broke the registry during the backfill: two rows, ONE list object.
    shared = ["A1.05"]
    x1, x2 = dict(i4["A3.04"]), dict(i4["A3.06"])
    x1["depends_on"] = x2["depends_on"] = shared
    cases.append(("two rows share one list (a YAML alias)", check_no_shared_nodes, ([x1, x2],),
                  "no two rows share one object (no YAML aliases)"))

    # A8.01's headline, probed the way PLAN records it failing: restate the row to 12% and
    # watch both generators' S_DTC disagree. Before 2026-09-21 this doctoring left the gate CLEAN.
    r, i2 = fresh()
    i2["A8.01"] = dict(i2["A8.01"], value=str(i2["A8.01"]["value"]).replace(
        "DTC SHARE OF GROSS (A1.03) = 10%", "DTC SHARE OF GROSS (A1.03) = 12%"))
    cases.append(("A8.01's headline restated to 12%", check_generator_mirrors, (i2,),
                  "generator constants mirror the registry"))

    # A11.01's current-state share, doctored the way a cascade would move it.
    r, i3 = fresh()
    i3["A11.01"] = dict(i3["A11.01"], value=str(i3["A11.01"]["value"]).replace(
        "at 30 / 35 / 40% of it IN THE CURRENT STATE", "at 30 / 35 / 45% of it IN THE CURRENT STATE"))
    cases.append(("A11.01's current-state share moved to 45%", check_generator_mirrors, (i3,),
                  "generator constants mirror the registry"))

    # The same check on the transcriptions of 2026-09-18: A6.26's mapping, two controls' weights exchanged. Every
    # total still sums to 100, which is why only the mirror can see it.
    r, i = fresh()
    i["A6.26"] = dict(i["A6.26"], value=doctor(str(i["A6.26"]["value"]), "label/ASN edi 60 / item_setup 40",
                                               "label/ASN edi 40 / item_setup 60"))
    cases.append(("generator mirrors A6.26", check_generator_mirrors, (i,),
                  "generator constants mirror the registry"))

    # The mirrors added 2026-09-23 with A9.02's derived achievable and the restated 21. Each case restores the wrong
    # value its mirror exists to catch, in memory (#probe-before-trust).
    gm = "generator constants mirror the registry"

    def mirrored(rid, field, old, new):
        _, i5 = fresh()
        i5[rid] = dict(i5[rid])
        i5[rid][field] = doctor(str(i5[rid][field]), old, new)
        return (i5,)
    # A4.15's achievable read one-sided, "within 2%" as 0 to 2% over accrual: a midpoint of 1, not 0
    cases.append(("A4.15's achievable read one-sided", check_generator_mirrors,
                  mirrored("A4.15", "value", "-> achievable within +/-2%", "-> achievable within +0-2%"), gm))
    # A8.11's achievable back at the 34% it printed until U4 derived it: its own components give 35%
    cases.append(("A8.11's achievable at the retired 34%", check_generator_mirrors,
                  mirrored("A8.11", "value", "-> contribution 35%", "-> contribution 34%"), gm))
    # A4.01's y3 line read on the 6.54 bucket base, the confusion the retired achievable's deduction term made
    cases.append(("A4.01's y3 on the bucket base", check_generator_mirrors,
                  mirrored("A4.01", "value", "/ 6.0% of gross", "/ 6.54% of gross"), gm))
    # A9.06's FTE back at the 0.3 A4.06 once cited
    cases.append(("A9.06's FTE at the cited 0.3", check_generator_mirrors,
                  mirrored("A9.06", "value", "dispute share is 0.45 FTE (y1, y2) / 0.50 (y3)",
                           "dispute share is 0.3 FTE (y1, y2) / 0.3 (y3)"), gm))
    # A3.01's layers taken as 2.10 x 1.24 = 2.604, the "+7% + 17%" the ruling called a description that rounded
    cases.append(("A3.01's cost at 2.10 x 1.24", check_generator_mirrors,
                  mirrored("A3.01", "value", "0.15 + 0.36 = 2.61", "0.15 + 0.36 = 2.60"), gm))
    # A11.30's plausibility band back at "a fifth to a third", the words the restatement replaced
    cases.append(("A11.30's band at a third", check_generator_mirrors,
                  mirrored("A11.30", "plausibility_anchor", "ACoS of 20-30% of the sale", "ACoS of 20-33% of the sale"),
                  gm))
    # Group 2's line table as it stood before the 33.8 fl oz oil was marked club
    import group10_floors as F
    table_before = doctor(rd(GROUP2_DOC), "| 8 (7 glass, 1 tin) | 1 |", "| 8 (7 glass, 1 tin) | 0 |")
    cases.append(("group 2's table, oil not club", lambda: report(BLOCK, gm, _a201_line_mirror(F, table_before)), (),
                  gm))

    # Every generator constant that names a row, probed the way the audit found the class open (2026-09-24): A4.05's
    # short_ship doctored 26 -> 21 IN THE ROW left the gate CLEAN, because group10_floors.A405_SHARE kept its own 26.
    gp = "every generator constant that names a row publishes its value there"
    r, i = fresh()
    i["A4.05"] = dict(i["A4.05"], value=re.sub(r"short_ship\s+26", "short_ship 21", str(i["A4.05"]["value"])))
    cases.append(("A4.05's short_ship 26 -> 21", check_generator_constants_published, (i,), gp))
    # ...and an exemption scoped to one element does not stop the others being watched: ASK[0] is exempt, ASK[1] is
    # the owner-signed +2% and must still fire when A3.22 stops printing it. EVERY standalone 2 goes: the row also
    # prints "band 2-4%" and "about 1-2%", and the first version of this case left those standing and was silent.
    r, i = fresh()
    a322 = dict(i["A3.22"])
    for f in FINGERPRINTED_FIELDS:
        if isinstance(a322.get(f), str):
            a322[f] = re.sub(r"(?<![\d.])2(?:\.0)?(?![\d.])", "2.5", a322[f])
    i["A3.22"] = a322
    cases.append(("A3.22's +2% gone, ASK[1] fires", check_generator_constants_published, (i,), gp))
    # A registered y2 moves in its row and the generator keeps its own. VELOCITY_INDEX's 77.5 is printed in A7.12
    # alone. (These three cases read INFULL's 92.45 in A5.11 until U4 derived INFULL from A5.12, which made it a
    # computed value this check lists rather than compares.) ONTIME's 84.5 is NOT a case this check can prove:
    # A5.17's in-full drop line "<85" also publishes it (84.5 rounded half up is 85) -- a coincidence, named by the
    # review of 2026-09-25, not a second print of it.
    r, i = fresh()
    i["A7.12"] = dict(i["A7.12"], value=str(i["A7.12"]["value"]).replace("85 / 77.5 / 70", "85 / 78.5 / 70"))
    cases.append(("A7.12's y2 index 77.5 -> 78.5", check_generator_constants_published, (i,), gp))
    # ...and the same figure left standing only as history: published, but only in the past tense.
    r, i = fresh()
    i["A7.12"] = dict(i["A7.12"], value=str(i["A7.12"]["value"]).replace("85 / 77.5 / 70", "85 / 78.5 / 70"),
                      history="The index was 85 / 77.5 / 70 before.")
    cases.append(("A7.12's 77.5 left only as history", check_generator_constants_published, (i,),
                  "no generator constant is published only by a row's history"))

    # OPTION C (owner, 2026-09-28). Each rule is shown to fire on the case the old check passed. The synthetic modules
    # name A1.01, which prints none of 7.77, 8.88 or 93.24; a case that needs a print adds it to the row in memory.
    gn = "every typed generator constant names a row or states why it does not"

    def c_case(label, src, report_name=gp, add=None):
        _, i = fresh()
        if add:
            i["A1.01"] = dict(i["A1.01"], value=str(i["A1.01"]["value"]) + " " + add)
        cases.append((label, check_generator_constants_published, (i, {"synthetic": src}), report_name))
    # exact: A7.12's y2 index printed 78 no longer publishes 77.5 -- the half-up path did
    r, i = fresh()
    i["A7.12"] = dict(i["A7.12"], value=str(i["A7.12"]["value"]).replace("85 / 77.5 / 70", "85 / 78 / 70"))
    cases.append(("C: A7.12's 77.5 printed 78", check_generator_constants_published, (i,), gp))
    c_case("C: the second named row prints it, the first does not", "X = 7.77   # A1.01, A1.02\n")
    cases[-1][2][0]["A1.02"] = dict(cases[-1][2][0]["A1.02"],
                                    value=str(cases[-1][2][0]["A1.02"]["value"]) + " It is 7.77.")
    c_case("C: siblings printed at two scales", "Y = [0.25, 5.0]   # A1.01\n", add="It is 25 and 5 of them.")
    c_case("C: dict(...) of literals is a dict", "Z = dict(a=7.77)   # A1.01\n")
    c_case("C: a row named only on the divider", "# ---------------- A1.01, a section\nW = 7.77\n")
    c_case("C: an exemption scopes its leading list only",
           "E = [7.77, 8.88]   # A1.01 mirror-exempt: E[0], a pad; E[1] stays watched\n")
    c_case("C: a typed constant that names no row", "N = 7.77\n", gn)
    c_case("C: arithmetic whose result and literal go unprinted", "T = 7.77 * 12   # A1.01\n")
    c_case("C: an owed value the row now prints", "G = 7.77   # A1.01 mirror-owed: U4 -- a test debt\n",
           add="It is 7.77.")
    c_case("C: an owed value naming no closure unit", "H = 7.77   # A1.01 mirror-owed: U99 -- no such unit\n")
    c_case("C: an owed value is listed", "K = 7.77   # A1.01 mirror-owed: U4 -- a test debt\n",
           "generator constants owed to a closure unit: named, dated to the unit, not yet printed")
    # a locator reads the value AT its place: Kroger's 10 -> 11 swapped keeps both numbers in the row
    r, i = fresh()
    i["A7.26"] = dict(i["A7.26"], value=str(i["A7.26"]["value"]).replace("Kroger 10 -> 11 -> 11",
                                                                          "Kroger 11 -> 10 -> 11"))
    cases.append(("C: AUTH's Kroger swapped at its locator", check_generator_constants_published, (i,), gp))

    # The review of 2026-09-28 (44 confirmed findings): each defect it reproduced is a case here.
    c_case("C review: a note wrapped onto the next line names no row",
           "X = [7.77, 5.5]   # mirror-exempt: X[0], a pad; X[1] was once\n"
           "                  # carried in A1.01 as its 5.5\n", gn, add="It is 5.5.")
    c_case("C review: a note scoped to A is not B's", "A, B = [7.77], [8.88]   # A1.01 mirror-exempt: A[0], a pad\n")
    c_case("C review: arithmetic siblings share one scale", "Y = [0.5 / 2, 10 / 2]   # A1.01\n",
           add="It is 25 and 5 of them.")
    c_case("C review: a set literal is compared", "S = {7.77, 8.88}   # A1.01\n")
    c_case("C review: the typed literal, not a later rebind", "X = 7.77   # A1.01\nX = 5.5\n", add="It is 5.5.")
    c_case("C review: a repeat count is typed", "C = ['a'] * 97   # A1.01\n")
    c_case("C review: a printed 0 publishes only a 0", "Z = 0.0003   # A1.01\n", add="It is 0 of them.")
    c_case("C review: a note naming a path the constant lacks", "R = [5.5]   # A1.01 mirror-owed: R[3], U4 -- none\n",
           add="It is 5.5.")
    c_case("C review: a whole owed note the row partly prints", "X = [5.5, 7.77]   # A1.01 mirror-owed: U4 -- debt\n",
           add="It is 5.5.")
    c_case("C review: exempt as a whole and owed", "X = 7.77   # A1.01 mirror-exempt: a pad mirror-owed: U4 -- x\n")
    c_case("C review: a debt to a unit marked DONE", "X = 7.77   # A1.01 mirror-owed: U2 -- a done unit\n")
    c_case("C review: ROSTER's roles swapped", "ROSTER = {'y12': [('sales_mgr', 5), ('warehouse', 1)]}   # A9.04\n")
    cases[-1][2][1]["group9_ledger"] = cases[-1][2][1].pop("synthetic")
    # a flat count restated as a chain, and ROSTER's y2 warehouse count, each moved in the row alone
    r, i = fresh()
    i["A7.26"] = dict(i["A7.26"], value=str(i["A7.26"]["value"]).replace("Sprouts 12,", "Sprouts 12 -> 13 -> 14,"))
    cases.append(("C review: AUTH's flat Sprouts restated as a chain", check_generator_constants_published, (i,), gp))
    r, i = fresh()
    i["A9.04"] = dict(i["A9.04"], value=str(i["A9.04"]["value"]).replace("warehouse & shipping 5 / 5 / 6",
                                                                          "warehouse & shipping 5 / 9 / 6"))
    cases.append(("C review: ROSTER's y2 warehouse count moved", check_generator_constants_published, (i,), gp))

    def stale_locator():
        MIRROR_LOCATORS[("group9_ledger", "NO_SUCH_CONSTANT")] = (1.0, {}, {})
        try:
            check_generator_constants_published(fresh()[1])
        finally:
            MIRROR_LOCATORS.pop(("group9_ledger", "NO_SUCH_CONSTANT"))
    cases.append(("C review: a locator for a constant no generator binds", stale_locator, (), gp))
    cases.append(("C review: a locator phrase naming an anchor id", check_locator_hygiene,
                  ([("a figure", [1.0], ("A9.01",), 3, False, None)],
                   {("m", "X"): (1.0, {"[0]": (r"A1\.01 said", (0,), None)}, {})}),
                  "locators anchor on sentence content only"))
    # THE IDENTITY SITTING (owner, 2026-09-29). Each rule fires on the case option C passed.
    c_case("identity: a year-list printed with y2 apart from its endpoints", "Y = [7.77, 8.88, 9.99]   # A1.01\n",
           add="It runs 7.77 -> 9.99, and y2 is 8.88.")
    c_case("identity: arithmetic whose literals are not one run", "T = 7.77 * 12   # A1.01\n",
           add="It is 7.77 a month, 5 weeks, and 12 of them.")
    r, i = fresh()
    i["A9.01"] = dict(i["A9.01"], value=str(i["A9.01"]["value"]).replace("professional fees 0.5, travel 0.3",
                                                                          "professional fees 0.3, travel 0.5"))
    cases.append(("identity: GA_SPLIT's two lines swapped", check_generator_constants_published, (i,), gp))
    r, i = fresh()
    i["A7.14"] = dict(i["A7.14"], value=str(i["A7.14"]["value"]).replace("median 5 days, 25% >2 weeks",
                                                                          "median 5 days, 26% >2 weeks"))
    cases.append(("identity: a locator's own scale (A7.14's tail share)", check_generator_constants_published,
                  (i,), gp))
    r, i = fresh()
    i["A7.26"] = dict(i["A7.26"], value=str(i["A7.26"]["value"]).replace("Walmart 6 -> 7 -> 8",
                                                                          "Walmart 6 -> 7 -> 7"))
    cases.append(("identity: AUTH_ALL's Walmart onto the independents' run", check_generator_constants_published,
                  (i,), gp))
    _, i = fresh()
    i["A1.01"] = dict(i["A1.01"], value=str(i["A1.01"]["value"]) + " It is 2 and 3 of them.")
    cases.append(("identity: a one-unit drift the check accepts", check_constant_drift,
                  (i, {"synthetic": "X = 2   # A1.01\n"}), DRIFT_CHECK))

    unscoped = [c[0] for c in cases if c[1] is check_group11_figures and c[0] not in SCOPES]
    if unscoped:
        raise AssertionError("group-11 self-test cases with no scope, so any live finding would credit them: %s"
                             % ", ".join(unscoped))
    # The scope discriminates: A9.13's doctored FCCR is a live finding that credits its own case and no other.
    fccr = [c for c in cases if c[0] == "group 9 FCCR, row"][0]
    msgs = _isolated(fccr[1], fccr[2], fccr[3])
    for other, (pre, suf) in SCOPES.items():
        hit = [m for m in msgs if m.startswith(pre) and m.endswith(suf)]
        if bool(hit) != (other == fccr[0]):
            raise AssertionError("scope %r %s A9.13's FCCR finding" % (other, "is credited by" if hit else "misses"))
    # THE BASELINE (owner, 2026-10-02; U5): the live gate's own findings, under the gate's own exceptions. A case is
    # credited only with a message the live registry does not already produce, so a finding already on main can
    # never stand in for a case's edit. Per check name where the case names one; across all names where it does not.
    try:
        live_exceptions = yaml.safe_load(rd(EXCEPTIONS))
    except IOError:
        live_exceptions = {}
    saved, globals()["RESULTS"] = RESULTS, []
    try:
        _run_all(rows, index, enums, live_exceptions)
        live = [(rep[1], m) for rep in RESULTS for m in rep[2]]   # every level: the print rule's report is INFO
    finally:
        globals()["RESULTS"] = saved

    def unseen(found, expect):
        already = set(m for n, m in live if expect is None or n == expect)
        return [m for m in found if m not in already]
    # ...and the baseline subtracts: A9.13's doctored FCCR, made a live finding, no longer credits its own case
    live.extend((fccr[3], m) for m in msgs)
    if not msgs or unseen(msgs, fccr[3]) or unseen(msgs, None):
        raise AssertionError("the baseline does not subtract a live finding from the case that reproduces it")
    del live[len(live) - len(msgs):]
    silent = []
    for case in cases:
        name, fn, args = case[0], case[1], case[2]
        expect = case[3] if len(case) > 3 else None
        found = unseen(_isolated(fn, args, expect), expect)
        if name in SCOPES:
            found = [m for m in found if m.startswith(SCOPES[name][0]) and m.endswith(SCOPES[name][1])]
        print("   %-28s %s" % (name, "fires (%d)" % len(found) if found
                               else "SILENT -- this check cannot fail"))
        if not found:
            silent.append(name)
    # COVERAGE: a check added without a case would otherwise escape the proof
    # silently, which is how the group-10 cross-check shipped unproven. Compare
    # the names the cases exercise against the names the real gate reports.
    proven = set()
    for case in cases:
        saved, globals()["RESULTS"] = RESULTS, []
        try:
            case[1](*case[2])
            proven.update(rep[1] for rep in RESULTS if rep[0] in (BLOCK, WARN))
        except Exception:
            pass
        finally:
            globals()["RESULTS"] = saved
    saved, globals()["RESULTS"] = RESULTS, []
    try:
        _run_all(rows, index, enums, {})
        gated = set(rep[1] for rep in RESULTS if rep[0] in (BLOCK, WARN))
    finally:
        globals()["RESULTS"] = saved
    uncovered = sorted(gated - proven)

    print("")
    if uncovered:
        print("NO SELF-TEST CASE EXERCISES: %s" % ", ".join(uncovered))
    print("self-test: %d of %d cases fire; %d of %d gate checks covered"
          % (len(cases) - len(silent), len(cases), len(gated) - len(uncovered), len(gated)))
    return 1 if (silent or uncovered) else 0


# -------------------------------------------------------------------- the gate
def _run_all(rows, index, enums, exceptions):
    """Every check, in order. Shared by the gate and the self-test's coverage pass."""
    check_schema(rows, enums)
    check_denominator(rows, enums)
    check_depends_resolve(rows, index, enums)
    check_cycles(rows, index)
    check_tier_a(rows, enums)
    check_tier_a_non_vendor(rows)
    check_tier_a_verified(rows)
    check_pinned_records(index)
    check_set_records(index)
    check_first_order_flag(index)
    check_first_order_signed(index)
    check_tier_d(rows, enums)
    check_sourcing_slugs(rows)
    check_decision_refs(rows)
    check_line_endings()
    check_worklist_parity(index)
    check_depends_completeness(rows, index, exceptions)
    check_one_value_per_quantity(rows)
    check_retired_figures(rows)
    check_cross_row_credits(rows)
    check_history_reach(rows)
    check_generator_mirrors(index)
    check_generator_constants_published(index)
    check_constant_drift(index)
    check_generator_figures(index)
    check_survivability_flag(rows)
    check_no_shared_nodes(rows)
    check_signed_figures(rows, write=True)
    check_closed_forms()
    check_group10_figures(index)
    check_door_plan_minimum(index)
    check_equity_call(index)
    check_daily_dates(index)
    check_daily_flows()
    check_daily_before_note()
    check_daily_sawtooth()
    check_daily_part_held()
    check_ap_schedule()
    check_pnl_foots()
    check_packet_figures(index)
    check_small_channel()
    check_card_network_floors()
    check_slotting_outside_rates()
    check_group11_figures(index)
    check_locator_hygiene()
    check_catalogue_table(index)
    check_entry_outputs()      # last: it reads what every figure check above asked the generators for


def _tree_state():
    """(HEAD's commit, the porcelain status lines) -- the one place the gate asks git anything, for --export."""
    import subprocess
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode("utf-8").strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).decode("utf-8").splitlines()
    return head, dirty


def export(out_dir, rows, index, enums, exceptions):
    """`--export <dir>`: write <dir>/outputs.json, the four generators' outputs() the gate has just checked -- each one's
    `printed` beside its `series`, and group 11's `trial` -- from a clean tree at a gate-clean commit (U21; U15 runs
    it). Refused on a dirty tree, on a blocking finding, and on a tree the gate run itself dirtied. The JSON is the
    gate's own: floats by repr, Fractions as {"__fraction__": [numerator, denominator]}, dates as
    {"__date__": "YYYY-MM-DD"}."""
    import json
    head, dirty = _tree_state()
    if dirty:
        print("export refused -- the tree is not clean:\n   %s" % "\n   ".join(dirty))
        return 2
    _run_all(rows, index, enums, exceptions)
    blocking = sum(len(m) for level, _, m in RESULTS if level == BLOCK)
    if blocking:
        print("export refused -- the gate reports %d blocking findings at %s" % (blocking, head))
        return 2
    if _tree_state() != (head, []):
        print("export refused -- the gate run changed the tree at %s" % head)
        return 2
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    path = os.path.join(out_dir, "outputs.json")
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(dict(commit=head, generators=_outputs()), default=_encode, sort_keys=True))
    print("exported %s at %s, gate clean" % (path, head))
    return 0


def main():
    enums = yaml.safe_load(rd(ENUMS))
    rows = yaml.safe_load(rd(REGISTRY))
    index = dict((r["anchor_id"], r) for r in rows)
    if "--self-test" in sys.argv:
        print("self-test -- each check is shown to fail on a broken copy")
        return self_test(rows, index, enums)
    if "--export" in sys.argv:
        k = sys.argv.index("--export")
        if k + 1 >= len(sys.argv):
            print("--export needs a directory")
            return 2
        try:
            exceptions = yaml.safe_load(rd(EXCEPTIONS))
        except IOError:
            exceptions = {}
        return export(sys.argv[k + 1], rows, index, enums, exceptions)
    try:
        exceptions = yaml.safe_load(rd(EXCEPTIONS))
    except IOError:
        exceptions = {}

    _run_all(rows, index, enums, exceptions)

    print("registry gate -- %d rows in %s" % (len(rows), REGISTRY))
    blocking = 0
    for level, name, messages in RESULTS:
        if not messages:
            if "--all" in sys.argv:
                print("   ok    %s" % name)
            continue
        if level == BLOCK:
            blocking += len(messages)
        print("   %-5s %s (%d)" % (level.lower(), name, len(messages)))
        for m in messages[:20]:
            print("            %s" % m)
        if len(messages) > 20:
            print("            ... and %d more" % (len(messages) - 20))
    print("")
    print("CLEAN -- no blocking findings" if not blocking
          else "%d BLOCKING findings" % blocking)
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
