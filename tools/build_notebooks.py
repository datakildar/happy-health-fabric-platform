"""Build notebooks/*.ipynb from the py-percent sources in tools/nb_sources/.

Cells start with '# %%' (code) or '# %% [markdown]'; '# %% tags=["parameters"]' marks the parameters cell
that a Fabric pipeline Notebook activity overrides. Keeping sources as .py files makes code review and diffs readable.

Usage: python tools/build_notebooks.py [--check]   (--check compiles every code cell)
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC, OUT = ROOT / "tools" / "nb_sources", ROOT / "notebooks"


def cells_from(text: str):
    cells, cur, kind, tags = [], [], None, []
    for line in text.splitlines():
        m = re.match(r"^# %%(.*)$", line)
        if m:
            if kind:
                cells.append((kind, tags, cur))
            rest = m.group(1).strip()
            kind = "markdown" if rest.startswith("[markdown]") else "code"
            tags = ["parameters"] if "parameters" in rest else []
            cur = []
            continue
        if kind == "markdown":
            cur.append(re.sub(r"^# ?", "", line))
        elif kind == "code":
            cur.append(line)
    if kind:
        cells.append((kind, tags, cur))
    out = []
    for kind, tags, lines in cells:
        while lines and not lines[-1].strip():
            lines.pop()
        while lines and not lines[0].strip():
            lines.pop(0)
        src = [l + "\n" for l in lines]
        if src:
            src[-1] = src[-1].rstrip("\n")
        cell = {"cell_type": kind, "metadata": {"tags": tags} if tags else {}, "source": src}
        if kind == "code":
            cell.update(execution_count=None, outputs=[])
        out.append(cell)
    return out


def build(check: bool = False):
    OUT.mkdir(exist_ok=True)
    for src in sorted(SRC.glob("*.py")):
        cells = cells_from(src.read_text())
        if check:
            for i, c in enumerate(cells):
                if c["cell_type"] == "code":
                    code = "".join(c["source"])
                    compile(code, f"{src.name}[cell {i}]", "exec")
        nb = {"cells": cells, "metadata": {
                  "kernelspec": {"display_name": "Synapse PySpark" if "spark" in src.read_text() else "Python 3",
                                 "language": "python", "name": "synapse_pyspark" if "spark" in src.read_text() else "python3"},
                  "language_info": {"name": "python"},
                  "microsoft": {"language": "python"}},
              "nbformat": 4, "nbformat_minor": 5}
        (OUT / f"{src.stem}.ipynb").write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n")
        print(f"{src.stem}.ipynb: {len(cells)} cells")


if __name__ == "__main__":
    build(check="--check" in sys.argv)
