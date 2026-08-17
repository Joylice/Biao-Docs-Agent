/**
 * E2E 认证与项目 fixture — 直接打后端 API 完成 注册 → 登录拿 JWT → 建项目，
 * 避免 UI 前置流程对每个场景的干扰（对齐 docs/agents/testing.md §4）。
 *
 * 注意：后端 API 前缀为 /api/v1（backend/app/core/config.py: api_prefix）。
 *
 * 已知产品 bug（2026-08-16 回归确认）：backend/app/core/database.py get_db 在响应
 * 发出后才 commit（FastAPI 0.106+ 依赖 teardown 时序），register 返回 200 时用户行
 * 可能尚未提交，紧随其后的 login 约 1/3 概率命中竞态返回 4001。
 * registerAndLogin 内置有限重试规避该竞态（交回后端智能体修复后重试可移除）。
 */
import { expect, request, test as base, type APIRequestContext } from '@playwright/test';

// ── 环境常量 ──
export const API_URL = process.env.E2E_API_URL || 'http://localhost:8000';
export const API_PREFIX = '/api/v1';

/** 拼接 API 路径：api('/auth/login') => '/api/v1/auth/login' */
export function api(path: string): string {
  return `${API_PREFIX}${path}`;
}

/** 由 API_URL 推导 WebSocket 地址（http→ws / https→wss） */
export function wsUrl(path: string): string {
  return API_URL.replace(/^http/, 'ws') + path;
}

/**
 * 后端 LLM mock 开关是否打开。
 * 对应 backend/app/core/config.py 的 `llm_mock`（环境变量 BID_LLM_MOCK，前缀 BID_）。
 * 服务端 llm_service.py / rag_service.py 已引用 settings.llm_mock，相关 LLM 断言
 * 需后端以 BID_LLM_MOCK=true 启动，未设置时以此开关为前置条件 skip。
 * 注意：本函数读取的是"测试进程"的环境变量，运行 E2E 时需设 BID_LLM_MOCK=true
 * 以匹配 docker compose 中 api/worker 容器的实际配置。
 */
export function llmMockEnabled(): boolean {
  return String(process.env.BID_LLM_MOCK || '').toLowerCase() === 'true';
}

// ── 数据类型（对齐 backend/app/schemas/）──
export interface AuthedUser {
  email: string;
  password: string;
  displayName: string;
  userId: string;
  accessToken: string;
  refreshToken: string;
}

export interface Project {
  id: string;
  name: string;
  tender_no: string | null;
  industry: string | null;
  status: string;
  owner_id: string;
}

/** 统一响应体：{ code, message, data }（backend/app/core/response.py） */
export interface BizResponse<T = unknown> {
  code: number;
  message: string;
  data: T;
}

/**
 * 工作流状态（对齐 workflow_runtime.get_status_dict）：
 * phase/progress/score_points/outline/chapters/review_action/review_feedback/
 * export_status/export_storage_key/error/interrupt
 */
export interface WorkflowStatus {
  workflow_id?: string;
  phase: string;
  progress: number;
  score_points: unknown[];
  outline: Array<{
    chapter_no: string;
    title: string;
    sections?: string[];
    covered_clauses?: string[];
  }>;
  chapters: Record<string, string>;
  review_action?: string;
  review_feedback?: Record<string, string>;
  export_status?: string;
  export_storage_key?: string;
  error?: string;
  interrupt: { type: string; [k: string]: unknown } | null;
}

