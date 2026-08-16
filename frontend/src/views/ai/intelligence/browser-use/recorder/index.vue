<template>
  <div class="recorder-container">
    <el-row :gutter="16">
      <!-- 左侧：录制配置 -->
      <el-col :span="10">
        <el-card shadow="never" header="录制配置">
          <el-form :model="form" label-width="90px" size="default">
            <el-form-item label="UI 项目">
              <el-select v-model="form.projectId" placeholder="选择 UI 项目" filterable style="width:100%">
                <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="用例名称">
              <el-input v-model="form.name" placeholder="留空自动命名" />
            </el-form-item>
            <el-form-item label="起始 URL">
              <el-input v-model="form.url" placeholder="https://example.com" />
            </el-form-item>
            <el-form-item label="浏览器">
              <el-select v-model="form.browserType" style="width:100%">
                <el-option label="Microsoft Edge" value="edge" />
                <el-option label="Google Chrome" value="chrome" />
                <el-option label="Mozilla Firefox" value="firefox" />
                <el-option label="Apple Safari" value="safari" />
              </el-select>
            </el-form-item>
            <el-form-item label="视口">
              <el-input-number v-model="form.viewportWidth" :min="320" :max="4000" controls-position="right" />
              <span class="sep">×</span>
              <el-input-number v-model="form.viewportHeight" :min="320" :max="4000" controls-position="right" />
            </el-form-item>
            <el-form-item label="配色">
              <el-select v-model="form.colorScheme" clearable placeholder="默认" style="width:100%">
                <el-option label="浅色" value="light" />
                <el-option label="深色" value="dark" />
              </el-select>
            </el-form-item>
            <el-form-item label="语言">
              <el-input v-model="form.locale" placeholder="如 zh-CN / en-US" clearable />
            </el-form-item>
            <el-form-item label="时区">
              <el-input v-model="form.timezone" placeholder="如 Asia/Shanghai" clearable />
            </el-form-item>
            <el-form-item label="无头模式">
              <el-switch v-model="form.headless" active-text="开启" inactive-text="关闭" />
              <span class="hint">后台服务/无桌面环境建议开启</span>
            </el-form-item>
          </el-form>

          <el-divider />

          <div class="actions">
            <el-button v-if="!running" type="primary" :disabled="!form.projectId" @click="openEnvCheck">
              <el-icon><VideoCamera /></el-icon> 开始录制
            </el-button>
            <template v-else>
              <el-button :type="paused ? 'success' : 'warning'" @click="togglePause">
                <el-icon><component :is="paused ? CaretRight : VideoPause" /></el-icon>
                {{ paused ? '继续录制' : '暂停录制' }}
              </el-button>
              <el-button type="danger" @click="stopRecord">
                <el-icon><VideoCameraFilled /></el-icon> 停止录制
              </el-button>
            </template>
          </div>

          <template v-if="running">
            <el-divider>断言 / 拾取工具栏</el-divider>
            <div class="assert-bar">
              <el-button size="small" @click="setAssert('visible')">断言-可见性</el-button>
              <el-button size="small" @click="setAssert('text')">断言-文本</el-button>
              <el-button size="small" @click="setAssert('value')">断言-值</el-button>
              <el-button size="small" @click="startPick">拾取定位器</el-button>
            </div>
            <el-alert
              v-if="pickResult"
              type="success"
              :closable="true"
              show-icon
              :title="'已拾取定位器'"
              :description="pickText"
              style="margin-top:10px"
            />
            <el-alert type="info" :closable="false" show-icon title="提示"
              :description="form.headless
                ? '无头模式：浏览器在后台运行，不会弹出窗口。点击下方“打开被录页面”可在新标签页查看目标页面，但当前标签页的操作不会被录制。'
                : '在弹出的浏览器中操作后，点击下方断言/拾取按钮，再点击页面元素即可捕获。录制步骤会实时显示到右侧。'" />
            <el-button v-if="form.headless && form.url" size="small" type="info" style="margin-top:10px" @click="openRecordedPage">
              打开被录页面
            </el-button>
          </template>
        </el-card>

        <el-card shadow="never" header="导入已有脚本" style="margin-top:16px">
          <el-tabs v-model="importTab">
            <el-tab-pane label="Playwright Codegen" name="codegen">
              <el-input v-model="importCode" type="textarea" :rows="5"
                placeholder="粘贴 npx playwright codegen 生成的测试代码（JS/Python）" />
              <el-button type="primary" size="small" style="margin-top:8px"
                :disabled="!form.projectId || !importCode" @click="doImport('codegen')">导入为用例</el-button>
            </el-tab-pane>
            <el-tab-pane label="Selenium IDE" name="side">
              <el-input v-model="importSide" type="textarea" :rows="5"
                placeholder="粘贴 Selenium IDE 导出的 .side 文件内容（JSON）" />
              <el-button type="primary" size="small" style="margin-top:8px"
                :disabled="!form.projectId || !importSide" @click="doImport('side')">导入为用例</el-button>
            </el-tab-pane>
          </el-tabs>
        </el-card>
      </el-col>

      <!-- 右侧：实时步骤 -->
      <el-col :span="14">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>{{ running ? `录制中（会话 ${sessionId}）` : '录制步骤' }}</span>
              <el-tag v-if="running && paused" type="warning" effect="dark" size="small">已暂停</el-tag>
              <el-tag v-else-if="running" type="success" effect="plain" size="small">录制中</el-tag>
            </div>
          </template>
          <el-empty v-if="steps.length === 0" description="尚未录制到步骤" />
          <el-timeline v-else>
            <el-timeline-item
              v-for="s in steps"
              :key="s.id"
              :type="stepColor(s.actionType)"
              :timestamp="`#${s.stepNumber} ${s.actionType}`"
            >
              <div class="step-line">
                <el-tag size="small" effect="plain">{{ stepLabel(s.actionType) }}</el-tag>
                <span class="desc">{{ s.description || s.actionValue || s.assertionValue || '-' }}</span>
              </div>
              <div v-if="s.assertionType" class="assert-info">
                断言类型：{{ s.assertionType }} ｜ 期望值：{{ s.assertionValue || '（无）' }}
              </div>
            </el-timeline-item>
          </el-timeline>
        </el-card>
      </el-col>
    </el-row>

    <!-- 前置环境检测弹窗 -->
    <el-dialog
      v-model="envCheckVisible"
      title="录制前置环境检测"
      width="520px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <div class="env-check-intro">
        开始录制前将自动检查后端服务、所选浏览器及目标 URL 是否就绪。
        <el-alert
          v-if="!form.headless"
          type="warning"
          :closable="false"
          show-icon
          style="margin-top:10px"
          title="无头模式建议"
          description="当前关闭无头模式。若后端以后台服务/SYSTEM 身份运行，可能无法弹出浏览器窗口，建议开启无头模式。"
        />
      </div>
      <el-divider />
      <div class="env-check-list">
        <div v-for="(item, idx) in envChecks" :key="idx" class="env-check-item">
          <el-icon v-if="item.status === 'pending'" class="status-icon" color="#909399"><Loading /></el-icon>
          <el-icon v-else-if="item.status === 'checking'" class="status-icon is-loading" color="#409EFF"><Loading /></el-icon>
          <el-icon v-else-if="item.status === 'success'" class="status-icon" color="#67C23A"><CircleCheck /></el-icon>
          <el-icon v-else-if="item.status === 'error'" class="status-icon" color="#F56C6C"><CircleClose /></el-icon>
          <div class="env-check-body">
            <div class="env-check-name">{{ item.name }}</div>
            <div class="env-check-msg" :class="item.status">{{ item.message || '等待检测...' }}</div>
          </div>
        </div>
      </div>
      <template #footer>
        <div class="dialog-footer">
          <el-button :loading="envChecking" @click="runEnvCheck">重新检测</el-button>
          <el-button type="primary" :disabled="!envAllPassed || envChecking" @click="confirmStartRecord">开始录制</el-button>
          <el-button @click="envCheckVisible = false">取消</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { VideoCamera, VideoCameraFilled, VideoPause, CaretRight, Loading, CircleCheck, CircleClose } from '@element-plus/icons-vue'
