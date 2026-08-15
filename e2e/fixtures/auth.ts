/**
 * E2E 认证与项目 fixture — 直接打后端 API 完成 注册 → 登录拿 JWT → 建项目，
 * 避免 UI 前置流程对每个场景的干扰（对齐 docs/agents/testing.md §4）。
 *
 * 注意：后端 API 前缀为 /api/v1（backend/app/core/config.py: api_prefix）。
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

function uniqueStamp(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function bearer(user: AuthedUser): Record<string, string> {
  return { Authorization: `Bearer ${user.accessToken}` };
}

/**
 * 注册新用户并登录获取 JWT（直接打 API）。
 * 每次调用使用唯一邮箱，避免用例间数据冲突。
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

  const login = await apiCtx.post(api('/auth/login'), { data: { email, password } });
  expect(login.status(), `登录失败: ${await login.text()}`).toBe(200);
  const loginBody = (await login.json()) as BizResponse<{
    access_token: string;
    refresh_token: string;
  }>;
  expect(loginBody.code).toBe(0);

  return {
    email,
    password,
    displayName,
    userId: regBody.data.id,
    accessToken: loginBody.data.access_token,
    refreshToken: loginBody.data.refresh_token,
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
  return body.data;
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

/**
 * 轮询文档列表直到目标文档进入期望状态（或超时）。
 * 上传后解析/向量化为 Arq worker 异步任务，状态流转：
 * uploaded → parsing/indexed/failed（backend/worker/tasks.py）。
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
export const test = base.extend<Record<string, never>, { api: APIRequestContext }>({
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
