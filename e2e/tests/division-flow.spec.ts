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
  /** outline 子节（阶段 5：2 级目录展示用，分工粒度仍为章级） */
  sections?: string[];
  /** 提交人标注（阶段 5：审阅页展示用，即负责人） */
  submitted_by_name?: string;
}

/** 1x1 透明 PNG（章节插图上传用例） */
const PNG_1X1 = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64',
);

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
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

test.describe('章节编制工具栏：AI 辅助生成 / 暂停 / 图片 / 批注（阶段 2~4）', () => {
  /** 前置：建项目 + 分工一章给 member 并领取（辅助生成要求 in_progress） */
  async function setupAssignedInProgress(apiCtx: APIRequestContext) {
    const owner = await registerAndLogin(apiCtx, 'tb-owner');
    const member = await registerAndLogin(apiCtx, 'tb-member');
    const memberB = await registerAndLogin(apiCtx, 'tb-member-b');
    const project = await createProject(apiCtx, owner);
    for (const u of [member, memberB]) {
      const add = await apiCtx.post(api(`/projects/${project.id}/members`), {
        headers: bearer(owner),
        data: { email: u.email },
      });
      expect(add.status()).toBe(200);
    }
    await uploadParsedTender(apiCtx, owner, project.id);
    const chapter = await driveToOutline(apiCtx, owner, project.id);
    const assign = await apiCtx.post(api(`/projects/${project.id}/chapter-assignments`), {
      headers: bearer(owner),
      data: [{ chapter_no: chapter.chapter_no, title: chapter.title, assignee_id: member.userId }],
    });
    expect(assign.status()).toBe(200);
    const items = await listAssignments(apiCtx, owner, project.id);
    const assignmentId = items[0].id;
    const accept = await apiCtx.post(
      api(`/projects/${project.id}/chapter-assignments/${assignmentId}/accept`),
      { headers: bearer(member) },
    );
    expect(accept.status()).toBe(200);
    return { owner, member, memberB, project, chapter, assignmentId };
  }

  test('辅助生成：append/overwrite 落库 + 非 assignee 403 + stop 可中断', async ({
    api: apiCtx,
  }) => {
    test.skip(!llmMockEnabled(), '前置条件：需后端 LLM mock 开启（库内 llm_mock 或 BID_LLM_MOCK）。');
    const { member, memberB, project, assignmentId } = await setupAssignedInProgress(apiCtx);

    // append：自定义提示词 + 追加模式（mock 确定性产出）
    const append = await apiCtx.post(
      api(`/projects/${project.id}/chapter-assignments/${assignmentId}/assist-generate`),
      { headers: bearer(member), data: { prompt: '补充质量保障措施', mode: 'append' } },
    );
    expect(append.status(), `辅助生成(append)失败: ${await append.text()}`).toBe(200);
    const appendData = (
      (await append.json()) as BizResponse<{ content: string; stopped: boolean; mode: string }>
    ).data;
    expect(appendData.content.length, 'mock 辅助生成应产出内容').toBeGreaterThan(0);
    expect(appendData.mode).toBe('append');
    expect(appendData.stopped).toBe(false);

    // overwrite：整章覆盖
    const overwrite = await apiCtx.post(
      api(`/projects/${project.id}/chapter-assignments/${assignmentId}/assist-generate`),
      { headers: bearer(member), data: { prompt: '', mode: 'overwrite' } },
    );
    expect(overwrite.status()).toBe(200);
    expect(
      ((await overwrite.json()) as BizResponse<{ mode: string }>).data.mode,
    ).toBe('overwrite');

    // 非 assignee（memberB 是项目成员但非负责人）→ 403
    const forbidden = await apiCtx.post(
      api(`/projects/${project.id}/chapter-assignments/${assignmentId}/assist-generate`),
      { headers: bearer(memberB), data: { prompt: 'x', mode: 'append' } },
    );
    expect(forbidden.status()).toBe(403);

    // 暂停：发起生成后短时置位取消令牌；mock 生成极快，仅断言确定性蕴含：
    // stop 命中进行中任务（stopped=true）时，生成端点必返回 stopped=true（保留部分）
    const genPromise = apiCtx.post(
      api(`/projects/${project.id}/chapter-assignments/${assignmentId}/assist-generate`),
      { headers: bearer(member), data: { prompt: '', mode: 'append' } },
    );
    await sleep(150);
    const stop = await apiCtx.post(
      api(`/projects/${project.id}/chapter-assignments/${assignmentId}/assist-generate/stop`),
      { headers: bearer(member) },
    );
    expect(stop.status()).toBe(200);
    const stopHit = ((await stop.json()) as BizResponse<{ stopped: boolean }>).data.stopped;
    const gen = await genPromise;
    expect(gen.status()).toBe(200);
    const genData = ((await gen.json()) as BizResponse<{ stopped: boolean }>).data;
    if (stopHit) {
      expect(genData.stopped, 'stop 命中时生成端点应报告已暂停').toBe(true);
    }
    // 无进行中任务时 stop → stopped=false
    const stopAgain = await apiCtx.post(
      api(`/projects/${project.id}/chapter-assignments/${assignmentId}/assist-generate/stop`),
      { headers: bearer(member) },
    );
    expect(stopAgain.status()).toBe(200);
    expect(((await stopAgain.json()) as BizResponse<{ stopped: boolean }>).data.stopped).toBe(
      false,
    );
  });

  test('章节插图：上传返签名 URL + 签名读 + 非图片 400 + 跨项目 403', async ({
    api: apiCtx,
  }) => {
    const { member, project } = await setupAssignedInProgress(apiCtx);
    const outsider = await registerAndLogin(apiCtx, 'tb-outsider');

    const up = await apiCtx.post(api(`/projects/${project.id}/images`), {
      headers: bearer(member),
      multipart: {
        file: { name: 'chapter-fig.png', mimeType: 'image/png', buffer: PNG_1X1 },
      },
    });
    expect(up.status(), `图片上传失败: ${await up.text()}`).toBe(200);
    const upData = (
      (await up.json()) as BizResponse<{ storage_key: string; url: string }>
    ).data;
    expect(upData.storage_key).toContain(`images/${project.id}/`);
    expect(upData.url.length, '应返回签名 URL').toBeGreaterThan(0);

    // 签名读（同项目成员）
    const signed = await apiCtx.get(api(`/projects/${project.id}/images/signed`), {
      headers: bearer(member),
      params: { storage_key: upData.storage_key },
    });
    expect(signed.status()).toBe(200);
    expect(
      ((await signed.json()) as BizResponse<{ url: string }>).data.url.length,
    ).toBeGreaterThan(0);

    // 非图片类型 → 400
    const badType = await apiCtx.post(api(`/projects/${project.id}/images`), {
      headers: bearer(member),
      multipart: {
        file: {
          name: 'not-image.pdf',
          mimeType: 'application/pdf',
          buffer: buildMinimalPdf('not an image'),
        },
      },
    });
    expect(badType.status()).toBe(400);

    // 非项目成员：上传与签名读均 403
    const forbiddenUp = await apiCtx.post(api(`/projects/${project.id}/images`), {
      headers: bearer(outsider),
      multipart: {
        file: { name: 'chapter-fig.png', mimeType: 'image/png', buffer: PNG_1X1 },
      },
    });
    expect(forbiddenUp.status()).toBe(403);
    const forbiddenSigned = await apiCtx.get(api(`/projects/${project.id}/images/signed`), {
      headers: bearer(outsider),
      params: { storage_key: upData.storage_key },
    });
    expect(forbiddenSigned.status()).toBe(403);
  });

  test('章节批注：assignee/owner 可写，非 assignee 成员 403，列表正序', async ({
    api: apiCtx,
  }) => {
    const { owner, member, memberB, project, assignmentId } =
      await setupAssignedInProgress(apiCtx);

    // assignee 批注
    const ann1 = await apiCtx.post(
      api(`/projects/${project.id}/chapter-assignments/${assignmentId}/annotations`),
      { headers: bearer(member), data: { content: '实施计划需要补充里程碑' } },
    );
    expect(ann1.status(), `批注失败: ${await ann1.text()}`).toBe(200);
    // owner 批注
    const ann2 = await apiCtx.post(
      api(`/projects/${project.id}/chapter-assignments/${assignmentId}/annotations`),
      { headers: bearer(owner), data: { content: '请对齐评分点 3.2' } },
    );
    expect(ann2.status()).toBe(200);
    // 非 assignee 的项目成员（memberB）→ 403
    const forbidden = await apiCtx.post(
      api(`/projects/${project.id}/chapter-assignments/${assignmentId}/annotations`),
      { headers: bearer(memberB), data: { content: '越权批注' } },
    );
    expect(forbidden.status()).toBe(403);

    // 列表：项目成员可读，含批注人姓名
    const list = await apiCtx.get(
      api(`/projects/${project.id}/chapter-assignments/${assignmentId}/annotations`),
      { headers: bearer(memberB) },
    );
    expect(list.status()).toBe(200);
    const items = (
      (await list.json()) as BizResponse<{
        items: Array<{ content: string; created_by_name: string }>;
      }>
    ).data.items;
    expect(items.length).toBe(2);
    expect(items.map((i) => i.content)).toEqual([
      '实施计划需要补充里程碑',
      '请对齐评分点 3.2',
    ]);
    expect(items[0].created_by_name).toBe(member.displayName);
  });
});

