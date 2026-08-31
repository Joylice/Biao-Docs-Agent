"""Worker 模块."""

from worker.settings import WorkerSettings
from worker.tasks import task_index_document, task_parse_tender

WorkerSettings.functions = [task_parse_tender, task_index_document]

__all__ = ["WorkerSettings", "task_index_document", "task_parse_tender"]
