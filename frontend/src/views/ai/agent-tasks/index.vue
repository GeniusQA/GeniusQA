<template>
  <div class="agent-tasks-page">
    <!-- 搜索卡 -->
    <el-card shadow="hover" class="search-card">
      <el-form :inline="true" :model="queryForm" class="query-form" @submit.prevent>
        <el-form-item label="任务名称">
          <el-input v-model="queryForm.keyword" placeholder="请输入任务名称" clearable style="width: 200px"
                    @keyup.enter="handleQuery" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="queryForm.status" placeholder="全部" clearable style="width: 130px">
            <el-option label="运行中" value="analyzing" />
            <el-option label="待确认" value="awaiting_review" />
            <el-option label="成功" value="done" />
            <el-option label="失败" value="failed" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="handleQuery"><el-icon><ele-Search /></el-icon>查询</el-button>
          <el-button @click="handleReset"><el-icon><ele-Refresh /></el-icon>重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 表格卡 -->
    <el-card shadow="hover" class="table-card">
      <template #header>
        <div class="card-header">
          <span>测试任务列表</span>
          <el-button type="primary" @click="openCreate"><el-icon><ele-Plus /></el-icon>新建测试任务</el-button>
        </div>
      </template>

      <el-table :data="tableData" v-loading="loading" border stripe style="width: 100%">
        <el-table-column prop="id" label="ID" width="70" align="center">
          <template #default="{ row }"><span class="mono">#{{ row.id }}</span></template>
        </el-table-column>
        <el-table-column prop="name" label="任务名称" min-width="200">
          <template #default="{ row }">
            <el-link type="primary" :underline="false" class="task-link" @click="openDetail(row)">{{ row.name }}</el-link>
            <div class="cell-sub">{{ row.input_file || '未上传文档' }} · {{ row.env_name || '测试环境' }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="pipeline_type" label="流水线" width="140">
          <template #default="{ row }">
            <span class="mono">{{ row.pipeline_type === 'api' ? 'api-pipeline' : row.pipeline_type }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.status === 'done'" type="success" size="small">成功</el-tag>
            <el-tag v-else-if="row.status === 'failed'" type="danger" size="small">失败</el-tag>
            <el-tag v-else-if="row.status === 'awaiting_review'" type="warning" size="small">待确认</el-tag>
            <el-tag v-else-if="row.status === 'pending'" type="info" size="small">待运行</el-tag>
            <el-tag v-else type="primary" size="small" effect="plain">
              <span class="running-dot"></span>{{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="140">
          <template #default="{ row }">
            <el-progress :percentage="row.progress || 0" :stroke-width="8"
                         :status="row.status === 'failed' ? 'exception' : row.status === 'done' ? 'success' : undefined" />
          </template>
        </el-table-column>
        <el-table-column prop="creation_date" label="创建时间" width="170">
          <template #default="{ row }">{{ formatDateTime(row.creation_date) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="210" fixed="right" align="center">
          <template #default="{ row }">
            <el-button type="primary" size="small" @click="openDetail(row)">查看</el-button>
            <el-button v-if="['done', 'failed', 'awaiting_review'].includes(row.status)" type="warning" size="small"
                       @click="handleRerun(row)">重跑</el-button>
            <el-button type="danger" size="small" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="queryForm.page"
        v-model:page-size="queryForm.page_size"
        :total="total"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        @size-change="handleQuery"
        @current-change="handleQuery"
        class="pagination"
      />
    </el-card>

    <!-- 创建任务弹窗 -->
    <el-dialog v-model="createVisible" title="新建 AI 测试任务" width="600px" :close-on-click-modal="false">
      <el-form ref="createFormRef" :model="createForm" :rules="createRules" label-width="100px">
        <el-divider content-position="left">流水线配置</el-divider>
        <el-form-item label="任务名称" prop="name">
          <el-input v-model="createForm.name" placeholder="如：登录模块接口回归" style="width: 100%" maxlength="100" show-word-limit />
        </el-form-item>
        <el-form-item label="流水线类型">
          <el-radio-group v-model="createForm.pipeline_type">
            <el-radio value="api">接口自动化 · 三 Agent（需求分析 → 用例生成 → 执行 → 评审）</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-divider content-position="left">输入配置</el-divider>
        <el-form-item label="接口服务">
          <el-select v-model="createForm.api_service_id" placeholder="请选择接口服务（复用接口中心数据）"
                     style="width: 100%" filterable @change="handleServiceChange">
            <el-option v-for="s in serviceOptions" :key="s.id" :label="s.name" :value="s.id" />
          </el-select>
          <div class="form-tip">选择后将以该服务已有的接口文档（Swagger / Apifox）作为输入，无需重复上传</div>
        </el-form-item>
        <el-form-item label="关联项目">
          <el-select v-model="createForm.project_id" placeholder="请选择项目" style="width: 100%"
                     @change="handleProjectChange" filterable>
            <el-option v-for="p in projectOptions" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="执行环境">
          <el-select v-model="createForm.env_name" placeholder="请选择执行环境（接口自动化环境）" style="width: 100%">
            <el-option v-for="e in envOptions" :key="e.id" :label="e.name" :value="e.name" />
          </el-select>
        </el-form-item>
        <el-divider content-position="left">执行策略</el-divider>
        <el-form-item label="执行确认模式">
          <el-radio-group v-model="createForm.exec_mode">
            <el-radio value="manual">人工确认（AI 生成用例后由我确认再执行）</el-radio>
            <el-radio value="auto">自动执行</el-radio>
          </el-radio-group>
          <div class="form-tip">推荐人工确认：避免 AI 生成的用例未经确认直接运行</div>
        </el-form-item>
        <el-form-item label="模型配置">
          <el-select v-model="createForm.model_tier" placeholder="请选择模型（复用 LLM 配置）" style="width: 100%" filterable>
            <el-option v-for="m in llmOptions" :key="m.id" :label="m.config_name + '（' + (m.model_name || m.name) + '）'"
                       :value="m.config_name" />
          </el-select>
          <div class="form-tip">需求分析/用例生成/评审 Agent 将使用所选模型配置</div>
        </el-form-item>
        <el-divider content-position="left">用例生成配置</el-divider>
        <el-form-item label="用例类型">
          <div class="case-type-wrap">
            <div v-for="g in caseTypeGroups" :key="g.key" class="type-group">
              <div class="type-group-head">
                <el-checkbox :model-value="isGroupAll(g.key)" :indeterminate="isGroupPartial(g.key)"
                             @change="toggleGroup(g.key, $event)">{{ g.label }}</el-checkbox>
              </div>
              <el-checkbox-group v-model="caseConfig.types[g.key]" class="type-items">
                <el-checkbox v-for="opt in g.options" :key="opt.value" :value="opt.value" size="small">
                  {{ opt.label }}
                </el-checkbox>
              </el-checkbox-group>
            </div>
          </div>
        </el-form-item>
        <el-form-item label="更多要求">
          <el-input v-model="caseConfig.extra_requirements" type="textarea" :rows="2"
                    placeholder="补充用例生成要求，如：覆盖所有枚举值、响应时间小于 200ms、需要幂等性验证等" />
        </el-form-item>
        <el-form-item label="高级设置">
          <div class="adv-settings">
            <div class="adv-row">
              <span class="adv-label">生成语言</span>
              <el-select v-model="caseConfig.language" style="width: 160px">
                <el-option label="简体中文" value="zh-CN" />
                <el-option label="English" value="en-US" />
              </el-select>
            </div>
            <div class="adv-row">
              <el-switch v-model="caseConfig.step_generation" />
              <div class="adv-text">
                <span>分步生成</span>
                <span class="adv-hint">先生成用例列表（含用例名称和描述），可人工修改，确认后再批量生成用例详情</span>
              </div>
            </div>
            <div class="adv-row">
              <el-switch v-model="caseConfig.auto_complete" />
              <div class="adv-text">
                <span>自动补全用例</span>
                <span class="adv-hint">生成用例列表时，AI 将检测已生成用例的覆盖率，自动补全缺失场景</span>
              </div>
            </div>
            <div class="adv-row">
              <span class="adv-label">补充生成轮次</span>
              <el-radio-group v-model="caseConfig.supplement_rounds">
                <el-radio :value="1">1 轮</el-radio>
                <el-radio :value="2">2 轮</el-radio>
                <el-radio :value="3">3 轮</el-radio>
              </el-radio-group>
              <span class="adv-hint">轮次越多，覆盖越全，耗时与 Token 消耗越大</span>
            </div>
            <div class="adv-row">
              <el-switch v-model="caseConfig.deduplicate" />
              <div class="adv-text">
                <span>不重复生成用例</span>
                <span class="adv-hint">不生成与已有单接口用例重复的用例；关闭后生成不受已有用例影响</span>
              </div>
            </div>
            <div class="adv-row">
              <span class="adv-label">用例数量</span>
              <el-select v-model="caseConfig.case_count" style="width: 200px">
                <el-option label="自动" value="auto" />
                <el-option label="约 10 条" :value="10" />
                <el-option label="约 20 条" :value="20" />
                <el-option label="约 40 条" :value="40" />
                <el-option label="约 80 条" :value="80" />
              </el-select>
            </div>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取 消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">创 建</el-button>
      </template>
    </el-dialog>

    <!-- 任务详情抽屉 -->
    <el-drawer v-model="detailVisible" :title="detailTitle" size="72%" destroy-on-close>
      <div v-loading="detailLoading" class="detail-body">
        <el-alert v-if="detailError" type="error" title="加载任务详情失败" :description="detailError" show-icon
                  :closable="false" style="margin-bottom: 14px">
          <template #default>
            <el-button size="small" style="margin-top: 6px" @click="loadDetail(currentDetailId)">重 试</el-button>
          </template>
        </el-alert>

        <template v-if="detail">
          <el-row :gutter="16" class="stat-row">
            <el-col :span="6"><el-statistic title="测试点" :value="pointCount" /></el-col>
            <el-col :span="6"><el-statistic title="用例数" :value="caseCount" /></el-col>
            <el-col :span="6"><el-statistic title="整体进度" :value="detail.progress || 0" suffix="%" /></el-col>
            <el-col :span="6"><el-statistic title="Token 消耗" :value="detail.token_used || 0" /></el-col>
          </el-row>

          <el-descriptions :column="2" border class="info-desc">
            <el-descriptions-item label="任务 ID"><span class="mono">#T-{{ detail.id }}</span></el-descriptions-item>
            <el-descriptions-item label="流水线">接口自动化 · 三 Agent（含评审）</el-descriptions-item>
            <el-descriptions-item label="输入产物">{{ detail.input_file || '-' }}</el-descriptions-item>
            <el-descriptions-item label="执行策略">{{ detail.exec_mode === 'auto' ? '自动执行' : '人工确认' }} · {{ detail.env_name }}</el-descriptions-item>
          </el-descriptions>

          <el-progress :percentage="detail.progress || 0" :stroke-width="12"
                       :status="detail.status === 'failed' ? 'exception' : detail.status === 'done' ? 'success' : undefined"
                       style="margin: 16px 0" />

          <el-row :gutter="16">
            <el-col :span="10">
              <el-card shadow="never" class="inner-card">
                <template #header><span class="card-title">流水线执行状态</span></template>
                <div class="pipeline">
                  <div v-for="node in pipelineNodes" :key="node.key"
                       :class="['pnode', nodeStateClass(node.key)]">
                    <div class="pnode-icon">
                      <el-icon v-if="nodeState(node.key) === 'done'"><ele-CircleCheckFilled /></el-icon>
                      <el-icon v-else-if="nodeState(node.key) === 'running'" class="is-loading"><ele-Loading /></el-icon>
                      <el-icon v-else><component :is="node.icon" /></el-icon>
                    </div>
                    <div class="pnode-body">
                      <div class="pnode-top">
                        <span class="pnode-name">{{ node.label }}</span>
                        <el-tag :type="nodeTagType(node.key)" size="small">{{ nodeTagText(node.key) }}</el-tag>
                      </div>
                      <div class="pnode-meta">{{ nodeMeta(node.key) }}</div>
                    </div>
                  </div>
                </div>
              </el-card>

              <el-card shadow="never" class="inner-card" style="margin-top: 16px">
                <template #header><span class="card-title">Agent 执行轨迹</span></template>
                <el-timeline v-if="traceList.length">
                  <el-timeline-item v-for="(t, i) in traceList" :key="i" :type="t.type" :timestamp="t.timestamp" placement="top">
                    <div class="trace-title">{{ t.content }} <span class="tool-chip">{{ t.tool }}</span></div>
                  </el-timeline-item>
                </el-timeline>
                <el-empty v-else description="暂无轨迹" :image-size="60" />
              </el-card>
            </el-col>

            <el-col :span="14">
              <el-card shadow="never" class="inner-card">
                <template #header><span class="card-title">产物</span></template>
                <el-tabs v-model="activeTab">
                  <el-tab-pane label="测试点" name="points">
                    <el-table :data="artifactsByKind('test_points')" border stripe size="small" max-height="420">
                      <el-table-column prop="id" label="#" width="50" />
                      <el-table-column prop="api" label="接口" min-width="160" />
                      <el-table-column prop="point" label="测试点" min-width="220" />
                      <el-table-column prop="type" label="类型" width="70">
                        <template #default="{ row }">
                          <el-tag :type="row.type === '正常' ? 'success' : row.type === '边界' ? 'primary' : 'info'" size="small">{{ row.type }}</el-tag>
                        </template>
                      </el-table-column>
                      <el-table-column prop="priority" label="优先级" width="80" />
                    </el-table>
                  </el-tab-pane>
                  <el-tab-pane label="用例集" name="cases">
                    <div v-if="detail.status === 'awaiting_review'" class="review-bar">
                      <div>
                        <div class="rb-t">用例集 v{{ latestCasesVersion }} 待人工确认</div>
                        <div class="rb-d">可编辑参数与断言后确认执行；驳回将回到用例生成 Agent 重做</div>
                      </div>
                      <div>
                        <el-button type="primary" size="small" :loading="acting" @click="handleConfirm">确认并执行</el-button>
                        <el-button type="danger" size="small" :loading="acting" @click="handleReject">驳回重生成</el-button>
                      </div>
                    </div>
                    <el-table :data="artifactsByKind('cases')" border stripe size="small" max-height="420">
                      <el-table-column prop="id" label="#" width="50" />
                      <el-table-column prop="name" label="用例名称" min-width="150" />
                      <el-table-column prop="method" label="方法" width="80" />
                      <el-table-column prop="path" label="路径" min-width="160" />
                      <el-table-column prop="asserts" label="断言" min-width="180" />
                    </el-table>
                  </el-tab-pane>
                  <el-tab-pane label="执行结果" name="results">
                    <div v-if="resultsArtifact">
                      <el-result icon="success" title="执行完成" :sub-title="`通过 ${resultsContent.passed} / ${resultsContent.total}`" />
                      <el-table :data="resultsContent.failures || []" border stripe size="small">
                        <el-table-column prop="case" label="失败用例" min-width="170" />
                        <el-table-column prop="path" label="路径" min-width="150" />
                        <el-table-column prop="type" label="归类" width="110">
                          <template #default="{ row }">
                            <el-tag :type="row.type === '断言失败' ? 'danger' : 'warning'" size="small">{{ row.type }}</el-tag>
                          </template>
                        </el-table-column>
                        <el-table-column prop="reason" label="原因分析" min-width="220" />
                      </el-table>
                    </div>
                    <el-empty v-else description="尚未执行，用例集确认后由执行 Agent 运行" :image-size="80" />
                  </el-tab-pane>
                  <el-tab-pane label="质量报告" name="report">
                    <div v-if="reportArtifact">
                      <el-result icon="success" title="评审完成" :sub-title="`通过率 ${reportContent.pass_rate}%`" />
                      <el-alert v-for="(s, i) in reportContent.suggestions || []" :key="i" :title="s" type="warning" show-icon
                                :closable="false" style="margin-bottom: 10px" />
                    </div>
                    <el-empty v-else description="评审 Agent 尚未运行" :image-size="80" />
                  </el-tab-pane>
                </el-tabs>
              </el-card>
            </el-col>
          </el-row>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts" name="agentTasks">
import { reactive, ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useAgentTaskApi } from '/@/api/v1/ai/agentTasks';
import { useProjectApi } from '/@/api/v1/projects/project';
import { apiAutomationApi } from '/@/api/v1/testing/apiAutomation';
import { useLLMConfigApi } from '/@/api/v1/ai/llmConfig';
import { formatDateTime } from '/@/utils/formatTime';

const api = useAgentTaskApi();

// ── 列表 ──
const queryForm = reactive({ keyword: '', status: '', page: 1, page_size: 20 });
const tableData = ref<any[]>([]);
const total = ref(0);
const loading = ref(false);

const loadList = async () => {
  loading.value = true;
  try {
    const res: any = await api.getTaskList({
      keyword: queryForm.keyword || undefined,
      status: queryForm.status || undefined,
      page: queryForm.page,
      page_size: queryForm.page_size,
    });
    if (res.code === 200) {
      tableData.value = res.data.items;
      total.value = res.data.total;
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '加载任务列表失败');
  } finally {
    loading.value = false;
    syncListPolling();
  }
};

/* 列表自动轮询：存在进行中/待确认任务时每 5 秒刷新一次状态 */
let listPollTimer: any = null;
const syncListPolling = () => {
  const hasRunning = tableData.value.some((r: any) => RUNNING_STATES.includes(r.status));
  if (hasRunning && !listPollTimer) {
    listPollTimer = setInterval(loadList, 5000);
  } else if (!hasRunning && listPollTimer) {
    clearInterval(listPollTimer);
    listPollTimer = null;
  }
};
const stopListPolling = () => {
  if (listPollTimer) { clearInterval(listPollTimer); listPollTimer = null; }
};

const handleQuery = () => { queryForm.page = 1; loadList(); };
const handleReset = () => { queryForm.keyword = ''; queryForm.status = ''; queryForm.page = 1; loadList(); };

const statusLabel = (s: string) => {
  const map: any = { analyzing: '需求分析', case_generating: '用例生成', executing: '执行中', reviewing: '评审中', awaiting_review: '待确认' };
  return map[s] || s;
};

// ── 创建 ──
const createVisible = ref(false);
const creating = ref(false);
const createFormRef = ref();
/* 用例生成配置：类型分组（参照 AI 生成单接口用例） */
const caseTypeGroups = [
  { key: 'positive', label: '正向', options: [
    { value: 'required_fields', label: '仅传必要字段' },
    { value: 'semantic_valid', label: '语义合法' },
    { value: 'enum_combo', label: '覆盖枚举组合' },
    { value: 'other_positive', label: '其他正向' },
  ]},
  { key: 'negative', label: '负向', options: [
    { value: 'invalid_value', label: '无效值' },
    { value: 'missing_required', label: '缺失必填字段' },
    { value: 'format_error', label: '格式错误' },
    { value: 'type_error', label: '类型错误' },
    { value: 'semantic_invalid', label: '语义非法' },
    { value: 'other_negative', label: '其他负向' },
  ]},
  { key: 'boundary', label: '边界值', options: [
    { value: 'extreme_max_min', label: '极大值/极小值' },
    { value: 'beyond_boundary', label: '超出边界' },
    { value: 'null_zero_empty', label: 'Null/零值/空值' },
    { value: 'string_length', label: '字符串过长/过短' },
  ]},
  { key: 'security', label: '安全性', options: [
    { value: 'auth_control', label: '鉴权控制' },
    { value: 'sql_injection', label: 'SQL注入' },
    { value: 'fuzz_input', label: '模糊输入' },
    { value: 'xss_injection', label: 'XSS注入' },
    { value: 'command_injection', label: '命令行注入' },
    { value: 'json_injection', label: 'JSON注入' },
    { value: 'nosql_injection', label: 'NoSQL注入' },
  ]},
];

const caseConfig = reactive({
  types: {
    positive: ['required_fields', 'semantic_valid', 'enum_combo', 'other_positive'],
    negative: ['invalid_value', 'missing_required', 'format_error', 'type_error', 'semantic_invalid', 'other_negative'],
    boundary: ['extreme_max_min', 'beyond_boundary', 'null_zero_empty', 'string_length'],
    security: ['auth_control', 'sql_injection', 'fuzz_input', 'xss_injection', 'command_injection', 'json_injection', 'nosql_injection'],
  },
  extra_requirements: '',
  step_generation: true,
  auto_complete: false,
  supplement_rounds: 1,
  deduplicate: true,
  case_count: 'auto' as string | number,
  language: 'zh-CN',
});

const isGroupAll = (key: string) => {
  const g = caseTypeGroups.find((x: any) => x.key === key)!;
  return caseConfig.types[key].length === g.options.length;
};
const isGroupPartial = (key: string) => {
  const g = caseTypeGroups.find((x: any) => x.key === key)!;
  return caseConfig.types[key].length > 0 && caseConfig.types[key].length < g.options.length;
};
const toggleGroup = (key: string, checked: boolean | string | number) => {
  const g = caseTypeGroups.find((x: any) => x.key === key)!;
  caseConfig.types[key] = checked ? g.options.map((o: any) => o.value) : [];
};

const createForm = reactive({
  name: '', pipeline_type: 'api', project_id: null as number | null,
  api_service_id: null as number | null, env_name: '',
  exec_mode: 'manual', model_tier: '',
});
const createRules = {
  name: [{ required: true, message: '请输入任务名称', trigger: 'blur' }],
};

const projectApi = useProjectApi();
const projectOptions = ref<any[]>([]);
const envOptions = ref<any[]>([]);

const loadApiEnvs = async () => {
  envOptions.value = [];
  createForm.env_name = '';
  try {
    const res: any = await apiAutomationApi.api_env({});
    if (res.code === 200) {
      const list = Array.isArray(res.data) ? res.data : [];
      envOptions.value = list;
      const def = list[0];
      if (def) createForm.env_name = def.name;
    }
  } catch (e) { /* 环境加载失败不影响创建 */ }
};

const llmOptions = ref<any[]>([]);
const loadLLMConfigs = async () => {
  try {
    const res: any = await useLLMConfigApi().getList({});
    if (res.code === 200) {
      const list = Array.isArray(res.data) ? res.data : (res.data?.items || []);
      llmOptions.value = list.filter((m: any) => m.is_active !== false);
      const def = list.find((m: any) => m.is_default) || list[0];
      if (def && !createForm.model_tier) createForm.model_tier = def.config_name;
    }
  } catch (e) { /* 模型配置加载失败不影响创建 */ }
};

const serviceOptions = ref<any[]>([]);
const loadServices = async (projectId?: number | null) => {
  try {
    const res: any = await apiAutomationApi.api_service_list({ project_id: projectId ?? undefined });
    if (res.code === 200) {
      serviceOptions.value = Array.isArray(res.data) ? res.data : [];
      if (serviceOptions.value.length && !createForm.api_service_id) {
        createForm.api_service_id = serviceOptions.value[0].id;
        const svc = serviceOptions.value[0];
        if (svc.name) createForm.input_file = `接口服务: ${svc.name}`;
      }
    }
  } catch (e) { /* 服务加载失败不影响创建 */ }
};

const handleServiceChange = (sid: number) => {
  const svc = serviceOptions.value.find((s: any) => s.id === sid);
  createForm.input_file = svc ? `接口服务: ${svc.name}` : '';
};

const loadProjects = async () => {
  try {
    const res: any = await projectApi.getList({ page: 1, page_size: 100 });
    if (res.code === 200) {
      projectOptions.value = res.data.items || [];
      const active = projectOptions.value.find((p: any) => p.status === 'active') || projectOptions.value[0];
      if (active) {
        createForm.project_id = active.id;
        loadServices(active.id);
      }
      loadApiEnvs();
    }
  } catch (e) { /* 项目加载失败不影响其他功能 */ }
};

const handleProjectChange = (pid: number) => { loadEnvs(pid); };

const openCreate = () => {
  createVisible.value = true;
  if (!projectOptions.value.length) loadProjects();
  if (!llmOptions.value.length) loadLLMConfigs();
};
const submitCreate = async () => {
  await createFormRef.value.validate();
  creating.value = true;
  try {
    const res: any = await api.createTask({
      ...createForm,
      case_config: { ...caseConfig },
    });
    if (res.code === 200) {
      ElMessage.success('任务创建成功，流水线已启动');
      createVisible.value = false;
      createForm.name = '';
      createForm.api_service_id = null;
      createForm.input_file = '';
      loadList();
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '创建失败');
  } finally {
    creating.value = false;
  }
};

// ── 详情 ──
const detailVisible = ref(false);
const detailLoading = ref(false);
const detailError = ref('');
const detail = ref<any>(null);
const currentDetailId = ref(0);
const activeTab = ref('points');
const acting = ref(false);
let pollTimer: any = null;

const detailTitle = computed(() => (detail.value ? `${detail.value.name} · 任务详情` : '任务详情'));

const pipelineNodes = [
  { key: 'analyzing', label: '需求分析 Agent', icon: 'ele-Document' },
  { key: 'case_generating', label: '用例生成 Agent', icon: 'ele-List' },
  { key: 'awaiting_review', label: '人工审核点（HITL）', icon: 'ele-AlarmClock' },
  { key: 'executing', label: '执行 Agent', icon: 'ele-Monitor' },
  { key: 'reviewing', label: '评审 Agent', icon: 'ele-CircleCheck' },
];

const NODE_ORDER: any = { analyzing: 0, case_generating: 1, awaiting_review: 2, executing: 3, reviewing: 4, done: 4, failed: 4 };

const nodeState = (key: string) => {
  if (!detail.value) return 'pending';
  const cur = NODE_ORDER[detail.value.status] ?? -1;
  const idx = NODE_ORDER[key];
  if (detail.value.status === 'failed') return idx < cur ? 'done' : 'failed';
  if (detail.value.status === 'done') return 'done';
  if (idx < cur) return 'done';
  if (idx === cur && key === detail.value.status) return 'running';
  return 'pending';
};
const nodeStateClass = (key: string) => {
  const s = nodeState(key);
  return s === 'done' ? 'done' : s === 'running' ? 'running' : s === 'failed' ? 'failed' : '';
};
const nodeTagType = (key: string) => {
  const s = nodeState(key);
  return s === 'done' ? 'success' : s === 'running' ? 'primary' : s === 'failed' ? 'danger' : 'info';
};
const nodeTagText = (key: string) => {
  const s = nodeState(key);
  return s === 'done' ? '完成' : s === 'running' ? '运行中' : s === 'failed' ? '失败' : '待执行';
};
const nodeMeta = (key: string) => {
  if (!detail.value) return '';
  const points = artifactsByKind('test_points').length;
  const cases = artifactsByKind('cases').length;
  const metaMap: any = {
    analyzing: points ? `测试点 ${points} 条 · 耗时 01:24 · token 8.2K` : `耗时 01:24 · token 8.2K`,
    case_generating: cases ? `用例 ${cases} 条 · 耗时 03:17` : `耗时 03:17`,
    awaiting_review: detail.value.status === 'awaiting_review' ? '等待测试人员确认用例集' : '审核通过，进入执行',
    executing: cases ? `调用接口执行引擎运行 ${cases} 条用例` : '调用接口执行引擎运行用例',
    reviewing: '失败归类、根因分析、质量报告',
  };
  return metaMap[key] || '';
};

const traceList = computed(() => (detail.value?.trace || []).map((t: any) => ({
  ...t,
  type: t.tool === 'done' || t.tool === 'artifact' ? 'success' : 'primary',
})));

const artifactsByKind = (kind: string) => {
  const art = (detail.value?.artifacts || []).find((a: any) => a.kind === kind);
  if (!art) return [];
  if (kind === 'test_points') return art.content || [];
  if (kind === 'cases') return art.content || [];
  return [art];
};
const latestCasesVersion = computed(() => {
  const arts = (detail.value?.artifacts || []).filter((a: any) => a.kind === 'cases');
  return arts.length ? arts[arts.length - 1].version : 1;
});
const resultsArtifact = computed(() => (detail.value?.artifacts || []).find((a: any) => a.kind === 'results'));
const resultsContent = computed(() => resultsArtifact.value?.content || { total: 0, passed: 0, failures: [] });
const reportArtifact = computed(() => (detail.value?.artifacts || []).find((a: any) => a.kind === 'report'));
const reportContent = computed(() => reportArtifact.value?.content || { pass_rate: 0, suggestions: [] });
const pointCount = computed(() => artifactsByKind('test_points').length || 0);
const caseCount = computed(() => artifactsByKind('cases').length || 0);

const loadDetail = async (id: number) => {
  if (!id) return;
  detailLoading.value = true;
  detailError.value = '';
  try {
    const res: any = await api.getTaskDetail(id);
    if (res.code === 200) {
      detail.value = res.data;
      startPolling(id);
    }
  } catch (e: any) {
    detailError.value = e?.message || '加载失败';
  } finally {
    detailLoading.value = false;
  }
};

const openDetail = (row: any) => {
  currentDetailId.value = row.id;
  detailVisible.value = true;
  detail.value = null;
  nextTick(() => loadDetail(row.id));
};

const startPolling = (id: number) => {
  stopPolling();
  pollTimer = setInterval(async () => {
    try {
      const res: any = await api.getTaskDetail(id);
      if (res.code === 200) {
        detail.value = res.data;
        if (['done', 'failed'].includes(res.data.status)) stopPolling();
      }
    } catch (e) { /* 静默，下次再试 */ }
  }, 3000);
};
const stopPolling = () => {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
};

// ── HITL / 重跑 / 删除 ──
const handleConfirm = async () => {
  acting.value = true;
  try {
    const res: any = await api.confirmTask(currentDetailId.value);
    if (res.code === 200) { ElMessage.success('已确认，执行 Agent 开始运行'); loadDetail(currentDetailId.value); loadList(); }
  } catch (e: any) { ElMessage.error(e?.message || '操作失败'); } finally { acting.value = false; }
};
const handleReject = async () => {
  acting.value = true;
  try {
    const res: any = await api.rejectTask(currentDetailId.value);
    if (res.code === 200) { ElMessage.success('已驳回，用例生成 Agent 重新生成'); loadDetail(currentDetailId.value); loadList(); }
  } catch (e: any) { ElMessage.error(e?.message || '操作失败'); } finally { acting.value = false; }
};
const handleRerun = async (row: any) => {
  await ElMessageBox.confirm(`确认重跑任务「${row.name}」？`, '重跑确认', { type: 'warning' });
  try {
    const res: any = await api.rerunTask(row.id);
    if (res.code === 200) { ElMessage.success('任务已重新启动'); loadList(); }
  } catch (e: any) { ElMessage.error(e?.message || '重跑失败'); }
};
const handleDelete = async (row: any) => {
  await ElMessageBox.confirm(`确认删除任务「${row.name}」？`, '删除确认', { type: 'warning' });
  try {
    const res: any = await api.deleteTask(row.id);
    if (res.code === 200) { ElMessage.success('删除成功'); loadList(); }
  } catch (e: any) { ElMessage.error(e?.message || '删除失败'); }
};

onMounted(() => { loadList(); loadProjects(); loadLLMConfigs(); });
onBeforeUnmount(() => { stopPolling(); stopListPolling(); });
</script>

<style scoped lang="scss">
.agent-tasks-page {
  padding: 20px;

  .search-card { margin-bottom: 20px; }
  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .mono { font-family: Consolas, 'Courier New', monospace; font-size: 12.5px; }
  .cell-sub { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 2px; }
  .task-link { font-weight: 500; }
  .running-dot {
    display: inline-block; width: 6px; height: 6px; border-radius: 50%;
    background: currentColor; margin-right: 5px; animation: pulse 1.2s ease infinite;
  }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .25; } }
  .pagination { margin-top: 16px; justify-content: flex-end; }
  .form-tip { font-size: 12px; color: var(--el-text-color-secondary); width: 100%; }

  .detail-body { min-height: 200px; }
  .stat-row { margin-bottom: 16px; }
  .info-desc { margin-bottom: 4px; }
  .inner-card {
    border: 1px solid var(--el-border-color-lighter);
    .card-title { font-size: 14px; font-weight: 600; }
  }
  .pipeline {
    .pnode {
      display: flex; gap: 12px; padding: 12px 14px; border: 1px solid var(--el-border-color-lighter);
      border-radius: 8px; margin-bottom: 12px; position: relative;
      &::after {
        content: ''; position: absolute; left: 27px; top: calc(100% - 2px);
        width: 2px; height: 12px; background: var(--el-border-color-lighter);
      }
      &:last-child::after { display: none; }
      &.done::after { background: var(--el-color-success); }
      &.done .pnode-icon { color: var(--el-color-success); background: #f0f9eb; }
      &.running .pnode-icon { color: var(--el-color-primary); background: var(--el-color-primary-light-9); }
      &.failed .pnode-icon { color: var(--el-color-danger); background: #fef0f0; }
      .pnode-icon {
        width: 34px; height: 34px; border-radius: 8px; background: var(--el-fill-color-lighter);
        color: var(--el-text-color-secondary); display: flex; align-items: center; justify-content: center;
        flex-shrink: 0; font-size: 17px;
      }
      .pnode-body { flex: 1; min-width: 0; }
      .pnode-top { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
      .pnode-name { font-size: 14px; font-weight: 600; }
      .pnode-meta { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 3px; }
    }
  }
  .trace-title { font-size: 13px; font-weight: 500; }
  .tool-chip {
    font-family: Consolas, monospace; font-size: 11px; background: var(--el-fill-color-lighter);
    color: var(--el-text-color-secondary); padding: 1px 7px; border-radius: 3px; margin-left: 6px;
  }
  .case-type-wrap { width: 100%; display: flex; flex-direction: column; gap: 10px; }
  .type-group {
    border: 1px solid var(--el-border-color-lighter); border-radius: 8px; padding: 10px 12px;
    background: var(--el-bg-color);
  }
  .type-group-head { margin-bottom: 6px; }
  .type-items { display: flex; flex-wrap: wrap; gap: 2px 14px; }
  .adv-settings { width: 100%; display: flex; flex-direction: column; gap: 10px; }
  .adv-row { display: flex; align-items: center; gap: 10px; font-size: 14px; color: var(--el-text-color-regular); }
  .adv-label { width: 70px; color: var(--el-text-color-secondary); flex-shrink: 0; }
  .adv-text { display: flex; flex-direction: column; }
  .adv-hint { font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.5; }
  .review-bar {
    display: flex; align-items: center; justify-content: space-between; gap: 12px;
    padding: 12px 16px; background: #fdf6ec; border: 1px solid #faecd8; border-radius: 8px; margin-bottom: 14px;
    flex-wrap: wrap;
    .rb-t { font-size: 13.5px; font-weight: 600; color: #b88230; }
    .rb-d { font-size: 12.5px; color: #a9833f; margin-top: 2px; }
  }
}
</style>
