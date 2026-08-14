<template>
  <div class="op-panel">
    <!-- 操作卡片列表（可滚动） -->
    <div class="op-list">
      <div v-if="!items.length && !hideEmpty" class="op-empty">
        <el-icon size="32" color="#c0c4cc"><DocumentAdd /></el-icon>
        <p>暂无{{ panelLabel }}，点击下方按钮添加</p>
      </div>

      <div
        v-for="(item, index) in items"
        :key="index"
        class="op-card"
        :class="`op-card--${typeColor(item.type)}`"
      >
        <!-- 卡片头部：点击标题区折叠/展开 -->
        <div class="op-card__header" @click="toggleCollapse(index)">
          <div class="op-card__title">
            <span class="op-card__badge" :class="`badge--${typeColor(item.type)}`">
              {{ index + 1 }}
            </span>
            <el-icon class="op-card__icon"><component :is="typeIcon(item.type)" /></el-icon>
            <span class="op-card__type-label">{{ typeLabel(item.type) }}</span>
            <span class="op-card__summary">{{ itemSummary(item) }}</span>
          </div>
          <div class="op-card__actions" @click.stop>
            <el-icon
              class="op-card__collapse-icon"
              :class="{ 'is-collapsed': collapsed[index] }"
            >
              <ArrowDown />
            </el-icon>
            <el-button
              type="danger"
              link
              size="small"
              @click="items.splice(index, 1)"
            >
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
        </div>

        <!-- 卡片内容（折叠控制） -->
        <div v-show="!collapsed[index]" class="op-card__body">

          <!-- ===== BEFORE ===== -->
          <template v-if="mode === 'before'">
            <!-- type 1: 预请求接口 -->
            <template v-if="item.type === 1">
              <div class="op-row">
                <label class="op-label">名称</label>
                <el-input v-model="item.title" placeholder="操作名称" size="small" style="flex:1" />
              </div>
              <div class="op-row">
                <label class="op-label">环境</label>
                <el-select v-model="item.env_id" placeholder="选择环境" size="small" style="width:200px">
                  <el-option v-for="e in envList" :key="e.id" :label="e.name" :value="e.id" />
                </el-select>
              </div>
              <div class="op-row">
                <label class="op-label">接口</label>
                <el-cascader
                  v-model="item.api_id"
                  :options="treeList"
                  :props="{ value: 'id', label: 'name', children: 'children' }"
                  placeholder="选择接口"
                  filterable
                  size="small"
                  style="flex:1"
                />
              </div>
            </template>

            <!-- type 2: 预设变量 -->
            <template v-else-if="item.type === 2">
              <div class="op-row">
                <label class="op-label">变量名</label>
                <el-input v-model="item.name" placeholder="变量名" size="small" style="width:180px" />
                <label class="op-label" style="margin-left:12px">类型</label>
                <el-select v-model="item.env_type" size="small" style="width:130px">
                  <el-option v-for="t in valTypeList" :key="t.value" :label="t.name" :value="t.value" />
                </el-select>
                <label class="op-label" style="margin-left:12px">值</label>
                <el-input v-model="item.value" placeholder="变量值" size="small" style="flex:1" />
              </div>
            </template>

            <!-- type 3: 等待时长 -->
            <template v-else-if="item.type === 3">
              <div class="op-row">
                <label class="op-label">等待时间</label>
                <el-input-number v-model="item.wait_time" :min="0" :max="300" size="small" style="width:160px" />
                <span class="op-unit">秒</span>
              </div>
            </template>

            <!-- type 4: 自定义脚本 -->
            <template v-else-if="item.type === 4">
              <div class="op-code-wrap">
                <div class="op-code-toolbar">
                  <el-select :model-value="item.language || 'python'" size="small" style="width:120px" @update:model-value="(v: string) => item.language = v">
                    <el-option label="Python" value="python" />
                    <el-option label="JavaScript" value="javascript" />
                  </el-select>

                  <el-radio-group v-if="(item.language || 'python') !== 'javascript'" :model-value="item.exec_mode || 'sandbox'" size="small" style="margin-left:8px" @update:model-value="(v: string) => item.exec_mode = v">
                    <el-radio-button value="sandbox">沙盒</el-radio-button>
                    <el-radio-button value="native">原生</el-radio-button>
                  </el-radio-group>
                  <el-tag v-else size="small" type="warning" effect="plain" style="margin-left:8px">JS 仅原生(Node)</el-tag>
                  <span class="op-code-hint">可用 ntest / pm / request{{ (item.language || 'python') === 'javascript' ? '（需本机 Node）' : '' }}</span>
                </div>
                <textarea
                  :value="item.code_map ? (item.code_map[item.language] ?? '') : (item.code || '')" @input="(e: any) => { const v = e.target ? e.target.value : e; if (!item.code_map) item.code_map = {}; item.code_map[item.language] = v; item.code = v }"
                  class="op-code-editor"
                  :placeholder="(item.language || 'python') === 'javascript' ? '// JavaScript：pm.environment.set / ntest.set / request' : '# Python：ntest.set / pm.environment.set / request'"
                  spellcheck="false"
                />
                <div class="op-code-validate">
                  <el-button type="primary" link size="small" :loading="vs(item)?.validating" @click="validateOpScript(item)">
                    <el-icon style="margin-right:2px"><ele-CircleCheck /></el-icon>AI 校验
                  </el-button>
                  <div v-if="vs(item)?.result" class="op-cv-panel" :class="vs(item)?.result.passed ? 'ok' : 'fail'">
                    <el-tag :type="vs(item)?.result.passed ? 'success' : 'danger'" size="small">
                      {{ vs(item)?.result.passed ? '校验通过' : '校验未通过' }}
                    </el-tag>
                    <div v-if="vs(item)?.result.syntax_ok === false" class="op-cv-line">{{ vs(item)?.result.syntax_error }}</div>
                    <div v-for="(s, i) in vs(item)?.result.spec_issues || []" :key="'sp' + i" class="op-cv-line">• {{ s }}</div>
                    <div v-if="vs(item)?.result.run_ok === false" class="op-cv-line">试运行失败: {{ vs(item)?.result.run_error }}</div>
                    <div v-if="vs(item)?.result.ai_review && vs(item)?.result.ai_review.summary" class="op-cv-line ai">
                      AI: {{ vs(item)?.result.ai_review.summary }}
                    </div>
                    <div v-for="(s, i) in (vs(item)?.result.ai_review && vs(item)?.result.ai_review.suggestions) || []" :key="'sg' + i" class="op-cv-line ai">💡 {{ s }}</div>
                  </div>
                </div>
              </div>
            </template>

            <!-- type 5: 数据库操作 -->
            <template v-else-if="item.type === 5">
              <div class="op-row">
                <label class="op-label">数据库</label>
                <el-select
                  v-model="item.db_id"
                  placeholder="选择数据库"
                  size="small"
                  style="width:220px"
                  @visible-change="(open: boolean) => { if (open) emit('refresh-dbs') }"
                  @change="(v: any) => { const db = dbList?.find((d: any) => d.id === v); item.db_name = db?.name || '' }"
                >
                  <el-option v-for="db in dbList" :key="db.id" :label="db.name" :value="db.id" />
                </el-select>
                <label class="op-label" style="margin-left:12px">结果存入</label>
                <el-input v-model="item.result_var" placeholder="变量名（可选）" size="small" style="width:160px" />
              </div>
              <div class="op-row op-row--full">
                <label class="op-label">SQL</label>
                <el-input
                  v-model="item.sql"
                  type="textarea"
                  :rows="3"
                  placeholder="SELECT * FROM table"
                  size="small"
                  style="flex:1;font-family:monospace;font-size:12px"
                />
              </div>
            </template>

            <!-- type 6: 脚本库 -->
            <template v-else-if="item.type === 6">
              <div class="op-row">
                <label class="op-label">脚本</label>
                <el-select
                  v-model="item.func_id"
                  placeholder="选择脚本"
                  filterable
                  size="small"
                  style="width:260px"
                  @visible-change="(open: boolean) => { if (open) emit('refresh-scripts') }"
                  @change="(v: any) => { const fn = scriptList?.find((f: any) => f.id === v); item.func_name = fn?.name || '' }"
                >
                  <el-option v-for="fn in scriptList" :key="fn.id" :label="fn.name" :value="fn.id" />
                </el-select>
                <label class="op-label" style="margin-left:12px">结果存入</label>
                <el-input v-model="item.result_var" placeholder="变量名（可选）" size="small" style="width:140px" />
              </div>
              <div class="op-row">
                <label class="op-label">参数</label>
                <el-input v-model="item.func_params" placeholder='{"key":"value"}' size="small" style="flex:1;font-family:monospace" />
              </div>
              <div class="op-row">
                <label class="op-label">执行模式</label>
                <el-radio-group :model-value="item.exec_mode || 'sandbox'" size="small" @update:model-value="(v: string) => item.exec_mode = v">
                  <el-radio-button value="sandbox">沙盒</el-radio-button>
                  <el-radio-button value="native">原生</el-radio-button>
                </el-radio-group>
                <span style="font-size:11px;color:var(--el-text-color-placeholder)">脚本库自身模式可被此处覆盖</span>
              </div>
            </template>
          </template>

          <!-- ===== AFTER ===== -->
          <template v-else-if="mode === 'after'">
            <!-- type 1: 提取变量 -->
            <template v-if="item.type === 1">
              <div class="op-row">
                <label class="op-label">提取目标</label>
                <el-select v-model="item.res_type" size="small" style="width:160px">
                  <el-option v-for="r in resTypeList" :key="r.value" :label="r.name" :value="r.value" />
                </el-select>
                <label class="op-label" style="margin-left:12px">路径</label>
                <el-input v-model="item.name" placeholder="如 $.data.token" size="small" style="flex:1;font-family:monospace" />
              </div>
              <div class="op-row">
                <label class="op-label">变量类型</label>
                <el-select v-model="item.env_type" size="small" style="width:160px">
                  <el-option v-for="t in valTypeList" :key="t.value" :label="t.name" :value="t.value" />
                </el-select>
                <label class="op-label" style="margin-left:12px">变量名</label>
                <el-input v-model="item.value" placeholder="存入变量名" size="small" style="flex:1" />
              </div>
            </template>

            <!-- type 2: 等待时长 -->
            <template v-else-if="item.type === 2">
              <div class="op-row">
                <label class="op-label">等待时间</label>
                <el-input-number v-model="item.wait_time" :min="0" :max="300" size="small" style="width:160px" />
                <span class="op-unit">秒</span>
              </div>
            </template>

    <!-- type 3: 断言 -->
            <template v-else-if="item.type === 3">
              <div class="op-row">
                <label class="op-label">名称</label>
                <el-input v-model="item.assert_name" placeholder="断言名称（可选）" size="small" style="width:200px" />
              </div>
              <AssertEditor :rules="item.rules = item.rules || []" />
            </template>

            <!-- type 4: 数据库操作 -->
            <template v-else-if="item.type === 4">
              <div class="op-row">
                <label class="op-label">数据库</label>
                <el-select
                  v-model="item.db_id"
                  placeholder="选择数据库"
                  size="small"
                  style="width:220px"
                  @visible-change="(open: boolean) => { if (open) emit('refresh-dbs') }"
                  @change="(v: any) => { const db = dbList?.find((d: any) => d.id === v); item.db_name = db?.name || '' }"
                >
                  <el-option v-for="db in dbList" :key="db.id" :label="db.name" :value="db.id" />
                </el-select>
                <label class="op-label" style="margin-left:12px">结果存入</label>
                <el-input v-model="item.result_var" placeholder="变量名（可选）" size="small" style="width:160px" />
              </div>
              <div class="op-row op-row--full">
                <label class="op-label">SQL</label>
                <el-input
                  v-model="item.sql"
                  type="textarea"
                  :rows="3"
                  placeholder="SELECT * FROM table"
                  size="small"
                  style="flex:1;font-family:monospace;font-size:12px"
                />
              </div>
            </template>

            <!-- type 5: 自定义脚本 -->
            <template v-else-if="item.type === 5">
              <div class="op-code-wrap">
                <div class="op-code-toolbar">
                  <el-select :model-value="item.language || 'python'" size="small" style="width:120px" @update:model-value="(v: string) => item.language = v">
                    <el-option label="Python" value="python" />
                    <el-option label="JavaScript" value="javascript" />
                  </el-select>

                  <el-radio-group v-if="(item.language || 'python') !== 'javascript'" :model-value="item.exec_mode || 'sandbox'" size="small" style="margin-left:8px" @update:model-value="(v: string) => item.exec_mode = v">
                    <el-radio-button value="sandbox">沙盒</el-radio-button>
                    <el-radio-button value="native">原生</el-radio-button>
                  </el-radio-group>
                  <el-tag v-else size="small" type="warning" effect="plain" style="margin-left:8px">JS 仅原生(Node)</el-tag>
                  <span class="op-code-hint">可用 ntest / pm / request / response{{ (item.language || 'python') === 'javascript' ? '（需本机 Node）' : '' }}</span>
                </div>
                <textarea
                  :value="item.code_map ? (item.code_map[item.language] ?? '') : (item.code || '')" @input="(e: any) => { const v = e.target ? e.target.value : e; if (!item.code_map) item.code_map = {}; item.code_map[item.language] = v; item.code = v }"
                  class="op-code-editor"
                  :placeholder="(item.language || 'python') === 'javascript' ? '// JavaScript：pm.response.json() / ntest.set' : '# Python：pm.response.json() / ntest.set'"
                  spellcheck="false"
                />
                <div class="op-code-validate">
                  <el-button type="primary" link size="small" :loading="vs(item)?.validating" @click="validateOpScript(item)">
                    <el-icon style="margin-right:2px"><ele-CircleCheck /></el-icon>AI 校验
                  </el-button>
                  <div v-if="vs(item)?.result" class="op-cv-panel" :class="vs(item)?.result.passed ? 'ok' : 'fail'">
                    <el-tag :type="vs(item)?.result.passed ? 'success' : 'danger'" size="small">
                      {{ vs(item)?.result.passed ? '校验通过' : '校验未通过' }}
                    </el-tag>
                    <div v-if="vs(item)?.result.syntax_ok === false" class="op-cv-line">{{ vs(item)?.result.syntax_error }}</div>
                    <div v-for="(s, i) in vs(item)?.result.spec_issues || []" :key="'sp' + i" class="op-cv-line">• {{ s }}</div>
                    <div v-if="vs(item)?.result.run_ok === false" class="op-cv-line">试运行失败: {{ vs(item)?.result.run_error }}</div>
                    <div v-if="vs(item)?.result.ai_review && vs(item)?.result.ai_review.summary" class="op-cv-line ai">
                      AI: {{ vs(item)?.result.ai_review.summary }}
                    </div>
                    <div v-for="(s, i) in (vs(item)?.result.ai_review && vs(item)?.result.ai_review.suggestions) || []" :key="'sg' + i" class="op-cv-line ai">💡 {{ s }}</div>
                  </div>
                </div>
              </div>
            </template>

            <!-- type 6: 脚本库 -->
            <template v-else-if="item.type === 6">
              <div class="op-row">
                <label class="op-label">脚本</label>
                <el-select
                  v-model="item.func_id"
                  placeholder="选择脚本"
                  filterable
                  size="small"
                  style="width:260px"
                  @visible-change="(open: boolean) => { if (open) emit('refresh-scripts') }"
                  @change="(v: any) => { const fn = scriptList?.find((f: any) => f.id === v); item.func_name = fn?.name || '' }"
                >
                  <el-option v-for="fn in scriptList" :key="fn.id" :label="fn.name" :value="fn.id" />
                </el-select>
                <label class="op-label" style="margin-left:12px">结果存入</label>
                <el-input v-model="item.result_var" placeholder="变量名（可选）" size="small" style="width:140px" />
              </div>
              <div class="op-row">
                <label class="op-label">参数</label>
                <el-input v-model="item.func_params" placeholder='{"key":"value"}' size="small" style="flex:1;font-family:monospace" />
              </div>
              <div class="op-row">
                <label class="op-label">执行模式</label>
                <el-radio-group :model-value="item.exec_mode || 'sandbox'" size="small" @update:model-value="(v: string) => item.exec_mode = v">
                  <el-radio-button value="sandbox">沙盒</el-radio-button>
                  <el-radio-button value="native">原生</el-radio-button>
                </el-radio-group>
                <span style="font-size:11px;color:var(--el-text-color-placeholder)">脚本库自身模式可被此处覆盖</span>
              </div>
            </template>

            <!-- type 7: 引入接口 -->
            <template v-else-if="item.type === 7">
              <div class="op-row">
                <label class="op-label">名称</label>
                <el-input v-model="item.import_title" placeholder="操作名称（可选）" size="small" style="width:200px" />
                <label class="op-label" style="margin-left:12px">环境</label>
                <el-select v-model="item.env_id" size="small" style="width:180px">
                  <el-option v-for="e in envList" :key="e.id" :label="e.name" :value="e.id" />
                </el-select>
              </div>
              <div class="op-row">
                <label class="op-label">接口</label>
                <el-cascader
                  v-model="item.api_id"
                  :options="treeList"
                  :props="{ value: 'id', label: 'name', children: 'children' }"
                  placeholder="选择接口"
                  filterable
                  size="small"
                  style="flex:1"
                />
              </div>
            </template>
          </template>

          <!-- ===== ASSERT ===== -->
          <template v-else-if="mode === 'assert'">
            <!-- type 1: 响应断言 -->
            <template v-if="item.type === 1">
              <div class="op-row">
                <label class="op-label">名称</label>
                <el-input v-model="item.assert_name" placeholder="断言名称（可选）" size="small" style="width:200px" />
              </div>
              <AssertEditor :rules="item.rules = item.rules || []" />
            </template>

            <!-- type 2: DB断言 -->
            <template v-else-if="item.type === 2">
              <div class="op-row">
                <label class="op-label">查询表</label>
                <el-input v-model="item.ops_db_table" placeholder="表名" size="small" style="width:200px" />
                <label class="op-label" style="margin-left:12px">条件</label>
                <el-input v-model="item.ops_db_where" placeholder="WHERE 条件" size="small" style="flex:1" />
              </div>
            </template>

            <!-- type 4: 直连DB断言 -->
            <template v-else-if="item.type === 4">
              <div class="op-row">
                <label class="op-label">数据库</label>
                <el-select
                  v-model="item.local_db"
                  size="small"
                  style="width:200px"
                  @visible-change="(open: boolean) => { if (open) emit('refresh-dbs') }"
                >
                  <el-option v-for="db in dbList" :key="db.id" :label="db.name" :value="db.id" />
                </el-select>
                <label class="op-label" style="margin-left:12px">查询表</label>
                <el-input v-model="item.local_db_table" placeholder="表名" size="small" style="width:160px" />
                <label class="op-label" style="margin-left:12px">条件</label>
                <el-input v-model="item.local_db_where" placeholder="WHERE 条件" size="small" style="flex:1" />
              </div>
              <div class="op-row op-row--full">
                <label class="op-label">断言字段</label>
                <div style="flex:1">
                  <div
                    v-for="(a, ai) in (item.local_db_assert || [])"
                    :key="ai"
                    style="display:flex;gap:8px;margin-bottom:6px;align-items:center"
                  >
                    <el-input v-model="a.field" placeholder="字段名" size="small" style="width:160px" />
                    <span style="color:#909399;font-size:12px">=</span>
                    <el-input v-model="a.value" placeholder="期望值" size="small" style="flex:1" />
                    <el-button type="danger" link size="small" @click="item.local_db_assert.splice(ai, 1)">
                      <el-icon><Delete /></el-icon>
                    </el-button>
                  </div>
                  <el-button
                    type="primary"
                    link
                    size="small"
                    @click="(item.local_db_assert = item.local_db_assert || []).push({ field: '', value: '' })"
                  >
                    + 添加字段
                  </el-button>
                </div>
              </div>
            </template>

            <!-- type 5: 自定义断言 -->
            <template v-else-if="item.type === 5">
              <div class="op-row">
                <label class="op-label">名称</label>
                <el-input v-model="item.custom_name" placeholder="断言名称（可选）" size="small" style="width:240px" />
              </div>
              <div class="op-code-wrap">
                <div class="op-code-toolbar">
                  <el-select :model-value="item.language || 'python'" size="small" style="width:120px" @update:model-value="(v: string) => item.language = v">
                    <el-option label="Python" value="python" />
                    <el-option label="JavaScript" value="javascript" />
                  </el-select>

                  <el-radio-group v-if="(item.language || 'python') !== 'javascript'" :model-value="item.exec_mode || 'sandbox'" size="small" style="margin-left:8px" @update:model-value="(v: string) => item.exec_mode = v">
                    <el-radio-button value="sandbox">沙盒</el-radio-button>
                    <el-radio-button value="native">原生</el-radio-button>
                  </el-radio-group>
                  <el-tag v-else size="small" type="warning" effect="plain" style="margin-left:8px">JS 仅原生(Node)</el-tag>
                  <span class="op-code-hint">可用 ntest / pm / request / response{{ (item.language || 'python') === 'javascript' ? '（需本机 Node）' : '' }}；失败请 throw / assert</span>
                </div>
                <textarea
                  :value="item.code_map ? (item.code_map[item.language] ?? '') : (item.custom_script || '')" @input="(e: any) => { const v = e.target ? e.target.value : e; if (!item.code_map) item.code_map = {}; item.code_map[item.language] = v; item.custom_script = v }"
                  class="op-code-editor"
                  :placeholder="(item.language || 'python') === 'javascript'
                    ? '// JavaScript：pm.response.json() / ntest.get'
                    : '# Python：assert / pm.response.json() / response / status_code'"
                  spellcheck="false"
                />
                <div class="op-code-validate">
                  <el-button type="primary" link size="small" :loading="vs(item)?.validating" @click="validateOpScript(item)">
                    <el-icon style="margin-right:2px"><ele-CircleCheck /></el-icon>AI 校验
                  </el-button>
                  <div v-if="vs(item)?.result" class="op-cv-panel" :class="vs(item)?.result.passed ? 'ok' : 'fail'">
                    <el-tag :type="vs(item)?.result.passed ? 'success' : 'danger'" size="small">
                      {{ vs(item)?.result.passed ? '校验通过' : '校验未通过' }}
                    </el-tag>
                    <div v-if="vs(item)?.result.syntax_ok === false" class="op-cv-line">{{ vs(item)?.result.syntax_error }}</div>
                    <div v-for="(s, i) in vs(item)?.result.spec_issues || []" :key="'sp' + i" class="op-cv-line">• {{ s }}</div>
                    <div v-if="vs(item)?.result.run_ok === false" class="op-cv-line">试运行失败: {{ vs(item)?.result.run_error }}</div>
                    <div v-if="vs(item)?.result.ai_review && vs(item)?.result.ai_review.summary" class="op-cv-line ai">
                      AI: {{ vs(item)?.result.ai_review.summary }}
                    </div>
                    <div v-for="(s, i) in (vs(item)?.result.ai_review && vs(item)?.result.ai_review.suggestions) || []" :key="'sg' + i" class="op-cv-line ai">💡 {{ s }}</div>
                  </div>
                </div>
              </div>
            </template>
          </template>

        </div>
      </div>
    </div>

    <!-- 底部添加栏 -->
    <div class="op-add-bar">
      <span class="op-add-label">添加：</span>
      <div class="op-add-types">
        <button
          v-for="t in availableTypes"
          :key="t.type"
          class="op-type-btn"
          :class="`op-type-btn--${t.color}`"
          @click="addItem(t.type)"
        >
          <el-icon style="margin-right:3px;vertical-align:middle"><component :is="t.icon" /></el-icon>
          {{ t.label }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, reactive, watch } from 'vue'
