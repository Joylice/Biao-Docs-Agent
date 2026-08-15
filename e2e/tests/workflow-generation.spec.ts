/**
 * 场景 5 / E2E-04 / E2E-05 / E2E-06：方案生成闭环
 * 评分点确认(HITL) → 大纲确认(HITL) → 章节生成 → 审阅重写 → Word 导出。
 *
 * 对齐后端路由：backend/app/api/workflow.py
 *   POST /api/v1/projects/{pid}/workflow/start
 *   GET  /api/v1/projects/{pid}/workflow/status
 *   POST .../workflow/confirm-score-points | confirm-outline | rewrite-chapter
 *   GET  .../workflow/export
 *
 * 现状与限制（如实标注，不谎报）：
 * - workflow.py 多数端点为 TODO stub（返回固定 phase=init / 内存态），
 *   本 spec 断言"现有 API 契约"；待 LangGraph checkpointer 接入后升级为真实闭环断言。
 * - rewrite-chapter 走 review_service → LLM 调用：前置条件 BID_LLM_MOCK=true，
 *   llm_service.py 已引用 settings.llm_mock，需后端以 BID_LLM_MOCK=true 启动。
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
  expect,
} from '../fixtures/auth';

test.beforeEach(async ({ api: apiCtx }) => {
  test.skip(
    !(await backendHealthy(apiCtx)),
    '后端服务未就绪（E2E_API_URL 不可达 /health）。请先 docker compose 启动基础设施并运行后端。',
  );
});

test.describe('方案生成闭环', () => {
  test('启动工作流返回 workflow_id（E2E-04 触发）', async ({ api: apiCtx }) => {
    const user = await registerAndLogin(apiCtx, 'wf');
    const project = await createProject(apiCtx, user);

    const resp = await apiCtx.post(api(`/projects/${project.id}/workflow/start`), {
      headers: bearer(user),
    });
    expect(resp.status()).toBe(200);
    const body = (await resp.json()) as BizResponse<{
      workflow_id: string;
      status: string;
      phase: string;
    }>;
    expect(body.code).toBe(0);
    expect(body.data.workflow_id).toBeTruthy();
    expect(body.data.status).toBe('started');
  });

  test('HITL：确认评分点 → next_phase=outline；确认大纲 → next_phase=generate', async ({
    api: apiCtx,
  }) => {
    const user = await registerAndLogin(apiCtx, 'wf-hitl');
    const project = await createProject(apiCtx, user);

    const sp = await apiCtx.post(api(`/projects/${project.id}/workflow/confirm-score-points`), {
      headers: bearer(user),
    });
    expect(sp.status()).toBe(200);
    const spBody = (await sp.json()) as BizResponse<{ status: string; next_phase: string }>;
    expect(spBody.data.status).toBe('confirmed');
    expect(spBody.data.next_phase).toBe('outline');

    const outline = await apiCtx.post(api(`/projects/${project.id}/workflow/confirm-outline`), {
      headers: bearer(user),
    });
    expect(outline.status()).toBe(200);
    const outlineBody = (await outline.json()) as BizResponse<{
      status: string;
      next_phase: string;
    }>;
    expect(outlineBody.data.status).toBe('confirmed');
    expect(outlineBody.data.next_phase).toBe('generate');
  });

  test('工作流状态查询返回完整结构', async ({ api: apiCtx }) => {
    const user = await registerAndLogin(apiCtx, 'wf-status');
    const project = await createProject(apiCtx, user);

    const resp = await apiCtx.get(api(`/projects/${project.id}/workflow/status`), {
      headers: bearer(user),
    });
    expect(resp.status()).toBe(200);
    const body = (await resp.json()) as BizResponse<{
      phase: string;
      progress: number;
      score_points: unknown[];
      outline: unknown[];
      chapters: Record<string, unknown>;
      review_comments: unknown[];
      export_status: string;
    }>;
    expect(body.code).toBe(0);
    expect(typeof body.data.phase).toBe('string');
    expect(typeof body.data.progress).toBe('number');
    expect(Array.isArray(body.data.score_points)).toBe(true);
    expect(Array.isArray(body.data.outline)).toBe(true);
  });

  // E2E-04 完整流式生成、E2E-05 章节级审阅重写断言依赖：
  // 1) LangGraph checkpointer 持久化（workflow.py 现返回固定 stub 状态）
  // 2) BID_LLM_MOCK=true 且 llm_service 真正走 mock 分支
  // 待上述落地后，本用例改为断言：章节逐段生成 → 仅目标章内容变化 → 其余章不变。
  test('E2E-04/E2E-05 章节生成与审阅重写（依赖 LLM mock + 状态持久化）', async ({
    api: apiCtx,
  }) => {
    test.skip(
      !llmMockEnabled(),
      '前置条件：需后端以 BID_LLM_MOCK=true 启动（llm_service.py 已引用开关）；' +
        '另 workflow.py 章节生成为 TODO stub，断言条件未具备。',
    );

    const user = await registerAndLogin(apiCtx, 'wf-gen');
    const project = await createProject(apiCtx, user);
    await apiCtx.post(api(`/projects/${project.id}/workflow/start`), { headers: bearer(user) });

    // 审阅重写单章（chapter_no/comment 为查询参数，见 workflow.py rewrite_chapter 签名）
    const resp = await apiCtx.post(
      api(`/projects/${project.id}/workflow/rewrite-chapter?chapter_no=3&comment=补充实施方案细节`),
      { headers: bearer(user) },
    );
    expect(resp.status(), `章节重写失败: ${await resp.text()}`).toBe(200);
    const body = (await resp.json()) as BizResponse<{ chapter_no: string; content: string }>;
    expect(body.data.chapter_no).toBe('3');
    expect(body.data.content.length).toBeGreaterThan(0);
  });

  test('E2E-06 导出 Word（当前为 stub，断言契约）', async ({ api: apiCtx }) => {
    const user = await registerAndLogin(apiCtx, 'wf-export');
    const project = await createProject(apiCtx, user);

    const resp = await apiCtx.get(api(`/projects/${project.id}/workflow/export`), {
      headers: bearer(user),
    });
    expect(resp.status()).toBe(200);
    const body = (await resp.json()) as BizResponse<{ export_status: string }>;
    expect(body.code).toBe(0);
    // TODO: workflow.py export_document 尚未调用 export_to_word（返回 pending）。
    // 待导出落地后升级为：断言二进制下载 + 文档含目录与正文（python-docx 校验）。
    expect(body.data.export_status).toBeTruthy();
  });
});
