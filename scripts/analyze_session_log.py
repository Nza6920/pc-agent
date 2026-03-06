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


def fmt(v: float) -> str:
    return f"{v:.3f}s"


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


def select_rows(rows: list[dict[str, Any]], session_id: str | None, latest_session: bool) -> tuple[list[dict[str, Any]], str | None, int]:
    if session_id and latest_session:
        print("[ERROR] --session-id and --latest-session cannot be used together.")
        return [], None, 3

    selected_session_id = session_id
    if latest_session:
        for row in reversed(rows):
            sid = row.get("session_id")
            if isinstance(sid, str) and sid:
                selected_session_id = sid
                break
        if not selected_session_id:
            print("[ERROR] no session_id found in log.")
            return [], None, 4

    if selected_session_id:
        filtered = [r for r in rows if r.get("session_id") == selected_session_id]
        if not filtered:
            print(f"[ERROR] session_id not found in log: {selected_session_id}")
            return [], selected_session_id, 5
        return filtered, selected_session_id, 0

    return rows, selected_session_id, 0


def build_action_by_step(rows: list[dict[str, Any]]) -> dict[int, str]:
    action_by_step: dict[int, str] = {}
    for row in rows:
        step = row.get("step")
        action = row.get("action_type")
        if not isinstance(step, int) or not isinstance(action, str):
            continue
        action_by_step[step] = action
    return action_by_step


def analyze(log_path: Path, session_id: str | None = None, latest_session: bool = False) -> int:
    if not log_path.exists():
        print(f"[ERROR] log file not found: {log_path}")
        return 1

    rows = load_rows(log_path)
    rows, selected_session_id, code = select_rows(rows, session_id, latest_session)
    if code != 0:
        return code

    step_rows = [r for r in rows if r.get("type") == "step_timing"]
    decision_rows = [
        r
        for r in rows
        if isinstance(r.get("step"), int) and isinstance(r.get("action_type"), str) and r.get("type") != "step_timing"
    ]
    status_rows = [
        r
        for r in rows
        if r.get("status") in {"blocked", "stopped"} and isinstance(r.get("step"), int)
    ]
    summary_rows = [r for r in rows if r.get("type") == "summary"]
    startup_rows = [r for r in rows if r.get("type") == "startup"]

    if not step_rows:
        print("[ERROR] no step_timing records found.")
        return 2

    action_by_step = build_action_by_step(decision_rows + status_rows)
    phase_by_step: dict[int, str] = {}
    status_by_step: dict[int, str] = {}
    thought_by_step: dict[int, str] = {}
    for row in decision_rows + status_rows:
        step = row.get("step")
        if not isinstance(step, int):
            continue
        if isinstance(row.get("phase"), str):
            phase_by_step[step] = str(row["phase"])
        if isinstance(row.get("status"), str):
            status_by_step[step] = str(row["status"])
        if isinstance(row.get("thought"), str):
            thought_by_step[step] = str(row["thought"])

    for row in step_rows:
        step = row.get("step")
        if isinstance(step, int):
            row["action_type"] = action_by_step.get(step, "unknown")
            row["phase"] = phase_by_step.get(step, "unknown")
            row["status"] = status_by_step.get(step, row.get("end_state", "unknown"))
            row["thought"] = thought_by_step.get(step, "")

    print(f"Log: {log_path}")
    if selected_session_id:
        print(f"Session: {selected_session_id}")
    if startup_rows:
        startup = startup_rows[0]
        print(f"Resolution: {startup.get('resolution_width', '?')}x{startup.get('resolution_height', '?')}")
    print(f"Timed steps: {len(step_rows)}")

    if summary_rows:
        summary = summary_rows[-1]
        status_code = summary.get("status_code")
        total = summary.get("total_elapsed_sec")
        if status_code is not None:
            print(f"Exit code: {status_code}")
        if isinstance(total, (int, float)):
            print(f"Total elapsed: {fmt(float(total))}")

    final_status = "unknown"
    final_reason = ""
    if status_rows:
        last_status = status_rows[-1]
        final_status = str(last_status.get("status", "unknown"))
        final_reason = str(last_status.get("reason", "")).strip()
    elif summary_rows:
        code_map = {0: "completed", 2: "blocked", 3: "stopped", 4: "stopped"}
        final_status = code_map.get(int(summary_rows[-1].get("status_code", -1)), "unknown")
    print(f"Final status: {final_status}")
    if final_reason:
        print(f"Final reason: {final_reason}")
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
            f"step={r.get('step'):>3} phase={str(r.get('phase')):<8} status={str(r.get('status')):<12} "
            f"action={str(r.get('action_type')):<12} elapsed={fmt(float(r.get('elapsed_sec', 0.0)))} "
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
    print()

    print("== Step Outcomes ==")
    outcome_groups: dict[str, int] = {}
    end_state_groups: dict[str, int] = {}
    for row in step_rows:
        status = str(row.get("status", "unknown"))
        outcome_groups[status] = outcome_groups.get(status, 0) + 1
        end_state = str(row.get("end_state", "unknown"))
        end_state_groups[end_state] = end_state_groups.get(end_state, 0) + 1
    print("Status counts:")
    for status, count in sorted(outcome_groups.items()):
        print(f"  {status}: {count}")
    print("End-state counts:")
    for end_state, count in sorted(end_state_groups.items()):
        print(f"  {end_state}: {count}")
    print()

    if status_rows:
        print("== Terminal Records ==")
        for row in status_rows:
            step = row.get("step")
            status = row.get("status")
            reason = row.get("reason", "")
            action = row.get("action_type", "")
            print(f"step={step} status={status} action={action} reason={reason}")
        print()

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze desktop-agent session log timings.")
    parser.add_argument("--log", default="runs/session.log", help="Path to session log file")
    parser.add_argument("--session-id", default=None, help="Analyze only one session_id")
    parser.add_argument("--latest-session", action="store_true", help="Analyze the latest session_id in log")
    args = parser.parse_args()
    return analyze(Path(args.log), session_id=args.session_id, latest_session=args.latest_session)


if __name__ == "__main__":
    raise SystemExit(main())
