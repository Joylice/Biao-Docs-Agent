/**
 * 场景 1 / E2E-01：注册登录
 * 注册 → 登录获取 JWT → （刷新 token）→ /auth/me 校验身份。
 *
 * 对齐后端路由：backend/app/api/auth.py
 *   POST /api/v1/auth/register | POST /api/v1/auth/login | GET /api/v1/auth/me
 */
import {
  api,
  backendHealthy,
  bearer,
  type BizResponse,
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

test.describe('注册登录', () => {
  test('注册成功返回用户信息（code=0）', async ({ api: apiCtx }) => {
    const email = `e2e-reg-${Date.now()}@example.com`;
    const resp = await apiCtx.post(api('/auth/register'), {
      data: { email, password: 'E2ePass#12345', display_name: 'E2E 注册' },
    });
    expect(resp.status()).toBe(200);
    const body = (await resp.json()) as BizResponse<{ id: string; email: string }>;
    expect(body.code).toBe(0);
    expect(body.data.email).toBe(email);
    expect(body.data.id).toBeTruthy();
  });

  test('重复注册同一邮箱被拒（BizError 4000）', async ({ api: apiCtx }) => {
    const email = `e2e-dup-${Date.now()}@example.com`;
    const data = { email, password: 'E2ePass#12345', display_name: 'E2E 重复' };
    const first = await apiCtx.post(api('/auth/register'), { data });
    expect(first.status()).toBe(200);

    const second = await apiCtx.post(api('/auth/register'), { data });
    expect(second.status()).toBe(400);
    const body = (await second.json()) as BizResponse;
    expect(body.code).toBe(4000);
  });

  test('登录获取 access_token 与 refresh_token', async ({ api: apiCtx }) => {
    const user = await registerAndLogin(apiCtx, 'login');
    expect(user.accessToken).toBeTruthy();
    expect(user.refreshToken).toBeTruthy();
    expect(user.accessToken).not.toBe(user.refreshToken);
  });

  test('错误密码登录返回 401（BizError 4001）', async ({ api: apiCtx }) => {
    const user = await registerAndLogin(apiCtx, 'wrongpw');
    const resp = await apiCtx.post(api('/auth/login'), {
      data: { email: user.email, password: 'WrongPass#999' },
    });
    expect(resp.status()).toBe(401);
    const body = (await resp.json()) as BizResponse;
    expect(body.code).toBe(4001);
  });

  test('JWT 访问 /auth/me 返回当前用户；无 token 被拒', async ({ api: apiCtx }) => {
    const user = await registerAndLogin(apiCtx, 'me');

    const ok = await apiCtx.get(api('/auth/me'), { headers: bearer(user) });
    expect(ok.status()).toBe(200);
    const body = (await ok.json()) as BizResponse<{ email: string; display_name: string }>;
    expect(body.code).toBe(0);
    expect(body.data.email).toBe(user.email);

    const unauthorized = await apiCtx.get(api('/auth/me'));
    expect(unauthorized.status()).toBe(401);
  });

  // 前置条件缺失：backend/app/api/auth.py 目前仅实现 register/login/me，
  // 未提供 /auth/refresh 端点（refresh_token 仅在登录响应中下发，无法换新 access_token）。
  // 待后端补充刷新端点后移除 skip。
  test('刷新 token（refresh → 新 access_token）', async () => {
    test.skip(true, '后端暂未实现 /auth/refresh 端点（auth.py 仅有 register/login/me），无法验证刷新流程。');
  });

  test('UI：登录页可访问，登录后进入项目列表（E2E-01 进入工作台）', async ({
    api: apiCtx,
    page,
  }) => {
    const user = await registerAndLogin(apiCtx, 'ui');

    // 前端未启动时优雅跳过（UI 场景依赖 E2E_BASE_URL）
    try {
      await page.goto('/login', { timeout: 10_000 });
    } catch {
      test.skip(true, '前端未就绪（E2E_BASE_URL 不可达），跳过 UI 断言。');
      return;
    }

    await page.getByPlaceholder('邮箱').fill(user.email);
    await page.getByPlaceholder('密码').fill(user.password);
    await page.getByRole('button', { name: '登录' }).click();

    // 登录成功后路由跳转项目列表（router/index.ts: '/' => Projects）
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByText('我的项目')).toBeVisible();
  });
});
