/**
 * 阶段 H：废标条款识别端到端.
 *
 * 覆盖：
 * - API：解析产出废标条款（mock 确定性样本）→ PUT 幂等覆盖 → GET 回读一致
 * - 导出门禁：未确认 high 条款阻塞导出（4012）→ 人工确认后放行（不再 4012）
 * - UI：解析确认页「废标风险」卡片渲染 + 生成页高风险警告横幅
 *
 * 前置条件：BID_LLM_MOCK=true；前端可访问（E2E_BASE_URL），不满足时 skip UI 断言。
 */
import type { APIRequestContext } from '@playwright/test';
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
  expect,
  type AuthedUser,
} from '../fixtures/auth';
import { buildMinimalPdf } from '../fixtures/files';

interface DqClause {
  id?: string;
  clause_no: string;
  title: string;
  risk_category: string;
  severity: string;
  recommendation?: string | null;
  confirmed: boolean;
}

/** 上传招标文件并等待解析完成，返回 docId */
async function uploadParsedTender(
  apiCtx: APIRequestContext,
  user: AuthedUser,
  projectId: string,
): Promise<string> {
  const resp = await apiCtx.post(api(`/projects/${projectId}/documents?doc_type=tender_file`), {
    headers: bearer(user),
    multipart: {
      file: {
        name: 'tender-dq.pdf',
        mimeType: 'application/pdf',
        buffer: buildMinimalPdf('E2E Disqualification Tender. 未提交投标保证金的按废标处理。'),
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
  return docId;
}

async function putClauses(
  apiCtx: APIRequestContext,
  user: AuthedUser,
  projectId: string,
  docId: string,
  items: DqClause[],
): Promise<DqClause[]> {
  const resp = await apiCtx.put(
    api(`/projects/${projectId}/documents/${docId}/disqualification-clauses`),
    { headers: bearer(user), data: { items } },
  );
  expect(resp.status(), `PUT 废标条款失败: ${await resp.text()}`).toBe(200);
  return ((await resp.json()) as BizResponse<{ items: DqClause[] }>).data.items;
}

async function getClauses(
  apiCtx: APIRequestContext,
  user: AuthedUser,
  projectId: string,
  docId: string,
): Promise<DqClause[]> {
  const resp = await apiCtx.get(
    api(`/projects/${projectId}/documents/${docId}/disqualification-clauses`),
    { headers: bearer(user) },
  );
  expect(resp.status()).toBe(200);
  return ((await resp.json()) as BizResponse<{ items: DqClause[] }>).data.items;
}

test.beforeEach(async ({ api: apiCtx }) => {
  test.skip(
    !(await backendHealthy(apiCtx)),
    '后端服务未就绪（E2E_API_URL 不可达 /health）。',
  );
});

test.describe('废标条款识别：解析提取 + 导出门禁', () => {
  test('解析产出条款 → PUT 覆盖回读一致 → 未确认 high 阻塞导出 → 确认后放行', async ({
    api: apiCtx,
  }) => {
    test.skip(!llmMockEnabled(), '前置条件：需后端以 BID_LLM_MOCK=true 启动。');

    const user = await registerAndLogin(apiCtx, 'dq-gate');
    const project = await createProject(apiCtx, user);
    const docId = await uploadParsedTender(apiCtx, user, project.id);

    // 1. 解析产出废标条款（mock schema 确定性样本：≥1 条）
    const parsed = await getClauses(apiCtx, user, project.id, docId);
    expect(parsed.length).toBeGreaterThan(0);

    // 2. PUT 幂等覆盖为 high 未确认条款 → GET 回读一致
    const highItems: DqClause[] = [
      {
        clause_no: '3.1.2',
        title: '投标保证金缺失按废标处理',
        risk_category: 'substantive_deviation',
        severity: 'high',
        recommendation: '开标前确认保证金到账凭证',
        confirmed: false,
      },
    ];
    const saved = await putClauses(apiCtx, user, project.id, docId, highItems);
    expect(saved).toHaveLength(1);
    expect(saved[0].severity).toBe('high');
    const round = await getClauses(apiCtx, user, project.id, docId);
    expect(round).toHaveLength(1);
    expect(round[0].title).toBe('投标保证金缺失按废标处理');
    expect(round[0].confirmed).toBe(false);

    // 3. 导出门禁：未确认 high → 4012 阻塞
    const blocked = await apiCtx.get(api(`/projects/${project.id}/workflow/export`), {
      headers: bearer(user),
    });
    expect(blocked.status()).toBe(400);
    expect(((await blocked.json()) as BizResponse<unknown>).code).toBe(4012);

    // 4. 人工确认后放行（未生成方案时导出可能 5010，但不应再是 4012）
    await putClauses(apiCtx, user, project.id, docId, [
      { ...highItems[0], confirmed: true },
    ]);
    const passed = await apiCtx.get(api(`/projects/${project.id}/workflow/export`), {
      headers: bearer(user),
    });
    const passedBody = (await passed.json()) as BizResponse<unknown>;
    expect(passedBody.code, '确认后不应再被废标门禁阻塞').not.toBe(4012);
  });
});

test.describe('废标条款识别：前端风险展示', () => {
  test('解析确认页废标风险卡片 + 生成页高风险横幅', async ({ api: apiCtx, page }) => {
    test.skip(!llmMockEnabled(), '前置条件：需后端以 BID_LLM_MOCK=true 启动。');

    const user = await registerAndLogin(apiCtx, 'dq-ui');
    const project = await createProject(apiCtx, user);
    const docId = await uploadParsedTender(apiCtx, user, project.id);
    await putClauses(apiCtx, user, project.id, docId, [
      {
        clause_no: '2.4',
        title: '项目经理资质不符按废标处理',
        risk_category: 'qualification_missing',
        severity: 'high',
        recommendation: '核查项目经理一级建造师证书',
        confirmed: false,
      },
    ]);

    try {
      await page.goto('/login', { timeout: 10_000 });
    } catch {
      test.skip(true, '前端未就绪（E2E_BASE_URL 不可达），跳过 UI 断言。');
      return;
    }

    await page.addInitScript((token) => {
      localStorage.setItem('access_token', token);
    }, user.accessToken);

    // 解析确认页（内嵌于招标解析页）：废标风险卡片 + 条款标题 + 人工确认勾选
    await page.goto(`/projects/${project.id}/parse`);
    await expect(page.getByText('废标风险', { exact: true }).first()).toBeVisible({
      timeout: 30_000,
    });
    // antd tab-pane 惰性渲染：默认激活「评分点」Tab，先点击「废标风险」Tab 再断言条款
    await page.getByRole('tab', { name: '废标风险' }).click();
    await expect(page.getByText('项目经理资质不符按废标处理')).toBeVisible();
    await expect(page.getByText('已确认').first()).toBeVisible();

    // 生成页：存在未确认 high 条款 → 顶部高风险警告横幅
    await page.goto(`/projects/${project.id}/generate`);
    await expect(
      page.getByText(/本项目存在 \d+ 条高风险废标条款/),
    ).toBeVisible({ timeout: 30_000 });
  });
});
