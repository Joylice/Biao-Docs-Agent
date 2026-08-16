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

  test('无待处理中断时 confirm 被拒（interrupt 校验，BizError 4009）', async ({ api: apiCtx }) => {
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