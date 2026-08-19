/**
 * 子节分工与工作台改版 E2E — 生成页只读/权限按钮 + 工作台双视图。
 *
 * 覆盖：
 * - 阶段 B：生成页非 owner 只读（无确认/编辑入口），owner 见「确认大纲」主按钮
 * - 阶段 C：登录后默认落地 /workbench，待办条目直达项目分工页
 * - 阶段 D：按钮可见性按角色收敛（前端隐藏 + 后端 403 双保险的前端侧）
 *
 * 前置：后端健康 + LLM mock（BID_LLM_MOCK=true，与 docker compose 配置一致）。
 */
import { expect, type APIRequestContext } from '@playwright/test';
import {
  api,
  backendHealthy,
  bearer,
  createProject,
  llmMockEnabled,
  registerAndLogin,
  test,
  waitForWorkflowStatus,
  type AuthedUser,
} from '../fixtures/auth';

test.beforeEach(async ({ api: apiCtx }) => {
  test.skip(
    !(await backendHealthy(apiCtx)),
    '后端服务未就绪（E2E_API_URL 不可达 /health）。',
  );
});

/** API 驱动工作流到 confirm_outline 挂起（大纲待确认态） */
async function driveToOutlineConfirm(
  apiCtx: APIRequestContext,
  user: AuthedUser,
  projectId: string,
): Promise<void> {
  await apiCtx.post(api(`/projects/${projectId}/workflow/start`), { headers: bearer(user) });
  await waitForWorkflowStatus(
    apiCtx,
    user,
    projectId,
    (s) => s.interrupt?.type === 'confirm_score_points',
    30_000,
  );
  await apiCtx.post(api(`/projects/${projectId}/workflow/confirm-score-points`), {
    headers: bearer(user),
  });
  await waitForWorkflowStatus(
    apiCtx,
    user,
    projectId,
    (s) => s.interrupt?.type === 'confirm_outline',
    30_000,
  );
}

test.describe('生成页只读与大纲确认权限（阶段 B/D）', () => {
  test('非 owner 成员：确认态只读，无确认/编辑入口；owner 见「确认大纲」', async ({
    api: apiCtx,
    page,
  }) => {
    test.skip(!llmMockEnabled(), '前置条件：需后端以 BID_LLM_MOCK=true 启动。');

    const owner = await registerAndLogin(apiCtx, 'ro-owner');
    const member = await registerAndLogin(apiCtx, 'ro-member');
    const project = await createProject(apiCtx, owner);
    const add = await apiCtx.post(api(`/projects/${project.id}/members`), {
      headers: bearer(owner),
      data: { email: member.email },
    });
    expect(add.status()).toBe(200);
    await driveToOutlineConfirm(apiCtx, owner, project.id);

    try {
      await page.goto('/login', { timeout: 10_000 });
    } catch {
      test.skip(true, '前端未就绪（E2E_BASE_URL 不可达），跳过 UI 断言。');
      return;
    }

    // 1. 成员视角：只读提示 + 无确认/编辑类按钮（正文编辑入口已在阶段 B 移除）
    await page.addInitScript((token) => {
      localStorage.setItem('access_token', token);
    }, member.accessToken);
    await page.goto(`/projects/${project.id}/generate`);
    await expect(page.getByText('大纲编辑')).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/等待项目负责人确认大纲/)).toBeVisible();
    await expect(page.getByRole('button', { name: '确认大纲' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: '保存草稿' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: '添加章节' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: '重新生成大纲' })).toHaveCount(0);
    // 只读态：大纲标题输入框不可编辑（readonly prop 生效）
    await expect(page.getByPlaceholder('章节标题').first()).not.toBeEditable();

    // 2. 后端双保险：成员直调 confirm-outline → 403
    const forbidden = await apiCtx.post(api(`/projects/${project.id}/workflow/confirm-outline`), {
      headers: bearer(member),
    });
    expect(forbidden.status()).toBe(403);

    // 3. owner 视角：「确认大纲」主按钮可见（同一项目切换 token 重进）
    await page.addInitScript((token) => {
      localStorage.setItem('access_token', token);
    }, owner.accessToken);
    await page.goto(`/projects/${project.id}/generate`);
    await expect(page.getByRole('button', { name: '确认大纲' })).toBeVisible({
      timeout: 30_000,
    });
    // 页头/大纲卡均有待确认 tag，exact 匹配卡片徽标（避免 strict mode 多元素）
    await expect(page.getByText('待确认', { exact: true }).first()).toBeVisible();
  });
});

test.describe('工作台双视图（阶段 C）', () => {
  test('登录后默认落地工作台；待办条目直达分工页；owner 见项目进度', async ({
    api: apiCtx,
    page,
  }) => {
    test.skip(!llmMockEnabled(), '前置条件：需后端以 BID_LLM_MOCK=true 启动。');

    const owner = await registerAndLogin(apiCtx, 'wb-owner');
    const member = await registerAndLogin(apiCtx, 'wb-member');
    const project = await createProject(apiCtx, owner);
    const add = await apiCtx.post(api(`/projects/${project.id}/members`), {
      headers: bearer(owner),
      data: { email: member.email },
    });
    expect(add.status()).toBe(200);

    // 分配第一章给 member（mock 大纲单章 chapter_no=1）→ 待领取任务
    const assign = await apiCtx.post(api(`/projects/${project.id}/chapter-assignments`), {
      headers: bearer(owner),
      data: [{ chapter_no: '1', title: 'mock', assignee_id: member.userId }],
    });
    expect(assign.status(), `分配失败: ${await assign.text()}`).toBe(200);

    try {
      await page.goto('/login', { timeout: 10_000 });
    } catch {
      test.skip(true, '前端未就绪（E2E_BASE_URL 不可达），跳过 UI 断言。');
      return;
    }

    // 1. member 登录后访问根路径 → 重定向工作台，待办桶含刚分配的任务
    await page.addInitScript((token) => {
      localStorage.setItem('access_token', token);
    }, member.accessToken);
    await page.goto('/');
    await expect(page).toHaveURL(/\/workbench$/);
    await expect(page.getByText('我的待办')).toBeVisible({ timeout: 30_000 });
    // 待办条目为文本 span（项目名 · 章号 标题），非 title 属性
    const todo = page.getByText(`${project.name} · 1 mock`, { exact: true });
    await expect(todo).toBeVisible({ timeout: 30_000 });

    // 2. 待办条目点击 → 直达该项目分工页
    await todo.click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/division$`));

    // 3. owner 视角：项目进度看板可见（my_projects 非空）
    await page.addInitScript((token) => {
      localStorage.setItem('access_token', token);
    }, owner.accessToken);
    await page.goto('/workbench');
    // 「项目进度」区标题（exact 避免命中 PageContainer 副标题）
    await expect(page.getByText('项目进度', { exact: true })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(project.name).first()).toBeVisible();
  });
});