import {
  Delete,
  Connection,
  Operation,
  Clock,
  EditPen,
  Coin,
  Document,
  CircleCheck,
  DocumentAdd,
  ArrowDown,
  Rank,
} from '@element-plus/icons-vue'
import AssertEditor from './AssertEditor.vue'
import { useApiAutomationApi } from '/@/api/v1/testing/apiAutomation'

// ---- Props ----
const validateStates = reactive(new Map<any, any>())
const vs = (item: any) => validateStates.get(item)

const validateOpScript = async (item: any) => {
  const code = (item.code ?? item.custom_script) || ''
  if (!code.trim()) {
    validateStates.set(item, { validating: false, result: { passed: false, syntax_ok: false, syntax_error: '脚本内容为空', spec_issues: [], run_ok: null, ai_review: null } })
    return
  }
  validateStates.set(item, { validating: true })
  try {
    const res: any = await useApiAutomationApi().script_validate({ code, language: item.language || 'python', use_ai: true })
    validateStates.set(item, { validating: false, result: res.code === 200 ? res.data : { passed: false, syntax_ok: true, syntax_error: '', spec_issues: [res.message || '校验失败'], run_ok: null, ai_review: null } })
  } catch (e: any) {
    validateStates.set(item, { validating: false, result: { passed: false, syntax_ok: true, syntax_error: '', spec_issues: [e?.message || '校验接口调用失败'], run_ok: null, ai_review: null } })
  }
}

