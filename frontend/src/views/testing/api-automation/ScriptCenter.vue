<template>
  <div class="sc-root">

  
    <div v-if="detailScript" class="sc-fullscreen">
      <div class="sc-fullscreen__header">
        <div class="sc-fullscreen__title">
          <span class="sc-lang-badge" :class="langBadgeClass(detailScript.language)">{{ langLabel(detailScript.language) }}</span>
          <span style="color:#cdd6f4;font-size:15px;font-weight:600">{{ detailScript.name }}</span>
          <span v-if="detailScript.description" style="color:#6c7086;font-size:12px">{{ detailScript.description }}</span>
        </div>
        <div class="sc-fullscreen__actions">
          <el-radio-group v-if="normalizeLang(detailScript.language)==='python'" v-model="execMode" size="small">
            <el-radio-button value="sandbox">沙盒</el-radio-button>
            <el-radio-button value="native">原生</el-radio-button>
          </el-radio-group>
          <el-tag v-else size="small" type="warning" effect="plain">JS 仅原生(Node)</el-tag>
          <el-tooltip content="ntest.get('var') / ntest.set('var', val) / ntest.env('KEY')" placement="bottom">
            <el-button type="info" link size="small" style="color:#a6adc8">API 说明</el-button>
          </el-tooltip>
          <el-button type="success" size="small" :loading="running" @click="runScript(detailScript)">
            <el-icon><ele-VideoPlay /></el-icon>&nbsp;运行
          </el-button>
          <el-button size="small" @click="saveDetail">保存</el-button>
          <el-button size="small" @click="detailScript = null">关闭</el-button>
        </div>
      </div>
      <textarea
        v-model="detailScript.code"
        class="sc-fullscreen__editor"
        spellcheck="false"
      />
      <!-- Run output -->
      <div v-if="runOutput !== null" class="sc-run-output">
        <div class="sc-run-output__header">
          <span>执行输出</span>
          <el-button link size="small" @click="runOutput = null">清除</el-button>
        </div>
        <pre class="sc-run-output__body">{{ runOutput }}</pre>
      </div>
    </div>

    <!-- ── List view ── -->
    <template v-else>
      <div class="sc-toolbar">
        <el-input
          v-model="keyword"
          placeholder="搜索脚本名称或描述"
          clearable
          style="width: 260px"
          prefix-icon="ele-Search"
        />
        <el-button type="primary" @click="openAdd">
          <el-icon><ele-Plus /></el-icon>&nbsp;新增脚本
        </el-button>
        <div class="sc-mode-switch">
          <span class="sc-mode-label">执行模式</span>
          <el-radio-group v-model="execMode" size="small">
            <el-radio-button value="sandbox">沙盒</el-radio-button>
            <el-radio-button value="native">原生</el-radio-button>
          </el-radio-group>
          <el-tooltip placement="bottom" :show-after="200">
            <template #content>
              <div style="max-width:280px;line-height:1.6;font-size:12px">
                <b>沙盒</b>：仅 Python，受限执行<br/>
                <b>原生</b>：本机 Python / Node，可任意依赖（仅信任环境）<br/>
                JavaScript 脚本固定走 Node 原生执行
              </div>
            </template>
            <el-icon style="cursor:help;color:var(--el-text-color-placeholder)"><ele-QuestionFilled /></el-icon>
          </el-tooltip>
        </div>
      </div>

      <el-table
        v-loading="loading"
        :data="filteredList"
        border
        stripe
        empty-text="暂无脚本"
        style="width: 100%"
      >
        <el-table-column label="脚本名称" min-width="180">
          <template #default="{ row }">
            <el-button type="primary" link @click="openDetail(row)">{{ row.name }}</el-button>
          </template>
        </el-table-column>
        <el-table-column label="脚本类型" width="100" align="center">
          <template #default="{ row }">
            <el-tag
              size="small"
              :style="normalizeLang(row.language)==='javascript'
                ? 'background:#f7df1e;border:none;color:#323330;font-weight:700'
                : 'background:#3776ab;border:none;color:#fff;font-weight:700'"
            >{{ normalizeLang(row.language)==='javascript' ? 'JS' : 'Py' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="备注" min-width="160" show-overflow-tooltip />
        <el-table-column label="操作" width="220" align="center" fixed="right">
          <template #default="{ row }">
            <div style="display:flex;gap:4px;justify-content:center;flex-wrap:nowrap;white-space:nowrap">
              <el-button type="primary" size="small" @click="openFuncList(row)">执行</el-button>
              <el-button type="warning" size="small" @click="openEdit(row)">编辑</el-button>
              <el-button type="danger" size="small" @click="deleteScript(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </template>

    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? '编辑脚本' : '新增脚本'"
      width="720px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
        <el-form-item label="脚本名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入脚本名称" />
        </el-form-item>
        <el-form-item label="语言" prop="language">
          <el-radio-group v-model="form.language" size="small" @change="onLangChange">
            <el-radio-button value="python">Python</el-radio-button>
            <el-radio-button value="javascript">JavaScript</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.description" placeholder="可选描述" />
        </el-form-item>
        <el-form-item label="外部程序">
          <div class="sc-ext-field">
            <el-upload :show-file-list="false" :http-request="doUploadFile" accept=".py,.js,.jar,.php,.bsh,.go,.sh,.rb,.lua,.rs,.bat,.ps1,.exe,.java,.ts,.c,.cpp">
              <el-button size="small" type="primary" plain>
                <el-icon style="margin-right:3px"><ele-Upload /></el-icon>上传文件
              </el-button>
            </el-upload>
            <span class="sc-ext-hint">支持 .jar/.php/.js/.py/.bsh/.go/.sh/.rb/.lua/.rs/.bat/.ps1；脚本内用 pm.executeAsync('python', ['D:/GeniusQA/backend/scripts_ext/文件名']) 调用（原生模式）</span>
            <div v-if="form.external_files.length" class="sc-ext-tags">
              <el-tag v-for="(f, i) in form.external_files" :key="i" size="small" type="info" effect="plain" closable @close="removeExtFile(i)" style="margin-right:6px">
                {{ f.name }}
              </el-tag>
            </div>
          </div>
        </el-form-item>
        <el-form-item label="代码">
          <div class="sc-editor-wrap">
            <div class="sc-editor-toolbar">
              <span class="sc-lang-badge" :class="langBadgeClass(form.language)">{{ langLabel(form.language) }}</span>
              <el-tooltip placement="top" :show-after="200">
                <template #content>
                  <div style="font-size:12px;line-height:1.8">
                    <b>ntest API 使用说明</b><br/>
                    <code>ntest.get('var')</code> — 读取变量<br/>
                    <code>ntest.set('var', val)</code> — 写入变量<br/>
                    <code>ntest.env('KEY')</code> — 读取环境变量
                  </div>
                </template>
                <el-icon style="cursor:pointer;color:#94a3b8"><ele-QuestionFilled /></el-icon>
              </el-tooltip>
              <el-button type="primary" link size="small" style="margin-left:auto" :loading="validating" @click="runValidate">
                <el-icon style="margin-right:2px"><ele-CircleCheck /></el-icon>AI 校验
              </el-button>
            </div>
            <textarea
              v-model="form.code"
              class="sc-code-editor"
              :placeholder="codePlaceholder"
              spellcheck="false"
            />


            <!-- AI 校验结果 -->
            <div v-if="validateResult" class="sc-validate" :class="validateResult.passed ? 'ok' : 'fail'">
              <div class="vr-head">
                <el-tag :type="validateResult.passed ? 'success' : 'danger'" size="small">
                  {{ validateResult.passed ? '校验通过' : '校验未通过' }}
                </el-tag>
                <span v-if="validateResult.syntax_ok === false" class="vr-item">{{ validateResult.syntax_error }}</span>
              </div>
              <template v-if="validateResult.spec_issues && validateResult.spec_issues.length">
                <div class="vr-title">规范问题：</div>
                <div v-for="(s, i) in validateResult.spec_issues" :key="'sp' + i" class="vr-line">• {{ s }}</div>
              </template>
              <template v-if="validateResult.run_ok === false">
                <div class="vr-title">试运行失败：</div>
                <div class="vr-line">{{ validateResult.run_error }}</div>
              </template>
              <template v-if="validateResult.ai_review">
                <div class="vr-title">AI 审查：</div>
                <div v-if="validateResult.ai_review.summary" class="vr-line">{{ validateResult.ai_review.summary }}</div>
                <div v-for="(s, i) in validateResult.ai_review.suggestions || []" :key="'sg' + i" class="vr-line suggest">💡 {{ s }}</div>
              </template>
            </div>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>


    <el-dialog
      v-model="funcListVisible"
      :title="`函数列表 — ${funcListScript?.name || ''}`"
      width="760px"
      :close-on-click-modal="false"
    >
      <div style="margin-bottom:10px;display:flex;gap:8px">
        <el-input v-model="funcSearch" placeholder="输入函数名或说明查询" clearable style="width:240px" />
      </div>
      <div style="max-height:480px;overflow-y:auto">
        <div v-if="(funcListScript?.external_files || []).length" class="fl-ext">
          <div class="fl-ext-title">外部程序文件（点击执行查看运行结果）</div>
          <div v-for="(f, i) in funcListScript.external_files" :key="i" class="fl-ext-item">
            <el-icon style="margin-right:4px;color:#64748b"><Document /></el-icon>
            <span class="fl-ext-name">{{ f.name }}</span>
            <el-button type="primary" link size="small" :loading="extRunning === i" @click="execExternalFile(f, i)">执行</el-button>
          </div>
          <div v-if="extOutput" class="fl-ext-output"><pre>{{ extOutput }}</pre></div>
        </div>
        <el-table :data="filteredFuncs" border stripe empty-text="未解析到函数定义">
          <el-table-column prop="name" label="函数名称" width="200">
            <template #default="{ row }">
              <code style="color:#6366f1;font-weight:700">{{ row.name }}</code>
            </template>
          </el-table-column>
          <el-table-column prop="args" label="参数" width="200">
            <template #default="{ row }">
              <code style="color:#94a3b8">{{ row.args }}</code>
            </template>
          </el-table-column>
          <el-table-column prop="doc" label="说明" show-overflow-tooltip />
          <el-table-column label="操作" width="80" align="center">
            <template #default="{ row }">
              <el-button type="primary" size="small" @click="openDebugFunc(row)">调试</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-dialog>

  
    <el-dialog
      v-model="debugFuncVisible"
      :title="`函数调试 — ${debugFunc?.name || ''}`"
      width="600px"
      :close-on-click-modal="false"
      append-to-body
      destroy-on-close
    >
      <el-descriptions :title="`${debugFunc?.name}(${debugFunc?.args})`" :column="1" border size="small">
        <template #extra>
          <div style="display:flex;align-items:center;gap:10px">
            <el-radio-group v-if="normalizeLang(funcListScript?.language)==='python'" v-model="execMode" size="small">
              <el-radio-button value="sandbox">沙盒</el-radio-button>
              <el-radio-button value="native">原生</el-radio-button>
            </el-radio-group>
            <el-tag v-else size="small" type="warning" effect="plain">JS 仅原生</el-tag>
            <el-button type="primary" :loading="running" @click="execDebugFunc">执行</el-button>
          </div>
        </template>
        <el-descriptions-item label="说明" width="100px">
          <span style="white-space:pre-wrap;font-weight:600">{{ debugFunc?.doc || '—' }}</span>
        </el-descriptions-item>
        <el-descriptions-item
          v-for="(_, key) in debugFuncArgs"
          :key="key"
          :label="String(key)"
          width="100px"
        >
          <el-input v-model="debugFuncArgs[key]" />
        </el-descriptions-item>
        <el-descriptions-item label="执行结果" width="100px">
          <pre class="sc-debug-result">{{ debugFuncResult ?? '（点击执行）' }}</pre>
        </el-descriptions-item>
      </el-descriptions>
    </el-dialog>

  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useApiAutomationApi } from '/@/api/v1/testing/apiAutomation'
import { Local } from '/@/utils/storage'
import { notifyNtestScriptsChanged } from './composables/scriptListSync'

const props = defineProps<{ serviceId: number }>()

const { ntest_script_list, add_ntest_script, edit_ntest_script, del_ntest_script, run_api_script, get_api_script_result, upload_script_file, del_script_file } = useApiAutomationApi()

// ─── State ────────────────────────────────────────────────────────────────────
const scriptList = ref<any[]>([])
const keyword = ref('')
const loading = ref(false)
const saving = ref(false)
const validating = ref(false)
const validateResult = ref<any>(null)

const runValidate = async () => {
  const code = form.code || ''
  if (!code.trim()) {
    validateResult.value = { passed: false, syntax_ok: false, syntax_error: '脚本内容为空', spec_issues: [], run_ok: null, ai_review: null }
    return
  }
  validating.value = true
  try {
    const res: any = await useApiAutomationApi().script_validate({ code, language: form.language, exec_mode: execMode.value, use_ai: true })
    if (res.code === 200) {
      validateResult.value = res.data
    } else {
      validateResult.value = { passed: false, syntax_ok: true, syntax_error: '', spec_issues: [res.message || '校验失败'], run_ok: null, ai_review: null }
    }
  } catch (e: any) {
    validateResult.value = { passed: false, syntax_ok: true, syntax_error: '', spec_issues: [e?.message || '校验接口调用失败'], run_ok: null, ai_review: null }
  } finally {
    validating.value = false
  }
}

const dialogVisible = ref(false)
const isEdit = ref(false)
const formRef = ref<any>(null)
const form = ref({
  id: undefined as number | undefined,
  name: '',
  description: '',
  code: '',
  language: 'python',
  external_files: [] as any[],
})

// Detail / fullscreen
const detailScript = ref<any>(null)

// Run state
const running = ref(false)
const runningId = ref<number | null>(null)
const runOutput = ref<string | null>(null)

const EXEC_MODE_STORAGE_KEY = 'api_automation:last_exec_mode'
const readLastExecMode = (): 'sandbox' | 'native' => {
  try {
    const v = String(Local.get(EXEC_MODE_STORAGE_KEY) || '').toLowerCase()
    return v === 'native' ? 'native' : 'sandbox'
  } catch {
    return 'sandbox'
  }
}
const execMode = ref<'sandbox' | 'native'>(readLastExecMode())
watch(execMode, (mode) => {
  Local.set(EXEC_MODE_STORAGE_KEY, mode)
})

const normalizeLang = (lang: any): 'python' | 'javascript' => {
  const v = String(lang || 'python').toLowerCase()
  return (v === 'js' || v === 'javascript' || v === 'node' || v === 'nodejs') ? 'javascript' : 'python'
}
const langLabel = (lang: any) => normalizeLang(lang) === 'javascript' ? 'JavaScript' : 'Python'
const langBadgeClass = (lang: any) => normalizeLang(lang) === 'javascript' ? 'is-js' : ''
const effectiveExecMode = (lang: any) => normalizeLang(lang) === 'javascript' ? 'native' : execMode.value
const codePlaceholder = computed(() =>
  form.value.language === 'javascript'
    ? "// 在此编写 JavaScript 脚本\n// ntest.set('result', 'hello')\n// const val = ntest.get('some_var')"
    : "# 在此编写 Python 脚本\n# ntest.set('result', 'hello')\n# val = ntest.get('some_var')"
)


const funcListVisible = ref(false)
const funcListScript = ref<any>(null)
const funcSearch = ref('')
const parsedFuncs = ref<{ name: string; args: string; doc: string }[]>([])

const filteredFuncs = computed(() => {
  const kw = funcSearch.value.trim().toLowerCase()
  if (!kw) return parsedFuncs.value
  return parsedFuncs.value.filter(f =>
    f.name.toLowerCase().includes(kw) || f.doc.toLowerCase().includes(kw)
  )
})

// Debug func state
const debugFuncVisible = ref(false)
const debugFunc = ref<any>(null)
const debugFuncArgs = ref<Record<string, string>>({})
const debugFuncResult = ref<string | null>(null)

const rules = {
  name: [{ required: true, message: '请输入脚本名称', trigger: 'blur' }],
}

const filteredList = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return scriptList.value
  return scriptList.value.filter(s =>
    (s.name || '').toLowerCase().includes(kw) ||
    (s.description || '').toLowerCase().includes(kw)
  )
})


