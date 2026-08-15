"""Worker 模块."""

from worker.settings import WorkerSettings
from worker.tasks import task_generate_chapters, task_index_document, task_parse_tender

WorkerSettings.functions = [task_parse_tender, task_index_document, task_generate_chapters]

__all__ = ["WorkerSettings", "task_generate_chapters", "task_index_document", "task_parse_tender"]
