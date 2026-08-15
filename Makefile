.PHONY: check security-check test lint format type-check

# ── 一键自检（CI 本地等价物） ──
check: lint type-check test

# ── Lint + Format ──
lint:
	cd backend && ruff check .
	cd backend && ruff format --check .

# ── 类型检查 ──
type-check:
	cd backend && mypy app

# ── 测试 + 覆盖率 ──
test:
	cd backend && pytest tests --cov=app --cov-report=term-missing --cov-fail-under=70 -q

# ── 关键模块覆盖率门禁 ──
test-coverage-gates:
	cd backend && pytest tests/services --cov=app.services.parse_service  --cov-fail-under=80 -q
	cd backend && pytest tests/services --cov=app.services.rag_service    --cov-fail-under=80 -q
	cd backend && pytest tests/services --cov=app.services.export_service --cov-fail-under=80 -q
	cd backend && pytest tests/unit    --cov=app.core.redact             --cov-fail-under=80 -q
	cd backend && pytest tests/agents  --cov=app.agents.graph            --cov-fail-under=80 -q

# ── 安全扫描 ──
security-check:
	@echo "=== Gitleaks ==="
	gitleaks detect --source . -v || true
	@echo "=== pip-audit ==="
	pip-audit -r backend/requirements.txt || true
	@echo "=== pnpm audit ==="
	cd frontend && pnpm audit --audit-level high || true

# ── 数据库迁移 ──
migrate:
	cd backend && alembic upgrade head

# ── 开发服务器 ──
dev-backend:
	cd backend && uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && pnpm dev

# ── Docker Compose ──
docker-up:
	docker compose -f deploy/docker-compose.yml up -d

docker-down:
	docker compose -f deploy/docker-compose.yml down
