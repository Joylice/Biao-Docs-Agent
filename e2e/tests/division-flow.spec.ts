/**
 * E2E：章节分工协作全链路（需求 B）+ 格式要求提取/编辑（需求 A 存储面）
 *
 * 分工全链路：上传解析 → 工作流推进到大纲待确认 → owner 分配章节 →
 * 成员领取 → 生成初稿（mock）→ 编辑保存 → 提交 → owner 打回（附意见）→
 * 重新领取/提交 → owner 通过。
 * 权限：非 owner 分配 403；assignee 非成员 404；非 assignee 编辑已分配章节 403；
 * 非 assignee 领取 403。
 *
 * 对齐后端路由：backend/app/api/division.py（chapter-assignments 系列端点）
 * + api/workflow.py save_section_edit（章节级可视不可改）
 * + api/documents.py format-requirements（GET/PUT）
 *
 * 前置条件：后端 LLM mock 开启（库内 llm_settings.llm_mock=true 或
 * BID_LLM_MOCK=true），否则 skip（解析/大纲/初稿生成依赖 mock 分支）。
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

interface AssignmentItem {
  id: string;
  chapter_no: string;
  title: string;
  assignee_id: string;
  assignee_name: string;
  status: string;
  section_status: string | null;
  review_comment: string | null;
}

/** 上传招标文件并等待解析完成（评分点入库），与 parse-confirm-flow 同构 */
async function uploadParsedTender(
  apiCtx: APIRequestContext,
  user: AuthedUser,
  projectId: string,
): Promise<string> {
  const resp = await apiCtx.post(api(`/projects/${projectId}/documents?doc_type=tender_file`), {
    headers: bearer(user),
    multipart: {
      file: {
        name: 'tender-division.pdf',
        mimeType: 'application/pdf',
        buffer: buildMinimalPdf('E2E Division Tender. Scoring: technical 60, price 40.'),
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

/** 驱动工作流到 confirm_outline 挂起并返回大纲首章 */
async function driveToOutline(
  apiCtx: APIRequestContext,
  user: AuthedUser,
  projectId: string,
): Promise<{ chapter_no: string; title: string }> {
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
  const status = await waitForWorkflowStatus(
    apiCtx,
    user,
    projectId,
    (s) => s.interrupt?.type === 'confirm_outline',
    60_000,
  );
  expect(status.outline.length, `mock 大纲应至少含一章（error=${status.error || ''}）`).toBeGreaterThan(0);
  return { chapter_no: status.outline[0].chapter_no, title: status.outline[0].title };
}

/** 读取分工列表 */
async function listAssignments(
  apiCtx: APIRequestContext,
  user: AuthedUser,
  projectId: string,
): Promise<AssignmentItem[]> {
  const resp = await apiCtx.get(api(`/projects/${projectId}/chapter-assignments`), {
    headers: bearer(user),
  });
  expect(resp.status()).toBe(200);
  return ((await resp.json()) as BizResponse<{ items: AssignmentItem[] }>).data.items;
}

test.beforeEach(async ({ api: apiCtx }) => {
  test.skip(
    !(await backendHealthy(apiCtx)),
    '后端服务未就绪（E2E_API_URL 不可达 /health）。请先 docker compose 启动基础设施并运行后端。',
  );
});

test.describe('章节分工协作全链路', () => {
  test('分配→领取→生成初稿→编辑→提交→打回→重提→通过', async ({ api: apiCtx }) => {
    test.skip(!llmMockEnabled(), '前置条件：需后端 LLM mock 开启（库内 llm_mock 或 BID_LLM_MOCK）。');

    const owner = await registerAndLogin(apiCtx, 'div-owner');
    const member = await registerAndLogin(apiCtx, 'div-member');
    const project = await createProject(apiCtx, owner);

    // 加协作者（assignee 必须是项目成员）
    const add = await apiCtx.post(api(`/projects/${project.id}/members`), {
      headers: bearer(owner),
      data: { email: member.email },
    });
    expect(add.status()).toBe(200);

    // 前置：招标文件解析入库评分点（工作流启动依赖）
    await uploadParsedTender(apiCtx, owner, project.id);
    const chapter = await driveToOutline(apiCtx, owner, project.id);

    // 1. owner 分配章节 → 列表含 pending 记录
    const assign = await apiCtx.post(api(`/projects/${project.id}/chapter-assignments`), {
      headers: bearer(owner),
      data: [{ chapter_no: chapter.chapter_no, title: chapter.title, assignee_id: member.userId }],
    });
    expect(assign.status(), `分配失败: ${await assign.text()}`).toBe(200);
    let items = await listAssignments(apiCtx, member, project.id);
    expect(items).toHaveLength(1);
    expect(items[0].assignee_id).toBe(member.userId);
    expect(items[0].status).toBe('pending');

    // 提交竞态窗口（get_db 响应后 commit）：轮询直到 assignee 视角可见
    const assignmentId = items[0].id;

    // 2. 成员领取 → in_progress
    const accept = await apiCtx.post(
      api(`/projects/${project.id}/chapter-assignments/${assignmentId}/accept`),
      { headers: bearer(member) },
    );
    expect(accept.status(), `领取失败: ${await accept.text()}`).toBe(200);
    expect(((await accept.json()) as BizResponse<{ status: string }>).data.status).toBe(
      'in_progress',
    );

    // 3. 生成初稿（mock 确定性产出）
    const gen = await apiCtx.post(
      api(`/projects/${project.id}/chapter-assignments/${assignmentId}/generate`),
      { headers: bearer(member) },
    );
    expect(gen.status(), `生成初稿失败: ${await gen.text()}`).toBe(200);
    const content = ((await gen.json()) as BizResponse<{ content: string }>).data.content;
    expect(content.length, 'mock 初稿应非空').toBeGreaterThan(0);

    // 4. 人工编辑保存（PUT sections，assignee 有权）
    const edited = `${content}\n\n（人工编制补充：实施计划与质量保障措施。）`;
    const save = await apiCtx.put(
      api(`/projects/${project.id}/workflow/sections/${chapter.chapter_no}`),
      { data: { content: edited }, headers: bearer(member) },
    );
    expect(save.status(), `保存编辑失败: ${await save.text()}`).toBe(200);

    // 5. 提交待审 → submitted
    const submit = await apiCtx.post(
      api(`/projects/${project.id}/chapter-assignments/${assignmentId}/submit`),
      { headers: bearer(member) },
    );
    expect(submit.status(), `提交失败: ${await submit.text()}`).toBe(200);
    expect(((await submit.json()) as BizResponse<{ status: string }>).data.status).toBe(
      'submitted',
    );

    // 6. owner 打回（附意见）
    const reject = await apiCtx.post(
      api(`/projects/${project.id}/chapter-assignments/${assignmentId}/review`),
      {
        headers: bearer(owner),
        data: { action: 'rejected', comment: '缺少质量保障措施，请补充' },
      },
    );
    expect(reject.status(), `打回失败: ${await reject.text()}`).toBe(200);
    items = await listAssignments(apiCtx, owner, project.id);
    expect(items[0].status).toBe('rejected');
    expect(items[0].review_comment).toBe('缺少质量保障措施，请补充');

    // 7. 重新领取 → 重新提交（rejected 回退可重编）
    const reaccept = await apiCtx.post(
      api(`/projects/${project.id}/chapter-assignments/${assignmentId}/accept`),
      { headers: bearer(member) },
    );
    expect(reaccept.status()).toBe(200);
    const resubmit = await apiCtx.post(
      api(`/projects/${project.id}/chapter-assignments/${assignmentId}/submit`),
      { headers: bearer(member) },
    );
    expect(resubmit.status()).toBe(200);

    // 8. owner 通过 → approved
    const approve = await apiCtx.post(
      api(`/projects/${project.id}/chapter-assignments/${assignmentId}/review`),
      { headers: bearer(owner), data: { action: 'approved', comment: '' } },
    );
    expect(approve.status(), `审核通过失败: ${await approve.text()}`).toBe(200);
    items = await listAssignments(apiCtx, owner, project.id);
    expect(items[0].status).toBe('approved');
    // 章节内容状态已落 proposal_sections（draft/final 任一均表示内容在库）
    expect(items[0].section_status, '章节内容应已入库').toBeTruthy();
  });

  test('权限：非 owner 分配 403；assignee 非成员 404；非 assignee 编辑/领取 403', async ({
    api: apiCtx,
  }) => {
    test.skip(!llmMockEnabled(), '前置条件：需后端 LLM mock 开启（库内 llm_mock 或 BID_LLM_MOCK）。');

    const owner = await registerAndLogin(apiCtx, 'div-owner2');
    const memberA = await registerAndLogin(apiCtx, 'div-memberA');
    const memberB = await registerAndLogin(apiCtx, 'div-memberB');
    const outsider = await registerAndLogin(apiCtx, 'div-outsider');
    const project = await createProject(apiCtx, owner);

    for (const u of [memberA, memberB]) {
      const add = await apiCtx.post(api(`/projects/${project.id}/members`), {
        headers: bearer(owner),
        data: { email: u.email },
      });
      expect(add.status()).toBe(200);
    }

    // 前置：招标文件解析入库评分点（工作流启动依赖）
    await uploadParsedTender(apiCtx, owner, project.id);
    const chapter = await driveToOutline(apiCtx, owner, project.id);

    // 非 owner 分配 → 403（4003）
    const forbiddenAssign = await apiCtx.post(api(`/projects/${project.id}/chapter-assignments`), {
      headers: bearer(memberA),
      data: [{ chapter_no: chapter.chapter_no, title: chapter.title, assignee_id: memberA.userId }],
    });
    expect(forbiddenAssign.status()).toBe(403);

    // assignee 非项目成员 → 404（4004）
    const badAssign = await apiCtx.post(api(`/projects/${project.id}/chapter-assignments`), {
      headers: bearer(owner),
      data: [
        { chapter_no: chapter.chapter_no, title: chapter.title, assignee_id: outsider.userId },
      ],
    });
    expect(badAssign.status()).toBe(404);

    // owner 正常分配给 memberA
    const assign = await apiCtx.post(api(`/projects/${project.id}/chapter-assignments`), {
      headers: bearer(owner),
      data: [{ chapter_no: chapter.chapter_no, title: chapter.title, assignee_id: memberA.userId }],
    });
    expect(assign.status()).toBe(200);
    const items = await listAssignments(apiCtx, owner, project.id);
    const assignmentId = items[0].id;

    // 非 assignee（memberB）编辑已分配章节 → 403（可视不可改）
    const forbiddenEdit = await apiCtx.put(
      api(`/projects/${project.id}/workflow/sections/${chapter.chapter_no}`),
      { data: { content: '越权编辑内容' }, headers: bearer(memberB) },
    );
    expect(forbiddenEdit.status(), `非 assignee 编辑应 403: ${await forbiddenEdit.text()}`).toBe(
      403,
    );

    // 非 assignee 领取 → 403
    const forbiddenAccept = await apiCtx.post(
      api(`/projects/${project.id}/chapter-assignments/${assignmentId}/accept`),
      { headers: bearer(memberB) },
    );
    expect(forbiddenAccept.status()).toBe(403);

    // 非项目成员读取分工列表 → 403
    const forbiddenList = await apiCtx.get(api(`/projects/${project.id}/chapter-assignments`), {
      headers: bearer(outsider),
    });
    expect(forbiddenList.status()).toBe(403);
  });
});

test.describe('格式要求：提取 + 人工编辑幂等覆盖', () => {
  test('解析后提取格式要求，PUT 幂等覆盖并回读一致', async ({ api: apiCtx }) => {
    test.skip(!llmMockEnabled(), '前置条件：需后端 LLM mock 开启（库内 llm_mock 或 BID_LLM_MOCK）。');

    const user = await registerAndLogin(apiCtx, 'fmt-user');
    const project = await createProject(apiCtx, user);
    const docId = await uploadParsedTender(apiCtx, user, project.id);

    // 解析自动提取（mock 按 schema 产出条目；未知分类清洗为 other）
    const get1 = await apiCtx.get(
      api(`/projects/${project.id}/documents/${docId}/format-requirements`),
      { headers: bearer(user) },
    );
    expect(get1.status()).toBe(200);
    const items1 = ((await get1.json()) as BizResponse<{ items: unknown[] }>).data.items;
    expect(Array.isArray(items1)).toBe(true);
    expect(items1.length, 'mock 解析应产出格式要求条目').toBeGreaterThan(0);

    // 人工编辑：幂等覆盖为自定义条目
    const custom = [
      { category: 'font_body', requirement: '正文小四号仿宋_GB2312' },
      { category: 'line_spacing', requirement: '1.5 倍行距' },
      { category: 'margin', requirement: '上下 2.54cm，左右 3.17cm' },
    ];
    const put = await apiCtx.put(
      api(`/projects/${project.id}/documents/${docId}/format-requirements`),
      { headers: bearer(user), data: { format_requirements: custom } },
    );
    expect(put.status(), `保存失败: ${await put.text()}`).toBe(200);
    const saved = ((await put.json()) as BizResponse<{ items: typeof custom }>).data.items;
    expect(saved).toEqual(custom);

    // 回读一致（含空条目清洗 + 未知分类归 other）
    const put2 = await apiCtx.put(
      api(`/projects/${project.id}/documents/${docId}/format-requirements`),
      {
        headers: bearer(user),
        data: {
          format_requirements: [
            ...custom,
            { category: 'font_body', requirement: '   ' },
            { category: 'unknown_cat', requirement: 'A4 纵向打印' },
          ],
        },
      },
    );
    expect(put2.status()).toBe(200);
    const get2 = await apiCtx.get(
      api(`/projects/${project.id}/documents/${docId}/format-requirements`),
      { headers: bearer(user) },
    );
    const items2 = (
      (await get2.json()) as BizResponse<{ items: Array<{ category: string; requirement: string }> }>
    ).data.items;
    expect(items2).toHaveLength(4); // 空条目被清洗
    expect(items2.map((i) => i.category)).toContain('other'); // 未知分类归入 other
  });

  test('非招标文件读写格式要求被拒（4010 → 400）', async ({ api: apiCtx }) => {
    const user = await registerAndLogin(apiCtx, 'fmt-user2');
    const project = await createProject(apiCtx, user);

    // 上传资料库素材（kb_material 不支持格式要求）
    const resp = await apiCtx.post(api(`/projects/${project.id}/documents?doc_type=kb_material`), {
      headers: bearer(user),
      multipart: {
        file: {
          name: 'material.pdf',
          mimeType: 'application/pdf',
          buffer: buildMinimalPdf('E2E material doc.'),
        },
      },
    });
    expect(resp.status()).toBe(200);
    const docId = ((await resp.json()) as BizResponse<{ id: string }>).data.id;

    const get = await apiCtx.get(
      api(`/projects/${project.id}/documents/${docId}/format-requirements`),
      { headers: bearer(user) },
    );
    // BizError 4010 → HTTP 400
    expect(get.status()).toBe(400);
  });
});