import { uiRecordApi, uiProjectApi, uiBrowserApi } from '/@/api/v1/testing/uiAutomation'

const projects = ref<any[]>([])
const running = ref(false)
const paused = ref(false)
const sessionId = ref<number | null>(null)
const steps = ref<any[]>([])
const pickResult = ref<any>(null)
const importTab = ref('codegen')
const importCode = ref('')
const importSide = ref('')
let pollTimer: any = null

const form = reactive({
  projectId: null as number | null,
  name: '',
  url: '',
  browserType: 'edge',
  viewportWidth: 1280,
  viewportHeight: 720,
  colorScheme: '',
  locale: '',
  timezone: '',
  headless: false,
})

const route = useRoute()
const pickText = ref('')

// 前置环境检测弹窗
const envCheckVisible = ref(false)
const envChecking = ref(false)
const envChecks = ref<Array<{ name: string; status: 'pending' | 'checking' | 'success' | 'error'; message: string }>>([])
const envAllPassed = computed(() => envChecks.value.length > 0 && envChecks.value.every((c) => c.status === 'success'))

async function applyProjectConfig(pid: number | null) {
  if (!pid) return
  try {
    const res: any = await uiProjectApi.get(pid)
    const p = res.data
  if (!p) return
  if (p.base_url && !form.url) form.url = p.base_url
  if (p.browser_type) {
    const bt = String(p.browser_type).toLowerCase()
    // 兼容旧数据：msedge/chromium/webkit 映射到新的统一命名
    const compatMap: Record<string, string> = {
      msedge: 'edge',
      chromium: 'chrome',
      webkit: 'safari'
    }
    form.browserType = compatMap[bt] || bt
  }
  if (p.viewport_width != null) form.viewportWidth = Number(p.viewport_width)
  if (p.viewport_height != null) form.viewportHeight = Number(p.viewport_height)
  } catch (e) {
    ElMessage.error(`加载项目配置失败（项目ID: ${pid}）`)
  }
}

