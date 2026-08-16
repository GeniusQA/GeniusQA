<template>
	<div class="manage-panel">
		<!-- 主体：左侧接口树 + 右侧详情 -->
		<div class="manage-body">
			<!-- 左侧接口树 -->
			<div class="tree-panel">
				<div class="tree-actions">
					<el-input v-model="treeFilter" placeholder="搜索接口" clearable size="small" style="flex:1" />
					<el-dropdown @command="handleAddCommand" style="margin-left:6px">
						<el-button type="primary" size="small">添加<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
						<template #dropdown>
							<el-dropdown-menu>
								<el-dropdown-item command="add_module">添加模块</el-dropdown-item>
								<el-dropdown-item command="add_folder">添加目录</el-dropdown-item>
								<el-dropdown-item command="add_api">添加接口</el-dropdown-item>
								<el-dropdown-item command="add_data_model">新建数据模型</el-dropdown-item>
								<el-dropdown-item command="import_api">导入接口</el-dropdown-item>
							</el-dropdown-menu>
						</template>
					</el-dropdown>
				</div>
				<div v-if="treeCheckedKeys.length" class="tree-batch-bar">
					<span class="batch-count">已选 {{ treeCheckedKeys.length }} 项</span>
					<el-dropdown @command="treeCheckAllByMode" size="small">
						<el-button link type="primary" size="small">全选<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
						<template #dropdown>
							<el-dropdown-menu>
								<el-dropdown-item command="dir">全选目录</el-dropdown-item>
								<el-dropdown-item command="api">全选接口</el-dropdown-item>
								<el-dropdown-item command="all">全选全部</el-dropdown-item>
							</el-dropdown-menu>
						</template>
					</el-dropdown>
					<el-button link size="small" @click="treeCheckClear">清空</el-button>
					<el-button type="danger" size="small" class="batch-delete-btn" :loading="treeDeleting" @click="treeBatchDelete">{{ treeDeleting ? `删除中 ${treeDeleteProgress}/${treeCheckedKeys.length}` : '删除选中' }}</el-button>
				</div>
				<el-tree
					ref="treeRef"
					:data="treeData"
					:props="{ children: 'children', label: 'name' }"
					node-key="id"
					:filter-node-method="filterNode"
					show-checkbox
					check-strictly
					:check-on-click-leaf="false"
					@check="onTreeCheck"
					draggable
					:allow-drop="allowDrop"
					class="api-tree"
					@node-click="onNodeClick"
					@node-drop="handleNodeDrop"
					empty-text="暂无模块，点击「添加 → 添加模块」创建"
				>
					<template #default="{ data }">
						<div class="tree-node">
							<div class="node-left">
								<el-icon v-if="data.type===0" class="icon-folder" style="color:#7c3aed"><Grid /></el-icon>
								<el-icon v-else-if="data.type===1" :class="data.name==='数据模型' ? 'icon-dm' : 'icon-folder'"><Box v-if="data.name==='数据模型'" /><FolderOpened v-else /></el-icon>
					<el-icon v-else-if="data.type===4" class="icon-dm"><Box /></el-icon>
								<el-icon v-else-if="data.type===5" class="icon-folder" style="color:#7c3aed"><Grid /></el-icon>
								<el-icon v-else-if="data.type===3" class="icon-case"><Link /></el-icon>
								<span v-if="(data.type===2||data.type===3) && data.protocol !== 'websocket' && data.protocol !== 'socketio' && data.protocol !== 'webhook'" class="method-badge" :style="{background: methodColor(data.method)}">{{ methodLabel(data.method) }}</span>
								<span v-if="data.type===2 && (data.protocol==='websocket' || data.protocol==='socketio')" class="proto-badge proto-ws">WS</span>
								<span v-else-if="data.type===2 && data.protocol==='webhook'" class="proto-badge proto-wh">WH</span>
								<span class="node-name">{{ data.name }}</span>
							</div>
							<el-dropdown trigger="click" @command="(cmd) => handleNodeCommand(cmd, data)" @click.stop>
								<el-icon class="node-more"><MoreFilled /></el-icon>
								<template #dropdown>
									<el-dropdown-menu>
										<el-dropdown-item v-if="data.type===0" command="add_folder">添加目录</el-dropdown-item>
										<el-dropdown-item v-if="data.type===1" command="add_folder">添加子目录</el-dropdown-item>
										<el-dropdown-item v-if="data.type===1" command="add_api">添加接口</el-dropdown-item>
										<el-dropdown-item v-if="data.type===1" command="menu_params">目录参数</el-dropdown-item>
										<el-dropdown-item v-if="data.type===2" command="copy">复制接口</el-dropdown-item>
										<el-dropdown-item v-if="data.type===0" command="menu_params">目录参数</el-dropdown-item>
										<el-dropdown-item v-if="!(data.type===1 && data.name==='接口')" command="rename">重命名</el-dropdown-item>
										<el-dropdown-item v-if="!(data.type===1 && data.name==='接口')" command="delete" divided>删除</el-dropdown-item>
									</el-dropdown-menu>
								</template>
							</el-dropdown>
						</div>
					</template>
				</el-tree>
			</div>

			<!-- 右侧接口详情 -->
			<div class="detail-panel">
				<div v-if="selectedModule && !apiTabs.length" class="module-detail">
					<div class="module-detail-head">
						<h3 class="module-detail-title">{{ selectedModule.name }}</h3>
						<el-button type="primary" size="small" @click="saveModuleVars">保存</el-button>
					</div>
					<el-tabs v-model="moduleDetailTab" class="module-detail-tabs">
						<el-tab-pane label="概览" name="overview">
							<div class="md-stats">
								<div class="md-stat-card"><div class="md-stat-num">{{ moduleStats.apiCount }}</div><div class="md-stat-label">接口数</div></div>
								<div class="md-stat-card"><div class="md-stat-num">{{ moduleStats.caseCount }}</div><div class="md-stat-label">用例数</div></div>
								<div class="md-stat-card"><div class="md-stat-num">{{ moduleStats.dirCount }}</div><div class="md-stat-label">目录数</div></div>
							</div>
							<div class="md-section">
								<div class="md-section-head">
									<span class="md-section-title">绑定数据源</span>
									<el-button link type="primary" size="small" @click="openBindDs">{{ bindDsExisting?.url ? '编辑数据源' : '+ 添加数据源' }}</el-button>
								</div>
								<div v-if="bindDsExisting?.url" class="md-source-item">
									<span class="md-source-logo">{{ dsNameLetter }}</span>
									<div class="md-source-info">
										<div class="md-source-name">{{ bindDsExisting.name || moduleSource.source_addr || '数据源' }}</div>
										<div class="md-source-meta">{{ sourceTypeLabel(moduleSource.source_type) }} · {{ freqLabel(bindDsExisting.frequency) }}</div>
									</div>
									<el-button link type="primary" size="small" @click="openBindDs">编辑</el-button>
									<el-button link type="primary" size="small" @click="syncBoundDs" :loading="dsSyncing">立即导入</el-button>
								</div>
								<div v-else class="md-source-empty">尚未绑定数据源，点击「+ 添加数据源」配置数据源（支持定时自动同步更新接口）</div>
							</div>
						</el-tab-pane>
						<el-tab-pane label="模块变量" name="vars">
							<div class="md-vars-head">
								<span>变量名</span>
								<span>远程值</span>
								<span>本地值</span>
								<span style="width: 50px"></span>
							</div>
							<div v-for="(v, i) in moduleVars" :key="i" class="md-vars-row">
								<el-input v-model="v.key" placeholder="添加变量" size="small" />
								<el-input v-model="v.remote" placeholder="远程值" size="small" />
								<el-input v-model="v.local" placeholder="跟随远程值" size="small" />
								<el-button type="danger" link size="small" @click="moduleVars.splice(i, 1)">删除</el-button>
							</div>
							<div class="md-vars-actions">
								<el-button type="primary" link size="small" @click="moduleVars.push({ key: '', remote: '', local: '' })">+ 添加变量</el-button>
								<el-button type="primary" link size="small" @click="openModuleVarsBulk">批量编辑</el-button>
							</div>
						</el-tab-pane>
					</el-tabs>
				</div>
				<div v-else-if="selectedDir && !apiTabs.length" class="dir-detail">
					<div class="dir-detail-head">
						<h3 class="dir-detail-title">{{ dirTitleText }}</h3>
						<el-button type="primary" size="small" @click="saveDirConfig">保存</el-button>
					</div>
					<el-tabs v-model="dirDetailTab" class="dir-detail-tabs">
						<el-tab-pane label="目录设置" name="settings">
							<div class="dd-section">
								<div class="dd-section-title">基本信息</div>
								<div class="dd-row">
									<div class="dd-row-text">
										<div class="dd-row-label">目录名称</div>
										<div class="dd-row-desc">修改目录在树中的展示名称</div>
									</div>
									<el-input v-model="dirName" size="small" style="width: 220px" />
								</div>
								<div class="dd-row" style="margin-top: 8px">
									<div class="dd-row-text">
										<div class="dd-row-label">目录 ID</div>
										<div class="dd-row-desc">目录唯一标识（只读）</div>
									</div>
									<el-input :model-value="String(selectedDir?.id ?? '')" size="small" disabled style="width: 220px" />
								</div>
							</div>
							<div class="dd-section">
								<div class="dd-section-title">可见性</div>
								<div class="dd-row">
									<div class="dd-row-text">
										<div class="dd-row-label">可见性</div>
										<div class="dd-row-desc">设置目录内的接口文档是否可以对外分享或发布</div>
									</div>
									<el-select v-model="dirConfig.visibility" style="width: 200px">
										<el-option label="共享" value="shared" />
										<el-option label="内部" value="internal" />
									</el-select>
								</div>
							</div>
							<div class="dd-section">
								<div class="dd-section-title">高级配置</div>
								<div class="dd-row">
									<div class="dd-row-text">
										<div class="dd-row-label">目录下的接口唯一标识</div>
										<div class="dd-row-desc">导入数据的时候用来匹配对应的接口</div>
									</div>
									<el-select v-model="dirConfig.id_key" style="width: 220px">
										<el-option label="继承父级" value="inherit" />
										<el-option label="Method & Path" value="method_path" />
										<el-option label="OperationId" value="operation_id" />
										<el-option label="Query 参数" value="query" />
										<el-option label="Body 参数" value="body" />
										<el-option label="Header 参数" value="header" />
									</el-select>
								</div>
							</div>
						</el-tab-pane>
						<el-tab-pane label="文档" name="docs">
							<div class="dir-doc-head">
								<el-input v-model="dirDocTitle" size="small" placeholder="文档标题（默认目录名）" style="width: 320px" />
								<el-button type="primary" size="small" @click="saveDirDoc">保存</el-button>
								<el-radio-group v-model="dirDocMode" size="small" style="margin-left: 8px">
									<el-radio-button value="edit">编辑</el-radio-button>
									<el-radio-button value="preview">预览</el-radio-button>
								</el-radio-group>
							</div>
							<el-input v-if="dirDocMode === 'edit'" v-model="dirDocContent" type="textarea" :rows="18" class="dir-doc-textarea" placeholder="请输入内容（支持 Markdown）" />
							<div v-else class="dir-doc-preview markdown-body" v-html="dirDocHtml"></div>
						</el-tab-pane>
					<el-tab-pane label="全部接口" name="apis">
							<div class="dd-apis">
								<div v-if="dirApis.length" class="dd-apis-bar">
									<span>已选 {{ dirChecked.length }}/{{ dirApis.length }} 项</span>
									<el-button link type="danger" size="small" :disabled="!dirChecked.length" @click="dirBatchDelete">删除</el-button>
								</div>
								<div class="dd-apis-head">
									<el-checkbox :model-value="dirApis.length > 0 && dirChecked.length === dirApis.length" @change="(v: any) => toggleDirAll(v)" />
									<span>接口名称</span><span>请求类型</span><span>接口路径</span><span>接口分组</span><span>接口状态</span><span>标签</span>
								</div>
								<div v-for="a in dirApis" :key="a.id" class="dd-apis-row">
									<el-checkbox :model-value="dirChecked.includes(a.id)" @change="(v: any) => toggleDirCheck(a.id, v)" />
									<span class="dd-api-name">{{ a.name }}</span>
									<span class="dd-method" :style="{ color: methodColor(a.method) }">{{ methodLabel(a.method) }}</span>
									<span class="dd-api-path">{{ a.url || '/' }}</span>
									<span>{{ a.groupName }}</span>
									<span><span class="dd-status-dot dot-blue"></span>开发中</span>
									<span>-</span>
								</div>
								<div v-if="!dirApis.length" class="dd-empty">该目录下暂无接口</div>
							</div>
						</el-tab-pane>
						<el-tab-pane label="前置操作" name="before">
							<div class="dd-op-wrap">
								<OperationPanel
									:items="dirBefore"
									mode="before"
									:env-list="envList"
									:tree-list="treeData"
									:db-list="dirDbList"
									:script-list="dirScriptList"
								/>
							</div>
						</el-tab-pane>
						<el-tab-pane label="后置操作" name="after">
							<div class="dd-op-wrap">
								<OperationPanel
									:items="dirAfter"
									mode="after"
									:env-list="envList"
									:tree-list="treeData"
									:db-list="dirDbList"
									:script-list="dirScriptList"
								/>
							</div>
						</el-tab-pane>
						<el-tab-pane label="Auth" name="auth">
							<div style="padding: 8px 0; max-height: 100%; overflow: auto">
								<el-form label-width="130px"><div style="padding:8px 0; max-height:100%; overflow:auto">
										<el-form label-width="130px">
											<el-form-item label="认证类型：">
												<el-select v-model="dirAuth.auth_type" style="width:280px" placeholder="请选择认证类型">
													<el-option label="无认证" value="none" />
													<el-option label="Bearer Token" value="bearer" />
													<el-option label="JWT Bearer" value="jwt" />
													<el-option label="Basic Auth" value="basic" />
													<el-option label="Digest Auth" value="digest" />
													<el-option label="API Key" value="apikey" />
													<el-option label="OAuth 2.0" value="oauth2" />
												</el-select>
											</el-form-item>

											<template v-if="dirAuth.auth_type === 'bearer'">
												<el-form-item label="Token：">
													<el-input v-model="dirAuth.auth_token" placeholder="支持 {{变量}}，如 {{token}}" style="width:420px" />
												</el-form-item>
												<el-form-item label="前缀：">
													<el-input v-model="dirAuth.auth_prefix" placeholder="默认 Bearer，可留空" style="width:200px" />
												</el-form-item>
											</template>

											<template v-if="dirAuth.auth_type === 'jwt'">
												<el-form-item label="Token 来源：">
													<el-radio-group v-model="dirAuth.auth_jwt_mode">
														<el-radio value="token">使用已有 Token</el-radio>
														<el-radio value="generate">本地签发 JWT</el-radio>
													</el-radio-group>
												</el-form-item>
												<template v-if="dirAuth.auth_jwt_mode !== 'generate'">
													<el-form-item label="JWT Token：">
														<el-input v-model="dirAuth.auth_token" type="textarea" :rows="3" placeholder="粘贴 JWT，支持 {{变量}}" style="width:480px" />
													</el-form-item>
												</template>
												<template v-else>
													<el-form-item label="算法：">
														<el-select v-model="dirAuth.auth_jwt_alg" style="width:200px">
															<el-option v-for="a in jwtAlgOptions" :key="a" :label="a" :value="a" />
														</el-select>
													</el-form-item>
													<el-form-item label="Secret / 私钥：">
														<el-input v-model="dirAuth.auth_jwt_secret" type="textarea" :rows="3" placeholder="HS* 填密钥；RS*/ES* 填 PEM 私钥" style="width:480px" />
													</el-form-item>
													<el-form-item label="Payload：">
														<el-input v-model="dirAuth.auth_jwt_payload" type="textarea" :rows="5" placeholder='{"sub":"user","exp":1710000000}' style="width:480px" />
													</el-form-item>
													<el-form-item label="Header（可选）：">
														<el-input v-model="dirAuth.auth_jwt_headers" type="textarea" :rows="2" placeholder='{"typ":"JWT"}' style="width:480px" />
													</el-form-item>
												</template>
												<el-form-item label="前缀：">
													<el-input v-model="dirAuth.auth_prefix" placeholder="默认 Bearer" style="width:200px" />
												</el-form-item>
											</template>

											<template v-if="dirAuth.auth_type === 'basic' || dirAuth.auth_type === 'digest'">
												<el-form-item label="用户名：">
													<el-input v-model="dirAuth.auth_username" placeholder="请输入用户名，支持 {{变量}}" style="width:320px" />
												</el-form-item>
												<el-form-item label="密码：">
													<el-input v-model="dirAuth.auth_password" placeholder="请输入密码，支持 {{变量}}" type="password" show-password style="width:320px" />
												</el-form-item>
											</template>

											<template v-if="dirAuth.auth_type === 'apikey'">
												<el-form-item label="Key：">
													<el-input v-model="dirAuth.auth_key" placeholder="如 X-API-KEY / api_key" style="width:320px" />
												</el-form-item>
												<el-form-item label="Value：">
													<el-input v-model="dirAuth.auth_value" placeholder="支持 {{变量}}" style="width:320px" />
												</el-form-item>
												<el-form-item label="添加到：">
													<el-radio-group v-model="dirAuth.auth_in">
														<el-radio value="header">Header</el-radio>
														<el-radio value="query">Query Params</el-radio>
													</el-radio-group>
												</el-form-item>
											</template>

											<template v-if="dirAuth.auth_type === 'oauth2'">
												<el-form-item label="Grant Type：">
													<el-select v-model="dirAuth.auth_oauth_grant" style="width:280px">
														<el-option label="Access Token（已有令牌）" value="access_token" />
														<el-option label="Client Credentials" value="client_credentials" />
														<el-option label="Password Credentials" value="password" />
													</el-select>
												</el-form-item>
												<template v-if="dirAuth.auth_oauth_grant === 'access_token'">
													<el-form-item label="Access Token：">
														<el-input v-model="dirAuth.auth_oauth_access_token" type="textarea" :rows="2" placeholder="支持 {{access_token}}" style="width:480px" />
													</el-form-item>
												</template>
												<template v-else>
													<el-form-item label="Token URL：">
														<el-input v-model="dirAuth.auth_oauth_token_url" placeholder="https://auth.example.com/oauth/token" style="width:480px" />
													</el-form-item>
													<el-form-item label="Client ID：">
														<el-input v-model="dirAuth.auth_oauth_client_id" style="width:320px" />
													</el-form-item>
													<el-form-item label="Client Secret：">
														<el-input v-model="dirAuth.auth_oauth_client_secret" type="password" show-password style="width:320px" />
													</el-form-item>
													<el-form-item label="Scope：">
														<el-input v-model="dirAuth.auth_oauth_scope" placeholder="可选，多个用空格分隔" style="width:320px" />
													</el-form-item>
													<el-form-item label="Client 认证：">
														<el-radio-group v-model="dirAuth.auth_oauth_client_auth">
															<el-radio value="basic">Basic Auth Header</el-radio>
															<el-radio value="body">Request Body</el-radio>
														</el-radio-group>
													</el-form-item>
													<template v-if="dirAuth.auth_oauth_grant === 'password'">
														<el-form-item label="用户名：">
															<el-input v-model="dirAuth.auth_username" style="width:320px" />
														</el-form-item>
														<el-form-item label="密码：">
															<el-input v-model="dirAuth.auth_password" type="password" show-password style="width:320px" />
														</el-form-item>
													</template>
												</template>
												<el-form-item label="前缀：">
													<el-input v-model="dirAuth.auth_prefix" placeholder="默认 Bearer" style="width:200px" />
												</el-form-item>
											</template>

											<div v-if="dirAuth.auth_type && dirAuth.auth_type !== 'none'" class="auth-hint">
												发送请求时会自动写入 Authorization / 指定 Header 或 Query；支持环境变量替换。
											</div>
										</el-form>
									</div>
								</el-form>
							</div>
						</el-tab-pane>
					</el-tabs>
				</div>
				<div v-if="dmModel && !apiTabs.length && !selectedModule && !selectedDir" class="dm-detail">
					<div class="dm-header">
						<span class="dm-title">数据模型</span>
						<div style="flex:1"></div>
						<el-button size="small" @click="formatDmJson">格式化</el-button>
						<el-button size="small" @click="genDmSchemaFromExample">从示例生成 Schema</el-button>
						<el-button size="small" type="primary" :loading="dmSaving" @click="saveDm">保存</el-button>
						<el-button size="small" type="danger" plain :loading="dmDeleting" @click="deleteDm">删除</el-button>
					</div>
					<el-input v-model="dmName" size="small" placeholder="模型名称" style="margin-top:10px" />
					<div class="dm-label">Schema（JSON Schema）</div>
					<el-input v-model="dmSchemaJson" type="textarea" :rows="18" class="dm-json" spellcheck="false" />
					<div class="dm-hint">提示：粘贴 JSON 示例数据后点「从示例生成 Schema」自动推断结构</div>
				</div>
				<el-dialog v-model="dmCreateVisible" title="新建数据模型" width="560px" append-to-body>
					<el-form label-position="top">
						<el-form-item label="模型名称" required>
							<el-input v-model="dmCreateName" placeholder="请输入模型名称" />
						</el-form-item>
						<el-form-item label="JSON 示例（粘贴后自动推断生成 Schema）" required>
							<el-input v-model="dmCreateJson" type="textarea" :rows="10" placeholder="{&quot;code&quot;:0,&quot;data&quot;:{&quot;id&quot;:1,&quot;name&quot;:&quot;张三&quot;}}" spellcheck="false" class="dm-json" />
						</el-form-item>
					</el-form>
					<template #footer>
						<el-button @click="dmCreateVisible = false">取消</el-button>
						<el-button type="primary" :loading="dmCreating" @click="createDmFromJson">生成并保存</el-button>
					</template>
				</el-dialog>
				<div v-if="!apiTabs.length && !selectedModule && !selectedDir && !dmModel" class="detail-empty">
					<el-icon style="font-size:40px;color:#dcdfe6"><Document /></el-icon>
					<p>点击左侧接口查看详情</p>
				</div>
				<div v-else class="detail-tabs-wrap">
					<!-- 接口多 Tab（可关闭） -->
					<el-tabs v-model="activeTab" type="card" closable class="api-outer-tabs" @tab-remove="closeTab">
						<el-tab-pane v-for="tab in apiTabs" :key="tab.name" :label="tab.title" :name="tab.name">
							<!-- 接口内部功能 Tab：调试 / 接口文档 / 调试记录 / Mock -->
							<div class="inner-tab-container">
								<el-tabs v-model="tab.innerTab" class="inner-tabs">
									<el-tab-pane label="调试" name="debug" />
									<el-tab-pane label="接口文档" name="doc" />
									<el-tab-pane label="调试记录" name="history" />
									<el-tab-pane label="Mock" name="mock" />
								</el-tabs>
								<div class="inner-tab-content">
									<!-- 调试：始终渲染，用 v-show 控制显隐 -->
									<ApiDetail
										v-show="tab.innerTab==='debug'"
										:api-data="tab.data"
										:env-id="envId"
										:env_list="envList"
										:tree_list="treeData"
										:service-id="serviceId"
										:embedded="true"
										@caseSaved="loadTree"
										@apiSaved="loadTree"
									/>
									<!-- 接口文档 -->
									<div v-if="tab.innerTab==='doc'" class="inner-panel-wrap">
										<ApiDocPanel :api-data="tab.data" :api-id="Number(tab.data?.api_id || 0)" />
									</div>
									<!-- 调试记录 -->
									<div v-if="tab.innerTab==='history'" class="inner-panel-wrap">
										<ApiHistoryPanel :api-data="tab.data" />
									</div>
									<!-- Mock -->
									<div v-if="tab.innerTab==='mock'" class="inner-panel-wrap">
										<ApiMockPanel :service-id="serviceId" :api-data="tab.data" />
									</div>
								</div>
							</div>
						</el-tab-pane>
					</el-tabs>
				</div>
			</div>
		</div>

		<!-- 导入接口弹窗 -->
		<el-dialog v-model="importDialogVisible" title="导入接口" width="560px" destroy-on-close class="import-dialog" @closed="onImportDialogClosed">
			<el-form label-position="top">
				<el-form-item label="数据源格式" required>
					<el-select v-model="importSourceType" style="width:100%" @change="onImportSourceChange">
						<el-option label="OpenAPI/Swagger" value="swagger" />
						<el-option label="Postman" value="postman" />
						<el-option label="cURL" value="curl" />
						<el-option label="Apifox" value="apifox" />
					</el-select>
				</el-form-item>
			</el-form>

			<!-- OpenAPI/Swagger：提示横幅 + 上传文件 / URL 导入 -->
			<template v-if="importSourceType === 'swagger'">
				<div class="import-info-bar">
					支持导入 OpenAPI 3.0、3.1 或 Swagger 2.0 数据格式的 JSON 或 YAML 文件。
					<a class="import-info-link" @click="importInfoPopVisible = !importInfoPopVisible">查看详细说明</a>
					<el-popover v-if="importInfoPopVisible" placement="bottom-start" trigger="click" width="420">
						<template #reference>
							<span style="display:none"></span>
						</template>
						<div class="import-info-pop">
							<div><b>OpenAPI 3.0 / 3.1</b>：支持 openapi 字段 + paths 结构的 JSON / YAML 文档</div>
							<div><b>Swagger 2.0</b>：支持 swagger: "2.0" 字段 + paths 结构的 JSON / YAML 文档</div>
							<div>URL 导入支持 Basic Auth 认证的私有文档地址</div>
						</div>
					</el-popover>
				</div>
				<el-radio-group v-model="importTab" class="import-seg">
					<el-radio-button value="file">上传文件</el-radio-button>
					<el-radio-button value="url">URL 导入</el-radio-button>
				</el-radio-group>
				<template v-if="importTab === 'file'">
					<el-upload
						ref="uploadRef"
						drag
						:auto-upload="false"
						:limit="1"
						accept=".json,.yaml,.yml"
						:on-change="onImportFileChange"
						:on-remove="onImportFileRemove"
						:on-exceed="onImportFileExceed"
						class="import-dropzone"
					>
						<el-icon class="el-icon--upload"><UploadFilled /></el-icon>
						<div class="el-upload__text">点击或拖拽文件到本区域导入</div>
					</el-upload>
				</template>
				<el-form v-else label-position="top">
					<el-form-item label="文档 URL" required>
						<el-input v-model="doc_source_url" placeholder="输入 OpenAPI/Swagger 数据 URL" clearable />
					</el-form-item>
					<el-form-item label="Basic Auth">
						<el-switch v-model="urlAuthEnabled" />
					</el-form-item>
					<template v-if="urlAuthEnabled">
						<el-form-item label="账号">
							<el-input v-model="urlAuthUsername" placeholder="账号" clearable />
						</el-form-item>
						<el-form-item label="密码">
							<el-input v-model="urlAuthPassword" type="password" placeholder="密码" show-password />
						</el-form-item>
					</template>
				</el-form>
			</template>

			<!-- Postman：仅文件上传 -->
			<template v-else-if="importSourceType === 'postman'">
				<div class="import-info-bar">
					Postman：请在 Postman 中选择 Collection → 「...」→ Export → Collection v2.1，导出 JSON 文件后导入
				</div>
				<el-upload
					ref="uploadRef"
					drag
					:auto-upload="false"
					:limit="1"
					accept=".json"
					:on-change="onImportFileChange"
					:on-remove="onImportFileRemove"
					:on-exceed="onImportFileExceed"
					class="import-dropzone"
				>
					<el-icon class="el-icon--upload"><UploadFilled /></el-icon>
					<div class="el-upload__text">点击或拖拽文件到本区域导入</div>
				</el-upload>
			</template>

			<!-- cURL -->
			<el-form v-else-if="importSourceType === 'curl'" label-position="top">
				<el-form-item label="粘贴 cURL 数据" required>
					<el-input
						v-model="curlText"
						type="textarea"
						:rows="8"
						placeholder="curl --request GET --url http://www.google.com"
					/>
				</el-form-item>
				<el-form-item label="忽略通用 Header">
					<el-switch v-model="curlIgnoreCommon" />
					<span class="curl-ignore-tip">忽略 User-Agent、Referer 等通用 Header</span>
				</el-form-item>
			</el-form>

			<!-- Apifox：URL + Cookies -->
			<el-form v-else label-position="top">
				<el-form-item label="项目 URL" required>
					<el-input v-model="doc_source_url" placeholder="https://app.apifox.com/project/xxx 或 s.apifox.cn 分享链接" clearable />
				</el-form-item>
				<el-form-item label="Cookies" required>
					<el-input v-model="doc_source_cookies" placeholder="Apifox Cookies（必填）" clearable />
				</el-form-item>
			</el-form>
			<template #footer>
				<el-button @click="importDialogVisible = false">取消</el-button>
				<el-button type="primary" :loading="pulling" @click="confirmImport">继续</el-button>
			</template>
		</el-dialog>

		<!-- 导入预览 & 配置弹窗 -->
		<ImportPreviewDialog
			v-model="previewVisible"
			:preview-list="previewList"
			:service-id="props.serviceId"
			:import-params="previewParams"
			@imported="onPreviewImported"
		/>

		<!-- 绑定数据源弹窗 -->
		<BindDataSourceDialog
			v-model="bindDsVisible"
			:service-id="props.serviceId"
			:module-id="selectedModule?.id || 0"
			:module-name="selectedModule?.name || ''"
			:existing="bindDsExisting"
			@saved="onBindDsSaved"
			@sync-ok="onDsSyncOk"
		/>
		<SyncResultDialog v-model="syncResultVisible" :result="syncResult" />

		<!-- 模块变量批量编辑 -->
		<BatchEditDialog v-model="moduleVarsBulkVisible" :target="'module_vars'" :initial-text="moduleVarsBulkText" @apply="applyModuleVarsBulk" />

		<!-- 新增目录/接口弹窗 -->
		<el-dialog v-model="menuDialogVisible" :title="menuDialogTitle" width="400px" destroy-on-close>
			<el-form label-width="80px">
				<el-form-item label="名称" required>
					<el-input v-model="menuForm.name" placeholder="请输入名称" />
				</el-form-item>
				<el-form-item v-if="menuForm.type === 2" label="协议">
					<el-select v-model="menuForm.protocol" style="width:100%">
						<el-option label="HTTP" value="http" />
						<el-option label="WebSocket" value="websocket" />
						<el-option label="Socket.IO" value="socketio" />
						<el-option label="Webhook" value="webhook" />
					</el-select>
				</el-form-item>
				<el-form-item v-if="menuForm.type === 2" label="父级目录">
					<el-tree-select
						v-model="menuForm.pid"
						:data="folderTree"
						node-key="id"
						:props="{ label: 'name', children: 'children' }"
						check-strictly
						default-expand-all
						filterable
						placeholder="选择父级目录（选模块=默认根目录）"
						style="width:100%"
					/>
					<el-button link type="primary" size="small" style="margin-top: 4px" @click="openCreateDir">
						<el-icon><Plus /></el-icon> 新建目录
					</el-button>
				</el-form-item>
				<el-form-item v-if="menuForm.type === 1" label="父级目录">
					<el-tree-select
						v-model="menuForm.pid"
						:data="folderTree"
						node-key="id"
						:props="{ label: 'name', children: 'children' }"
						check-strictly
						default-expand-all
						filterable
						placeholder="选择父级目录（选模块=默认根目录）"
						style="width:100%"
					/>
				</el-form-item>
			</el-form>
			<template #footer>
				<el-button @click="menuDialogVisible=false">取消</el-button>
				<el-button type="primary" @click="confirmMenu">确定</el-button>
			</template>
		</el-dialog>
	</div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import type { UploadFile, UploadInstance, UploadProps, UploadRawFile } from 'element-plus';
