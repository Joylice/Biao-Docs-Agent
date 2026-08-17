/**
 * E2E：项目成员管理（权限体系完善 — 阶段二/阶段四）
 * owner 添加协作者 → 成员列表含新成员（owner 恒在首位）→ 移除 →
 * 被移除者访问项目端点 403；非 owner 移除被拒（403）。
 *
 * 对齐后端路由：backend/app/api/projects.py（GET/DELETE /projects/{id}/members）
 * + services/project_service.py（_check_project_member / owner 判定）
 */
import {
  api,
  backendHealthy,
  bearer,
  type BizResponse,
  createProject,
  registerAndLogin,
  test,
  expect,
} from '../fixtures/auth';

interface MemberItem {
  user_id: string;
  email: string;
  display_name: string;
  is_owner: boolean;
  joined_at: string;
}

test.beforeEach(async ({ api: apiCtx }) => {
  test.skip(
    !(await backendHealthy(apiCtx)),
    '后端服务未就绪（E2E_API_URL 不可达 /health）。请先 docker compose 启动基础设施并运行后端。',
  );
});

test.describe('项目成员管理', () => {
  test('添加协作者后成员列表可见且 owner 恒在首位', async ({ api: apiCtx }) => {
    const owner = await registerAndLogin(apiCtx, 'owner');
    const member = await registerAndLogin(apiCtx, 'member');
    const project = await createProject(apiCtx, owner);

    const add = await apiCtx.post(api(`/projects/${project.id}/members`), {
      headers: bearer(owner),
      data: { email: member.email },
    });
    expect(add.status()).toBe(200);

    const list = await apiCtx.get(api(`/projects/${project.id}/members`), {
      headers: bearer(owner),
    });
    expect(list.status()).toBe(200);
    const body = (await list.json()) as BizResponse<{ items: MemberItem[] }>;
    expect(body.code).toBe(0);

    const items = body.data.items;
    expect(items[0].user_id, 'owner 应恒在成员列表首位').toBe(owner.userId);
    expect(items[0].is_owner).toBe(true);
    expect(items.map((m) => m.user_id)).toContain(member.userId);

    const memberRow = items.find((m) => m.user_id === member.userId)!;
    expect(memberRow.is_owner).toBe(false);
    expect(memberRow.email).toBe(member.email);
    expect(memberRow.display_name).toBe(member.displayName);
    expect(memberRow.joined_at).toBeTruthy();
  });

  test('移除协作者后被移除者访问项目端点 403', async ({ api: apiCtx }) => {
    const owner = await registerAndLogin(apiCtx, 'owner2');
    const member = await registerAndLogin(apiCtx, 'member2');
    const project = await createProject(apiCtx, owner);

    const add = await apiCtx.post(api(`/projects/${project.id}/members`), {
      headers: bearer(owner),
      data: { email: member.email },
    });
    expect(add.status()).toBe(200);

    const del = await apiCtx.delete(api(`/projects/${project.id}/members/${member.userId}`), {
      headers: bearer(owner),
    });
    expect(del.status()).toBe(200);
    expect(((await del.json()) as BizResponse).code).toBe(0);

    // 移除提交存在竞态窗口（get_db 响应后 commit，与既有 E2E 处理一致）：
    // 轮询直到被移除者 403，避免把提交延迟误判为移除未生效。
    const deadline = Date.now() + 10_000;
    let status = 0;
    while (Date.now() < deadline) {
      const resp = await apiCtx.get(api(`/projects/${project.id}`), {
        headers: bearer(member),
      });
      status = resp.status();
      if (status === 403) break;
      await new Promise((r) => setTimeout(r, 300));
    }
    expect(status, '移除后 10s 内被移除者仍可访问项目（提交未收敛）').toBe(403);
  });

  test('非 owner 移除成员被拒（403）', async ({ api: apiCtx }) => {
    const owner = await registerAndLogin(apiCtx, 'owner3');
    const member = await registerAndLogin(apiCtx, 'member3');
    const outsider = await registerAndLogin(apiCtx, 'outsider3');
    const project = await createProject(apiCtx, owner);

    const add = await apiCtx.post(api(`/projects/${project.id}/members`), {
      headers: bearer(owner),
      data: { email: member.email },
    });
    expect(add.status()).toBe(200);

    // 协作者（非 owner）尝试移除他人 → 403
    const forbidden = await apiCtx.delete(
      api(`/projects/${project.id}/members/${outsider.userId}`),
      { headers: bearer(member) },
    );
    expect(forbidden.status()).toBe(403);
    expect(((await forbidden.json()) as BizResponse).code).toBe(4003);
  });
});