watch(() => form.projectId, applyProjectConfig)

onMounted(async () => {
  try {
    const res: any = await uiProjectApi.list({ page: 1, page_size: 200 })
    projects.value = res.data?.items || res.data || []
    const rawQid = route.query.projectId
    if (rawQid) {
      const pid = Number(rawQid)
      if (!isNaN(pid) && pid > 0) {
        form.projectId = pid
        await applyProjectConfig(pid)
      }
    }
  } catch (e) {
    ElMessage.error('加载 UI 项目失败')
  }
})

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
})

function stepLabel(t: string) {
  return { navigate: '导航', click: '点击', fill: '输入', assert: '断言', waitFor: '等待' }[t] || t
}
function stepColor(t: string) {
  return { navigate: 'info', click: 'primary', fill: 'warning', assert: 'success', waitFor: 'info' }[t] || ''
}

function openEnvCheck() {
  if (!form.projectId) {
    ElMessage.warning('请先选择 UI 项目')
    return
  }
  envCheckVisible.value = true
  runEnvCheck()
}

async function runEnvCheck() {
  envChecking.value = true
  envChecks.value = [
    { name: '后端服务连通性', status: 'pending', message: '' },
    { name: `浏览器可用性（${form.browserType}）`, status: 'pending', message: '' },
    { name: '起始 URL 格式', status: 'pending', message: '' },
  ]

  // 1. 后端服务连通性
  const check1 = envChecks.value[0]
  check1.status = 'checking'
  try {
    await uiProjectApi.list({ page: 1, page_size: 1 })
    check1.status = 'success'
    check1.message = '后端服务正常'
  } catch (e: any) {
    check1.status = 'error'
    check1.message = e?.response?.data?.message || '无法连接到后端服务'
  }

  // 2. 浏览器可用性
  const check2 = envChecks.value[1]
  check2.status = 'checking'
  try {
    const res: any = await uiBrowserApi.checkPlaywright(form.browserType, true)
    if (res.data?.is_available) {
      check2.status = 'success'
      check2.message = res.data?.message || '浏览器可正常启动'
    } else {
      check2.status = 'error'
      check2.message = res.data?.message || '浏览器不可用'
    }
  } catch (e: any) {
    check2.status = 'error'
    const timedOut = e?.code === 'ECONNABORTED' || /timeout/i.test(e?.message || '')
    check2.message = timedOut
      ? '环境检测超时（>15s）：后端服务无法拉起 Playwright 浏览器，请检查后端日志/浏览器安装'
      : (e?.response?.data?.message || '浏览器检测请求失败')
  }

  // 3. URL 格式
  const check3 = envChecks.value[2]
  check3.status = 'checking'
  const url = (form.url || '').trim()
  if (!url) {
    check3.status = 'success'
    check3.message = '未填写起始 URL，将使用 about:blank'
  } else {
    try {
      new URL(url)
      check3.status = 'success'
      check3.message = 'URL 格式正确'
    } catch {
      check3.status = 'error'
      check3.message = '起始 URL 格式不正确，请以 http:// 或 https:// 开头'
    }
  }

  envChecking.value = false
}

async function confirmStartRecord() {
  if (!envAllPassed.value) {
    ElMessage.warning('请确保所有前置检测项通过后再开始录制')
    return
  }
  envCheckVisible.value = false
  await doStartRecord()
}

