import {
  Callout,
  CollapsibleSection,
  Divider,
  Grid,
  H1,
  H2,
  Row,
  Stack,
  Stat,
  Table,
  Tag,
  Text,
  canvasImage,
} from 'qoder/canvas';

const imgRoleChange = canvasImage('./output/1_role_change_confirm.png');
const imgMemberIsolation = canvasImage('./output/2_member_kb_no_edit_delete.png');
const imgKbColumns = canvasImage('./output/3_admin_kb_columns.png');
const imgTagFilterFixed = canvasImage('./output/reverify-1-1-tag-filter-yanshou.png');
const imgAuditLogs = canvasImage('./output/4_audit_logs_table.png');
const imgStreamingA = canvasImage('./output/reverify-2-7-streaming-ch8-a.png');
const imgStreamingB = canvasImage('./output/reverify-2-8-streaming-ch8-b.png');
const imgExportDone = canvasImage('./output/reverify-2-14-export-done.png');

export default function Phase3CompletionReport() {
  return (
    <Stack gap={24}>
      <Stack gap={6}>
        <H1>三期「体验与治理增强」交付完成报告</H1>
        <Text tone="secondary">
          投标软件技术方案智能体 · 2026-08-16 · S1 角色 / S2 素材治理 / S3 审计页 / S4 真流式 / S5 集成验收
        </Text>
      </Stack>

      <Grid columns={4} gap={16}>
        <Stat value="15/15" label="计划任务完成" tone="success" />
        <Stat value="366" label="后端测试通过（4 skipped）" tone="success" />
        <Stat value="88.2%" label="全仓覆盖率（门槛 70%）" tone="success" />
        <Stat value="34/34" label="E2E Playwright 全绿" tone="success" />
      </Grid>

      <Divider />

      <H2>验收中发现并修复的缺陷</H2>
      <Table
        headers={['缺陷', '根因', '修复', '复验']}
        rows={[
          [
            '素材标签筛选 HTTP 500',
            'tags 为 JSON 列，PG @> 运算符仅支持 jsonb',
            'kb.py 列表过滤 cast(tags, JSONB) @> cast([tag], JSONB)',
            '通过（200 + 正确过滤）',
          ],
          [
            '真实模式招标解析秒失败、错误被吞',
            'call_llm_with_schema 内 import json 位于 try 内，except json.JSONDecodeError 触发 UnboundLocalError 遮蔽真实错误',
            'json 提升为模块级 import',
            '通过（真实错误暴露并定位）',
          ],
          [
            'DeepSeek 结构化解析 400',
            'DeepSeek 不支持 strict json_schema（"This response_format type is unavailable now"）',
            '新增 _compat_response_format：deepseek 降级 json_object + schema 写入 system prompt；其余模型原样透传（TDD 4 用例）',
            '通过（真实解析成功提取评分点）',
          ],
          ['ruff 存量 B905（scripts/）', 'zip() 缺 strict= 参数', '补 strict=True', '通过（ruff 全仓绿）'],
        ]}
      />

      <Divider />

      <H2>浏览器验收证据（真实 LLM 模式）</H2>
      <Grid columns={2} gap={16}>
        <Stack gap={6}>
          <Text weight="semibold">S1 角色变更确认弹窗（admin 用户管理）</Text>
          <img src={imgRoleChange} alt="角色变更确认弹窗" style={{ maxWidth: '100%', borderRadius: 8 }} />
        </Stack>
        <Stack gap={6}>
          <Text weight="semibold">S1 member 权限隔离（无编辑/删除按钮）</Text>
          <img src={imgMemberIsolation} alt="member 无编辑删除按钮" style={{ maxWidth: '100%', borderRadius: 8 }} />
        </Stack>
        <Stack gap={6}>
          <Text weight="semibold">S2 素材库：分类/标签/上传者列</Text>
          <img src={imgKbColumns} alt="素材库表格新列" style={{ maxWidth: '100%', borderRadius: 8 }} />
        </Stack>
        <Stack gap={6}>
          <Text weight="semibold">S2 标签筛选修复复验（过滤命中 1 条）</Text>
          <img src={imgTagFilterFixed} alt="标签筛选修复后" style={{ maxWidth: '100%', borderRadius: 8 }} />
        </Stack>
        <Stack gap={6}>
          <Text weight="semibold">S3 审计日志页（role_change / material_update / audit.query）</Text>
          <img src={imgAuditLogs} alt="审计日志表格" style={{ maxWidth: '100%', borderRadius: 8 }} />
        </Stack>
        <Stack gap={6}>
          <Text weight="semibold">S4 真流式：第 8 章 9 秒内 1122 → 4320 字符增量渲染</Text>
          <Row gap={8}>
            <img src={imgStreamingA} alt="流式增量 t1" style={{ maxWidth: '49%', borderRadius: 8 }} />
            <img src={imgStreamingB} alt="流式增量 t2" style={{ maxWidth: '49%', borderRadius: 8 }} />
          </Row>
        </Stack>
      </Grid>
      <Stack gap={6}>
        <Text weight="semibold">S4 全流程闭环：11/11 章生成 → 审阅通过 → 导出完成</Text>
        <img src={imgExportDone} alt="导出完成终态" style={{ maxWidth: '72%', borderRadius: 8 }} />
      </Stack>

      <Divider />

      <H2>质量门禁最终状态</H2>
      <Table
        headers={['门禁', '要求', '结果']}
        rows={[
          ['pytest 全量', '全绿', '366 passed / 4 skipped'],
          ['覆盖率（全仓）', '≥70%', '88.20%'],
          ['覆盖率（deps/kb/llm_service/nodes）', '≥80%', '92% / 98% / 86% / 87%'],
          ['ruff check（全仓含 scripts/alembic）', 'All checks passed', '通过'],
          ['E2E Playwright（BID_LLM_MOCK=true）', '全绿', '34 passed（含 section_token 断言）'],
          ['真实 LLM 模式', '恢复 + 健康', 'env/DB llm_mock=false，/health ok'],
          ['迁移 0007/0008', '生产库执行', 'alembic upgrade head 完成'],
        ]}
      />

      <H2>关键变更文件</H2>
      <Table
        headers={['模块', '文件', '内容']}
        rows={[
          ['迁移', 'alembic/versions/0007、0008', 'users.role 回填 admin；documents.category/tags'],
          ['权限', 'app/core/deps.py、app/api/users.py', 'role 判定 + 白名单 OR 兼容；用户列表/角色变更（自降级拒绝、最后 admin 保护）'],
          ['素材', 'app/api/kb.py、app/schemas/document.py', '上传 category/tags、PATCH 编辑、category/tag 过滤（jsonb @>）、uploader_name join'],
          ['审计', 'app/api/audit.py', 'GET /audit-logs（前缀/时间/分页倒序/user_name join/audit.query 留痕）'],
          ['流式', 'app/services/llm_service.py、chapter_service.py、app/agents/nodes.py', 'call_llm_stream + on_delta + write_node 节流 40 字符/200ms + DeepSeek json_schema 降级'],
          ['前端', 'UsersView / MaterialsView / AuditLogsView / GenerateView', '用户管理、素材分类标签编辑、审计页、去假打字机增量渲染'],
          ['E2E', 'e2e/tests/websocket.spec.ts', 'section_token ≥1、先于 section_done、delta 拼接 == 全文'],
          ['文档', '投标软件技术方案智能体_SDD.md', '§3.8 事件协议+真流式链路+供应商兼容、§4.1 表结构、§5.1 接口、§6.1 节点'],
        ]}
      />

      <CollapsibleSection title="遗留观察项（非本期范围）">
        <Stack gap={8}>
          <Text>1. 前端缺「启动工作流」入口：未启动过工作流的项目在解析页点击确认会报 4009，提示文案未给出原因，建议后续优化。</Text>
          <Text>2. KnowledgeBaseView.vue / KbView.vue 孤儿组件按计划维持现状，另行处理。</Text>
        </Stack>
      </CollapsibleSection>

      <Callout tone="success" title="结论">
        <Stack gap={4}>
          <Text>三期计划 15 项任务全部完成并通过逐项证据验证：后端 366 测试全绿、覆盖率 88.2%、E2E 34 全绿、浏览器验收四项（用户管理授权流 / 素材分类标签 / 审计页 / 真实模式流式打字）全部通过；验收中发现的 3 个缺陷（标签过滤 500、json 遮蔽、DeepSeek json_schema 不兼容）均已修复并复验。系统已恢复真实 LLM 模式运行。</Text>
          <Row gap={8}>
            <Tag tone="success">S1 角色治理</Tag>
            <Tag tone="success">S2 素材治理</Tag>
            <Tag tone="success">S3 审计页</Tag>
            <Tag tone="success">S4 真流式</Tag>
            <Tag tone="success">S5 集成验收</Tag>
          </Row>
        </Stack>
      </Callout>

      <Text tone="secondary" size="small">
        截图来源：output/ 目录浏览器验收留证（accept-admin@example.com admin / manual-probe@example.com member）。
      </Text>
    </Stack>
  );
}