const props = withDefaults(defineProps<{
  items: any[]
  mode: 'before' | 'after' | 'assert'
  envList?: any[]
  treeList?: any[]
  dbList?: any[]
  scriptList?: any[]
  resTypeList?: any[]
  valTypeList?: any[]
  hideEmpty?: boolean
}>(), {
  envList: () => [],
  treeList: () => [],
  dbList: () => [],
  scriptList: () => [],
  resTypeList: () => [],
  valTypeList: () => [],
})

// ---- code_map 迁移：旧数据（code/custom_script）初始化到对应语言槽位，
//      切换语言时自动加载该语言历史代码，互不覆盖 ----
watch(() => props.items, (list) => {
  if (!Array.isArray(list)) return
  for (const item of list) {
    if (!item || typeof item !== 'object') continue
    const isScript = (props.mode === 'before' && item.type === 4) ||
                     (props.mode === 'after' && item.type === 5) ||
                     (props.mode === 'assert' && item.type === 5)
    if (!isScript) continue
    const lang = item.language || 'python'
    const src = item.code ?? item.custom_script ?? ''
    if (!item.code_map || typeof item.code_map !== 'object') {
      item.code_map = { [lang]: src }
    } else if (item.code_map[lang] === undefined && src) {
      item.code_map[lang] = src
    }
  }
}, { deep: true, immediate: true })


