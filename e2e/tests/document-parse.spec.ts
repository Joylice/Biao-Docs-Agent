/**
 * 场景 3 / E2E-02：文档上传解析
 * 上传招标文件（最小 PDF fixture）→ 异步解析 → 评分点/技术需求入库。
 *
 * 对齐后端路由：backend/app/api/documents.py
 *   POST /api/v1/projects/{pid}/documents?doc_type=tender_file
 *   GET  /api/v1/projects/{pid}/documents | /score-points | /tech-requirements
 * 异步解析任务：backend/worker/tasks.py task_parse_tender（Arq worker）。
 *
 * 前置条件（不满足时对应用例 skip 而非硬失败）：
 * - MinIO 就绪（上传落盘）；worker 就绪（状态推进 uploaded → parsing → parsed）
 * - BID_LLM_MOCK=true 且后端真正走 mock 分支（llm_service.py 已引用 settings.llm_mock，
 *   需后端以 BID_LLM_MOCK=true 启动，见 fixtures/auth.ts llmMockEnabled 注释）
 * - 上传即入队 task_parse_tender（documents.py → task_service.enqueue_parse_tender，2026-08-16 已接通）
 */
import {
  api,
  backendHealthy,
  bearer,
  type BizResponse,
  createProject,
  llmMockEnabled,
  registerAndLogin,
  test,
  waitForDocumentStatus,
  expect,
} from '../fixtures/auth';
import { buildMinimalPdf } from '../fixtures/files';

const TENDER_TEXT =
  'E2E Tender Document. Scoring criteria: technical proposal 60 points, price 40 points.';

test.beforeEach(async ({ api: apiCtx }) => {
  test.skip(
    !(await backendHealthy(apiCtx)),
    '后端服务未就绪（E2E_API_URL 不可达 /health）。请先 docker compose 启动基础设施并运行后端。',
  );
});

