"""Worker 模块.

⚠️ 任务注册的**唯一来源**是 `worker/settings.py` 的 `WorkerSettings.functions`。

本模块只做 re-export，**禁止**再对 `functions` 赋值：arq 的启动入口是
`arq worker.WorkerSettings`（见 `deploy/*.yml`、`_start_dev.ps1`），导入 `worker` 包
必然先执行本文件，此处任何 `functions` 赋值都会覆盖 `settings.py` 的注册列表。

2026-09-17 修复的真实缺陷：本文件曾写 `WorkerSettings.functions = [2 个任务]`，
使 `task_reindex_all` 从未被 worker 注册 —— 管理端「全量重建索引」入队成功，
worker 却因找不到函数而丢弃，用户侧表现为点了没反应。
"""

from worker.settings import WorkerSettings
from worker.tasks import task_index_document, task_parse_tender, task_reindex_all

__all__ = [
    "WorkerSettings",
    "task_index_document",
    "task_parse_tender",
    "task_reindex_all",
]
