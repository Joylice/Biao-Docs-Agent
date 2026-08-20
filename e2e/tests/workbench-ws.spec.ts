/**
 * 阶段 C：工作台待办 WebSocket 实时推送 E2E。
 *
 * 被测能力（后端 app/api/websocket.py + division.py；前端 WorkbenchView.vue）：
 * - 用户级 WS：/ws/user/{user_id}?token=<JWT>；缺 token/无效 → 4001，订阅他人频道 → 4003（浏览器侧 1006）
 * - 订阅 Redis 频道 bid:user:{user_id}；owner 分配章节（POST chapter-assignments）→
 *   向 assignee 用户频道推 task_assigned
 * - WorkbenchView 挂载时建立用户级 WS，收到事件静默刷新 /workbench/summary
 *
 * 注：本链路（注册→建项目→分配→工作台）不依赖 LLM，无 BID_LLM_MOCK 门槛。
 */
import type { APIRequestContext, Page } from '@playwright/test';
import {
  api,
  backendHealthy,
  bearer,
  createProject,
  registerAndLogin,
  test,
  wsUrl,
  type AuthedUser,
  expect,
} from '../fixtures/auth';

interface WsMessage {
  type: string;
  project_id?: string;
  assignments?: Array<{ chapter_no: string; assignee_id: string }>;
  [k: string]: unknown;
}

/** owner 建项目并添加 member（分配前置：assignee 必须是项目成员） */
async function setupProjectWithMember(
  apiCtx: APIRequestContext,
  owner: AuthedUser,
  member: AuthedUser,
) {
  const project = await createProject(apiCtx, owner);
  const add = await apiCtx.post(api(`/projects/${project.id}/members`), {
    headers: bearer(owner),
    data: { email: member.email },
  });
  expect(add.status(), `添加成员失败: ${await add.text()}`).toBe(200);
  return project;
}

/** 打开用户级 WS 并等待 pong（连接就绪+双向通路证明），常驻继续收集事件到 window.__userWsEvents */
async function openUserWsAndAwaitReady(page: Page, url: string, timeoutMs = 10_000): Promise<void> {
  await page.evaluate(
    ({ url, timeoutMs }) =>
      new Promise<void>((resolve, reject) => {
        const w = window as unknown as {
          __userWs: WebSocket;
          __userWsEvents: unknown[];
        };
        const ws = new WebSocket(url);
        const timer = setTimeout(() => {
          ws.close();
          reject(new Error('用户级 WS 连接/pong 超时'));
        }, timeoutMs);
        ws.onopen = () => ws.send(JSON.stringify({ type: 'ping' }));
        ws.onmessage = (e) => {
          const m = JSON.parse(String(e.data));
          if (m.type !== 'pong') return;
          clearTimeout(timer);
          w.__userWsEvents = [];
          w.__userWs = ws;
          ws.onmessage = (ev) => w.__userWsEvents.push(JSON.parse(String(ev.data)));
          resolve();
        };
        ws.onerror = () => {
          clearTimeout(timer);
          reject(new Error('用户级 WS 连接错误（后端 /ws/user 端点不可达？）'));
        };
      }),
    { url, timeoutMs },
  );
}

/** 轮询用户级 WS 收集事件直到 predicate 命中或超时 */
async function pollUserWsEvents(
  page: Page,
  predicate: (m: WsMessage) => boolean,
  timeoutMs = 10_000,
): Promise<WsMessage[]> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const events = (await page.evaluate(() => {
      const w = window as unknown as { __userWsEvents?: unknown[] };
      return w.__userWsEvents ?? [];
    })) as WsMessage[];
    if (events.some(predicate)) return events;
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`等待用户级 WS 业务事件超时(${timeoutMs}ms)`);
}

test.beforeEach(async ({ api: apiCtx }) => {
  test.skip(
    !(await backendHealthy(apiCtx)),
    '后端服务未就绪（E2E_API_URL 不可达 /health），无法验证用户级 WebSocket。',
  );
});