const emit = defineEmits<{
  (e: 'refresh-scripts'): void
  (e: 'refresh-dbs'): void
}>()

// ---- Collapse state ----
const collapsed = ref<Record<number, boolean>>({})

const toggleCollapse = (index: number) => {
  collapsed.value[index] = !collapsed.value[index]
}

// ---- Type metadata ----
type TypeMeta = { label: string; icon: any; color: string }

const TYPE_META: Record<string, TypeMeta> = {
  // before
  'before-1': { label: '引入接口', icon: Connection,   color: 'blue'   },
  'before-2': { label: '提取变量',   icon: Operation,    color: 'purple' },
  'before-3': { label: '等待时长',   icon: Clock,        color: 'gray'   },
  'before-4': { label: '自定义脚本', icon: EditPen,      color: 'orange' },
  'before-5': { label: '数据库操作', icon: Coin,         color: 'yellow' },
  'before-6': { label: '脚本库',     icon: Document,     color: 'teal'   },
  // after
  'after-1':  { label: '提取变量',   icon: Operation,    color: 'purple' },
  'after-2':  { label: '等待时长',   icon: Clock,        color: 'gray'   },
  'after-3':  { label: '断言',       icon: CircleCheck,  color: 'green'  },
  'after-4':  { label: '数据库操作', icon: Coin,         color: 'yellow' },
  'after-5':  { label: '自定义脚本', icon: EditPen,      color: 'orange' },
  'after-6':  { label: '脚本库',     icon: Document,     color: 'teal'   },
  'after-7':  { label: '引入接口',   icon: Connection,   color: 'blue'   },
  // assert
  'assert-1': { label: '响应断言',   icon: CircleCheck,  color: 'green'  },
  'assert-2': { label: 'DB断言',     icon: Coin,         color: 'yellow' },
  'assert-4': { label: '数据库断言', icon: Coin,         color: 'yellow' },
  'assert-5': { label: '自定义断言', icon: EditPen,      color: 'orange' },
}

