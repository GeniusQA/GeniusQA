<template>
  <div class="web-automation-page">
    <el-container class="wa-container" direction="vertical">
      <el-header class="wa-page-header">
        <div v-if="pageMode === 'list'" class="wa-header-row">
          <el-space wrap :size="12">
            <el-text tag="b" size="large">{{ listPageTitle }}</el-text>
            <el-text size="small" type="info">点击表格行：脚本进入编辑，脚本库进入分组管理</el-text>
          </el-space>
          <el-space wrap :size="8">
            <el-button type="primary" :plain="false" @click="openCreateResourceDialog('script')">
              <el-icon class="el-icon--left"><CirclePlus /></el-icon>
              新建脚本/脚本库
            </el-button>
            <el-button type="warning" :plain="false" @click="goPlaywrightRecorder">
              <el-icon class="el-icon--left"><VideoCamera /></el-icon>
              录制脚本
            </el-button>
            <el-button type="info" :plain="false" @click="get_web_menu">
              <el-icon class="el-icon--left"><Refresh /></el-icon>
              刷新
            </el-button>
          </el-space>
        </div>
        <div v-else class="wa-header-row">
          <el-space wrap :size="8">
            <el-button @click="goBackToList">
              <el-icon class="el-icon--left"><ArrowLeft /></el-icon>
              返回列表
            </el-button>
            <el-button type="primary" @click="resourceDrawerVisible = true">
              <el-icon class="el-icon--left"><Folder /></el-icon>
              切换脚本
            </el-button>
          </el-space>
          <el-button text type="primary" @click="get_web_menu">
            <el-icon class="el-icon--left"><Refresh /></el-icon>
            刷新目录
          </el-button>
        </div>
      </el-header>
      <el-main class="wa-main">
      <!-- 首页：脚本列表 -->
      <div v-if="pageMode === 'list'" class="wa-home-list">
        <el-card shadow="never" class="wa-list-card">
          <el-table
            class="wa-script-table wa-script-table--tree"
            v-loading="loading"
            :data="homeResourceTree"
            :row-key="(row: any) => row.id"
            :tree-props="{ children: 'children' }"
            default-expand-all
            stripe
            border
            style="width: 100%"
            empty-text="暂无目录与脚本，请先新建或刷新"
            @row-click="onHomeResourceRowClick"
          >
            <el-table-column label="名称" min-width="220" show-overflow-tooltip>
              <template #default="{ row }">
                <el-space :size="8" alignment="center">
                  <el-icon class="wa-res-icon" :class="row.type === 2 ? 'wa-res-icon--script' : 'wa-res-icon--folder'">
                    <ChromeFilled v-if="row.type === 2" />
                    <Folder v-else />
                  </el-icon>
                  <span>{{ row.name }}</span>
                </el-space>
              </template>
            </el-table-column>
            <el-table-column label="类型" width="108" align="center">
              <template #default="{ row }">
                <el-tag :type="row.type === 2 ? 'primary' : 'warning'" effect="dark" size="small">
                  {{ row.type === 2 ? '脚本' : '脚本库' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="112" align="center">
              <template #default="{ row }">
                <el-tag :type="statusTagTypeFor(row)" size="small">{{ statusLabelFor(row) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="268" fixed="right" align="center">
              <template #default="{ row }">
                <el-space :size="8" wrap alignment="center" class="wa-table-actions">
                  <el-button type="primary" size="small" :plain="false" @click.stop="openResourceFromList(row)">
                    {{ row.type === 2 ? '进入编辑' : '进入管理' }}
                  </el-button>
                  <el-button type="danger" size="small" :plain="false" @click.stop="deleteResourceFromList(row)">
                    删除
                  </el-button>
                </el-space>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </div>

      <section v-else class="web-automation-workspace">
        <div class="workspace-shell">
        <div class="workspace-inner">
          <el-tabs v-model="tab_active" closable class="demo-tabs web-script-tabs web-script-tabs--underline" @tab-remove="removeTab">
            <el-tab-pane
              v-for="(item, index) in tab_list"
              :key="index"
              :label="item.title"
              :name="item.name"
              v-loading="loading"
            >
              <template #label>
                <span v-if="item.type === 1">
                  <el-icon style="padding-right: 5px">
                    <Folder />
                  </el-icon>
                  {{ item.name }}
                </span>
                <span v-else-if="item.type === 2">
                  <el-icon style="padding-right: 5px">
                    <ChromeFilled />
                  </el-icon>
                  {{ item.name }}
                </span>
              </template>

              <!-- 脚本集 tab -->
              <div v-if="item.type === 1" class="folder-tab-panel">
                <el-card shadow="never" class="folder-batch-card">
                  <div>
                    <div
                      style="float: right; padding-left: 10px; padding-right: 10px; padding-block-end: 10px"
                    >
                      <el-button type="primary" @click="batch_run_script">立即调试</el-button>
                    </div>
                    <el-table
                      v-loading="loading"
                      border
                      :data="table_list"
                      empty-text="暂时没有数据"
                      @selection-change="handleSelectionChange"
                    >
                      <el-table-column type="selection" align="center" />
                      <el-table-column label="序号" prop="id" align="center" type="index" />
                      <el-table-column
                        label="脚本名称"
                        prop="name"
                        align="center"
                        :show-overflow-tooltip="true"
                      />
                      <el-table-column label="类型" align="center">
                        <template #default="{ row }">
                          <el-tag v-if="row.type === 1">脚本库</el-tag>
                          <el-tag v-else-if="row.type === 2">脚本</el-tag>
                        </template>
                      </el-table-column>
                      <el-table-column label="顺序" align="center">
                        <template #default="{ row }">
                          <el-input-number v-model="row.step" :min="1" :max="100" />
                        </template>
                      </el-table-column>
                    </el-table>
                  </div>
                </el-card>
              </div>

              <!-- 单脚本：顶区卡片 + 步骤工具卡片 + 上下分栏（步骤上 / 属性下） -->
              <div v-else-if="item.type === 2" class="script-tab-root">
                <el-card class="wa-hero-card" shadow="never">
                  <div class="workspace-hero">
                    <div class="hero-left">
                      <div class="hero-icon-wrap" aria-hidden="true">
                        <el-icon><ChromeFilled /></el-icon>
                      </div>
                      <div class="hero-text">
                        <el-text tag="h2" class="hero-title" truncated>{{ item.name }}</el-text>
                        <p class="hero-meta-line">
                          <el-tag size="small" type="info" effect="plain">Web 自动化</el-tag>
                          <el-text size="small" type="info" class="hero-meta-sep">·</el-text>
                          <el-text size="small" type="info">{{ item.content?.username ?? '-' }}</el-text>
                          <el-text size="small" type="info" class="hero-meta-sep">·</el-text>
                          <el-text size="small" type="info">{{ item.content?.update_time ?? '-' }}</el-text>
                        </p>
                      </div>
                    </div>
                    <div class="hero-actions">
                      <!-- 暂不启用 AI 脚本录入，仅保留自定义步骤入口
                      <el-button type="primary" plain @click="ai_script_input()">AI 脚本录入</el-button>
                      -->
                      <el-button type="primary" @click="run_script(item)">立即调试</el-button>
                      <el-button type="success" @click="save_web_script_handler(item.id)">保存</el-button>
                    </div>
                  </div>
                </el-card>

                <el-card class="wa-ribbon-card" shadow="never" aria-label="添加步骤">
                  <div class="step-ribbon">
                  <el-text size="small" type="info" class="ribbon-label">添加步骤</el-text>
                  <div class="ribbon-scroll">
                      <el-dropdown @command="add_script" trigger="click">
                        <el-button type="primary" :plain="false" class="toolbar-dd-btn">
                          浏览器操作<el-icon class="el-icon--right"><ArrowDown /></el-icon>
                        </el-button>
                        <template #dropdown>
                          <el-dropdown-menu>
                            <el-dropdown-item divided :command="{ type: 0, name: '首次打开网页' }">首次打开网页</el-dropdown-item>
                            <el-dropdown-item divided :command="{ type: 13, name: '打开新窗口' }">打开新窗口</el-dropdown-item>
                            <el-dropdown-item divided :command="{ type: 14, name: '切换上一个窗口' }">切换上一个窗口</el-dropdown-item>
                            <el-dropdown-item divided :command="{ type: 15, name: '切换下一个窗口' }">切换下一个窗口</el-dropdown-item>
                            <el-dropdown-item divided :command="{ type: 20, name: '刷新当前页' }">刷新当前页</el-dropdown-item>
                            <el-dropdown-item divided :command="{ type: 21, name: '关闭标签页' }">关闭标签页</el-dropdown-item>
                          </el-dropdown-menu>
                        </template>
                      </el-dropdown>
                      <el-button
                        :plain="false"
                        class="toolbar-dd-btn wa-step-dd--custom"
                        @click="add_script({ type: 17, name: '自定义步骤' })"
                      >
                        自定义步骤
                      </el-button>
                      <!-- AI 步骤（type:19）暂下线，恢复时还原下拉并取消下行注释
                      <el-dropdown @command="add_script" trigger="click">
                        <el-button :plain="false" class="toolbar-dd-btn wa-step-dd--ai">
                          AI + 自定义<el-icon class="el-icon--right"><ArrowDown /></el-icon>
                        </el-button>
                        <template #dropdown>
                          <el-dropdown-menu>
                            <el-dropdown-item :command="{ type: 19, name: 'AI 步骤' }">AI 步骤</el-dropdown-item>
                            <el-dropdown-item divided :command="{ type: 17, name: '自定义步骤' }">自定义步骤</el-dropdown-item>
                          </el-dropdown-menu>
                        </template>
                      </el-dropdown>
                      -->
                      <el-dropdown @command="add_script" trigger="click">
                        <el-button type="success" :plain="false" class="toolbar-dd-btn">
                          鼠标操作<el-icon class="el-icon--right"><ArrowDown /></el-icon>
                        </el-button>
                        <template #dropdown>
                          <el-dropdown-menu>
                            <el-dropdown-item :command="{ type: 1, name: '左键点击' }">左键点击</el-dropdown-item>
                            <el-dropdown-item :command="{ type: 16, name: '右键点击' }">右键点击</el-dropdown-item>
                            <el-dropdown-item :command="{ type: 2, name: '双击事件' }">双击事件</el-dropdown-item>
                            <el-dropdown-item :command="{ type: 3, name: '长按事件' }">长按事件</el-dropdown-item>
                            <el-dropdown-item :command="{ type: 4, name: '拖拽事件' }">拖拽事件</el-dropdown-item>
                          </el-dropdown-menu>
                        </template>
                      </el-dropdown>
                      <el-dropdown @command="add_script" trigger="click">
                        <el-button type="info" :plain="false" class="toolbar-dd-btn">
                          输入操作<el-icon class="el-icon--right"><ArrowDown /></el-icon>
                        </el-button>
                        <template #dropdown>
                          <el-dropdown-menu>
                            <el-dropdown-item :command="{ type: 5, name: '直接输入' }">直接输入</el-dropdown-item>
                            <el-dropdown-item :command="{ type: 6, name: '补充输入' }">补充输入</el-dropdown-item>
                            <el-dropdown-item :command="{ type: 7, name: '清空文本' }">清空文本</el-dropdown-item>
                          </el-dropdown-menu>
                        </template>
                      </el-dropdown>
                      <el-dropdown @command="add_script" trigger="click">
                        <el-button type="warning" :plain="false" class="toolbar-dd-btn">
                          滑动操作<el-icon class="el-icon--right"><ArrowDown /></el-icon>
                        </el-button>
                        <template #dropdown>
                          <el-dropdown-menu>
                            <el-dropdown-item :command="{ type: 8, name: '上下滑动' }">上下滑动</el-dropdown-item>
                          </el-dropdown-menu>
                        </template>
                      </el-dropdown>
                      <el-dropdown @command="add_script" trigger="click">
                        <el-button type="danger" :plain="false" class="toolbar-dd-btn">
                          文件操作<el-icon class="el-icon--right"><ArrowDown /></el-icon>
                        </el-button>
                        <template #dropdown>
                          <el-dropdown-menu>
                            <el-dropdown-item :command="{ type: 18, name: '上传文件' }">上传文件</el-dropdown-item>
                          </el-dropdown-menu>
                        </template>
                      </el-dropdown>
                      <el-dropdown @command="add_script" trigger="click">
                        <el-button :plain="false" class="toolbar-dd-btn wa-step-dd--logic">
                          逻辑事件<el-icon class="el-icon--right"><ArrowDown /></el-icon>
                        </el-button>
                        <template #dropdown>
                          <el-dropdown-menu>
                            <el-dropdown-item :command="{ type: 10, name: 'if 事件' }">if 事件</el-dropdown-item>
                            <el-dropdown-item :command="{ type: 11, name: 'for 循环' }">for 循环</el-dropdown-item>
                            <el-dropdown-item :command="{ type: 12, name: '等待事件' }">等待事件</el-dropdown-item>
                          </el-dropdown-menu>
                        </template>
                      </el-dropdown>
                  </div>
                </div>
                </el-card>

                <div class="workspace-canvas workspace-canvas--stacked">
                  <el-card class="step-rail-card" shadow="never">
                    <template #header>
                      <span>步骤</span>
                    </template>
                    <div class="step-tree-inner">
                          <el-tree
                            ref="step_treeRef"
                            :data="item.content.script"
                            :props="defaultProps"
                            default-expand-all
                            :allow-drop="on_menu_allowDrop"
                            @node-click="web_script_click"
                            draggable
                            class="step-tree"
                          >
                            <template #default="{ data }">
                              <el-card class="step-card" shadow="never" :body-style="{ padding: '4px 8px' }">
                                <div class="card-header">
                                  <span class="card-left">
                                    <span class="step-icon">1</span>
                                    <span class="method-tag">{{ data.name }}</span>
                                  </span>
                                  <div class="card-actions">
                                    <el-switch
                                      v-model="data.status"
                                      inline-prompt
                                      size="small"
                                      style="--el-switch-on-color: var(--el-color-primary); --el-switch-off-color: var(--el-color-danger)"
                                    />
                                    <el-button
                                      :icon="DocumentCopy"
                                      link
                                      type="primary"
                                      size="small"
                                      circle
                                      class="action-button"
                                      title="复制"
                                      @click.stop="copy_row(item.content.script, data)"
                                    />
                                    <el-button
                                      :icon="Delete"
                                      link
                                      type="danger"
                                      size="small"
                                      circle
                                      class="action-button"
                                      title="删除"
                                      @click.stop="Delete_row(item.content.script, data)"
                                    />
                                  </div>
                                </div>
                              </el-card>
                            </template>
                          </el-tree>
                    </div>
                  </el-card>

                  <el-card class="step-inspector-card" shadow="never">
                    <template #header>
                      <span>步骤属性</span>
                    </template>
                    <div class="step-config-body">
                          <el-form>
                            <el-form-item v-if="script_info.type !== 19" label="名称：">
                              <el-input v-model="script_info.name" />
                            </el-form-item>
                            <el-form-item
                              v-if="
                                script_info.type === 0 ||
                                script_info.type === 1 ||
                                script_info.type === 2 ||
                                script_info.type === 3 ||
                                script_info.type === 5 ||
                                script_info.type === 6 ||
                                script_info.type === 7 ||
                                script_info.type === 13 ||
                                script_info.type === 16 ||
                                script_info.type === 17
                              "
                              label="定位："
                            >
                              <el-radio-group v-model="script_info.action.type">
                                <el-radio :value="1">自定义</el-radio>
                                <el-radio :value="2">元素库</el-radio>
                              </el-radio-group>
                            </el-form-item>
                            <el-form-item
                              v-if="
                                script_info.action.type !== 2 &&
                                script_info.type !== 0 &&
                                script_info.type !== 4 &&
                                script_info.type !== 8 &&
                                script_info.type !== 9 &&
                                script_info.type !== 10 &&
                                script_info.type !== 11 &&
                                script_info.type !== 12 &&
                                script_info.type !== 13 &&
                                script_info.type !== 14 &&
                                script_info.type !== 15 &&
                                script_info.type !== 19 &&
                                script_info.type !== 20 &&
                                script_info.type !== 21 &&
                                script_info.type !== 17
                              "
                              label="选择器："
                            >
                              <el-select v-model="script_info.action.locator" style="width: 22%" filterable>
                                <el-option
                                  v-for="item in locator_list"
                                  :key="item.value"
                                  :label="item.name"
                                  :value="item.value"
                                />
                              </el-select>
                              <el-select
                                v-if="script_info.action.locator === 2"
                                v-model="script_info.action.locator_select"
                                style="width: 22%; padding-left: 15px"
                                filterable
                              >
                                <el-option
                                  v-for="item in locator_selects"
                                  :key="item.value"
                                  :label="item.label"
                                  :value="item.value"
                                />
                              </el-select>
                              <el-select
                                v-if="script_info.action.locator_select === 7 && script_info.action.locator === 2"
                                v-model="script_info.action.role"
                                style="width: 22%; padding-left: 15px"
                                filterable
                              >
                                <el-option
                                  v-for="(item, index) in role_list"
                                  :key="index"
                                  :label="item.label"
                                  :value="item.value"
                                />
                              </el-select>
                            </el-form-item>
                            <el-form-item
                              v-if="
                                script_info.action.type !== 2 &&
                                (script_info.type === 0 || script_info.type === 13)
                              "
                              label="网址："
                            >
                              <el-input v-model="script_info.action.element" placeholder="请输入网址" />
                            </el-form-item>
                            <el-form-item
                              v-if="
                                script_info.type !== 0 &&
                                script_info.type !== 4 &&
                                script_info.type !== 8 &&
                                script_info.type !== 9 &&
                                script_info.type !== 10 &&
                                script_info.type !== 11 &&
                                script_info.type !== 12 &&
                                script_info.type !== 13 &&
                                script_info.type !== 14 &&
                                script_info.type !== 15 &&
                                script_info.type !== 20 &&
                                script_info.type !== 19 &&
                                script_info.type !== 21 &&
                                script_info.action.type === 1
                              "
                              label="元素值："
                            >
                              <textarea
                                v-if="
                                  (script_info.type !== 19 && script_info.action.locator === 1) ||
                                  script_info.type === 17
                                "
                                v-model="script_info.action.element"
                                style="
                                  padding: 5px;
                                  border: 1px solid var(--el-border-color);
                                  width: 98%;
                                  height: 80px;
                                "
                                placeholder="请输入元素值，多个元素地址用英文逗号“,”隔开"
                              />
                              <el-input
                                v-if="script_info.action.locator === 2"
                                v-model="script_info.action.element"
                                placeholder="请输入元素值"
                              />
                            </el-form-item>
                            <el-form-item v-if="script_info.type === 19" label="脚本内容：">
                              <textarea
                                v-model="script_info.action.element"
                                style="
                                  padding: 5px;
                                  border: 1px solid var(--el-border-color);
                                  width: 98%;
                                  height: 80px;
                                "
                                placeholder="例如：用户名输入框输入'admin'"
                              />
                            </el-form-item>
                            <el-form-item v-if="script_info.type === 4" label="起始定位：">
                              <el-radio-group v-model="script_info.action.type">
                                <el-radio :value="1">自定义</el-radio>
                                <el-radio :value="2">元素库</el-radio>
                              </el-radio-group>
                            </el-form-item>
                            <el-form-item
                              v-if="script_info.action.type === 1 && script_info.type === 4"
                              label="选择器："
                            >
                              <el-select v-model="script_info.action.locator" style="width: 22%" filterable>
                                <el-option
                                  v-for="item in locator_list"
                                  :key="item.value"
                                  :label="item.name"
                                  :value="item.value"
                                />
                              </el-select>
                              <el-select
                                v-if="script_info.action.locator === 2"
                                v-model="script_info.action.locator_select"
                                style="width: 22%; padding-left: 15px"
                                filterable
                              >
                                <el-option
                                  v-for="item in locator_selects"
                                  :key="item.value"
                                  :label="item.label"
                                  :value="item.value"
                                />
                              </el-select>
                              <el-select
                                v-if="script_info.action.locator_select === 7 && script_info.action.locator === 2"
                                v-model="script_info.action.role"
                                style="width: 22%; padding-left: 15px"
                                filterable
                              >
                                <el-option
                                  v-for="(item, index) in role_list"
                                  :key="index"
                                  :label="item.label"
                                  :value="item.value"
                                />
                              </el-select>
                            </el-form-item>
                            <el-form-item
                              v-if="script_info.action.type === 2 && script_info.type === 4"
                              label="选择元素："
                            >
                              <el-cascader
                                v-model="script_info.action.element_id"
                                placeholder="请选择元素"
                                style="width: 350px"
                                :options="element_select_list"
                                filterable
                                :props="{ value: 'element_id', label: 'name', children: 'children' }"
                                @change="element_select_change"
                              >
                                <template #default="{ node, data }">
                                  <el-icon v-if="data.type === 0" style="padding-right: 5px">
                                    <HomeFilled />
                                  </el-icon>
                                  <el-icon v-if="data.type === 1" style="padding-right: 5px">
                                    <Folder />
                                  </el-icon>
                                  <el-icon v-if="data.type === 2" style="padding-right: 5px">
                                    <ElementPlus />
                                  </el-icon>
                                  <span>{{ data.name }}</span>
                                  <span v-if="!node.isLeaf">({{ data.children?.length ?? 0 }})</span>
                                </template>
                              </el-cascader>
                            </el-form-item>
                            <el-form-item
                              v-if="script_info.type === 4 && script_info.action.type === 1"
                              label="起始地址："
                            >
                              <el-input v-model="script_info.action.element" />
                            </el-form-item>
                            <el-form-item v-if="script_info.type === 4" label="目标定位：">
                              <el-radio-group v-model="script_info.action.target_type">
                                <el-radio :value="1">自定义</el-radio>
                                <el-radio :value="2">元素库</el-radio>
                              </el-radio-group>
                            </el-form-item>
                            <el-form-item
                              v-if="script_info.action.target_type === 1 && script_info.type === 4"
                              label="选择器："
                            >
                              <el-select v-model="script_info.action.target_locator" style="width: 22%" filterable>
                                <el-option
                                  v-for="item in locator_list"
                                  :key="item.value"
                                  :label="item.name"
                                  :value="item.value"
                                />
                              </el-select>
                              <el-select
                                v-if="script_info.action.target_locator === 2"
                                v-model="script_info.action.target_locator_select"
                                style="width: 22%; padding-left: 15px"
                                filterable
                              >
                                <el-option
                                  v-for="item in locator_selects"
                                  :key="item.value"
                                  :label="item.label"
                                  :value="item.value"
                                />
                              </el-select>
                              <el-select
                                v-if="script_info.action.target_locator_select === 7"
                                v-model="script_info.action.role"
                                style="width: 22%; padding-left: 15px"
                                filterable
                              >
                                <el-option
                                  v-for="(item, index) in role_list"
                                  :key="index"
                                  :label="item.label"
                                  :value="item.value"
                                />
                              </el-select>
                            </el-form-item>
                            <el-form-item
                              v-if="script_info.action.target_type === 2 && script_info.type === 4"
                              label="选择元素："
                            >
                              <el-cascader
                                v-model="script_info.action.target_id"
                                placeholder="请选择元素"
                                style="width: 350px"
                                :options="element_select_list"
                                filterable
                                :props="{ value: 'element_id', label: 'name', children: 'children' }"
                                @change="element_select_change"
                              >
                                <template #default="{ node, data }">
                                  <el-icon v-if="data.type === 0" style="padding-right: 5px">
                                    <HomeFilled />
                                  </el-icon>
                                  <el-icon v-if="data.type === 1" style="padding-right: 5px">
                                    <Folder />
                                  </el-icon>
                                  <el-icon v-if="data.type === 2" style="padding-right: 5px">
                                    <ElementPlus />
                                  </el-icon>
                                  <span>{{ data.name }}</span>
                                  <span v-if="!node.isLeaf">({{ data.children?.length ?? 0 }})</span>
                                </template>
                              </el-cascader>
                            </el-form-item>
                            <el-form-item
                              v-if="script_info.type === 4 && script_info.action.target_type === 1"
                              label="目标地址："
                            >
                              <el-input v-model="script_info.action.target" />
                            </el-form-item>
                            <el-form-item v-if="script_info.type === 8" label="滑动方向：">
                              <el-radio-group v-model="script_info.action.up_type">
                                <el-radio :value="1">向上</el-radio>
                                <el-radio :value="2">向下</el-radio>
                              </el-radio-group>
                            </el-form-item>
                            <el-form-item v-if="script_info.type === 9" label="滑动方向：">
                              <el-radio-group v-model="script_info.action.sway_type">
                                <el-radio :value="1">向左</el-radio>
                                <el-radio :value="2">向右</el-radio>
                              </el-radio-group>
                            </el-form-item>
                            <el-form-item v-if="script_info.type === 8 || script_info.type === 9" label="像素：">
                              <el-input v-model="script_info.action.element" />
                            </el-form-item>
                            <el-form-item v-if="script_info.type === 10">
                              <el-select
                                v-model="script_info.action.type"
                                style="width: 17%; padding-block-end: 5px"
                                filterable
                              >
                                <el-option
                                  v-for="item in assert_list"
                                  :key="item.value"
                                  :label="item.name"
                                  :value="item.value"
                                />
                              </el-select>
                              <el-select
                                v-if="script_info.action.type === 1 || script_info.action.type === 2"
                                v-model="script_info.action.locator"
                                style="width: 15%; padding-block-end: 5px; padding-left: 5px"
                                filterable
                              >
                                <el-option
                                  v-for="item in locator_list"
                                  :key="item.value"
                                  :label="item.name"
                                  :value="item.value"
                                />
                              </el-select>
                              <el-select
                                v-if="script_info.action.type === 5"
                                v-model="script_info.action.target_type"
                                style="width: 20%; padding-block-end: 5px; padding-left: 5px"
                                filterable
                              >
                                <el-option
                                  v-for="item in browser_assert"
                                  :key="item.value"
                                  :label="item.name"
                                  :value="item.value"
                                />
                              </el-select>
                              <el-select
                                v-if="
                                  script_info.action.locator === 2 &&
                                  (script_info.action.type === 1 || script_info.action.type === 2)
                                "
                                v-model="script_info.action.locator_select"
                                style="width: 15%; padding-block-end: 5px; padding-left: 5px"
                                filterable
                              >
                                <el-option
                                  v-for="item in locator_selects"
                                  :key="item.value"
                                  :label="item.label"
                                  :value="item.value"
                                />
                              </el-select>
                              <el-select
                                v-if="
                                  script_info.action.locator_select === 7 && script_info.action.locator === 2
                                "
                                v-model="script_info.action.input"
                                style="width: 18%; padding-left: 5px; padding-block-end: 5px"
                              >
                                <el-option
                                  v-for="(item, index) in role_list"
                                  :key="index"
                                  :label="item.label"
                                  :value="item.value"
                                />
                              </el-select>
                              <el-input
                                v-model="script_info.action.element"
                                style="width: 30%; padding-left: 5px; padding-block-end: 5px"
                                placeholder="请输入断言内容"
                              />
                            </el-form-item>
                            <el-form-item v-if="script_info.type === 12" label="等待时长：">
                              <el-input-number v-model="script_info.action.element" />
                            </el-form-item>
                            <el-form-item v-if="script_info.type === 11" label="循环次数：">
                              <el-input-number v-model="script_info.action.element" />
                            </el-form-item>
                            <el-form-item
                              v-if="
                                script_info.action.type === 2 &&
                                script_info.type !== 4 &&
                                script_info.type !== 10
                              "
                              label="选择元素："
                            >
                              <el-cascader
                                v-model="script_info.action.element_id"
                                placeholder="请选择元素"
                                style="width: 350px"
                                :options="element_select_list"
                                filterable
                                :props="{ value: 'element_id', label: 'name', children: 'children' }"
                                @change="element_select_change"
                              >
                                <template #default="{ node, data }">
                                  <el-icon v-if="data.type === 0" style="padding-right: 5px">
                                    <HomeFilled />
                                  </el-icon>
                                  <el-icon v-if="data.type === 1" style="padding-right: 5px">
                                    <Folder />
                                  </el-icon>
                                  <el-icon v-if="data.type === 2" style="padding-right: 5px">
                                    <ElementPlus />
                                  </el-icon>
                                  <span>{{ data.name }}</span>
                                  <span v-if="!node.isLeaf">({{ data.children?.length ?? 0 }})</span>
                                </template>
                              </el-cascader>
                            </el-form-item>
                            <el-form-item v-if="script_info.type === 5 || script_info.type === 6" label="输入值：">
                              <el-input v-model="script_info.action.input" />
                            </el-form-item>
                            <el-form-item v-if="script_info.type === 0 || script_info.type === 13">
                              <div style="width: 100%">
                                <el-button
                                  type="primary"
                                  link
                                  :icon="CirclePlus"
                                  @click="add_cookie(script_info.action.cookies || [])"
                                >
                                  添加 cookies 配置项
                                </el-button>
                                <el-form>
                                  <el-form-item
                                    v-for="(ck, index) in (script_info.action.cookies || [])"
                                    :key="index"
                                  >
                                    <el-input
                                      v-model="ck.name"
                                      placeholder="请输入 key"
                                      style="width: 30%; padding-block-end: 5px"
                                    />
                                    <el-input
                                      v-model="ck.value"
                                      placeholder="请输入 value"
                                      style="width: 63%; padding-block-end: 5px; padding-left: 5px"
                                    />
                                    <el-button
                                      type="danger"
                                      link
                                      style="padding-left: 5px; padding-block-end: 10px"
                                      :icon="Remove"
                                      circle
                                      @click="del_cookie(script_info.action.cookies, index)"
                                    />
                                  </el-form-item>
                                </el-form>
                              </div>
                            </el-form-item>
                            <el-form-item v-if="script_info.type === 0 || script_info.type === 13">
                              <div style="width: 100%">
                                <el-button
                                  type="primary"
                                  link
                                  :icon="CirclePlus"
                                  @click="add_localstorage(script_info.action.localstorage || [])"
                                >
                                  添加 localstorage 配置项
                                </el-button>
                                <el-form>
                                  <el-form-item
                                    v-for="(local, index) in (script_info.action.localstorage || [])"
                                    :key="index"
                                  >
                                    <el-input
                                      v-model="local.name"
                                      placeholder="请输入 key"
                                      style="width: 30%; padding-block-end: 5px"
                                    />
                                    <el-input
                                      v-model="local.value"
                                      placeholder="请输入 value"
                                      style="width: 63%; padding-block-end: 5px; padding-left: 5px"
                                    />
                                    <el-button
                                      type="danger"
                                      link
                                      style="padding-left: 5px; padding-block-end: 10px"
                                      :icon="Remove"
                                      circle
                                      @click="del_localstorage(script_info.action.localstorage, index)"
                                    />
                                  </el-form-item>
                                </el-form>
                              </div>
                            </el-form-item>
                            <el-form-item v-if="script_info.type === 21" label="请选择：">
                              <el-radio-group v-model="script_info.action.target">
                                <el-radio value="now">当前标签页</el-radio>
                                <el-radio value="previous">关闭上一个标签页</el-radio>
                                <el-radio value="next">关闭下一个标签页</el-radio>
                                <el-radio value="customize">自定义</el-radio>
                              </el-radio-group>
                            </el-form-item>
                            <el-form-item
                              v-if="script_info.type === 21 && script_info.action.target === 'customize'"
                              label="请选择第几个标签页："
                            >
                              <el-input-number v-model="script_info.action.element" :min="0" :max="10" />
                            </el-form-item>
                            <el-form-item v-if="script_info.type === 18" label="上传文件：">
                              <span v-if="script_info.action.input">
                                （已上传成功：{{ script_info.action.input }}）
                              </span>
                              <div style="width: 100%; display: flex; justify-content: center; height: 220px">
                                <NtestercUploadFiles
                                  v-model="script_info.action.input"
                                  :file-name="script_info.action.input"
                                  @file-success="call_back_1"
                                />
                                <el-button plain type="primary" @click="add_file(script_info.action)">
                                  确认上传
                                </el-button>
                              </div>
                            </el-form-item>
                            <div style="margin-top: 4px">
                              <div style="width: 100%">
                                <el-tabs v-model="config_active" class="demo-tabs web-config-tabs">
                                  <el-tab-pane label="配置项" name="first">
                                    <el-form label-width="120px" label-position="right" style="margin-top: 8px">
                                      <el-form-item label="执行前等待(秒)">
                                        <el-input-number
                                          v-model="script_info.action.before_wait"
                                          :min="0"
                                          :max="15"
                                          controls-position="right"
                                        />
                                      </el-form-item>
                                      <el-form-item label="执行后等待(秒)">
                                        <el-input-number
                                          v-model="script_info.action.after_wait"
                                          :min="0"
                                          :max="15"
                                          controls-position="right"
                                        />
                                      </el-form-item>
                                      <el-form-item label="超时时长(秒)">
                                        <el-input-number
                                          v-model="script_info.action.timeout"
                                          :min="0"
                                          :max="60"
                                          controls-position="right"
                                        />
                                      </el-form-item>
                                    </el-form>
                                  </el-tab-pane>
                                  <el-tab-pane label="断言" name="second">
                                    <el-button
                                      type="primary"
                                      link
                                      :icon="CirclePlus"
                                      @click="add_assert(script_info.action.assert || [])"
                                    >
                                      添加断言
                                    </el-button>
                                    <el-form>
                                      <el-form-item
                                        v-for="(as, index) in (script_info.action.assert || [])"
                                        :key="index"
                                      >
                                        <el-select
                                          v-model="as.type"
                                          style="width: 17%; padding-block-end: 5px"
                                          filterable
                                        >
                                          <el-option
                                            v-for="item in assert_list"
                                            :key="item.value"
                                            :label="item.name"
                                            :value="item.value"
                                          />
                                        </el-select>
                                        <el-select
                                          v-if="as.type === 1 || as.type === 2"
                                          v-model="as.locator"
                                          style="width: 15%; padding-block-end: 5px; padding-left: 5px"
                                          filterable
                                        >
                                          <el-option
                                            v-for="item in locator_list"
                                            :key="item.value"
                                            :label="item.name"
                                            :value="item.value"
                                          />
                                        </el-select>
                                        <el-select
                                          v-if="as.type === 5"
                                          v-model="as.page_type"
                                          style="width: 20%; padding-block-end: 5px; padding-left: 5px"
                                          filterable
                                        >
                                          <el-option
                                            v-for="item in browser_assert"
                                            :key="item.value"
                                            :label="item.name"
                                            :value="item.value"
                                          />
                                        </el-select>
                                        <el-select
                                          v-if="as.locator === 2 && (as.type === 1 || as.type === 2)"
                                          v-model="as.locator_select"
                                          style="width: 15%; padding-block-end: 5px; padding-left: 5px"
                                          filterable
                                        >
                                          <el-option
                                            v-for="item in locator_selects"
                                            :key="item.value"
                                            :label="item.label"
                                            :value="item.value"
                                          />
                                        </el-select>
                                        <el-select
                                          v-if="as.locator_select === 7 && as.locator === 2"
                                          v-model="as.role"
                                          style="width: 18%; padding-left: 5px; padding-block-end: 5px"
                                        >
                                          <el-option
                                            v-for="(item, index) in role_list"
                                            :key="index"
                                            :label="item.label"
                                            :value="item.value"
                                          />
                                        </el-select>
                                        <el-input
                                          v-if="as.type !== 6 && as.type !== 7"
                                          v-model="as.element"
                                          style="width: 28%; padding-left: 5px; padding-block-end: 5px"
                                          placeholder="请输入断言内容"
                                        />
                                        <el-input
                                          v-if="as.type === 6"
                                          v-model="as.element"
                                          style="width: 75%; padding-left: 5px; padding-block-end: 5px"
                                          placeholder="例如：expect(page.get_by_role('xxx', name='xxx')).to_have_value(xxx)"
                                        />
                                        <el-input
                                          v-if="as.type === 7"
                                          v-model="as.element"
                                          style="width: 75%; padding-left: 5px; padding-block-end: 5px"
                                          placeholder="例如：断言xxx存在当前页面"
                                        />
                                        <el-button
                                          type="danger"
                                          link
                                          style="padding-left: 5px; padding-block-end: 10px"
                                          :icon="Remove"
                                          circle
                                          @click="del_assert(script_info.action.assert, index)"
                                        />
                                      </el-form-item>
                                    </el-form>
                                  </el-tab-pane>
                                </el-tabs>
                              </div>
                            </div>
                          </el-form>
                    </div>
                  </el-card>
                </div>
              </div>
            </el-tab-pane>
          </el-tabs>
        </div>


        <NtestercDialog
          ref="add_ntestercDialogRef"
          :title="title"
          :height="100"
          @ntesterc-confirm="add_menu_confirm"
          @ntesterc-cancel="add_menu_cancel"
        >
          <template #content>
            <el-form :model="add_menu_form" label-width="80px">
              <el-form-item label="名称：">
                <el-input v-model="add_menu_form.name" placeholder="请输入名称" clearable />
              </el-form-item>
              <el-form-item label="类型：">
                <el-radio-group v-model="add_menu_form.type">
                  <el-radio :value="1">脚本库</el-radio>
                  <el-radio :value="2">脚本</el-radio>
                </el-radio-group>
              </el-form-item>
            </el-form>
          </template>
        </NtestercDialog>

        <NtestercDialog
          ref="rename_ntestercDialogRef"
          :title="title"
          :height="100"
          @ntesterc-confirm="edit_menu_confirm"
          @ntesterc-cancel="edit_menu_cancel"
        >
          <template #content>
            <el-form :model="add_menu_form" label-width="80px">
              <el-form-item label="名称：">
                <el-input v-model="add_menu_form.name" placeholder="请输入名称" clearable />
              </el-form-item>
            </el-form>
          </template>
        </NtestercDialog>

        <NtestercDialog
          ref="upload_ntestercDialogRef"
          :title="title"
          :height="250"
          @ntesterc-confirm="upload_file_confirm"
          @ntesterc-cancel="upload_file_cancel"
        >
          <template #content>
            <div style="width: 100%; display: flex; justify-content: center">
              <NtestercUploadFiles
                v-model="file_name"
                :accept-type="'.json'"
                :accept-types="'.json'"
                :file-name="file_name"
                @file-success="call_back"
              />
            </div>
          </template>
        </NtestercDialog>

        <NtestercDialog
          ref="run_ntestercDialogRef"
          :title="title"
          :height="200"
          @ntesterc-confirm="run_script_confirm"
          @ntesterc-cancel="run_script_cancel"
        >
          <template #content>
            <el-form>
              <el-form-item label="名称：">
                <el-input v-model="run_script_form.task_name" placeholder="请输入名称" clearable />
              </el-form-item>
              <el-form-item label="执行模式：">
                <el-radio-group v-model="run_script_form.browser_type">
                  <el-radio :value="1">有界面</el-radio>
                  <el-radio :value="2">无界面</el-radio>
                </el-radio-group>
              </el-form-item>
              <el-form-item label="分辨率(高*宽)：">
                <div>
                  <el-input-number
                    v-model="run_script_form.height"
                    controls-position="right"
                    :min="800"
                    label="高度"
                  />
                  <el-input-number
                    v-model="run_script_form.width"
                    style="padding-left: 10px"
                    controls-position="right"
                    :min="800"
                    label="宽度"
                  />
                </div>
              </el-form-item>
              <el-form-item label="选择浏览器：">
                <el-select v-model="run_script_form.browser" multiple style="width: 60%">
                  <el-option
                    v-for="item in browser_list"
                    :key="item.value"
                    :label="item.name"
                    :value="item.value"
                  />
                </el-select>
              </el-form-item>
            </el-form>
          </template>
        </NtestercDialog>

        <el-drawer
          v-model="runMonitorDrawerVisible"
          :title="title"
          direction="rtl"
          size="min(92vw, 1680px)"
          append-to-body
          class="wa-run-monitor-drawer wa-run-monitor-theme"
          :show-close="true"
          :close-on-click-modal="false"
          @closed="onRunMonitorDrawerClosed"
        >
          <template #header>
            <div class="wa-run-monitor-drawer-header">
              <div class="wa-run-monitor-drawer-titleline">
                <span class="wa-run-monitor-drawer-title">{{ title }}</span>
                <el-tag type="info" effect="plain" size="small" class="wa-run-monitor-drawer-badge">执行监控</el-tag>
              </div>
              <p class="wa-run-monitor-drawer-sub">实时步骤与日志，执行结束后可继续查看或关闭抽屉</p>
            </div>
          </template>
          <div class="wa-run-monitor-shell">
            <div v-loading="loading" class="wa-run-monitor-body">
              <el-tabs
                tab-position="left"
                v-model="run_browser_active"
                class="wa-run-monitor-tabs"
                @tab-click="change_browser"
              >
                <el-tab-pane v-for="(item, index) in run_browsers" :key="index" :name="item.value">
                  <template #label>
                    <span class="wa-run-monitor-tab-label">{{ item.name }}</span>
                  </template>
                  <div class="wa-run-monitor-pane">
                    <div class="wa-run-monitor-desc">
                      <el-card shadow="never" class="wa-run-monitor-surface wa-run-monitor-summary">
                        <el-descriptions :column="3" class="wa-run-monitor-desc-table" size="small">
                          <el-descriptions-item label="执行状态">
                            <span v-if="run_type === '正在执行'" class="wa-run-monitor-pill wa-run-monitor-pill--run">{{ run_type }}</span>
                            <span v-else-if="run_type === '执行结束'" class="wa-run-monitor-pill wa-run-monitor-pill--done">{{ run_type }}</span>
                          </el-descriptions-item>
                          <el-descriptions-item label="浏览器">{{ item.name }}</el-descriptions-item>
                          <el-descriptions-item label="开始时间">{{ start_time || '—' }}</el-descriptions-item>
                          <el-descriptions-item label="结束时间">{{ end_time || '—' }}</el-descriptions-item>
                          <el-descriptions-item label="已执行">{{ run_count }}</el-descriptions-item>
                          <el-descriptions-item label="通过">{{ run_count - run_fail }}</el-descriptions-item>
                          <el-descriptions-item label="失败">{{ run_fail }}</el-descriptions-item>
                        </el-descriptions>
                      </el-card>
                    </div>
                    <div class="wa-run-monitor-split">
                      <el-card shadow="never" class="wa-run-monitor-surface wa-run-monitor-card wa-run-monitor-card--timeline">
                        <template #header>
                          <span class="wa-run-monitor-card-title">执行步骤</span>
                        </template>
                        <el-timeline class="wa-run-monitor-timeline">
                          <el-timeline-item
                            v-for="(res, index) in web_result"
                            :key="index"
                            center
                            :icon="getIcon(res.status)"
                            type="primary"
                            :color="colors(res.status)"
                            size="large"
                            :timestamp="'执行时间：' + formatTime(res.create_time)"
                            placement="top"
                          >
                            <el-card
                              shadow="never"
                              class="wa-run-monitor-timeline-node"
                              :class="res.status === 1 ? 'wa-run-monitor-timeline-node--ok' : 'wa-run-monitor-timeline-node--fail'"
                              :body-style="{ padding: '8px 12px' }"
                            >
                              <span>{{ res.name }}</span>
                              <span>{{ '结果：' + res.log }}</span>
                            </el-card>
                          </el-timeline-item>
                        </el-timeline>
                      </el-card>
                      <el-card shadow="never" class="wa-run-monitor-surface wa-run-monitor-card wa-run-monitor-card--log">
                        <template #header>
                          <div class="wa-run-monitor-log-toolbar">
                            <span class="wa-run-monitor-log-toolbar-title">
                              <el-icon class="wa-run-monitor-log-toolbar-icon"><Monitor /></el-icon>
                              调试执行日志
                            </span>
                            <el-button size="small" class="wa-run-monitor-btn-ghost" @click="copyWebResultLog">
                              <el-icon class="el-icon--left"><DocumentCopy /></el-icon>
                              复制
                            </el-button>
                          </div>
                        </template>
                        <ul class="wa-run-monitor-log-list">
                          <li v-if="run_type !== '执行结束'" class="wa-run-monitor-log-pending">
                            <span class="wa-run-monitor-log-dot" aria-hidden="true" />
                            执行日志获取中…
                          </li>
                          <li
                            v-for="(log, index) in web_result_log"
                            :key="index"
                            class="wa-run-monitor-log-line"
                            :class="logLineClass(log)"
                          >
                            <template v-for="(seg, si) in parseLogLineForDisplay(log)" :key="`${index}-${si}`">
                              <span :class="seg.cls">{{ seg.text }}</span>
                            </template>
                          </li>
                        </ul>
                      </el-card>
                    </div>
                  </div>
                </el-tab-pane>
              </el-tabs>
            </div>
            <div class="wa-run-monitor-footer">
              <el-button class="wa-run-monitor-btn-ghost" @click="runMonitorDrawerVisible = false">关闭</el-button>
            </div>
          </div>
        </el-drawer>
      </div>
      </section>
      </el-main>
    </el-container>

    <el-drawer
      v-model="resourceDrawerVisible"
      title="脚本资源"
      direction="ltr"
      size="320px"
      append-to-body
    >
      <el-input
        v-model="filterText"
        clearable
        placeholder="搜索节点名称"
        class="wa-drawer-search"
      />
      <el-tree
        ref="treeRef"
        class="filter-tree"
        :data="tree_data"
        :props="defaultProps"
        default-expand-all
        :filter-node-method="filterNode"
        @node-click="web_menu_click"
        :allow-drop="on_menu_allowDrop"
        draggable
      >
        <template #default="{ node, data }">
          <span class="custom-tree-node">
            <span v-if="data.type === 0">
              <el-icon class="wa-tree-icon">
                <HomeFilled />
              </el-icon>
              {{ node.label }}
            </span>
            <span v-else-if="data.type === 1">
              <el-icon class="wa-tree-icon">
                <Folder />
              </el-icon>
              {{ node.label }}
            </span>
            <span v-else-if="data.type === 2">
              <el-icon class="wa-tree-icon">
                <ChromeFilled />
              </el-icon>
              {{ node.label }}
            </span>
            <span v-if="data.type === 0" class="right tree-node-actions">
              <el-dropdown placement="bottom" trigger="click">
                <el-icon class="tree-more-trigger">
                  <MoreFilled />
                </el-icon>
                <span class="el-dropdown-link" />
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item :icon="CirclePlus" @click="add_menu(data)">
                      新建子菜单
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </span>
            <span v-else-if="data.type === 1" class="right tree-node-actions">
              <el-dropdown placement="bottom" trigger="click">
                <el-icon class="tree-more-trigger">
                  <MoreFilled />
                </el-icon>
                <span class="el-dropdown-link" />
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item :icon="CirclePlus" @click="add_menu(data)">
                      新建子菜单
                    </el-dropdown-item>
                    <el-dropdown-item :icon="Upload" @click="upload_file(data)">上传</el-dropdown-item>
                    <el-dropdown-item :icon="Edit" @click="rename_menu(data)">重命名</el-dropdown-item>
                    <el-dropdown-item :icon="Delete" @click="del_menu(data)">删除</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </span>
            <span v-else-if="data.type === 2" class="right tree-node-actions">
              <el-dropdown placement="bottom" trigger="click">
                <el-icon class="tree-more-trigger">
                  <MoreFilled />
                </el-icon>
                <span class="el-dropdown-link" />
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item :icon="Edit" @click="rename_menu(data)">重命名</el-dropdown-item>
                    <el-dropdown-item :icon="Delete" @click="del_menu(data)">删除</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </span>
          </span>
        </template>
      </el-tree>
    </el-drawer>

    <el-dialog
      v-model="createResourceVisible"
      :title="createResourceForm.resourceType === 2 ? '新建脚本' : '新建脚本库'"
      width="460px"
      destroy-on-close
      append-to-body
      @closed="resetCreateResourceForm"
    >
      <el-form :model="createResourceForm" label-width="96px">
        <el-form-item label="类型">
          <el-radio-group v-model="createResourceForm.resourceType" @change="onCreateResourceTypeChange">
            <el-radio :value="2">脚本</el-radio>
            <el-radio :value="1">脚本库</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item :label="createResourceForm.resourceType === 2 ? '脚本名称' : '脚本库名称'" required>
          <el-input
            v-model="createResourceForm.name"
            :placeholder="createResourceForm.resourceType === 2 ? '请输入脚本名称' : '请输入脚本库名称'"
            clearable
            maxlength="64"
            show-word-limit
          />
        </el-form-item>
        <el-form-item label="父级位置" required>
          <el-select v-model="createResourceForm.pid" placeholder="选择父级目录" filterable style="width: 100%">
            <el-option
              v-for="opt in folderParentOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createResourceVisible = false">取消</el-button>
        <el-button type="primary" :loading="createResourceSubmitting" @click="submitCreateResource">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>
<script setup lang="ts">
import { onMounted, ref, watch, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElTree, ElMessage, ElMessageBox } from 'element-plus'
import {
  DocumentCopy,
  Delete,
  HomeFilled,
  Folder,
  ChromeFilled,
  ArrowDown,
  MoreFilled,
  CirclePlus,
  Edit,
  Upload,
  Remove,
  Refresh,
  ArrowLeft,
  Monitor,
  VideoCamera,
} from '@element-plus/icons-vue'
import NtestercDialog from '/@/components/ntesterc/NtestercDialog.vue'
import NtestercUploadFiles from '/@/components/ntesterc/NtestercUploadFiles.vue'
import { useWebManagementApi } from '/@/api/v1/testing/webManagement'
import { logLineClass, parseLogLineForDisplay } from '@/utils/runMonitorLog'

const {
  web_menu,
  get_web_script,
  menu_script_list,
  run_web_script,
  get_web_result,
  get_web_result_log,
  add_web_menu,
  del_web_menu,
  rename_web_menu,
  save_web_script,
  input_element,
  get_element_select,
} = useWebManagementApi()

// 数据表格加载页面动画
const route = useRoute()
const router = useRouter()

/** list：首页脚本表；script：单脚本编辑 */
const pageMode = ref<'list' | 'script'>('list')
const listPageTitle = 'Web 自动化脚本'

const loading = ref(false)
/** 仅在脚本编辑页左上角打开，用于切换脚本 */
const resourceDrawerVisible = ref(false)
const filterText = ref<any>('')
const treeRef = ref<InstanceType<typeof ElTree>>()
const tree_data = ref<any>()
const defaultProps = {
  children: 'children',
  label: 'name',
}

/** 接口可能返回单根对象或根数组，统一成数组再遍历 */
function normalizeMenuRoots(data: any): any[] {
  if (data == null) return []
  return Array.isArray(data) ? data : [data]
}

/** 拍平菜单树（节点上保留后端返回的 pid） */
function flattenWebMenuTree(nodes: any[] | any | undefined, out: any[] = []): any[] {
  const list = normalizeMenuRoots(nodes)
  for (const n of list) {
    if (!n) continue
    out.push(n)
    if (n.children?.length) flattenWebMenuTree(n.children, out)
  }
  return out
}

function isRootPid(pid: any): boolean {
  return pid === undefined || pid === null || pid === 0 || pid === '0'
}

function nodeByIdMap(flat: any[]): Map<any, any> {
  const m = new Map<any, any>()
  for (const n of flat) {
    if (n && n.id != null) {
      m.set(n.id, n)
      const num = Number(n.id)
      if (!Number.isNaN(num)) m.set(num, n)
    }
  }
  return m
}

function getMenuNode(m: Map<any, any>, pid: any): any {
  if (pid === undefined || pid === null) return undefined
  return m.get(pid) ?? m.get(Number(pid)) ?? m.get(String(pid))
}

/** 脚本库节点完整路径（用于新建脚本选父级） */
function fullPathForFolderNode(node: any, m: Map<any, any>): string {
  const chain: string[] = []
  let cur: any = node
  let guard = 0
  while (cur && guard++ < 64) {
    chain.unshift(cur.name)
    if (isRootPid(cur.pid)) break
    cur = getMenuNode(m, cur.pid)
  }
  return chain.filter(Boolean).join(' / ')
}

/** 根据节点计算状态标签文案 */
function statusLabelFor(n: any): string {
  if (n.status === false || n.enabled === false || n.disabled === true) return '停用'
  if (n.type === 1) return '目录'
  return '就绪'
}

/** 根据节点计算状态标签类型 */
function statusTagTypeFor(n: any): 'success' | 'info' | 'warning' | 'danger' {
  if (n.status === false || n.enabled === false || n.disabled === true) return 'danger'
  if (n.type === 1) return 'info'
  return 'success'
}

/** 把后端菜单树转换为首页树形表格数据。
 *  - type=0（历史文件夹/默认分组）作为透明容器：不显示为独立行，
 *    直接把它下面的脚本库/脚本提升到父级。
 *  - type=1（脚本库）和 type=2（脚本）保留并展示真实的从属关系。
 */
function buildResourceTree(nodes: any[]): any[] {
  const result: any[] = []
  for (const n of nodes || []) {
    if (!n) continue
    if (n.type === 0) {
      // 历史文件夹仅作为层级桥梁，子节点提升到当前层级
      if (n.children?.length) {
        result.push(...buildResourceTree(n.children))
      }
      continue
    }
    const children = n.children?.length ? buildResourceTree(n.children) : []
    result.push({ ...n, children })
  }
  return result
}

/** 首页列表：脚本库 + 脚本，以树形结构展示从属关系 */
const homeResourceTree = computed(() => buildResourceTree(tree_data.value))

/** 新建脚本：所有可作为父级的脚本库/脚本组 */
const folderParentOptions = computed(() => {
  const flat = flattenWebMenuTree(tree_data.value)
  const m = nodeByIdMap(flat)
  const opts: { label: string; value: number }[] = []
  for (const n of flat) {
    if (n.type !== 0 && n.type !== 1) continue
    opts.push({ label: fullPathForFolderNode(n, m), value: n.id })
  }
  return opts
})

const createResourceVisible = ref(false)
const createResourceSubmitting = ref(false)
/** resourceType：与树侧「新建子菜单」一致，1=脚本库，2=脚本 */
const createResourceForm = ref<{
  resourceType: 1 | 2
  name: string
  pid: number | undefined
}>({ resourceType: 2, name: '', pid: undefined })

const resetCreateResourceForm = () => {
  createResourceForm.value = { resourceType: 2, name: '', pid: undefined }
}

const openCreateResourceDialog = (kind: 'script' | 'folder') => {
  resetCreateResourceForm()
  createResourceForm.value.resourceType = kind === 'folder' ? 1 : 2
  const opts = folderParentOptions.value
  // 脚本库可建在根（无父级）；脚本必须挂在脚本库下，默认选中第一个可用父级
  createResourceForm.value.pid = opts.length ? opts[0].value : undefined
  createResourceVisible.value = true
}

const onCreateResourceTypeChange = () => {
  /* 切换类型时保留已选父级（仍在 options 内） */
}

function findNodeInTree(nodes: any[], id: number): any | null {
  for (const n of nodes || []) {
    if (n.id === id) return n
    if (n.children?.length) {
      const f = findNodeInTree(n.children, id)
      if (f) return f
    }
  }
  return null
}

/** 按 id 打开脚本编辑（列表 / 路由 / 新建后） */
const openScriptByIdFromApi = async (id: number) => {
  const node = findNodeInTree(tree_data.value, id)
  if (!node || node.type !== 2) {
    ElMessage.warning('未找到该脚本')
    return
  }
  loading.value = true
  try {
    const res: any = await get_web_script({ id })
    script_info.value = res.data.script[0]
    tab_list.value = []
    tab_active.value = ''
    await addTab(node, res.data)
    pageMode.value = 'script'
    await router.replace({ query: { ...route.query, scriptId: String(id) } })
  } catch {
    ElMessage.error('加载脚本失败')
  } finally {
    loading.value = false
  }
}

const goBackToList = () => {
  tab_list.value = []
  tab_active.value = ''
  pageMode.value = 'list'
  resourceDrawerVisible.value = false
  router.replace({ query: {} })
}

// 跳转到 Playwright 脚本录制页（仅展示 Playwright Codegen 导入）
const goPlaywrightRecorder = () => {
  router.push({ path: '/ai/ui-recorder', query: { engine: 'playwright' } })
}

const openScriptFromList = async (row: { id: number }) => {
  await openScriptByIdFromApi(row.id)
}

const openResourceFromList = async (row: { type: 1 | 2; id: number }) => {
  if (row.type === 2) await openScriptFromList(row)
  else await web_menu_click(row)
}

const onHomeResourceRowClick = (row: { type: 1 | 2; id: number }) => {
  openResourceFromList(row)
}

const deleteResourceFromList = (row: { id: number; name: string; type: 1 | 2 }) => {
  const kind = row.type === 2 ? '脚本' : '脚本库'
  ElMessageBox.confirm(`确定删除${kind}「${row.name}」吗？`, '提示', { type: 'warning' })
    .then(async () => {
      const res: any = await del_web_menu({ id: row.id, type: row.type })
      ElMessage.success(res.message || '已删除')
      if (pageMode.value === 'script' && tab_list.value[0]?.id === row.id) {
        goBackToList()
      }
      await get_web_menu()
    })
    .catch(() => {})
}

const submitCreateResource = async () => {
  const name = createResourceForm.value.name?.trim()
  if (!name) {
    ElMessage.warning(createResourceForm.value.resourceType === 2 ? '请输入脚本名称' : '请输入脚本库名称')
    return
  }
  // 脚本必须挂在脚本库下；脚本库允许建在根（pid 传 0）
  if (createResourceForm.value.resourceType === 2 && createResourceForm.value.pid == null) {
    ElMessage.warning('请选择父级位置（脚本须挂在脚本库下）')
    return
  }
  try {
    createResourceSubmitting.value = true
    const res: any = await add_web_menu({
      name,
      type: createResourceForm.value.resourceType,
      pid: createResourceForm.value.pid ?? 0,
    })
    ElMessage.success(res.message || '创建成功')
    createResourceVisible.value = false
    await get_web_menu()
    if (createResourceForm.value.resourceType === 2) {
      const newId = res.data?.id
      if (newId) await openScriptByIdFromApi(Number(newId))
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '创建失败')
  } finally {
    createResourceSubmitting.value = false
  }
}

// 当前页面的脚本数据 — 始终指向当前激活 tab 的 script 数组
const script_list = computed<any[]>(() => {
  const active = tab_list.value.find((t: any) => t.name === tab_active.value)
  return active?.content?.script ?? []
})
const script_info = ref<any>({
  name: '',
  type: 0,
  status: true,
  children: [],
  action: {
    type: 1,
    locator: 1,
    locator_select: 1,
    target_locator: 1,
    target_locator_select: 1,
    target_type: 1,
    up_type: 1,
    sway_type: 1,
    before_wait: 1,
    after_wait: 1,
    timeout: 15,
    input: '',
    element: '',
    target: '',
    assert: [],
    cookies: [],
    localstorage: [],
    role: 'button',
    element_id: null,
    target_id: '',
  },
})
const table_list = ref<any>([])
const tab_active = ref('')
const tab_list = ref<any>([])
const add_menu_form = ref<any>({})
const icon_style = ref<any>('padding-right: 5px; padding-left: 5px; padding-top: 4px;')
const locator_list = ref<any>([
  { name: '定位器', value: 1 },
  { name: '选择器', value: 2 },
])
const locator_selects = ref<any>([
  { label: 'id', value: 1 },
  { label: 'text', value: 2 },
  { label: 'label', value: 3 },
  { label: 'title', value: 4 },
  { label: 'placeholder', value: 5 },
  { label: 'alt', value: 6 },
  { label: 'role', value: 7 },
])
const role_list = ref<any>([
  { label: 'button', value: 'button' },
  { label: 'link', value: 'link' },
  { label: 'tab', value: 'tab' },
  { label: 'tabpanel', value: 'tabpanel' },
  { label: 'textbox', value: 'textbox' },
  { label: 'checkbox', value: 'checkbox' },
  { label: 'radio', value: 'radio' },
  { label: 'combobox', value: 'combobox' },
  { label: 'listbox', value: 'listbox' },
  { label: 'menu', value: 'menu' },
  { label: 'menuitem', value: 'menuitem' },
  { label: 'alert', value: 'alert' },
  { label: 'status', value: 'status' },
  { label: 'progressbar', value: 'progressbar' },
  { label: 'spinbutton', value: 'spinbutton' },
  { label: 'heading', value: 'heading' },
  { label: 'tree', value: 'tree' },
  { label: 'treeitem', value: 'treeitem' },
])
const browser_list = ref<any>([
  { name: 'Chrome', value: 1 },
  { name: 'Firefox', value: 2 },
  { name: 'Edge', value: 3 },
  { name: 'Safari', value: 4 },
])

// web目录过滤
watch(filterText, (val) => {
  treeRef.value?.filter(val)
})

const filterNode = (value: string, data: any): boolean => {
  if (!value) return true
  return data.name.includes(value)
}

const element_select_change = (selection: any) => {
  console.log(selection)
}

const get_web_menu = async () => {
  try {
    loading.value = true
    const res: any = await web_menu({})
    tree_data.value = res.data
  } catch {
    ElMessage.error('数据查询失败，请刷新重试')
  } finally {
    loading.value = false
  }
}

const web_menu_click = async (node: any) => {
  try {
    if (node.type === 1) {
      const res: any = await menu_script_list({ id: node.id })
      table_list.value = (res.data || []).map((item: any) => ({
        ...item,
        step: item.step == null || item.step === 0 ? 1 : item.step,
      }))
      if (pageMode.value === 'script') {
        tab_list.value = []
        tab_active.value = ''
      }
      await addTab(node, res.data)
      pageMode.value = 'script'
      const q = { ...route.query } as Record<string, any>
      delete q.scriptId
      await router.replace({ query: q })
      resourceDrawerVisible.value = false
    } else if (node.type === 2) {
      if (pageMode.value === 'script') {
        tab_list.value = []
        tab_active.value = ''
      }
      const res: any = await get_web_script({ id: node.id })
      script_info.value = res.data.script[0]
      await addTab(node, res.data)
      pageMode.value = 'script'
      await router.replace({ query: { ...route.query, scriptId: String(node.id) } })
      resourceDrawerVisible.value = false
    }
  } catch {
    ElMessage.error('数据查询失败，请刷新重试')
  }
}

const addTab = async (node: any, target: any) => {
  const newTabName = node.name
  const index = tab_list.value.findIndex((item: any) => item.title === newTabName)
  if (index === -1) {
    tab_list.value.push({
      title: newTabName,
      name: newTabName,
      content: target,
      id: node.id,
      type: node.type,
    })
  }
  tab_active.value = node.name
}

const removeTab = (targetName: string) => {
  const tabs = tab_list.value
  let activeName = tab_active.value
  if (activeName === targetName) {
    tab_list.value.forEach((tab: any, index: any) => {
      if (tab.name === targetName) {
        const nextTab = tabs[index + 1] || tabs[index - 1]
        if (nextTab) {
          activeName = nextTab.name
        }
      }
    })
  }
  tab_active.value = activeName
  tab_list.value = tabs.filter((tab: any) => tab.name !== targetName)
}

const select_list = ref<any>([])
const handleSelectionChange = (selection: any) => {
  select_list.value = selection.sort((a: any, b: any) => a.step - b.step)
}

const menu_form = ref<any>({
  name: '',
  id: null,
})
const title = ref<string>('')
const add_ntestercDialogRef = ref<InstanceType<typeof NtestercDialog> | null>(null)
const rename_ntestercDialogRef = ref<InstanceType<typeof NtestercDialog> | null>(null)

const add_menu = (data: any) => {
  title.value = '新增子菜单'
  add_ntestercDialogRef.value?.ntestercOpen()
  menu_form.value = data
}

const check_children = (data: any, menu: any) => {
  if ('children' in data) {
    data.children.push(menu)
  } else {
    data.children = []
    data.children.push(menu)
  }
}

const add_menu_confirm = async () => {
  try {
    add_menu_form.value.pid = menu_form.value.id
    const res: any = await add_web_menu(add_menu_form.value)
    await check_children(menu_form.value, res.data)
    add_ntestercDialogRef.value?.ntestercQuickClose(res.message)
  } catch {
    ElMessage.error('保存失败，请重试')
  } finally {
    add_menu_form.value = {}
  }
}

const add_menu_cancel = () => {
  add_ntestercDialogRef.value?.ntestercClose()
}

const rename_menu = (data: any) => {
  title.value = '重命名'
  rename_ntestercDialogRef.value?.ntestercOpen()
  menu_form.value = data
}

const edit_menu_confirm = async () => {
  try {
    add_menu_form.value.id = menu_form.value.id
    const res: any = await rename_web_menu(add_menu_form.value)
    rename_ntestercDialogRef.value?.ntestercQuickClose(res.message)
    menu_form.value.name = add_menu_form.value.name
  } catch {
    ElMessage.error('保存失败，请重试')
  } finally {
    add_menu_form.value = {}
  }
}

const edit_menu_cancel = () => {
  rename_ntestercDialogRef.value?.ntestercClose()
}

const on_menu_allowDrop = (moveNode: any, inNode: any, type: any) => {
  console.log(moveNode)
  if (inNode.data.type === 2) {
    return type !== 'inner'
  }
  return type
}

const del_menu = (data: any) => {
  ElMessageBox.confirm('您确认需要删除该目录么？', '提示', {
    type: 'warning',
  })
    .then(async () => {
      const res: any = await del_web_menu({ id: data.id, type: data.type })
      ElMessage.success(res.message || '删除成功')
      await get_web_menu()
    })
    .catch(() => {})
}

const step_style = (type: any) => {
  if (type === 0) {
    return 'border: 1px solid #3e7be5; border-radius: 5px; width: 93%; color: #3e7be5'
  } else if (type === 1 || type === 2 || type === 3 || type === 4) {
    return 'border: 1px solid #400ae6; border-radius: 5px; width: 93%; color: #400ae6'
  } else if (type === 5 || type === 6 || type === 7) {
    return 'border: 1px solid #ee4866; border-radius: 5px; width: 93%; color: #ee4866'
  } else if (type === 8 || type === 9) {
    return 'border: 1px solid #e99516; border-radius: 5px; width: 93%; color: #e99516'
  } else if (type === 10 || type === 11) {
    return 'border: 1px solid #ea035f; border-radius: 5px; width: 93%; color: #ea035f'
  } else if (type === 12) {
    return 'border: 1px solid #20a162; border-radius: 5px; width: 93%; color: #20a162'
  }
  return 'border: 1px solid #3e7be5; border-radius: 5px; width: 93%; color: #3e7be5'
}

const random_string = (data_length: any) => {
  return Array.from(crypto.getRandomValues(new Uint8Array(data_length)))
    .map((n) => n.toString(36))
    .join('')
}

// 自动化脚本：新增步骤
const add_script = (command: any) => {
  const active = tab_list.value.find((t: any) => t.name === tab_active.value)
  if (!active?.content?.script) return
  const new_string = random_string(2)
  active.content.script.push({
    name: `${command.name}-${new_string}`,
    type: command.type,
    status: true,
    children: [],
    action: {
      type: 1,
      locator: 1,
      locator_select: 1,
      target_locator: 1,
      target_locator_select: 1,
      input: '',
      element: '',
      element_id: null,
      target: '',
      target_id: '',
      target_type: 1,
      assert: [],
      up_type: 1,
      sway_type: 1,
      wait_time: 1,
      before_wait: 1,
      after_wait: 1,
      role: 'button',
      cookies: [],
      localstorage: [],
      timeout: 15,
    },
  })
}

const config_active = ref('first')
const assert_list = ref<any>([
  { name: '元素存在', value: 1 },
  { name: '元素不存在', value: 2 },
  { name: '文本存在', value: 3 },
  { name: '文本不存在', value: 4 },
  { name: '页面属性', value: 5 },
  { name: '自定义断言', value: 6 },
  { name: 'AI 断言', value: 7 },
])
const browser_assert = ref<any>([
  { name: '网页地址', value: 1 },
  { name: '网页标题', value: 2 },
])

const add_assert = (data: any) => {
  data.push({
    type: 1,
    locator: 1,
    locator_select: 1,
    page_type: 1,
    element: '',
    role: 'button',
  })
}

const add_cookie = (data: any) => {
  data.push({
    name: '',
    value: '',
  })
}

const del_cookie = (data: any, index: any) => {
  data.splice(index, 1)
}

const add_localstorage = (data: any) => {
  data.push({
    name: '',
    value: '',
  })
}

const del_localstorage = (data: any, index: any) => {
  data.splice(index, 1)
}

const del_assert = (data: any, index: any) => {
  data.splice(index, 1)
}

const web_script_click = (node: any) => {

  if (!node.action) node.action = {}
  const action = node.action

  action.type ??= 1
  action.locator ??= 1
  action.locator_select ??= 1
  action.target_locator ??= 1
  action.target_locator_select ??= 1
  action.target_type ??= 1
  action.up_type ??= 1
  action.sway_type ??= 1
  action.before_wait ??= 1
  action.after_wait ??= 1
  action.timeout ??= 15
  action.input ??= ''
  action.element ??= ''
  action.target ??= ''
  action.role ??= 'button'
  action.element_id ??= null
  action.target_id ??= ''

  if (!Array.isArray(action.assert)) action.assert = []
  if (!Array.isArray(action.cookies)) action.cookies = []
  if (!Array.isArray(action.localstorage)) action.localstorage = []

  script_info.value = node
}

// 顶部「AI 脚本录入」：与下拉「AI 步骤」一并暂注释，仅保留自定义步骤
// const ai_script_input = () => {
//   add_script({ type: 19, name: 'AI 步骤' })
//   const last = script_list.value?.[script_list.value.length - 1]
//   if (last) web_script_click(last)
//   ElMessage.success('已添加 AI 步骤，请在右侧填写脚本内容')
// }

const save_web_script_handler = async (id: any) => {
  const res: any = await save_web_script({
    id,
    script: script_list.value,
  })
  if (res.code === 200) {
    ElMessage.success(res.message || '保存成功')
  } else {
    ElMessage.error(res.message || '保存失败，请重试')
  }
}

const Delete_row = (list: any, data: any) => {
  list.forEach((item: any, index: any) => {
    if (item.name === data.name) {
      list.splice(index, 1)
    } else if (item.children.length > 0) {
      Delete_row(item.children, data)
    }
  })
  return false
}

const copy_row = (list: any, data: any) => {
  const new_string = 'copy'
  const new_data = {
    name: `${data.name}-${new_string}`,
    type: data.type,
    status: true,
    children: [],
    action: data.action,
  }
  list.push(new_data)
}

const element_select_list = ref<any>([])
const element_select = async () => {
  const res: any = await get_element_select({})
  element_select_list.value = res.data
}

const file_name = ref<any>(null)
const file_url = ref<any>(null)
const upload_ntestercDialogRef = ref<InstanceType<typeof NtestercDialog> | null>(null)

const call_back = (fileMap: any) => {
  ElMessage.success('上传文件成功（占位实现）')
  file_url.value = fileMap.file_url
  file_name.value = fileMap.filename
}

const file_script_path = ref<any>('')
const call_back_1 = (fileMap: any) => {
  file_script_path.value = `${fileMap.file_url}/${fileMap.filename}`
}

const add_file = (action: any) => {
  action.input = file_script_path.value
}

const pid = ref<any>(null)
const upload_file = (data: any) => {
  pid.value = data.id
  upload_ntestercDialogRef.value?.ntestercOpen()
  title.value = '上传文件'
}

const upload_file_confirm = async () => {
  const res: any = await input_element({
    file_url: file_url.value,
    file_name: file_name.value,
    pid: pid.value,
  })
  if (res.code === 200) {
    upload_ntestercDialogRef.value?.ntestercQuickClose(res.message || '上传成功')
    await get_web_menu()
  } else {
    ElMessage.error('上传失败，请重试')
  }
}

const upload_file_cancel = () => {
  upload_ntestercDialogRef.value?.ntestercQuickClose('取消上传')
}

const run_script_form = ref<any>({
  task_name: '',
  browser: [],
  script: [],
  width: 1920,
  height: 1080,
  browser_type: 1,
})
const run_ntestercDialogRef = ref<InstanceType<typeof NtestercDialog> | null>(null)
const result_id = ref<any>('')

const run_script = (item: any) => {
  run_script_form.value.script = []
  run_ntestercDialogRef.value?.ntestercOpen()
  title.value = '请配置调试信息'
  const script = {
    id: item.id,
    name: item.name,
    type: item.type,
  }
  run_script_form.value.script.push(script)
}

const run_browsers = ref<any>([])
const run_browser_active = ref<any>('')
const runMonitorDrawerVisible = ref(false)

const onRunMonitorDrawerClosed = () => {
  stopPolling()
}

const run_script_confirm = async () => {
  if (run_script_form.value.script.length === 0) {
    ElMessage.error('请选择脚本')
    return
  }
  if (!run_script_form.value.task_name) {
    ElMessage.error('请输入任务名称')
    return
  }
  if (run_script_form.value.browser.length === 0) {
    ElMessage.error('请选择浏览器')
    return
  }
  if (run_script_form.value.browser.length > 1) {
    ElMessage.error('抱歉，由于资源有限，单次仅支持一个浏览器执行')
    return
  }

  run_browsers.value = []
  result_id.value = String(Date.now())
  run_script_form.value.result_id = result_id.value
  await run_browser_show()
  run_browser_active.value = run_script_form.value.browser[0]
  title.value = `正在执行：${run_script_form.value.task_name}`
  runMonitorDrawerVisible.value = true
  await startPolling()
  const res: any = await run_web_script(run_script_form.value)
  if (res.code === 10001) {
    ElMessage.error(res.message || '执行失败')
    runMonitorDrawerVisible.value = false
    stopPolling()
  }
}

const run_browser_show = () => {
  run_browsers.value = []
  run_script_form.value.browser.forEach((item: any) => {
    browser_list.value.forEach((browser: any) => {
      if (browser.value === item) {
        run_browsers.value.push({
          name: browser.name,
          value: browser.value,
        })
      }
    })
  })
}

const interval = ref<any>(null)

const startPolling = async () => {
  if (interval.value) return
  interval.value = setInterval(get_run_result, 2000)
}

const stopPolling = () => {
  if (interval.value) {
    clearInterval(interval.value)
    interval.value = null
  }
}

const change_browser = async () => {
  loading.value = true
  await startPolling()
  loading.value = false
}

const get_run_result = async () => {
  run_type.value = '正在执行'
  await get_result()
  await get_result_log()
}

const web_result = ref<any>([])
const web_result_log = ref<any>([])
const run_type = ref<any>('')
const run_count = ref<any>(0)
const run_fail = ref<any>(0)
const start_time = ref<any>('')
const end_time = ref<any>('')
const pre_video = ref<any>('')
const img_show = ref<any>(false)
const pre_img = ref<any>('')
const trace = ref<any>('')

const formatTime = (t: string) => t ? t.replace('T', ' ').slice(0, 19) : '-'

const get_result = async () => {
  const res: any = await get_web_result({
    result_id: result_id.value,
    browser: run_browser_active.value,
  })
  web_result.value = res.data
  run_count.value = web_result.value.length
  if (web_result.value.length > 0) {
    start_time.value = formatTime(web_result.value[web_result.value.length - 1].create_time)
  }
  let fail = 0
  web_result.value.forEach((item: any) => {
    if (item.status === 0) {
      fail += 1
    }
    if (item.name === '执行结束') {
      stopPolling()
      run_count.value -= 1
      run_type.value = '执行结束'
      end_time.value = formatTime(item.create_time)
      pre_video.value = item.video
      trace.value = item.trace
    }
  })
  run_fail.value = fail
}

const get_result_log = async () => {
  const res: any = await get_web_result_log({
    result_id: result_id.value,
    browser: run_browser_active.value,
  })
  web_result_log.value = res.data
}

const getIcon = (status: any) => (status === 1 ? 'Check' : 'Close')
const colors = (status: any) => (status === 1 ? '#0bbd87' : '#d70e0e')

const copyWebResultLog = async () => {
  const lines = web_result_log.value
  const text = Array.isArray(lines) ? lines.join('\n') : ''
  if (!text.trim()) {
    ElMessage.info('暂无日志可复制')
    return
  }
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.warning('复制失败，请手动选择日志文本')
  }
}

const pre_view = (img: any) => {
  pre_img.value = [img]
  img_show.value = true
}

const close_img = () => {
  img_show.value = false
}

const view_video = () => {
  if (pre_video.value) window.open(pre_video.value)
}

const run_script_cancel = () => {
  run_ntestercDialogRef.value?.ntestercQuickClose('取消调试')
}

const batch_run_script = () => {
  run_script_form.value.script = []
  run_ntestercDialogRef.value?.ntestercOpen()
  title.value = '请配置调试信息'
  run_script_form.value.script = select_list.value
}

const download_report = () => {
  if (trace.value) window.open(trace.value)
  view_trace()
}

const view_trace = () => {
  window.open('https://trace.playwright.dev/')
}

watch(
  () => route.query.scriptId,
  (sid) => {
    const empty = sid === undefined || sid === null || sid === ''
    if (empty && pageMode.value === 'script') {
      tab_list.value = []
      tab_active.value = ''
      pageMode.value = 'list'
      resourceDrawerVisible.value = false
    }
  }
)

onMounted(async () => {
  await get_web_menu()
  await element_select()
  const raw = route.query.scriptId
  const sid = Array.isArray(raw) ? raw[0] : raw
  if (sid) {
    await openScriptByIdFromApi(Number(sid))
  }
})
</script>



<style lang="scss" scoped>
/* 遵循 Element Plus 语义色（--el-*），适配亮色 / 深色模式 */
.web-automation-page {
  --wa-gap: 12px;
  box-sizing: border-box;
  min-height: calc(100vh - 88px);
  background-color: var(--el-bg-color-page);
}

.wa-container {
  min-height: calc(100vh - 88px);
  background-color: var(--el-bg-color-page);
}

/* 避免嵌套的 el-main 使用默认浅色底，与布局深色区脱节 */
.web-automation-page :deep(.el-main.wa-main) {
  background-color: var(--el-bg-color-page) !important;
}

.wa-page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  margin: 0;
  height: auto !important;
  border-bottom: 1px solid var(--el-border-color-lighter);
  background-color: var(--el-bg-color);
  box-sizing: border-box;
}

.wa-header-row {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.wa-main {
  padding: 12px 16px 20px;
  box-sizing: border-box;
  overflow: auto;
  background-color: var(--el-bg-color-page);
}

.wa-home-list {
  width: 100%;
  min-height: 320px;
  background-color: var(--el-bg-color-page);
}

.wa-list-card {
  --el-card-bg-color: var(--el-bg-color);
  border-color: var(--el-border-color-lighter);
  background-color: var(--el-bg-color);
  color: var(--el-text-color-primary);
}

.wa-list-card :deep(.el-card__body) {
  padding: 16px;
  background-color: var(--el-bg-color);
  color: var(--el-text-color-primary);
}

.wa-home-list :deep(.el-table__row) {
  cursor: pointer;
}

/* 首页表格：背景、表头、斑马行均走 Element Plus 变量，深色模式一致 */
.wa-script-table {
  --el-table-bg-color: var(--el-bg-color);
  --el-table-tr-bg-color: var(--el-bg-color);
  --el-table-header-bg-color: var(--el-fill-color-light);
  --el-table-header-text-color: var(--el-text-color-regular);
  --el-table-text-color: var(--el-text-color-primary);
  --el-table-border-color: var(--el-border-color-lighter);
  --el-table-row-hover-bg-color: var(--el-fill-color-light);
}
.wa-script-table :deep(.el-table__inner-wrapper::before) {
  background-color: var(--el-border-color-lighter);
}
.wa-script-table :deep(.el-table__body tr.el-table__row--striped > td.el-table__cell) {
  background-color: var(--el-fill-color-lighter);
}

/*
 * EP 表格 fixed 列在表体底部会插入 .el-table__fixed-right-patch，theme-chalk 里写死 background:#fff，
 * 深色模式下会出现表格下方一条浅色带，改为跟随页面/表格背景。
 */
.wa-script-table :deep(.el-table__fixed-right-patch) {
  background-color: var(--el-table-bg-color, var(--el-bg-color)) !important;
}

.wa-table-actions {
  justify-content: center;
}

.wa-res-icon {
  font-size: 18px;
  flex-shrink: 0;
}
.wa-res-icon--folder {
  color: var(--el-color-warning);
}
.wa-res-icon--script {
  color: var(--el-color-primary);
}

.wa-drawer-search {
  margin-bottom: 12px;
}

.wa-tree-icon {
  margin-right: 6px;
  vertical-align: middle;
}

.tree-more-trigger {
  cursor: pointer;
  color: var(--el-text-color-secondary);
}

.tree-more-trigger:hover {
  color: var(--el-color-primary);
}

.tree-node-actions {
  padding-right: 2px;
  opacity: 0.85;
}

/* —— 主工作区 —— */
.web-automation-workspace {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.workspace-shell {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-radius: var(--el-border-radius-base);
  background-color: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
}

.workspace-inner {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 0 4px 8px;
}

.web-script-tabs {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 0 8px 4px;
}

.web-script-tabs--underline :deep(.el-tabs__header) {
  margin: 0;
  border-bottom: none;
  background: transparent;
}

.web-script-tabs--underline :deep(.el-tabs__nav-wrap::after) {
  display: none;
}

.web-script-tabs--underline :deep(.el-tabs__item) {
  font-weight: 600;
  font-size: 14px;
  padding: 0 18px;
  height: 44px;
  line-height: 44px;
  color: var(--el-text-color-secondary);
  border: none;
  transition: color 0.2s;
}

.web-script-tabs--underline :deep(.el-tabs__item.is-active) {
  color: var(--el-color-primary);
}

.web-script-tabs--underline :deep(.el-tabs__active-bar) {
  height: 3px;
  border-radius: 3px 3px 0 0;
}

.web-script-tabs :deep(.el-tabs__content) {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  padding-top: 8px;
}

.web-script-tabs :deep(.el-tab-pane) {
  height: 100%;
}

/* 单脚本：卡片 + 上下分栏 */
.script-tab-root {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: var(--wa-gap);
  box-sizing: border-box;
}

.wa-hero-card,
.wa-ribbon-card {
  flex-shrink: 0;
}

.wa-hero-card :deep(.el-card__body) {
  padding: 16px 18px;
}

.wa-ribbon-card :deep(.el-card__body) {
  padding: 12px 14px;
}

.workspace-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.hero-left {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  min-width: 0;
  flex: 1;
}

.hero-icon-wrap {
  width: 44px;
  height: 44px;
  border-radius: var(--el-border-radius-base);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: var(--el-color-white);
  background-color: var(--el-color-primary);
  font-size: 22px;
}

.hero-text {
  min-width: 0;
}

.hero-title {
  margin: 0 0 8px;
  font-size: var(--el-font-size-large);
  font-weight: 600;
  color: var(--el-text-color-primary);
  line-height: 1.35;
}

.hero-meta-line {
  margin: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.hero-meta-sep {
  opacity: 0.65;
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  flex-shrink: 0;
}

.step-ribbon {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.ribbon-label {
  flex-shrink: 0;
  font-weight: 600;
}

.ribbon-scroll {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  flex: 1;
  min-width: 0;
}

.toolbar-dd-btn {
  font-weight: 500;
}

/* 添加步骤下拉触发：分类高级色（实心），与 EP 主题变量协同 */
.wa-step-dd--custom.el-button {
  --el-button-text-color: var(--el-color-white);
  --el-button-bg-color: #7c3aed;
  --el-button-border-color: #6d28d9;
  --el-button-hover-text-color: var(--el-color-white);
  --el-button-hover-bg-color: #6d28d9;
  --el-button-hover-border-color: #5b21b6;
  --el-button-active-text-color: var(--el-color-white);
  --el-button-active-bg-color: #5b21b6;
  --el-button-active-border-color: #4c1d95;
}

.wa-step-dd--logic.el-button {
  --el-button-text-color: var(--el-color-white);
  --el-button-bg-color: #0d9488;
  --el-button-border-color: #0f766e;
  --el-button-hover-text-color: var(--el-color-white);
  --el-button-hover-bg-color: #0f766e;
  --el-button-hover-border-color: #115e59;
  --el-button-active-text-color: var(--el-color-white);
  --el-button-active-bg-color: #115e59;
  --el-button-active-border-color: #134e4a;
}

[data-theme='dark'] .wa-step-dd--custom.el-button {
  --el-button-bg-color: #8b5cf6;
  --el-button-border-color: #7c3aed;
  --el-button-hover-bg-color: #7c3aed;
  --el-button-hover-border-color: #6d28d9;
  --el-button-active-bg-color: #6d28d9;
  --el-button-active-border-color: #5b21b6;
}

[data-theme='dark'] .wa-step-dd--logic.el-button {
  --el-button-bg-color: #14b8a6;
  --el-button-border-color: #0d9488;
  --el-button-hover-bg-color: #0d9488;
  --el-button-hover-border-color: #0f766e;
  --el-button-active-bg-color: #0f766e;
  --el-button-active-border-color: #115e59;
}

.workspace-canvas--stacked {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: var(--wa-gap);
}

.step-rail-card {
  flex: 0 1 auto;
  max-height: min(42vh, 420px);
  min-height: 160px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.step-rail-card :deep(.el-card__body) {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  padding: 0;
}

.step-inspector-card {
  flex: 1;
  min-height: 200px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.step-inspector-card :deep(.el-card__body) {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  padding: 0;
}

.step-tree-inner {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 12px;
}

.step-config-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 4px 16px 16px;
}

.web-config-tabs :deep(.el-tabs__header) {
  margin-bottom: 0;
}

.web-config-tabs :deep(.el-tabs__nav-wrap::after) {
  height: 1px;
  background-color: var(--el-border-color-lighter);
}

.step-tree :deep(.el-tree-node__content) {
  height: auto;
  margin-bottom: 4px;
  padding: 0;
  min-height: 0;
}

.step-tree :deep(.el-tree-node) {
  margin-bottom: 2px;
}

.step-card {
  border-radius: var(--el-border-radius-base);
  margin-bottom: 6px;
  width: 100%;
  border-color: var(--el-border-color);
  background-color: var(--el-fill-color-blank);
}

.step-card:hover {
  border-color: var(--el-color-primary-light-5);
}

.step-card :deep(.el-card__body) {
  padding: 6px 10px;
  line-height: 1.45;
}

.card-header {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 30px;
}

.card-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
  overflow: hidden;
}

.method-tag {
  font-size: 13px;
  color: var(--el-color-primary);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.step-icon {
  display: inline-flex;
  justify-content: center;
  align-items: center;
  width: 22px;
  height: 22px;
  font-size: 11px;
  font-weight: 700;
  border-radius: var(--el-border-radius-small);
  background-color: var(--el-color-primary-light-9);
  border: 1px solid var(--el-color-primary-light-5);
  color: var(--el-color-primary);
  flex-shrink: 0;
}

.card-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.action-button {
  padding: 4px;
}

.custom-tree-node {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  padding-right: 2px;
  color: var(--el-text-color-primary);
}

.folder-tab-panel {
  padding: 4px 0 0;
  height: 100%;
  min-height: 0;
  box-sizing: border-box;
}

.folder-batch-card {
  min-height: min(680px, calc(100vh - 200px));
  border-color: var(--el-border-color-lighter);
  background-color: var(--el-bg-color);
}

.folder-batch-card :deep(.el-card__body) {
  height: 100%;
}

@media (max-width: 768px) {
  .workspace-hero {
    flex-direction: column;
  }
}
</style>

<style lang="scss">
@import '@/theme/modules/web-run-monitor.scss';
</style>

