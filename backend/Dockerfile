# ── Builder 阶段：安装 dev 依赖用于测试 ──
FROM docker.1ms.run/library/python:3.12-slim AS builder

WORKDIR /app

# 系统依赖（apt 换清华源加速）
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖（使用清华 PyPI 镜像加速）
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    -r requirements.txt -r requirements-dev.txt

# 应用代码
COPY . .

# ── Runtime 阶段：仅安装生产依赖 ──
FROM docker.1ms.run/library/python:3.12-slim AS runtime

WORKDIR /app

# 系统依赖（runtime 仅需运行时库，不需 build-essential）
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# 仅安装生产依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    -r requirements.txt

# 从 builder 复制应用代码（已通过测试的版本）
COPY --from=builder /app /app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