async function loadScripts() {
  loading.value = true
  try {
    const res: any = await ntest_script_list({ api_service_id: props.serviceId })
    scriptList.value = Array.isArray(res?.data) ? res.data : []
  } catch {
    scriptList.value = []
  } finally {
    loading.value = false
  }
}

let prevLang = 'python'
const onLangChange = (lang: string) => {
  const cm = form.value.code_map || {}
  if (form.value.code) cm[prevLang] = form.value.code
  form.value.code = cm[lang] || ''
  form.value.code_map = cm
  prevLang = lang
}

const doUploadFile = async (opt: any) => {
	try {
		const res: any = await upload_script_file(opt.file)
		if (res?.code === 200 && res?.data) {
			const files = form.value.external_files || []
			// 同名文件替换，避免重复关联
			const idx = files.findIndex((f: any) => f.name === res.data.name)
			if (idx >= 0) files[idx] = res.data
			else files.push(res.data)
			ElMessage.success(res?.message || '上传成功')
		} else {
			ElMessage.error(res?.message || '上传失败')
		}
	} catch (e: any) {
		ElMessage.error(e?.message || '上传失败')
	}
}

const removeExtFile = async (i: number) => {
	const f = form.value.external_files[i]
	try {
		if (f?.path) await del_script_file({ path: f.path })
	} catch {}
	form.value.external_files.splice(i, 1)
}

