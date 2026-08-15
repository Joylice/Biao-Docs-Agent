# security.md — 安全审计与发布门禁

> AGENTS.md 分域规约。**安全自检不通过 = 禁止合并/发布**。CI 挂载安全 job，发布前人工复核清单。

---

## 1. 依赖扫描（自动化，CI 执行）

```bash
make security-check
# 包含：
#   gitleaks detect --source . -v        # 密钥/Token/.env 泄露扫描
#   pip-audit -r backend/requirements.txt
#   cd frontend && pnpm audit
```

- CI 每次合并前扫描；**高危漏洞必须修复或记录豁免（经安全评审）**，禁止带病发布；
- 扫描产物（report）随 CI 记录，发布时归档。

## 2. 敏感信息与脱敏

- 仓库扫描（gitleaks）：禁止提交密钥/Token/`.env`；发现即撤销凭据并轮换；
- 日志/前端展示：手机号、身份证、客户名经 `app/core/redact.py` 脱敏，**有单测守护**；
- LLM 外发：脱敏后再调用（development.md §3.7），抽查样本验证脱敏有效。

**验证命令**：
```bash
pytest backend/tests/unit -k redact -q          # 脱敏单测
grep -rn "password\|secret\|api_key" backend/app/ --include="*.py" | grep -v "config\|\.env" || echo "OK"
```

## 3. 权限与越权用例（测试必须包含）

- 每个项目级接口至少一条"非成员访问 → 403"用例（E2E-07 兜底 + 接口层全覆盖）；
- 文件上传：越权文档不可下载/解析；对象存储 key 需鉴权中间件；
- 评审关注：JWT 过期/篡改、IDOR（project_id 遍历）、路径穿越（storage_key 拼接）。

**验证命令**：
```bash
grep -rn "403\|Forbidden\|assert.*status_code.*403" backend/tests/api/ | wc -l   # 越权用例数量 ≥ 项目级接口数
```

## 4. 审计日志

- 关键操作留痕：登录、上传、解析、生成、审阅、导出、成员变更（who/what/when）；
- 存 PostgreSQL `audit_logs` 表（追加式，禁止更新删除）；保留 ≥ 180 天；
- 审计写入在 service 层统一封装（`app/core/audit.py`），禁止散落各处。

## 5. 发布前安全自检清单（人工复核，可部分自动化）

```bash
make security-check   # 覆盖 1、2 项，输出报告
```

```
[ ] pip-audit / pnpm audit 无高危未豁免项（make security-check 输出）
[ ] gitleaks 扫描 0 命中
[ ] .env 未入库，密钥已轮换（如有泄露）
[ ] 越权用例全绿（接口层 + E2E-07）
[ ] 脱敏单测通过，抽查外发样本无 PII
[ ] audit_logs 记录正常（关键操作可查）
[ ] 生产凭据已改（非 Compose 默认值）
[ ] 安全评审结论（如有豁免项）已记录
```

## 6. AI 代理安全行为约束

- 禁止把密钥/Token/客户资料写入代码、日志、提交信息或粘贴到对话；
- 遇到疑似泄露：立即停止该操作，报告并建议轮换凭据，不自行继续；
- 涉及脱敏逻辑修改，必须同时更新 `redact.py` 的单测，不得绕过。