test.describe('2 级目录 + 提交人 + 意见回派（阶段 5）', () => {
  test('分工列表返回 sections 子节与 submitted_by_name', async ({ api: apiCtx }) => {
    test.skip(!llmMockEnabled(), '前置条件：需后端 LLM mock 开启（库内 llm_mock 或 BID_LLM_MOCK）。');

    const owner = await registerAndLogin(apiCtx, 'tree-owner');
    const member = await registerAndLogin(apiCtx, 'tree-member');
    const project = await createProject(apiCtx, owner);
    const add = await apiCtx.post(api(`/projects/${project.id}/members`), {
      headers: bearer(owner),
      data: { email: member.email },
    });
    expect(add.status()).toBe(200);

    await uploadParsedTender(apiCtx, owner, project.id);
    const chapter = await driveToOutline(apiCtx, owner, project.id);
    const assign = await apiCtx.post(api(`/projects/${project.id}/chapter-assignments`), {
      headers: bearer(owner),
      data: [{ chapter_no: chapter.chapter_no, title: chapter.title, assignee_id: member.userId }],
    });
    expect(assign.status()).toBe(200);

    const items = await listAssignments(apiCtx, member, project.id);
    expect(items).toHaveLength(1);
    expect(Array.isArray(items[0].sections), '分工列表应附 outline 子节数组').toBe(true);
    expect(items[0].submitted_by_name, '提交人标注应为负责人').toBe(member.displayName);
  });

  test('confirm-review 意见回派：命中分工 → rejected + next_phase=redispatch', async ({
    api: apiCtx,
  }) => {
    test.skip(!llmMockEnabled(), '前置条件：需后端 LLM mock 开启（库内 llm_mock 或 BID_LLM_MOCK）。');

    const owner = await registerAndLogin(apiCtx, 'rd-owner');
    const member = await registerAndLogin(apiCtx, 'rd-member');
    const project = await createProject(apiCtx, owner);
    const add = await apiCtx.post(api(`/projects/${project.id}/members`), {
      headers: bearer(owner),
      data: { email: member.email },
    });
    expect(add.status()).toBe(200);

    await uploadParsedTender(apiCtx, owner, project.id);
    const chapter = await driveToOutline(apiCtx, owner, project.id);
    const assign = await apiCtx.post(api(`/projects/${project.id}/chapter-assignments`), {
      headers: bearer(owner),
      data: [{ chapter_no: chapter.chapter_no, title: chapter.title, assignee_id: member.userId }],
    });
    expect(assign.status()).toBe(200);

    // 确认大纲 → 章节生成 → 审阅挂起
    const confirm = await apiCtx.post(api(`/projects/${project.id}/workflow/confirm-outline`), {
      headers: bearer(owner),
    });
    expect(confirm.status()).toBe(200);
    await waitForWorkflowStatus(
      apiCtx,
      owner,
      project.id,
      (s) => s.interrupt?.type === 'review_request',
      90_000,
    );

    // 意见命中已分工章节 → 回派负责人，不走 AI 重写
    const comment = '缺少质量保障措施，请补充后重新提交';
    const review = await apiCtx.post(api(`/projects/${project.id}/workflow/confirm-review`), {
      headers: bearer(owner),
      data: { action: 'feedback', feedback: { [chapter.chapter_no]: comment } },
    });
    expect(review.status(), `确认审阅失败: ${await review.text()}`).toBe(200);
    const reviewData = (
      (await review.json()) as BizResponse<{ action: string; next_phase: string }>
    ).data;
    expect(reviewData.action).toBe('redispatched');
    expect(reviewData.next_phase).toBe('redispatch');

    // 提交竞态窗口：轮询分工状态直到 rejected 可见
    const deadline = Date.now() + 10_000;
    let rejected = false;
    while (Date.now() < deadline && !rejected) {
      const items = await listAssignments(apiCtx, member, project.id);
      rejected = items.length > 0 && items[0].status === 'rejected';
      if (rejected) {
        expect(items[0].review_comment).toBe(comment);
      } else {
        await sleep(500);
      }
    }
    expect(rejected, '回派后 assignment 应置 rejected').toBe(true);
  });
});

