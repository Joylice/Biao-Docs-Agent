"""Arq worker 启动器（Windows 兼容）.

psycopg 异步驱动无法在 Windows 默认的 ProactorEventLoop 上运行，
启动前切换到 SelectorEventLoop（仅 Windows 生效，Linux/macOS 无影响）。

用法：python -m worker.run_worker worker.WorkerSettings
"""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from arq.cli import cli

if __name__ == "__main__":
    cli()
