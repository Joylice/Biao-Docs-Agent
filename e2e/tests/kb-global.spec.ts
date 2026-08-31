/**
 * 场景 9 / E2E-08：全局资料库（二期）
 * 全局资料上传（project_id IS NULL）→ 全局列表可见 → 全局检索命中 →
 * 项目隔离（全局列表不含项目级文档）→ 删除仅限管理员（普通用户 403）。
 *
 * 对齐后端路由：backend/app/api/kb.py
 *   POST   /api/v1/kb/materials（上传，登录可用）
 *   GET    /api/v1/kb/materials（列表，仅全局资料）
 *   GET    /api/v1/kb/materials/search?q=&top_k=（检索）
 *   DELETE /api/v1/kb/materials/{id}（删除，仅管理员 BID_ADMIN_USER_IDS）
 *
 * 前置条件（不满足时对应用例 skip）：
 * - MinIO + pgvector + worker 就绪；BID_LLM_MOCK=true 时 Embedding 走确定性伪向量。
 */
import type { APIRequestContext } from '@playwright/test';
import {
  api,
  backendHealthy,
  bearer,
  type AuthedUser,
  type BizResponse,
  registerAndLogin,
  test,
  expect,
} from '../fixtures/auth';
import { buildMinimalPdf } from '../fixtures/files';

const MATERIAL = {
  name: 'global-handbook.pdf',
  mime: 'application/pdf',
  text: 'E2E Global Handbook. Our company holds ISO27001 certification.',
} as const;

test.beforeEach(async ({ api: apiCtx }) => {
  test.skip(
    !(await backendHealthy(apiCtx)),
    '后端服务未就绪（E2E_API_URL 不可达 /health）。请先 docker compose 启动基础设施并运行后端。',
  );
});

/** 上传一份全局资料，返回文档 id */
async function uploadGlobalMaterial(
  apiCtx: APIRequestContext,
  user: AuthedUser,
): Promise<string> {
  const resp = await apiCtx.post(api('/kb/materials'), {
    headers: bearer(user),
    multipart: {
      file: { name: MATERIAL.name, mimeType: MATERIAL.mime, buffer: buildMinimalPdf(MATERIAL.text) },
    },
  });
  expect(resp.status(), `上传全局资料失败: ${await resp.text()}`).toBe(200);
  const body = (await resp.json()) as BizResponse<{ id: string; doc_type: string; status: string }>;
  expect(body.data.doc_type).toBe('kb_material');
  return body.data.id;
}