import { ArrowDown, Box, Coin, FolderOpened, Link, MoreFilled, Document, Grid, Plus, UploadFilled } from '@element-plus/icons-vue';
import { marked } from 'marked';
import ApiDetail from './api_detail.vue';
import ApiDbPopover from './components/ApiDbPopover.vue';
import ImportPreviewDialog from './components/ImportPreviewDialog.vue';
import BatchEditDialog from './components/BatchEditDialog.vue';
import BindDataSourceDialog from './components/BindDataSourceDialog.vue';
import SyncResultDialog from './components/SyncResultDialog.vue';
import OperationPanel from './components/OperationPanel.vue';
import ApiDocPanel from './components/ApiDocPanel.vue';
import ApiHistoryPanel from './components/ApiHistoryPanel.vue';
import ApiMockPanel from './components/ApiMockPanel.vue';
import {
	api_tree, api_info, add_menu, del_menu, edit_menu, copy_menu, useApiAutomationApi, api_service_list,
	pull_api_doc, edit_api_service, add_api_service, del_api_service, sort_menu,
} from '/@/api/v1/testing/apiAutomation';

const props = defineProps<{
	serviceId: number;
	envId: number | null;
	envList: any[];
	sourceType?: string;
	sourceAddr?: string;
}>();

const emit = defineEmits<{
	(e: 'update-source', payload: { source_type?: string; source_addr?: string }): void;
}>();