function uniqueStamp(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function bearer(user: AuthedUser): Record<string, string> {
  return { Authorization: `Bearer ${user.accessToken}` };
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

/**
 * 注册新用户并登录获取 JWT（直接打 API）。
 * 每次调用使用唯一邮箱，避免用例间数据冲突。
 * 登录带有限重试：规避 register 提交竞态（见文件头说明）。
 */
export async function registerAndLogin(
  apiCtx: APIRequestContext,
  role = 'user',
): Promise<AuthedUser> {
  const email = `e2e-${role}-${uniqueStamp()}@example.com`;
  const password = 'E2ePass#12345';
  const displayName = `E2E ${role}`;

  const reg = await apiCtx.post(api('/auth/register'), {
    data: { email, password, display_name: displayName },
  });
  expect(reg.status(), `注册失败: ${await reg.text()}`).toBe(200);
  const regBody = (await reg.json()) as BizResponse<{ id: string }>;
  expect(regBody.code).toBe(0);

  let lastStatus = 0;
  let lastText = '';
  let loginBody: BizResponse<{ access_token: string; refresh_token: string }> | null = null;
  for (let attempt = 0; attempt < 5 && !loginBody; attempt++) {
    if (attempt > 0) await sleep(400); // 等待 register 事务提交（后端竞态规避）
    const login = await apiCtx.post(api('/auth/login'), { data: { email, password } });
    lastStatus = login.status();
    lastText = await login.text();
    if (lastStatus === 200) {
      loginBody = JSON.parse(lastText) as BizResponse<{
        access_token: string;
        refresh_token: string;
      }>;
    }
  }
  expect(loginBody, `登录失败(${lastStatus}): ${lastText}`).not.toBeNull();

  return {
    email,
    password,
    displayName,
    userId: regBody.data.id,
    accessToken: loginBody!.data.access_token,
    refreshToken: loginBody!.data.refresh_token,
  };
}

/** 创建项目并返回 ProjectOut（对齐 backend/app/schemas/project.py） */
export async function createProject(
  apiCtx: APIRequestContext,
  user: AuthedUser,
  name?: string,
): Promise<Project> {
  const resp = await apiCtx.post(api('/projects'), {
    headers: bearer(user),
    data: {
      name: name || `E2E项目-${uniqueStamp()}`,
      tender_no: `T-${uniqueStamp()}`,
      industry: '软件',
    },
  });
  expect(resp.status(), `创建项目失败: ${await resp.text()}`).toBe(200);
  const body = (await resp.json()) as BizResponse<Project>;
  expect(body.code).toBe(0);

  // 提交可见性等待：后端 get_db 在响应发出后才 commit（产品 bug，见文件头），
  // 创建响应 200 时 project/member 行可能尚未提交。轮询详情直到 owner 可见，
  // 规避后续"上传 403 / 越权 404 / WS 握手 4003"类竞态误报。后端修复后可移除。
  const deadline = Date.now() + 10_000;
  while (Date.now() < deadline) {
    const detail = await apiCtx.get(api(`/projects/${body.data.id}`), { headers: bearer(user) });
    if (detail.status() === 200) return body.data;
    await sleep(300);
  }
  throw new Error(`项目创建后 10s 内仍不可见（提交竞态未收敛）: ${body.data.id}`);
}

/** 探测后端健康检查；基础设施/后端未就绪时返回 false（用于优雅 skip） */
export async function backendHealthy(apiCtx: APIRequestContext): Promise<boolean> {
  try {
    const resp = await apiCtx.get('/health', { timeout: 5_000 });
    return resp.ok();
  } catch {
    return false;
  }
}

/** 获取一次工作流状态快照 */
export async function getWorkflowStatus(
  apiCtx: APIRequestContext,
  user: AuthedUser,
  projectId: string,
): Promise<WorkflowStatus> {
  const resp = await apiCtx.get(api(`/projects/${projectId}/workflow/status`), {
    headers: bearer(user),
  });
  expect(resp.status(), `工作流状态查询失败: ${await resp.text()}`).toBe(200);
  return ((await resp.json()) as BizResponse<WorkflowStatus>).data;
}

/**
 * 轮询工作流状态直到 predicate 满足（或超时 / 进入 error 态立即返回）。
 * 用于 HITL interrupt 等待、phase 推进等待等。
 */
export async function waitForWorkflowStatus(
  apiCtx: APIRequestContext,
  user: AuthedUser,
  projectId: string,
  predicate: (s: WorkflowStatus) => boolean,
  timeoutMs = 60_000,
  intervalMs = 1_000,
): Promise<WorkflowStatus> {
  const deadline = Date.now() + timeoutMs;
  let last: WorkflowStatus | null = null;
  while (Date.now() < deadline) {
    last = await getWorkflowStatus(apiCtx, user, projectId);
    if (predicate(last)) return last;
    if (last.error) return last; // error 态不再推进，提前返回供断言归因
    await sleep(intervalMs);
  }
  throw new Error(
    `等待工作流状态超时(${timeoutMs}ms)，最后状态: ${JSON.stringify({
      phase: last?.phase,
      progress: last?.progress,
      interrupt: last?.interrupt?.type ?? null,
      error: last?.error || '',
    })}`,
  );
}

/**
 * 轮询文档列表直到目标文档进入期望状态（或超时）。
 * 上传后解析/向量化为 Arq worker 异步任务（上传时由 documents.py 入队），
 * 状态流转：uploaded → parsing/indexed/failed（backend/worker/tasks.py）。
 */
export async function waitForDocumentStatus(
  apiCtx: APIRequestContext,
  user: AuthedUser,
  projectId: string,
  docId: string,
  expectStatus: string[],
  timeoutMs = 60_000,
  docType?: string,
): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  let lastStatus = 'unknown';
  while (Date.now() < deadline) {
    const query = docType ? `?doc_type=${docType}` : '';
    const resp = await apiCtx.get(api(`/projects/${projectId}/documents${query}`), {
      headers: bearer(user),
    });
    if (resp.ok()) {
      const body = (await resp.json()) as BizResponse<{
        items: Array<{ id: string; status: string }>;
        total: number;
      }>;
      const doc = body.data.items.find((d) => d.id === docId);
      if (doc) {
        lastStatus = doc.status;
        if (expectStatus.includes(doc.status)) {
          return doc.status;
        }
      }
    }
    await new Promise((r) => setTimeout(r, 3_000));
  }
  return lastStatus;
}

/**
 * 扩展 test：注入 worker 级 API 请求上下文（baseURL 指向后端）。
 * specs 中统一 `import { test, expect } from '../fixtures/auth'`。
 */
export const test = base.extend<NonNullable<unknown>, { api: APIRequestContext }>({
  api: [
    async ({}, use) => {
      const ctx = await request.newContext({
        baseURL: API_URL,
        extraHTTPHeaders: { Accept: 'application/json' },
      });
      await use(ctx);
      await ctx.dispose();
    },
    { scope: 'worker' },
  ],
});

export { expect } from '@playwright/test';