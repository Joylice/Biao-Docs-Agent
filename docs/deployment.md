# 部署文档（deployment.md）

> 适用项目：投标软件技术方案智能体
> 适用环境：Windows（PowerShell，分隔符使用 `;`）/ Linux（参考调整分隔符为 `&&`）
> 最后更新：2026-08-15

---

## 1. 架构总览

系统由 6 类服务组成，通过 `deploy/docker-compose.yml` 编排：

| 服务 | 镜像 / 构建 | 端口 | 说明 |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg16` | 5432 | PostgreSQL 16 + pgvector 扩展，业务数据 + 向量检索 |
| `redis` | `redis:7-alpine` | 6379 | Arq 任务队列 Broker + 缓存 |
| `minio` | `minio/minio` | 9000 / 9001 | 对象存储（招标文件、生成产物），9001 为控制台 |
| `api` | 本地构建 `backend/Dockerfile` | 8000 | FastAPI 后端（uvicorn），依赖 postgres/redis/minio |
| `worker` | 本地构建 `backend/Dockerfile` | — | Arq 异步任务 Worker（`arq worker.WorkerSettings`） |
| `web` | 本地构建 `frontend/Dockerfile` | 5173→80 | Vue3 前端，构建产物由 Nginx 托管 |

服务拓扑（依赖方向）：

```mermaid
graph TB
    web[web - Vue3/Nginx] --> api
    api[api - FastAPI/uvicorn] --> postgres
    api --> redis
    api --> minio
    worker[worker - Arq] --> postgres
    worker --> redis
    worker --> minio
    postgres[(postgres+pgvector)]
    redis[(redis)]
    minio[(minio)]