function normalizeSourceType(raw?: string) {
	const t = String(raw || '').trim().toLowerCase();
	if (t === 'apifox') return 'apifox';
	if (t === 'swagger' || t === 'openapi' || t === 'http') return 'swagger';
	return t || 'swagger';
}

function applySourceFromProps() {
	doc_source_type.value = normalizeSourceType(props.sourceType);
	doc_source_url.value = (props.sourceAddr || '').trim();
	file_source_type.value = normalizeSourceType(props.sourceType);
}

// ---- 接口树 ----
const treeRef = ref<any>(null);
const treeData = ref<any[]>([]);
const treeFilter = ref('');

watch(treeFilter, (v) => treeRef.value?.filter(v));
const filterNode = (val: string, data: any) => !val || data.name?.includes(val);

// ---- 树多选/全选批量删除 ----
const treeCheckedKeys = ref<(string | number)[]>([]);
const treeTypeMap = ref<Record<string, number>>({});

const buildTreeTypeMap = () => {
	const map: Record<string, number> = {};
	const walk = (nodes: any[]) => {
		for (const n of nodes || []) {
			map[String(n.id)] = Number(n.type);
			walk(n.children || []);
		}
	};
	walk(treeData.value);
	treeTypeMap.value = map;
};

const onTreeCheck = () => {
	const keys = treeRef.value?.getCheckedKeys() || [];
	treeCheckedKeys.value = keys;
};

