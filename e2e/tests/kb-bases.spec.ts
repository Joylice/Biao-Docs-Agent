/**
 * E2E：多知识库容器（个人/项目/公司三级可见性）+ 素材归属 + 库级挂载（阶段 1）
 *
 * 覆盖：
 * - personal 库：任意登录用户可建，仅本人可见；重命名/删除；
 *   素材上传携带 kb_id 归属入库，库内素材列表可见，删库素材级联删除。
 * - project 库：仅项目 owner 可建（成员建库 403）；成员带 project_id 查询可见，
 *   非成员不可见；非成员读库内素材 404。
 * - company 库：普通用户建库 403（E2E 无管理员提权手段，仅覆盖负向）。
 * - 挂载：confirm-outline 携带 mounted_kb_ids → 200 且工作流正常推进到审阅。
 *
 * 对齐后端路由：backend/app/api/kb_bases.py（/kb-bases 系列）
 * + api/kb.py POST /kb/materials（kb_id 归属）+ api/workflow.py confirm-outline。
 */
import type { APIRequestContext } from '@playwright/test';
import {
  api,
  backendHealthy,
  bearer,
  confirmAllScorePoints,
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

interface KbBaseItem {
  id: string;
  name: string;
  scope: string;
  project_id: string | null;
  owner_id: string | null;
  material_count: number;
}

/** 读取当前用户可见知识库列表（可带项目上下文） */
async function listKbBases(
  apiCtx: APIRequestContext,
  user: AuthedUser,
  projectId?: string,
): Promise<KbBaseItem[]> {
  const query = projectId ? `?project_id=${projectId}` : '';
  const resp = await apiCtx.get(api(`/kb-bases${query}`), { headers: bearer(user) });
  expect(resp.status()).toBe(200);
  return ((await resp.json()) as BizResponse<{ items: KbBaseItem[] }>).data.items;
}

/** 创建知识库（scope: personal|project|company） */
async function createKbBase(
  apiCtx: APIRequestContext,
  user: AuthedUser,
  scope: string,
  name: string,
  projectId?: string,
): Promise<KbBaseItem> {
  const resp = await apiCtx.post(api('/kb-bases'), {
    headers: bearer(user),
    data: { scope, name, project_id: projectId ?? null },
  });
  expect(resp.status(), `建库失败: ${await resp.text()}`).toBe(200);
  return ((await resp.json()) as BizResponse<KbBaseItem>).data;
}

test.beforeEach(async ({ api: apiCtx }) => {
  test.skip(
    !(await backendHealthy(apiCtx)),
    '后端服务未就绪（E2E_API_URL 不可达 /health）。请先 docker compose 启动基础设施并运行后端。',
  );
});

test.describe('知识库创建与可见性矩阵', () => {
  test('personal 库：本人创建可见、他人不可见，重命名与删除', async ({ api: apiCtx }) => {
    const userA = await registerAndLogin(apiCtx, 'kb-owner-a');
    const userB = await registerAndLogin(apiCtx, 'kb-other-b');

    const base = await createKbBase(apiCtx, userA, 'personal', `E2E个人库-${Date.now()}`);
    expect(base.scope).toBe('personal');
    expect(base.owner_id).toBe(userA.userId);

    // 本人列表可见；他人列表不可见
    const itemsA = await listKbBases(apiCtx, userA);
    expect(itemsA.map((b) => b.id)).toContain(base.id);
    const itemsB = await listKbBases(apiCtx, userB);
    expect(itemsB.map((b) => b.id)).not.toContain(base.id);

    // 重命名
    const newName = `E2E个人库-改名-${Date.now()}`;
    const patch = await apiCtx.patch(api(`/kb-bases/${base.id}`), {
      headers: bearer(userA),
      data: { name: newName },
    });
    expect(patch.status(), `改名失败: ${await patch.text()}`).toBe(200);
    const afterPatch = ((await patch.json()) as BizResponse<KbBaseItem>).data;
    expect(afterPatch.name).toBe(newName);

    // 他人无权改名
    const forbiddenPatch = await apiCtx.patch(api(`/kb-bases/${base.id}`), {
      headers: bearer(userB),
      data: { name: '越权改名' },
    });
    expect(forbiddenPatch.status()).toBe(403);

    // 删除后列表不再可见
    const del = await apiCtx.delete(api(`/kb-bases/${base.id}`), { headers: bearer(userA) });
    expect(del.status()).toBe(200);
    const afterDelete = await listKbBases(apiCtx, userA);
    expect(afterDelete.map((b) => b.id)).not.toContain(base.id);
  });

  test('素材归属个人库：库内列表可见，删库级联删除素材', async ({ api: apiCtx }) => {
    const user = await registerAndLogin(apiCtx, 'kb-mat-owner');
    const base = await createKbBase(apiCtx, user, 'personal', `E2E素材库-${Date.now()}`);

    // 上传素材携带 kb_id 归属入库（POST /kb/materials Form 字段）
    const up = await apiCtx.post(api('/kb/materials'), {
      headers: bearer(user),
      multipart: {
        file: {
          name: 'kb-base-material.pdf',
          mimeType: 'application/pdf',
          buffer: buildMinimalPdf('E2E kb base material.'),
        },
        kb_id: base.id,
      },
    });
    expect(up.status(), `素材上传失败: ${await up.text()}`).toBe(200);

    // 提交竞态窗口：轮询库内素材列表直到可见
    let materials: Array<{ id: string }> = [];
    const deadline = Date.now() + 10_000;
    while (Date.now() < deadline) {
      const resp = await apiCtx.get(api(`/kb-bases/${base.id}/materials`), {
        headers: bearer(user),
      });
      if (resp.status() === 200) {
        materials = ((await resp.json()) as BizResponse<{ items: Array<{ id: string }> }>).data
          .items;
        if (materials.length > 0) break;
      }
      await new Promise((r) => setTimeout(r, 500));
    }
    expect(materials.length, '上传的素材应出现在库内列表').toBe(1);

    // 删库 → 库内素材级联删除（库 404）
    const del = await apiCtx.delete(api(`/kb-bases/${base.id}`), { headers: bearer(user) });
    expect(del.status()).toBe(200);
    const afterDelete = await apiCtx.get(api(`/kb-bases/${base.id}/materials`), {
      headers: bearer(user),
    });
    expect(afterDelete.status()).toBe(404);
  });

  test('project 库：仅 owner 可建，成员可见、非成员不可见', async ({ api: apiCtx }) => {
    const owner = await registerAndLogin(apiCtx, 'kb-proj-owner');
    const member = await registerAndLogin(apiCtx, 'kb-proj-member');
    const outsider = await registerAndLogin(apiCtx, 'kb-proj-outsider');
    const project = await createProject(apiCtx, owner);

    const add = await apiCtx.post(api(`/projects/${project.id}/members`), {
      headers: bearer(owner),
      data: { email: member.email },
    });
    expect(add.status()).toBe(200);

    // 非 owner（成员）建项目库 → 403
    const forbidden = await apiCtx.post(api('/kb-bases'), {
      headers: bearer(member),
      data: { scope: 'project', name: '越权项目库', project_id: project.id },
    });
    expect(forbidden.status()).toBe(403);

    // owner 建项目库 → 200
    const base = await createKbBase(
      apiCtx,
      owner,
      'project',
      `E2E项目库-${Date.now()}`,
      project.id,
    );
    expect(base.scope).toBe('project');
    expect(base.project_id).toBe(project.id);

    // 提交竞态窗口：轮询直到成员带项目上下文可见
    let visibleToMember = false;
    const deadline = Date.now() + 10_000;
    while (Date.now() < deadline && !visibleToMember) {
      const items = await listKbBases(apiCtx, member, project.id);
      visibleToMember = items.some((b) => b.id === base.id);
      if (!visibleToMember) await new Promise((r) => setTimeout(r, 500));
    }
    expect(visibleToMember, '项目成员带 project_id 查询应可见项目库').toBe(true);

    // 非成员不可见；读库内素材 404
    const outsiderItems = await listKbBases(apiCtx, outsider, project.id);
    expect(outsiderItems.map((b) => b.id)).not.toContain(base.id);
    const forbiddenMaterials = await apiCtx.get(api(`/kb-bases/${base.id}/materials`), {
      headers: bearer(outsider),
    });
    expect(forbiddenMaterials.status()).toBe(404);
  });

  test('company 库：普通用户创建被拒（403）', async ({ api: apiCtx }) => {
    const user = await registerAndLogin(apiCtx, 'kb-company-user');
    const resp = await apiCtx.post(api('/kb-bases'), {
      headers: bearer(user),
      data: { scope: 'company', name: '越权公司库' },
    });
    expect(resp.status()).toBe(403);
  });
});

test.describe('知识库库级挂载', () => {
  test('confirm-outline 携带 mounted_kb_ids → 工作流正常推进到审阅', async ({ api: apiCtx }) => {
    test.skip(!llmMockEnabled(), '前置条件：需后端 LLM mock 开启（库内 llm_mock 或 BID_LLM_MOCK）。');

    const owner = await registerAndLogin(apiCtx, 'kb-mount-owner');
    const project = await createProject(apiCtx, owner);

    // 前置：招标文件解析入库评分点（工作流启动依赖）
    const up = await apiCtx.post(api(`/projects/${project.id}/documents?doc_type=tender_file`), {
      headers: bearer(owner),
      multipart: {
        file: {
          name: 'tender-mount.pdf',
          mimeType: 'application/pdf',
          buffer: buildMinimalPdf('E2E KB mount tender. Scoring: technical 60, price 40.'),
        },
      },
    });
    expect(up.status()).toBe(200);
    const docId = ((await up.json()) as BizResponse<{ id: string }>).data.id;
    const status = await waitForDocumentStatus(
      apiCtx,
      owner,
      project.id,
      docId,
      ['parsed', 'failed'],
      60_000,
      'tender_file',
    );
    expect(status, '招标文件未解析成功（worker/LLM mock 异常？）').toBe('parsed');

    // 个人库作为挂载对象（检索范围 = 挂载库 ∪ 本人个人库，库存在即可挂载）
    const base = await createKbBase(apiCtx, owner, 'personal', `E2E挂载库-${Date.now()}`);

    // 驱动到大纲待确认
    // 严格模式（2026-08-25）：先逐条确认评分点再启动工作流，否则 parse 节点直接 error
    await confirmAllScorePoints(apiCtx, owner, project.id);
    await apiCtx.post(api(`/projects/${project.id}/workflow/start`), { headers: bearer(owner) });
    await waitForWorkflowStatus(
      apiCtx,
      owner,
      project.id,
      (s) => s.interrupt?.type === 'confirm_score_points',
      30_000,
    );
    await apiCtx.post(api(`/projects/${project.id}/workflow/confirm-score-points`), {
      headers: bearer(owner),
    });
    await waitForWorkflowStatus(
      apiCtx,
      owner,
      project.id,
      (s) => s.interrupt?.type === 'confirm_outline',
      60_000,
    );

    // 携带 mounted_kb_ids 确认大纲 → 200 且章节生成正常推进到审阅挂起
    const confirm = await apiCtx.post(api(`/projects/${project.id}/workflow/confirm-outline`), {
      headers: bearer(owner),
      data: { mounted_kb_ids: [base.id], start_generation: true },
    });
    expect(confirm.status(), `确认大纲失败: ${await confirm.text()}`).toBe(200);
    const review = await waitForWorkflowStatus(
      apiCtx,
      owner,
      project.id,
      (s) => s.interrupt?.type === 'review_request',
      90_000,
    );
    expect(Object.keys(review.chapters).length, '挂载知识库后章节应正常生成').toBeGreaterThan(0);
  });
});