function openAdd() {
  isEdit.value = false
  form.value = { id: undefined, name: '', description: '', code: '', language: 'python', exec_mode: 'sandbox', code_map: {}, external_files: []}
  prevLang = 'python'
  validateResult.value = null
  dialogVisible.value = true
}

function openEdit(row: any) {
  isEdit.value = true
  form.value = {
    id: row.id,
    name: row.name,
    description: row.description || '',
    code: row.code || '',
    language: row.language || 'python',
    code_map: (row.code_map && typeof row.code_map === 'object') ? row.code_map : { [row.language || 'python']: row.code || '' },
    external_files: Array.isArray(row.external_files) ? row.external_files : [],
  }
  prevLang = form.value.language
  dialogVisible.value = true
}

function openDetail(row: any) {
  // Deep copy so edits don't affect list until saved
  detailScript.value = { ...row }
  runOutput.value = null
}

async function saveDetail() {
  if (!detailScript.value) return
  saving.value = true
  try {
    await edit_ntest_script({
      id: detailScript.value.id,
      name: detailScript.value.name,
      description: detailScript.value.description,
      code: detailScript.value.code,
      language: detailScript.value.language,
      exec_mode: execMode.value,
      code_map: detailScript.value.code_map || { [detailScript.value.language]: detailScript.value.code },
      external_files: detailScript.value.external_files || [],
    })
    ElMessage.success('保存成功')
    await loadScripts()
    notifyNtestScriptsChanged(props.serviceId)
    // Sync back to list
    const idx = scriptList.value.findIndex(s => s.id === detailScript.value.id)
    if (idx >= 0) scriptList.value[idx] = { ...detailScript.value }
  } catch (e: any) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function submitForm() {
  await formRef.value?.validate()
  saving.value = true
  try {
    if (isEdit.value && form.value.id) {
      await edit_ntest_script({
        id: form.value.id,
        name: form.value.name,
        description: form.value.description,
        code: form.value.code,
        language: form.value.language,
        exec_mode: execMode.value,
        code_map: { ...(form.value.code_map || {}), [form.value.language]: form.value.code },
        external_files: form.value.external_files || [],
      })
      ElMessage.success('编辑成功')
    } else {
      await add_ntest_script({
        name: form.value.name,
        description: form.value.description,
        code: form.value.code,
        language: form.value.language,
        exec_mode: execMode.value,
        code_map: { ...(form.value.code_map || {}), [form.value.language]: form.value.code },
        external_files: form.value.external_files || [],
        api_service_id: props.serviceId,
      })
      ElMessage.success('添加成功')
    }
    dialogVisible.value = false
    await loadScripts()
    notifyNtestScriptsChanged(props.serviceId)
  } catch (e: any) {
    ElMessage.error(e?.message || '操作失败')
  } finally {
    saving.value = false
  }
}

async function deleteScript(row: any) {
  try {
    await ElMessageBox.confirm(`确认删除脚本「${row.name}」？`, '提示', {
      type: 'warning',
      confirmButtonText: '确定',
      cancelButtonText: '取消',
    })
    await del_ntest_script({ id: row.id })
    ElMessage.success('删除成功')
    await loadScripts()
    notifyNtestScriptsChanged(props.serviceId)
  } catch {
    // cancelled
  }
}

async function runScript(row: any) {
  const code = row.code || ''
  if (!code.trim()) {
    ElMessage.warning('脚本内容为空，无法运行')
    return
  }
  if (detailScript.value) {
    running.value = true
  } else {
    runningId.value = row.id
  }
  runOutput.value = null
  try {
    const resultId = Date.now()
    const lang = normalizeLang(row.language)
    await run_api_script({
      result_id: resultId,
      name: row.name,
      api_service_id: props.serviceId,
      config: { env_id: 0 },
      run_list: [{
        name: row.name,
        config: {},
        script: [{
          step_type: 'script',
          name: row.name,
          enable: true,
          request: {
            script_content: code,
            exec_mode: effectiveExecMode(lang),
            language: lang,
          },
          extracts: [],
          validators: [],
          children_steps: [],
        }],
      }],
    })
    const step = await fetchScriptStepResult(resultId)
    if (!step) {
      runOutput.value = '执行完成，但未获取到结果'
      return
    }
    const resBody = step.res?.body || step.res || {}
    const output: string = resBody.output || ''
    const vars: Record<string, any> = resBody.vars || {}
    const error: string = step.res?.error || step.error || resBody.exception || resBody.msg || ''
    const lines: string[] = []
    if (output) lines.push('--- 输出 ---\n' + output)
    if (Object.keys(vars).length) lines.push('--- 变量 ---\n' + JSON.stringify(vars, null, 2))
    if (error) lines.push('--- 错误 ---\n' + error)
    if (!step.status && !error) lines.push('--- 状态 ---\n执行失败')
    runOutput.value = lines.join('\n') || '执行完成（无输出）'
  } catch (e: any) {
    runOutput.value = '运行失败: ' + (e?.message || String(e))
  } finally {
    running.value = false
    runningId.value = null
  }
}


async function fetchScriptStepResult(resultId: number) {
  const res: any = await get_api_script_result({ result_id: resultId })
  const list: any[] = Array.isArray(res?.data) ? res.data : []
  return list.find((r: any) => r.name !== '执行结束' && r.name !== '执行开始') || null
}


function parseArgName(raw: string): string {
  return String(raw || '')
    .trim()
    .split('=')[0]
    .trim()
    .split(':')[0]
    .trim()
}


function parseFunctions(code: string, language: string) {
  const funcs: { name: string; args: string; doc: string }[] = []
  if (!code) return funcs
  if (normalizeLang(language) === 'javascript') {
    // function name(...) / async function name(...) / const name = (...) => / const name = function(
    const patterns = [
      /(?:^|\n)\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)/g,
      /(?:^|\n)\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>/g,
      /(?:^|\n)\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?function\s*\(([^)]*)\)/g,
    ]
    const seen = new Set<string>()
    for (const re of patterns) {
      let m: RegExpExecArray | null
      while ((m = re.exec(code)) !== null) {
        const name = m[1]
        if (seen.has(name)) continue
        seen.add(name)
        const before = code.slice(Math.max(0, m.index - 200), m.index)
        const docMatch = before.match(/\/\*\*([\s\S]*?)\*\/\s*$/)
        const doc = docMatch ? docMatch[1].replace(/^\s*\*\s?/gm, '').trim() : ''
        funcs.push({ name, args: (m[2] || '').trim(), doc })
      }
    }
    return funcs
  }
  // Python
  const defRe = /^def\s+(\w+)\s*\(([^)]*)\)\s*(?:->[^:]+)?\s*:/gm
  let m: RegExpExecArray | null
  while ((m = defRe.exec(code)) !== null) {
    const name = m[1]
    const args = m[2].trim()
    const afterDef = code.slice(m.index + m[0].length)
    const docMatch = afterDef.match(/^\s*(?:"""([\s\S]*?)"""|'''([\s\S]*?)''')/)
    const doc = docMatch ? (docMatch[1] || docMatch[2] || '').trim() : ''
    funcs.push({ name, args, doc })
  }
  return funcs
}