test.describe('阶段 C：工作台待办用户级 WebSocket 实时推送', () => {
  test('A 分配 → B 工作台待办实时出现（无需手动刷新）', async ({
    api: apiCtx,
    page,
  }) => {
    const owner = await registerAndLogin(apiCtx, 'uws-owner');
    const member = await registerAndLogin(apiCtx, 'uws-member');
    const project = await setupProjectWithMember(apiCtx, owner, member);

    try {
      await page.goto('/login', { timeout: 10_000 });
    } catch {
      test.skip(true, '前端未就绪（E2E_BASE_URL 不可达），跳过 UI 断言。');
      return;
    }

    const summaryReqs: number[] = [];
    let mainFrameNavigations = 0;
    page.on('request', (req) => {
      if (req.url().includes('/api/v1/workbench/summary')) summaryReqs.push(Date.now());
    });
    page.on('framenavigated', (frame) => {
      if (frame === page.mainFrame()) mainFrameNavigations += 1;
    });

    // B 打开工作台：WorkbenchView 挂载应建立用户级 WS（先挂事件等待器再导航，防漏）
    const userWsOpened = page
      .waitForEvent('websocket', {
        predicate: (ws) => ws.url().includes(`/ws/user/${member.userId}`),
        timeout: 10_000,
      })
      .catch(() => null);
    await page.addInitScript((token) => {
      localStorage.setItem('access_token', token);
    }, member.accessToken);
    await page.goto('/workbench');
    mainFrameNavigations = 0; // 排除 goto 自身的导航计数
    await expect(page.getByText('我的待办')).toBeVisible({ timeout: 30_000 });
    const todo = page.getByText(`${project.name} · 1 E2E实时推送`, { exact: true });
    await expect(todo).toHaveCount(0); // 分配前无该待办

    const wsHandle = await userWsOpened;
    expect(
      wsHandle,
      '工作台挂载后 10s 内未建立用户级 WS（疑似 currentUserId 未就绪且无重试）',
    ).not.toBeNull();
    await new Promise((r) => setTimeout(r, 1_500)); // 预留握手完成时间

    // A（owner）分配章节 1 给 B → 后端向 B 用户频道推 task_assigned
    const assignAt = Date.now();
    const assign = await apiCtx.post(api(`/projects/${project.id}/chapter-assignments`), {
      headers: bearer(owner),
      data: [{ chapter_no: '1', title: 'E2E实时推送', assignee_id: member.userId }],
    });
    expect(assign.status(), `分配失败: ${await assign.text()}`).toBe(200);

    // B 工作台 10s 内出现待办（轮询断言），全程无手动刷新/导航
    await expect(todo).toBeVisible({ timeout: 10_000 });
    expect(mainFrameNavigations, '期间页面发生重载（待办应经 WS 静默刷新出现）').toBe(0);
    expect(
      summaryReqs.some((t) => t > assignAt),
      '分配后未再请求 /workbench/summary（WS 事件未触发静默刷新）',
    ).toBe(true);
  });

  test('兜底：B token 直连用户频道，分配后收到 task_assigned', async ({
    api: apiCtx,
    page,
  }) => {
    const owner = await registerAndLogin(apiCtx, 'uws-api-owner');
    const member = await registerAndLogin(apiCtx, 'uws-api-member');
    const project = await setupProjectWithMember(apiCtx, owner, member);

    // 先建连（pong 证明就绪）再触发分配，避免丢事件
    await openUserWsAndAwaitReady(
      page,
      wsUrl(`/ws/user/${member.userId}?token=${member.accessToken}`),
    );
    const assign = await apiCtx.post(api(`/projects/${project.id}/chapter-assignments`), {
      headers: bearer(owner),
      data: [{ chapter_no: '1', title: 'E2E直连推送', assignee_id: member.userId }],
    });
    expect(assign.status(), `分配失败: ${await assign.text()}`).toBe(200);

    const events = await pollUserWsEvents(page, (m) => m.type === 'task_assigned', 10_000);
    const evt = events.find((m) => m.type === 'task_assigned') as WsMessage;
    expect(evt.project_id).toBe(project.id);
    expect(evt.assignments ?? []).toEqual([{ chapter_no: '1', assignee_id: member.userId }]);
  });

  test('用户级 WS 握手鉴权：缺 token/无效/订阅他人频道均被拒', async ({
    api: apiCtx,
    page,
  }) => {
    const owner = await registerAndLogin(apiCtx, 'uws-deny-owner');
    const member = await registerAndLogin(apiCtx, 'uws-deny-member');

    for (const url of [
      wsUrl(`/ws/user/${member.userId}`), // 缺 token
      wsUrl(`/ws/user/${member.userId}?token=invalid-token`), // 无效 token
      wsUrl(`/ws/user/${member.userId}?token=${owner.accessToken}`), // 他人 token 订阅 member 频道
    ]) {
      const code = await page.evaluate(
        (u) =>
          new Promise<number>((resolve) => {
            const ws = new WebSocket(u);
            const timer = setTimeout(() => resolve(-1), 10_000);
            ws.onclose = (e) => {
              clearTimeout(timer);
              resolve(e.code);
            };
            ws.onerror = () => {
              /* close 事件随后到达，以 onclose 为准 */
            };
          }),
        url,
      );
      // 握手前 close → uvicorn 拒绝升级（浏览器侧 1006）；accept 后关闭 → 4001/4003
      expect([1006, 4001, 4003], `未被拒绝的连接: ${url}`).toContain(code);
    }
  });
});
