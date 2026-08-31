#!/usr/bin/env python3
"""1Panel API 客户端 — 测试环境远端部署工具（2026-08-31 实测协议固化）。

认证方式（按优先级）：
  1. API Key 模式（推荐，全自动免验证码）：
     - 1Panel → 设置 → 安全 → API 接口：开启 + 生成 API Key + 配置 IP 白名单
     - 请求头：1Panel-Timestamp=<unix秒>, 1Panel-Token=md5("1panel"+key+ts)
  2. Session 模式（备选）：.env.remote 的 PANEL_COOKIES 传
     "psession=xxx; SecurityEntrance=dGVjaA%3D%3D"（浏览器登录后复制，约 24h 有效）

典型用法（配合 deploy-remote.ps1）：
  python panel_api.py health-check
  python panel_api.py upload  app_20260901.tar.gz  /opt
  python panel_api.py load    /opt/app_20260901.tar.gz
  python panel_api.py tag     bidagent-backend:20260901  bidagent-backend:latest
  python panel_api.py compose-test --name deploy --path /opt/bidagent/deploy/docker-compose.offline.yml
  python panel_api.py compose-up   --name deploy --path /opt/bidagent/deploy/docker-compose.offline.yml
  python panel_api.py ps
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests

HERE = Path(__file__).resolve().parent


# ────────────────────────── 配置加载 ──────────────────────────

def load_remote_env() -> dict[str, str]:
    """读取 deploy/.env.remote（远端参数）与 deploy/.env.prod（密钥）。"""
    env: dict[str, str] = {}
    for fname in (".env.remote", ".env.prod", ".env.prod.example"):
        p = HERE / fname
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def build_env_list(env: dict[str, str], extra: list[str] | None = None) -> list[str]:
    """从 .env.prod 提取 compose 所需密钥变量（1Panel 会写入 1panel.env）。"""
    keys = ["BID_JWT_SECRET", "BID_MINIO_ACCESS_KEY", "BID_MINIO_SECRET_KEY"]
    out = [f"{k}={env.get(k, '')}" for k in keys]
    if extra:
        out.extend(extra)
    return out


# ────────────────────────── 1Panel 客户端 ──────────────────────────

class PanelClient:
    def __init__(self, env: dict[str, str]):
        self.base = env["PANEL_URL"].rstrip("/")
        self.entrance = env.get("PANEL_ENTRANCE", "")
        self.api_key = env.get("PANEL_API_KEY", "")
        self.cookies = env.get("PANEL_COOKIES", "")
        self.timeout = int(env.get("PANEL_TIMEOUT", "30"))

    # -- 鉴权头 --
    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        h: dict[str, str] = {}
        if self.api_key:
            ts = str(int(time.time()))
            h["1Panel-Timestamp"] = ts
            h["1Panel-Token"] = hashlib.md5(
                f"1panel{self.api_key}{ts}".encode()
            ).hexdigest()
        elif self.cookies:
            h["Cookie"] = self.cookies
        else:
            raise RuntimeError("未配置 PANEL_API_KEY 或 PANEL_COOKIES（见 .env.remote）")
        if extra:
            h.update(extra)
        return h

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base}{path}"
        headers = self._headers()
        headers["Accept-Language"] = "zh"
        headers.update(kwargs.pop("headers", {}) or {})
        r = requests.request(method, url, timeout=kwargs.pop("timeout", self.timeout), headers=headers, **kwargs)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        try:
            data = r.json()
        except ValueError:
            raise RuntimeError(f"非 JSON 响应（可能被面板入口拦截）: {r.text[:200]}")
        if data.get("code") != 200:
            raise RuntimeError(f"面板错误 {data.get('code')}: {data.get('message')} | {json.dumps(data.get('data'), ensure_ascii=False)[:200]}")
        return data.get("data")

    # -- 通用查询 --
    def login_check(self) -> bool:
        d = self._request("POST", "/api/v1/settings/search", json={})
        return isinstance(d, dict) and bool(d.get("userName"))

    def images(self, keyword: str = "") -> list[dict]:
        items = self._request("GET", "/api/v1/containers/image/all")
        out = []
        for it in items or []:
            tag = (it.get("tags") or [""])[0]
            if not keyword or keyword in tag:
                out.append({"id": it.get("id"), "tag": tag, "size": it.get("size")})
        return out

    def containers(self, name: str = "") -> list[dict]:
        d = self._request(
            "POST", "/api/v1/containers/search",
            json={"page": 1, "pageSize": 100, "state": "all", "name": name,
                  "orderBy": "created_at", "order": "null", "filters": ""},
        )
        return d.get("items") or []

    def compose_search(self, name: str = "") -> list[dict]:
        d = self._request(
            "POST", "/api/v1/containers/compose/search",
            json={"page": 1, "pageSize": 50, "name": name,
                  "orderBy": "created_at", "order": "desc"},
        )
        return d if isinstance(d, list) else (d.get("items") or [] if isinstance(d, dict) else [])

    # -- 文件与镜像 --
    def upload(self, local_path: str, target_dir: str) -> None:
        """1Panel 上传语义：target_dir 是目录，文件名取本地文件名。"""
        if not os.path.isfile(local_path):
            raise RuntimeError(f"本地文件不存在: {local_path}")
        with open(local_path, "rb") as f:
            r = requests.post(
                f"{self.base}/api/v1/files/upload",
                headers=self._headers(),
                files={"file": (os.path.basename(local_path), f)},
                data={"path": target_dir, "overwrite": "true"},
                timeout=1800,
            )
        if r.status_code != 200:
            raise RuntimeError(f"上传失败 HTTP {r.status_code}: {r.text[:200]}")
        d = r.json()
        if d.get("code") != 200:
            raise RuntimeError(f"上传失败: {d.get('message')}")
        print(f"  [upload] {os.path.basename(local_path)} -> {target_dir} OK")

    def image_load(self, server_path: str, retries: int = 3) -> None:
        """加载镜像包。面板 SQLite 可能瞬时 BUSY（并发写），重试收敛；大包加载耗时长，放宽读超时."""
        import time as _t

        last_err: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                self._request("POST", "/api/v1/containers/image/load",
                              json={"path": server_path}, timeout=900.0)
                print(f"  [load] {server_path} OK")
                return
            except Exception as e:
                last_err = e
                msg = str(e)
                if "SQLITE_BUSY" in msg or "database is locked" in msg:
                    print(f"  [load] 面板忙（SQLITE_BUSY），{attempt}/{retries} 次重试...")
                    _t.sleep(8)
                    continue
                raise
        raise RuntimeError(f"load 失败（{retries} 次重试后仍 BUSY）: {last_err}")

    def image_tag(self, source: str, target: str, retries: int = 5) -> None:
        """source/target 用镜像名或 ID 均可；面板 SQLite BUSY 时重试."""
        import time as _t

        last_err: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                self._request("POST", "/api/v1/containers/image/tag",
                              json={"sourceID": source, "targetName": target})
                print(f"  [tag] {source} -> {target} OK")
                return
            except Exception as e:
                last_err = e
                msg = str(e)
                if "SQLITE_BUSY" in msg or "database is locked" in msg:
                    print(f"  [tag] 面板忙（SQLITE_BUSY），{attempt}/{retries} 次重试...")
                    _t.sleep(10)
                    continue
                raise
        raise RuntimeError(f"tag 失败（{retries} 次重试后仍 BUSY）: {last_err}")

    # -- 编排 --
    def compose_test(self, name: str, path: str, env_list: list[str]) -> None:
        d = self._request(
            "POST", "/api/v1/containers/compose/test",
            json={"name": name, "from": "path", "path": path, "env": env_list},
        )
        if d is not True:
            raise RuntimeError(f"compose 校验未通过: {d}")
        print(f"  [compose-test] {path} OK")

    def compose_up(self, name: str, path: str, env_list: list[str], retries: int = 6) -> str:
        """触发 compose 编排（异步）；面板 SQLite BUSY 时重试（等待面板恢复）."""
        import time as _t

        last_err: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                d = self._request(
                    "POST", "/api/v1/containers/compose",
                    json={"name": name, "from": "path", "path": path, "env": env_list},
                    timeout=120.0,
                )
                print(f"  [compose-up] 已触发（日志 {d}），异步执行中")
                return str(d)
            except Exception as e:
                last_err = e
                msg = str(e)
                if "SQLITE_BUSY" in msg or "database is locked" in msg:
                    print(f"  [compose-up] 面板忙（SQLITE_BUSY），{attempt}/{retries} 次重试...")
                    _t.sleep(15)
                    continue
                raise
        raise RuntimeError(f"compose-up 失败（{retries} 次重试后仍 BUSY）: {last_err}")


# ────────────────────────── CLI ──────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="1Panel 远端部署工具")
    ap.add_argument("command", choices=[
        "health-check", "images", "containers", "compose-search",
        "upload", "load", "tag", "compose-test", "compose-up",
    ])
    ap.add_argument("arg", nargs="*", help="位置参数（见命令说明）")
    ap.add_argument("--name", default="", help="compose 名称")
    ap.add_argument("--path", default="", help="compose 文件路径（服务器端）")
    ap.add_argument("--dir", default="", help="上传目标目录（服务器端）")
    args = ap.parse_args()

    env = load_remote_env()
    client = PanelClient(env)

    try:
        if args.command == "health-check":
            ok = client.login_check()
            print(f"面板会话: {'OK' if ok else 'FAIL'}")
            return 0 if ok else 1
        if args.command == "images":
            for it in client.images(args.arg[0] if args.arg else ""):
                print(f"  {it['tag']:60s} {it['size']}")
            return 0
        if args.command == "containers":
            for it in client.containers(args.arg[0] if args.arg else ""):
                print(f"  {it.get('name',''):40s} {it.get('state','')}")
            return 0
        if args.command == "compose-search":
            for it in client.compose_search(args.arg[0] if args.arg else ""):
                print(f"  {it.get('name',''):30s} {it.get('path','')}")
            return 0
        if args.command == "upload":
            if len(args.arg) < 2:
                raise RuntimeError("用法: upload <本地文件> <目标目录>")
            client.upload(args.arg[0], args.arg[1])
            return 0
        if args.command == "load":
            if not args.arg:
                raise RuntimeError("用法: load <服务器文件路径>")
            client.image_load(args.arg[0])
            return 0
        if args.command == "tag":
            if len(args.arg) < 2:
                raise RuntimeError("用法: tag <源镜像名/ID> <目标tag>")
            client.image_tag(args.arg[0], args.arg[1])
            return 0
        if args.command in ("compose-test", "compose-up"):
            if not args.name or not args.path:
                raise RuntimeError("需要 --name 与 --path")
            env_list = build_env_list(env)
            if args.command == "compose-test":
                client.compose_test(args.name, args.path, env_list)
            else:
                client.compose_up(args.name, args.path, env_list)
            return 0
    except RuntimeError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
