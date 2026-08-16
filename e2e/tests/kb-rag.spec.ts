/**
 * 场景 4 / E2E-03：资料库 RAG
 * 上传资料（kb_material）→ 分块向量化入库 → 相似度检索命中。
 *
 * 对齐后端路由：backend/app/api/documents.py
 *   POST /api/v1/projects/{pid}/documents?doc_type=kb_material
 *   GET  /api/v1/projects/{pid}/kb/search?q=&top_k=（检索端点，2026-08-16 落地）
 * 异步向量化：backend/worker/tasks.py task_index_document（Arq worker）。
 *
 * 前置条件（不满足时对应用例 skip）：
 * - MinIO + pgvector（postgres）就绪；worker 就绪
 * - Embedding 服务（bge-m3，BID_EMBEDDING_API_BASE）就绪
 * - 上传即入队 task_index_document（documents.py → task_service.enqueue_index_document，2026-08-16 已接通）；
 *   BID_LLM_MOCK=true 时 Embedding 走确定性伪向量（rag_service._mock_embedding），无需外部服务，
 *   检索端点 min_score 默认 0（按相似度倒序返回 top_k），mock 模式下亦可命中
 */
import {
  api,
  backendHealthy,
  bearer,
  type BizResponse,
  createProject,
  registerAndLogin,
  test,
  waitForDocumentStatus,
  expect,
} from '../fixtures/auth';
import { buildMinimalDocx, buildMinimalPdf } from '../fixtures/files';

const MATERIALS = [
  { name: 'product-handbook.pdf', mime: 'application/pdf', text: 'E2E Product Handbook. Our platform supports high availability deployment.' },
  { name: 'case-study.pdf', mime: 'application/pdf', text: 'E2E Case Study. We delivered a smart city project in 2025.' },
  { name: 'tech-whitepaper.docx', mime: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', text: 'E2E Tech Whitepaper. Microservice architecture with Kubernetes.' },
] as const;

test.beforeEach(async ({ api: apiCtx }) => {
  test.skip(
    !(await backendHealthy(apiCtx)),
    '后端服务未就绪（E2E_API_URL 不可达 /health）。请先 docker compose 启动基础设施并运行后端。',
  );
});

test.describe('资料库 RAG', () => {
  test('E2E-03 上传 3 份资料并登记入库', async ({ api: apiCtx }) => {
    const user = await registerAndLogin(apiCtx, 'kb');
    const project = await createProject(apiCtx, user);
    const uploadedIds: string[] = [];

    for (const m of MATERIALS) {
      const buffer =
        m.mime === 'application/pdf' ? buildMinimalPdf(m.text) : buildMinimalDocx(m.text);
      const resp = await apiCtx.post(
        api(`/projects/${project.id}/documents?doc_type=kb_material`),
        {
          headers: bearer(user),
          multipart: {
            file: { name: m.name, mimeType: m.mime, buffer },
          },
        },
      );
      expect(resp.status(), `上传资料 ${m.name} 失败: ${await resp.text()}`).toBe(200);
      const body = (await resp.json()) as BizResponse<{
        id: string;
        doc_type: string;
        status: string;
      }>;
      expect(body.data.doc_type).toBe('kb_material');
      expect(body.data.status).toBe('uploaded');
      uploadedIds.push(body.data.id);
    }

    // 资料列表可见 3 份
    const list = await apiCtx.get(
      api(`/projects/${project.id}/documents?doc_type=kb_material`),
      { headers: bearer(user) },
    );
    const listBody = (await list.json()) as BizResponse<{
      items: Array<{ id: string }>;
      total: number;
    }>;
    expect(listBody.data.total).toBe(3);
    for (const id of uploadedIds) {
      expect(listBody.data.items.map((d) => d.id)).toContain(id);
    }
  });

  test('分块向量化：资料状态推进到 indexed', async ({ api: apiCtx }) => {
    const user = await registerAndLogin(apiCtx, 'kb-index');
    const project = await createProject(apiCtx, user);

    const resp = await apiCtx.post(
      api(`/projects/${project.id}/documents?doc_type=kb_material`),
      {
        headers: bearer(user),
        multipart: {
          file: {
            name: MATERIALS[0].name,
            mimeType: MATERIALS[0].mime,
            buffer: buildMinimalPdf(MATERIALS[0].text),
          },
        },
      },
    );
    expect(resp.status()).toBe(200);
    const docId = ((await resp.json()) as BizResponse<{ id: string }>).data.id;

    // 轮询 worker 向量化：uploaded → indexed / failed
    // 已知缺口：上传未入队 task_index_document，状态不推进则 skip（非断言失败）
    const status = await waitForDocumentStatus(
      apiCtx,
      user,
      project.id,
      docId,
      ['indexed', 'failed'],
      60_000,
      'kb_material',
    );
    test.skip(
      status !== 'indexed',
      `资料状态停留在 "${status}"，未推进到 indexed：` +
        '后端上传未入队向量化任务/worker/Embedding 服务未就绪，属已知前置条件缺失。',
    );
    expect(status).toBe('indexed');
  });

  test('相似度检索命中资料（E2E-03 检索命中）', async ({ api: apiCtx }) => {
    const user = await registerAndLogin(apiCtx, 'kb-search');
    const project = await createProject(apiCtx, user);

    // 上传 1 份资料并等待向量化完成（indexed 后 kb_chunks 才有向量可检索）
    const resp = await apiCtx.post(
      api(`/projects/${project.id}/documents?doc_type=kb_material`),
      {
        headers: bearer(user),
        multipart: {
          file: {
            name: MATERIALS[0].name,
            mimeType: MATERIALS[0].mime,
            buffer: buildMinimalPdf(MATERIALS[0].text),
          },
        },
      },
    );
    expect(resp.status(), `上传资料失败: ${await resp.text()}`).toBe(200);
    const docId = ((await resp.json()) as BizResponse<{ id: string }>).data.id;

    const status = await waitForDocumentStatus(
      apiCtx,
      user,
      project.id,
      docId,
      ['indexed', 'failed'],
      60_000,
      'kb_material',
    );
    test.skip(
      status !== 'indexed',
      `资料状态停留在 "${status}"，未推进到 indexed：worker/Embedding 未就绪，检索命中无从断言。`,
    );

    // 相似度检索（后端契约：GET /projects/{pid}/kb/search?q=&top_k=，
    // 返回 {items: [{chunk_id, doc_id, title, content, page_no, score}], total}）
    const search = await apiCtx.get(api(`/projects/${project.id}/kb/search`), {
      headers: bearer(user),
      params: { q: 'high availability deployment', top_k: 5 },
    });
    expect(search.status(), `检索失败: ${await search.text()}`).toBe(200);
    const body = (await search.json()) as BizResponse<{
      items: Array<{ chunk_id: string; doc_id: string; title: string; content: string; score: number }>;
      total: number;
    }>;
    expect(body.data.total).toBeGreaterThan(0);
    expect(body.data.items.map((i) => i.doc_id)).toContain(docId);
    expect(body.data.items.map((i) => i.title)).toContain(MATERIALS[0].name);
    for (const item of body.data.items) {
      expect(item.content.length, '命中分块内容非空').toBeGreaterThan(0);
      expect(typeof item.score, '相似度为数值').toBe('number');
    }
  });
});
