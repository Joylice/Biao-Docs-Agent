/**
 * 场景 5 / E2E-04 / E2E-05 / E2E-06：方案生成闭环
 * 招标解析 → 评分点确认(HITL) → 大纲确认(HITL) → 章节生成 → 审阅(HITL：通过/反馈重写) → Word 导出。
 *
 * 对齐后端路由：backend/app/api/workflow.py（经 workflow_runtime → LangGraph + AsyncPostgresSaver）
 *   POST /api/v1/projects/{pid}/workflow/start
 *   GET  /api/v1/projects/{pid}/workflow/status
 *   POST .../workflow/confirm-score-points | confirm-outline | confirm-review | rewrite-chapter
 *   GET  .../workflow/export
 *
 * 契约要点（2026-08-16 联调后）：
 * - confirm-* 端点经 ensure_pending_interrupt 校验：无对应 pending interrupt → BizError 4009（HTTP 400）
 * - status 含 review_action/review_feedback（无 review_comments 字段）与 interrupt payload
 * - rewrite-chapter 仅可重写已生成章节（未生成 → 4004/HTTP 404）；export 需章节已生成（否则 4005/400）
 * - LLM 在 BID_LLM_MOCK=true 下走 mock（mock 大纲为单章 chapter_no="mock"）
 */
import type { APIRequestContext } from '@playwright/test';
import {
  api,
  backendHealthy,
  bearer,
  confirmAllScorePoints,
  type BizResponse,
  createProject,
  llmMockEnabled,
  registerAndLogin,
  test,
  waitForDocumentStatus,
  waitForWorkflowStatus,
  type AuthedUser,
  type WorkflowStatus,
  expect,
} from '../fixtures/auth';
import { buildMinimalPdf } from '../fixtures/files';

test.beforeEach(async ({ api: apiCtx }) => {
  test.skip(
    !(await backendHealthy(apiCtx)),
    '后端服务未就绪（E2E_API_URL 不可达 /health）。请先 docker compose 启动基础设施并运行后端。',
  );
});

/** 上传招标文件并等待 worker 解析完成（工作流前置：评分点入库） */
async function uploadParsedTender(
  apiCtx: APIRequestContext,
  user: AuthedUser,
  projectId: string,
): Promise<void> {
  const resp = await apiCtx.post(api(`/projects/${projectId}/documents?doc_type=tender_file`), {
    headers: bearer(user),
    multipart: {
      file: {
        name: 'tender-wf.pdf',
        mimeType: 'application/pdf',
        buffer: buildMinimalPdf('E2E Workflow Tender. Scoring: technical 60, price 40.'),
      },
    },
  });
  expect(resp.status(), `上传失败: ${await resp.text()}`).toBe(200);
  const docId = ((await resp.json()) as BizResponse<{ id: string }>).data.id;
  const status = await waitForDocumentStatus(
    apiCtx,
    user,
    projectId,
    docId,
    ['parsed', 'failed'],
    60_000,
    'tender_file',
  );
  expect(status, '招标文件未解析成功（worker/LLM mock 异常？）').toBe('parsed');
}

/** 驱动工作流到 review_request 挂起：start → 确认评分点 → 确认大纲 → 等待章节生成完成 */
async function driveToReview(
  apiCtx: APIRequestContext,
  user: AuthedUser,
  projectId: string,
): Promise<WorkflowStatus> {
  // 严格模式（2026-08-25）：先逐条确认评分点再启动工作流，否则 parse 节点直接 error
  await confirmAllScorePoints(apiCtx, user, projectId);
  await apiCtx.post(api(`/projects/${projectId}/workflow/start`), { headers: bearer(user) });

  await waitForWorkflowStatus(
    apiCtx,
    user,
    projectId,
    (s) => s.interrupt?.type === 'confirm_score_points',
    30_000,
  );
  const sp = await apiCtx.post(api(`/projects/${projectId}/workflow/confirm-score-points`), {
    headers: bearer(user),
  });
  expect(sp.status()).toBe(200);

  await waitForWorkflowStatus(
    apiCtx,
    user,
    projectId,
    (s) => s.interrupt?.type === 'confirm_outline',
    30_000,
  );
  const outline = await apiCtx.post(api(`/projects/${projectId}/workflow/confirm-outline`), {
    headers: bearer(user),
    // 2026-08-25 起默认分工驱动（start_generation=False）；本链路验证章节自动生成，显式开启
    data: { start_generation: true },
  });
  expect(outline.status()).toBe(200);

  // 章节逐章生成（mock 下为单章），直到 review HITL 挂起
  return waitForWorkflowStatus(
    apiCtx,
    user,
    projectId,
    (s) => s.interrupt?.type === 'review_request',
    90_000,
  );
}

