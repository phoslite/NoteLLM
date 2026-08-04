import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import router from './router'
import './styles/theme.css'
import { defuseHiddenReplaceState } from './utils/historyReplaceDefuse'

// 必须在 vue-router 初始化/挂载前安装：vue-router 在页面 hidden（窗口最小化）时
// 调用 history.replaceState 保存滚动位置，会触发 Edge/Chromium 把最小化窗口恢复。
defuseHiddenReplaceState()

createApp(App).use(createPinia()).use(router).use(ElementPlus).mount('#app')
