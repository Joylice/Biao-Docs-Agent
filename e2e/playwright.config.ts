import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright 配置。
 *
 * 环境变量：
 * - E2E_BASE_URL : 前端地址（UI 场景），默认 http://localhost:5173
 * - E2E_API_URL  : 后端 API 地址（API/WS 场景），默认 http://localhost:8000
 * - BID_LLM_MOCK : 后端 LLM mock 开关（true 才放开 LLM 相关断言）
 */
export default defineConfig({
  testDir: './tests',
  // 单条用例超时：解析/生成链路含异步轮询，给足余量
  timeout: 120_000,
  expect: { timeout: 10_000 },
  // E2E 依赖共享后端与数据库，串行执行避免相互干扰
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  use: {
    // UI 场景 baseURL：前端（vite dev / nginx）
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:5173',
    actionTimeout: 15_000,
    navigationTimeout: 20_000,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