const treeCheckAllByMode = (mode: string) => {
	// dir=只选目录（1/5，不含模块与接口）；api=只选接口（2/3，不动目录/模块）；all=全部（除模块）
	const keys: (string | number)[] = [];
	const walk = (nodes: any[]) => {
		for (const n of nodes || []) {
			const t = Number(n.type);
			const ok = mode === 'all' ? (t !== 0 && t !== 5) : mode === 'dir' ? (t === 1) : (t === 2 || t === 3);
			if (ok) keys.push(n.id);
			walk(n.children || []);
		}
	};
	walk(treeData.value);
	treeRef.value?.setCheckedKeys(keys);
	treeCheckedKeys.value = keys;
};

const treeCheckClear = () => {
	treeRef.value?.setCheckedKeys([]);
	treeCheckedKeys.value = [];
};

const treeDeleting = ref(false);
const treeDeleteProgress = ref(0);

const treeBatchDelete = async () => {
	if (!treeCheckedKeys.value.length) return;
	try {
		await ElMessageBox.confirm(
			`将删除选中的 ${treeCheckedKeys.value.length} 个节点（模块不计入，目录会级联删除其下接口），确定？`,
			'批量删除确认',
			{ type: 'warning' },
		);
	} catch { return; }
	const ids = [...treeCheckedKeys.value]
		.filter((k: any) => {
			const t = Number(treeTypeMap.value[String(k)]);
			return t !== 0 && t !== 5;
		})
		.map((k) => Number(k));
	if (!ids.length) {
		ElMessage.warning('所选节点不含可删除项（模块/服务请走服务管理删除）');
		return;
	}
	treeDeleting.value = true;
	treeDeleteProgress.value = 0;
	try {
		for (let i = 0; i < ids.length; i++) {
			await del_menu({ id: ids[i] });
			treeDeleteProgress.value = i + 1;
		}
		ElMessage.success(`已删除 ${ids.length} 个节点`);
		treeCheckedKeys.value = [];
		treeDeleting.value = false;
		treeDeleteProgress.value = 0;
		await loadTree();
	} catch (e: any) {
		treeDeleting.value = false;
		ElMessage.error(e?.message || '删除失败');
	}
};

const loadTree = async () => {
	try {
		const r: any = await api_tree({ search: { api_service_id: props.serviceId } });
		treeData.value = r?.data || [];
	} catch { treeData.value = []; }
	buildTreeTypeMap();
	treeCheckedKeys.value = [];
	// 保持当前选中高亮；无任何选中且无接口 tab 时，默认选中第一个模块展示模块详情
	await nextTick();
	if (dmModel.value) {
		treeRef.value?.setCurrentKey(dmModel.value.menu_id || dmModel.value.id);
	} else if (selectedModule.value) {
		treeRef.value?.setCurrentKey(selectedModule.value.id);
	} else if (selectedDir.value) {
		treeRef.value?.setCurrentKey(selectedDir.value.id);
	} else if (!apiTabs.value.length) {
		const firstMod = treeData.value.find((n: any) => n.type === 5);
		if (firstMod) {
			treeRef.value?.setCurrentKey(firstMod.id);
			await loadModuleDetail(firstMod);
		}
	}
};

// ---- 接口 Tab ----
const apiTabs = ref<any[]>([]);
const activeTab = ref('');

// ---- 刷新保持：接口 tabs 状态持久化（按服务隔离）----
const tabsStorageKey = () => `apiCenter_tabs_${props.serviceId}`
watch(
	[apiTabs, activeTab],
	() => {
		try {
			const saved = {
				tabs: apiTabs.value.map((t) => ({ id: t.id, name: t.name, title: t.title || t.name, apiId: t.data?.api_id || t.apiId, innerTab: t.innerTab || 'debug' })),
				active: activeTab.value,
			}
			localStorage.setItem(tabsStorageKey(), JSON.stringify(saved))
		} catch {}
	},
	{ deep: true }
)

// ---- 拖拽排序 / 跨目录移动 ----
const allowDrop = (draggingNode: any, dropNode: any, type: string) => {
	if (type === 'inner') {
		return dropNode.data.type === 1 || dropNode.data.type === 0
	}
	return true
}

const collectByPid = (pid: number) => {
	const out: any[] = []
	const walk = (nodes: any[]) => {
		for (const n of nodes || []) {
			if (n.type !== 0 && (n.pid || 0) === pid) out.push(n)
			walk(n.children || [])
		}
	}
	walk(treeData.value || [])
	return out
}

const handleNodeDrop = async (draggingNode: any, dropNode: any, dropType: string) => {
	const drag = draggingNode.data
	if (drag.type === 0) { loadTree(); return }
	let newPid: number
	if (dropType === 'inner') {
		newPid = dropNode.data.type === 0 ? 0 : dropNode.data.id
	} else {
		newPid = dropNode.data.pid || 0
	}
	const siblings = collectByPid(newPid)
	const dropId = dropNode.data.id
	const list = siblings.filter((s) => s.id !== drag.id)
	const di = list.findIndex((s) => s.id === dropId)
	if (dropType === 'before' && di >= 0) list.splice(di, 0, drag)
	else if (dropType === 'after' && di >= 0) list.splice(di + 1, 0, drag)
	else list.push(drag)
	try {
		await sort_menu({ pid: newPid, ids: list.map((s) => s.id) })
		ElMessage.success('已更新排序/位置')
		loadTree()
	} catch (e: any) {
		ElMessage.error(e?.message || '移动失败')
		loadTree()
	}
}

const selectedDir = ref<any>(null);
const dirTitleText = computed(() => {
	const dir = selectedDir.value;
	if (!dir) return '';
	// 「接口」根目录显示「根目录 (模块名)」；子目录直接显示目录名称
	if (dir.name === '接口') {
		const mod = treeData.value.find((n: any) => Number(n.id) === Number(dir.pid));
		return mod ? `根目录 (${mod.name})` : '接口';
	}
	return dir.name;
});
const dirDetailTab = ref('settings');
const dirConfig = ref<{ visibility: string; id_key: string }>({ visibility: 'shared', id_key: 'method_path' });
const dirName = ref('');
const dirDocTitle = ref('');
const dirDocContent = ref('');
const dirDocMode = ref<'edit' | 'preview'>('edit');
const dirDocHtml = computed(() => {
	try { return marked.parse(dirDocContent.value || '') as string; } catch { return ''; }
});
const saveDirDoc = async () => {
	if (!selectedDir.value) return;
	try {
		let cp: Record<string, any> = {};
		try { cp = selectedDir.value.common_params ? JSON.parse(selectedDir.value.common_params) : {}; } catch { cp = {}; }
		if (!cp || typeof cp !== 'object') cp = {};
		cp.document = { title: dirDocTitle.value || selectedDir.value.name, content: dirDocContent.value };
		await edit_menu({ id: selectedDir.value.id, name: selectedDir.value.name, common_params: JSON.stringify(cp) } as any);
		ElMessage.success('文档已保存');
		await loadTree();
	} catch (e: any) { ElMessage.error(e?.message || '保存失败'); }
};
const dirChecked = ref<number[]>([]);
const dirBefore = ref<any[]>([]);
const dirAfter = ref<any[]>([]);
const dirDbList = ref<any[]>([]);
const dirScriptList = ref<any[]>([]);
const dirAuth = ref<any>({
	auth_type: 'none', auth_token: '', auth_username: '', auth_password: '',
	auth_key: '', auth_value: '', auth_in: 'header', auth_prefix: 'Bearer',
	auth_jwt_mode: 'token', auth_jwt_alg: 'HS256', auth_jwt_secret: '', auth_jwt_payload: '{\n  "sub": "user"\n}', auth_jwt_headers: '',
	auth_oauth_grant: 'access_token', auth_oauth_access_token: '', auth_oauth_token_url: '',
	auth_oauth_client_id: '', auth_oauth_client_secret: '', auth_oauth_scope: '', auth_oauth_client_auth: 'basic',
});

const dirApis = computed(() => {
	const out: any[] = [];
	const walk = (nodes: any[], group: string) => {
		for (const n of nodes || []) {
			if (n.type === 2) {
				out.push({
					id: n.id,
					api_id: n.api_id,
					name: n.name,
					method: n.method || 2,
					url: n.url || '',
					groupName: group || '根目录',
				});
			} else if (n.type === 1) {
				walk(n.children || [], n.name);
			} else {
				walk(n.children || [], group);
			}
		}
	};
	walk(selectedDir.value?.children || [], '');
	return out;
});

const toggleDirCheck = (id: number, v: any) => {
	if (v) {
		if (!dirChecked.value.includes(id)) dirChecked.value.push(id);
	} else {
		dirChecked.value = dirChecked.value.filter((x) => x !== id);
	}
};
const toggleDirAll = (v: any) => {
	dirChecked.value = v ? dirApis.value.map((a) => a.id) : [];
};
const dirBatchDelete = async () => {
	if (!dirChecked.value.length) return;
	try {
		for (const id of dirChecked.value) {
			await del_menu({ id });
		}
		ElMessage.success(`已删除 ${dirChecked.value.length} 个接口`);
		dirChecked.value = [];
		await loadTree();
	} catch (e: any) {
		ElMessage.error(e?.message || '删除失败');
	}
};
const loadDirLists = async () => {
	try {
		const r: any = await useApiAutomationApi().ntest_script_list({ api_service_id: Number(props.serviceId) });
		dirScriptList.value = Array.isArray(r?.data) ? r.data : [];
	} catch { dirScriptList.value = []; }
	try {
		const r2: any = await useApiAutomationApi().api_db_list({});
		const raw = r2?.data;
		dirDbList.value = Array.isArray(raw?.content) ? raw.content : (Array.isArray(raw) ? raw : []);
	} catch { dirDbList.value = []; }
};

