/**
 * 场景 6：流式推送（WebSocket 进度事件顺序与完整性）
 *
 * 对齐后端：backend/app/api/websocket.py
 *   WS /ws/{project_id}?token=<JWT access token>（握手鉴权：缺 token/无效 → close 4001，
 *   非项目成员 → close 4003）
 *   协议：client → {"type":"ping"} ⇒ server → {"type":"pong"}
 *         client → {"type":"get_status"} ⇒ server → {"type":"status",...checkpointer 状态}
 *   事件转发：agents 节点 publish_event → Redis 频道 bid:events:{project_id} → 本端点转发。
 *   事件类型（event_service.py 协议注释）：
 *     progress      {"type":"progress","phase":...,"progress":...,"current_chapter":...}
 *     section_done  {"type":"section_done","chapter_no":...,"title":...,"content":...}
 *     task_done     {"type":"task_done","export_storage_key":...}
 *     error         {"type":"error","message":...}
 *
 * 实现方式：在浏览器 page 上下文使用原生 WebSocket（无需额外依赖）。
 */
import type { APIRequestContext, Page } from '@playwright/test';
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
  wsUrl,
  type AuthedUser,
  expect,
} from '../fixtures/auth';
import { buildMinimalPdf } from '../fixtures/files';

interface WsMessage {
  type: string;
  phase?: string;
  progress?: number;
  chapter_no?: string;
  export_storage_key?: string;
  message?: string;
  [k: string]: unknown;
}

/** 打开 WS 会话，发送 send 中的消息，收集 expectCount 条响应后关闭 */
async function wsSession(
  page: Page,
  url: string,
  send: object[],
  expectCount: number,
  timeoutMs = 10_000,
): Promise<WsMessage[]> {
  return page.evaluate(
    ({ url, send, expectCount, timeoutMs }) =>
      new Promise<unknown[]>((resolve, reject) => {
        const ws = new WebSocket(url);
        const received: unknown[] = [];
        const timer = setTimeout(() => {
          ws.close();
          reject(new Error(`等待 WS 消息超时，已收到: ${JSON.stringify(received)}`));
        }, timeoutMs);
        ws.onopen = () => {
          for (const m of send) ws.send(JSON.stringify(m));
        };
        ws.onmessage = (e) => {
          received.push(JSON.parse(String(e.data)));
          if (received.length >= expectCount) {
            clearTimeout(timer);
            ws.close();
            resolve(received);
          }
        };
        ws.onerror = () => {
          clearTimeout(timer);
          reject(new Error('WebSocket 连接错误（后端 /ws 端点不可达？）'));
        };
      }),
    { url, send, expectCount, timeoutMs },
  ) as Promise<WsMessage[]>;
}

/**
 * 启动长驻事件收集器（page 内全局数组），返回后由测试主体驱动工作流，
 * 最后通过 pollWsEvents 读取已收集事件。
 */
async function startWsCollector(page: Page, url: string): Promise<void> {
  await page.evaluate((wsUrlStr) => {
    const ws = new WebSocket(wsUrlStr);
    const w = window as unknown as {
      __wsEvents: unknown[];
      __wsDone: boolean;
      __wsError: string;
    };
    w.__wsEvents = [];
    w.__wsDone = false;
    w.__wsError = '';
    ws.onmessage = (e) => {
      const m = JSON.parse(String(e.data));
      w.__wsEvents.push(m);
      if (m.type === 'task_done' || m.type === 'error') w.__wsDone = true;
    };
    ws.onerror = () => {
      w.__wsError = 'ws connection error';
      w.__wsDone = true;
    };
    ws.onclose = () => {
      w.__wsDone = true;
    };
    (window as unknown as { __ws: WebSocket }).__ws = ws;
  }, url);
}

/** 轮询收集器直到 task_done/error/超时，返回全部事件 */
async function pollWsEvents(page: Page, timeoutMs = 90_000): Promise<WsMessage[]> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const snap = (await page.evaluate(() => {
      const w = window as unknown as {
        __wsEvents: unknown[];
        __wsDone: boolean;
        __wsError: string;
      };
      return { events: w.__wsEvents, done: w.__wsDone, error: w.__wsError };
    })) as { events: WsMessage[]; done: boolean; error: string };
    if (snap.error) throw new Error(`WebSocket 收集器错误: ${snap.error}`);
    const terminated = snap.events.some((m) => m.type === 'task_done' || m.type === 'error');
    if (terminated || snap.done) return snap.events;
    await new Promise((r) => setTimeout(r, 1_000));
  }
  throw new Error(`等待 WS 事件流超时(${timeoutMs}ms)`);
}

