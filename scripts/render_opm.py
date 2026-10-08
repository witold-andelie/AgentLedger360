"""Render the OPM model: the full map plus one SVG per OPD, all from docs/opm/agentledger_opm.dot.

    python scripts/render_opm.py            (needs Graphviz `dot` on PATH)

Each per-OPD view = graph header + that cluster (+ legend + rules), so the .dot stays the single source.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

OPM_DIR = Path(__file__).resolve().parents[1] / "docs" / "opm"
SOURCE = OPM_DIR / "agentledger_opm.dot"
VIEWS = {"SD": "cluster_SD", "SD1": "cluster_SD1", "SD2": "cluster_SD2", "SD3": "cluster_SD3", "SD4": "cluster_SD4",
         "SD5": "cluster_SD5"}
ALWAYS = ("cluster_legend", "cluster_rules")


def extract_block(text: str, cluster: str) -> str:
    match = re.search(rf"^\s*subgraph {cluster} \{{", text, flags=re.MULTILINE)
    if match is None:
        raise SystemExit(f"{cluster} not found in {SOURCE.name}")
    depth, i = 0, match.start()
    while i < len(text):
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
        if depth == 0 and text[i - 1] == "}":
            return text[match.start():i]
    raise SystemExit(f"unbalanced braces in {cluster}")


def header(text: str) -> str:
    """Everything before the first cluster: graph/node/edge defaults."""
    return text[: re.search(r"^\s*subgraph cluster_", text, flags=re.MULTILINE).start()]


def render(dot_text: str, out: Path) -> None:
    subprocess.run(["dot", "-Tsvg", "-o", str(out)], input=dot_text.encode("utf-8"), check=True)
    print(f"wrote {out.relative_to(OPM_DIR.parents[1])}")


def main() -> int:
    if shutil.which("dot") is None:
        print("Graphviz `dot` not found on PATH", file=sys.stderr)
        return 1
    text = SOURCE.read_text(encoding="utf-8")
    render(text, OPM_DIR / "agentledger_opm.svg")
    head = header(text)
    extras = "\n".join(extract_block(text, c) for c in ALWAYS)
    for name, cluster in VIEWS.items():
        render(f"{head}\n{extract_block(text, cluster)}\n{extras}\n}}\n", OPM_DIR / f"opm_{name}.svg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
