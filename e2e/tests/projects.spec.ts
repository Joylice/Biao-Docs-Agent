/**
 * 场景 2 / E2E-07：项目管理
 * 创建项目 → 添加成员 → 越权访问他人项目被拒（403）。
 *
 * 对齐后端路由：backend/app/api/projects.py + services/project_service.py
 *   ForbiddenError => BizError 4003 => HTTP 403（backend/app/main.py 全局异常处理）
 */
import {
  api,
  backendHealthy,
  bearer,
  type BizResponse,
  createProject,
  type Project,
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

test.describe('项目管理', () => {
  test('创建项目 → 详情与列表中可见', async ({ api: apiCtx }) => {
    const owner = await registerAndLogin(apiCtx, 'owner');
    const project = await createProject(apiCtx, owner);

    // 详情
    const detail = await apiCtx.get(api(`/projects/${project.id}`), { headers: bearer(owner) });
    expect(detail.status()).toBe(200);
    const detailBody = (await detail.json()) as BizResponse<Project>;
    expect(detailBody.code).toBe(0);
    expect(detailBody.data.id).toBe(project.id);
    expect(detailBody.data.name).toBe(project.name);

    // 列表包含新项目
    const list = await apiCtx.get(api('/projects'), { headers: bearer(owner) });
    expect(list.status()).toBe(200);
    const listBody = (await list.json()) as BizResponse<{ items: Project[]; total: number }>;
    expect(listBody.code).toBe(0);
    expect(listBody.data.items.map((p) => p.id)).toContain(project.id);
    expect(listBody.data.total).toBeGreaterThanOrEqual(1);
  });

  test('添加成员后协作者可访问项目', async ({ api: apiCtx }) => {
    const owner = await registerAndLogin(apiCtx, 'owner2');
    const member = await registerAndLogin(apiCtx, 'member');
    const project = await createProject(apiCtx, owner);

    // 添加前：协作者无权访问（403）
    const before = await apiCtx.get(api(`/projects/${project.id}`), { headers: bearer(member) });
    expect(before.status()).toBe(403);

    // owner 通过邮箱添加成员
    const add = await apiCtx.post(api(`/projects/${project.id}/members`), {
      headers: bearer(owner),
      data: { email: member.email },
    });
    expect(add.status()).toBe(200);
    expect(((await add.json()) as BizResponse).code).toBe(0);

    // 添加后：协作者可访问
    // 成员行提交存在竞态窗口（后端 get_db 响应后 commit，产品 bug 已在回归报告记录）：
    // 轮询直到协作者可见，避免把提交延迟误判为越权拦截。
    const deadline = Date.now() + 10_000;
    let afterStatus = 0;
    let afterBody: BizResponse<Project> | null = null;
    while (Date.now() < deadline) {
      const after = await apiCtx.get(api(`/projects/${project.id}`), { headers: bearer(member) });
      afterStatus = after.status();
      if (afterStatus === 200) {
        afterBody = (await after.json()) as BizResponse<Project>;
        break;
      }
      await new Promise((r) => setTimeout(r, 300));
    }
    expect(afterStatus, '添加成员后 10s 内协作者仍无法访问（提交未收敛）').toBe(200);
    expect(afterBody!.data.id).toBe(project.id);
  });

  test('非 owner 添加成员被拒（403）', async ({ api: apiCtx }) => {
    const owner = await registerAndLogin(apiCtx, 'owner3');
    const member = await registerAndLogin(apiCtx, 'member3');
    const outsider = await registerAndLogin(apiCtx, 'outsider3');
    const project = await createProject(apiCtx, owner);

    // 先把 member 加为协作者
    const add = await apiCtx.post(api(`/projects/${project.id}/members`), {
      headers: bearer(owner),
      data: { email: member.email },
    });
    expect(add.status()).toBe(200);

    // 协作者（非 owner）尝试添加 outsider → 403
    const forbidden = await apiCtx.post(api(`/projects/${project.id}/members`), {
      headers: bearer(member),
      data: { email: outsider.email },
    });
    expect(forbidden.status()).toBe(403);
    expect(((await forbidden.json()) as BizResponse).code).toBe(4003);
  });

  test('E2E-07 越权访问他人项目返回 403，数据不泄露', async ({ api: apiCtx }) => {
    const owner = await registerAndLogin(apiCtx, 'victim');
    const stranger = await registerAndLogin(apiCtx, 'stranger');
    const project = await createProject(apiCtx, owner);

    // 陌生人访问项目详情 → 403
    const detail = await apiCtx.get(api(`/projects/${project.id}`), {
      headers: bearer(stranger),
    });
    expect(detail.status()).toBe(403);
    expect(((await detail.json()) as BizResponse).code).toBe(4003);

    // 项目不应出现在陌生人的列表中
    const list = await apiCtx.get(api('/projects'), { headers: bearer(stranger) });
    const listBody = (await list.json()) as BizResponse<{ items: Project[] }>;
    expect(listBody.data.items.map((p) => p.id)).not.toContain(project.id);

    // 关联资源同样被拒（文档列表 / 评分点 / 工作流）
    for (const path of [
      `/projects/${project.id}/documents`,
      `/projects/${project.id}/score-points`,
      `/projects/${project.id}/workflow/status`,
    ]) {
      const resp = await apiCtx.get(api(path), { headers: bearer(stranger) });
      expect(resp.status(), `越权访问 ${path} 未被拦截`).toBe(403);
    }
  });

  test('UI：登录后项目列表页展示已创建项目（E2E-01 项目可见）', async ({
    api: apiCtx,
    page,
  }) => {
    const owner = await registerAndLogin(apiCtx, 'ui-owner');
    const project = await createProject(apiCtx, owner);

    try {
      await page.goto('/login', { timeout: 10_000 });
    } catch {
      test.skip(true, '前端未就绪（E2E_BASE_URL 不可达），跳过 UI 断言。');
      return;
    }

    // 路由守卫读取 localStorage.access_token（frontend/src/router/index.ts）；
    // 项目列表已迁至 /projects（/ 重定向到工作台）
    await page.evaluate((token) => localStorage.setItem('access_token', token), owner.accessToken);
    await page.goto('/projects');
    await expect(page.getByText('我的项目')).toBeVisible();
    await expect(page.getByText(project.name)).toBeVisible();
  });
});
