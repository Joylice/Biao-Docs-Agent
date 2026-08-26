import { createApp } from 'vue'
import { createPinia } from 'pinia'
import piniaPluginPersistedState from 'pinia-plugin-persistedstate'
import 'ant-design-vue/dist/reset.css'

import App from './App.vue'
import router from './router'
import { useUiStore } from './stores/ui'

// 设计系统样式
import './styles/variables.css'
import './styles/reset.css'
import './styles/utilities.css'

const app = createApp(App)
const pinia = createPinia()

// UI 状态（主题/侧边栏折叠）持久化：各 store 按需声明 persist 配置
pinia.use(piniaPluginPersistedState)

app.use(pinia)
app.use(router)
// 注意：antd 组件按需引入由 unplugin-vue-components 自动解析（vite.config.ts），
// 此处不再全量 app.use(Antd)。message/Modal 等静态方法需在使用处显式 import。

// 初始化 UI store（应用主题）
const uiStore = useUiStore(pinia)
uiStore.init()

app.mount('#app')
