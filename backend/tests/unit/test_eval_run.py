"""阶段四 TDD 红：eval/run.py CLI（参数解析/报告结构/--check 退出码/skip 不计失败）."""

import json
from pathlib import Path

import pytest

from eval import run, tasks
from eval.tasks import EvalResult


def _ok_result(task: str, metrics: dict[str, float]) -> EvalResult:
    return EvalResult(task=task, status="ok", metrics=metrics, details=[{"id": "d1"}])


def _patch_all_tasks(monkeypatch, results: dict[str, EvalResult]):
    """按任务名替换 from_dir 入口（run.py 经 tasks 模块属性访问，可 patch）."""
    for name in ("extraction", "coverage", "retrieval"):
        result = results.get(name)
        if result is None:
            continue

        async def _fake(_dataset_dir, _result=result, **kwargs):
            return _result

        monkeypatch.setattr(tasks, f"run_{name}_from_dir", _fake)


# ── 参数解析 ──


class TestParseArgs:
    def test_defaults(self):
        args = run.parse_args([])
        assert args.task == "all"
        assert args.dataset is None
        assert args.json is None
        assert args.check is False

    def test_explicit(self, tmp_path):
        args = run.parse_args(
            ["--task", "coverage", "--dataset", str(tmp_path), "--json", "r.json", "--check"]
        )
        assert args.task == "coverage"
        assert args.dataset == str(tmp_path)
        assert args.json == "r.json"
        assert args.check is True

    def test_invalid_task_exits(self):
        with pytest.raises(SystemExit):
            run.parse_args(["--task", "nonsense"])


# ── 报告结构与达标判定 ──


class TestReport:
    def test_build_report_with_verdict(self):
        report = run.build_report([_ok_result("extraction", {"f1": 0.9})])
        entry = report["tasks"]["extraction"]
        assert entry["status"] == "ok"
        assert entry["metrics"] == {"f1": 0.9}
        assert entry["verdict"] == {"f1": True}

    def test_skipped_task_has_empty_verdict(self):
        result = EvalResult(task="retrieval", status="skipped", note="无 Key")
        report = run.build_report([result])
        entry = report["tasks"]["retrieval"]
        assert entry["status"] == "skipped"
        assert entry["verdict"] == {}

    def test_all_pass(self):
        report = run.build_report(
            [
                _ok_result("extraction", {"f1": 0.9}),
                _ok_result("coverage", {"coverage_rate": 1.0}),
            ]
        )
        assert run.report_passed(report) is True

    def test_any_metric_fail(self):
        report = run.build_report([_ok_result("coverage", {"coverage_rate": 0.5})])
        assert run.report_passed(report) is False

    def test_skipped_not_counted_as_failure(self):
        report = run.build_report(
            [
                _ok_result("coverage", {"coverage_rate": 1.0}),
                EvalResult(task="extraction", status="skipped", note="LLM 未配置"),
            ]
        )
        assert run.report_passed(report) is True


# ── 控制台输出 ──


class TestRender:
    def test_render_contains_task_and_metrics(self):
        report = run.build_report(
            [
                _ok_result("extraction", {"f1": 0.9}),
                EvalResult(task="retrieval", status="skipped", note="Embedding 未配置"),
            ]
        )
        text = run.render_console(report)
        assert "extraction" in text
        assert "0.9000" in text
        assert "skipped" in text
        assert "Embedding 未配置" in text


# ── main 集成（mock 全部任务） ──


class TestMain:
    async def test_check_exit_nonzero_on_fail(self, monkeypatch, capsys):
        _patch_all_tasks(
            monkeypatch,
            {
                "extraction": _ok_result("extraction", {"f1": 0.5}),
                "coverage": _ok_result("coverage", {"coverage_rate": 1.0}),
                "retrieval": EvalResult(task="retrieval", status="skipped", note="无 Key"),
            },
        )
        code = await run.execute(run.parse_args(["--task", "all", "--check"]))
        assert code == 1

    async def test_check_exit_zero_when_pass_and_skipped(self, monkeypatch, capsys):
        _patch_all_tasks(
            monkeypatch,
            {
                "extraction": _ok_result("extraction", {"f1": 0.9}),
                "coverage": _ok_result("coverage", {"coverage_rate": 1.0}),
                "retrieval": EvalResult(task="retrieval", status="skipped", note="无 Key"),
            },
        )
        code = await run.execute(run.parse_args(["--check"]))
        assert code == 0

    async def test_single_task_selection(self, monkeypatch, capsys):
        executed: list[str] = []

        async def _fake_coverage(dataset_dir):
            executed.append("coverage")
            return _ok_result("coverage", {"coverage_rate": 1.0})

        async def _fail_other(dataset_dir):
            raise AssertionError("不应执行其他任务")

        monkeypatch.setattr(tasks, "run_coverage_from_dir", _fake_coverage)
        monkeypatch.setattr(tasks, "run_extraction_from_dir", _fail_other)
        monkeypatch.setattr(tasks, "run_retrieval_from_dir", _fail_other)
        code = await run.execute(run.parse_args(["--task", "coverage"]))
        assert code == 0
        assert executed == ["coverage"]

    async def test_json_report_written(self, monkeypatch, tmp_path):
        _patch_all_tasks(monkeypatch, {"coverage": _ok_result("coverage", {"coverage_rate": 1.0})})
        out = tmp_path / "report.json"
        code = await run.execute(run.parse_args(["--task", "coverage", "--json", str(out)]))
        assert code == 0
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["tasks"]["coverage"]["metrics"] == {"coverage_rate": 1.0}
        assert data["passed"] is True

    async def test_dataset_dir_passed_through(self, monkeypatch, tmp_path):
        seen: list[Path] = []

        async def _fake(dataset_dir):
            seen.append(Path(dataset_dir))
            return _ok_result("coverage", {"coverage_rate": 1.0})

        monkeypatch.setattr(tasks, "run_coverage_from_dir", _fake)
        custom = tmp_path / "custom"
        custom.mkdir()
        await run.execute(run.parse_args(["--task", "coverage", "--dataset", str(custom)]))
        assert seen == [custom]