const saveDirConfig = async () => {
	if (!selectedDir.value) return;
	try {
		let cp: Record<string, any> = {};
		try {
			cp = selectedDir.value.common_params ? JSON.parse(selectedDir.value.common_params) : {};
		} catch { cp = {}; }
		if (!cp || typeof cp !== 'object') cp = {};
		cp.visibility = dirConfig.value.visibility;
		cp.id_key = dirConfig.value.id_key;
		cp.before = dirBefore.value;
		cp.after = dirAfter.value;
		cp.auth = dirAuth.value;
		await edit_menu({ id: selectedDir.value.id, name: dirName.value || selectedDir.value.name, common_params: JSON.stringify(cp) } as any);
		ElMessage.success('目录设置已保存');
		await loadTree();
	} catch (e: any) {
		ElMessage.error(e?.message || '保存失败');
	}
};

const bindDsVisible = ref(false);
const bindDsExisting = ref<Record<string, any> | null>(null);
const syncResult = ref<Record<string, any> | null>(null);
const syncResultVisible = ref(false);
const onDsSyncOk = (result: any) => {
	syncResult.value = result || null;
	syncResultVisible.value = true;
	// 同步成功后自动刷新树与模块详情（接口数/目录数等实时更新）
	loadTree();
	if (selectedModule.value) loadModuleDetail(selectedModule.value);
};
const dsSyncing = ref(false);

const freqLabel = (v: string) =>
	v === 'manual' ? '手动触发' : v === '30m' ? '每隔 30 分钟' : v === '1h' ? '每隔 1 小时' : v === '3h' ? '每隔 3 小时' : v === '6h' ? '每隔 6 小时' : v === '12h' ? '每隔 12 小时' : v === '24h' ? '每隔 24 小时' : (v || '-');

const dsNameLetter = computed(() => {
	const nm = bindDsExisting.value?.name || moduleSource.value.source_addr || 'DS';
	return (String(nm).charAt(0) || 'D').toUpperCase();
});

const openBindDs = () => {
	bindDsExisting.value = (moduleSource.value.data_source_config && moduleSource.value.data_source_config.url) ? { ...moduleSource.value.data_source_config } : null;
	bindDsVisible.value = true;
};

const onBindDsSaved = () => {
	loadModuleDetail(selectedModule.value);
	loadTree();
};

const syncBoundDs = async () => {
	if (!selectedModule.value) return;
	dsSyncing.value = true;
	try {
		const r: any = await useApiAutomationApi().syncDataSource({ service_id: Number(selectedModule.value.api_service_id), module_id: Number(selectedModule.value.id || 0) });
		if (r?.code === 200) {
			syncResult.value = r.data || null;
			syncResultVisible.value = true;
			loadModuleDetail(selectedModule.value);
			loadTree();
		} else {
			ElMessage.error(r?.message || '同步失败');
		}
	} catch (e: any) {
		ElMessage.error(e?.message || '同步失败');
	} finally { dsSyncing.value = false; }
};

const selectedModule = ref<any>(null);
const moduleDetailTab = ref('overview');
const moduleVars = ref<{ key: string; remote: string; local: string }[]>([]);
const moduleSource = ref<{ source_type: string; source_addr: string }>({ source_type: '', source_addr: '' });
const moduleVarsBulkVisible = ref(false);
const moduleVarsBulkText = ref('');

const moduleStats = computed(() => {
	const children = selectedModule.value?.children || [];
	let apiCount = 0, caseCount = 0, dirCount = 0;
	const walk = (nodes: any[]) => {
		for (const n of nodes || []) {
			if (n.type === 2) apiCount++;
			else if (n.type === 3) caseCount++;
			else if (n.type === 1 && n.name !== '接口' && n.name !== '数据模型') dirCount++;
			walk(n.children || []);
		}
	};
	walk(children);
	return { apiCount, caseCount, dirCount };
});

const sourceTypeLabel = (t: string) =>
	t === 'apifox' ? 'Apifox' : t === 'postman' ? 'Postman' : t === 'curl' ? 'cURL' : t ? 'OpenAPI/Swagger' : '';

// ---- 数据模型（type=4 节点）----
const dmModel = ref<any>(null);
const dmName = ref('');
const dmSchemaJson = ref('');
const dmSaving = ref(false);
const dmDeleting = ref(false);
const dmCreateVisible = ref(false);
const dmCreateName = ref('');
const dmCreateJson = ref('');
const dmCreating = ref(false);

const openDmByNode = async (data: any) => {
	apiTabs.value = [];
	selectedModule.value = null;
	selectedDir.value = null;
	try {
		const r: any = await apiDataModelList({ api_service_id: props.serviceId });
		const list = r?.data || [];
		const m = list.find((x: any) => Number(x.menu_id) === Number(data.id)) || list.find((x: any) => x.name === data.name);
		if (m) {
			dmModel.value = m;
			dmName.value = m.name || '';
			dmSchemaJson.value = JSON.stringify(m.schema ?? {}, null, 2);
		} else {
			dmModel.value = { id: 0, name: data.name || '未命名', schema: { type: 'object', properties: {} }, menu_id: data.id, pid: data.pid };
			dmName.value = dmModel.value.name;
			dmSchemaJson.value = '{\n  "type": "object",\n  "properties": {}\n}';
		}
	} catch { dmModel.value = null; }
};

const formatDmJson = () => {
	try { dmSchemaJson.value = JSON.stringify(JSON.parse(dmSchemaJson.value), null, 2); }
	catch { ElMessage.error('JSON 格式错误'); }
};

const saveDm = async () => {
	let schema: any = null;
	try { schema = JSON.parse(dmSchemaJson.value); }
	catch { ElMessage.error('Schema JSON 格式错误'); return; }
	dmSaving.value = true;
	try {
		const r: any = await saveDataModel({
			id: dmModel.value?.id || 0,
			api_service_id: props.serviceId,
			name: dmName.value,
			schema,
			pid: dmModel.value?.pid || 0,
		});
		dmModel.value = { ...dmModel.value, id: r?.data?.id ?? dmModel.value?.id, name: dmName.value, schema };
		ElMessage.success('已保存');
		await loadTree();
	} catch (e: any) { ElMessage.error(e?.message || '保存失败'); }
	finally { dmSaving.value = false; }
};

const deleteDm = async () => {
	try { await ElMessageBox.confirm(`确认删除数据模型「${dmName.value}」？`, '删除确认', { type: 'warning' }); }
	catch { return; }
	dmDeleting.value = true;
	try {
		await deleteDataModel({ id: dmModel.value?.id });
		dmModel.value = null;
		ElMessage.success('已删除');
		await loadTree();
	} catch (e: any) { ElMessage.error(e?.message || '删除失败'); }
	finally { dmDeleting.value = false; }
};

const genDmSchemaFromExample = async () => {
	try {
		await saveDataModel({
			id: dmModel.value?.id || 0,
			api_service_id: props.serviceId,
			name: dmName.value,
			json_example: dmSchemaJson.value,
			pid: dmModel.value?.pid || 0,
		});
		const r: any = await apiDataModelList({ api_service_id: props.serviceId });
		const m = (r?.data || []).find((x: any) => Number(x.id) === Number(dmModel.value?.id));
		if (m) {
			dmModel.value = m;
			dmSchemaJson.value = JSON.stringify(m.schema ?? {}, null, 2);
		}
		ElMessage.success('Schema 已从示例生成');
		await loadTree();
	} catch (e: any) { ElMessage.error(e?.message || '生成失败'); }
};

const createDmFromJson = async () => {
	if (!dmCreateName.value.trim()) { ElMessage.warning('请输入模型名称'); return; }
	dmCreating.value = true;
	try {
		const r: any = await importDataModelJson({ api_service_id: props.serviceId, name: dmCreateName.value, json_text: dmCreateJson.value, pid: 0 });
		dmCreateVisible.value = false;
		dmCreateName.value = '';
		dmCreateJson.value = '';
		ElMessage.success('数据模型已创建');
		await loadTree();
		const rr: any = await apiDataModelList({ api_service_id: props.serviceId });
		const m = (rr?.data || []).find((x: any) => Number(x.id) === Number(r?.data?.id));
		if (m) {
			dmModel.value = m;
			dmName.value = m.name || '';
			dmSchemaJson.value = JSON.stringify(m.schema ?? {}, null, 2);
		}
	} catch (e: any) { ElMessage.error(e?.message || '创建失败'); }
	finally { dmCreating.value = false; }
};

const loadModuleDetail = async (data: any) => {
	selectedModule.value = data;
	moduleDetailTab.value = 'overview';
	moduleSource.value = { source_type: '', source_addr: '' };
	moduleVars.value = [];
	try {
		const r: any = await api_service_list({});
		const list = r?.data || [];
		const svc = list.find((s: any) => Number(s.id) === Number(data.api_service_id));
		if (svc) {
			// 模块级数据源：type=5 模块读模块 common_params；兼容服务级
			let dsCp: any = {};
			try { dsCp = data.common_params ? JSON.parse(data.common_params) : {}; } catch { dsCp = {}; }
			const dsCfg = (dsCp && typeof dsCp === 'object' && dsCp.data_source_config && typeof dsCp.data_source_config === 'object') ? dsCp.data_source_config : (svc.data_source_config || null);
			moduleSource.value = {
				source_type: (dsCfg && dsCfg.data_source_type) || svc.source_type || '',
				source_addr: (dsCfg && dsCfg.url) || svc.source_addr || '',
				data_source_config: dsCfg || null,
			};
			bindDsExisting.value = dsCfg && dsCfg.url ? { ...dsCfg } : null;
			const cp = svc.common_params;
			const vars = cp && typeof cp === 'object' && Array.isArray((cp as any).vars) ? (cp as any).vars : [];
			moduleVars.value = vars.map((v: any) => ({ key: String(v.key || ''), remote: String(v.remote ?? v.value ?? ''), local: String(v.local ?? '') }));
		}
	} catch {}
};

const saveModuleVars = async () => {
	if (!selectedModule.value) return;
	try {
		await edit_api_service({ id: Number(selectedModule.value.api_service_id), module_vars: moduleVars.value } as any);
		ElMessage.success('模块变量已保存');
	} catch (e: any) {
		ElMessage.error(e?.message || '保存失败');
	}
};

const openModuleVarsBulk = () => {
	moduleVarsBulkText.value = moduleVars.value
		.map((v) => `${v.key || ''},string,true,${v.remote || ''},true,`)
		.join('\n');
	moduleVarsBulkVisible.value = true;
};

const applyModuleVarsBulk = (rows: any[]) => {
	moduleVars.value = rows.map((r) => ({ key: String(r.key || ''), remote: String(r.value || ''), local: '' }));
};

