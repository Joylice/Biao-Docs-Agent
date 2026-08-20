import { createApp } from 'vue'
import { createPinia } from 'pinia'
import Antd from 'ant-design-vue'
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

app.use(pinia)
app.use(router)
app.use(Antd)

// 初始化 UI store（应用主题）
const uiStore = useUiStore(pinia)
uiStore.init()

app.mount('#app')
