/**
 * 阶段 E 质量增强 E2E — 章节批注 CRUD 回读 / 版本回滚 / 导出 docx 结构（E4/E5）。
 *
 * 覆盖端点：
 *   POST/GET/PUT/DELETE /projects/{pid}/chapters/{no}/annotations
 *   POST   /projects/{pid}/versions（手动快照，含结构化快照）
 *   GET    /projects/{pid}/versions/{id}/download?type=docx
 *   POST   /projects/{pid}/versions/{id}/rollback
 *
 * 前置：后端以 BID_LLM_MOCK=true 启动（生成闭环场景）；批注 CRUD 不依赖 mock。
 */
import { inflateRawSync } from 'node:zlib';
import type { APIRequestContext } from '@playwright/test';
import {
  api,
  backendHealthy,
  bearer,
  type AuthedUser,
  type BizResponse,
  createProject,
  getWorkflowStatus,
  llmMockEnabled,
  registerAndLogin,
  test,
  expect,
  waitForDocumentStatus,
  waitForWorkflowStatus,
  type WorkflowStatus,
} from '../fixtures/auth';
import { buildMinimalPdf } from '../fixtures/files';

test.beforeEach(async ({ api: apiCtx }) => {
  test.skip(
    !(await backendHealthy(apiCtx)),
    '后端服务未就绪（E2E_API_URL 不可达 /health）。请先 docker compose 启动基础设施并运行后端。',
  );
});

/** 读取 zip 内指定条目（docx = zip；python-docx 写入本地头含压缩尺寸） */
function readZipEntry(buffer: Buffer, name: string): Buffer | null {
  let offset = 0;
  while (offset + 30 <= buffer.length) {
    if (buffer.readUInt32LE(offset) !== 0x04034b50) break; // 本地文件头签名
    const method = buffer.readUInt16LE(offset + 8);
    const compSize = buffer.readUInt32LE(offset + 18);
    const nameLen = buffer.readUInt16LE(offset + 26);
    const extraLen = buffer.readUInt16LE(offset + 28);
    const entryName = buffer.subarray(offset + 30, offset + 30 + nameLen).toString('utf8');
    const dataStart = offset + 30 + nameLen + extraLen;
    if (entryName === name) {
      const data = buffer.subarray(dataStart, dataStart + compSize);
      return method === 8 ? inflateRawSync(data) : Buffer.from(data);
    }
    offset = dataStart + compSize;
  }
  return null;
}