const onNodeClick = async (data: any) => {
	if (data.type === 0) {
		apiTabs.value = [];
		dmModel.value = null;
		selectedDir.value = null;
		await loadModuleDetail(data);
		return;
	}
	if (data.type === 5) {
		// 模块节点 → 模块详情（概览/模块变量/绑定数据源）
		apiTabs.value = [];
		dmModel.value = null;
		selectedDir.value = null;
		await loadModuleDetail(data);
		return;
	}
	if (data.type === 1) {
		if (data.name === '数据模型') {
			// 数据模型目录：仅展开子级，不展示目录设置详情
			selectedModule.value = null;
			selectedDir.value = null;
			return;
		}
		apiTabs.value = [];
		dmModel.value = null;
		selectedModule.value = null;
		selectedDir.value = data;
		dirDetailTab.value = 'settings';
		dirChecked.value = [];
		let cp: Record<string, any> = {};
		try {
			cp = data.common_params ? JSON.parse(data.common_params) : {};
		} catch { cp = {}; }
		dirConfig.value = {
			visibility: cp.visibility || 'shared',
			id_key: cp.id_key || 'method_path',
		};
		dirName.value = data.name || '';
		const _doc = cp.document;
		if (_doc && typeof _doc === 'object') {
			dirDocTitle.value = _doc.title || '';
			dirDocContent.value = _doc.content || '';
		} else {
			dirDocTitle.value = data.name || '';
			dirDocContent.value = '';
		}
		dirDocMode.value = 'edit';
		dirBefore.value = Array.isArray(cp.before) ? cp.before : [];
		dirAfter.value = Array.isArray(cp.after) ? cp.after : [];
		dirAuth.value = { ...dirAuth.value, ...(cp.auth && typeof cp.auth === 'object' ? cp.auth : {}) };
		loadDirLists();
		return;
	}
	if (data.type === 4) {
		await openDmByNode(data);
		return;
	}
	if (data.type !== 2 && data.type !== 3) return;
	const existing = apiTabs.value.find((t) => t.id === data.id);
	if (existing) { activeTab.value = existing.name; return; }
	const apiId = Number(data.api_id || 0);
	try {
		if (apiId) {
			const r: any = await api_info({ api_id: apiId });
			const info = r?.data || {};
			// 保证后续保存文档/Mock 能拿到接口表 id
			data.api_info = { ...info, id: info.id ?? apiId };
			if (!data.api_id) data.api_id = info.id ?? apiId;
		}
	} catch {}
	const name = `api-${data.id}`;
	apiTabs.value.push({ id: data.id, name, title: data.name, data, innerTab: 'debug' });
	activeTab.value = name;
};

const closeTab = (name: string) => {
	const idx = apiTabs.value.findIndex((t) => t.name === name);
	apiTabs.value.splice(idx, 1);
	if (activeTab.value === name) {
		activeTab.value = apiTabs.value[Math.max(0, idx - 1)]?.name || '';
	}
};

// ---- 方法颜色 ----
const METHOD_MAP: Record<number, { label: string; color: string }> = {
	1: { label: 'GET', color: '#67C23A' }, 2: { label: 'POST', color: '#409EFF' },
	3: { label: 'PUT', color: '#E6A23C' }, 4: { label: 'DELETE', color: '#F56C6C' },
	5: { label: 'PATCH', color: '#8E44AD' }, 6: { label: 'OPTIONS', color: '#909399' },
};
const methodLabel = (m: number) => METHOD_MAP[m]?.label || 'GET';
const methodColor = (m: number) => METHOD_MAP[m]?.color || '#409EFF';

// ---- 导入接口 ----
const importDialogVisible = ref(false);
const importTab = ref<'url' | 'file'>('file');
const importSourceType = ref<'swagger' | 'postman' | 'curl' | 'apifox'>('swagger');
const importInfoPopVisible = ref(false);
const curlText = ref('');
const curlIgnoreCommon = ref(true);
const doc_source_type = ref('swagger');
const doc_source_url = ref('');
const urlAuthEnabled = ref(false);
const urlAuthUsername = ref('');
const urlAuthPassword = ref('');
const doc_source_cookies = ref('');
const file_source_type = ref('swagger');
const importFileContent = ref<Record<string, any> | null>(null);
const uploadRef = ref<UploadInstance>();
const pulling = ref(false);

applySourceFromProps();

watch(
	() => [props.serviceId, props.sourceType, props.sourceAddr] as const,
	() => applySourceFromProps(),
);

const onImportSourceChange = (v: string) => {
	doc_source_type.value = v === 'apifox' ? 'apifox' : 'swagger';
	file_source_type.value = v === 'postman' ? 'postman' : (v === 'apifox' ? 'apifox' : 'swagger');
	if (v === 'swagger') importTab.value = 'file';
};

const openImportDialog = () => {
	applySourceFromProps();
	importSourceType.value = 'swagger';
	importTab.value = 'file';
	doc_source_type.value = 'swagger';
	file_source_type.value = 'swagger';
	urlAuthEnabled.value = false;
	urlAuthUsername.value = '';
	urlAuthPassword.value = '';
	doc_source_cookies.value = '';
	curlText.value = '';
	curlIgnoreCommon.value = true;
	importFileContent.value = null;
	uploadRef.value?.clearFiles();
	importDialogVisible.value = true;
};

const onImportDialogClosed = () => {
	importFileContent.value = null;
	uploadRef.value?.clearFiles();
	importSourceType.value = 'swagger';
	importTab.value = 'file';
	curlText.value = '';
	curlIgnoreCommon.value = true;
};

const readFileAsText = (file: UploadRawFile) =>
	new Promise<string>((resolve, reject) => {
		const reader = new FileReader();
		reader.onload = () => resolve(String(reader.result || ''));
		reader.onerror = () => reject(new Error('文件读取失败'));
		reader.readAsText(file);
	});

const onImportFileChange: UploadProps['onChange'] = async (uploadFile: UploadFile) => {
	importFileContent.value = null;
	const raw = uploadFile.raw;
	if (!raw) return;
	try {
		const text = await readFileAsText(raw);
		if (!text.trim()) throw new Error('文件内容为空');
		importFileContent.value = text;
	} catch (e: any) {
		importFileContent.value = null;
		uploadRef.value?.clearFiles();
		ElMessage.error(e?.message || '文件读取失败');
	}
};

const onImportFileRemove = () => {
	importFileContent.value = null;
};

const onImportFileExceed: UploadProps['onExceed'] = (files) => {
	uploadRef.value?.clearFiles();
	const file = files[0] as UploadRawFile;
	uploadRef.value?.handleStart(file);
	onImportFileChange({ name: file.name, raw: file, status: 'ready', uid: file.uid } as UploadFile);
};

const saveSourceNow = async (source_type: string, source_addr: string) => {
	const normalized = normalizeSourceType(source_type);
	await edit_api_service({
		id: props.serviceId,
		source_type: normalized,
		source_addr: source_addr || undefined,
	} as any);
	emit('update-source', { source_type: normalized, source_addr });
};

const previewVisible = ref(false);
const previewList = ref<any[]>([]);
const previewParams = ref<Record<string, any>>({});

const buildImportBase = (): Record<string, any> | null => {
	if (importSourceType.value === 'apifox') {
		if (!doc_source_url.value.trim()) { ElMessage.warning('请输入 Apifox 项目 URL'); return null; }
		if (!doc_source_cookies.value.trim()) { ElMessage.warning('请输入 Apifox Cookies'); return null; }
		return { source_type: 'apifox', doc_url: doc_source_url.value.trim(), cookies: doc_source_cookies.value.trim() };
	}
	if (importSourceType.value === 'postman') {
		if (!importFileContent.value) { ElMessage.warning('请选择 Postman Collection 文件'); return null; }
		return { source_type: 'postman', doc_content: String(importFileContent.value || '') };
	}
	if (importTab.value === 'url') {
		if (!doc_source_url.value.trim()) { ElMessage.warning('请输入文档 URL'); return null; }
		const base: Record<string, any> = { source_type: 'swagger', doc_url: doc_source_url.value.trim() };
		if (urlAuthEnabled.value) {
			base.basic_auth = { username: urlAuthUsername.value.trim(), password: urlAuthPassword.value };
		}
		return base;
	}
	if (!importFileContent.value) { ElMessage.warning('请选择要导入的 JSON 或 YAML 文件'); return null; }
	return { source_type: 'swagger', doc_content: String(importFileContent.value || '') };
};

const confirmImport = async () => {
	if (importSourceType.value === 'curl') {
		await importByCurl();
		return;
	}
	const base = buildImportBase();
	if (!base) return;
	pulling.value = true;
	try {
		const r: any = await pull_api_doc({ api_service_id: props.serviceId, ...base, preview: true });
		if (r?.code === 200) {
			const list = r?.data?.preview || [];
			if (!list.length) { ElMessage.warning('文档中未解析到接口'); return; }
			previewList.value = list;
			previewParams.value = base;
			previewVisible.value = true;
		} else {
			ElMessage.error(r?.message || '解析失败');
		}
	} catch (e: any) {
		ElMessage.error(e?.message || '解析失败');
	} finally {
		pulling.value = false;
	}
};

const onPreviewImported = () => {
	importDialogVisible.value = false;
	loadTree();
};