const getMeta = (type: number): TypeMeta =>
  TYPE_META[`${props.mode}-${type}`] ?? { label: `类型${type}`, icon: Document, color: 'gray' }

const typeLabel = (type: number) => getMeta(type).label
const typeIcon  = (type: number) => getMeta(type).icon
const typeColor = (type: number) => getMeta(type).color

// ---- Panel label ----
const panelLabel = computed(() => {
  if (props.mode === 'before') return '前置操作'
  if (props.mode === 'after')  return '后置操作'
  return '断言'
})

// ---- Item summary ----
const itemSummary = (item: any): string => {
  if (props.mode === 'before') {
    if (item.type === 1) return item.title || ''
    if (item.type === 2) return item.name  || ''
    if (item.type === 3) return item.wait_time != null ? `${item.wait_time}s` : ''
    if (item.type === 5) return item.db_name  || ''
    if (item.type === 6) return item.func_name || ''
  }
  if (props.mode === 'after') {
    if (item.type === 1) return item.value || item.name || ''
    if (item.type === 2) return item.wait_time != null ? `${item.wait_time}s` : ''
    if (item.type === 3) return item.assert_name || ''
    if (item.type === 4) return item.db_name  || ''
    if (item.type === 6) return item.func_name || ''
    if (item.type === 7) return item.import_title || ''
  }
  if (props.mode === 'assert') {
    if (item.type === 1) return item.name  || ''
    if (item.type === 2) return item.ops_db_table || ''
    if (item.type === 4) return item.local_db_table || ''
    if (item.type === 5) return item.custom_name || ''
  }
  return ''
}

