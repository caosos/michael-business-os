"""C-09: owner-decision support for MICHAEL_DECISIONS #1 (cash at risk) and #2 ($/h floor and targets).

REPORT ONLY. Every scenario is an in-memory copy of the scoring config with one value changed; nothing
is written. ``sensitivity_report`` returns plain data; ``render_markdown`` turns it into the docs table.

Two views:
* one-at-a-time sweeps: the verdict of every case at each candidate value (others at default);
* break-even points: per case, the most permissive / restrictive value at which its verdict flips,
  found by a deterministic integer scan.
"""

from __future__ import annotations

import copy
from decimal import Decimal

from .canonical import content_hash
from .config import ScoringConfig
from .engine import compute
from .inputs import build_engine_input

PARAMS = {
    "cash_cap": ("capital_and_risk.risk_capital_per_deal_cap", "#1 max cash per deal", [1000, 1500, 2000, 2500, 3000], (500, 5000, 50)),
    "max_loss": ("capital_and_risk.max_loss_cap", "#1 max loss per deal", [600, 800, 1000, 1200], (200, 2000, 25)),
    "floor": ("time_value.w_min_per_hour", "#2 absolute $/h floor", [30, 35, 40, 45, 50], (10, 100, 1)),
    "flip_target": ("time_value.w_target_flip_per_hour", "#2 flip $/h target", [55, 60, 65, 70, 75], (20, 150, 1)),
    "service_target": ("time_value.w_target_service_per_hour", "#2 service $/h target", [65, 70, 75, 80, 85], (20, 150, 1)),
}
_RANK = {"PASS": 0, "MAYBE": 1, "YES": 2}


def variant(cfg: ScoringConfig, path: str, value) -> ScoringConfig:
    raw = copy.deepcopy(cfg.raw)
    node = raw
    parts = path.split(".")
    for p in parts[:-1]:
        node = node[p]
    node[parts[-1]]["value"] = Decimal(str(value))
    label = f"{cfg.version}+{path}={value}"
    return ScoringConfig(version=label, raw=raw, hash=content_hash(raw))


def _verdict(item: dict, cfg: ScoringConfig) -> str:
    return compute(build_engine_input(item), cfg)["decision"]


def _break_even(item: dict, cfg: ScoringConfig, path: str, scan: tuple[int, int, int], base: str) -> dict | None:
    """Scan the parameter; report the value range over which the verdict differs from the default."""
    lo, hi, step = scan
    seen: dict[str, list[int]] = {}
    for v in range(lo, hi + 1, step):
        seen.setdefault(_verdict(item, variant(cfg, path, v)), []).append(v)
    if set(seen) == {base}:
        return None
    return {k: [min(v), max(v)] for k, v in sorted(seen.items(), key=lambda kv: _RANK[kv[0]])}


def sensitivity_report(cases: dict[str, dict], cfg: ScoringConfig, *, params: dict | None = None) -> dict:
    """``cases``: name -> scored-or-scorable Item. Returns default verdicts, sweeps and break-evens.
    ``params`` overrides PARAMS (tests use narrow scans; the full scan takes ~40 s)."""
    names = sorted(cases)
    default = {n: _verdict(cases[n], cfg) for n in names}
    sweeps, counts, breaks = {}, {}, {}
    for key, (path, label, values, scan) in (params or PARAMS).items():
        grid = {v: {n: _verdict(cases[n], variant(cfg, path, v)) for n in names} for v in values}
        sweeps[key] = {"path": path, "label": label, "default": cfg.get(path), "values": values, "verdicts": grid}
        counts[key] = {v: {d: sum(1 for x in grid[v].values() if x == d) for d in ("YES", "MAYBE", "PASS")} for v in values}
        breaks[key] = {n: b for n in names if (b := _break_even(cases[n], cfg, path, scan, default[n])) is not None}
    return {"config_version": cfg.version, "config_hash": cfg.hash, "cases": names, "default": default,
            "sweeps": sweeps, "counts": counts, "break_even": breaks}


def render_markdown(rep: dict, *, title_note: str = "") -> str:
    out = []
    for key, sw in rep["sweeps"].items():
        vals = sw["values"]
        out.append(f"### {sw['label']} (`{sw['path']}`, default {sw['default']})\n")
        out.append("| Case | " + " | ".join(f"{v}{' (default)' if Decimal(str(v)) == sw['default'] else ''}" for v in vals) + " |")
        out.append("|---|" + "---|" * len(vals))
        for n in rep["cases"]:
            cells = []
            for v in vals:
                d = sw["verdicts"][v][n]
                cells.append(f"**{d}**" if d != rep["default"][n] else d)
            out.append(f"| {n} | " + " | ".join(cells) + " |")
        c = rep["counts"][key]
        out.append("| **YES / MAYBE / PASS** | " + " | ".join(f"{c[v]['YES']} / {c[v]['MAYBE']} / {c[v]['PASS']}" for v in vals) + " |")
        be = rep["break_even"][key]
        if be:
            out.append("\nBreak-even ranges (integer scan; verdict: [lowest, highest] value giving it):\n")
            for n, ranges in be.items():
                out.append(f"- `{n}`: " + "; ".join(f"{d} for {r[0]}–{r[1]}" for d, r in ranges.items()))
        else:
            out.append("\nNo case changes verdict anywhere in the scanned range.")
        out.append("")
    return "\n".join(out)