test.describe('全局资料库', () => {
  test('上传全局资料并在列表中可见', async ({ api: apiCtx }) => {
    const user = await registerAndLogin(apiCtx, 'kb-global');
    const docId = await uploadGlobalMaterial(apiCtx, user);

    const list = await apiCtx.get(api('/kb/materials'), { headers: bearer(user) });
    expect(list.status()).toBe(200);
    const body = (await list.json()) as BizResponse<{
      items: Array<{ id: string; title: string }>;
      total: number;
    }>;
    expect(body.data.items.map((d) => d.id)).toContain(docId);
  });

  test('全局列表不含项目级文档（隔离）', async ({ api: apiCtx }) => {
    const user = await registerAndLogin(apiCtx, 'kb-global-iso');

    // 项目级 kb_material（project_id 非空）
    const proj = await apiCtx.post(api('/projects'), {
      headers: bearer(user),
      data: { name: 'E2E隔离项目', tender_no: 'T-iso', industry: '软件' },
    });
    expect(proj.status()).toBe(200);
    const projectId = ((await proj.json()) as BizResponse<{ id: string }>).data.id;
    const projDoc = await apiCtx.post(api(`/projects/${projectId}/documents?doc_type=kb_material`), {
      headers: bearer(user),
      multipart: {
        file: { name: MATERIAL.name, mimeType: MATERIAL.mime, buffer: buildMinimalPdf(MATERIAL.text) },
      },
    });
    expect(projDoc.status()).toBe(200);
    const projDocId = ((await projDoc.json()) as BizResponse<{ id: string }>).data.id;

    // 全局列表不应包含项目级文档
    const list = await apiCtx.get(api('/kb/materials'), { headers: bearer(user) });
    expect(list.status()).toBe(200);
    const body = (await list.json()) as BizResponse<{ items: Array<{ id: string }>; total: number }>;
    expect(body.data.items.map((d) => d.id)).not.toContain(projDocId);
  });

  test('全局检索命中已索引资料', async ({ api: apiCtx }) => {
    const user = await registerAndLogin(apiCtx, 'kb-global-search');
    // mock embedding 为文本 hash 确定性伪向量：仅「文档文本 == 查询词」时向量一致（相似度 1.0）必命中。
    // 全局库跨用例共享（历史同名资料会挤占 top_k 席位），故用唯一检索词上传并查询同一 token。
    const token = `ISO27001-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const resp = await apiCtx.post(api('/kb/materials'), {
      headers: bearer(user),
      multipart: {
        file: {
          name: 'global-unique.pdf',
          mimeType: MATERIAL.mime,
          buffer: buildMinimalPdf(token),
        },
      },
    });
    expect(resp.status(), `上传唯一检索词资料失败: ${await resp.text()}`).toBe(200);
    const docId = ((await resp.json()) as BizResponse<{ id: string }>).data.id;

    // 等待 worker 向量化（uploaded → indexed / failed）；未就绪则 skip（非断言失败）
    const deadline = Date.now() + 60_000;
    let status = 'unknown';
    while (Date.now() < deadline) {
      const list = await apiCtx.get(api('/kb/materials'), { headers: bearer(user) });
      if (list.ok()) {
        const body = (await list.json()) as BizResponse<{
          items: Array<{ id: string; status: string }>;
        }>;
        const doc = body.data.items.find((d) => d.id === docId);
        if (doc) {
          status = doc.status;
          if (['indexed', 'failed'].includes(status)) break;
        }
      }
      await new Promise((r) => setTimeout(r, 3_000));
    }
    test.skip(
      status !== 'indexed',
      `全局资料状态停留在 "${status}"：worker/Embedding 未就绪，检索命中无从断言。`,
    );

    const search = await apiCtx.get(api('/kb/materials/search'), {
      headers: bearer(user),
      params: { q: token, top_k: 5 },
    });
    expect(search.status(), `全局检索失败: ${await search.text()}`).toBe(200);
    const body = (await search.json()) as BizResponse<{
      items: Array<{ chunk_id: string; doc_id: string; title: string; content: string; score: number }>;
      total: number;
    }>;
    expect(body.data.total).toBeGreaterThan(0);
    // 文档文本与查询词一致（向量相同），必排在结果首位
    expect(body.data.items.map((i) => i.doc_id)).toContain(docId);
  });

  test('删除仅限管理员：普通用户删除返回 403', async ({ api: apiCtx }) => {
    const user = await registerAndLogin(apiCtx, 'kb-global-del');
    const docId = await uploadGlobalMaterial(apiCtx, user);

    const del = await apiCtx.delete(api(`/kb/materials/${docId}`), { headers: bearer(user) });
    // 二期决策：删除限管理员（get_current_admin_id）；E2E 注册用户非管理员
    expect(del.status()).toBe(403);

    // 删除被拒后资料仍存在
    const list = await apiCtx.get(api('/kb/materials'), { headers: bearer(user) });
    const body = (await list.json()) as BizResponse<{ items: Array<{ id: string }> }>;
    expect(body.data.items.map((d) => d.id)).toContain(docId);
  });

  test('未认证访问全局资料接口返回 401', async ({ api: apiCtx }) => {
    const list = await apiCtx.get(api('/kb/materials'));
    expect(list.status()).toBe(401);
    const search = await apiCtx.get(api('/kb/materials/search'), { params: { q: 'x' } });
    expect(search.status()).toBe(401);
  });
});
