/**
 * E2E（阶段 B）：子节级分工全链路 + RBAC 权限矩阵 403 断言
 *
 * 覆盖：
 * 1. owner 建项目 → 解析 → 评分点确认 → 自定义嵌套大纲确认（子节编号 1.1/1.2/1.2.1）
 *    → 按子节粒度（"1.1"）分配给协作成员；
 * 2. 成员端：领取 → 生成初稿（mock）→ 提交 → owner 审核通过，全链路状态流转
 *    （API + DivisionView UI 混合断言）；
 * 3. 章级分配自动展开为全部子节（GET 树形 children，替换旧分工并重置 pending）；
 * 4. 越权 403：非 owner 分配；非 assignee 领取/生成/提交他人子节；
 *    非 assignee 编辑已分工子节；未分工章节非 owner 编辑；
 * 5. RBAC 配置端点（阶段 A）：member/kb_admin 一律 403，admin（BID_ADMIN_USER_IDS
 *    邮箱白名单）200。
 *
 * 前置条件：后端 LLM mock 开启（BID_LLM_MOCK=true），否则 skip；
 * 后端不可达整组 skip；前端不可达仅跳过 UI 断言（与现有 spec 一致）。
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
  waitForWorkflowStatus,
  expect,
  type AuthedUser,
} from '../fixtures/auth';
import { buildMinimalPdf } from '../fixtures/files';

/** 分工树节点（GET chapter-assignments：章聚合行 id/assignee_id 为 null） */
interface AssignmentTreeItem {
  id: string | null;
  chapter_no: string;
  title: string;
  assignee_id: string | null;
  assignee_name: string | null;
  status: string | null;
  section_status?: string | null;
  review_comment?: string | null;
  children: AssignmentTreeItem[];
  total: number;
  approved_count: number;
}

/** 自定义嵌套大纲（confirm-outline body 注入）：章 1 含子节 → 1.1/1.2/1.2.1；章 2 为 string[]（无子节，对照组） */
const NESTED_OUTLINE = [
  {
    chapter_no: '1',
    title: '项目概述',
    sections: [
      { title: '项目背景' },
      { title: '建设目标', children: [{ title: '总体目标' }] },
    ],
  },
  { chapter_no: '2', title: '技术方案', sections: ['总体架构'] },
];

/** 系统管理员邮箱（compose 默认 BID_ADMIN_USER_IDS 白名单值）+ 固定测试密码 */
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL || 'admin@bidagent.com';
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || 'E2eAdmin#12345';

/**
 * 获取系统管理员（注册固定白名单邮箱；已存在则回退登录固定密码），并校验
 * RBAC 配置端点可访问（system:manage）。白名单未配置/密码漂移时返回 null
 * （调用方 skip 并如实说明，不硬试）。
 */
async function ensureWhitelistAdmin(
  apiCtx: APIRequestContext,
): Promise<AuthedUser | null> {
  const reg = await apiCtx.post(api('/auth/register'), {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD, display_name: 'E2E Admin' },
  });
  if (reg.status() !== 200) {
    const login = await apiCtx.post(api('/auth/login'), {
      data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
    });
    if (login.status() !== 200) return null;
    const d = ((await login.json()) as BizResponse<{ access_token: string; refresh_token: string }>).data;
    const probe = await apiCtx.get(api('/rbac/permissions'), {
      headers: { Authorization: `Bearer ${d.access_token}` },
    });
    return probe.status() === 200
      ? {
          email: ADMIN_EMAIL,
          password: ADMIN_PASSWORD,
          displayName: 'E2E Admin',
          userId: '',
          accessToken: d.access_token,
          refreshToken: d.refresh_token,
        }
      : null;
  }
  const regBody = (await reg.json()) as BizResponse<{ id: string }>;
  const login = await apiCtx.post(api('/auth/login'), {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  });
  if (login.status() !== 200) return null;
  const d2 = ((await login.json()) as BizResponse<{ access_token: string; refresh_token: string }>).data;
  const probe = await apiCtx.get(api('/rbac/permissions'), { headers: bearer({ accessToken: d2.access_token } as AuthedUser) });
  if (probe.status() !== 200) return null;
  return {
    email: ADMIN_EMAIL,
    password: ADMIN_PASSWORD,
    displayName: 'E2E Admin',
    userId: regBody.data.id,
    accessToken: d2.access_token,
    refreshToken: d2.refresh_token,
  };
}

