"""Audit installed core/dev distribution license metadata; no network or install."""

from __future__ import annotations

import json
import sys
from importlib.metadata import PackageNotFoundError, metadata
from pathlib import Path

from packaging.requirements import Requirement

ALLOWED = {"MIT", "Apache-2.0", "PSF-2.0", "BSD-2-Clause", "BSD-3-Clause", "BSD-2-Clause OR Apache-2.0", "Apache-2.0 OR BSD-2-Clause"}


def audit():
    pending = ["pydantic", "pytest", "ruff"]
    seen = set()
    rows = []
    failures = []
    while pending:
        name = pending.pop().lower().replace("_", "-")
        if name in seen:
            continue
        seen.add(name)
        try:
            info = metadata(name)
        except PackageNotFoundError:
            failures.append(f"missing distribution: {name}")
            continue
        expression = info.get("License-Expression") or info.get("License")
        rows.append({"name": name, "version": info["Version"], "license": expression})
        if expression not in ALLOWED:
            failures.append(f"unreviewed license metadata: {name}: {expression}")
        for raw in info.get_all("Requires-Dist") or []:
            requirement = Requirement(raw)
            if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
                pending.append(requirement.name)
    root = Path(__file__).resolve().parents[1]
    for path in [root / "LICENSE", root / "src/tradecase/vendor/ai_hunter/LICENSE"]:
        if not path.exists() or "Permission is hereby granted" not in path.read_text():
            failures.append(f"missing MIT license text: {path.relative_to(root)}")
    return {
        "scope": "installed core/dev metadata and bundled MIT notices; optional crawler stack not audited",
        "distributions": sorted(rows, key=lambda x: x["name"]),
        "failures": failures,
    }


if __name__ == "__main__":
    result = audit()
    print(json.dumps(result, indent=2))
    sys.exit(1 if result["failures"] else 0)
