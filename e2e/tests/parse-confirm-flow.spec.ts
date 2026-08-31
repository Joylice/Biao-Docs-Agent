/**
 * UI 全链路 HITL：招标解析页（评分点展示）→ 确认并生成大纲 → 跳转方案生成页
 * → 大纲就绪 → 开始生成 → 生成完成进入审阅。
 *
 * 覆盖前端缺陷修复（2026-08-16）：
 * - 「确认并生成大纲」自动启动工作流并轮询等待 confirm_score_points interrupt
 *   （此前工作流未启动直接调 confirm-score-points 报 4009）
 * - 生成页对「评分点未确认 / 大纲生成中 / 大纲待确认」三态分别呈现
 *
 * 前置条件：BID_LLM_MOCK=true（后端走 LLM mock，解析/大纲/生成为秒级）；
 * 前端可访问（E2E_BASE_URL），不满足时 skip。
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
  expect,
  type AuthedUser,
} from '../fixtures/auth';
import { buildMinimalPdf } from '../fixtures/files';

/** 上传招标文件并等待解析完成（评分点入库），与 workflow-generation.spec 同构 */
async function uploadParsedTender(
  apiCtx: APIRequestContext,
  user: AuthedUser,
  projectId: string,
): Promise<void> {
  const resp = await apiCtx.post(api(`/projects/${projectId}/documents?doc_type=tender_file`), {
    headers: bearer(user),
    multipart: {
      file: {
        name: 'tender-ui-hitl.pdf',
        mimeType: 'application/pdf',
        buffer: buildMinimalPdf('E2E UI Tender. Scoring: technical 60, price 40.'),
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

test.beforeEach(async ({ api: apiCtx }) => {
  test.skip(
    !(await backendHealthy(apiCtx)),
    '后端服务未就绪（E2E_API_URL 不可达 /health）。请先 docker compose 启动基础设施并运行后端。',
  );
});

test.describe('UI：招标解析 → 确认评分点 → 大纲 → 生成', () => {
  test('解析页确认评分点自动启动工作流，生成页大纲就绪后一键生成', async ({
    api: apiCtx,
    page,
  }) => {
    test.skip(!llmMockEnabled(), '前置条件：需后端以 BID_LLM_MOCK=true 启动。');

    const user = await registerAndLogin(apiCtx, 'ui-hitl');
    const project = await createProject(apiCtx, user);
    await uploadParsedTender(apiCtx, user, project.id);

    // 前端未启动时优雅跳过
    try {
      await page.goto('/login', { timeout: 10_000 });
    } catch {
      test.skip(true, '前端未就绪（E2E_BASE_URL 不可达），跳过 UI 断言。');
      return;
    }

    // 注入 token 直达解析页（路由守卫读 localStorage access_token）
    await page.addInitScript((token) => {
      localStorage.setItem('access_token', token);
    }, user.accessToken);
    await page.goto(`/projects/${project.id}/parse`);

    // 1. 解析页展示智能解析的评分点（内嵌确认页；按钮名为「生成大纲」，2026-08-25 起确认后进入分工驱动）
    await expect(page.getByRole('button', { name: '生成大纲' })).toBeVisible({
      timeout: 30_000,
    });

    // 1.1 勾选首条评分点确认（严格模式：canGenerate = confirmedCount > 0；排除测量行）
    const firstScoreRow = page.locator('.ant-table-tbody tr.ant-table-row').first();
    await expect(firstScoreRow).toBeVisible({ timeout: 30_000 });
    await firstScoreRow.locator('.ant-checkbox-input').last().check();

    // 2. 确认：前端自动 start workflow → 等待 interrupt → confirm-score-points
    await page.getByRole('button', { name: '生成大纲' }).click();

    // 3. 跳转方案生成页，大纲生成完成后出现「确认大纲」主按钮（mock 秒级；
    //    确认态底部「开始生成」已收敛为大纲卡「确认大纲」单一入口）
    await expect(page).toHaveURL(/\/generate$/, { timeout: 60_000 });
    await expect(page.getByRole('button', { name: '确认大纲' })).toBeVisible({
      timeout: 60_000,
    });

    // 4. 确认大纲（confirm-outline，2026-08-25 起默认分工驱动）→ 生成页出现「前往分工编制」引导
    await page.getByRole('button', { name: '确认大纲' }).click();
    await expect(page.getByText('大纲已确认，请前往分工页进行章节编制')).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByRole('button', { name: '前往分工编制' })).toBeVisible();
  });

  test('大纲编辑草稿：树形编辑后刷新可恢复（防抖保存 + 恢复弹窗）', async ({
    api: apiCtx,
    page,
  }) => {
    test.skip(!llmMockEnabled(), '前置条件：需后端以 BID_LLM_MOCK=true 启动。');

    const user = await registerAndLogin(apiCtx, 'ui-draft');
    const project = await createProject(apiCtx, user);
    await uploadParsedTender(apiCtx, user, project.id);

    // API 驱动工作流到 confirm_outline（大纲编辑态）
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

    try {
      await page.goto('/login', { timeout: 10_000 });
    } catch {
      test.skip(true, '前端未就绪（E2E_BASE_URL 不可达），跳过 UI 断言。');
      return;
    }
    await page.addInitScript((token) => {
      localStorage.setItem('access_token', token);
    }, user.accessToken);
    await page.goto(`/projects/${project.id}/generate`);

    // 1. 大纲编辑卡就绪（confirm_outline 态仅编辑卡、无左侧 sider；mock 大纲单章 title="mock"）
    await expect(page.getByText('大纲编辑')).toBeVisible({ timeout: 30_000 });
    await expect(page.getByPlaceholder('章节标题').first()).toHaveValue('mock', { timeout: 30_000 });

    // 2. 树形编辑：改章节标题 + 添加子节并输入标题
    await page.getByPlaceholder('章节标题').first().fill('定制章节标题');
    await page.getByRole('button', { name: '添加子节' }).first().click();
    await page.getByPlaceholder('子节标题').first().fill('定制子节标题');

    // 3. 等待防抖自动保存（2s 无操作后落库）
    await expect
      .poll(
        async () => {
          const resp = await apiCtx.get(api(`/projects/${project.id}/workflow/outline-draft`), {
            headers: bearer(user),
          });
          const body = (await resp.json()) as BizResponse<{
            outline: Array<{ title: string; sections?: Array<{ title: string }> }>;
          }>;
          return body.data.outline?.[0]?.title;
        },
        { timeout: 15_000 },
      )
      .toBe('定制章节标题');

    // 4. 刷新页面：进入编辑态检测到草稿 → 弹出恢复确认
    await page.reload();
    await expect(page.getByText('恢复编辑草稿')).toBeVisible({ timeout: 30_000 });

    // 5. 恢复草稿：标题与子节均还原
    await page.getByRole('button', { name: '恢复草稿' }).click();
    await expect(page.getByPlaceholder('章节标题').first()).toHaveValue('定制章节标题');
    await expect(page.getByPlaceholder('子节标题').first()).toHaveValue('定制子节标题');

    // 清理：删除草稿（幂等），避免遗留数据
    await apiCtx.delete(api(`/projects/${project.id}/workflow/outline-draft`), {
      headers: bearer(user),
    });
  });

  test('生成页未确认评分点时引导回招标解析页', async ({ api: apiCtx, page }) => {
    test.skip(!llmMockEnabled(), '前置条件：需后端以 BID_LLM_MOCK=true 启动。');

    const user = await registerAndLogin(apiCtx, 'ui-hitl-guard');
    const project = await createProject(apiCtx, user);
    // 不上传招标文件：工作流未启动（phase=init）

    try {
      await page.goto('/login', { timeout: 10_000 });
    } catch {
      test.skip(true, '前端未就绪（E2E_BASE_URL 不可达），跳过 UI 断言。');
      return;
    }

    await page.addInitScript((token) => {
      localStorage.setItem('access_token', token);
    }, user.accessToken);
    await page.goto(`/projects/${project.id}/generate`);

    // phase=init → 引导回招标解析页（而非误显示「开始生成」触发 4009）
    await expect(page.getByRole('button', { name: '前往招标解析' })).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByText('尚未确认评分点')).toBeVisible();
  });

  test('工作流已推进到审阅阶段时，解析页确认按钮给出引导而非空转', async ({
    api: apiCtx,
    page,
  }) => {
    test.skip(!llmMockEnabled(), '前置条件：需后端以 BID_LLM_MOCK=true 启动。');

    const user = await registerAndLogin(apiCtx, 'ui-hitl-late');
    const project = await createProject(apiCtx, user);
    await uploadParsedTender(apiCtx, user, project.id);

    // API 驱动工作流到 review_request（章节全部生成后挂起审阅）
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

    try {
      await page.goto('/login', { timeout: 10_000 });
    } catch {
      test.skip(true, '前端未就绪（E2E_BASE_URL 不可达），跳过 UI 断言。');
      return;
    }
    await page.addInitScript((token) => {
      localStorage.setItem('access_token', token);
    }, user.accessToken);
    await page.goto(`/projects/${project.id}/parse`);

    // 1. 解析页展示「生成大纲」（2026-08-25 起按钮名收敛）
    await expect(page.getByRole('button', { name: '生成大纲' })).toBeVisible({
      timeout: 30_000,
    });

    // 2. 点击后立即给出引导提示（而非 60s 轮询空转），且不跳转
    await page.getByRole('button', { name: '生成大纲' }).click();
    await expect(page.getByText(/工作流已进入后续阶段/)).toBeVisible({ timeout: 15_000 });
    await expect(page).toHaveURL(/\/parse$/);
  });
});
