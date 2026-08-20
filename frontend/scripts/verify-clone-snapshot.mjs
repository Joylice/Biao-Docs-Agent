/**
 * P2 缺陷最小复现验证（可选，可删除）：
 * 模拟 DivisionView/GenerateView 场景——把 Vue reactive Proxy 数组传入 useUndoRedo
 * 的 push/reset/undo/redo，验证不再抛 DataCloneError 且快照与当前 state 解耦。
 *
 * 前置：先用 esbuild 打包真实源码（vue 外部化）：
 *   pnpm.cmd exec esbuild src/composables/useUndoRedo.ts --bundle --format=esm
 *     --platform=node --external:vue --outfile=useUndoRedo.bundled.mjs
 * 运行：cd frontend; node scripts/verify-clone-snapshot.mjs
 */
import { reactive, isReactive } from 'vue'

let failed = false
const assert = (cond, msg) => {
  if (!cond) {
    failed = true
    console.error(`❌ ${msg}`)
  } else {
    console.log(`✅ ${msg}`)
  }
}

let useUndoRedo
try {
  ;({ useUndoRedo } = await import(new URL('../useUndoRedo.bundled.mjs', import.meta.url)))
} catch {
  console.error('❌ 缺少 useUndoRedo.bundled.mjs，请先按文件头注释执行 esbuild 打包')
  failed = true
}

if (useUndoRedo) {
  // ---- 0. 复现缺陷现场：structuredClone 直接克隆 reactive Proxy 数组必然抛错 ----
  const items = reactive([
    { id: 1, title: '任务A', status: 'todo', children: [{ id: 11, title: '子任务', created_at: '2026-08-21' }] },
    { id: 2, title: '任务B', status: 'doing', children: [] },
  ])
  assert(isReactive(items), '测试前置：items 为 reactive Proxy 数组')
  let oldImplThrew = false
  try {
    structuredClone(items) // 修复前 cloneSnapshot 的行为
  } catch (e) {
    oldImplThrew = true
    console.log(`✅ 复现缺陷：structuredClone(reactive) 抛出 ${e.name}: ${e.message}`)
  }
  assert(oldImplThrew, '修复前路径确实抛 DataCloneError（否则复现无效）')

  // ---- 1. 修复后：push / reset 传入 reactive 数组不抛错（看板拖拽、手动刷新路径） ----
  const history = useUndoRedo([])
  try {
    history.push(items) // DivisionView: kanbanHistory.push(items.value)
    history.reset(items) // DivisionView: kanbanHistory.reset(items.value)（reset 同路径）
    assert(true, 'push/reset 传入 reactive Proxy 数组不再抛错')
  } catch (e) {
    assert(false, `push/reset 仍抛错: ${e.name}: ${e.message}`)
  }

  // ---- 2. 快照与当前 state 解耦：原地修改 state 不污染历史 ----
  history.push(history.state.value)
  history.state.value[0].status = 'done'
  history.state.value.splice(1, 1)
  assert(history.undo(), 'undo 成功执行')
  assert(history.state.value.length === 2, 'undo 恢复了快照（长度 2）')
  assert(history.state.value[0].status === 'todo', 'undo 恢复了快照内字段值（未被原地修改污染）')

  // ---- 3. redo 路径同样走安全克隆 ----
  assert(history.redo(), 'redo 成功执行')
  assert(
    history.state.value.length === 1 && history.state.value[0].status === 'done',
    'redo 恢复变更后状态',
  )

  // ---- 4. reset 后 state 为普通数据，嵌套对象完整（响应性由 ref 自行维持） ----
  history.reset(items)
  assert(
    history.state.value[0].id === 1 && history.state.value[0].children[0].id === 11,
    '嵌套对象数据完整',
  )
}

console.log(failed ? '\n验证存在失败项' : '\n全部验证通过')
