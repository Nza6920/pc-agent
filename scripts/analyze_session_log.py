from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any


COMPONENTS = ["capture_sec", "encode_sec", "llm_sec", "action_sec", "sleep_sec", "elapsed_sec"]


def percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    idx = int((len(sorted_values) - 1) * p)
    return sorted_values[idx]


def load_rows(log_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def fmt(v: float) -> str:
    return f"{v:.3f}s"


def analyze(log_path: Path) -> int:
    if not log_path.exists():
        print(f"[ERROR] log file not found: {log_path}")
        return 1

    rows = load_rows(log_path)
    step_rows = [r for r in rows if r.get("type") == "step_timing"]
    action_rows = [r for r in rows if "step" in r and "action_type" in r]
    summary_rows = [r for r in rows if r.get("type") == "summary"]

    if not step_rows:
        print("[ERROR] no step_timing records found.")
        return 2

    action_by_step: dict[int, str] = {}
    for row in action_rows:
        step = row.get("step")
        action = row.get("action_type")
        if isinstance(step, int) and isinstance(action, str):
            action_by_step[step] = action

    for row in step_rows:
        step = row.get("step")
        row["action_type"] = action_by_step.get(step, "unknown")

    print(f"Log: {log_path}")
    print(f"Steps: {len(step_rows)}")
    if summary_rows:
        total = summary_rows[-1].get("total_elapsed_sec")
        if isinstance(total, (int, float)):
            print(f"Total elapsed: {fmt(float(total))}")
    print()

    print("== Component Stats ==")
    comp_totals: dict[str, float] = {}
    for comp in COMPONENTS:
        vals = [float(r.get(comp, 0.0)) for r in step_rows if isinstance(r.get(comp, 0.0), (int, float))]
        vals_sorted = sorted(vals)
        total = sum(vals)
        comp_totals[comp] = total
        print(
            f"{comp:>10}: count={len(vals):>3} avg={fmt(mean(vals) if vals else 0.0)} "
            f"p50={fmt(percentile(vals_sorted, 0.5))} p90={fmt(percentile(vals_sorted, 0.9))} max={fmt(max(vals) if vals else 0.0)}"
        )
    elapsed_total = comp_totals.get("elapsed_sec", 0.0) or 1.0
    print()
    print("== Component Share (by summed time) ==")
    for comp in ["capture_sec", "encode_sec", "llm_sec", "action_sec", "sleep_sec"]:
        share = (comp_totals.get(comp, 0.0) / elapsed_total) * 100.0
        print(f"{comp:>10}: {share:6.2f}%")
    print()

    print("== Slowest Steps (Top 10 by elapsed_sec) ==")
    top_steps = sorted(step_rows, key=lambda r: float(r.get("elapsed_sec", 0.0)), reverse=True)[:10]
    for r in top_steps:
        print(
            f"step={r.get('step'):>3} action={str(r.get('action_type')):<12} "
            f"elapsed={fmt(float(r.get('elapsed_sec', 0.0)))} "
            f"llm={fmt(float(r.get('llm_sec', 0.0)))} capture={fmt(float(r.get('capture_sec', 0.0)))}"
        )
    print()

    print("== By Action Type ==")
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in step_rows:
        action = str(row.get("action_type", "unknown"))
        groups.setdefault(action, []).append(row)
    for action, items in sorted(groups.items(), key=lambda kv: mean(float(i.get("elapsed_sec", 0.0)) for i in kv[1]), reverse=True):
        vals = [float(i.get("elapsed_sec", 0.0)) for i in items]
        print(f"{action:>12}: count={len(vals):>3} avg={fmt(mean(vals))} max={fmt(max(vals))}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze desktop-agent session log timings.")
    parser.add_argument("--log", default="runs/session.log", help="Path to session log file")
    args = parser.parse_args()
    return analyze(Path(args.log))


if __name__ == "__main__":
    raise SystemExit(main())