// ---- cURL 导入 ----
const parseCurl = (raw: string) => {
	const parts: string[] = [];
	for (const tok of raw.match(/"([^"]*)"|'([^']*)'|[^\s]+/g) || []) {
		parts.push(tok.replace(/^["']|["']$/g, ''));
	}
	let method = 'GET';
	let url = '';
	const headers: { key: string; value: string; status: boolean }[] = [];
	let bodyRaw = '';
	let hasData = false;
	let i = 0;
	const next = () => parts[++i];
	while (i < parts.length) {
		const t = parts[i];
		if (t === '-X' || t === '--request') {
			method = (next() || 'GET').toUpperCase();
		} else if (t === '-H' || t === '--header') {
			const h = next() || '';
			const idx = h.indexOf(':');
			if (idx > 0) headers.push({ key: h.slice(0, idx).trim(), value: h.slice(idx + 1).trim(), status: true });
		} else if (t === '-d' || t === '--data' || t === '--data-raw' || t === '--data-binary' || t === '--data-ascii') {
			bodyRaw = (bodyRaw ? bodyRaw + '&' : '') + (next() || '');
			hasData = true;
		} else if (t === '-G' || t === '--get') {
			method = 'GET';
		} else if (t.charAt(0) !== '-' && !url) {
			url = t;
		}
		i++;
	}
	if (hasData && method === 'GET') method = 'POST';
	const commonHeaders = ['user-agent', 'referer', 'accept', 'accept-language', 'accept-encoding', 'connection', 'cookie', 'content-length'];
	const header = headers.filter((h) => !(curlIgnoreCommon.value && commonHeaders.indexOf(h.key.toLowerCase()) >= 0));
	let bodyType = 2;
	let body: any = bodyRaw;
	const ct = header.find((h) => h.key.toLowerCase() === 'content-type');
	if (ct && ct.value.toLowerCase().indexOf('application/json') >= 0) {
		bodyType = 2;
		try { body = bodyRaw ? JSON.parse(bodyRaw) : {}; } catch (e) { body = bodyRaw; }
	} else if (ct && ct.value.toLowerCase().indexOf('x-www-form-urlencoded') >= 0) {
		bodyType = 3;
		body = bodyRaw.split('&').map((p) => {
			const kv = p.split('=');
			return { key: decodeURIComponent(kv[0] || ''), value: decodeURIComponent(kv.slice(1).join('=') || ''), status: true };
		});
	} else if (bodyRaw) {
		try { body = JSON.parse(bodyRaw); } catch (e) { body = bodyRaw; }
	}
	const methodMap: Record<string, number> = { GET: 1, POST: 2, PUT: 3, DELETE: 4, PATCH: 5, HEAD: 6, OPTIONS: 7 };
	return { method: methodMap[method] || 2, url, header, body, bodyType, params: [] };
};

const importByCurl = async () => {
	if (!curlText.value.trim()) {
		ElMessage.warning('请粘贴 cURL 命令');
		return;
	}
	pulling.value = true;
	try {
		const parsed = parseCurl(curlText.value) as any;
		if (!parsed.url) {
			ElMessage.warning('未解析到 URL，请检查 cURL 命令格式');
			return;
		}
		const name = parsed.url.split('?')[0].split('/').filter(Boolean).pop() || '导入接口';
		const payload = {
			api_service_id: props.serviceId,
			pid: 0,
			name: name,
			url: parsed.url,
			method: parsed.method,
			header: parsed.header,
			body: parsed.body,
			bodyType: parsed.bodyType,
			params: parsed.params,
		};
		await useApiAutomationApi().curlImport(payload);
		ElMessage.success('cURL 导入成功');
		importDialogVisible.value = false;
		await loadTree();
	} catch (e: any) {
		ElMessage.error(e?.message || 'cURL 导入失败');
	} finally {
		pulling.value = false;
	}
};

const importByUrl = async () => {
	const docUrl = doc_source_url.value.trim();
	if (!docUrl) { ElMessage.warning('请输入文档 URL'); return; }
	if (doc_source_type.value === 'apifox' && !doc_source_cookies.value.trim()) {
		ElMessage.warning('Apifox 导入需要 Cookies'); return;
	}
	pulling.value = true;
	try {
		const source_type = normalizeSourceType(doc_source_type.value);
		try {
			await edit_api_service({ id: props.serviceId, source_type } as any);
			emit('update-source', { source_type });
		} catch { /* 保存失败不阻断导入 */ }
		await pull_api_doc({
			api_service_id: props.serviceId,
			source_type: source_type as 'swagger' | 'apifox',
			doc_url: docUrl,
			cookies: doc_source_cookies.value.trim(),
			basic_auth: urlAuthEnabled.value && doc_source_type.value === 'swagger'
				? { username: urlAuthUsername.value.trim(), password: urlAuthPassword.value }
				: undefined,
		});
		ElMessage.success('导入成功');
		importDialogVisible.value = false;
		await loadTree();
	} catch (e: any) {
		ElMessage.error(e?.message || '导入失败');
	} finally {
		pulling.value = false;
	}
};

const importByFile = async () => {
	if (!importFileContent.value) {
		ElMessage.warning('请选择要导入的 JSON 或 YAML 文件');
		return;
	}
	pulling.value = true;
	try {
		const source_type = normalizeSourceType(file_source_type.value);
		try {
			await edit_api_service({
				id: props.serviceId,
				source_type,
			} as any);
			emit('update-source', { source_type });
		} catch { /* 保存失败不阻断导入 */ }
		await pull_api_doc({
			api_service_id: props.serviceId,
			source_type: source_type as 'swagger' | 'apifox',
			doc_content: String(importFileContent.value || ''),
		});
		ElMessage.success('导入成功');
		importDialogVisible.value = false;
		await loadTree();
	} catch (e: any) {
		ElMessage.error(e?.message || '导入失败');
	} finally {
		pulling.value = false;
	}
};

// ---- 菜单操作 ----
const folderOptions = computed(() => {
	const mods: any[] = []
	const dirs: any[] = []
	const walk = (nodes: any[], prefix: string) => {
		for (const n of nodes || []) {
			if (n.type === 0) {
				mods.push({ id: 'svc_' + n.api_service_id, path: n.name, api_service_id: n.api_service_id })
				walk(n.children || [], n.name)
			} else if (n.type === 5) {
				mods.push({ id: n.id, path: n.name, api_service_id: n.api_service_id })
				walk(n.children || [], n.name)
			} else if (n.type === 1 && n.name !== '数据模型') {
				const p = prefix ? prefix + ' / ' + n.name : n.name
				dirs.push({ id: n.id, path: p })
				walk(n.children || [], p)
			}
		}
	}
	walk(treeData.value || [], '')
	return { mods, dirs }
});

// Apifox 树形：模块 + 子目录（「接口」根不展示，「接口」下的子目录提升到模块下；数据模型不参与）
const folderTree = computed(() => {
	const build = (nodes: any[]): any[] =>
		(nodes || []).map((n: any) => {
			if (n.type === 5) {
				const iface = (n.children || []).find((c: any) => c.type === 1 && c.name === '接口');
				const others = (n.children || []).filter((c: any) => c.type === 1 && c.name !== '接口' && c.name !== '数据模型');
				const kids = [...((iface && iface.children) || []), ...others];
				return { id: n.id, name: n.name, children: build(kids) };
			}
			if (n.type === 1 && n.name !== '接口' && n.name !== '数据模型') {
				return { id: n.id, name: n.name, children: build(n.children || []) };
			}
			return null;
		}).filter((x: any) => x !== null);
	return build(treeData.value || []);
});

const openCreateDir = () => {
	menuForm.value = { name: '', type: 1, pid: menuForm.value.pid || folderTree.value[0]?.id || 0, editId: 0, mode: 'add', protocol: 'http' };
	menuDialogTitle.value = '添加目录';
	menuDialogVisible.value = true;
};

const menuDialogVisible = ref(false);
const menuDialogTitle = ref('');
const menuForm = ref({ name: '', type: 1, pid: 0, editId: 0, mode: 'add' as 'add' | 'edit', protocol: 'http' });

const handleAddCommand = (cmd: string) => {
	if (cmd === 'import_api') {
		openImportDialog();
		return;
	}
	if (cmd === 'add_data_model') {
		dmCreateVisible.value = true;
		return;
	}
	if (cmd === 'add_module') {
		menuForm.value = { name: '', type: 5, pid: 0, editId: 0, mode: 'add_module' };
		menuDialogTitle.value = '添加模块';
		menuDialogVisible.value = true;
		return;
	}
	const _first = folderTree.value[0]?.id ?? folderOptions.value.mods[0]?.id ?? 0;
	menuForm.value = { name: '', type: cmd === 'add_folder' ? 1 : 2, pid: _first, editId: 0, mode: 'add', protocol: 'http' };
	menuDialogTitle.value = cmd === 'add_folder' ? '添加目录' : '添加接口';
	menuDialogVisible.value = true;
};

const handleNodeCommand = (cmd: string, data: any) => {
	if (cmd === 'menu_params') {
		commonParamsRef.value?.open(data.id)
		return
	}
	if (cmd === 'add_folder') {
		const isModule = data.type === 0;
		menuForm.value = { name: '', type: 1, pid: isModule ? 0 : data.id, editId: 0, mode: 'add', protocol: 'http' };
		menuDialogTitle.value = isModule ? '添加目录' : '添加子目录';
		menuDialogVisible.value = true;
	} else if (cmd === 'add_api') {
		menuForm.value = { name: '', type: 2, pid: data.id, editId: 0, mode: 'add', protocol: 'http' };
		menuDialogTitle.value = '添加接口';
		menuDialogVisible.value = true;
	} else if (cmd === 'rename') {
		if (data.type === 0) {
			menuForm.value = { name: data.name, type: 0, pid: 0, editId: Number(data.api_service_id), mode: 'edit_module' };
			menuDialogTitle.value = '重命名模块';
			menuDialogVisible.value = true;
			return;
		}
		menuForm.value = { name: data.name, type: data.type, pid: data.pid || 0, editId: data.id, mode: 'edit' };
		menuDialogTitle.value = '重命名';
		menuDialogVisible.value = true;
	} else if (cmd === 'copy') {
		copyApi(data);
	} else if (cmd === 'delete') {
		deleteNode(data);
	}
};

const confirmMenu = async () => {
	if (menuForm.value.mode === 'add_module') {
		// 模块 = 当前服务（项目）下的模块子节点；不创建服务，模块下自动生成「接口」根目录 +「数据模型」
		if (!menuForm.value.name.trim()) { ElMessage.warning('请输入模块名称'); return; }
		try {
			const rr: any = await add_menu({ name: menuForm.value.name.trim(), pid: 0, type: 5, api_service_id: props.serviceId, protocol: 'http' });
			const modId = rr?.data?.id;
			if (modId) {
				await add_menu({ name: '接口', pid: Number(modId), type: 1, api_service_id: props.serviceId, protocol: 'http' });
				await add_menu({ name: '数据模型', pid: Number(modId), type: 1, api_service_id: props.serviceId, protocol: 'http' });
			}
			ElMessage.success('模块已创建（含接口根目录与数据模型）');
			menuDialogVisible.value = false;
			loadTree();
		} catch (e: any) {
			ElMessage.error(e?.message || '创建失败');
		}
		return;
	}
	if (menuForm.value.mode === 'edit_module') {
		try {
			await edit_api_service({ id: menuForm.value.editId, name: menuForm.value.name });
			ElMessage.success('模块已重命名');
			menuDialogVisible.value = false;
			loadTree();
		} catch (e: any) {
			ElMessage.error(e?.message || '重命名失败');
		}
		return;
	}
	if (!menuForm.value.name.trim()) { ElMessage.warning('请输入名称'); return; }
	try {
		if (menuForm.value.mode === 'edit') {
			await edit_menu({ id: menuForm.value.editId, name: menuForm.value.name.trim() });
		} else {
			let pidVal = menuForm.value.pid
			let svcId: any = props.serviceId
			if (typeof pidVal === 'string' && pidVal.startsWith('svc_')) {
				svcId = Number(pidVal.replace('svc_', ''))
				pidVal = 0
			}
			await add_menu({ name: menuForm.value.name.trim(), pid: pidVal, type: menuForm.value.type, api_service_id: svcId, protocol: menuForm.value.protocol || 'http' });
		}
		menuDialogVisible.value = false;
		await loadTree();
	} catch (e: any) { ElMessage.error(e?.message || '操作失败'); }
};

const copyApi = async (data: any) => {
	try {
		await copy_menu({ id: data.id, api_id: data.api_id });
		ElMessage.success('复制成功');
		await loadTree();
	} catch (e: any) { ElMessage.error(e?.message || '复制失败'); }
};

const deleteNode = async (data: any) => {
	if (data.type === 0) {
		// 树顶级 = 模块；服务不参与树层级，删除服务请到服务管理
		ElMessage.info('服务不参与树层级，请到服务管理列表删除');
		return;
	}
	try {
		await ElMessageBox.confirm(`确认删除「${data.name}」？`, '提示', { type: 'warning' });
		await del_menu({ id: data.id, type: data.type });
		ElMessage.success('删除成功');
		apiTabs.value = apiTabs.value.filter((t) => t.id !== data.id);
		await loadTree();
	} catch (e: any) {
		if (e === 'cancel' || e === 'close') return;
		ElMessage.error(e?.message || '删除失败');
	}
};

onMounted(() => {
	loadTree().then(async () => {
		// 刷新恢复：重新打开上次的接口 tabs（重新拉详情）
		try {
			const raw = localStorage.getItem(tabsStorageKey())
			if (!raw) return
			const saved = JSON.parse(raw)
			if (!saved?.tabs?.length) return
			for (const t of saved.tabs) {
				try {
					const r: any = await api_info({ api_id: Number(t.apiId) })
					const info = r?.data || {}
					const data = { id: t.id, name: t.name, api_id: Number(t.apiId), api_info: { ...info, id: info.id ?? Number(t.apiId) } }
					apiTabs.value.push({ id: t.id, name: t.name, title: t.title || info.name || t.name, data, innerTab: t.innerTab || 'debug' })
				} catch {}
			}
			if (saved.active && apiTabs.value.some((x) => x.name === saved.active)) {
				activeTab.value = saved.active
			} else if (apiTabs.value.length) {
				activeTab.value = apiTabs.value[0].name
			}
		} catch {}
	});
});
</script>

<style scoped>
.manage-panel { height: 100%; display: flex; flex-direction: column; overflow: hidden; }
.manage-toolbar { padding: 8px 12px; background: var(--el-bg-color); border-bottom: 1px solid var(--el-border-color); flex-shrink: 0; }
.toolbar-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.toolbar-tools { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
.manage-body { flex: 1; min-height: 0; display: flex; overflow: hidden; }
.tree-panel { width: 320px; flex-shrink: 0; border-right: 1px solid var(--el-border-color); display: flex; flex-direction: column; overflow: hidden; background: var(--el-bg-color); }
.tree-actions { display: flex; align-items: center; padding: 8px; border-bottom: 1px solid var(--el-border-color); flex-shrink: 0; }
.api-tree { flex: 1; overflow-y: auto; padding: 4px 0; }
.tree-node { display: flex; align-items: center; justify-content: space-between; width: 100%; padding-right: 4px; }
.node-left { display: flex; align-items: center; gap: 4px; min-width: 0; flex: 1; overflow: hidden; }
.node-name { font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.node-more { font-size: 14px; color: var(--el-text-color-placeholder); cursor: pointer; flex-shrink: 0; opacity: 0; }
.tree-node:hover .node-more { opacity: 1; }
.icon-folder { color: #f39c12; font-size: 16px; flex-shrink: 0; }
.icon-case { color: #e6a23c; font-size: 16px; flex-shrink: 0; }
.method-badge { font-size: 10px; font-weight: 700; padding: 0 4px; border-radius: 3px; color: #fff; flex-shrink: 0; line-height: 16px; }
.detail-panel { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; height: 100%; }
.detail-empty { height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; color: var(--el-text-color-placeholder); gap: 8px; font-size: 13px; }
.detail-tabs-wrap { height: 100%; display: flex; flex-direction: column; overflow: hidden; }
.detail-tabs-wrap > :deep(.el-tabs) { height: 100%; display: flex; flex-direction: column; }
.detail-tabs-wrap > :deep(.el-tabs > .el-tabs__header) { flex-shrink: 0; }
.detail-tabs-wrap > :deep(.el-tabs > .el-tabs__content) { flex: 1; min-height: 0; overflow: hidden; padding: 0; }
.detail-tabs-wrap > :deep(.el-tabs > .el-tabs__content > .el-tab-pane) { height: 100%; overflow: hidden; }
.inner-tab-container { height: 100%; display: flex; flex-direction: column; overflow: hidden; }
.inner-tabs { flex-shrink: 0; }
.inner-tabs :deep(.el-tabs__header) { margin: 0; background: var(--el-fill-color-light); border-bottom: 1px solid var(--el-border-color); padding: 0 8px; }
.inner-tabs :deep(.el-tabs__nav-wrap::after) { display: none; }
.inner-tabs :deep(.el-tabs__item) { height: 36px; line-height: 36px; font-size: 12px; color: var(--el-text-color-regular); padding: 0 14px; }
.inner-tabs :deep(.el-tabs__item:hover) { color: #409eff; }
.inner-tabs :deep(.el-tabs__item.is-active) { color: #409eff; font-weight: 600; }
.inner-tabs :deep(.el-tabs__active-bar) { height: 2px; background: #409eff; }
.inner-tabs :deep(.el-tabs__content) { display: none; }
.inner-tab-content { flex: 1; min-height: 0; overflow: hidden; display: flex; flex-direction: column; }
.inner-panel-wrap { flex: 1; min-height: 0; overflow: hidden; height: 100%; }
.curl-ignore-tip {
	margin-left: 8px;
	font-size: 12px;
	color: #909399;
}
.import-tip-bar {
	background: var(--el-fill-color-light);
	border-radius: 4px;
	padding: 6px 10px;
	font-size: 12px;
	color: var(--el-text-color-secondary);
	line-height: 1.6;
}
.proto-badge {
	display: inline-flex;
	align-items: center;
	justify-content: center;
	font-size: 10px;
	line-height: 1;
	padding: 2px 5px;
	border-radius: 4px;
	color: #fff;
	margin-left: 6px;
	flex: 0 0 auto;
}
.proto-ws { background: #7c4dff; }
.proto-wh { background: #ec4899; }
.import-dialog .el-form-item { margin-bottom: 18px; }
.import-dialog .el-form-item:last-child { margin-bottom: 4px; }
.import-dialog .el-tabs__header { margin-bottom: 12px; }
.import-info-bar {
	background: var(--el-fill-color-light);
	border-radius: 6px;
	padding: 8px 12px;
	font-size: 12px;
	color: var(--el-text-color-secondary);
	line-height: 1.7;
	margin: 4px 0 14px;
}
.import-info-link { color: #7c3aed; cursor: pointer; margin-left: 4px; }
.import-info-pop { font-size: 12px; color: #606266; line-height: 1.9; }
.import-seg {
	display: flex;
	background: var(--el-fill-color-light);
	border-radius: 6px;
	padding: 3px;
	margin-bottom: 16px;
	width: 100%;
}
.import-seg :deep(.el-radio-button) { flex: 1; }
.import-seg :deep(.el-radio-button__inner) {
	width: 100%;
	border: none;
	border-radius: 4px;
	background: transparent;
	box-shadow: none;
	color: var(--el-text-color-regular);
}
.import-seg :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
	background: #fff;
	color: var(--el-text-color-primary);
	font-weight: 600;
	box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}
.import-dropzone { width: 100%; }
.import-dropzone :deep(.el-upload-dragger) { width: 100%; }
.module-detail { padding: 4px 2px; }
.module-detail-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.module-detail-title { margin: 0; font-size: 18px; font-weight: 600; color: var(--el-text-color-primary); }
.module-detail-tabs { }
.md-stats { display: flex; gap: 12px; margin-bottom: 18px; }
.md-stat-card { flex: 1; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; padding: 16px; text-align: center; background: var(--el-bg-color); }
.md-stat-num { font-size: 24px; font-weight: 600; color: var(--el-text-color-primary); }
.md-stat-label { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 4px; }
.md-section { border: 1px solid var(--el-border-color-lighter); border-radius: 8px; padding: 14px; }
.md-section-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.md-section-title { font-size: 14px; font-weight: 600; }
.md-source-row { display: flex; align-items: center; gap: 10px; }
.md-source-tag { font-size: 11px; color: #fff; background: #7c3aed; border-radius: 4px; padding: 2px 8px; }
.md-source-addr { font-size: 13px; color: var(--el-text-color-regular); font-family: Consolas, Monaco, monospace; word-break: break-all; }
.md-source-empty { font-size: 12px; color: var(--el-text-color-secondary); }
.md-vars-head, .md-vars-row { display: grid; grid-template-columns: 1fr 1fr 1fr 50px; gap: 8px; align-items: center; }
.md-vars-head { font-size: 12px; color: var(--el-text-color-secondary); margin-bottom: 6px; }
.md-vars-row { margin-bottom: 6px; }
.md-vars-actions { margin-top: 8px; display: flex; gap: 12px; }
.dir-detail { padding: 4px 2px; }
.dir-detail-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.dir-detail-title { margin: 0; font-size: 18px; font-weight: 600; color: var(--el-text-color-primary); }
.dd-section { border: 1px solid var(--el-border-color-lighter); border-radius: 8px; padding: 14px; margin-bottom: 12px; }
.dd-section-title { font-size: 14px; font-weight: 600; margin-bottom: 8px; }
.dd-desc { font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.8; }
.dd-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.dd-row-text { flex: 1; }
.dd-row-label { font-size: 13px; color: var(--el-text-color-primary); }
.dd-row-desc { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 2px; }
.dd-apis-bar { display: flex; align-items: center; gap: 12px; font-size: 12px; color: var(--el-text-color-secondary); margin-bottom: 8px; }
.dd-apis-head, .dd-apis-row { display: grid; grid-template-columns: 30px 1.2fr 90px 1.6fr 1fr 100px 80px; gap: 8px; align-items: center; }
.dd-apis-head { font-size: 12px; color: var(--el-text-color-secondary); padding: 6px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.dd-apis-row { padding: 5px 0; border-bottom: 1px solid var(--el-border-color-lighter); font-size: 13px; }
.dd-api-name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.dd-api-path { font-family: Consolas, Monaco, monospace; font-size: 12px; color: var(--el-text-color-regular); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.dd-method { font-weight: 600; font-size: 12px; }
.dd-status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; }
.dot-green { background: #67c23a; }
.dot-blue { background: #409eff; }
.dd-empty { font-size: 12px; color: var(--el-text-color-secondary); text-align: center; padding: 30px 0; }
.dd-op-wrap { max-height: 480px; overflow: auto; }
.md-source-freq { font-size: 12px; color: var(--el-text-color-secondary); background: var(--el-fill-color-light); border-radius: 4px; padding: 2px 8px; }
.md-source-item { display: flex; align-items: center; gap: 12px; }
.md-source-logo { width: 36px; height: 36px; border-radius: 8px; background: #ef4444; color: #fff; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 16px; flex: 0 0 auto; }
.md-source-info { flex: 1; min-width: 0; }
.md-source-name { font-size: 14px; font-weight: 600; color: var(--el-text-color-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.md-source-meta { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 2px; }
.dm-detail { padding: 4px 2px; }
.dm-header { display: flex; align-items: center; gap: 8px; }
.dm-title { font-size: 15px; font-weight: 600; color: var(--el-text-color-primary); }
.dm-label { font-size: 13px; color: var(--el-text-color-secondary); margin-top: 12px; margin-bottom: 4px; }
.dm-json :deep(textarea) { font-family: Consolas, Monaco, monospace; font-size: 12px; line-height: 1.5; }
.dm-hint { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 6px; }
.icon-dm { color: #8b5cf6; }
.tree-batch-bar { display: flex; align-items: center; flex-wrap: nowrap; gap: 8px; padding: 6px 8px; background: #fef0f0; border-radius: 4px; margin-bottom: 4px; white-space: nowrap; }
.batch-count { font-size: 12px; color: var(--el-color-danger); flex-shrink: 0; }
.batch-delete-btn { margin-left: auto; }
.dir-doc-head { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.dir-doc-textarea :deep(textarea) { font-family: Consolas, Monaco, monospace; font-size: 13px; line-height: 1.6; }
.dir-doc-preview { min-height: 300px; padding: 12px 16px; border: 1px solid var(--el-border-color-lighter); border-radius: 4px; background: #fff; overflow: auto; }
</style>