/** 上传招标文件并等待解析完成（工作流前置） */
async function uploadParsedTender(
  apiCtx: APIRequestContext,
  user: AuthedUser,
  projectId: string,
): Promise<void> {
  const resp = await apiCtx.post(api(`/projects/${projectId}/documents?doc_type=tender_file`), {
    headers: bearer(user),
    multipart: {
      file: {
        name: 'tender-stage-e.pdf',
        mimeType: 'application/pdf',
        buffer: buildMinimalPdf('E2E Stage E Tender. Scoring: technical 60, price 40.'),
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

/** 驱动工作流到 review_request 挂起 */
async function driveToReview(
  apiCtx: APIRequestContext,
  user: AuthedUser,
  projectId: string,
): Promise<WorkflowStatus> {
  await apiCtx.post(api(`/projects/${projectId}/workflow/start`), { headers: bearer(user) });
  await waitForWorkflowStatus(
    apiCtx,
    user,
    projectId,
    (s) => s.interrupt?.type === 'confirm_score_points',
    30_000,
  );
  const sp = await apiCtx.post(api(`/projects/${projectId}/workflow/confirm-score-points`), {
    headers: bearer(user),
  });
  expect(sp.status()).toBe(200);
  await waitForWorkflowStatus(
    apiCtx,
    user,
    projectId,
    (s) => s.interrupt?.type === 'confirm_outline',
    30_000,
  );
  const outline = await apiCtx.post(api(`/projects/${projectId}/workflow/confirm-outline`), {
    headers: bearer(user),
  });
  expect(outline.status()).toBe(200);
  return waitForWorkflowStatus(
    apiCtx,
    user,
    projectId,
    (s) => s.interrupt?.type === 'review_request',
    90_000,
  );
}

interface AnnotationItem {
  id: string;
  chapter_no: string;
  content: string;
  created_by: string;
  created_by_name: string;
  created_at: string | null;
  updated_at: string | null;
}

test.describe('阶段 E5：章节批注 CRUD', () => {
  test('批注写入 → 列表回读一致 → 编辑 → 删除', async ({ api: apiCtx }) => {
    const user = await registerAndLogin(apiCtx, 'ann');
    const project = await createProject(apiCtx, user);
    const base = api(`/projects/${project.id}/chapters/1/annotations`);

    // 写入
    const created = await apiCtx.post(base, {
      headers: bearer(user),
      data: { content: ' 请补充实施案例与等保资质 ' },
    });
    expect(created.status(), await created.text()).toBe(200);
    const createdData = ((await created.json()) as BizResponse<AnnotationItem>).data;
    expect(createdData.content).toBe('请补充实施案例与等保资质'); // 后端 trim
    expect(createdData.chapter_no).toBe('1');

    // 列表回读一致
    const list = await apiCtx.get(base, { headers: bearer(user) });
    expect(list.status()).toBe(200);
    const items = ((await list.json()) as BizResponse<{ items: AnnotationItem[] }>).data.items;
    expect(items).toHaveLength(1);
    expect(items[0].id).toBe(createdData.id);
    expect(items[0].content).toBe(createdData.content);

    // 编辑（作者本人）
    const updated = await apiCtx.put(`${base}/${createdData.id}`, {
      headers: bearer(user),
      data: { content: '修改后的批注内容' },
    });
    expect(updated.status(), await updated.text()).toBe(200);
    expect(((await updated.json()) as BizResponse<AnnotationItem>).data.content).toBe(
      '修改后的批注内容',
    );

    // 删除后列表为空
    const deleted = await apiCtx.delete(`${base}/${createdData.id}`, { headers: bearer(user) });
    expect(deleted.status(), await deleted.text()).toBe(200);
    const empty = await apiCtx.get(base, { headers: bearer(user) });
    const emptyItems = ((await empty.json()) as BizResponse<{ items: AnnotationItem[] }>).data
      .items;
    expect(emptyItems).toHaveLength(0);
  });

  test('非成员批注 403（项目级越权）', async ({ api: apiCtx }) => {
    const owner = await registerAndLogin(apiCtx, 'ann-owner');
    const outsider = await registerAndLogin(apiCtx, 'ann-outsider');
    const project = await createProject(apiCtx, owner);
    const resp = await apiCtx.post(api(`/projects/${project.id}/chapters/1/annotations`), {
      headers: bearer(outsider),
      data: { content: '越权批注' },
    });
    expect(resp.status()).toBe(403);
  });
});

test.describe('阶段 E5：版本回滚 + 阶段 E4：导出 docx 结构', () => {
  test('快照 → docx 封面/目录域/附表结构 → 回滚恢复正文', async ({ api: apiCtx }) => {
    test.skip(!llmMockEnabled(), '前置条件：需后端以 BID_LLM_MOCK=true 启动。');

    const user = await registerAndLogin(apiCtx, 'stage-e');
    const project = await createProject(apiCtx, user);
    await uploadParsedTender(apiCtx, user, project.id);
    await driveToReview(apiCtx, user, project.id);

    // 审阅通过 → 图内 export 节点完成
    const ok = await apiCtx.post(api(`/projects/${project.id}/workflow/confirm-review`), {
      headers: bearer(user),
      data: { action: 'approved' },
    });
    expect(ok.status(), await ok.text()).toBe(200);
    const done = await waitForWorkflowStatus(
      apiCtx,
      user,
      project.id,
      (s) => s.export_status === 'done' || s.phase === 'done',
      60_000,
    );
    expect(done.error || '', `工作流进入错误态: ${done.error}`).toBe('');

    // 手动快照（含结构化快照）
    const snap = await apiCtx.post(api(`/projects/${project.id}/versions`), {
      headers: bearer(user),
      data: { snapshot_note: '阶段E 回滚基线' },
    });
    expect(snap.status(), await snap.text()).toBe(200);
    const versionId = ((await snap.json()) as BizResponse<{ id: string; version: number }>).data
      .id;

    // 下载 docx → 解包 word/document.xml 断言封面/目录域/分页控制
    const dl = await apiCtx.get(
      api(`/projects/${project.id}/versions/${versionId}/download?type=docx`),
      { headers: bearer(user) },
    );
    expect(dl.status(), await dl.text()).toBe(200);
    const url = ((await dl.json()) as BizResponse<{ url: string }>).data.url;
    const fileResp = await apiCtx.get(url).catch(() => null);
    if (fileResp === null || !fileResp.ok()) {
      test.skip(true, `MinIO 签名 URL 不可达（宿主网络限制）：${url}`);
      return;
    }
    const docx = Buffer.from(await fileResp.body());
    const docXml = readZipEntry(docx, 'word/document.xml')?.toString('utf8');
    expect(docXml, 'docx 缺少 word/document.xml').toBeTruthy();
    expect(docXml).toContain(project.name); // 封面项目名
    expect(docXml).toContain('编制日期'); // 封面日期占位
    expect(docXml).toContain('TOC \\o'); // 目录域
    expect(docXml).toContain('pageBreakBefore'); // 章节前分页
    const footerXml = readZipEntry(docx, 'word/footer1.xml')?.toString('utf8') ?? '';
    expect(footerXml).toContain('PAGE'); // 页脚页码域

    // 回滚：恢复章节数 ≥ 1，且状态正文仍可读
    const rb = await apiCtx.post(api(`/projects/${project.id}/versions/${versionId}/rollback`), {
      headers: bearer(user),
    });
    expect(rb.status(), await rb.text()).toBe(200);
    const rbData = (
      (await rb.json()) as BizResponse<{ version: number; chapters_restored: number }>
    ).data;
    expect(rbData.chapters_restored).toBeGreaterThanOrEqual(1);

    const after = await getWorkflowStatus(apiCtx, user, project.id);
    expect(Object.keys(after.chapters).length).toBeGreaterThanOrEqual(1);
  });
});