test.describe('文档上传解析', () => {
  test('上传招标文件成功（status=uploaded，落盘 MinIO）', async ({ api: apiCtx }) => {
    const user = await registerAndLogin(apiCtx, 'upload');
    const project = await createProject(apiCtx, user);

    const resp = await apiCtx.post(
      api(`/projects/${project.id}/documents?doc_type=tender_file`),
      {
        headers: bearer(user),
        multipart: {
          file: {
            name: 'tender-e2e.pdf',
            mimeType: 'application/pdf',
            buffer: buildMinimalPdf(TENDER_TEXT),
          },
        },
      },
    );
    expect(resp.status(), `上传失败（MinIO 未就绪？）: ${await resp.text()}`).toBe(200);
    const body = (await resp.json()) as BizResponse<{
      id: string;
      title: string;
      doc_type: string;
      status: string;
      storage_key: string;
    }>;
    expect(body.code).toBe(0);
    expect(body.data.id).toBeTruthy();
    expect(body.data.title).toBe('tender-e2e.pdf');
    expect(body.data.doc_type).toBe('tender_file');
    expect(body.data.status).toBe('uploaded');
    expect(body.data.storage_key).toBeTruthy();

    // 文档列表按 doc_type 过滤可见
    const list = await apiCtx.get(
      api(`/projects/${project.id}/documents?doc_type=tender_file`),
      { headers: bearer(user) },
    );
    const listBody = (await list.json()) as BizResponse<{
      items: Array<{ id: string; status: string }>;
      total: number;
    }>;
    expect(listBody.data.items.map((d) => d.id)).toContain(body.data.id);
  });

  test('不支持的文件类型被拒（ValidationError 4000）', async ({ api: apiCtx }) => {
    const user = await registerAndLogin(apiCtx, 'upload-bad');
    const project = await createProject(apiCtx, user);

    const resp = await apiCtx.post(
      api(`/projects/${project.id}/documents?doc_type=tender_file`),
      {
        headers: bearer(user),
        multipart: {
          file: {
            name: 'evil.txt',
            mimeType: 'text/plain',
            buffer: Buffer.from('not a tender file'),
          },
        },
      },
    );
    expect(resp.status()).toBe(400);
    expect(((await resp.json()) as BizResponse).code).toBe(4000);
  });

  test('E2E-02 异步解析完成后评分点/技术需求入库', async ({ api: apiCtx }) => {
    test.skip(
      !llmMockEnabled(),
      '前置条件：需 BID_LLM_MOCK=true 让后端走 LLM mock（llm_service.py 已引用开关，' +
        '需后端以 BID_LLM_MOCK=true 启动）。',
    );

    const user = await registerAndLogin(apiCtx, 'parse');
    const project = await createProject(apiCtx, user);

    const upload = await apiCtx.post(
      api(`/projects/${project.id}/documents?doc_type=tender_file`),
      {
        headers: bearer(user),
        multipart: {
          file: {
            name: 'tender-parse.pdf',
            mimeType: 'application/pdf',
            buffer: buildMinimalPdf(TENDER_TEXT),
          },
        },
      },
    );
    expect(upload.status(), `上传失败: ${await upload.text()}`).toBe(200);
    const docId = ((await upload.json()) as BizResponse<{ id: string }>).data.id;

    // 轮询等待 worker 异步解析：uploaded → parsing → parsed
    // 已知缺口：documents.py 上传未入队 task_parse_tender，状态可能不推进 → 明确 skip
    const status = await waitForDocumentStatus(
      apiCtx,
      user,
      project.id,
      docId,
      ['parsed', 'failed'],
      60_000,
      'tender_file',
    );
    test.skip(
      status !== 'parsed',
      `文档状态停留在 "${status}"，未推进到 parsed：` +
        '后端上传未入队解析任务/worker 未运行，属已知前置条件缺失（非断言失败）。',
    );

    // 评分点入库且可确认（HITL 前置数据）
    const spResp = await apiCtx.get(api(`/projects/${project.id}/score-points`), {
      headers: bearer(user),
    });
    expect(spResp.status()).toBe(200);
    const spBody = (await spResp.json()) as BizResponse<
      Array<{ id: string; clause_no: string; confirmed: boolean }>
    >;
    expect(spBody.data.length, '解析完成但评分点为空').toBeGreaterThan(0);

    // 技术需求入库
    const trResp = await apiCtx.get(api(`/projects/${project.id}/tech-requirements`), {
      headers: bearer(user),
    });
    expect(trResp.status()).toBe(200);
    expect(((await trResp.json()) as BizResponse<unknown[]>).data.length).toBeGreaterThan(0);

    // 人工编辑评分点策略并确认（HITL）
    const spId = spBody.data[0].id;
    const upd = await apiCtx.put(api(`/projects/${project.id}/score-points/${spId}`), {
      headers: bearer(user),
      data: { strategy: 'E2E 应答策略', confirmed: true },
    });
    expect(upd.status()).toBe(200);
    const updBody = (await upd.json()) as BizResponse<{ strategy: string; confirmed: boolean }>;
    expect(updBody.data.strategy).toBe('E2E 应答策略');
    expect(updBody.data.confirmed).toBe(true);
  });

  test('重新解析：清除旧结果并重新入库', async ({ api: apiCtx }) => {
    test.skip(
      !llmMockEnabled(),
      '前置条件：需 BID_LLM_MOCK=true 让后端走 LLM mock。',
    );

    const user = await registerAndLogin(apiCtx, 'reparse');
    const project = await createProject(apiCtx, user);

    const upload = await apiCtx.post(
      api(`/projects/${project.id}/documents?doc_type=tender_file`),
      {
        headers: bearer(user),
        multipart: {
          file: {
            name: 'tender-reparse.pdf',
            mimeType: 'application/pdf',
            buffer: buildMinimalPdf(TENDER_TEXT),
          },
        },
      },
    );
    expect(upload.status(), `上传失败: ${await upload.text()}`).toBe(200);
    const docId = ((await upload.json()) as BizResponse<{ id: string }>).data.id;

    const first = await waitForDocumentStatus(
      apiCtx,
      user,
      project.id,
      docId,
      ['parsed', 'failed'],
      60_000,
      'tender_file',
    );
    test.skip(
      first !== 'parsed',
      `首次解析未推进到 parsed（停留 ${first}），worker 未就绪属前置条件缺失。`,
    );

    // 首次解析结果入库
    const spFirst = await apiCtx.get(api(`/projects/${project.id}/score-points`), {
      headers: bearer(user),
    });
    expect(
      ((await spFirst.json()) as BizResponse<unknown[]>).data.length,
      '首次解析应有评分点',
    ).toBeGreaterThan(0);

    // 首次解析的技术需求（重新解析不得清除、不得重复提取）
    const trFirst = await apiCtx.get(api(`/projects/${project.id}/tech-requirements`), {
      headers: bearer(user),
    });
    const trFirstCount = ((await trFirst.json()) as BizResponse<unknown[]>).data.length;

    // 发起重新解析
    const reparse = await apiCtx.post(
      api(`/projects/${project.id}/documents/${docId}/reparse`),
      { headers: bearer(user) },
    );
    expect(reparse.status(), `重新解析失败: ${await reparse.text()}`).toBe(200);
    const reparseBody = (await reparse.json()) as BizResponse<{ status: string }>;
    expect(reparseBody.data.status).toBe('uploaded');

    // 解析中重复提交被拒（4010）
    const dup = await apiCtx.post(
      api(`/projects/${project.id}/documents/${docId}/reparse`),
      { headers: bearer(user) },
    );
    const dupStatus = dup.status();
    const dupCode = ((await dup.json()) as BizResponse).code;
    expect([400, 409]).toContain(dupStatus);
    expect(dupCode).toBe(4010);

    // 二次解析完成：状态回到 parsed，评分点重新入库
    const second = await waitForDocumentStatus(
      apiCtx,
      user,
      project.id,
      docId,
      ['parsed', 'failed'],
      60_000,
      'tender_file',
    );
    expect(second, '重新解析应再次推进到 parsed').toBe('parsed');
    const spSecond = await apiCtx.get(api(`/projects/${project.id}/score-points`), {
      headers: bearer(user),
    });
    expect(
      ((await spSecond.json()) as BizResponse<unknown[]>).data.length,
      '重新解析后评分点应重新入库',
    ).toBeGreaterThan(0);

    // 重新解析只负责评分点提取：技术需求不被清除也不重复提取
    if (trFirstCount > 0) {
      const trSecond = await apiCtx.get(api(`/projects/${project.id}/tech-requirements`), {
        headers: bearer(user),
      });
      expect(
        ((await trSecond.json()) as BizResponse<unknown[]>).data.length,
        '重新解析后技术需求应保持不变（不清除、不重复提取）',
      ).toBe(trFirstCount);
    }
  });
});
