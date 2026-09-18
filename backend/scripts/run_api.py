"""FastAPI 开发启动器（Windows 兼容）.

psycopg3 异步驱动无法在 Windows 默认的 ProactorEventLoop 上运行。
uvicorn CLI（>=0.30）的 Server.run() 内部自行调用 asyncio.run 并指定
loop_factory，会覆盖模块级的 set_event_loop_policy——因此必须用
asyncio.run(..., loop_factory=SelectorEventLoop) 程序化驱动 uvicorn.Server。

用法：
    python -m scripts.run_api                 # 默认 0.0.0.0:8000
    python -m scripts.run_api --port 8001     # 指定端口
"""

from __future__ import annotations

import argparse
import asyncio
import selectors
import sys

import uvicorn


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="启动 bid-agent API 服务")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--log-level", default="info")
    return parser


async def _serve(host: str, port: int, log_level: str) -> None:
    config = uvicorn.Config(
        "app.main:app",
        host=host,
        port=port,
        log_level=log_level,
        loop="asyncio",
    )
    server = uvicorn.Server(config)
    await server.serve()


def main() -> None:
    args = _build_parser().parse_args()

    if sys.platform == "win32":
        # 当前线程内驱动 uvicorn，事件循环由本文件的 loop_factory 决定。
        asyncio.run(
            _serve(args.host, args.port, args.log_level),
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
    else:
        asyncio.run(_serve(args.host, args.port, args.log_level))


if __name__ == "__main__":
    main()
