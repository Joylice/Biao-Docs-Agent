/** 编辑器共享类型（消除 composable → component 反向依赖） */

/** 保存状态机（与 WordEditorPage / WordEditorStatusBar 保持一致） */
export type SaveStatus = 'idle' | 'saving' | 'saved' | 'error'