/** 上传招标文件并等待解析完成（评分点入库），与 division-flow 同构 */
async function uploadParsedTender(
  apiCtx: APIRequestContext,
  user: AuthedUser,
  projectId: string,
): Promise<void> {
  const resp = await apiCtx.post(api(`/projects/${projectId}/documents?doc_type=tender_file`), {
    headers: bearer(user),
    multipart: {
      file: {
        name: 'tender-subdiv.pdf',
        mimeType: 'application/pdf',
        buffer: buildMinimalPdf('E2E SubDivision Tender. Scoring: technical 60, price 40.'),
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
}

/** 启动工作流 → 确认评分点 → 推进到 confirm_outline 挂起 */
async function driveToOutlineInterrupt(
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
    60_000,
  );
}

/** 确认嵌套大纲：轮询骨架落库（outline 含子节）→ 等 review_request 图空闲（避免 checkpoint 并发写） */
async function confirmNestedOutlineIdle(
  apiCtx: APIRequestContext,
  user: AuthedUser,
  projectId: string,
): Promise<void> {
  const confirm = await apiCtx.post(api(`/projects/${projectId}/workflow/confirm-outline`), {
    headers: bearer(user),
    data: { outline: NESTED_OUTLINE },
  });
  expect(confirm.status(), `确认大纲失败: ${await confirm.text()}`).toBe(200);
  await waitForWorkflowStatus(
    apiCtx,
    user,
    projectId,
    (s) => JSON.stringify(s.outline).includes('项目背景'),
    30_000,
  );
  await waitForWorkflowStatus(
    apiCtx,
    user,
    projectId,
    (s) => s.interrupt?.type === 'review_request',
    120_000,
  );
}

/** 读取分工树（GET chapter-assignments：章行带 children） */
async function listAssignments(
  apiCtx: APIRequestContext,
  user: AuthedUser,
  projectId: string,
): Promise<AssignmentTreeItem[]> {
  const resp = await apiCtx.get(api(`/projects/${projectId}/chapter-assignments`), {
    headers: bearer(user),
  });
  expect(resp.status()).toBe(200);
  return ((await resp.json()) as BizResponse<{ items: AssignmentTreeItem[] }>).data.items;
}

test.beforeEach(async ({ api: apiCtx }) => {
  test.skip(
    !(await backendHealthy(apiCtx)),
    '后端服务未就绪（E2E_API_URL 不可达 /health）。请先 docker compose 启动基础设施并运行后端。',
  );
});

test.describe('子节级分工全链路（阶段 B）', () => {
  test('子节分配→领取→生成初稿→提交→owner 审核通过（API+UI）', async ({
    api: apiCtx,
    page,
  }) => {
    test.skip(!llmMockEnabled(), '前置条件：需后端 LLM mock 开启（库内 llm_mock 或 BID_LLM_MOCK）。');

    const owner = await registerAndLogin(apiCtx, 'subdiv-owner');
    const member = await registerAndLogin(apiCtx, 'subdiv-member');
    const project = await createProject(apiCtx, owner);
    const add = await apiCtx.post(api(`/projects/${project.id}/members`), {
      headers: bearer(owner),
      data: { email: member.email },
    });
    expect(add.status()).toBe(200);

    // 前置：解析 → 评分点确认 → 嵌套大纲确认（章节生成完，图空闲）
    await uploadParsedTender(apiCtx, owner, project.id);
    await driveToOutlineInterrupt(apiCtx, owner, project.id);
    await confirmNestedOutlineIdle(apiCtx, owner, project.id);

    // 1. owner 分配子节 1.1 → 章聚合行（id/assignee=null）+ children=['1.1']
    const assign = await apiCtx.post(api(`/projects/${project.id}/chapter-assignments`), {
      headers: bearer(owner),
      data: [{ chapter_no: '1.1', title: '项目背景', assignee_id: member.userId }],
    });
    expect(assign.status(), `分配失败: ${await assign.text()}`).toBe(200);
    let tree = await listAssignments(apiCtx, owner, project.id);
    const ch1 = tree.find((t) => t.chapter_no === '1');
    expect(ch1, '章聚合行应存在').toBeDefined();
    expect(ch1!.id, '无自身分工的章行 id 应为 null').toBeNull();
    expect(ch1!.assignee_id).toBeNull();
    expect(ch1!.children.map((c) => c.chapter_no)).toEqual(['1.1']);
    expect(ch1!.total).toBe(1);
    expect(ch1!.approved_count).toBe(0);
    const sub = ch1!.children[0];
    expect(sub.assignee_id).toBe(member.userId);
    expect(sub.status).toBe('pending');
    expect(sub.title).toBe('项目背景');
    const subId = sub.id as string;

    // 2. 成员领取子节 → in_progress
    const accept = await apiCtx.post(
      api(`/projects/${project.id}/chapter-assignments/${subId}/accept`),
      { headers: bearer(member) },
    );
    expect(accept.status(), `领取失败: ${await accept.text()}`).toBe(200);
    expect(((await accept.json()) as BizResponse<{ status: string }>).data.status).toBe(
      'in_progress',
    );

    // 3. 生成子节初稿（mock：父章路由生成 → 子节切分）
    const gen = await apiCtx.post(
      api(`/projects/${project.id}/chapter-assignments/${subId}/generate`),
      { headers: bearer(member) },
    );
    expect(gen.status(), `生成初稿失败: ${await gen.text()}`).toBe(200);
    const content = ((await gen.json()) as BizResponse<{ content: string }>).data.content;
    expect(content.length, 'mock 初稿应非空').toBeGreaterThan(0);

    // 4. 提交待审 → submitted
    const submit = await apiCtx.post(
      api(`/projects/${project.id}/chapter-assignments/${subId}/submit`),
      { headers: bearer(member) },
    );
    expect(submit.status(), `提交失败: ${await submit.text()}`).toBe(200);
    expect(((await submit.json()) as BizResponse<{ status: string }>).data.status).toBe(
      'submitted',
    );

    // 5. UI：成员分工页「我的任务」展示子节 1.1 待审核
    try {
      await page.goto('/login', { timeout: 10_000 });
    } catch {
      test.skip(true, '前端未就绪（E2E_BASE_URL 不可达），跳过 UI 断言。');
      return;
    }
    await page.addInitScript((token) => {
      localStorage.setItem('access_token', token);
    }, member.accessToken);
    await page.goto(`/projects/${project.id}/division`);
    const task = page.locator('.task-item').filter({ hasText: '1.1 项目背景' });
    await expect(task).toBeVisible({ timeout: 30_000 });
    await expect(task).toContainText('待审核');

    // 6. owner 审核通过 → 子节 approved；章聚合行 approved_count=1
    const approve = await apiCtx.post(
      api(`/projects/${project.id}/chapter-assignments/${subId}/review`),
      { headers: bearer(owner), data: { action: 'approved', comment: '' } },
    );
    expect(approve.status(), `审核通过失败: ${await approve.text()}`).toBe(200);
    await expect
      .poll(
        async () => {
          tree = await listAssignments(apiCtx, owner, project.id);
          const c = tree.find((t) => t.chapter_no === '1');
          return c?.children[0]?.status;
        },
        { timeout: 15_000 },
      )
      .toBe('approved');
    tree = await listAssignments(apiCtx, owner, project.id);
    const after = tree.find((t) => t.chapter_no === '1')!;
    expect(after.status, '聚合状态应变为 approved').toBe('approved');
    expect(after.approved_count).toBe(1);
    await page.reload();
    await expect(
      page.locator('.task-item').filter({ hasText: '1.1 项目背景' }),
    ).toContainText('已通过', { timeout: 30_000 });
  });

  test('章级分配自动展开为全部子节（替换旧分工并重置 pending）', async ({
    api: apiCtx,
  }) => {
    test.skip(!llmMockEnabled(), '前置条件：需后端 LLM mock 开启（库内 llm_mock 或 BID_LLM_MOCK）。');

    const owner = await registerAndLogin(apiCtx, 'expand-owner');
    const memberA = await registerAndLogin(apiCtx, 'expand-memberA');
    const memberB = await registerAndLogin(apiCtx, 'expand-memberB');
    const project = await createProject(apiCtx, owner);
    for (const u of [memberA, memberB]) {
      const add = await apiCtx.post(api(`/projects/${project.id}/members`), {
        headers: bearer(owner),
        data: { email: u.email },
      });
      expect(add.status()).toBe(200);
    }
    await uploadParsedTender(apiCtx, owner, project.id);
    await driveToOutlineInterrupt(apiCtx, owner, project.id);
    await confirmNestedOutlineIdle(apiCtx, owner, project.id);

    // 1. 直分子节 1.1 → memberB（供后续章级替换的旧子节分工）
    const assign1 = await apiCtx.post(api(`/projects/${project.id}/chapter-assignments`), {
      headers: bearer(owner),
      data: [{ chapter_no: '1.1', title: '项目背景', assignee_id: memberB.userId }],
    });
    expect(assign1.status(), `子节分配失败: ${await assign1.text()}`).toBe(200);
    let tree = await listAssignments(apiCtx, owner, project.id);
    expect(tree.find((t) => t.chapter_no === '1')?.children.map((c) => c.chapter_no)).toEqual([
      '1.1',
    ]);

    // 2. 章级分配 "1" → memberA：自动展开全部子节，旧分工被替换重置
    const assign2 = await apiCtx.post(api(`/projects/${project.id}/chapter-assignments`), {
      headers: bearer(owner),
      data: [{ chapter_no: '1', title: '项目概述', assignee_id: memberA.userId }],
    });
    expect(assign2.status(), `章级分配失败: ${await assign2.text()}`).toBe(200);
    // 轮询容忍提交竞态：展开全部子节 + 负责人替换 + pending 重置
    await expect
      .poll(
        async () => {
          tree = await listAssignments(apiCtx, owner, project.id);
          return tree.find((t) => t.chapter_no === '1')?.children.length;
        },
        { timeout: 15_000 },
      )
      .toBe(3);
    tree = await listAssignments(apiCtx, owner, project.id);
    const ch1 = tree.find((t) => t.chapter_no === '1')!;
    expect(ch1.children.map((c) => c.chapter_no)).toEqual(['1.1', '1.2', '1.2.1']);
    for (const c of ch1.children) {
      expect(c.assignee_id, `子节 ${c.chapter_no} 应替换负责人`).toBe(memberA.userId);
      expect(c.status, `子节 ${c.chapter_no} 应重置 pending`).toBe('pending');
    }
    expect(ch1.total).toBe(3);
    expect(ch1.approved_count).toBe(0);
    // 章 2（string[] 无子节，未分工）不出现在树中
    expect(tree.find((t) => t.chapter_no === '2'), '无分工章不应出现').toBeUndefined();
  });

  test('越权 403 矩阵：非 owner 分配/非 assignee 操作子节/未分工章节编辑', async ({
    api: apiCtx,
  }) => {
    test.skip(!llmMockEnabled(), '前置条件：需后端 LLM mock 开启（库内 llm_mock 或 BID_LLM_MOCK）。');

    const owner = await registerAndLogin(apiCtx, 'forbid-owner');
    const memberA = await registerAndLogin(apiCtx, 'forbid-memberA');
    const memberB = await registerAndLogin(apiCtx, 'forbid-memberB');
    const outsider = await registerAndLogin(apiCtx, 'forbid-outsider');
    const project = await createProject(apiCtx, owner);
    for (const u of [memberA, memberB]) {
      const add = await apiCtx.post(api(`/projects/${project.id}/members`), {
        headers: bearer(owner),
        data: { email: u.email },
      });
      expect(add.status()).toBe(200);
    }
    await uploadParsedTender(apiCtx, owner, project.id);
    await driveToOutlineInterrupt(apiCtx, owner, project.id);
    await confirmNestedOutlineIdle(apiCtx, owner, project.id);
    // owner 分配子节 1.1 给 memberA
    const assign = await apiCtx.post(api(`/projects/${project.id}/chapter-assignments`), {
      headers: bearer(owner),
      data: [{ chapter_no: '1.1', title: '项目背景', assignee_id: memberA.userId }],
    });
    expect(assign.status()).toBe(200);
    let tree = await listAssignments(apiCtx, owner, project.id);
    const subId = tree.find((t) => t.chapter_no === '1')!.children[0].id as string;

    // 非 owner（memberA）分配 → 403
    const forbiddenAssign = await apiCtx.post(api(`/projects/${project.id}/chapter-assignments`), {
      headers: bearer(memberA),
      data: [{ chapter_no: '1.2', title: '建设目标', assignee_id: memberA.userId }],
    });
    expect(forbiddenAssign.status()).toBe(403);

    // 非项目成员读取分工树 → 403
    const forbiddenList = await apiCtx.get(api(`/projects/${project.id}/chapter-assignments`), {
      headers: bearer(outsider),
    });
    expect(forbiddenList.status()).toBe(403);
    // 非 assignee（memberB）操作他人子节：领取/生成/提交 → 403
    const forbiddenAccept = await apiCtx.post(
      api(`/projects/${project.id}/chapter-assignments/${subId}/accept`),
      { headers: bearer(memberB) },
    );
    expect(forbiddenAccept.status()).toBe(403);
    const forbiddenGen = await apiCtx.post(
      api(`/projects/${project.id}/chapter-assignments/${subId}/generate`),
      { headers: bearer(memberB) },
    );
    expect(forbiddenGen.status()).toBe(403);
    const forbiddenSubmit = await apiCtx.post(
      api(`/projects/${project.id}/chapter-assignments/${subId}/submit`),
      { headers: bearer(memberB) },
    );
    expect(forbiddenSubmit.status()).toBe(403);

    // 非 assignee 编辑已分工子节 → 403（可视不可改）
    const forbiddenEditSub = await apiCtx.put(
      api(`/projects/${project.id}/workflow/sections/1.1`),
      { data: { content: '越权编辑子节' }, headers: bearer(memberB) },
    );
    expect(forbiddenEditSub.status(), `非 assignee 编辑子节应 403: ${await forbiddenEditSub.text()}`).toBe(403);
    // 未分工章节（章 2）非 owner 编辑 → 403（收紧：未分工仅 owner 可编辑）
    const forbiddenEditCh = await apiCtx.put(
      api(`/projects/${project.id}/workflow/sections/2`),
      { data: { content: '越权编辑章' }, headers: bearer(memberB) },
    );
    expect(forbiddenEditCh.status()).toBe(403);

    // 正例对照：assignee 与 owner 可编辑该子节（章 1 已生成，保存落库）
    const okEditAssignee = await apiCtx.put(
      api(`/projects/${project.id}/workflow/sections/1.1`),
      { data: { content: 'assignee 编辑内容' }, headers: bearer(memberA) },
    );
    expect(okEditAssignee.status(), `assignee 编辑子节应成功: ${await okEditAssignee.text()}`).toBe(200);
    const okEditOwner = await apiCtx.put(
      api(`/projects/${project.id}/workflow/sections/1.1`),
      { data: { content: 'owner 编辑内容' }, headers: bearer(owner) },
    );
    expect(okEditOwner.status()).toBe(200);
  });
});

test.describe('RBAC 配置端点权限矩阵（阶段 A）', () => {
  test('member/kb_admin 访问权限配置端点 403，admin 200（读写）', async ({
    api: apiCtx,
  }) => {
    const member = await registerAndLogin(apiCtx, 'rbac-member');
    const kbCandidate = await registerAndLogin(apiCtx, 'rbac-kb');
    const admin = await ensureWhitelistAdmin(apiCtx);
    test.skip(
      admin === null,
      '系统管理员不可用（admin@bidagent.com 未注册/BID_ADMIN_USER_IDS 白名单未命中/密码漂移），跳过 RBAC 矩阵断言。',
    );

    // member 访问三个配置端点 → 一律 403
    const r1 = await apiCtx.get(api('/rbac/permissions'), { headers: bearer(member) });
    expect(r1.status()).toBe(403);
    const r2 = await apiCtx.get(api('/rbac/roles/member/permissions'), { headers: bearer(member) });
    expect(r2.status()).toBe(403);
    const r3 = await apiCtx.put(api('/rbac/roles/member/permissions'), {
      headers: bearer(member),
      data: { codes: [] },
    });
    expect(r3.status()).toBe(403);
    // admin（白名单）：权限目录 + 角色映射 200
    const okCatalog = await apiCtx.get(api('/rbac/permissions'), { headers: bearer(admin!) });
    expect(okCatalog.status(), `admin 应可访问权限目录: ${await okCatalog.text()}`).toBe(200);
    const catalog = (
      (await okCatalog.json()) as BizResponse<{ items: Array<{ code: string; category: string }> }>
    ).data.items;
    expect(catalog.length, '权限点目录应非空').toBeGreaterThan(0);
    expect(catalog.map((i) => i.code)).toContain('system:manage');

    const okGet = await apiCtx.get(api('/rbac/roles/member/permissions'), {
      headers: bearer(admin!),
    });
    expect(okGet.status()).toBe(200);
    const roleBody = (
      (await okGet.json()) as BizResponse<{ role: string; codes: string[] }>
    ).data;
    expect(roleBody.role).toBe('member');

    // 幂等回写（原 codes 全量覆盖）→ 200
    const okPut = await apiCtx.put(api('/rbac/roles/member/permissions'), {
      headers: bearer(admin!),
      data: { codes: roleBody.codes },
    });
    expect(okPut.status(), `admin 回写角色权限应成功: ${await okPut.text()}`).toBe(200);
    // kb_admin：admin 授角色后访问配置端点同样 403（system:manage 仅 admin）
    const promote = await apiCtx.put(api(`/users/${kbCandidate.userId}/role`), {
      headers: bearer(admin!),
      data: { role: 'kb_admin' },
    });
    expect(promote.status(), `提权 kb_admin 失败: ${await promote.text()}`).toBe(200);
    const kbForbidden = await apiCtx.get(api('/rbac/permissions'), {
      headers: bearer(kbCandidate),
    });
    expect(kbForbidden.status()).toBe(403);
  });
});