function openFuncList(row: any) {
  funcListScript.value = row
  funcSearch.value = ''
  parsedFuncs.value = parseFunctions(row.code || '', row.language)
  funcListVisible.value = true
}

function openDebugFunc(func: any) {
  debugFunc.value = func
  debugFuncResult.value = null
  const argNames = func.args
    ? func.args.split(',').map((a: string) => parseArgName(a)).filter(Boolean)
    : []
  const argsObj: Record<string, string> = {}
  for (const a of argNames) argsObj[a] = ''
  debugFuncArgs.value = argsObj
  debugFuncVisible.value = true
}

const extRunning = ref(-1)
const extOutput = ref('')

async function execExternalFile(f: any, i: number) {
	if (!funcListScript.value) return
	extRunning.value = i
	extOutput.value = '执行中...'
	try {
		const lang = normalizeLang(funcListScript.value.language)
		const ext = String(f.name || '').split('.').pop()?.toLowerCase() || ''
		let cmd = 'python'
		const args: string[] = []
		if (ext === 'js') cmd = 'node'
		else if (ext === 'jar') { cmd = 'java'; args.push('-jar') }
		else if (ext === 'php') cmd = 'php'
		else if (ext === 'bsh') { cmd = 'java'; args.push('bsh.Interpreter') }
		else if (ext === 'go') { cmd = 'go'; args.push('run') }
		else if (ext === 'sh') cmd = 'bash'
		else if (ext === 'rb') cmd = 'ruby'
		else if (ext === 'lua') cmd = 'lua'
		else if (ext === 'rs') { cmd = 'cargo'; args.push('run') }
		else if (ext === 'bat') { cmd = 'cmd'; args.push('/c') }
		else if (ext === 'ps1') { cmd = 'powershell'; args.push('-File') }
		const filePath = f.path || `D:/GeniusQA/backend/scripts_ext/${f.name}`
		const cmdJson = JSON.stringify(cmd)
		const argsJson = JSON.stringify([...args, filePath])
		const fullCode = lang === 'javascript'
			? `const _extOut = pm.executeAsync(${cmdJson}, ${argsJson});\nconsole.log('=== 外部程序输出 ===');\nconsole.log(_extOut);\nntest.set('_result', _extOut);`
			: `_extOut = pm.executeAsync(${cmdJson}, ${argsJson})\nprint('=== 外部程序输出 ===')\nprint(_extOut)\nntest.set('_result', _extOut)`
		const resultId = Date.now()
		const stepName = `执行外部文件: ${f.name}`

		await run_api_script({
			result_id: resultId,
			name: stepName,
			api_service_id: props.serviceId,
			config: { env_id: 0 },
			run_list: [{
				name: stepName,
				config: {},
				script: [{
					step_type: 'script',
					name: stepName,
					enable: true,
					request: {
						script_content: fullCode,
						exec_mode: 'native',
						language: lang,
					},
					extracts: [],
					validators: [],
					children_steps: [],
				}],
			}],
		})

		const step = await fetchScriptStepResult(resultId)
		if (!step) {
			extOutput.value = '执行完成，但未获取到结果'
			return
		}
		const resBody = step.res?.body || step.res || {}
		const output: string = resBody.output || ''
		const vars: Record<string, any> = resBody.vars || {}
		const error: string = step.res?.error || step.error || resBody.exception || resBody.msg || ''
		const lines: string[] = []
		if (vars._result !== undefined) lines.push('返回值:\n' + JSON.stringify(vars._result, null, 2))
		if (output.trim()) lines.push('输出:\n' + output.trim())
		if (error) lines.push('错误:\n' + error)
		if (!step.status && !error) lines.push('错误:\n执行失败')
		if (!lines.length) lines.push(JSON.stringify(step.res, null, 2) || '执行完成（无输出）')
		extOutput.value = lines.join('\n\n')
	} catch (e: any) {
		extOutput.value = '执行失败: ' + (e?.message || String(e))
	} finally {
		extRunning.value = -1
	}
}