/** 上传招标文件并等待 worker 解析完成（HITL 前置数据） */
async function uploadParsedTender(
  apiCtx: APIRequestContext,
  user: AuthedUser,
  projectId: string,
): Promise<void> {
  const resp = await apiCtx.post(api(`/projects/${projectId}/documents?doc_type=tender_file`), {
    headers: bearer(user),
    multipart: {
      file: {
        name: 'tender-ws.pdf',
        mimeType: 'application/pdf',
        buffer: buildMinimalPdf('E2E WS Tender. Scoring: technical 60, price 40.'),
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
  expect(status, '招标文件未解析成功（worker 异常？）').toBe('parsed');
}

test.beforeEach(async ({ api: apiCtx }) => {
  test.skip(
    !(await backendHealthy(apiCtx)),
    '后端服务未就绪（E2E_API_URL 不可达 /health），无法验证 WebSocket。',
  );
});

test.describe('WebSocket 流式推送', () => {
  test('连接建立 + ping/pong 心跳（token 鉴权）', async ({ api: apiCtx, page }) => {
    const user = await registerAndLogin(apiCtx, 'ws');
    const project = await createProject(apiCtx, user);

    const messages = await wsSession(
      page,
      wsUrl(`/ws/${project.id}?token=${user.accessToken}`),
      [{ type: 'ping' }],
      1,
    );
    expect(messages).toHaveLength(1);
    expect(messages[0].type).toBe('pong');
  });

  test('无 token / 无效 token 连接被拒（close 4001）', async ({ page, api: apiCtx }) => {
    const user = await registerAndLogin(apiCtx, 'ws-notoken');
    const project = await createProject(apiCtx, user);

    for (const url of [
      wsUrl(`/ws/${project.id}`),
      wsUrl(`/ws/${project.id}?token=invalid-token`),
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
      // 后端在握手前 close(code=4001) → uvicorn 以 HTTP 403 拒绝升级，
      // 浏览器侧表现为异常关闭 1006（close code 不携带 4001）；
      // 若实现改为 accept 后关闭则收到 4001。两者均视为"拒绝未鉴权连接"。
      expect([1006, 4001], `未被拒绝的连接: ${url}`).toContain(code);
    }
  });

  test('get_status 返回状态消息（顺序与字段完整性）', async ({ api: apiCtx, page }) => {
    const user = await registerAndLogin(apiCtx, 'ws-status');
    const project = await createProject(apiCtx, user);

    const messages = await wsSession(
      page,
      wsUrl(`/ws/${project.id}?token=${user.accessToken}`),
      [{ type: 'ping' }, { type: 'get_status' }],
      2,
    );

    // 消息顺序与请求一致：pong → status
    expect(messages.map((m) => m.type)).toEqual(['pong', 'status']);

    const status = messages[1];
    expect(typeof status.phase).toBe('string');
    expect(typeof status.progress).toBe('number');
    expect(status.progress).toBeGreaterThanOrEqual(0);
    expect(status.progress).toBeLessThanOrEqual(1);
  });

  // 前置条件：LangGraph 真实编排 + Redis pubsub 事件转发（本轮联调已接通）。
  // 事件链路：outline progress → section_done/generate progress → review progress → task_done。
  test('生成进度事件流：顺序与完整性（progress/section_done → task_done）', async ({
    api: apiCtx,
    page,
  }) => {
    test.skip(
      !llmMockEnabled(),
      '前置条件：需后端以 BID_LLM_MOCK=true 启动（测试进程同步设置 BID_LLM_MOCK=true）。',
    );

    const user = await registerAndLogin(apiCtx, 'ws-flow');
    const project = await createProject(apiCtx, user);

    // 先挂 WS 收集器再启动工作流，避免丢失早期事件
    await startWsCollector(page, wsUrl(`/ws/${project.id}?token=${user.accessToken}`));

    await uploadParsedTender(apiCtx, user, project.id);

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
    });
    await waitForWorkflowStatus(
      apiCtx,
      user,
      project.id,
      (s) => s.interrupt?.type === 'review_request',
      60_000,
    );
    await apiCtx.post(api(`/projects/${project.id}/workflow/confirm-review`), {
      headers: bearer(user),
      data: { action: 'approved', feedback: {} },
    });

    // 收集事件流直到 task_done（或 error）
    const events = await pollWsEvents(page, 90_000);
    const types = events.map((e) => e.type);
    expect(types, `事件流含 error 或异常: ${JSON.stringify(events)}`).not.toContain('error');

    // 完整性：至少一条 progress、至少一条 section_done、以 task_done 收尾
    const progressEvents = events.filter((e) => e.type === 'progress');
    const sectionDones = events.filter((e) => e.type === 'section_done');
    expect(progressEvents.length, `缺少 progress 事件: ${JSON.stringify(types)}`).toBeGreaterThan(0);
    expect(sectionDones.length, `缺少 section_done 事件: ${JSON.stringify(types)}`).toBeGreaterThan(0);
    expect(types[types.length - 1]).toBe('task_done');
    expect(events[events.length - 1].export_storage_key).toBeTruthy();

    // 顺序：progress 的 phase 覆盖 outline → generate（review 可能在 section_done 之间）
    const phases = progressEvents.map((e) => e.phase);
    expect(phases).toContain('outline');
    expect(phases).toContain('generate');
    expect(phases.indexOf('outline')).toBeLessThan(phases.lastIndexOf('generate'));

    // progress 数值单调不减（允许相等）
    const values = progressEvents.map((e) => e.progress ?? -1);
    for (let i = 1; i < values.length; i++) {
      expect(values[i], `progress 非单调: ${JSON.stringify(values)}`).toBeGreaterThanOrEqual(
        values[i - 1],
      );
    }

    // section_done 携带 chapter_no 且先于 task_done
    for (const sd of sectionDones) {
      expect(sd.chapter_no).toBeTruthy();
    }
    expect(types.indexOf('section_done')).toBeLessThan(types.lastIndexOf('task_done'));
  });
});