// ---- Available types for add bar ----
const AVAILABLE_TYPES: Record<string, number[]> = {
  before: [1, 2, 3, 4, 5, 6],
  after:  [1, 2, 3, 4, 5, 6, 7],
  assert: [1, 2, 4, 5],
}

const availableTypes = computed(() =>
  (AVAILABLE_TYPES[props.mode] ?? []).map((t) => ({ type: t, ...getMeta(t) }))
)

// ---- Default item factory ----
const defaultItem = (type: number): any => {
  const base = { type }
  if (props.mode === 'before') {
    if (type === 1) return { ...base, title: '', env_id: null, api_id: null }
    if (type === 2) return { ...base, name: '', env_type: null, value: '' }
    if (type === 3) return { ...base, wait_time: 1 }
    if (type === 4) return { ...base, code: '', language: 'python', code_map: {}, exec_mode: 'sandbox' }
    if (type === 5) return { ...base, db_id: null, db_name: '', result_var: '', sql: '' }
    if (type === 6) return { ...base, func_id: null, func_name: '', result_var: '', func_params: '', exec_mode: 'sandbox' }
  }
  if (props.mode === 'after') {
    if (type === 1) return { ...base, res_type: null, name: '', env_type: null, value: '' }
    if (type === 2) return { ...base, wait_time: 1 }
    if (type === 3) return { ...base, assert_name: '', rules: [] }
    if (type === 4) return { ...base, db_id: null, db_name: '', result_var: '', sql: '' }
    if (type === 5) return { ...base, code: '', language: 'python', code_map: {}, exec_mode: 'sandbox' }
    if (type === 6) return { ...base, func_id: null, func_name: '', result_var: '', func_params: '', exec_mode: 'sandbox' }
    if (type === 7) return { ...base, import_title: '', env_id: null, api_id: null }
  }
  if (props.mode === 'assert') {
    if (type === 1) return { ...base, assert_name: '', rules: [] }
    if (type === 2) return { ...base, ops_db_table: '', ops_db_where: '' }
    if (type === 4) return { ...base, local_db: null, local_db_table: '', local_db_where: '', local_db_assert: [] }
    if (type === 5) return { ...base, custom_name: '', custom_script: '', language: 'python', code_map: {}, exec_mode: 'sandbox' }
  }
  return base
}