async function execDebugFunc() {
  if (!debugFunc.value || !funcListScript.value) return
  running.value = true
  debugFuncResult.value = '执行中...'
  try {
    const lang = normalizeLang(funcListScript.value.language)
    const argsLiteral = Object.values(debugFuncArgs.value).map(v => {
      const s = String(v ?? '').trim()
      if (!s) return lang === 'javascript' ? 'undefined' : 'None'
      try { return JSON.stringify(JSON.parse(s)) } catch { return JSON.stringify(s) }
    }).join(', ')
    const callCode = `${debugFunc.value.name}(${argsLiteral})`
    const fullCode = lang === 'javascript'
      ? `${funcListScript.value.code || ''}\n\nconst _result = ${callCode};\nntest.set('_result', _result);\nconsole.log('结果:', _result);`
      : `${funcListScript.value.code || ''}\n\n_result = ${callCode}\nntest.set('_result', _result)\nprint('结果:', _result)`
    const resultId = Date.now()
    const stepName = `调试: ${debugFunc.value.name}`

    await run_api_script({
      result_id: resultId,
      name: stepName,
      api_service_id: props.serviceId,
      config: { env_id: 0 },
      run_list: [{
        name: stepName,
        config: {},
        script: [{
          step_type: 'script',
          name: stepName,
          enable: true,
          request: {
            script_content: fullCode,
            exec_mode: effectiveExecMode(lang),
            language: lang,
          },
          extracts: [],
          validators: [],
          children_steps: [],
        }],
      }],
    })

    const step = await fetchScriptStepResult(resultId)
    if (!step) {
      debugFuncResult.value = '执行完成，但未获取到结果'
      return
    }
    const resBody = step.res?.body || step.res || {}
    const output: string = resBody.output || ''
    const vars: Record<string, any> = resBody.vars || {}
    const error: string = step.res?.error || step.error || resBody.exception || resBody.msg || ''
    const lines: string[] = []
    if (vars._result !== undefined) {
      lines.push('返回值:\n' + JSON.stringify(vars._result, null, 2))
    }
    if (output.trim()) {
      lines.push('输出:\n' + output.trim())
    }
    if (error) {
      lines.push('错误:\n' + error)
    }
    if (!step.status && !error) {
      lines.push('错误:\n执行失败')
    }
    if (!lines.length) {
      lines.push(JSON.stringify(step.res, null, 2) || '执行完成（无输出）')
    }
    debugFuncResult.value = lines.join('\n\n')
  } catch (e: any) {
    debugFuncResult.value = '执行失败: ' + (e?.message || String(e))
  } finally {
    running.value = false
  }
}