test.describe('版本库：快照 / 下载 / 归档（阶段 6）', () => {
  /** 驱动到 review_request 挂起（chapters 非空，满足快照前置） */
  async function driveToReview(apiCtx: APIRequestContext, user: AuthedUser, projectId: string) {
    await uploadParsedTender(apiCtx, user, projectId);
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
    await apiCtx.post(api(`/projects/${projectId}/workflow/confirm-outline`), {
      headers: bearer(user),
    });
    return waitForWorkflowStatus(
      apiCtx,
      user,
      projectId,
      (s) => s.interrupt?.type === 'review_request',
      90_000,
    );
  }

  interface VersionItem {
    id: string;
    version: number;
    snapshot_note: string | null;
    created_by: string | null;
    auto: boolean;
  }

  async function listVersions(
    apiCtx: APIRequestContext,
    user: AuthedUser,
    projectId: string,
  ): Promise<VersionItem[]> {
    const resp = await apiCtx.get(api(`/projects/${projectId}/versions`), {
      headers: bearer(user),
    });
    expect(resp.status()).toBe(200);
    return ((await resp.json()) as BizResponse<{ items: VersionItem[] }>).data.items;
  }

  test('手动快照续号 + 签名下载 + 归档目标库/权限校验', async ({ api: apiCtx }) => {
    test.skip(!llmMockEnabled(), '前置条件：需后端 LLM mock 开启（库内 llm_mock 或 BID_LLM_MOCK）。');

    const owner = await registerAndLogin(apiCtx, 'ver-owner');
    const member = await registerAndLogin(apiCtx, 'ver-member');
    const project = await createProject(apiCtx, owner);
    const add = await apiCtx.post(api(`/projects/${project.id}/members`), {
      headers: bearer(owner),
      data: { email: member.email },
    });
    expect(add.status()).toBe(200);
    await driveToReview(apiCtx, owner, project.id);

    // 手动快照：version 续号 1 → 2
    const snap1 = await apiCtx.post(api(`/projects/${project.id}/versions`), {
      headers: bearer(owner),
    });
    expect(snap1.status(), `手动快照失败: ${await snap1.text()}`).toBe(200);
    const v1 = ((await snap1.json()) as BizResponse<{ id: string; version: number }>).data;
    expect(v1.version).toBe(1);

    const snap2 = await apiCtx.post(api(`/projects/${project.id}/versions`), {
      headers: bearer(owner),
      data: { snapshot_note: 'E2E 手动快照' },
    });
    expect(snap2.status()).toBe(200);
    const v2 = ((await snap2.json()) as BizResponse<{ id: string; version: number }>).data;
    expect(v2.version).toBe(2);

    // 列表倒序，手动快照 auto=false
    const items = await listVersions(apiCtx, member, project.id);
    expect(items.length).toBeGreaterThanOrEqual(2);
    expect(items[0].version).toBe(2);
    expect(items[0].auto).toBe(false);
    expect(items[0].snapshot_note).toBe('E2E 手动快照');

    // 签名下载：docx 与 Markdown 源
    for (const type of ['docx', 'source']) {
      const dl = await apiCtx.get(
        api(`/projects/${project.id}/versions/${v1.id}/download`),
        { headers: bearer(member), params: { type } },
      );
      expect(dl.status(), `下载(${type})失败: ${await dl.text()}`).toBe(200);
      expect(
        ((await dl.json()) as BizResponse<{ url: string }>).data.url.length,
        `下载(${type})应返回签名 URL`,
      ).toBeGreaterThan(0);
    }

    // 归档：目标库必须为公司级（personal 库 → 400）
    const personalBase = await apiCtx.post(api('/kb-bases'), {
      headers: bearer(owner),
      data: { scope: 'personal', name: `E2E归档拦截库-${Date.now()}` },
    });
    expect(personalBase.status()).toBe(200);
    const personalKbId = ((await personalBase.json()) as BizResponse<{ id: string }>).data.id;
    const badArchive = await apiCtx.post(
      api(`/projects/${project.id}/versions/${v1.id}/archive`),
      { headers: bearer(owner), data: { kb_id: personalKbId } },
    );
    expect(badArchive.status()).toBe(400);

    // 归档：非 owner → 403
    const forbiddenArchive = await apiCtx.post(
      api(`/projects/${project.id}/versions/${v1.id}/archive`),
      { headers: bearer(member), data: { kb_id: personalKbId } },
    );
    expect(forbiddenArchive.status()).toBe(403);
  });

  test('自动快照：全部章节审核通过后自动入库（auto=true）', async ({ api: apiCtx }) => {
    test.skip(!llmMockEnabled(), '前置条件：需后端 LLM mock 开启（库内 llm_mock 或 BID_LLM_MOCK）。');

    const owner = await registerAndLogin(apiCtx, 'ver-auto-owner');
    const member = await registerAndLogin(apiCtx, 'ver-auto-member');
    const project = await createProject(apiCtx, owner);
    const add = await apiCtx.post(api(`/projects/${project.id}/members`), {
      headers: bearer(owner),
      data: { email: member.email },
    });
    expect(add.status()).toBe(200);

    await uploadParsedTender(apiCtx, owner, project.id);
    const chapter = await driveToOutline(apiCtx, owner, project.id);
    const assign = await apiCtx.post(api(`/projects/${project.id}/chapter-assignments`), {
      headers: bearer(owner),
      data: [{ chapter_no: chapter.chapter_no, title: chapter.title, assignee_id: member.userId }],
    });
    expect(assign.status()).toBe(200);
    const items = await listAssignments(apiCtx, owner, project.id);
    const assignmentId = items[0].id;

    // 领取 → 生成 → 提交 → 审核通过（触发自动快照）
    const accept = await apiCtx.post(
      api(`/projects/${project.id}/chapter-assignments/${assignmentId}/accept`),
      { headers: bearer(member) },
    );
    expect(accept.status()).toBe(200);
    const gen = await apiCtx.post(
      api(`/projects/${project.id}/chapter-assignments/${assignmentId}/generate`),
      { headers: bearer(member) },
    );
    expect(gen.status()).toBe(200);
    const submit = await apiCtx.post(
      api(`/projects/${project.id}/chapter-assignments/${assignmentId}/submit`),
      { headers: bearer(member) },
    );
    expect(submit.status()).toBe(200);
    const approve = await apiCtx.post(
      api(`/projects/${project.id}/chapter-assignments/${assignmentId}/review`),
      { headers: bearer(owner), data: { action: 'approved', comment: '' } },
    );
    expect(approve.status(), `审核通过失败: ${await approve.text()}`).toBe(200);

    // 自动快照在审核端点内同步完成；轮询容忍提交竞态
    const deadline = Date.now() + 15_000;
    let autoSnapshot: VersionItem | undefined;
    while (Date.now() < deadline && !autoSnapshot) {
      const versions = await listVersions(apiCtx, owner, project.id);
      autoSnapshot = versions.find((v) => v.auto);
      if (!autoSnapshot) await sleep(500);
    }
    expect(autoSnapshot, '全部章节 approved 后应自动创建版本快照').toBeDefined();
    expect(autoSnapshot!.version).toBe(1);
  });
});