// ---- 拖拽排序 ----
const dragIndex = ref(-1)
const onDragStart = (i: number, e: any) => {
	dragIndex.value = i
	if (e?.dataTransfer) {
		e.dataTransfer.effectAllowed = 'move'
		try { e.dataTransfer.setData('text/plain', String(i)) } catch {}
	}
}
const onDragOver = () => {}
const onDrop = (i: number) => {
	const from = dragIndex.value
	if (from >= 0 && from !== i) {
		const it = props.items.splice(from, 1)[0]
		props.items.splice(i, 0, it)
	}
	dragIndex.value = -1
}

// ---- Add item ----
const addItem = (type: number) => {
  props.items.push(defaultItem(type))
}
</script>

<style scoped lang="scss">
// ---- Panel shell ----
.op-panel {
  display: flex;
  flex-direction: column;
}

// ---- Card list (natural flow, parent tab scrolls) ----
.op-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 4px 0 8px;
}

.op-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 32px 0;
  color: var(--el-text-color-placeholder);
  font-size: 13px;
  gap: 8px;
}

// ---- Card ----
.op-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  overflow: hidden;

  &--blue   { border-left: 3px solid #409eff; }
  &--purple { border-left: 3px solid #9b59b6; }
  &--gray   { border-left: 3px solid #909399; }
  &--orange { border-left: 3px solid #e6a23c; }
  &--yellow { border-left: 3px solid #f59e0b; }
  &--teal   { border-left: 3px solid #0ea5e9; }
  &--green  { border-left: 3px solid #67c23a; }
}

.op-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 8px;
  cursor: pointer;
  user-select: none;
  background: var(--el-fill-color-lighter);

  &:hover {
    background: var(--el-fill-color-light);
  }
}

.op-card__title {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: 1;
}

.op-card__summary {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 200px;
}

.op-card__badge {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 700;
  color: #fff;
  flex-shrink: 0;

  &.badge--blue   { background: #409eff; }
  &.badge--purple { background: #9b59b6; }
  &.badge--gray   { background: #909399; }
  &.badge--orange { background: #e6a23c; }
  &.badge--yellow { background: #f59e0b; }
  &.badge--teal   { background: #0ea5e9; }
  &.badge--green  { background: #67c23a; }
}

.op-card__icon {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  flex-shrink: 0;
}

.op-card__type-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  flex-shrink: 0;
}

.op-card--disabled { opacity: 0.55; }
.op-card__drag { cursor: grab; font-size: 14px; color: #909399; margin-right: 4px; }
.op-card__drag:active { cursor: grabbing; }
.op-card__actions {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
}

.op-card__collapse-icon {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  transition: transform 0.2s;
  transform: rotate(0deg);

  &.is-collapsed {
    transform: rotate(-90deg);
  }
}

.op-card__body {
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 7px;
  border-top: 1px solid var(--el-border-color-lighter);
}

// ---- Row ----
.op-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: nowrap;

  &--full {
    align-items: flex-start;
  }
}

.op-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
  flex-shrink: 0;
  min-width: 36px;
}

.op-unit {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

// ---- Code editor ----
.op-code-wrap {
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  overflow: hidden;
}

.op-code-lang {
  background: #2a2a3e;
  color: #a78bfa;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  letter-spacing: 0.5px;
}

.op-code-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #2a2a3e;
  padding: 4px 8px;
}

.op-code-hint {
  font-size: 11px;
  color: #94a3b8;
}

.op-code-validate { margin-top: 6px; }
.op-cv-panel { margin-top: 4px; padding: 6px 10px; border-radius: 6px; font-size: 12px; line-height: 1.6; border: 1px solid; }
.op-cv-panel.ok { background: #f0fdf4; border-color: #bbf7d0; color: #166534; }
.op-cv-panel.fail { background: #fef2f2; border-color: #fecaca; color: #991b1b; }
.op-cv-line { margin-top: 2px; }
.op-cv-line.ai { color: #b45309; }
.op-code-editor {
  width: 100%;
  min-height: 80px;
  max-height: 160px;
  padding: 6px 8px;
  background: #1e1e2e;
  color: #cdd6f4;
  font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 12px;
  line-height: 1.5;
  border: none;
  outline: none;
  resize: vertical;
  box-sizing: border-box;
}

// ---- Add bar (always visible at bottom) ----
.op-add-bar {
  flex-shrink: 0;
  padding: 8px 10px;
  border-top: 1px solid var(--el-border-color-lighter);
  background: var(--el-fill-color-lighter);
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.op-add-label {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
  flex-shrink: 0;
}

.op-add-types {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.op-type-btn {
  display: inline-flex;
  align-items: center;
  border-radius: 4px;
  font-size: 11px;
  height: 24px;
  padding: 0 8px;
  border: 1px solid;
  cursor: pointer;
  background: transparent;
  transition: background 0.15s, color 0.15s;

  &--blue   { color: #409eff; border-color: #b3d8ff; background: #ecf5ff; &:hover { background: #409eff; color: #fff; } }
  &--purple { color: #9b59b6; border-color: #d9b3e8; background: #f5ecfb; &:hover { background: #9b59b6; color: #fff; } }
  &--gray   { color: #606266; border-color: #dcdfe6; background: #f4f4f5; &:hover { background: #909399; color: #fff; } }
  &--orange { color: #e6a23c; border-color: #f5dab1; background: #fdf6ec; &:hover { background: #e6a23c; color: #fff; } }
  &--yellow { color: #b45309; border-color: #fcd34d; background: #fffbeb; &:hover { background: #f59e0b; color: #fff; } }
  &--teal   { color: #0ea5e9; border-color: #bae6fd; background: #f0f9ff; &:hover { background: #0ea5e9; color: #fff; } }
  &--green  { color: #67c23a; border-color: #b3e19d; background: #f0f9eb; &:hover { background: #67c23a; color: #fff; } }
}
</style>