```

要点：

- `api` 与 `worker` 均带 healthcheck 依赖（`depends_on.condition: service_healthy`），postgres/redis/minio 就绪后才启动。
- compose 中的基础镜像均带有 `docker.1ms.run/` 加速前缀（国内镜像源），Dockerfile 内 pip/apt/npm 也已切换国内源。
- 本地开发模式下 `api`/`worker` 挂载 `../backend` 源码目录并开启 `--reload`，改代码即时生效。

---

## 2. 环境要求

| 组件 | 版本要求 | 说明 |
|---|---|---|
| Python | **3.12** | 后端运行时，建议使用 venv |
| Node.js | 20+（建议 22 LTS） | 前端构建 |
| pnpm | 8+ | 前端包管理器（`npm i -g pnpm`） |
| Docker Desktop | 最新版（含 Docker Compose v2） | 基础设施与生产容器 |
| make（可选） | Windows 可用 `choco install make` | 使用 Makefile 快捷目标时需要 |
| Git | 任意近期版本 | 代码管理 |

后端依赖（`backend/requirements.txt`）与前端依赖（`frontend/package.json`）分别由 pip / pnpm 安装，无需额外系统服务。

---

## 3. Docker 镜像加速配置（重要）

当前网络环境下 Docker Hub 经常不可达。本仓库已在 compose/Dockerfile 中为镜像地址加上 `docker.1ms.run/` 前缀作为加速源；如该源也不可用，请配置 Docker 引擎级镜像加速。

### 3.1 Docker Desktop 配置步骤（Windows）

1. 打开 **Docker Desktop → Settings（齿轮图标）→ Docker Engine**。
2. 在 JSON 配置中加入 `registry-mirrors` 字段（参考仓库示例文件 `deploy/daemon.windows.json`）：

   ```json
   {
     "registry-mirrors": [
       "https://<MIRROR-1-REPLACE-ME>",
       "https://<MIRROR-2-REPLACE-ME>"
     ]
   }
   ```

3. 将 `<MIRROR-x-REPLACE-ME>` 占位符替换为**当前可用**的镜像加速源（各厂商加速源可用性随时间变化，请使用前先在浏览器/`curl` 验证可达性；示例文件中保留 `_comment` 字段作说明，不影响 daemon 解析，介意可删）。
4. 点击 **Apply & Restart**，等待 Docker 重启完成。
5. 验证：

   ```powershell
   docker info | Select-String "Registry Mirrors" -Context 0,2
   ```

### 3.2 与 compose 前缀的关系

- compose 中已写死 `docker.1ms.run/...` 前缀的镜像**不受** daemon `registry-mirrors` 影响（mirror 仅对 Docker Hub 官方短名生效）。
- 若 `docker.1ms.run` 也不可达，参见 [§8.1 故障排查](#81-docker-hub--镜像源不可达) 的替代方案。

---

## 4. 本地开发启动步骤（Windows PowerShell）

> 约定：所有多命令均使用 `;` 作为 PowerShell 分隔符。

### 4.1 准备后端虚拟环境（首次）

```powershell
cd d:\AI\WorkBuddy\2026-08-15-17-35-34\backend ; python -3.12 -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt -r requirements-dev.txt
copy .env.example .env   # 按需修改 .env（默认值可直接对接本地 compose 基础设施）
```

### 4.2 准备前端依赖（首次）

```powershell
cd d:\AI\WorkBuddy\2026-08-15-17-35-34\frontend ; pnpm install
```

### 4.3 启动基础设施（postgres + redis + minio）

```powershell
cd d:\AI\WorkBuddy\2026-08-15-17-35-34 ; docker compose -f deploy/docker-compose.yml up -d postgres redis minio
docker compose -f deploy/docker-compose.yml ps   # 等待三者均为 healthy
```

### 4.4 数据库迁移

```powershell
cd d:\AI\WorkBuddy\2026-08-15-17-35-34\backend ; alembic upgrade head
```

### 4.5 初始化 MinIO bucket（首次）

```powershell
docker compose -f deploy/docker-compose.yml exec minio mc alias set local http://localhost:9000 minioadmin minioadmin ; docker compose -f deploy/docker-compose.yml exec minio mc mb --ignore-existing local/bid-documents
```

### 4.6 启动后端 API（终端 A）

```powershell
cd d:\AI\WorkBuddy\2026-08-15-17-35-34\backend ; uvicorn app.main:app --reload --port 8000
```

### 4.7 启动 Arq Worker（终端 B，可选，异步任务需要）

```powershell
cd d:\AI\WorkBuddy\2026-08-15-17-35-34\backend ; arq worker.WorkerSettings
```

### 4.8 启动前端（终端 C）

```powershell
cd d:\AI\WorkBuddy\2026-08-15-17-35-34\frontend ; pnpm dev
```

访问入口：

- 前端：<http://localhost:5173>
- 后端 API 文档：<http://localhost:8000/docs>
- MinIO 控制台：<http://localhost:9001>（minioadmin / minioadmin）

等价快捷命令（Makefile）：`make docker-up`（全量容器）、`make dev-backend`、`make dev-frontend`。

---

## 5. 生产部署步骤

### 5.1 构建并启动全部容器

```powershell
cd d:\AI\WorkBuddy\2026-08-15-17-35-34 ; docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml ps
```

### 5.2 执行数据库迁移

```powershell
docker compose -f deploy/docker-compose.yml exec api alembic upgrade head
```

### 5.3 初始化 MinIO bucket

```powershell
docker compose -f deploy/docker-compose.yml exec minio mc alias set local http://localhost:9000 minioadmin minioadmin ; docker compose -f deploy/docker-compose.yml exec minio mc mb --ignore-existing local/bid-documents
```

### 5.4 确认 Worker 运行

Worker 已在 compose 中随 `up -d` 启动（`arq worker.WorkerSettings`），确认其状态与日志：

```powershell
docker compose -f deploy/docker-compose.yml ps worker ; docker compose -f deploy/docker-compose.yml logs --tail=50 worker
```

### 5.5 生产环境注意事项

- 生产环境请通过 `environment` 或外部 `.env` 覆盖默认值：`BID_DEBUG=false`、`BID_LLM_MOCK=false`、`BID_JWT_SECRET`（强随机值）、PostgreSQL/MinIO 账号密码。
- compose 中 `api` 当前挂载源码并带 `--reload`，属于开发配置；生产建议去除 volume 挂载与 `--reload`，使用镜像默认 CMD。
- 持久化数据位于命名卷 `pgdata` 与 `miniodata`，备份请针对这两个卷。

---

## 6. 环境变量清单

与 `backend/.env.example` 对齐（前缀 `BID_`）：

| 变量 | 默认值（示例） | 说明 |
|---|---|---|
| `BID_DEBUG` | `false` | 调试模式；本地开发置 `true` |
| `BID_API_PREFIX` | `/api/v1` | API 路由前缀 |
| `BID_DATABASE_URL` | `postgresql+psycopg://bid:bid@localhost:5432/bid` | PostgreSQL 连接串（compose 内为 `postgres:5432`） |
| `BID_REDIS_URL` | `redis://localhost:6379/0` | Redis 连接串（compose 内为 `redis:6379`） |
| `BID_JWT_SECRET` | `change-me-in-production` | JWT 签名密钥，**生产必须更换** |
| `BID_JWT_ALGORITHM` | `HS256` | JWT 算法 |
| `BID_JWT_ACCESS_EXPIRE_MINUTES` | `120` | Access Token 有效期（分钟） |
| `BID_JWT_REFRESH_EXPIRE_DAYS` | `7` | Refresh Token 有效期（天） |
| `BID_MINIO_ENDPOINT` | `localhost:9000` | MinIO 地址（compose 内为 `minio:9000`） |
| `BID_MINIO_ACCESS_KEY` | `minioadmin` | MinIO 访问密钥 |
| `BID_MINIO_SECRET_KEY` | `minioadmin` | MinIO 秘密密钥，**生产必须更换** |
| `BID_MINIO_BUCKET` | `bid-documents` | 对象存储 bucket 名 |
| `BID_MINIO_SECURE` | `false` | 是否启用 HTTPS 访问 MinIO |
| `BID_LLM_MOCK` | `true` | LLM mock 开关；测试/离线开发为 `true` |
| `BID_LLM_MODEL` | `deepseek/deepseek-chat` | 默认 LLM 模型（LiteLLM 格式） |
| `BID_LLM_PRIMARY` | `deepseek/deepseek-chat` | 主模型 |
| `BID_LLM_BACKUP` | `qwen/qwen-plus` | 备用模型 |
| `BID_EMBEDDING_MODEL` | `bge-m3` | Embedding 模型名 |
| `BID_EMBEDDING_DIMENSION` | `1024` | 向量维度（需与 pgvector 列维度一致） |
| `BID_EMBEDDING_API_BASE` | `http://localhost:11434/v1` | Embedding 服务地址（如 Ollama） |
| `BID_MAX_UPLOAD_SIZE_MB` | `50` | 单文件上传上限（MB） |

