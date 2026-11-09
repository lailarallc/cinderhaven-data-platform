"""Resolve a file in another repository as repo, pinned commit and path (U3).

The harness runs external files unchanged (spec:03 runs price-point-architecture's
analysis/readiness_gate.py). It locates the checkout, verifies the checkout is at
the pinned commit and the file's SHA-256, and returns the path. Absent, at another
commit, or with another hash, it fails loudly. U7 writes the pin.
"""
from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path


class ExternalRefError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExternalRef:
    repo: Path
    commit: str
    path: str
    sha256: str


def resolve(ref: ExternalRef) -> Path:
    if not (ref.repo / ".git").exists():
        raise ExternalRefError(f"no checkout at {ref.repo}")
    head = subprocess.run(["git", "-C", str(ref.repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    if head != ref.commit:
        raise ExternalRefError(f"{ref.repo} is at {head or 'no commit'}, pinned {ref.commit}")
    dirty = subprocess.run(["git", "-C", str(ref.repo), "status", "--porcelain", "--", ref.path],
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        raise ExternalRefError(f"{ref.path} has local changes in {ref.repo}")
    f = ref.repo / ref.path
    if not f.is_file():
        raise ExternalRefError(f"{ref.path} not found in {ref.repo}")
    got = hashlib.sha256(f.read_bytes()).hexdigest()
    if got != ref.sha256:
        raise ExternalRefError(f"{ref.path} sha256 {got}, pinned {ref.sha256}")
    return f
