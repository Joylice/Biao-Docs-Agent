/**
 * 阶段 G UI 整改截图留存脚本（一次性工具，运行于 e2e 环境）.
 * 关键页面：工作台/项目列表/方案生成（分工）/方案大纲生成/用户管理。
 * 用法：node tools/stage-g-shots.mjs（前置：vite dev 5174 + 后端 8000）
 */
import { chromium } from 'playwright';
import fs from 'node:fs';

const BASE = 'http://localhost:5174';
const OUT = 'd:/AI/WorkBuddy/2026-08-15-17-35-34/output/stage-g';
fs.mkdirSync(OUT, { recursive: true });

const PROJ_NAME = `UI快照验证项目${Date.now()}`;

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

// 登录
await page.goto(`${BASE}/login`);
await page.getByPlaceholder(/邮箱/).fill('ui-shot-admin@example.com');
await page.getByPlaceholder(/密码/).fill('E2ePass#12345');
await page.getByRole('button', { name: /登\s*录/ }).click();
await page.waitForURL(/workbench/, { timeout: 15000 });

// 1. 工作台
await page.waitForTimeout(1200);
await page.screenshot({ path: `${OUT}/01-workbench.png`, fullPage: true });

// 2. 项目列表
await page.getByText('项目列表', { exact: true }).click();
await page.waitForTimeout(1200);
await page.screenshot({ path: `${OUT}/02-projects.png`, fullPage: true });

// 新建项目
await page.getByRole('button', { name: /新建项目|新\s*建\s*项\s*目/ }).click();
const modal = page.locator('.ant-modal');
await modal.locator('input').first().fill(PROJ_NAME);
await modal.getByRole('button', { name: /确\s*定/ }).click();
await page.waitForTimeout(1500);
await page.screenshot({ path: `${OUT}/02-projects-after-create.png`, fullPage: true });

// 3. 进入项目 → 方案生成（分工页，名称含空格，用正则兼容 autoInsertSpace）
await page.getByText(/UI\s*快\s*照\s*验\s*证\s*项\s*目/).first().click();
await page.waitForTimeout(1500);
const divisionLink = page.getByText('方案生成', { exact: true }).first();
if (await divisionLink.count()) {
  await divisionLink.click();
  await page.waitForTimeout(1200);
}
await page.screenshot({ path: `${OUT}/03-division.png`, fullPage: true });

// 4. 方案大纲生成页
const genLink = page.getByText('方案大纲生成', { exact: true }).first();
if (await genLink.count()) {
  await genLink.click();
  await page.waitForTimeout(1200);
}
await page.screenshot({ path: `${OUT}/04-generate.png`, fullPage: true });

// 5. 用户管理（项目详情布局无顶栏下拉，直接 URL 访问）
await page.goto(`${BASE}/users`);
await page.waitForTimeout(1200);
await page.screenshot({ path: `${OUT}/05-users.png`, fullPage: true });

await browser.close();
console.log('截图完成:', fs.readdirSync(OUT).join(', '));