compose 中 api/worker 内置的环境变量（`BID_DATABASE_URL`、`BID_REDIS_URL`、`BID_MINIO_ENDPOINT`、`BID_DEBUG=true`、`BID_LLM_MOCK=true`）面向开发联调，生产请覆盖。

---

## 7. 健康检查与验证

### 7.1 接口级

```powershell
# 后端健康检查（期望 {"status":"ok"} 或类似 200 响应）
curl.exe http://localhost:8000/health

# OpenAPI 文档页（浏览器打开应正常渲染）
start http://localhost:8000/docs
```

### 7.2 容器级

compose 已为 postgres / redis / minio 配置 healthcheck，查看状态：

```powershell
docker compose -f deploy/docker-compose.yml ps        # STATUS 列应出现 (healthy)
docker compose -f deploy/docker-compose.yml logs api --tail=50
```

### 7.3 端到端冒烟

1. 打开前端 <http://localhost:5173>，登录页可正常加载。
2. 使用测试账号登录（首次可经 `/api/v1/auth` 注册接口创建）。
3. 上传一个小体积 PDF 走「解析 → 确认」流程，确认 MinIO bucket `bid-documents` 中出现对象（MinIO 控制台 9001 查看）。
4. `BID_LLM_MOCK=true` 时生成流程应可离线跑通（不消耗真实 LLM 额度）。

