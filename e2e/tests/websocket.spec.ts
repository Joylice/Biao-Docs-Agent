/**
 * 场景 6：流式推送（WebSocket 进度事件顺序与完整性）
 *
 * 对齐后端：backend/app/api/websocket.py
 *   WS /ws/{project_id}（无路由前缀，见 main.py include_router(websocket.router)）
 *   协议：client → {"type":"ping"} ⇒ server → {"type":"pong"}
 *         client → {"type":"get_status"} ⇒ server → {"type":"status","phase":...,"progress":...}
 *
 * 实现方式：在浏览器 page 上下文使用原生 WebSocket（无需额外依赖）。
 * 限制：workflow 为 stub 状态时服务端不会主动推送 progress 事件流，
 * 进度事件顺序断言待 LangGraph 接入后补充（见文末 skip 用例）。
 */
import {
  backendHealthy,
  createProject,
  registerAndLogin,
  test,
  wsUrl,
  expect,
} from '../fixtures/auth';

interface WsMessage {
  type: string;
  phase?: string;
  progress?: number;
}

/** 打开 WS 会话，发送 send 中的消息，收集 expectCount 条响应后关闭 */
async function wsSession(
  page: import('@playwright/test').Page,
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

test.beforeEach(async ({ api: apiCtx }) => {
  test.skip(
    !(await backendHealthy(apiCtx)),
    '后端服务未就绪（E2E_API_URL 不可达 /health），无法验证 WebSocket。',
  );
});

test.describe('WebSocket 流式推送', () => {
  test('连接建立 + ping/pong 心跳', async ({ api: apiCtx, page }) => {
    const user = await registerAndLogin(apiCtx, 'ws');
    const project = await createProject(apiCtx, user);

    const messages = await wsSession(page, wsUrl(`/ws/${project.id}`), [{ type: 'ping' }], 1);
    expect(messages).toHaveLength(1);
    expect(messages[0].type).toBe('pong');
  });

  test('get_status 返回状态消息（顺序与字段完整性）', async ({ api: apiCtx, page }) => {
    const user = await registerAndLogin(apiCtx, 'ws-status');
    const project = await createProject(apiCtx, user);

    const messages = await wsSession(
      page,
      wsUrl(`/ws/${project.id}`),
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

  // 前置条件：workflow.py 状态持久化（LangGraph checkpointer）+ worker 产生进度事件，
  // 服务端才会通过 stream_generation_progress 主动推送 phase/progress/chapter 事件。
  // 当前为 stub（phase 恒为 init），无事件流可断言 → skip 并说明，不谎报通过。
  test('生成进度事件流：顺序与完整性（phase 递进 → completed）', async () => {
    test.skip(
      true,
      'workflow 编排为 TODO stub（无进度事件源），待 LangGraph checkpointer 接入后启用：' +
        '断言事件顺序 init→parse→outline→generate→export 且以 completed 收尾、无丢包。',
    );
  });
});