async function doStartRecord() {
  if (!form.projectId) return
  const payload = {
    url: form.url || undefined,
    name: form.name || undefined,
    browser_type: form.browserType,
    viewport_width: form.viewportWidth,
    viewport_height: form.viewportHeight,
    color_scheme: form.colorScheme || undefined,
    locale: form.locale || undefined,
    timezone: form.timezone || undefined,
    headless: form.headless,
  }
  try {
    const res: any = await uiRecordApi.start(form.projectId, payload)
    sessionId.value = res.data.session_id
    running.value = true
    paused.value = false
    pickResult.value = null
    steps.value = []
    startPolling()
    const tip = form.headless ? '录制已启动（无头模式），请继续操作' : '录制已启动，请在弹出的浏览器中操作'
    ElMessage.success(tip)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.message || '启动录制失败')
  }
}

async function stopRecord() {
  if (sessionId.value == null) return
  try {
    const res: any = await uiRecordApi.stop(sessionId.value)
    running.value = false
    paused.value = false
    if (pollTimer) clearInterval(pollTimer)
    await refreshSteps()
    ElMessage.success(`录制完成，已生成用例 #${res.data.test_case_id}，共 ${res.data.steps_count} 步`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.message || '停止录制失败')
  }
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(refreshSteps, 1000)
}

async function refreshSteps() {
  if (sessionId.value == null) return
  try {
    const res: any = await uiRecordApi.steps(sessionId.value)
    steps.value = res.data.steps || []
    paused.value = !!res.data.paused
  } catch (e) {
    /* 忽略轮询错误 */
  }
}

async function togglePause() {
  if (sessionId.value == null) return
  try {
    if (paused.value) {
      await uiRecordApi.resume(sessionId.value)
      paused.value = false
      ElMessage.success('已继续录制')
    } else {
      await uiRecordApi.pause(sessionId.value)
      paused.value = true
      ElMessage.info('已暂停录制，页面操作不再生成步骤')
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.message || '操作失败')
  }
}

async function setAssert(mode: string) {
  if (sessionId.value == null) return
  await uiRecordApi.assertMode(sessionId.value, { mode })
  ElMessage.info(`已开启「${mode}」断言，请在浏览器中点击目标元素`)
}

function openRecordedPage() {
  if (form.url) {
    window.open(form.url, '_blank')
  }
}

async function startPick() {
  if (sessionId.value == null) return
  await uiRecordApi.pick(sessionId.value)
  ElMessage.info('已开启拾取，请点击浏览器中的元素')
  // 轮询拾取结果
  for (let i = 0; i < 20; i++) {
    await new Promise((r) => setTimeout(r, 500))
    try {
      const res: any = await uiRecordApi.getPick(sessionId.value!)
      if (res.data && res.data.locators && res.data.locators.length) {
        pickResult.value = res.data
        const top = res.data.locators[0]
        pickText.value = `${top.strategy} = ${top.value}`
        break
      }
    } catch (e) { /* ignore */ }
  }
}

async function doImport(kind: 'codegen' | 'side') {
  if (!form.projectId) return
  const payload = {
    ui_project_id: form.projectId,
    name: form.name || undefined,
    code: kind === 'codegen' ? importCode.value : undefined,
    side_json: kind === 'side' ? importSide.value : undefined,
  }
  try {
    const res: any = kind === 'codegen'
      ? await uiRecordApi.importCodegen(payload)
      : await uiRecordApi.importSide(payload)
    ElMessage.success(`导入成功，生成用例 #${res.data.test_case_id}，共 ${res.data.steps_count} 步`)
    if (kind === 'codegen') importCode.value = ''
    else importSide.value = ''
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.message || '导入失败')
  }
}
</script>

<style scoped>
.recorder-container { padding: 16px; }
.sep { margin: 0 8px; color: #999; }
.hint { margin-left: 8px; color: #909399; font-size: 12px; }
.actions { display: flex; gap: 10px; }
.card-header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.assert-bar { display: flex; flex-wrap: wrap; gap: 8px; }
.step-line { display: flex; align-items: center; gap: 8px; }
.desc { color: #333; }
.assert-info { margin-top: 4px; color: #67c23a; font-size: 12px; }
.env-check-intro { color: #606266; font-size: 14px; }
.env-check-list { display: flex; flex-direction: column; gap: 16px; }
.env-check-item { display: flex; align-items: flex-start; gap: 12px; }
.status-icon { margin-top: 2px; font-size: 20px; }
.env-check-body { flex: 1; }
.env-check-name { font-weight: 500; color: #303133; }
.env-check-msg { margin-top: 4px; font-size: 13px; color: #909399; word-break: break-all; overflow-wrap: break-word; line-height: 1.5; }
.env-check-msg.success { color: #67c23a; }
.env-check-msg.error { color: #f56c6c; }
.dialog-footer { display: flex; justify-content: flex-end; gap: 10px; }
</style>