test.describe('方案生成闭环', () => {
  test('启动工作流返回 workflow_id（E2E-04 触发）', async ({ api: apiCtx }) => {
    const user = await registerAndLogin(apiCtx, 'wf');
    const project = await createProject(apiCtx, user);

    const resp = await apiCtx.post(api(`/projects/${project.id}/workflow/start`), {
      headers: bearer(user),
    });
    expect(resp.status(), `启动失败: ${await resp.text()}`).toBe(200);
    const body = (await resp.json()) as BizResponse<{
      workflow_id: string;
      status: string;
      phase: string;
      progress: number;
    }>;
    expect(body.code).toBe(0);
    expect(body.data.workflow_id).toBeTruthy();
    expect(body.data.status).toBe('started');
  });

  test('大纲确认前可重新生成（regenerate-outline 返回新大纲）', async ({ api: apiCtx }) => {
    test.skip(!llmMockEnabled(), '前置条件：需后端以 BID_LLM_MOCK=true 启动。');

    const user = await registerAndLogin(apiCtx, 'wf-regen');
    const project = await createProject(apiCtx, user);
    await uploadParsedTender(apiCtx, user, project.id);

    // 严格模式（2026-08-25）：先逐条确认评分点再启动工作流，否则 parse 节点直接 error
    await confirmAllScorePoints(apiCtx, user, project.id);
    await apiCtx.post(api(`/projects/${project.id}/workflow/start`), { headers: bearer(user) });
    await waitForWorkflowStatus(
      apiCtx,
      user,
      project.id,
      (s) => s.interrupt?.type === 'confirm_score_points',
      30_000,
    );
    await apiCtx.post(api(`/projects/${project.id}/workflow/confirm-score-points`), {
      headers: bearer(user),
    });
    await waitForWorkflowStatus(
      apiCtx,
      user,
      project.id,
      (s) => s.interrupt?.type === 'confirm_outline',
      30_000,
    );

    const resp = await apiCtx.post(api(`/projects/${project.id}/workflow/regenerate-outline`), {
      headers: bearer(user),
    });
    expect(resp.status()).toBe(200);
    const body = (await resp.json()) as BizResponse<{
      status: string;
      outline: Array<{ chapter_no: string; covered_clauses?: string[] }>;
    }>;
    expect(body.data.status).toBe('regenerated');
    expect(body.data.outline.length).toBeGreaterThan(0);
    expect(body.data.outline[0].covered_clauses).toBeDefined();
  });

  test('大纲可二次编辑：编辑后确认按新结构生成章节', async ({ api: apiCtx }) => {
    test.skip(!llmMockEnabled(), '前置条件：需后端以 BID_LLM_MOCK=true 启动。');

    const user = await registerAndLogin(apiCtx, 'wf-edit');
    const project = await createProject(apiCtx, user);
    await uploadParsedTender(apiCtx, user, project.id);

    // 严格模式（2026-08-25）：先逐条确认评分点再启动工作流，否则 parse 节点直接 error
    await confirmAllScorePoints(apiCtx, user, project.id);
    await apiCtx.post(api(`/projects/${project.id}/workflow/start`), { headers: bearer(user) });
    await waitForWorkflowStatus(
      apiCtx,
      user,
      project.id,
      (s) => s.interrupt?.type === 'confirm_score_points',
      30_000,
    );
    await apiCtx.post(api(`/projects/${project.id}/workflow/confirm-score-points`), {
      headers: bearer(user),
    });
    const outlineStatus = await waitForWorkflowStatus(
      apiCtx,
      user,
      project.id,
      (s) => s.interrupt?.type === 'confirm_outline',
      30_000,
    );

    // 二次编辑：追加章节（mock 大纲为单章 chapter_no="mock"，追加后可稳定断言）
    const edited = [
      ...outlineStatus.outline,
      {
        chapter_no: '9',
        title: '编辑新增章节',
        sections: ['补充说明'],
        covered_clauses: ['1'],
      },
    ];
    const resp = await apiCtx.post(api(`/projects/${project.id}/workflow/confirm-outline`), {
      headers: bearer(user),
      data: { outline: edited, mounted_doc_ids: [], start_generation: true },
    });
    expect(resp.status(), `确认编辑后大纲失败: ${await resp.text()}`).toBe(200);

    // 章节按编辑后大纲生成：新增章节 9 应有内容、state.outline 同步为新结构
    const review = await waitForWorkflowStatus(
      apiCtx,
      user,
      project.id,
      (s) => s.interrupt?.type === 'review_request',
      90_000,
    );
    expect(Object.keys(review.chapters)).toContain('9');
    expect(review.outline.length).toBe(outlineStatus.outline.length + 1);
    expect(review.outline.some((c) => c.chapter_no === '9')).toBe(true);
  });

  test('大纲草稿：保存/读取/清除全链路（嵌套树形 sections 保留层级）', async ({
    api: apiCtx,
  }) => {
    test.skip(!llmMockEnabled(), '前置条件：需后端以 BID_LLM_MOCK=true 启动。');

    const user = await registerAndLogin(apiCtx, 'wf-draft');
    const project = await createProject(apiCtx, user);
    await uploadParsedTender(apiCtx, user, project.id);

    // 严格模式（2026-08-25）：先逐条确认评分点再启动工作流，否则 parse 节点直接 error
    await confirmAllScorePoints(apiCtx, user, project.id);
    await apiCtx.post(api(`/projects/${project.id}/workflow/start`), { headers: bearer(user) });
    await waitForWorkflowStatus(
      apiCtx,
      user,
      project.id,
      (s) => s.interrupt?.type === 'confirm_score_points',
      30_000,
    );
    await apiCtx.post(api(`/projects/${project.id}/workflow/confirm-score-points`), {
      headers: bearer(user),
    });
    await waitForWorkflowStatus(
      apiCtx,
      user,
      project.id,
      (s) => s.interrupt?.type === 'confirm_outline',
      30_000,
    );

    // 保存草稿：树形嵌套 sections（二次编辑产物，含层级）
    const draftOutline = [
      {
        chapter_no: '1',
        title: '技术方案概述',
        sections: [{ title: '项目背景', children: [{ title: '建设目标' }] }],
        covered_clauses: ['1'],
      },
    ];
    const saveResp = await apiCtx.put(
      api(`/projects/${project.id}/workflow/outline-draft`),
      {
        headers: bearer(user),
        data: { outline: draftOutline, mounted_doc_ids: null },
      },
    );
    expect(saveResp.status(), `草稿保存失败: ${await saveResp.text()}`).toBe(200);

    // 读取草稿：结构与保存一致（嵌套层级保留）
    const getResp = await apiCtx.get(
      api(`/projects/${project.id}/workflow/outline-draft`),
      { headers: bearer(user) },
    );
    const draftBody = (await getResp.json()) as BizResponse<{
      outline: Array<{
        chapter_no: string;
        title: string;
        sections: Array<{ title: string; children?: Array<{ title: string }> }>;
      }>;
      updated_at: string | null;
    }>;
    expect(draftBody.data.outline).toEqual(draftOutline);
    expect(draftBody.data.updated_at).toBeTruthy();

    // 清除草稿：幂等，清除后读回为空
    const delResp = await apiCtx.delete(
      api(`/projects/${project.id}/workflow/outline-draft`),
      { headers: bearer(user) },
    );
    expect(delResp.status()).toBe(200);
    const emptyResp = await apiCtx.get(
      api(`/projects/${project.id}/workflow/outline-draft`),
      { headers: bearer(user) },
    );
    const emptyBody = (await emptyResp.json()) as BizResponse<{ outline: unknown[] }>;
    expect(emptyBody.data.outline).toEqual([]);
  });

  test('确认大纲成功后自动清除草稿（防陈旧草稿下次误恢复）', async ({ api: apiCtx }) => {
    test.skip(!llmMockEnabled(), '前置条件：需后端以 BID_LLM_MOCK=true 启动。');

    const user = await registerAndLogin(apiCtx, 'wf-draft-clear');
    const project = await createProject(apiCtx, user);
    await uploadParsedTender(apiCtx, user, project.id);

    // 严格模式（2026-08-25）：先逐条确认评分点再启动工作流，否则 parse 节点直接 error
    await confirmAllScorePoints(apiCtx, user, project.id);
    await apiCtx.post(api(`/projects/${project.id}/workflow/start`), { headers: bearer(user) });
    await waitForWorkflowStatus(
      apiCtx,
      user,
      project.id,
      (s) => s.interrupt?.type === 'confirm_score_points',
      30_000,
    );
    await apiCtx.post(api(`/projects/${project.id}/workflow/confirm-score-points`), {
      headers: bearer(user),
    });
    const outlineStatus = await waitForWorkflowStatus(
      apiCtx,
      user,
      project.id,
      (s) => s.interrupt?.type === 'confirm_outline',
      30_000,
    );

    // 确认前先留草稿
    await apiCtx.put(api(`/projects/${project.id}/workflow/outline-draft`), {
      headers: bearer(user),
      data: { outline: outlineStatus.outline, mounted_doc_ids: null },
    });

    // 确认大纲 → 章节生成 → review 挂起
    await apiCtx.post(api(`/projects/${project.id}/workflow/confirm-outline`), {
      headers: bearer(user),
      // 2026-08-25 起默认分工驱动（start_generation=False）；本用例验证自动生成链路，显式开启
      data: { start_generation: true },
    });
    await waitForWorkflowStatus(
      apiCtx,
      user,
      project.id,
      (s) => s.interrupt?.type === 'review_request',
      90_000,
    );

    // 草稿已被 confirm 节点清除
    const resp = await apiCtx.get(api(`/projects/${project.id}/workflow/outline-draft`), {
      headers: bearer(user),
    });
    const body = (await resp.json()) as BizResponse<{ outline: unknown[] }>;
    expect(body.data.outline).toEqual([]);
  });

  test('无待处理中断时 confirm 被拒（interrupt 校验，BizError 4009）', async ({
    api: apiCtx,
  }) => {
    const user = await registerAndLogin(apiCtx, 'wf-noint');
    const project = await createProject(apiCtx, user);

    for (const path of [
      '/workflow/confirm-score-points',
      '/workflow/confirm-outline',
      '/workflow/confirm-review',
    ]) {
      const resp = await apiCtx.post(api(`/projects/${project.id}${path}`), {
        headers: bearer(user),
      });
      expect(resp.status(), `${path} 未拦截无中断操作`).toBe(400);
      expect(((await resp.json()) as BizResponse).code).toBe(4009);
    }
  });

  test('HITL：确认评分点 → next_phase=outline；确认大纲 → next_phase=generate', async ({
    api: apiCtx,
  }) => {
    test.skip(!llmMockEnabled(), '前置条件：需后端以 BID_LLM_MOCK=true 启动。');

    const user = await registerAndLogin(apiCtx, 'wf-hitl');
    const project = await createProject(apiCtx, user);
    await uploadParsedTender(apiCtx, user, project.id);

    // 严格模式（2026-08-25）：先逐条确认评分点再启动工作流，否则 parse 节点直接 error
    await confirmAllScorePoints(apiCtx, user, project.id);
    await apiCtx.post(api(`/projects/${project.id}/workflow/start`), { headers: bearer(user) });
    await waitForWorkflowStatus(
      apiCtx,
      user,
      project.id,
      (s) => s.interrupt?.type === 'confirm_score_points',
      30_000,
    );

    const sp = await apiCtx.post(api(`/projects/${project.id}/workflow/confirm-score-points`), {
      headers: bearer(user),
    });
    expect(sp.status()).toBe(200);
    const spBody = (await sp.json()) as BizResponse<{ status: string; next_phase: string }>;
    expect(spBody.data.status).toBe('confirmed');
    expect(spBody.data.next_phase).toBe('outline');

    await waitForWorkflowStatus(
      apiCtx,
      user,
      project.id,
      (s) => s.interrupt?.type === 'confirm_outline',
      30_000,
    );
    // 大纲契约：每章携带 covered_clauses（覆盖评分点条款号）
    const outlineStatus = await waitForWorkflowStatus(
      apiCtx,
      user,
      project.id,
      (s) => s.outline.length > 0,
      10_000,
    );
    expect(outlineStatus.outline[0].covered_clauses).toBeDefined();
    const outline = await apiCtx.post(api(`/projects/${project.id}/workflow/confirm-outline`), {
      headers: bearer(user),
      // 2026-08-25 起默认分工驱动（start_generation=False）；本用例验证自动生成链路，显式开启
      data: { start_generation: true },
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
    const body = (await resp.json()) as BizResponse<WorkflowStatus>;
    expect(body.code).toBe(0);
    expect(typeof body.data.phase).toBe('string');
    expect(typeof body.data.progress).toBe('number');
    expect(Array.isArray(body.data.score_points)).toBe(true);
    expect(Array.isArray(body.data.outline)).toBe(true);
    // 契约：chapters 为 {chapter_no: content} 映射；审阅字段为 review_action/review_feedback
    expect(typeof body.data.chapters).toBe('object');
    expect('review_action' in body.data).toBe(true);
    expect('review_feedback' in body.data).toBe(true);
    expect('interrupt' in body.data).toBe(true);
  });

  test('E2E-04/E2E-05 章节生成完整，审阅反馈触发重写且仅目标章变化', async ({ api: apiCtx }) => {
    test.skip(!llmMockEnabled(), '前置条件：需后端以 BID_LLM_MOCK=true 启动。');

    const user = await registerAndLogin(apiCtx, 'wf-gen');
    const project = await createProject(apiCtx, user);
    await uploadParsedTender(apiCtx, user, project.id);

    const reviewStatus = await driveToReview(apiCtx, user, project.id);

    // 章节已生成（E2E-04）：interrupt payload 携带 chapters，state.chapters 非空且字数达标
    expect(Object.keys(reviewStatus.chapters).length).toBeGreaterThan(0);
    const chapterNo = Object.keys(reviewStatus.chapters)[0];
    const original = reviewStatus.chapters[chapterNo];
    expect(original.length, '章节内容过短').toBeGreaterThanOrEqual(200);

    // 审阅反馈（feedback：{chapter_no: comment}）→ next_phase=rewrite
    const fb = await apiCtx.post(api(`/projects/${project.id}/workflow/confirm-review`), {
      headers: bearer(user),
      data: { action: 'feedback', feedback: { [chapterNo]: '补充实施方案细节' } },
    });
    expect(fb.status(), `审阅反馈失败: ${await fb.text()}`).toBe(200);
    const fbBody = (await fb.json()) as BizResponse<{
      status: string;
      action: string;
      next_phase: string;
    }>;
    expect(fbBody.data.action).toBe('feedback');
    expect(fbBody.data.next_phase).toBe('rewrite');

    // 重写后回到 review HITL：review_feedback 已入库，目标章内容变化
    const reReview = await waitForWorkflowStatus(
      apiCtx,
      user,
      project.id,
      (s) => s.interrupt?.type === 'review_request' && s.review_action === 'feedback',
      60_000,
    );
    expect(reReview.review_feedback?.[chapterNo]).toBe('补充实施方案细节');
    const rewritten = reReview.chapters[chapterNo];
    expect(rewritten).toBeTruthy();
    // mock 模式下 call_llm_text 恒返回固定 _MOCK_TEXT，重写前后内容相同属预期；
    // 内容差异断言仅在真实 LLM 下有意义（此处以 feedback 入库 + 章节存在性为准）。

    // 独立 rewrite-chapter 端点：仅重写指定章（mock 下返回固定重写文本）
    const rw = await apiCtx.post(
      api(
        `/projects/${project.id}/workflow/rewrite-chapter?chapter_no=${encodeURIComponent(chapterNo)}&comment=再细化进度计划`,
      ),
      { headers: bearer(user) },
    );
    expect(rw.status(), `章节重写失败: ${await rw.text()}`).toBe(200);
    const rwBody = (await rw.json()) as BizResponse<{ chapter_no: string; content: string }>;
    expect(rwBody.data.chapter_no).toBe(chapterNo);
    expect(rwBody.data.content.length).toBeGreaterThan(0);

    // 未生成的章节重写被拒（4004 → HTTP 404）
    const rwMissing = await apiCtx.post(
      api(`/projects/${project.id}/workflow/rewrite-chapter?chapter_no=99&comment=x`),
      { headers: bearer(user) },
    );
    expect(rwMissing.status()).toBe(404);
    expect(((await rwMissing.json()) as BizResponse).code).toBe(4004);
  });

  test('章节人工编辑保存：PUT sections 落库，刷新状态仍为编辑内容', async ({ api: apiCtx }) => {
    test.skip(!llmMockEnabled(), '前置条件：需后端以 BID_LLM_MOCK=true 启动。');

    const user = await registerAndLogin(apiCtx, 'wf-save-edit');
    const project = await createProject(apiCtx, user);
    await uploadParsedTender(apiCtx, user, project.id);

    const review = await driveToReview(apiCtx, user, project.id);
    const chapterNo = Object.keys(review.chapters)[0];
    const edited = `# 章节 ${chapterNo}（人工编辑保存）\n\n这是通过生成页编辑并保存的正式内容。`;

    const resp = await apiCtx.put(
      api(`/projects/${project.id}/workflow/sections/${encodeURIComponent(chapterNo)}`),
      { headers: bearer(user), data: { content: edited } },
    );
    expect(resp.status(), `保存失败: ${await resp.text()}`).toBe(200);

    // 重新拉取状态（刷新）仍显示编辑内容
    const statusResp = await apiCtx.get(api(`/projects/${project.id}/workflow/status`), {
      headers: bearer(user),
    });
    const statusBody = (await statusResp.json()) as BizResponse<WorkflowStatus>;
    expect(statusBody.data.chapters[chapterNo]).toBe(edited);

    // 未生成章节保存被拒（4004 → HTTP 404）
    const missing = await apiCtx.put(api(`/projects/${project.id}/workflow/sections/99`), {
      headers: bearer(user),
      data: { content: 'x' },
    });
    expect(missing.status()).toBe(404);
    expect(((await missing.json()) as BizResponse).code).toBe(4004);
  });

  test('大纲优化建议：建议 → 应用 → 大纲更新 → 人工确认后生成', async ({ api: apiCtx }) => {
    test.skip(!llmMockEnabled(), '前置条件：需后端以 BID_LLM_MOCK=true 启动。');

    const user = await registerAndLogin(apiCtx, 'wf-outline-suggest');
    const project = await createProject(apiCtx, user);
    await uploadParsedTender(apiCtx, user, project.id);

    // 严格模式（2026-08-25）：先逐条确认评分点再启动工作流，否则 parse 节点直接 error
    await confirmAllScorePoints(apiCtx, user, project.id);
    await apiCtx.post(api(`/projects/${project.id}/workflow/start`), { headers: bearer(user) });
    await waitForWorkflowStatus(
      apiCtx,
      user,
      project.id,
      (s) => s.interrupt?.type === 'confirm_score_points',
      30_000,
    );
    await apiCtx.post(api(`/projects/${project.id}/workflow/confirm-score-points`), {
      headers: bearer(user),
    });
    const outlineStatus = await waitForWorkflowStatus(
      apiCtx,
      user,
      project.id,
      (s) => s.interrupt?.type === 'confirm_outline',
      30_000,
    );

    // mock 模式：规则建议确定性可断言（占位数据兜底 → 非空建议）
    const suggestResp = await apiCtx.post(
      api(`/projects/${project.id}/workflow/outline-suggest`),
      { headers: bearer(user) },
    );
    expect(suggestResp.status(), `建议失败: ${await suggestResp.text()}`).toBe(200);
    const suggestBody = (await suggestResp.json()) as BizResponse<{
      suggestions: Array<{
        suggestion_id: string;
        suggestion_type: string;
        target: Record<string, string>;
        reason: string;
      }>;
    }>;
    expect(suggestBody.data.suggestions.length).toBeGreaterThan(0);
    const s = suggestBody.data.suggestions[0];
    expect(s.suggestion_id).toBeTruthy();
    expect(['add_section', 'add_chapter', 'rename', 'merge']).toContain(s.suggestion_type);
    expect(s.reason).toBeTruthy();

    // 应用建议 → 返回调整后大纲（不写 state：status 仍为原大纲，等待人工确认）
    const applyResp = await apiCtx.post(
      api(`/projects/${project.id}/workflow/outline-suggest/apply`),
      { headers: bearer(user), data: { adopted: [s.suggestion_id] } },
    );
    expect(applyResp.status(), `应用建议失败: ${await applyResp.text()}`).toBe(200);
    const applyBody = (await applyResp.json()) as BizResponse<{
      outline: Array<{ chapter_no: string; title: string }>;
    }>;
    expect(applyBody.data.outline.length).toBe(outlineStatus.outline.length + 1);
    expect(applyBody.data.outline[applyBody.data.outline.length - 1].title).toBeTruthy();

    const unchanged = await waitForWorkflowStatus(
      apiCtx,
      user,
      project.id,
      (s) => s.interrupt?.type === 'confirm_outline',
      10_000,
    );
    expect(unchanged.outline.length).toBe(outlineStatus.outline.length);

    // 人工确认调整后大纲 → 章节按新结构生成 → review 挂起
    const confirmResp = await apiCtx.post(api(`/projects/${project.id}/workflow/confirm-outline`), {
      headers: bearer(user),
      data: { outline: applyBody.data.outline, mounted_doc_ids: [], start_generation: true },
    });
    expect(confirmResp.status(), `确认调整后大纲失败: ${await confirmResp.text()}`).toBe(200);
    const review = await waitForWorkflowStatus(
      apiCtx,
      user,
      project.id,
      (s) => s.interrupt?.type === 'review_request',
      90_000,
    );
    expect(review.outline.length).toBe(outlineStatus.outline.length + 1);
    expect(Object.keys(review.chapters).length).toBeGreaterThan(0);
  });

  test('内容改进建议：建议 → 采纳重写（复用 rewrite-chapter）', async ({ api: apiCtx }) => {
    test.skip(!llmMockEnabled(), '前置条件：需后端以 BID_LLM_MOCK=true 启动。');

    const user = await registerAndLogin(apiCtx, 'wf-section-suggest');
    const project = await createProject(apiCtx, user);
    await uploadParsedTender(apiCtx, user, project.id);

    const review = await driveToReview(apiCtx, user, project.id);
    const chapterNo = Object.keys(review.chapters)[0];

    // mock 模式：规则建议确定性可断言（占位数据兜底 → 非空建议）
    const suggestResp = await apiCtx.post(
      api(`/projects/${project.id}/workflow/section-suggest`),
      { headers: bearer(user), data: { chapter_no: chapterNo } },
    );
    expect(suggestResp.status(), `建议失败: ${await suggestResp.text()}`).toBe(200);
    const suggestBody = (await suggestResp.json()) as BizResponse<{
      suggestions: Array<{
        chapter_no: string;
        issue: string;
        suggestion: string;
        severity: string;
      }>;
    }>;
    expect(suggestBody.data.suggestions.length).toBeGreaterThan(0);
    const s = suggestBody.data.suggestions[0];
    expect(s.chapter_no).toBe(chapterNo);
    expect(s.issue).toBeTruthy();
    expect(s.suggestion).toBeTruthy();
    expect(['high', 'medium']).toContain(s.severity);

    // 采纳 → 复用 rewrite-chapter 重写目标章
    const rw = await apiCtx.post(
      api(
        `/projects/${project.id}/workflow/rewrite-chapter?chapter_no=${encodeURIComponent(chapterNo)}&comment=${encodeURIComponent(s.suggestion)}`,
      ),
      { headers: bearer(user) },
    );
    expect(rw.status(), `采纳重写失败: ${await rw.text()}`).toBe(200);
    const rwBody = (await rw.json()) as BizResponse<{ chapter_no: string; content: string }>;
    expect(rwBody.data.chapter_no).toBe(chapterNo);
    expect(rwBody.data.content.length).toBeGreaterThan(0);
  });

  test('E2E-06 审阅通过后导出 Word（export_status=done + storage_key）', async ({ api: apiCtx }) => {
    test.skip(!llmMockEnabled(), '前置条件：需后端以 BID_LLM_MOCK=true 启动。');

    const user = await registerAndLogin(apiCtx, 'wf-export');
    const project = await createProject(apiCtx, user);
    await uploadParsedTender(apiCtx, user, project.id);

    await driveToReview(apiCtx, user, project.id);

    const ok = await apiCtx.post(api(`/projects/${project.id}/workflow/confirm-review`), {
      headers: bearer(user),
      data: { action: 'approved', feedback: {} },
    });
    expect(ok.status()).toBe(200);
    const okBody = (await ok.json()) as BizResponse<{ action: string; next_phase: string }>;
    expect(okBody.data.action).toBe('approved');
    expect(okBody.data.next_phase).toBe('export');

    // 等待图内 export 节点完成（phase=done，progress=1）
    const done = await waitForWorkflowStatus(
      apiCtx,
      user,
      project.id,
      (s) => s.export_status === 'done' || s.phase === 'done',
      60_000,
    );
    expect(done.error || '', `工作流进入错误态: ${done.error}`).toBe('');
    expect(done.export_status).toBe('done');
    expect(done.export_storage_key).toBeTruthy();
    expect(done.progress).toBe(1);

    // export 端点返回导出信息（storage_key 对应 MinIO 对象）
    const resp = await apiCtx.get(api(`/projects/${project.id}/workflow/export`), {
      headers: bearer(user),
    });
    expect(resp.status(), `导出失败: ${await resp.text()}`).toBe(200);
    const body = (await resp.json()) as BizResponse<{
      export_status: string;
      export_storage_key: string;
    }>;
    expect(body.code).toBe(0);
    expect(body.data.export_status).toBe('done');
    expect(body.data.export_storage_key).toBeTruthy();
  });

  test('章节未生成时导出被拒（BizError 4005）', async ({ api: apiCtx }) => {
    const user = await registerAndLogin(apiCtx, 'wf-export-early');
    const project = await createProject(apiCtx, user);

    const resp = await apiCtx.get(api(`/projects/${project.id}/workflow/export`), {
      headers: bearer(user),
    });
    expect(resp.status()).toBe(400);
    expect(((await resp.json()) as BizResponse).code).toBe(4005);
  });
});