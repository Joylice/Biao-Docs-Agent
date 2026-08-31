# 测试环境远端部署手册（192.168.18.200）

> 部署方式：**离线镜像方案**（目标服务器 dockerd 无法访问外网镜像仓库，已在 2026-08-31 实测验证）
> 管理面板：1Panel v1.10.31-lts（`http://192.168.18.200:20000/tech`）

## 一、架构与端口

| 服务 | 容器 | 宿主机端口 | 说明 |
|---|---|---|---|
| 前端 web | deploy-web-1 | **5173** | nginx 静态 |
| 后端 API | deploy-api-1 | **18000** | 启动前置 `alembic upgrade head` |
| Arq Worker | deploy-worker-1 | — | 后台任务 |
| PostgreSQL+pgvector | deploy-postgres-1 | 15432 | 数据卷 pgdata |
| Redis | deploy-redis-1 | 16379 | |
| MinIO | deploy-minio-1 | 19000 / 19001 | 数据卷 miniodata |

编排名：`deploy`，compose 文件：`/opt/bidagent/deploy/docker-compose.offline.yml`（服务器端）
服务器源码目录：`/opt/bidagent/{backend,frontend,deploy}`（可读，便于排查）

## 二、前置条件（一次性）

### 2.1 本地
- Docker Desktop 运行中（构建 + save）
- Python 环境（脚本自动找 venv：`~/.workbuddy/binaries/python/envs/default`，需含 `requests`、`cryptography`）

### 2.2 面板认证（二选一）
- **方式 A（推荐，全自动）**：1Panel → 设置 → 安全 → API 接口：**开启** + 生成 **API Key** + **IP 白名单必须配置**（填本机出口 IP 或 `0.0.0.0/0`；为空会报 "IP whitelist is empty"）→ 填入 `deploy/.env.remote` 的 `PANEL_API_KEY`
- **方式 B（备选）**：浏览器登录面板 → DevTools → Application → Cookies 复制 `psession=...; SecurityEntrance=...` 填入 `PANEL_COOKIES`（约 24h 有效，过期需刷新）

### 2.3 密钥文件
- `deploy/.env.prod`：生产密钥（已 gitignore），包含 `BID_JWT_SECRET` / `BID_MINIO_ACCESS_KEY` / `BID_MINIO_SECRET_KEY` / 可选 `DEEPSEEK_API_KEY` / `DASHSCOPE_API_KEY`
- `deploy/.env.remote`：远端连接参数（已 gitignore）

## 三、命令速查

```powershell
# 完整迭代部署（构建 → 导出 → 上传 → 加载 → retag → compose up → 健康检查）
powershell -ExecutionPolicy Bypass -File deploy\deploy-remote.ps1

# 指定版本号（镜像 tag，默认 yyyyMMdd）
powershell -ExecutionPolicy Bypass -File deploy\deploy-remote.ps1 -Version 20260901

# 只重新部署镜像（跳过构建）
powershell -ExecutionPolicy Bypass -File deploy\deploy-remote.ps1 -SkipBuild

# 首次部署（额外打包上传 pgvector/redis/minio 基础设施镜像）
powershell -ExecutionPolicy Bypass -File deploy\deploy-remote.ps1 -InitInfra

# 只做健康检查
powershell -ExecutionPolicy Bypass -File deploy\deploy-remote.ps1 -HealthOnly
```

## 四、首次部署 vs 迭代部署

| 场景 | 命令 | 说明 |
|---|---|---|
| **首次**（全新服务器） | `deploy-remote.ps1 -InitInfra` | 全量：infra + app 镜像、密钥、compose 编排 |
| **迭代**（日常发版） | `deploy-remote.ps1` | 只更新 app 镜像（api/worker/web） |
| **只改配置**（密钥/端口） | 编辑服务器 `/opt/bidagent/deploy/.env` → 1Panel「容器 → 编排 → deploy → 操作 → up」 | 不用重发镜像 |
| **升级依赖/基础镜像** | `deploy-remote.ps1 -InitInfra` | infra 镜像 tag 变化时 |

## 五、回滚

服务器保留历史版本镜像（如 `bidagent-backend:20260831` / `bidagent-web:20260831`）。

```powershell
# 1. 把旧版本 retag 为 latest
python deploy\panel_api.py tag bidagent-backend:20260831 bidagent-backend:latest
python deploy\panel_api.py tag bidagent-web:20260831     bidagent-web:latest

# 2. 重新编排（容器会用 latest 重建）
#    1Panel → 容器 → 编排 → deploy → 操作 → up
```

数据库回滚：迁移是前向的（`alembic upgrade head`），如需回退表结构需手动执行 `alembic downgrade <版本>`（一般不做）。

## 六、常见问题（实测踩坑记录）

| # | 现象 | 根因 | 处理 |
|---|---|---|---|
| 1 | 部署后无新容器，编排无记录 | **服务器 dockerd 无外网**，镜像拉取/构建卡死 | 必须走离线镜像方案（本手册）；`compose/test` 只校验语法不拉镜像 |
| 2 | 上传后文件变成目录 | 1Panel `files/upload` 的 `path` 是**目录语义**，文件名取本地文件名 | `panel_api.py upload` 已封装正确用法 |
| 3 | api 容器 CrashLoop，日志 `BID_JWT_SECRET` 为空 | 1Panel `newComposeEnv` 写 `1panel.env`，但 docker-compose `${VAR}` 替换只读同目录 **`.env`** | compose 已加 `env_file: 1panel.env`；密钥另存 `/opt/bidagent/deploy/.env`（脚本 compose-up 自动写 env 数组） |
| 4 | 迁移失败 `value too long for type character varying(32)` | revision `0016_annotation_edit_version_rollback` 35 字符 > varchar(32) | 首次已用一次性容器预建 varchar(128) 版本表；后续迁移自动复用 |
| 5 | api 首次启动崩 `proposal_workflows does not exist` | 数据库未初始化（迁移未跑） | api `command` 已前置 `alembic upgrade head`（幂等，每次启动自动迁移） |
| 6 | 面板 API 报 `IP whitelist is empty` | API 接口模式的 IP 白名单为空 | 设置 → 安全 → API 接口 → 配置 IP 白名单 |

## 七、服务器端文件布局（参照）

```
/opt/bidagent/
├── backend/            # 源码（可读，便于排查）
├── frontend/           # 源码
└── deploy/
    ├── docker-compose.offline.yml   # 编排定义（与仓库同步）
    ├── .env                         # 密钥变量（docker-compose ${} 替换来源）
    └── 1panel.env                   # 1Panel 每次 compose 时自动重写（勿手改）
```

## 八、附录：底层 API（panel_api.py 封装）

- 登录/鉴权：`1Panel-Token=md5("1panel"+key+ts)` + `1Panel-Timestamp`（API Key 模式）
- 上传：`POST /api/v1/files/upload`（multipart: file + path 目录 + overwrite）
- 加载：`POST /api/v1/containers/image/load`（支持 tar.gz，Docker SDK 自动解压）
- 打标：`POST /api/v1/containers/image/tag`
- 编排：`POST /api/v1/containers/compose`（from=path，env 数组 → 写 1panel.env）→ 异步 `docker-compose -f <path> up -d`
