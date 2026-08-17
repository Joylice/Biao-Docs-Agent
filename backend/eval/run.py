"""评测 CLI 入口.

用法：python -m eval.run --task all|extraction|coverage|retrieval
      [--dataset DIR] [--json PATH] [--check]

阈值对齐 SDD §10.2 验收标准：extraction F1 ≥ 0.85、coverage_rate ≥ 0.90；
检索 Recall@8 ≥ 0.80 为框架保守设定（SDD 仅要求「Top-8 有效」，无量化口径）。
--check：存在未达标指标时退出码非零；skipped 任务不计为失败。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from eval import tasks
from eval.metrics import evaluate_thresholds
from eval.tasks import EvalResult

DEFAULT_DATASETS_DIR = Path(__file__).parent / "datasets"
TASK_ORDER = ["extraction", "coverage", "retrieval"]
DEFAULT_THRESHOLDS: dict[str, dict[str, float]] = {
    "extraction": {"f1": 0.85},
    "coverage": {"coverage_rate": 0.90},
    "retrieval": {"recall_at_8": 0.80},
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="eval.run", description="投标方案智能体离线评测")
    parser.add_argument(
        "--task",
        choices=[*TASK_ORDER, "all"],
        default="all",
        help="评测任务（默认 all）",
    )
    parser.add_argument("--dataset", default=None, help="数据集目录（显式指定时直接传给所选任务）")
    parser.add_argument("--json", default=None, help="JSON 报告落盘路径")
    parser.add_argument("--check", action="store_true", help="未达标时退出码非零")
    return parser.parse_args(argv)


def build_report(results: list[EvalResult]) -> dict:
    """汇总各任务结果为报告结构（含阈值判定）."""
    entries: dict[str, dict] = {}
    for r in results:
        thresholds = DEFAULT_THRESHOLDS.get(r.task, {})
        verdict = evaluate_thresholds(r.metrics, thresholds) if r.status == "ok" else {}
        entries[r.task] = {
            "status": r.status,
            "metrics": r.metrics,
            "thresholds": thresholds,
            "verdict": verdict,
            "details": r.details,
            "note": r.note,
        }
    passed = all(not e["verdict"] or all(e["verdict"].values()) for e in entries.values())
    return {"tasks": entries, "passed": passed}


def report_passed(report: dict) -> bool:
    return report["passed"]


def render_console(report: dict) -> str:
    """控制台报告文本（任务/状态/指标/阈值/结果）."""
    lines = ["评测报告", "-" * 60]
    for name, entry in report["tasks"].items():
        if entry["status"] == "skipped":
            lines.append(f"{name:<12} skipped  {entry['note']}")
            continue
        lines.append(f"{name:<12} ok")
        for metric, value in entry["metrics"].items():
            bar = entry["thresholds"].get(metric)
            verdict = entry["verdict"].get(metric)
            bar_text = f">={bar}" if bar is not None else "-"
            verdict_text = {True: "PASS", False: "FAIL"}.get(verdict, "-")
            lines.append(f"  - {metric}={value:.4f}  阈值{bar_text}  {verdict_text}")
        if entry["note"]:
            lines.append(f"  备注: {entry['note']}")
    lines.append("-" * 60)
    lines.append(f"总体结论: {'PASS' if report['passed'] else 'FAIL'}")
    return "\n".join(lines)


async def execute(args: argparse.Namespace) -> int:
    selected = TASK_ORDER if args.task == "all" else [args.task]
    results: list[EvalResult] = []
    for name in selected:
        dataset_dir = Path(args.dataset) if args.dataset else DEFAULT_DATASETS_DIR / name
        runner = getattr(tasks, f"run_{name}_from_dir")
        results.append(await runner(dataset_dir))

    report = build_report(results)
    print(render_console(report))
    if args.json:
        Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if args.check and not report["passed"]:
        return 1
    return 0


def main() -> None:
    sys.exit(asyncio.run(execute(parse_args())))


if __name__ == "__main__":
    main()