---

## 8. 常见故障排查

### 8.1 Docker Hub / 镜像源不可达

**症状**：`docker compose up -d` 拉取镜像超时、`pull access denied`、`i/o timeout`。

本仓库基础镜像已带 `docker.1ms.run/` 加速前缀（含 `pgvector/pgvector:pg16`、`redis:7-alpine`、`minio/minio`、`python:3.12-slim`、`node:22-alpine`、`nginx:alpine`）。若该源同样不可达，按以下顺序处理：

1. **配置 daemon 镜像加速**：见 §3，把 `registry-mirrors` 替换为当前可用源后重启 Docker。注意：对已写死 `docker.1ms.run/` 前缀的镜像名，可临时把 compose/Dockerfile 中前缀替换为另一个可用加速前缀（如公司私有 Harbor/Nexus 代理），或去掉前缀走 daemon mirror。
2. **在可联网机器预拉取后导入**：

   ```powershell
   # 可联网机器
   docker pull pgvector/pgvector:pg16 ; docker save pgvector/pgvector:pg16 -o pgvector-pg16.tar
   # 目标机器
   docker load -i pgvector-pg16.tar
   ```

   其余镜像（redis、minio、python、node、nginx）同理。
3. **使用国内可用镜像仓库重打标签**，例如：

   ```powershell
   docker tag <可用源>/pgvector/pgvector:pg16 docker.1ms.run/pgvector/pgvector:pg16
   ```

4. 按约束**不要直接修改 compose 文件结构**；仅允许在确认网络方案后同步替换镜像前缀。

### 8.2 pip 安装超时

**症状**：`ReadTimeoutError`、`Could not fetch URL https://pypi.org/...`。

- 首选使用 **uv** 安装（更快、更稳）：

  ```powershell
  pip install uv ; uv pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt -r requirements-dev.txt
  ```

- 或全局切换清华源：

  ```powershell
  pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
  ```

- Dockerfile 内 pip 已使用清华源，构建时无需额外处理。

### 8.3 passlib / bcrypt 版本兼容性

**症状**：`AttributeError: module 'bcrypt' has no attribute '__about__'` 或 `(trapped) error reading bcrypt version`。

- 本项目鉴权直接使用 `bcrypt`（requirements 约束 `bcrypt>=4.0,<6.0`），**未引入 passlib**；若从旧代码/示例复制了 passlib 相关代码，请改为直接使用 `bcrypt`（参见 `app/core/security.py`）。
- 若确需 passlib：将 bcrypt 固定到 `bcrypt<4.1`（passlib 1.7.4 与 bcrypt≥4.1 不兼容），或升级到 passlib 官方修复版本 / 改用其他哈希库。
- 出现告警但功能正常时，该日志为版本探测告警，可忽略；功能异常（哈希校验失败）时必须按上述方式对齐版本。

### 8.4 其他常见问题速查

| 症状 | 可能原因 | 处理 |
|---|---|---|
| `alembic upgrade head` 连接失败 | postgres 未 healthy / URL 错误 | `docker compose ps` 检查；核对 `BID_DATABASE_URL` |
| 前端请求 404 | nginx 代理前缀与 `BID_API_PREFIX` 不一致 | 检查 `frontend/nginx.conf` 与 `.env` 的 `/api/v1` |
| Worker 无任务执行 | redis 连接串错误 / worker 未启动 | `docker compose logs worker`；核对 `BID_REDIS_URL` |
| 向量写入报维度错误 | `BID_EMBEDDING_DIMENSION` 与建表维度不符 | 保持 1024（bge-m3）一致 |
| 端口占用（5432/6379/9000/8000） | 本机已有同名服务 | 停掉本机服务或调整 compose 端口映射 |

---

*维护约定：修改 compose 服务/端口、Dockerfile、`.env.example` 时，须同步更新本文档对应章节。*
