<template>
  <div class="script-step-form">
    <!-- Public script selector -->
    <el-form-item label="引用公共脚本" style="margin-bottom: 8px">
      <el-select
        v-model="req.script_id"
        placeholder="引用公共脚本（可选）"
        clearable
        style="width: 100%"
        @visible-change="(open: boolean) => { if (open) loadPublicScripts() }"
      >
        <el-option
          v-for="s in publicScripts"
          :key="s.id"
          :label="s.name"
          :value="s.id"
        />
      </el-select>
      <div v-if="req.script_id" style="font-size:11px;color:#94a3b8;margin-top:4px">
        公共脚本将在内联代码之前执行
      </div>
    </el-form-item>

    <!-- Code editor -->
    <div class="script-toolbar">
      <span class="script-lang">Python</span>
      <el-tooltip placement="top" :show-after="200">
        <template #content>
          <div style="font-size:12px;line-height:1.8">
            <b>ntest API 使用说明</b><br/>
            <code>ntest.get('var')</code> — 读取变量<br/>
            <code>ntest.set('var', val)</code> — 写入变量<br/>
            <code>ntest.env('KEY')</code> — 读取环境变量
          </div>
        </template>
        <el-button type="info" link size="small">API 说明</el-button>
      </el-tooltip>
      <el-button type="primary" link size="small" :loading="validating" @click="runValidate">
        <el-icon style="margin-right:2px"><ele-CircleCheck /></el-icon>AI 校验
      </el-button>
    </div>

    <!-- AI 校验结果 -->
    <div v-if="validateResult" class="validate-result" :class="validateResult.passed ? 'ok' : 'fail'">
      <div class="vr-head">
        <el-tag :type="validateResult.passed ? 'success' : 'danger'" size="small">
          {{ validateResult.passed ? '校验通过' : '校验未通过' }}
        </el-tag>
        <span v-if="validateResult.syntax_ok === false" class="vr-item">❌ 语法: {{ validateResult.syntax_error }}</span>
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
        <div class="vr-title">AI 审查（{{ aiVerdictText }}）：</div>
        <div v-if="validateResult.ai_review.summary" class="vr-line">{{ validateResult.ai_review.summary }}</div>
        <div v-for="(s, i) in validateResult.ai_review.suggestions || []" :key="'sg' + i" class="vr-line suggest">💡 {{ s }}</div>
      </template>
    </div>
    <textarea
      v-model="req.script_content"
      class="script-editor"
      placeholder="# 示例：
# token = ntest.get('token')
# ntest.set('new_var', token + '_suffix')
# print('调试输出')
"
      spellcheck="false"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useApiAutomationApi } from '/@/api/v1/testing/apiAutomation'
import { onNtestScriptsChanged } from '../../composables/scriptListSync'

const props = defineProps<{ step: any; serviceId?: number }>()

const { ntest_script_list } = useApiAutomationApi()

const publicScripts = ref<{ id: number; name: string }[]>([])

const req = computed(() => {
  if (!props.step.request) props.step.request = { script_content: '', script_id: undefined }
  if (!('script_id' in props.step.request)) props.step.request.script_id = undefined
  return props.step.request
})

const validating = ref(false)
const validateResult = ref<any>(null)

const aiVerdictText = computed(() => {
  const v = validateResult.value?.ai_review?.verdict
  return v === 'pass' ? '通过' : v === 'fail' ? '不通过' : '提示'
})

const runValidate = async () => {
  const code = req.value.script_content || ''
  if (!code.trim()) {
    validateResult.value = { passed: false, syntax_ok: false, syntax_error: '脚本内容为空', spec_issues: [], run_ok: null, ai_review: null }
    return
  }
  validating.value = true
  try {
    const { script_validate } = useApiAutomationApi()
    const res: any = await script_validate({ code, language: 'python', use_ai: true })
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

const loadPublicScripts = async () => {
  if (!props.serviceId) return
  try {
    const res: any = await ntest_script_list({ api_service_id: props.serviceId })
    publicScripts.value = Array.isArray(res?.data) ? res.data.map((s: any) => ({ id: s.id, name: s.name })) : []
  } catch {
    publicScripts.value = []
  }
}

let offScriptListSync: (() => void) | null = null
onMounted(() => {
  loadPublicScripts()
  offScriptListSync = onNtestScriptsChanged((sid) => {
    if (Number(props.serviceId || 0) === sid) loadPublicScripts()
  })
})
onBeforeUnmount(() => {
  offScriptListSync?.()
  offScriptListSync = null
})
</script>

<style scoped>
.script-step-form { display: flex; flex-direction: column; gap: 4px; }
.script-toolbar {
  display: flex; align-items: center; justify-content: space-between;
  background: #1e1e2e; border-radius: 6px 6px 0 0; padding: 4px 10px;
}
.script-lang { font-size: 11px; color: #a6adc8; font-family: monospace; }
.validate-result {
  margin-top: 6px; padding: 8px 12px; border-radius: 6px; font-size: 12.5px; line-height: 1.7;
  border: 1px solid;
}
.validate-result.ok { background: #f0fdf4; border-color: #bbf7d0; color: #166534; }
.validate-result.fail { background: #fef2f2; border-color: #fecaca; color: #991b1b; }
.vr-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.vr-title { font-weight: 600; margin-top: 4px; }
.vr-line { margin-left: 4px; }
.vr-line.suggest { color: #b45309; }
.script-editor {
  width: 100%; min-height: 140px; padding: 10px 12px;
  background: #1e1e2e; color: #cdd6f4;
  border: none; border-radius: 0 0 6px 6px;
  font-family: 'Fira Code', 'Consolas', monospace; font-size: 13px;
  line-height: 1.6; resize: vertical; outline: none;
  box-sizing: border-box;
}
</style>