onMounted(loadScripts)
</script>

<style scoped>
.sc-root {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
  box-sizing: border-box;
}

.sc-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}
.sc-mode-switch {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}
.sc-mode-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

/* ── Fullscreen editor ── */
.sc-fullscreen {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #1e1e2e;
  border-radius: 8px;
  overflow: hidden;
}

.sc-fullscreen__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  background: #181825;
  border-bottom: 1px solid #313244;
  flex-shrink: 0;
}

.sc-fullscreen__title {
  display: flex;
  align-items: center;
  gap: 10px;
}

.sc-fullscreen__actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.sc-fullscreen__editor {
  flex: 1;
  width: 100%;
  padding: 16px;
  background: #1e1e2e;
  color: #cdd6f4;
  font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.7;
  border: none;
  outline: none;
  resize: none;
  box-sizing: border-box;
  tab-size: 4;
}

/* ── Run output panel ── */
.sc-run-output {
  flex-shrink: 0;
  max-height: 200px;
  background: #11111b;
  border-top: 1px solid #313244;
  display: flex;
  flex-direction: column;
}

.sc-run-output__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 12px;
  font-size: 12px;
  color: #a6adc8;
  background: #181825;
}

.sc-run-output__body {
  flex: 1;
  overflow-y: auto;
  padding: 8px 12px;
  margin: 0;
  font-family: 'Fira Code', 'Consolas', monospace;
  font-size: 12px;
  color: #a6e3a1;
  white-space: pre-wrap;
  word-break: break-all;
}

/* ── Dialog editor ── */
.sc-editor-wrap {
  width: 100%;
  border: 1px solid var(--el-border-color, #dcdfe6);
  border-radius: 6px;
  overflow: hidden;
}

.sc-editor-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: #2a2a3e;
  border-bottom: 1px solid #3a3a4e;
}
.sc-editor-toolbar :deep(.el-upload) {
  display: inline-flex;
  align-items: center;
  line-height: 1;
  height: 100%;
}
.sc-editor-toolbar :deep(.el-upload .el-button) {
  display: inline-flex;
  align-items: center;
  line-height: 1;
  height: 24px;
}
.sc-editor-toolbar .el-button {
  display: inline-flex;
  align-items: center;
  line-height: 1;
}

.sc-lang-badge {
  font-size: 11px;
  font-weight: 700;
  color: #a78bfa;
  background: rgba(167,139,250,0.15);
  padding: 1px 8px;
  border-radius: 4px;
  letter-spacing: 0.5px;
}
.sc-lang-badge.is-js {
  color: #323330;
  background: #f7df1e;
}

.sc-validate {
  margin-top: 6px; padding: 8px 12px; border-radius: 6px; font-size: 12.5px; line-height: 1.7;
  border: 1px solid;
}
.sc-validate.ok { background: #f0fdf4; border-color: #bbf7d0; color: #166534; }
.sc-validate.fail { background: #fef2f2; border-color: #fecaca; color: #991b1b; }
.vr-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.vr-title { font-weight: 600; margin-top: 4px; }
.vr-line { margin-left: 4px; }
.vr-line.suggest { color: #b45309; }
.sc-ext-field { width: 100%; }
.sc-ext-hint { font-size: 11px; color: #94a3b8; line-height: 1.6; margin: 6px 0 0; display: block; }
.sc-ext-tags { margin-top: 8px; display: flex; align-items: center; flex-wrap: wrap; }
.fl-ext { margin-bottom: 10px; padding: 8px 10px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; }
.fl-ext-title { font-size: 12px; font-weight: 600; color: #334155; margin-bottom: 6px; }
.fl-ext-item { display: flex; align-items: center; gap: 4px; font-size: 13px; padding: 3px 0; }
.fl-ext-name { font-family: 'JetBrains Mono', Consolas, monospace; color: #475569; }
.fl-ext-output { margin-top: 8px; }
.fl-ext-output pre {
	margin: 0; padding: 8px 10px; background: #0f1115; border-radius: 6px;
	font-family: 'JetBrains Mono', Consolas, monospace; font-size: 12px; line-height: 1.55;
	color: #c9d1d9; white-space: pre-wrap; word-break: break-all; max-height: 260px; overflow: auto;
}
.sc-code-editor {
  width: 100%;
  min-height: 280px;
  padding: 12px;
  background: #1e1e2e;
  color: #cdd6f4;
  font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.6;
  border: none;
  outline: none;
  resize: vertical;
  box-sizing: border-box;
  tab-size: 4;
}

.sc-debug-result {
  margin: 0;
  padding: 8px;
  background: #1e1e2e;
  color: #a6e3a1;
  font-family: 'Fira Code', 'Consolas', monospace;
  font-size: 12px;
  border-radius: 4px;
  white-space: pre-wrap;
  word-break: break-all;
  min-height: 60px;
  max-height: 200px;
  overflow-y: auto;
}
</style>
