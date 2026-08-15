<template>
	<div class="api-detail-container" :class="{'is-embedded': props.embedded}">
		<el-card class="api-detail-card">
			<!-- 顶部大 Tab（嵌入模式下隐藏）-->
			<el-tabs v-if="!props.embedded" v-model="mainTab" class="main-tabs">
				<el-tab-pane label="调试" name="debug" />
				<el-tab-pane label="接口文档" name="doc" />
				<el-tab-pane label="调试记录" name="history" />
				<el-tab-pane v-if="req.protocol !== 'websocket'" label="Mock" name="mock" />
			</el-tabs>

			<!-- 调试面板 -->
			<div v-show="mainTab==='debug'" class="api-detail-content">
				<!-- URL bar -->
				<div class="api-detail-header">
					<div class="req-url-bar">
						<el-tag v-if="req.protocol === 'websocket'" effect="dark" color="#7c4dff" class="ws-badge">WebSocket</el-tag>
						<el-tag v-else-if="req.protocol === 'webhook'" effect="dark" color="#ec4899" class="ws-badge">Webhook</el-tag>
						<el-select v-if="req.protocol !== 'websocket'" v-model="req.method" class="method-select" :style="{ '--method-color': currentMethodColor }">
							<el-option v-for="(m, i) in method_list" :key="i" :label="m.name" :value="m.value">
								<span :style="{ color: m.color, fontWeight: 600 }">{{ m.name }}</span>
							</el-option>
						</el-select>
						<el-tooltip v-if="req.protocol === 'webhook'" placement="bottom-start" trigger="focus" :visible-arrow="false" popper-class="webhook-tip-popper">
							<template #content>
								<div class="webhook-tip-box">
									<div class="webhook-tip-text">此处填写的 Webhook name 用于标识该回调，不会显示在接口文档中。</div>
									<img src="/webhook-tip.png" alt="Webhook 说明" class="webhook-tip-img" />
								</div>
							</template>
							<el-input v-model="req.webhook_name" placeholder="Webhook name" clearable class="url-input" />
						</el-tooltip>
						<el-input v-else v-model="req.url" :placeholder="req.protocol === 'websocket' ? '未设置前置URL，接口路径以 ws:// 或 wss:// 起始' : '请输入请求地址'" clearable class="url-input" />
						<el-button v-if="req.protocol === 'websocket'" type="primary" @click="wsConnect" class="send-btn">连接</el-button>
						<el-button v-else type="primary" @click="sendRequest" class="send-btn">发送</el-button>
						<el-dropdown @command="handleSaveCommand">
							<el-button type="success" class="save-btn">保存项 <el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
							<template #dropdown>
								<el-dropdown-menu>
									<el-dropdown-item command="save">直接保存</el-dropdown-item>
									<el-dropdown-item command="saveAsCase">保存测试用例</el-dropdown-item>
								</el-dropdown-menu>
							</template>
						</el-dropdown>
					</div>
					<div v-if="req.protocol === 'webhook'" class="webhook-bar">
						<span class="webhook-tip">调试 URL</span>
						<el-tooltip placement="top-start" trigger="focus" :visible-arrow="false" popper-class="webhook-tip-popper">
							<template #content>
								<div class="webhook-tip-text">Webhook 接口的 URL 应由接口使用者提供。此处填写的 URL 仅用于调试，不会显示在接口文档中。</div>
							</template>
							<el-input v-model="req.webhook_url" placeholder="调试 URL，可为空（留空使用接口路径）" size="small" />
						</el-tooltip>
					</div>
				</div>

				<div class="api-detail-body">
					<!-- WebSocket 调试面板（对齐 Apifox：Message/Params/设置） -->
					<div v-if="req.protocol === 'websocket'" class="ws-panel">
						<el-tabs v-model="wsTab" class="apifox-tabs" style="height: 100%">
							<el-tab-pane label="Message" name="message">
								<div class="ws-msg-editor">
									<div class="ws-format-row">
										<el-select v-model="wsFormat" style="width: 120px" size="small">
											<el-option v-for="ft in ['Text', 'JSON', 'XML', 'HTML', 'Binary']" :key="ft" :label="ft" :value="ft" />
										</el-select>
										<el-select v-if="wsFormat === 'Binary'" v-model="wsBinaryType" style="width: 132px" size="small">
											<el-option label="Base64" value="base64" />
											<el-option label="Hexadecimal" value="hex" />
										</el-select>
									</div>
									<el-input v-model="wsMessage" type="textarea" :rows="7" :placeholder="wsFormat === 'JSON' ? '输入 JSON 消息' : wsFormat === 'Binary' ? (wsBinaryType === 'base64' ? '输入 Base64 编码的二进制内容' : '输入十六进制内容（如 0A FF 01，可含空格）') : '输入消息内容'" />
									<div class="ws-send-options">
										<el-checkbox v-model="wsClearAfterSend">发送后清空输入</el-checkbox>
										<div style="flex:1"></div>
										<el-button type="primary" size="small" @click="wsSend">发送</el-button>
									</div>
								</div>
							</el-tab-pane>
							<el-tab-pane label="Params" name="params">
								<div style="overflow: auto; height: 100%">
									<div class="ws-params-head">
										<span style="width: 28px"></span>
										<span>参数名</span>
										<span>参数值</span>
										<span>类型</span>
										<span>说明</span>
										<span style="width: 48px"></span>
									</div>
									<div v-for="(p, i) in req.params" :key="i" class="ws-params-row">
										<el-checkbox v-model="p.status" />
										<el-input v-model="p.key" placeholder="参数名" size="small" />
										<el-input v-model="p.value" placeholder="参数值" size="small" />
										<el-select v-model="p.type" size="small" style="width: 110px">
											<el-option v-for="t in paramTypes" :key="t" :label="t" :value="t" />
										</el-select>
										<el-input v-model="p.desc" placeholder="说明" size="small" />
										<el-button type="danger" link size="small" @click="removeParam(i)">删除</el-button>
									</div>
									<div class="kv-actions">
										<el-button type="primary" link size="small" @click="addParam">+ 添加参数</el-button>
										<el-button type="primary" link size="small" @click="openBulkEdit('params')">批量编辑</el-button>
									</div>
								</div>
							</el-tab-pane>
							<el-tab-pane label="设置" name="settings">
								<div style="overflow: auto; height: 100%">
									<div class="ws-config-row">
										<span class="ws-config-label">SSL 证书验证</span>
										<el-switch v-model="req.config.ssl_verify" />
									</div>
									<div class="ws-config-row">
										<span class="ws-config-label">连接超时（秒）</span>
										<el-input-number v-model="req.config.req_timeout" :min="1" :max="120" size="small" style="width: 120px" />
									</div>
									<div class="ws-config-tip">SSL 验证关闭后，wss:// 连接将不校验服务端证书（仅用于调试环境）。</div>
								</div>
							</el-tab-pane>
						</el-tabs>
						<!-- 返回响应 -->
						<div class="ws-response">
							<div class="ws-response-title">返回响应</div>
							<div class="ws-history">
								<div v-for="(m, i) in wsMessages" :key="i" class="ws-msg" :class="m.dir">
									<span class="ws-msg-time">{{ m.time }}</span>
									<span class="ws-msg-tag" :class="m.dir">{{ m.dir === 'sent' ? '发送' : '接收' }}</span>
									<pre class="ws-msg-content">{{ m.content }}</pre>
								</div>
								<el-empty v-if="!wsMessages.length" description="暂无消息：输入消息点「发送」调试" :image-size="50" />
							</div>
						</div>
					</div>
					<!-- 请求区 -->
					<div v-if="req.protocol !== 'websocket'" class="request-section" :style="resCollapsed ? 'flex: 1 1 auto' : ''">
						<div class="panel-card">
							<el-tabs v-model="req_active" class="apifox-tabs" style="height: 100%">
								<!-- Params -->
								<el-tab-pane name="params">
									<template #label>
										<el-badge :show-zero="false" :value="req.params.length" :offset="[13, 2]" type="danger">Params</el-badge>
									</template>
									<div style="overflow: auto; height: 100%">
										<div v-for="(p, i) in req.params" :key="i" style="display:flex;align-items:center;gap:6px;margin-bottom:6px">
											<el-checkbox v-model="p.status" />
											<el-input v-model="p.key" placeholder="参数名" style="flex:1" size="small" />
											<el-input v-model="p.value" placeholder="参数值" style="flex:1" size="small" />
											<el-button type="danger" link size="small" @click="removeParam(i)">删除</el-button>
										</div>
										<div class="kv-actions">
											<el-button type="primary" link size="small" @click="addParam">+ 添加参数</el-button>
											<el-button type="primary" link size="small" @click="openBulkEdit('params')">批量编辑</el-button>
										</div>
									</div>
								</el-tab-pane>
								<!-- Header -->
								<el-tab-pane name="header">
									<template #label>
										<el-badge :show-zero="false" :value="req.header.length" :offset="[13, 2]" type="danger">Header</el-badge>
									</template>
									<div style="overflow: auto; height: 100%">
										<div v-for="(h, i) in req.header" :key="i" style="display:flex;align-items:center;gap:6px;margin-bottom:6px">
											<el-checkbox v-model="h.status" />
											<el-input v-model="h.name" placeholder="Header名" style="flex:1" size="small" />
											<el-input v-model="h.value" placeholder="Header值" style="flex:1" size="small" />
											<el-button type="danger" link size="small" @click="removeHeader(i)">删除</el-button>
										</div>
										<div class="kv-actions">
											<el-button type="primary" link size="small" @click="addHeader">+ 添加Header</el-button>
											<el-button type="primary" link size="small" @click="openBulkEdit('header')">批量编辑</el-button>
										</div>
									</div>
								</el-tab-pane>
								<!-- Body -->
								<el-tab-pane label="Body" name="body">
									<div class="body-pane">
										<div class="body-type-bar">
											<span v-for="bt in bodyTypes" :key="bt.value" class="body-type-item" :class="{ active: req.body_type === bt.value }" @click="req.body_type = bt.value">{{ bt.label }}</span>
										</div>
										<div class="body-content">
											<div v-if="req.body_type === 1" class="body-empty">该请求没有 Body</div>
											<div v-else-if="req.body_type === 2" class="body-editor">
												<div class="code-editor-wrap" style="height:100%">
													<div class="code-editor-lang">JSON</div>
													<div class="json-editor-inner">
														<JsonEditor v-model:value="req.body" height="100%" />
													</div>
												</div>
											</div>
											<div v-else-if="req.body_type === 3" class="body-kv">
												<div class="kv-header"><span class="kv-col-check"></span><span class="kv-col-key">参数名</span><span class="kv-col-val">参数值</span><span class="kv-col-act"></span></div>
												<div v-for="(f, i) in req.form_data" :key="i" class="kv-row">
													<el-checkbox v-model="f.status" class="kv-col-check" />
													<el-input v-model="f.key" placeholder="参数名" class="kv-col-key" size="small" />
													<el-input v-model="f.value" placeholder="参数值" class="kv-col-val" size="small" />
													<el-button type="danger" link size="small" class="kv-col-act" @click="removeFormData(i)">删除</el-button>
												</div>
												<div class="kv-actions">
													<el-button type="primary" link size="small" @click="addFormData">+ 添加参数</el-button>
													<el-button type="primary" link size="small" @click="openBulkEdit('form_data')">批量编辑</el-button>
												</div>
											</div>
											<div v-else-if="req.body_type === 4" class="body-kv">
												<div class="kv-header"><span class="kv-col-check"></span><span class="kv-col-key">参数名</span><span class="kv-col-val">参数值</span><span class="kv-col-act"></span></div>
												<div v-for="(f, i) in req.form_urlencoded" :key="i" class="kv-row">
													<el-checkbox v-model="f.status" class="kv-col-check" />
													<el-input v-model="f.key" placeholder="参数名" class="kv-col-key" size="small" />
													<el-input v-model="f.value" placeholder="参数值" class="kv-col-val" size="small" />
													<el-button type="danger" link size="small" class="kv-col-act" @click="removeFormUrlencoded(i)">删除</el-button>
												</div>
												<div class="kv-actions">
													<el-button type="primary" link size="small" @click="addFormUrlencoded">+ 添加参数</el-button>
													<el-button type="primary" link size="small" @click="openBulkEdit('form_urlencoded')">批量编辑</el-button>
												</div>
											</div>
											<div v-else-if="req.body_type === 5" class="body-binary">
												<el-upload :show-file-list="false" :limit="1" :http-request="uploadBinaryFile">
													<el-button type="primary" plain size="small">选择文件并上传</el-button>
												</el-upload>
												<div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:6px">
													<el-tag v-for="(file, i) in req.file_path" :key="file+i" type="success" closable @close="req.file_path.splice(i,1)">{{ file }}</el-tag>
												</div>
											</div>
											<div v-else-if="req.body_type === 6" class="body-editor">
												<div class="code-editor-wrap">
													<div class="code-editor-lang">XML</div>
													<textarea v-model="req.xml_body" class="code-textarea" placeholder="请输入 XML 内容" spellcheck="false"></textarea>
												</div>
											</div>
											<div v-else-if="req.body_type === 7" class="body-editor">
												<div class="code-editor-wrap">
													<div class="code-editor-lang">Text</div>
													<textarea v-model="req.text_body" class="code-textarea" placeholder="请输入纯文本内容" spellcheck="false"></textarea>
												</div>
											</div>
											<div v-else-if="req.body_type === 8" class="body-editor">
												<div class="code-editor-wrap" style="flex:1">
													<div class="code-editor-lang">GraphQL · Query</div>
													<textarea v-model="req.graphql_query" class="code-textarea" placeholder="请输入 GraphQL Query" spellcheck="false" style="flex:1"></textarea>
												</div>
												<div class="code-editor-wrap" style="margin-top:8px">
													<div class="code-editor-lang">Variables · JSON</div>
													<textarea v-model="req.graphql_variables" class="code-textarea" placeholder='{"key": "value"}' spellcheck="false" style="min-height:80px"></textarea>
												</div>
											</div>
										</div>
									</div>
								</el-tab-pane>
								<!-- Cookies -->
								<el-tab-pane name="cookies">
									<template #label>
										<el-badge :show-zero="false" :value="req.cookies ? req.cookies.length : 0" :offset="[13, 2]" type="danger">Cookies</el-badge>
									</template>
									<div style="overflow:auto;height:100%">
										<div v-for="(c, i) in (req.cookies || [])" :key="i" style="display:flex;align-items:center;gap:6px;margin-bottom:6px">
											<el-checkbox v-model="c.status" />
											<el-input v-model="c.name" placeholder="Cookie 名称" style="width:30%" size="small" />
											<el-input v-model="c.value" placeholder="Cookie 值" style="width:40%" size="small" />
											<el-input v-model="c.domain" placeholder="Domain（可选）" style="width:20%" size="small" />
											<el-button type="danger" link size="small" @click="removeCookie(i)">删除</el-button>
										</div>
										<div class="kv-actions">
											<el-button type="primary" link size="small" @click="addCookie">+ 添加 Cookie</el-button>
											<el-button type="primary" link size="small" @click="openBulkEdit('cookies')">批量编辑</el-button>
										</div>
									</div>
								</el-tab-pane>
								<!-- Auth -->
								<el-tab-pane name="auth">
									<template #label><span>Auth</span></template>
									<div style="padding:8px 0; max-height:100%; overflow:auto">
										<el-form label-width="130px">
											<el-form-item label="认证类型：">
												<el-select v-model="req.auth_type" style="width:280px" placeholder="请选择认证类型">
													<el-option label="无认证" value="none" />
													<el-option label="Bearer Token" value="bearer" />
													<el-option label="JWT Bearer" value="jwt" />
													<el-option label="Basic Auth" value="basic" />
													<el-option label="Digest Auth" value="digest" />
													<el-option label="API Key" value="apikey" />
													<el-option label="OAuth 2.0" value="oauth2" />
												</el-select>
											</el-form-item>

											<template v-if="req.auth_type === 'bearer'">
												<el-form-item label="Token：">
													<el-input v-model="req.auth_token" placeholder="支持 {{变量}}，如 {{token}}" style="width:420px" />
												</el-form-item>
												<el-form-item label="前缀：">
													<el-input v-model="req.auth_prefix" placeholder="默认 Bearer，可留空" style="width:200px" />
												</el-form-item>
											</template>

											<template v-if="req.auth_type === 'jwt'">
												<el-form-item label="Token 来源：">
													<el-radio-group v-model="req.auth_jwt_mode">
														<el-radio value="token">使用已有 Token</el-radio>
														<el-radio value="generate">本地签发 JWT</el-radio>
													</el-radio-group>
												</el-form-item>
												<template v-if="req.auth_jwt_mode !== 'generate'">
													<el-form-item label="JWT Token：">
														<el-input v-model="req.auth_token" type="textarea" :rows="3" placeholder="粘贴 JWT，支持 {{变量}}" style="width:480px" />
													</el-form-item>
												</template>
												<template v-else>
													<el-form-item label="算法：">
														<el-select v-model="req.auth_jwt_alg" style="width:200px">
															<el-option v-for="a in jwtAlgOptions" :key="a" :label="a" :value="a" />
														</el-select>
													</el-form-item>
													<el-form-item label="Secret / 私钥：">
														<el-input v-model="req.auth_jwt_secret" type="textarea" :rows="3" placeholder="HS* 填密钥；RS*/ES* 填 PEM 私钥" style="width:480px" />
													</el-form-item>
													<el-form-item label="Payload：">
														<el-input v-model="req.auth_jwt_payload" type="textarea" :rows="5" placeholder='{"sub":"user","exp":1710000000}' style="width:480px" />
													</el-form-item>
													<el-form-item label="Header（可选）：">
														<el-input v-model="req.auth_jwt_headers" type="textarea" :rows="2" placeholder='{"typ":"JWT"}' style="width:480px" />
													</el-form-item>
												</template>
												<el-form-item label="前缀：">
													<el-input v-model="req.auth_prefix" placeholder="默认 Bearer" style="width:200px" />
												</el-form-item>
											</template>

											<template v-if="req.auth_type === 'basic' || req.auth_type === 'digest'">
												<el-form-item label="用户名：">
													<el-input v-model="req.auth_username" placeholder="请输入用户名，支持 {{变量}}" style="width:320px" />
												</el-form-item>
												<el-form-item label="密码：">
													<el-input v-model="req.auth_password" placeholder="请输入密码，支持 {{变量}}" type="password" show-password style="width:320px" />
												</el-form-item>
											</template>

											<template v-if="req.auth_type === 'apikey'">
												<el-form-item label="Key：">
													<el-input v-model="req.auth_key" placeholder="如 X-API-KEY / api_key" style="width:320px" />
												</el-form-item>
												<el-form-item label="Value：">
													<el-input v-model="req.auth_value" placeholder="支持 {{变量}}" style="width:320px" />
												</el-form-item>
												<el-form-item label="添加到：">
													<el-radio-group v-model="req.auth_in">
														<el-radio value="header">Header</el-radio>
														<el-radio value="query">Query Params</el-radio>
													</el-radio-group>
												</el-form-item>
											</template>

											<template v-if="req.auth_type === 'oauth2'">
												<el-form-item label="Grant Type：">
													<el-select v-model="req.auth_oauth_grant" style="width:280px">
														<el-option label="Access Token（已有令牌）" value="access_token" />
														<el-option label="Client Credentials" value="client_credentials" />
														<el-option label="Password Credentials" value="password" />
													</el-select>
												</el-form-item>
												<template v-if="req.auth_oauth_grant === 'access_token'">
													<el-form-item label="Access Token：">
														<el-input v-model="req.auth_oauth_access_token" type="textarea" :rows="2" placeholder="支持 {{access_token}}" style="width:480px" />
													</el-form-item>
												</template>
												<template v-else>
													<el-form-item label="Token URL：">
														<el-input v-model="req.auth_oauth_token_url" placeholder="https://auth.example.com/oauth/token" style="width:480px" />
													</el-form-item>
													<el-form-item label="Client ID：">
														<el-input v-model="req.auth_oauth_client_id" style="width:320px" />
													</el-form-item>
													<el-form-item label="Client Secret：">
														<el-input v-model="req.auth_oauth_client_secret" type="password" show-password style="width:320px" />
													</el-form-item>
													<el-form-item label="Scope：">
														<el-input v-model="req.auth_oauth_scope" placeholder="可选，多个用空格分隔" style="width:320px" />
													</el-form-item>
													<el-form-item label="Client 认证：">
														<el-radio-group v-model="req.auth_oauth_client_auth">
															<el-radio value="basic">Basic Auth Header</el-radio>
															<el-radio value="body">Request Body</el-radio>
														</el-radio-group>
													</el-form-item>
													<template v-if="req.auth_oauth_grant === 'password'">
														<el-form-item label="用户名：">
															<el-input v-model="req.auth_username" style="width:320px" />
														</el-form-item>
														<el-form-item label="密码：">
															<el-input v-model="req.auth_password" type="password" show-password style="width:320px" />
														</el-form-item>
													</template>
												</template>
												<el-form-item label="前缀：">
													<el-input v-model="req.auth_prefix" placeholder="默认 Bearer" style="width:200px" />
												</el-form-item>
											</template>

											<div v-if="req.auth_type && req.auth_type !== 'none'" class="auth-hint">
												发送请求时会自动写入 Authorization / 指定 Header 或 Query；支持环境变量替换。
											</div>
										</el-form>
									</div>
								</el-tab-pane>
								<el-tab-pane name="before">
									<template #label>
										<el-badge :show-zero="false" :value="beforeCount" :offset="[10, 2]" type="danger">前置操作</el-badge>
									</template>
									<div v-if="inheritBefore.length && req.inherit_before_first !== false" class="inherit-bar inherit-drop" @dragover.prevent @drop.prevent="req.inherit_before_first = false">
										<div class="inherit-info inherit-click" @click="showInheritBefore = !showInheritBefore">
											<span class="inherit-label">继承父级</span>
											<el-tag v-for="(op, i) in inheritBefore" :key="i" size="small" type="info" effect="plain" style="margin-right:4px">{{ opLabel(op) }}</el-tag>
											<span class="inherit-muted">（{{ inheritBefore.length }} 个操作，来自根目录/父级目录）</span>
											<el-icon class="inherit-arrow" :style="{ transform: showInheritBefore ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform .2s' }"><ArrowRight /></el-icon>
										</div>
										<div class="inherit-drop-hint">拖动手动操作到此处 = 手动先执行</div>
									</div>
									<div v-if="showInheritBefore && inheritBefore.length" class="inherit-detail">
										<div v-for="(op, i) in inheritBefore" :key="i" class="inherit-op">
											<div class="inherit-op-title">
												<el-checkbox size="small" style="margin-right:6px" :model-value="!isBeforeExcluded(op)" @change="(v: any) => toggleBeforeExclude(op, v)" />
												{{ opLabel(op) }} <span class="inherit-muted">{{ langLabel(op.language) }}</span>
												<span style="flex:1"></span>
												<el-tooltip content="在子级默认开启，可以设为跟随父级" placement="top">
													<el-switch size="small" :model-value="op.follow_parent !== false" @change="(v: boolean) => op.follow_parent = v" />
												</el-tooltip>
											</div>
											<pre v-if="op.code" class="inherit-op-code">{{ op.code }}</pre>
											<div v-else class="inherit-op-meta">{{ JSON.stringify(op).slice(0, 200) }}</div>
										</div>
									</div>
									<div class="op-scroll-wrap">
										<OperationPanel
											:items="req.before"
											:hide-empty="inheritBefore.length > 0"
											mode="before"
											:env-list="env_list"
											:tree-list="tree_list"
											:db-list="effectiveDbList"
											:script-list="scriptList"
											:res-type-list="res_type_list"
											:val-type-list="val_type_list"
											@refresh-scripts="loadScriptList"
											@refresh-dbs="loadLocalDbList"
										/>
									</div>
								</el-tab-pane>

								<div v-if="inheritBefore.length && req.inherit_before_first === false" class="inherit-bar inherit-drop" style="margin-top:8px" @dragover.prevent @drop.prevent="req.inherit_before_first = true">
									<div class="inherit-info inherit-click" @click="showInheritBefore = !showInheritBefore">
										<span class="inherit-label">继承父级（后执行）</span>
										<el-tag v-for="(op, i) in inheritBefore" :key="i" size="small" type="info" effect="plain" style="margin-right:4px">{{ opLabel(op) }}</el-tag>
										<span class="inherit-muted">（{{ inheritBefore.length }} 个操作）</span>
										<el-icon class="inherit-arrow" :style="{ transform: showInheritBefore ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform .2s' }"><ArrowRight /></el-icon>
									</div>
									<div class="inherit-switch">
										<span class="inherit-muted">执行父级前置操作</span>
										<el-switch v-model="req.inherit_before" />
									</div>
									<div class="inherit-drop-hint">拖动手动操作到此处 = 继承先执行（恢复默认）</div>
								</div>

<!-- 后置操作 -->
<el-tab-pane name="after">
<template #label>
<el-badge :show-zero="false" :value="afterCount" :offset="[10, 2]" type="danger">后置操作</el-badge>
</template>
<div v-if="inheritAfter.length" class="inherit-bar">
<div class="inherit-info inherit-click" @click="showInheritAfter = !showInheritAfter">
<span class="inherit-label">继承父级</span>
<el-tag v-for="(op, i) in inheritAfter" :key="i" size="small" type="info" effect="plain" style="margin-right:4px">{{ opLabel(op) }}</el-tag>
<span class="inherit-muted">（{{ inheritAfter.length }} 个操作，来自根目录/父级目录）</span>
<el-icon class="inherit-arrow" :style="{ transform: showInheritAfter ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform .2s' }"><ArrowRight /></el-icon>
</div>

</div>
<div v-if="showInheritAfter && inheritAfter.length" class="inherit-detail">
<div v-for="(op, i) in inheritAfter" :key="i" class="inherit-op">
<div class="inherit-op-title">
<el-checkbox size="small" style="margin-right:6px" :model-value="!isAfterExcluded(op)" @change="(v: any) => toggleAfterExclude(op, v)" />
{{ opLabel(op) }} <span class="inherit-muted">{{ langLabel(op.language) }}</span>
<span style="flex:1"></span>
<el-tooltip content="在子级默认开启，可以设为跟随父级" placement="top">
<el-switch size="small" :model-value="op.follow_parent !== false" @change="(v: boolean) => op.follow_parent = v" />
</el-tooltip>
</div>
<pre v-if="op.code" class="inherit-op-code">{{ op.code }}</pre>
<div v-else class="inherit-op-meta">{{ JSON.stringify(op).slice(0, 200) }}</div>
</div>
</div>
<div class="op-scroll-wrap">
<OperationPanel
:items="req.after"
:hide-empty="inheritAfter.length > 0"
mode="after"
:env-list="env_list"
:tree-list="tree_list"
:db-list="effectiveDbList"
:script-list="scriptList"
:res-type-list="res_type_list"
:val-type-list="val_type_list"
@refresh-scripts="loadScriptList"
@refresh-dbs="loadLocalDbList"
/>
</div>
</el-tab-pane>

<!-- 断言 -->
<el-tab-pane name="assert">
<template #label>
<el-badge :show-zero="false" :value="req.assert.length" :offset="[10, 2]" type="danger">断言</el-badge>
</template>
<div class="op-scroll-wrap">
<OperationPanel
:items="req.assert"
mode="assert"
:db-list="effectiveDbList"
:res-type-list="res_type_list"
:val-type-list="val_type_list"
@refresh-dbs="loadLocalDbList"
/>
</div>
</el-tab-pane>

								<!-- 配置 -->
								<el-tab-pane label="配置" name="config">
									<div>
										<el-form v-model="req.config" label-position="right">
											<el-form-item label="重试次数(次)："><el-input-number v-model="req.config.retry"></el-input-number></el-form-item>
											<el-form-item label="接口连接超时(秒)："><el-input-number v-model="req.config.req_timeout"></el-input-number></el-form-item>
											<el-form-item label="结果读取超时(秒)："><el-input-number v-model="req.config.res_timeout"></el-input-number></el-form-item>
										</el-form>
									</div>
								</el-tab-pane>
								<!-- 设置 -->
								<el-tab-pane label="设置" name="settings">
									<div class="settings-pane">
										<div class="settings-item">
											<div class="settings-label">
												<span>SSL 证书验证</span>
												<el-tooltip content="关闭后跳过 HTTPS 证书校验，适用于自签名证书环境" placement="top">
													<el-icon class="settings-help"><InfoFilled /></el-icon>
												</el-tooltip>
											</div>
											<div style="display:flex;align-items:center;gap:10px">
												<el-button link size="small" style="color:#409eff;font-size:12px" @click="certDialogVisible=true">证书管理</el-button>
												<el-switch v-model="req.config.ssl_verify" />
											</div>
										</div>
										<div class="settings-item">
											<div class="settings-label">
												<span>自动跟随重定向</span>
												<el-tooltip content="开启后自动跟随 3xx 重定向响应" placement="top">
													<el-icon class="settings-help"><InfoFilled /></el-icon>
												</el-tooltip>
											</div>
											<el-switch v-model="req.config.allow_redirects" />
										</div>
										<div class="settings-item">
											<div class="settings-label">
												<span>URL 编码</span>
												<el-tooltip content="开启后对 URL 中的特殊字符进行编码" placement="top">
													<el-icon class="settings-help"><InfoFilled /></el-icon>
												</el-tooltip>
											</div>
											<el-switch v-model="req.config.url_encode" />
										</div>
									</div>
								</el-tab-pane>
							</el-tabs>
						</div>
					</div>

				
				<el-dialog v-model="bulkEditVisible" title="批量编辑" width="560px" destroy-on-close append-to-body>
					<div class="bulk-mode">
						<el-radio-group v-model="bulkEditMode" size="small">
							<el-radio-button value="comma">逗号模式</el-radio-button>
							<el-radio-button value="colon">冒号模式</el-radio-button>
						</el-radio-group>
						<span class="bulk-hint">{{ bulkEditMode === 'comma' ? '格式：参数名,类型,必需,默认值,默认启用,说明' : '格式：参数名:默认值' }}</span>
					</div>
					<el-input v-model="bulkEditText" type="textarea" :rows="9" :placeholder="bulkEditPlaceholder" spellcheck="false" />
					<div class="bulk-foot-hint">
						<template v-if="bulkEditMode === 'comma'">
							数据格式遵循
							<el-popover placement="bottom-start" trigger="click" width="560">
								<template #reference>
									<a class="bulk-csv-link">《标准 CSV 规范》</a>
								</template>
								<div class="bulk-csv-rules">
									<div class="bulk-csv-title">CSV 六列格式</div>
									<div v-for="r in bulkCsvRules" :key="r[0]" class="bulk-csv-row"><b>{{ r[0] }}</b><span>{{ r[1] }}</span></div>
									<div class="bulk-csv-divider"></div>
									<div class="bulk-csv-title">CSV 格式规范（RFC 4180）</div>
									<div v-for="(s, i) in bulkCsvSpecs" :key="i" class="bulk-csv-spec">
										<div class="bulk-csv-desc"><b>{{ i + 1 }}.</b> {{ s.desc }}</div>
										<code class="bulk-csv-code">{{ s.code }}</code>
									</div>
								</div>
							</el-popover>
							，字段之间以英文逗号(,)分隔，多条记录以换行分隔
						</template>
						<template v-else>字段之间以英文冒号(:)分隔，多条记录以换行分隔</template>
					</div>
					<template #footer>
						<el-button @click="bulkEditVisible = false">取消</el-button>
						<el-button type="primary" @click="confirmBulkEdit">确定</el-button>
					</template>
				</el-dialog>

				
				<el-dialog v-model="saveCaseDialogVisible" title="保存为测试用例" width="560px" destroy-on-close>
					<el-form :model="saveCaseForm" label-width="80px">
						<el-form-item label="用例名称" required>
							<el-input v-model="saveCaseForm.name" placeholder="请输入用例名称" />
						</el-form-item>
						<el-form-item label="用例类型">
							<el-radio-group v-model="saveCaseForm.case_type">
								<el-radio-button v-for="t in caseTypeOptions" :key="t.value" :value="t.value">{{ t.label }}</el-radio-button>
							</el-radio-group>
						</el-form-item>
						<el-form-item label="描述">
							<el-input v-model="saveCaseForm.description" type="textarea" :rows="2" placeholder="可选" />
						</el-form-item>
						<el-form-item label="用例集" required>
							<div v-loading="saveCaseLoading" style="width:100%;min-height:40px">
								<div v-if="!saveCaseLoading && !saveCaseSuiteTree.length" style="display:flex;align-items:center;gap:8px;color:var(--el-text-color-placeholder);font-size:13px">
									<span>该服务暂无用例集，请先在用例管理中创建</span>
									<el-button link size="small" @click="reloadSuiteTree">刷新</el-button>
								</div>
								<el-tree
									v-if="!saveCaseLoading && saveCaseSuiteTree.length"
									:data="saveCaseSuiteTree"
									:props="{ label: 'name', children: 'children' }"
									node-key="id"
									highlight-current
									default-expand-all
									:expand-on-click-node="false"
									style="border:1px solid var(--el-border-color);border-radius:6px;padding:6px;max-height:220px;overflow-y:auto"
									@node-click="(d:any) => saveCaseForm.suite_id = d.id"
								>
									<template #default="{ data }">
										<span :style="saveCaseForm.suite_id===data.id?'color:#409eff;font-weight:600':''">
											<el-icon style="margin-right:4px;color:#f39c12"><Folder /></el-icon>{{ data.name }}
										</span>
									</template>
								</el-tree>
								<div v-if="saveCaseForm.suite_id" style="margin-top:6px;font-size:12px;color:#409eff">
									已选用例集 ID: {{ saveCaseForm.suite_id }}
								</div>
							</div>
						</el-form-item>
					</el-form>
					<template #footer>
						<el-button @click="saveCaseDialogVisible=false">取消</el-button>
						<el-button type="primary" :loading="saveCaseSubmitting" @click="confirmSaveAsCase">保存</el-button>
					</template>
				</el-dialog>

				<!-- 证书管理对话框 -->
				<el-dialog v-model="certDialogVisible" title="证书管理" width="600px" destroy-on-close>
					<div v-if="certPage === 'list'">
						<div style="margin-bottom:12px">
							<div style="font-size:13px;font-weight:600;margin-bottom:8px">CA 证书</div>
							<div style="display:flex;align-items:center;gap:10px">
								<el-switch v-model="caEnabled" />
								<span style="font-size:12px;color:#606266">{{ caEnabled ? '已启用自定义 CA 证书' : '使用系统默认 CA 证书' }}</span>
								<el-upload v-if="caEnabled" :show-file-list="false" accept=".pem,.crt,.cer" :http-request="() => {}" :on-change="onCaFileChange">
									<el-button size="small" type="primary" plain>选择 CA 文件</el-button>
								</el-upload>
								<span v-if="caFileName" style="font-size:12px;color:#67c23a">{{ caFileName }}</span>
							</div>
						</div>
						<el-divider />
						<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
							<span style="font-size:13px;font-weight:600">客户端证书</span>
							<el-button size="small" type="primary" @click="certPage='add'">+ 添加证书</el-button>
						</div>
						<el-table :data="clientCerts" border size="small" empty-text="暂无客户端证书">
							<el-table-column prop="host" label="域名" min-width="140" />
							<el-table-column prop="port" label="端口" width="70" />
							<el-table-column label="证书类型" width="90">
								<template #default="{ row }">
									<el-tag size="small" :type="row.pfx ? 'warning' : 'primary'">{{ row.pfx ? 'PFX' : 'PEM' }}</el-tag>
								</template>
							</el-table-column>
							<el-table-column label="操作" width="70" align="center">
								<template #default="{ _, $index }">
									<el-button type="danger" link size="small" @click="clientCerts.splice($index, 1)">删除</el-button>
								</template>
							</el-table-column>
						</el-table>
					</div>
					<div v-else>
						<el-form label-width="90px">
							<el-form-item label="域名" required>
								<div style="display:flex;align-items:center;gap:6px;width:100%">
									<el-input v-model="newCert.host" placeholder="example.com" style="flex:1" />
									<span style="color:#909399">:</span>
									<el-input v-model="newCert.port" placeholder="443" style="width:80px" />
								</div>
							</el-form-item>
							<el-form-item label="CRT 文件">
								<el-input v-model="newCert.crt" placeholder="证书文件路径（.crt / .pem）" />
							</el-form-item>
							<el-form-item label="KEY 文件">
								<el-input v-model="newCert.key" placeholder="私钥文件路径（.key）" />
							</el-form-item>
							<el-form-item label="PFX 文件">
								<el-input v-model="newCert.pfx" placeholder="PFX/P12 文件路径（可选，替代 CRT+KEY）" />
							</el-form-item>
							<el-form-item label="密钥">
								<el-input v-model="newCert.passphrase" type="password" show-password placeholder="证书密钥（可选）" />
							</el-form-item>
						</el-form>
					</div>
					<template #footer>
						<template v-if="certPage === 'list'">
							<el-button @click="certDialogVisible = false">关闭</el-button>
						</template>
						<template v-else>
							<el-button @click="certPage = 'list'">取消</el-button>
							<el-button type="primary" @click="addClientCert">添加</el-button>
						</template>
					</template>
				</el-dialog>

				<!-- 响应区 -->
				<div v-if="req.protocol !== 'websocket'" class="response-section" :class="{ 'response-section--collapsed': resCollapsed }">
					<div class="panel-card">
						<div class="res-tab-header">
							<el-tabs v-model="res_active" class="apifox-tabs res-tabs" style="flex:1;min-width:0">
								<el-tab-pane label="Body" name="res" />
								<el-tab-pane name="res_cookies"><template #label><el-badge :show-zero="false" :value="(res.cookies||[]).length" :offset="[8,0]" type="primary" class="res-badge">Cookie</el-badge></template></el-tab-pane>
								<el-tab-pane label="Header" name="res_log" />
								<el-tab-pane label="控制台" name="res_console" />
								<el-tab-pane label="实际请求" name="res_raw" />
								<el-tab-pane name="before_res"><template #label><el-badge :show-zero="false" :value="res.before.length" :offset="[8,0]" type="danger" class="res-badge">前置操作结果</el-badge></template></el-tab-pane>
								<el-tab-pane name="after_res"><template #label><el-badge :show-zero="false" :value="res.after.length" :offset="[8,0]" type="danger" class="res-badge">后置操作结果</el-badge></template></el-tab-pane>
								<el-tab-pane name="assert_res"><template #label><el-badge :show-zero="false" :value="res.assert.length" :offset="[8,0]" type="danger" class="res-badge">断言结果</el-badge></template></el-tab-pane>
							</el-tabs>
							<div class="res-meta">
								<el-tag v-if="res.code>0" size="small" :type="res.code>=200&&res.code<300?'success':res.code>=400?'danger':'warning'" effect="light" class="res-meta-tag">{{ res.code }}</el-tag>
								<el-tag v-if="res.res_time>0" size="small" type="info" effect="plain" class="res-meta-tag">{{ res.res_time }} ms</el-tag>
								<el-tag v-if="res.size>0" size="small" type="info" effect="plain" class="res-meta-tag">{{ res.size >= 1024 ? (res.size/1024).toFixed(1)+'KB' : res.size+'B' }}</el-tag>
								<el-tooltip :content="resCollapsed ? '展开响应区' : '收起响应区'" placement="top">
									<el-button link size="small" style="margin-left:4px;color:#909399" @click="resCollapsed = !resCollapsed">
										<el-icon :style="{ transform: resCollapsed ? 'rotate(-90deg)' : 'rotate(0deg)', transition: 'transform 0.2s' }"><ArrowDown /></el-icon>
									</el-button>
								</el-tooltip>
							</div>
						</div>
						<div class="res-content">
							<template v-if="res_active==='res'">
								<div class="res-code-panel">
									<div class="res-code-toolbar">
										<button class="res-copy-btn" :class="{copied: bodyCopied}" @click="copyBody" title="复制响应内容">
											<svg v-if="!bodyCopied" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
											<svg v-else width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
											<span>{{ bodyCopied ? '已复制' : '复制' }}</span>
										</button>
									</div>
									<vue-json-pretty v-model:data="res.body" :height="resJsonHeight" :showIcon="true" :showLine="true" :virtual="true" :showSelectController="true" class="res-json-pretty" />
								</div>
							</template>
							<template v-else-if="res_active==='res_cookies'">
								<div class="res-dark-kv-panel">
									<div v-if="!(res.cookies&&res.cookies.length)" class="res-dark-empty">暂无 Cookie</div>
									<table v-else class="res-dark-kv-table">
										<thead><tr><th>Name</th><th>Value</th><th>Domain</th><th>Path</th><th>Expires</th><th>Secure</th></tr></thead>
										<tbody><tr v-for="(c,i) in res.cookies" :key="i"><td class="res-dark-key">{{ c.name }}</td><td class="res-dark-val">{{ c.value }}</td><td class="res-dark-muted">{{ c.domain||"-" }}</td><td class="res-dark-muted">{{ c.path||"/" }}</td><td class="res-dark-muted">{{ c.expires||"-" }}</td><td class="res-dark-muted">{{ c.secure?"✓":"-" }}</td></tr></tbody>
									</table>
								</div>
							</template>
							<template v-else-if="res_active==='res_log'">
								<div class="res-dark-kv-panel">
									<div v-if="!res.header||!Object.keys(res.header).length" class="res-dark-empty">暂无 Header</div>
									<table v-else class="res-dark-kv-table">
										<thead><tr><th>Name</th><th>Value</th></tr></thead>
										<tbody><tr v-for="(v,k) in res.header" :key="k"><td class="res-dark-key">{{ k }}</td><td class="res-dark-val">{{ v }}</td></tr></tbody>
									</table>
								</div>
							</template>
							<template v-else-if="res_active==='res_console'">
								<div class="res-console-panel">
									<div v-if="!(res.console&&res.console.length)" class="res-dark-empty">暂无控制台输出</div>
									<div v-for="(log,i) in (res.console||[])" :key="i" class="res-console-line" :class="'console-'+log.level">
										<div class="res-console-msg">{{ log.msg }}</div>
										<div v-if="log.output" class="res-console-detail">
											<div v-for="(ol, oi) in log.output.split('\n')" :key="oi" class="res-console-outline">{{ ol || ' ' }}</div>
										</div>
									</div>
								</div>
							</template>
							<template v-else-if="res_active==='res_raw'">
								<div class="res-raw-panel">
									<div v-if="res.raw_request" class="res-raw-meta">
										<span class="res-raw-method">{{ res.raw_request.method }}</span>
										<span class="res-raw-url">{{ res.raw_request.url }}</span>
									</div>
									<div v-if="res.raw_request && Object.keys(res.raw_request.headers||{}).length" class="res-raw-section">
										<div class="res-raw-section-title">Header</div>
										<div class="raw-header-wrap">
										<table class="res-dark-kv-table raw-header-table">
											<thead><tr><th>名称</th><th>值</th></tr></thead>
											<tbody><tr v-for="(v,k) in res.raw_request.headers" :key="k"><td class="res-dark-key">{{ k }}</td><td class="res-dark-val">{{ v }}</td></tr></tbody>
										</table>
										</div>
									</div>
									<div v-if="res.raw_request && res.raw_request.body" class="res-raw-section">
										<div class="res-raw-section-title">Body</div>
										<pre class="res-raw-body">{{ res.raw_request.body }}</pre>
									</div>
									<div class="res-raw-toolbar">
										<span v-for="lang in rawLangs" :key="lang.value" class="raw-lang-item" :class="{active: rawLang===lang.value}" @click="rawLang=lang.value">{{ lang.label }}</span>
									</div>
									<div class="res-raw-editor">
										<div v-if="!res.raw_request" class="res-dark-empty">发送请求后显示实际请求内容</div>
										<pre v-else class="res-raw-code"><code>{{ buildRawCode(res.raw_request, rawLang) }}</code></pre>
									</div>
								</div>
							</template>
							<template v-else-if="res_active==='before_res'">
								<div class="res-ops-panel">
									<div v-if="!res.before||!res.before.length" class="res-dark-empty">暂无前置操作结果</div>
									<div v-for="(b,i) in res.before" :key="i" class="res-ops-item">
										<div class="res-ops-title" :class="b.status===1?'ops-ok':'ops-fail'">
											<span class="ops-icon">{{ b.status===1?"✓":"✗" }}</span>
											<span>{{ i+1+'. '+b.message }}</span>
										</div>
										<div v-if="b.output" class="res-ops-output"><pre>{{ b.output }}</pre></div>
										<div v-if="b.type===1&&b.content" class="res-ops-body">
											<vue-json-pretty v-model:data="b.content.body" :height="160" :showIcon="true" :showLine="true" :virtual="true" :showSelectController="true" class="res-json-pretty" />
										</div>
									</div>
								</div>
							</template>
							<template v-else-if="res_active==='after_res'">
								<div class="res-ops-panel">
									<div v-if="!res.after||!res.after.length" class="res-dark-empty">暂无后置操作结果</div>
									<div v-for="(a,i) in res.after" :key="i" class="res-ops-item">
										<div class="res-ops-title" :class="a.status===1?'ops-ok':'ops-fail'">
											<span class="ops-icon">{{ a.status===1?"✓":"✗" }}</span>
											<span>{{ i+1+'. '+a.message }}</span>
										</div>
										<div v-if="a.output" class="res-ops-output"><pre>{{ a.output }}</pre></div>
									</div>
								</div>
							</template>
							<template v-else-if="res_active==='assert_res'">
								<div class="res-ops-panel">
									<div v-if="!res.assert||!res.assert.length" class="res-dark-empty">暂无断言结果</div>
									<div v-for="(a,i) in res.assert" :key="i" class="res-ops-item">
										<div class="res-ops-title" :class="a.status===1?'ops-ok':'ops-fail'">
											<span class="ops-icon">{{ a.status===1?"✓":"✗" }}</span>
											<span>{{ i+1+'. '+a.message }}</span>
										</div>
										<div v-if="a.output" class="res-ops-output"><pre>{{ a.output }}</pre></div>
									</div>
								</div>
							</template>
						</div>
					</div>
				</div>
				</div>
			</div>

			<!-- 接口文档面板 -->
			<div v-show="mainTab==='doc'" class="side-panel doc-panel">
				<ApiDocPanel :api-data="apiData" :api-id="Number(apiId || 0)" />
			</div>

			<!-- 调试记录面板 -->
			<div v-if="mainTab==='history'" class="side-panel history-side-panel">
				<ApiHistoryPanel :api-data="apiData" />
			</div>

			
			<div v-show="mainTab==='mock'" class="side-panel mock-panel">
				<div class="mock-section">
					<div class="mock-section-title">Mock 地址</div>
					<div class="mock-addr-bar">
						<code class="mock-url">{{ mockDisplayUrl }}</code>
						<el-button size="small" plain @click="copyMockUrl">复制</el-button>
					</div>
					<div class="mock-hint">
						<p>如何使用：</p>
						<ol>
							<li>复制上方地址，用 Postman / 前端请求 / curl 访问后端 Mock 服务即可拿到配置的响应。</li>
							<li>接口 URL 中的环境变量会自动剥离；地址指向后端服务（如 :8100），不是前端端口。</li>
							<li>请求按「Mock 期望」匹配；未命中时若开启自定义脚本则走脚本。</li>
						</ol>
					</div>
				</div>
				<div class="mock-section" style="margin-top:20px">
					<div class="mock-section-header">
						<span class="mock-section-title">Mock 期望</span>
						<el-button size="small" type="primary" plain @click="addMockExpect">+ 新建期望</el-button>
					</div>
					<el-table :data="mockExpects" size="small" style="margin-top:8px" empty-text="暂无期望">
						<el-table-column prop="name" label="名称" min-width="120" show-overflow-tooltip />
						<el-table-column label="条件" min-width="180" show-overflow-tooltip>
							<template #default="{ row }">{{ formatMockCondition(row) }}</template>
						</el-table-column>
						<el-table-column label="操作" width="120">
							<template #default="{ row, $index }">
								<el-button type="primary" link size="small" @click="editMockExpect(row, $index)">编辑</el-button>
								<el-button type="danger" link size="small" @click="mockExpects.splice($index,1)">删除</el-button>
							</template>
						</el-table-column>
					</el-table>
				</div>
				<div class="mock-section" style="margin-top:20px">
					<div class="mock-section-header">
						<span class="mock-section-title">Mock 脚本</span>
						<div style="display:flex;align-items:center;gap:8px">
							<span style="font-size:12px;color:var(--el-text-color-regular)">开启自定义脚本</span>
							<el-switch v-model="mockScriptEnabled" size="small" />
						</div>
					</div>
					<div v-if="mockScriptEnabled" style="margin-top:10px">
						<div class="code-editor-wrap">
							<div class="code-editor-lang">JavaScript</div>
							<textarea v-model="mockScript" class="code-textarea" placeholder="// 在此编写 Mock 脚本&#10;// 例：mock.mockResponse({ code: 200, data: {} })" spellcheck="false" style="min-height:120px"></textarea>
						</div>
					</div>
				</div>
			</div>

		
			<el-dialog v-model="mockExpectDialogVisible" :title="mockExpectEditIndex>=0?'编辑 Mock 期望':'新建 Mock 期望'" width="680px" destroy-on-close append-to-body>
				<el-form :model="newMockExpect" label-width="96px">
					<el-form-item label="名称" required>
						<el-input v-model="newMockExpect.name" placeholder="期望名称" />
					</el-form-item>
					<el-form-item label="IP 条件">
						<div style="width:100%">
							<div style="display:flex;align-items:center;gap:10px">
								<el-switch v-model="newMockExpect.ipEnabled" />
								<span style="font-size:12px;color:var(--el-text-color-placeholder)">开启后仅对指定的 IP 地址生效</span>
							</div>
							<el-input v-if="newMockExpect.ipEnabled" v-model="newMockExpect.ips" placeholder="多个 IP 用英文逗号分隔，如 127.0.0.1,192.168.1.10" style="margin-top:8px" />
						</div>
					</el-form-item>
					<el-form-item label="参数条件">
						<div style="width:100%">
							<div style="font-size:12px;color:var(--el-text-color-placeholder);margin-bottom:8px">支持 query / path / header / cookie / body；多条件为「且」关系。</div>
							<div class="mock-scroll-list mock-param-scroll">
								<div v-for="(c, idx) in newMockExpect.paramConditions" :key="idx" class="mock-param-row">
									<el-select v-model="c.location" style="width:100px">
										<el-option label="query" value="query" />
										<el-option label="path" value="path" />
										<el-option label="header" value="header" />
										<el-option label="cookie" value="cookie" />
										<el-option label="body" value="body" />
									</el-select>
									<el-input v-model="c.name" :placeholder="c.location==='body'?'字段名或 JSONPath':'参数名'" style="flex:1" />
									<el-select v-model="c.operator" style="width:110px">
										<el-option label="等于" value="eq" />
										<el-option label="不等于" value="neq" />
										<el-option label="大于" value="gt" />
										<el-option label="大于等于" value="gte" />
										<el-option label="小于" value="lt" />
										<el-option label="小于等于" value="lte" />
										<el-option label="包含" value="contains" />
										<el-option label="不包含" value="not_contains" />
										<el-option label="正则" value="regex" />
										<el-option label="存在" value="exists" />
										<el-option label="不存在" value="not_exists" />
									</el-select>
									<el-input v-if="!['exists','not_exists'].includes(c.operator)" v-model="c.value" placeholder="期望值" style="flex:1" />
									<el-button type="danger" link @click="newMockExpect.paramConditions.splice(idx,1)">删除</el-button>
								</div>
								<div v-if="!newMockExpect.paramConditions.length" class="mock-scroll-empty">暂无参数条件</div>
							</div>
							<el-button size="small" plain style="margin-top:8px" @click="newMockExpect.paramConditions.push({ location:'query', name:'', operator:'eq', value:'' })">+ 添加参数条件</el-button>
						</div>
					</el-form-item>
					<el-form-item label="状态码"><el-input-number v-model="newMockExpect.status" :min="100" :max="599" /></el-form-item>
					<el-form-item label="响应延迟">
						<div style="display:flex;align-items:center;gap:10px">
							<el-input-number v-model="newMockExpect.delay" :min="0" :max="60000" :step="100" />
							<span style="font-size:12px;color:var(--el-text-color-placeholder)">毫秒</span>
						</div>
					</el-form-item>
					<el-form-item label="响应 Headers">
						<div style="width:100%">
							<div class="mock-scroll-list mock-header-scroll">
								<div v-for="(h, idx) in newMockExpect.headers" :key="idx" class="mock-param-row">
									<el-input v-model="h.key" placeholder="Header 名" style="flex:1" />
									<el-input v-model="h.value" placeholder="Header 值" style="flex:1" />
									<el-button type="danger" link @click="newMockExpect.headers.splice(idx,1)">删除</el-button>
								</div>
								<div v-if="!newMockExpect.headers.length" class="mock-scroll-empty">暂无响应头</div>
							</div>
							<el-button size="small" plain style="margin-top:8px" @click="newMockExpect.headers.push({ key:'', value:'' })">+ 添加 Header</el-button>
						</div>
					</el-form-item>
					<el-form-item label="响应体">
						<div class="code-editor-wrap" style="width:100%">
							<div class="code-editor-lang">JSON</div>
							<textarea v-model="newMockExpect.body" class="code-textarea" placeholder='{"code":200,"data":{}}' spellcheck="false" style="min-height:100px"></textarea>
						</div>
					</el-form-item>
				</el-form>
				<template #footer>
					<el-button @click="mockExpectDialogVisible=false">取消</el-button>
					<el-button type="primary" @click="confirmAddMockExpect">确定</el-button>
				</template>
			</el-dialog>

		</el-card>
	</div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import VueJsonPretty from 'vue-json-pretty';
import JsonEditor from '/@/components/code-editor/JsonEditor.vue';
import 'vue-json-pretty/lib/styles.css';
import { ArrowDown, Operation, Clock, CircleCheck, Coin, Delete, Connection, EditPen, InfoFilled, View, Folder } from '@element-plus/icons-vue';
import { api_send, save_api, save_api_case, edit_history, apiAutomationApi } from '/@/api/v1/testing/apiAutomation';
import { useFileApi } from '/@/api/v1/common/file';
import OperationPanel from './components/OperationPanel.vue';
import ApiHistoryPanel from './components/ApiHistoryPanel.vue';
import ApiDocPanel from './components/ApiDocPanel.vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { getBaseApiUrl } from '/@/utils/config';
import { onNtestScriptsChanged } from './composables/scriptListSync';
import { onDbListChanged } from './composables/dbListSync';

const props = defineProps({
	apiData: { type: Object, default: () => ({}) },
	envId: { type: [Number, String], default: null },
	env_list: { type: Array, default: () => [] },
	tree_list: { type: Array, default: () => [] },
	redis_example_list: { type: Array, default: () => ['common'] },
	local_db_list: { type: Array, default: () => [] },
	serviceId: { type: [Number, String], default: null },
	embedded: { type: Boolean, default: false }, // 嵌入模式：隐藏顶部大 Tab
	initialTab: { type: String, default: 'debug' }, // 嵌入模式下初始显示的 Tab
});

const emit = defineEmits(['caseSaved', 'apiSaved']);
const fileApi = useFileApi();

const req_active = ref<any>('body');
const res_active = ref<any>('res');
const bodyCopied = ref(false);
const copyBody = () => {
	const text = typeof res.value.body === 'string' ? res.value.body : JSON.stringify(res.value.body, null, 2);
	navigator.clipboard?.writeText(text).then(() => {
		bodyCopied.value = true;
		setTimeout(() => { bodyCopied.value = false; }, 2000);
	});
};
const rawLang = ref('curl');
const rawLangs = [
	{ label: 'cURL', value: 'curl' },
	{ label: 'Python', value: 'python' },
	{ label: 'JavaScript', value: 'javascript' },
	{ label: 'Java', value: 'java' },
	{ label: 'Go', value: 'go' },
	{ label: 'PHP', value: 'php' },
	{ label: 'HTTP', value: 'http' },
];
const buildRawCode = (raw: any, lang: string): string => {
	if (!raw) return '';
	const method = raw.method || 'GET';
	const url = raw.url || '';
	const headers: Record<string,string> = raw.headers || {};
	const body = raw.body || '';
	const headerStr = Object.entries(headers).map(([k,v]) => `${k}: ${v}`).join('\n');
	const curlHeaders = Object.entries(headers).map(([k,v]) => `  --header '${k}: ${v}' \\`).join('\n');
	const bodyStr = typeof body === 'string' ? body : JSON.stringify(body, null, 2);
	if (lang === 'curl') {
		const bodyPart = bodyStr ? `\n  --data '${bodyStr.replace(/'/g,"'\\''")}'` : '';
		return `curl --location --request ${method} '${url}' \\\n${curlHeaders}${bodyPart}`;
	}
	if (lang === 'python') {
		const hLines = Object.entries(headers).map(([k,v]) => `    "${k}": "${v}",`).join('\n');
		const bLine = bodyStr ? `\npayload = ${bodyStr}\n` : '\npayload = None\n';
		return `import requests\n\nurl = "${url}"\nheaders = {\n${hLines}\n}\n${bLine}\nresponse = requests.request("${method}", url, headers=headers, data=payload)\nprint(response.text)`;
	}
	if (lang === 'javascript') {
		const hLines = Object.entries(headers).map(([k,v]) => `  "${k}": "${v}",`).join('\n');
		const bLine = bodyStr ? `\n  body: JSON.stringify(${bodyStr}),` : '';
		return `fetch("${url}", {\n  method: "${method}",\n  headers: {\n${hLines}\n  },${bLine}\n})\n  .then(r => r.json())\n  .then(console.log);`;
	}
	if (lang === 'java') {
		return `OkHttpClient client = new OkHttpClient();\nRequest request = new Request.Builder()\n  .url("${url}")\n  .method("${method}", ${bodyStr ? `RequestBody.create("${bodyStr}", MediaType.parse("application/json"))` : 'null'})\n  .build();\nResponse response = client.newCall(request).execute();`;
	}
	if (lang === 'go') {
		const bLine = bodyStr ? `\npayload := strings.NewReader(\`${bodyStr}\`)` : '\nvar payload io.Reader';
		return `package main\nimport (\n  "fmt"\n  "net/http"\n  "strings"\n)\nfunc main() {${bLine}\n  req, _ := http.NewRequest("${method}", "${url}", payload)\n  // add headers\n  res, _ := http.DefaultClient.Do(req)\n  defer res.Body.Close()\n  fmt.Println(res.Status)\n}`;
	}
	if (lang === 'php') {
		return `<?php\n$curl = curl_init();\ncurl_setopt_array($curl, [\n  CURLOPT_URL => "${url}",\n  CURLOPT_RETURNTRANSFER => true,\n  CURLOPT_CUSTOMREQUEST => "${method}",${bodyStr ? `\n  CURLOPT_POSTFIELDS => '${bodyStr}',` : ''}\n]);\n$response = curl_exec($curl);\ncurl_close($curl);\necho $response;`;
	}
	if (lang === 'http') {
		return `${method} ${url} HTTP/1.1\n${headerStr}${bodyStr ? '\n\n'+bodyStr : ''}`;
	}
	return JSON.stringify(raw, null, 2);
};

const directDbDialogVisible = ref(false);
const envManageDialogVisible = ref(false);

// 顶部大 Tab
const mainTab = ref(props.initialTab || 'debug');
// 嵌入模式下，父组件切换 Tab 时同步
watch(() => props.initialTab, (v) => { if (v && props.embedded) mainTab.value = v; });

// 保存为用例弹窗
const saveCaseDialogVisible = ref(false);
const saveCaseLoading = ref(false);
const saveCaseSubmitting = ref(false);
const saveCaseSuiteTree = ref<any[]>([]);
const saveCaseForm = ref<{ name: string; description: string; suite_id: number | null; case_type: number }>({
	name: '', description: '', suite_id: null, case_type: 1,
});
const caseTypeOptions = [
	{ label: '正向', value: 1 }, { label: '负向', value: 2 },
	{ label: '边界值', value: 3 }, { label: '安全性', value: 4 }, { label: '其他', value: 5 },
];



// Mock
const mockBaseUrl = computed(() => String(getBaseApiUrl() || window.location.origin).replace(/\/$/, ''));
const mockExpects = ref<any[]>([]);
const mockScriptEnabled = ref(false);
const mockScript = ref('');
const mockExpectDialogVisible = ref(false);
const mockExpectEditIndex = ref(-1);
const emptyMockExpect = () => ({
	name: '',
	ipEnabled: false,
	ips: '',
	paramConditions: [] as Array<{ location: string; name: string; operator: string; value: string }>,
	headers: [] as Array<{ key: string; value: string }>,
	body: '{"code":200,"data":{}}',
	status: 200,
	delay: 0,
	condition: '',
});
const newMockExpect = ref(emptyMockExpect());

const normalizeMockPath = (raw: string) => {
	let u = String(raw || '').trim();
	u = u.replace(/\{\{[^{}]+\}\}/g, '').replace(/\$\{[^}]+\}/g, '');
	try {
		if (/^https?:\/\//i.test(u)) {
			const parsed = new URL(u);
			u = parsed.pathname + (parsed.search || '');
		}
	} catch { /* ignore */ }
	u = u.replace(/([^:]\/)\/+/g, '$1');
	if (!u.startsWith('/')) u = `/${u}`;
	return u === '/' ? '/api/path' : u;
};
const mockDisplayUrl = computed(() => {
	const id = Number(apiId.value || 0);
	const base = `${mockBaseUrl.value}/mock${normalizeMockPath(req.value.url || '')}`;
	return id ? `${base}?_api_id=${id}` : base;
});

const formatMockCondition = (row: any) => {
	const parts: string[] = [];
	if (row.ipEnabled && row.ips?.trim()) parts.push(`IP∈[${row.ips.trim()}]`);
	const opMap: Record<string, string> = {
		eq: '等于', neq: '不等于', gt: '大于', gte: '大于等于', lt: '小于', lte: '小于等于',
		contains: '包含', not_contains: '不包含', regex: '正则', exists: '存在', not_exists: '不存在',
	};
	for (const c of row.paramConditions || []) {
		if (!c?.name) continue;
		const op = opMap[c.operator] || c.operator;
		parts.push(['exists', 'not_exists'].includes(c.operator) ? `${c.location}.${c.name} ${op}` : `${c.location}.${c.name} ${op} ${c.value ?? ''}`);
	}
	return parts.length ? parts.join(' 且 ') : (row.condition || '无条件（始终匹配）');
};

const copyMockUrl = () => {
	navigator.clipboard?.writeText(mockDisplayUrl.value).then(() => ElMessage.success('已复制'));
};
const addMockExpect = () => {
	mockExpectEditIndex.value = -1;
	newMockExpect.value = emptyMockExpect();
	mockExpectDialogVisible.value = true;
};
const editMockExpect = (row: any, index: number) => {
	mockExpectEditIndex.value = index;
	newMockExpect.value = {
		...emptyMockExpect(),
		...row,
		paramConditions: Array.isArray(row.paramConditions) ? row.paramConditions.map((c: any) => ({ ...c })) : [],
		headers: Array.isArray(row.headers) ? row.headers.map((h: any) => ({ ...h })) : [],
	};
	mockExpectDialogVisible.value = true;
};
const confirmAddMockExpect = () => {
	if (!newMockExpect.value.name) { ElMessage.warning('请填写期望名称'); return; }
	if (newMockExpect.value.ipEnabled && !String(newMockExpect.value.ips || '').trim()) {
		ElMessage.warning('已开启 IP 条件，请填写至少一个 IP 地址');
		return;
	}
	const payload = {
		...newMockExpect.value,
		paramConditions: (newMockExpect.value.paramConditions || []).filter((c) => c.name?.trim()),
		headers: (newMockExpect.value.headers || []).filter((h) => h.key?.trim()),
	};
	payload.condition = formatMockCondition(payload);
	if (mockExpectEditIndex.value >= 0) mockExpects.value[mockExpectEditIndex.value] = payload;
	else mockExpects.value.push(payload);
	mockExpectDialogVisible.value = false;
};

const scriptList = ref<any[]>([]);  // 脚本中心的脚本列表
const localDbList = ref<any[]>([]);  // 内部加载的数据库列表，优先级高于 props

// 证书管理
const certDialogVisible = ref(false);
const certPage = ref<'list'|'add'>('list');
const caEnabled = ref(false);
const caFileName = ref('');
const clientCerts = ref<any[]>([]);
const newCert = ref({ host: '', port: '443', crt: '', key: '', pfx: '', passphrase: '' });
const onCaFileChange = (file: any) => { caFileName.value = file.name; };
const addClientCert = () => {
	if (!newCert.value.host) { ElMessage.warning('请填写域名'); return; }
	clientCerts.value.push({ ...newCert.value });
	newCert.value = { host: '', port: '443', crt: '', key: '', pfx: '', passphrase: '' };
	certPage.value = 'list';
};

// 加载脚本中心的脚本列表（用于前置/后置操作的脚本库选择）
const loadScriptList = async () => {
	if (!props.serviceId) return;
	try {
		const res: any = await apiAutomationApi.ntest_script_list({ api_service_id: Number(props.serviceId) });
		scriptList.value = Array.isArray(res?.data) ? res.data : [];
	} catch { scriptList.value = []; }
};
// 内部加载数据库列表，不依赖父组件传入
const loadLocalDbList = async () => {
	try {
		const res: any = await apiAutomationApi.api_db_list({});
		const raw = res?.data;
		localDbList.value = Array.isArray(raw?.content) ? raw.content : (Array.isArray(raw) ? raw : []);
	} catch { localDbList.value = []; }
};

// 合并 prop 和内部加载的数据库列表
const effectiveDbList = computed(() => {
	const internal = localDbList.value;
	const fromProp = (props.local_db_list as any[]) || [];
	// 内部加载优先，若内部为空则用 prop
	return internal.length > 0 ? internal : fromProp;
});

const inheritBefore = ref<any[]>([]);
const inheritAfter = ref<any[]>([]);

// ---- 继承操作按操作级开关剔除（指纹与后端 _op_fingerprint 一致）----
const opFingerprint = (op: any) => {
  const payload = op.code || op.sql || op.name || op.title || ''
  return `${op.type}:${String(payload).slice(0, 64)}`
}
const isBeforeExcluded = (op: any) => (req.value.inherit_before_excludes || []).includes(opFingerprint(op))
const toggleBeforeExclude = (op: any, on: boolean) => {
  const fp = opFingerprint(op)
  const arr = req.value.inherit_before_excludes || []
  req.value.inherit_before_excludes = on ? arr.filter((x: string) => x !== fp) : [...arr, fp]
}
const isAfterExcluded = (op: any) => (req.value.inherit_after_excludes || []).includes(opFingerprint(op))
const toggleAfterExclude = (op: any, on: boolean) => {
  const fp = opFingerprint(op)
  const arr = req.value.inherit_after_excludes || []
  req.value.inherit_after_excludes = on ? arr.filter((x: string) => x !== fp) : [...arr, fp]
}

const opLabel = (op: any) => {
	if (!op || typeof op !== 'object') return '操作'
	const t = op.type
	if (t === 4 || t === 5) return '自定义脚本'
	if (t === 1 || t === 2) return '提取变量'
	if (t === 3) return `等待 ${op.wait_time ?? ''} 秒`
	if (t === 6) return `脚本库${op.func_name ? '：' + op.func_name : ''}`
	return '操作'
}

const beforeCount = computed(() => {
	// 只统计勾选启用（enabled !== false）的操作；继承操作另需未被剔除（excludes）且父级允许代入子级
	let n = (req.value.before || []).filter((op: any) => op.enabled !== false).length
	if (req.value.inherit_before !== false && inheritBefore.value.length) {
		n += inheritBefore.value.filter((op: any) => op.inherit_child !== false && !isBeforeExcluded(op)).length
	}
	return n
})
const afterCount = computed(() => {
	let n = (req.value.after || []).filter((op: any) => op.enabled !== false).length
	if (req.value.inherit_after !== false && inheritAfter.value.length) {
		n += inheritAfter.value.filter((op: any) => op.inherit_child !== false && !isAfterExcluded(op)).length
	}
	return n
})

const showInheritBefore = ref(false)
const showInheritAfter = ref(false)
const langLabel = (l: any) => (l === 'python' ? 'Python' : l === 'javascript' ? 'JavaScript' : l || '')

const req = ref({
	method: 1, url: '', params: [], header: [], body: '', body_type: 2,
	inherit_before: true, inherit_after: true,
	inherit_before_first: true, inherit_after_first: true,
	inherit_before_excludes: [], inherit_after_excludes: [],
	form_data: [], form_urlencoded: [], file_path: [],
	before: [], after: [], assert: [],
	config: { retry: 0, req_timeout: 30, res_timeout: 30, ssl_verify: true, allow_redirects: true, url_encode: false },
	xml_body: '', text_body: '', graphql_query: '', graphql_variables: '',
	cookies: [] as any[],
	auth_type: 'none',
	auth_token: '',
	auth_username: '',
	auth_password: '',
	auth_key: '',
	auth_value: '',
	auth_in: 'header',
	auth_prefix: 'Bearer',
	auth_jwt_mode: 'token',
	auth_jwt_alg: 'HS256',
	auth_jwt_secret: '',
	auth_jwt_payload: '{\n  "sub": "user"\n}',
	auth_jwt_headers: '',
	auth_oauth_grant: 'access_token',
	auth_oauth_access_token: '',
	auth_oauth_token_url: '',
	auth_oauth_client_id: '',
	auth_oauth_client_secret: '',
	auth_oauth_scope: '',
	auth_oauth_client_auth: 'basic',
});

const jwtAlgOptions = ['HS256', 'HS384', 'HS512', 'RS256', 'RS384', 'RS512', 'ES256', 'ES384', 'ES512'];

const bodyTypes = [
	{ label: 'none', value: 1 }, { label: 'form-data', value: 3 },
	{ label: 'x-www-form-urlencoded', value: 4 }, { label: 'JSON', value: 2 },
	{ label: 'XML', value: 6 }, { label: 'Text', value: 7 },
	{ label: 'Binary', value: 5 }, { label: 'GraphQL', value: 8 },
];

const res = ref({ body: {}, header: {}, before: [], after: [], assert: [], code: 0, size: 0, res_time: 0, cookies: [], console: [], raw_request: null });

const method_list = ref([
	{ name: 'GET', value: 1, color: '#67C23A' }, { name: 'POST', value: 2, color: '#409EFF' },
	{ name: 'PUT', value: 3, color: '#E6A23C' }, { name: 'DELETE', value: 4, color: '#F56C6C' },
	{ name: 'PATCH', value: 5, color: '#8E44AD' }, { name: 'OPTIONS', value: 6, color: '#909399' },
]);

const val_type_list = ref([{ name: '环境变量', value: 1 }, { name: '全局变量', value: 2 }, { name: '临时变量', value: 3 }]);
const res_type_list = ref([
	{ name: '响应结果-JSON', value: 1 }, { name: '请求-Headers', value: 2 },
	{ name: '请求-Body', value: 3 }, { name: 'Headers-响应结果', value: 4 }, { name: '自定义目标', value: 5 }
]);

const tips = ref<any>('路径示例，结果{"code":200,"info":{"username":"admin"},"list":[{"id":1},{"id":2}]}\n例子：code=$.code, username=$.info.username，数组：$.list[0].id / $.list[1].id分别等于1 / 2');

const viewportH = ref(typeof window !== 'undefined' ? window.innerHeight : 900);
const onResize = () => { viewportH.value = window.innerHeight; };
const resCollapsed = ref(false);
let offScriptListSync: (() => void) | null = null;
let offDbListSync: (() => void) | null = null;
onMounted(() => {
	window.addEventListener('resize', onResize);
	loadScriptList();
	loadLocalDbList();
	offScriptListSync = onNtestScriptsChanged((sid) => {
		if (Number(props.serviceId || 0) === sid) loadScriptList();
	});
	offDbListSync = onDbListChanged(loadLocalDbList);
});
watch(() => props.serviceId, (v) => { if (v) loadScriptList(); });
onBeforeUnmount(() => {
	window.removeEventListener('resize', onResize);
	offScriptListSync?.();
	offScriptListSync = null;
	offDbListSync?.();
	offDbListSync = null;
});

const resJsonHeight = computed(() => Math.max(120, Math.floor(viewportH.value * 0.28)));

const currentMethodColor = computed(() => {
	const m = method_list.value.find(m => m.value === req.value.method);
	return m?.color || '#409EFF';
});

const apiId = computed(() => {
	const d = props.apiData;
	const candidates = [d?.api_id, d?.api_info?.id, d?.api_info?.api_id];
	for (const c of candidates) {
		const n = Number(c);
		if (Number.isFinite(n) && n > 0) return n;
	}
	return null;
});

const lastApiId = ref<number | string | null>(null);
watch(
	() => apiId.value,
	() => {
		const newId = apiId.value;
		if (newId == null) return;
		if (lastApiId.value === newId) return;
		lastApiId.value = newId;
		const apiInfo = props.apiData?.api_info || props.apiData || {};
		const reqSrc = apiInfo.req || {};
		const resSrc = apiInfo.res || {};
		req.value = {
			protocol: reqSrc.protocol ?? 'http',
			webhook_name: reqSrc.webhook_name ?? '',
			webhook_url: reqSrc.webhook_url ?? '',
			method: reqSrc.method ?? 2, url: reqSrc.url ?? apiInfo.url ?? '',
			params: Array.isArray(reqSrc.params) ? reqSrc.params : [],
			header: Array.isArray(reqSrc.header) ? reqSrc.header.map((h: any) => ({ ...h, name: h.name ?? h.key ?? '' })) : [],
			body: typeof reqSrc.body === 'string' ? reqSrc.body : JSON.stringify(reqSrc.body != null ? reqSrc.body : {}, null, 2),
			body_type: reqSrc.body_type ?? 2,
			form_data: Array.isArray(reqSrc.form_data) ? reqSrc.form_data : [],
			form_urlencoded: Array.isArray(reqSrc.form_urlencoded) ? reqSrc.form_urlencoded : [],
			file_path: Array.isArray(reqSrc.file_path) ? reqSrc.file_path : [],
			before: Array.isArray(reqSrc.before) ? reqSrc.before : [],
			after: Array.isArray(reqSrc.after) ? reqSrc.after : [],
			inherit_before: reqSrc.inherit_before !== false,
			inherit_after: reqSrc.inherit_after !== false,
			inherit_before_first: reqSrc.inherit_before_first !== false,
			inherit_after_first: reqSrc.inherit_after_first !== false,
			inherit_before_excludes: Array.isArray(reqSrc.inherit_before_excludes) ? reqSrc.inherit_before_excludes : [],
			inherit_after_excludes: Array.isArray(reqSrc.inherit_after_excludes) ? reqSrc.inherit_after_excludes : [],
			assert: Array.isArray(reqSrc.assert) ? reqSrc.assert : [],
			config: { retry: reqSrc.config?.retry ?? 0, req_timeout: reqSrc.config?.req_timeout ?? 30, res_timeout: reqSrc.config?.res_timeout ?? 30, ssl_verify: reqSrc.config?.ssl_verify ?? true, allow_redirects: reqSrc.config?.allow_redirects ?? true, url_encode: reqSrc.config?.url_encode ?? false },
			xml_body: reqSrc.xml_body ?? '', text_body: reqSrc.text_body ?? '',
			graphql_query: reqSrc.graphql_query ?? '', graphql_variables: reqSrc.graphql_variables ?? '',
			cookies: Array.isArray(reqSrc.cookies) ? reqSrc.cookies : [],
			auth_type: reqSrc.auth_type ?? 'none',
			auth_token: reqSrc.auth_token ?? '',
			auth_username: reqSrc.auth_username ?? '',
			auth_password: reqSrc.auth_password ?? '',
			auth_key: reqSrc.auth_key ?? '',
			auth_value: reqSrc.auth_value ?? '',
			auth_in: reqSrc.auth_in ?? 'header',
			auth_prefix: reqSrc.auth_prefix ?? 'Bearer',
			auth_jwt_mode: reqSrc.auth_jwt_mode ?? 'token',
			auth_jwt_alg: reqSrc.auth_jwt_alg ?? 'HS256',
			auth_jwt_secret: reqSrc.auth_jwt_secret ?? '',
			auth_jwt_payload: reqSrc.auth_jwt_payload ?? '{\n  "sub": "user"\n}',
			auth_jwt_headers: reqSrc.auth_jwt_headers ?? '',
			auth_oauth_grant: reqSrc.auth_oauth_grant ?? 'access_token',
			auth_oauth_access_token: reqSrc.auth_oauth_access_token ?? '',
			auth_oauth_token_url: reqSrc.auth_oauth_token_url ?? '',
			auth_oauth_client_id: reqSrc.auth_oauth_client_id ?? '',
			auth_oauth_client_secret: reqSrc.auth_oauth_client_secret ?? '',
			auth_oauth_scope: reqSrc.auth_oauth_scope ?? '',
			auth_oauth_client_auth: reqSrc.auth_oauth_client_auth ?? 'basic',
		};
		res.value = { body: resSrc.body ?? {}, header: resSrc.header ?? {}, before: Array.isArray(resSrc.before) ? resSrc.before : [], after: Array.isArray(resSrc.after) ? resSrc.after : [], assert: Array.isArray(resSrc.assert) ? resSrc.assert : [], code: resSrc.code ?? 0, size: resSrc.size ?? 0, res_time: resSrc.res_time ?? 0, cookies: Array.isArray(resSrc.cookies) ? resSrc.cookies : [], console: Array.isArray(resSrc.console) ? resSrc.console : [], raw_request: resSrc.raw_request ?? null };
		inheritBefore.value = Array.isArray(apiInfo.inherit_before) ? apiInfo.inherit_before : [];
		inheritAfter.value = Array.isArray(apiInfo.inherit_after) ? apiInfo.inherit_after : [];
	},
	{ immediate: true }
);

const paramTypes = ['string', 'integer', 'boolean', 'number', 'array', 'object'];
const addParam = () => { req.value.params.push({ key: '', value: '', status: true, type: 'string', desc: '' }); };
const removeParam = (i: number) => { req.value.params.splice(i, 1); };
const addHeader = () => { req.value.header.push({ key: '', value: '', status: true }); };
const removeHeader = (i: number) => { req.value.header.splice(i, 1); };
const addFormData = () => { req.value.form_data.push({ key: '', value: '', status: true }); };
const removeFormData = (i: number) => { req.value.form_data.splice(i, 1); };
const addFormUrlencoded = () => { req.value.form_urlencoded.push({ key: '', value: '', status: true }); };
const removeFormUrlencoded = (i: number) => { req.value.form_urlencoded.splice(i, 1); };
const addCookie = () => { if (!req.value.cookies) req.value.cookies = []; req.value.cookies.push({ status: true, name: '', value: '', domain: '' }); };
const removeCookie = (i: number) => { req.value.cookies?.splice(i, 1); };

type BulkEditTarget = 'params' | 'header' | 'form_data' | 'form_urlencoded' | 'cookies';
const bulkEditVisible = ref(false);
const bulkEditTarget = ref<BulkEditTarget>('header');
const bulkEditMode = ref<'comma' | 'colon'>('comma');
const bulkEditText = ref('');
const bulkEditPlaceholder = computed(() =>
	bulkEditMode.value === 'comma'
		? '如：X-MERCHANT-ID,string,true,MCH007881,true,商户号'
		: '如：X-MERCHANT-ID:MCH007881'
);
const bulkCsvRules: [string, string][] = [
	['参数名', '参数名称（必填）'],
	['类型', 'string / integer / boolean / number / array / object'],
	['必需', 'true / false'],
	['默认值', '参数默认值（object 类型不可填）'],
	['默认启用', 'true / false'],
	['说明', '参数说明（可选）'],
];
const bulkCsvSpecs: { desc: string; code: string }[] = [
	{ desc: '文件中的各条记录必须位于不同行，其间以换行符 CRLF 分隔。例如：', code: 'aaa,bbb,ccc\nzzz,yyy,xxx' },
	{ desc: '最后一条记录的末尾可以不包括换行符。例如：', code: 'aaa,bbb,ccc\nzzz,yyy,xxx' },
	{ desc: '文件中的首条记录可以是字段名（但这不是必要的），且其所含的名称数量及存储规则须与其他记录保持一致。例如：', code: 'field_name,field_name,field_name\naaa,bbb,ccc\nzzz,yyy,xxx' },
	{ desc: '每条记录中可以包含一个或多个字段，每个字段以半角逗号分隔。文件中的所有记录必须拥有相同数量的字段。字段中的空格属于字段取值，不可忽略。每条记录的最后一个字段之后不应再添加半角逗号。例如：', code: 'aaa,bbb,ccc' },
	{ desc: '每个字段可以用半角双引号括起来（但这不一定是必要的）。如果字段没有被双引号括起来，那么字段中不应该出现双引号。例如：', code: '"aaa","bbb","ccc"\nzzz,yyy,xxx' },
	{ desc: '含有换行符、半角双引号或半角逗号的字段应该用半角双引号括起来。例如：', code: '"aaa","b\nbb","ccc"\nzzz,yyy,xxx' },
	{ desc: '如果字段被半角双引号括起来了，那么在表示字段取值中本身含有的半角双引号时，需要在其前方增加一个半角双引号。例如：', code: '"aaa","b""bb","ccc"' },
];
const BULK_TYPES = ['string', 'integer', 'boolean', 'number', 'array', 'object'];
const BULK_TRUE_SET = new Set(['true', '1', '是', 'yes', 'y']);

const openBulkEdit = (target: BulkEditTarget) => {
	bulkEditTarget.value = target;
	bulkEditMode.value = 'comma';
	const rows = getBulkRows(target) as any[];
	bulkEditText.value = rows
		.map((r: any) => {
			const key = String(r.key ?? r.name ?? '');
			const val = String(r.value ?? '');
			const type = r.type || 'string';
			const status = r.status !== false;
			const desc = String(r.desc ?? r.remark ?? '');
			return `${key},${type},true,${val},${status},${desc}`;
		})
		.join('\n');
	bulkEditVisible.value = true;
};

const parseBulkRow = (l: string) => {
	if (bulkEditMode.value === 'comma') {
		const parts = l.split(',').map((p) => p.trim());
		const row: any = { key: parts[0] || '', value: '', status: true, type: 'string', desc: '' };
		if (parts.length > 1 && BULK_TYPES.includes(parts[1].toLowerCase())) row.type = parts[1].toLowerCase();
		if (parts.length > 3) row.value = parts[3];
		if (parts.length > 4) row.status = BULK_TRUE_SET.has(parts[4].toLowerCase());
		if (parts.length > 5) row.desc = parts[5];
		return row;
	}
	const idx = l.indexOf(':');
	if (idx > 0) {
		return { key: l.slice(0, idx).trim(), value: l.slice(idx + 1).trim(), status: true, type: 'string', desc: '' };
	}
	return { key: l, value: '', status: true, type: 'string', desc: '' };
};

const confirmBulkEdit = () => {
	const lines = bulkEditText.value.split('\n').map((l) => l.trim()).filter(Boolean);
	const rows = lines.map(parseBulkRow);
	const target = bulkEditTarget.value;
	if (target === 'cookies') {
		const oldMap = new Map((req.value.cookies || []).map((c: any) => [String(c.name || ''), c]));
		req.value.cookies = rows.map((r) => ({
			status: r.status,
			name: r.key,
			value: r.value,
			domain: String(oldMap.get(r.key)?.domain || ''),
		}));
	} else {
		(req.value as any)[target] = rows.map((r: any) => ({
			key: r.key,
			value: r.value,
			status: r.status,
			type: r.type,
			desc: r.desc,
		}));
	}
	bulkEditVisible.value = false;
	ElMessage.success(`已导入 ${rows.length} 条`);
};


const addBefore = (type: number) => {
	const item: any = { type };
	if (type===1) { item.title=''; item.env_id=null; item.api_id=[]; }
	else if (type===2) { item.name=''; item.value=''; item.env_type=1; }
	else if (type===3) { item.wait_time=1; }
	else if (type===4) { item.title=''; item.code=''; }
	else if (type===5) { item.title=''; item.db_id=null; item.db_name=''; item.sql=''; item.result_var=''; }
	else if (type===6) { item.func_id=null; item.func_name=''; item.func_params=''; item.result_var=''; }
	req.value.before.push(item);
};
const removeBefore = (i: number) => { req.value.before.splice(i, 1); };

const addAfter = (type: number) => {
	const item: any = { type };
	if (type===1) { item.name=''; item.value=''; item.res_type=1; item.env_type=1; }
	else if (type===2) { item.wait_time=1; }
	else if (type===3) { item.assert_name=''; item.assert_path=''; item.assert_value=''; item.res_type=1; }
	else if (type===4) { item.title=''; item.db_id=null; item.db_name=''; item.sql=''; item.result_var=''; }
	else if (type===5) { item.code=''; }
	else if (type===6) { item.func_id=null; item.func_name=''; item.func_params=''; item.result_var=''; }
	else if (type===7) { item.import_title=''; item.env_id=null; item.api_id=[]; }
	req.value.after.push(item);
};
const removeAfter = (i: number) => { req.value.after.splice(i, 1); };

const addAssert = (type: number) => {
	const item: any = { type };
	if (type===1) { item.name=''; item.value=''; item.res_type=1; }
	else if (type===2) { item.ops_db=null; item.ops_db_table=''; item.ops_db_where=''; item.ops_db_assert=[]; }
	else if (type===3) { item.ops_redis=null; item.ops_redis_key=''; item.ops_redis_assert=[]; }
	else if (type===4) { item.local_db=null; item.local_db_table=''; item.local_db_where=''; item.local_db_assert=[]; }
	else if (type===5) { item.custom_name=''; item.custom_script=''; item.custom_expect=''; item.language='python'; }
	req.value.assert.push(item);
};
const removeAssert = (i: number) => { req.value.assert.splice(i, 1); };

const uploadBinaryFile = async (options: any) => {
	try {
		const formData = new FormData();
		formData.append('file', options.file);
		const res: any = await fileApi.uploadFile(formData);
		if (res?.data?.url) { req.value.file_path.push(res.data.url); ElMessage.success('上传成功'); }
	} catch { ElMessage.error('上传失败'); }
};

// ---- WebSocket 调试（代理往返：连接->发送->接收->断开）----
const wsTab = ref('message');
const wsFormat = ref('Text');
const wsBinaryType = ref('base64');
const wsClearAfterSend = ref(true);
const wsMessages = ref<{ dir: 'sent' | 'recv'; time: string; content: string }[]>([]);
const wsMessage = ref('');
const wsLastOk = ref(false);
const nowTime = () => {
	const d = new Date();
	return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`;
};
const wsConnect = async () => {
	const url = String(req.value.url || '').trim();
	if (!url) { ElMessage.warning('请先填写 WebSocket 地址（ws:// 或 wss:// 开头）'); return; }
	try {
		const r: any = await useApiAutomationApi().wsTest({ url, message: '', connect_only: true, headers: req.value.header || [], ssl_verify: req.value.config?.ssl_verify !== false });
		if (r?.code === 200 && r?.data?.ok) {
			wsLastOk.value = true;
			wsMessages.value.push({ dir: 'recv', time: nowTime(), content: `连接成功 ${url}` });
			ElMessage.success('连接成功');
		} else {
			wsLastOk.value = false;
			ElMessage.error(`连接失败：${r?.data?.error || r?.message || '未知错误'}`);
		}
	} catch (e: any) {
		wsLastOk.value = false;
		ElMessage.error(`连接失败：${e?.message || '未知错误'}`);
	}
};
const wsSend = async () => {
	const text = wsMessage.value.trim();
	if (!text) { ElMessage.warning('请输入要发送的消息'); return; }
	const url = String(req.value.url || '').trim();
	if (!url) { ElMessage.warning('请先填写 WebSocket 地址'); return; }
	wsMessages.value.push({ dir: 'sent', time: nowTime(), content: text });
	if (wsClearAfterSend.value) wsMessage.value = '';
	try {
		const r: any = await useApiAutomationApi().wsTest({ url, message: text, headers: req.value.header || [], binary_type: wsFormat.value === 'Binary' ? wsBinaryType.value : undefined, ssl_verify: req.value.config?.ssl_verify !== false });
		if (r?.code === 200) {
			const data = r.data || {};
			if (data.ok) {
				wsLastOk.value = true;
				if (data.received != null) wsMessages.value.push({ dir: 'recv', time: nowTime(), content: String(data.received) });
				else if (data.timeout) wsMessages.value.push({ dir: 'recv', time: nowTime(), content: `（${data.elapsed}s 内未收到响应）` });
			} else {
				wsLastOk.value = false;
				wsMessages.value.push({ dir: 'recv', time: nowTime(), content: `失败：${data.error || '未知错误'}` });
			}
		} else {
			wsMessages.value.push({ dir: 'recv', time: nowTime(), content: `调试失败：${r?.message || ''}` });
		}
	} catch (e: any) {
		wsMessages.value.push({ dir: 'recv', time: nowTime(), content: `调试失败：${e?.message || ''}` });
	}
};

const sendRequest = async () => {
	const id = apiId.value;
	if (!id) { ElMessage.warning('无法获取接口ID'); return; }
	if (req.value.protocol === 'websocket') { wsSend(); return; }
	const urlText = String(req.value.url || '');
	if (/\{\{.+\}\}/.test(urlText) && (props.envId == null || props.envId === '' || Number(props.envId) === 0)) {
		ElMessage.warning('URL 含环境变量，请先在右上角选择环境后再发送');
		return;
	}
	try {
		const finalUrl = req.value.protocol === 'webhook' && req.value.webhook_url ? String(req.value.webhook_url).trim() : req.value.url;
		const requestData: any = { id: Number(id), env_id: props.envId, url: finalUrl, req: req.value };
		const response: any = await api_send(requestData);
		if (response.code === 200) {
			const data = response.data;
			res.value = data?.res ? { ...res.value, ...data.res } : (data || res.value);
			ElMessage.success('请求发送成功');
		} else {
			const msg = response.message || response.data?.message || `接口返回异常（code=${response.code}）`;
			ElMessage.error(`请求发送失败：${msg}`);
		}
	} catch (error: any) {
		console.error('发送请求失败', error);
		const msg =
			error?.response?.data?.message ||
			error?.response?.data?.detail ||
			error?.message ||
			'未知错误';
		ElMessage.error(`请求发送失败：${msg}`);
	}
};

const handleSaveCommand = (command: string) => {
	if (command === 'save') saveApi();
	else if (command === 'saveAsCase') saveAsCase();
};

const saveApi = async () => {
	const id = apiId.value;
	if (!id) { ElMessage.warning('无法获取接口ID'); return; }
	try {
		await save_api({ id: Number(id), url: req.value.url, req: req.value });
		ElMessage.success('保存成功');
		emit('apiSaved');
	} catch { ElMessage.error('保存失败'); }
};

const saveAsCase = async () => {
	const apiServiceId = Number(props.serviceId ?? props.apiData?.api_info?.api_service_id ?? props.apiData?.api_service_id ?? 0);
	if (!apiServiceId) { ElMessage.warning('无法获取服务ID，请确认接口已关联服务'); return; }
	const defaultName = `${props.apiData?.name || props.apiData?.api_info?.name || '接口'}_用例_${Date.now()}`;
	saveCaseForm.value = { name: defaultName, description: '', suite_id: null, case_type: 1 };
	saveCaseSuiteTree.value = [];
	saveCaseLoading.value = true;
	saveCaseDialogVisible.value = true;
	try {
		const r: any = await apiAutomationApi.api_suite_list({ api_service_id: apiServiceId });
		const raw = r?.data;
		saveCaseSuiteTree.value = Array.isArray(raw) ? raw : (Array.isArray(raw?.content) ? raw.content : []);
	} catch (e) {
		console.error('加载用例集失败', e);
		saveCaseSuiteTree.value = [];
	} finally {
		saveCaseLoading.value = false;
	}
};

const reloadSuiteTree = async () => {
	const apiServiceId = Number(props.serviceId ?? props.apiData?.api_info?.api_service_id ?? props.apiData?.api_service_id ?? 0);
	if (!apiServiceId) return;
	saveCaseLoading.value = true;
	try {
		const r: any = await apiAutomationApi.api_suite_list({ api_service_id: apiServiceId });
		const raw = r?.data;
		saveCaseSuiteTree.value = Array.isArray(raw) ? raw : (Array.isArray(raw?.content) ? raw.content : []);
	} catch { saveCaseSuiteTree.value = []; }
	finally { saveCaseLoading.value = false; }
};

const confirmSaveAsCase = async () => {
	if (!saveCaseForm.value.name.trim()) { ElMessage.warning('请输入用例名称'); return; }
	if (!saveCaseForm.value.suite_id) { ElMessage.warning('请选择用例集'); return; }
	saveCaseSubmitting.value = true;
	try {
		await apiAutomationApi.save_api_case_to_suite({
			name: saveCaseForm.value.name.trim(),
			description: saveCaseForm.value.description,
			suite_id: saveCaseForm.value.suite_id,
			case_type: saveCaseForm.value.case_type,
			script: [{ api_id: apiId.value, name: props.apiData?.name || props.apiData?.api_info?.name || '接口', req: req.value }],
		});
		ElMessage.success('保存为用例成功');
		saveCaseDialogVisible.value = false;
		emit('caseSaved');
	} catch { ElMessage.error('保存失败'); }
	finally { saveCaseSubmitting.value = false; }
};
</script>

<style lang="scss" scoped>
.api-detail-container { height: 100%; display: flex; flex-direction: column; padding: 0; margin: 0; overflow: hidden; background: var(--el-bg-color-page); }
.api-detail-container.is-embedded { height: 100%; flex: 1; min-height: 0; }
.api-detail-container.is-embedded .api-detail-card :deep(.el-card__body) { padding: 6px; }
.api-detail-card { height: 100%; flex: 1; display: flex; flex-direction: column; margin: 0; border: none; border-radius: 0; box-shadow: none; background: var(--el-bg-color-page); }
.api-detail-card :deep(.el-card__body) { height: 100%; display: flex; flex-direction: column; padding: 10px; background: var(--el-bg-color-page); box-sizing: border-box; }
.api-detail-content { flex: 1; min-height: 0; display: flex; flex-direction: column; gap: 8px; }
.api-detail-header { flex: 0 0 auto; }
.req-url-bar { display: flex; align-items: center; gap: 6px; background: var(--el-bg-color); border: 1px solid var(--el-border-color); border-radius: 8px; padding: 8px 12px; box-shadow: 0 1px 4px rgba(0,0,0,.05); }
.method-select { width: 110px; flex-shrink: 0; }
.method-select :deep(.el-input__inner) { color: var(--method-color, #409eff); font-weight: 700; font-size: 13px; }
.method-select :deep(.el-select__selected-item span) { color: var(--method-color, #409eff); font-weight: 700; font-size: 13px; }
.method-select :deep(.el-select__placeholder) { color: var(--method-color, #409eff); font-weight: 700; font-size: 13px; }
.url-input { flex: 1; min-width: 0; }
.url-input :deep(.el-input__inner) { font-family: 'Consolas', 'Monaco', monospace; font-size: 13px; }
.send-btn, .save-btn { flex-shrink: 0; }
.action-btn { flex-shrink: 0; color: var(--el-text-color-regular); border-color: var(--el-border-color); }
.action-btn:hover { color: #409eff; border-color: #409eff; }
.api-detail-body { flex: 1 1 auto; display: flex; flex-direction: column; gap: 8px; min-height: 0; }
.request-section { flex: 0 0 44%; min-height: 260px; transition: flex 0.25s ease; }
.response-section { flex: 1 1 56%; min-height: 300px; display: flex; flex-direction: column; transition: flex 0.25s ease, min-height 0.25s ease; }
.response-section--collapsed { flex: 0 0 38px !important; min-height: 38px !important; overflow: hidden; }
.response-section--collapsed ~ .request-section,
.api-detail-body:has(.response-section--collapsed) .request-section { flex: 1 1 auto; }
.panel-card { height: 100%; background: var(--el-bg-color); border: 1px solid var(--el-border-color); border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,.05); display: flex; flex-direction: column; overflow: hidden; }
.apifox-tabs { height: 100%; display: flex; flex-direction: column; }
.apifox-tabs :deep(.el-tabs__header) { margin: 0; background: var(--el-fill-color-light); border-bottom: 1px solid var(--el-border-color); padding: 0 8px; flex-shrink: 0; }
.apifox-tabs :deep(.el-tabs__nav-wrap::after) { display: none; }
.apifox-tabs :deep(.el-tabs__item) { height: 38px; line-height: 38px; font-size: 12px; color: var(--el-text-color-regular); padding: 0 12px; transition: color .2s; letter-spacing: .2px; }
.apifox-tabs :deep(.el-tabs__item:hover) { color: #409eff; }
.apifox-tabs :deep(.el-tabs__item.is-active) { color: #1a6fe8; font-weight: 600; }
.apifox-tabs :deep(.el-tabs__active-bar) { height: 2px; background: linear-gradient(90deg,#409eff,#66b1ff); border-radius: 2px 2px 0 0; }
.apifox-tabs :deep(.el-tabs__content) { flex: 1; min-height: 0; overflow-y: auto; padding: 10px 12px; }
.apifox-tabs :deep(.el-tab-pane) { height: 100%; display: flex; flex-direction: column; min-height: 0; }
/* 前置/后置/断言 tab 内容自然流动，不限制高度 */
.apifox-tabs :deep(.el-tab-pane[id*="pane-before"]),
.apifox-tabs :deep(.el-tab-pane[id*="pane-after"]),
.apifox-tabs :deep(.el-tab-pane[id*="pane-assert"]) { height: auto; min-height: 0; }
/* 操作面板滚动容器：撑开内容，让父级 el-tabs__content 滚动 */
.inherit-click { cursor: pointer; }
.inherit-arrow { margin-left: 4px; font-size: 12px; color: #909399; }
.inherit-detail { margin: 0 0 8px; padding: 8px 10px; background: #fafbfc; border: 1px solid #e4e7ed; border-radius: 6px; }
.inherit-op { margin-bottom: 8px; }
.inherit-op:last-child { margin-bottom: 0; }
.inherit-op-title { font-size: 12px; font-weight: 600; color: #303133; margin-bottom: 4px; }
.inherit-op-code {
	margin: 0; padding: 8px 10px; background: #0f1115; border-radius: 6px;
	font-family: 'JetBrains Mono', Consolas, Menlo, monospace; font-size: 12px; line-height: 1.55;
	color: #c9d1d9; white-space: pre-wrap; word-break: break-all; max-height: 200px; overflow: auto;
}
.inherit-op-meta { font-size: 12px; color: #606266; }
.inherit-drop { cursor: crosshair; }
.inherit-drop-hint { font-size: 11px; color: #b3b8bf; }
.inherit-bar {
	display: flex; align-items: center; justify-content: space-between; gap: 8px;
	padding: 8px 10px; margin-bottom: 8px;
	background: #f6f8fa; border: 1px solid #e4e7ed; border-radius: 6px;
}
.inherit-info { display: flex; align-items: center; flex-wrap: wrap; gap: 2px; }
.inherit-label { font-size: 12px; font-weight: 600; color: #606266; margin-right: 6px; }
.inherit-muted { font-size: 11px; color: #909399; }
.inherit-switch { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
.op-scroll-wrap { width: 100%; }
.apifox-tabs :deep(.el-badge__content) { top: 6px; right: 0px; font-size: 9px; height: 14px; line-height: 14px; padding: 0 3px; min-width: 14px; border: none; }
.res-badge :deep(.el-badge__content) { font-size: 9px; height: 13px; line-height: 13px; padding: 0 3px; min-width: 13px; border: none; }
.res-meta-tag { font-size: 11px; font-weight: 600; padding: 0 6px; height: 20px; line-height: 20px; border-radius: 3px; }
.res-tab-header { display: flex; align-items: center; background: var(--el-fill-color-light); border-bottom: 1px solid var(--el-border-color); flex-shrink: 0; min-height: 38px; }
.res-tabs { flex: 1; min-width: 0; }
.res-tabs :deep(.el-tabs__header) { background: transparent; border-bottom: none; margin: 0; }
.res-meta { display: flex; align-items: center; gap: 5px; padding: 0 12px; flex-shrink: 0; }
.res-meta-tag { font-size: 11px; font-weight: 600; padding: 0 6px; height: 20px; line-height: 20px; border-radius: 3px; }
.res-content { flex: 1; min-height: 0; overflow: hidden; display: flex; flex-direction: column; }
.json-panel { flex: 1; min-height: 0; height: 100%; overflow: auto; background: #fafbfc; padding: 4px; }
.res-code-panel { height: 100%; display: flex; flex-direction: column; background: #1e1e1e; border-radius: 0; overflow: hidden; }
.res-json-pretty { flex: 1; min-height: 0; }
.res-json-pretty :deep(.vjs-tree) { background: #1e1e1e !important; color: #d4d4d4 !important; font-family: 'Consolas','Monaco',monospace; font-size: 13px; padding: 12px; }
.res-json-pretty :deep(.vjs-key) { color: #9cdcfe !important; }
.res-json-pretty :deep(.vjs-value-string) { color: #ce9178 !important; }
.res-json-pretty :deep(.vjs-value-number) { color: #b5cea8 !important; }
.res-json-pretty :deep(.vjs-value-boolean) { color: #569cd6 !important; }
.res-json-pretty :deep(.vjs-value-null) { color: #569cd6 !important; }
.res-json-pretty :deep(.vjs-tree-node:hover) { background: transparent !important; }
.res-json-pretty :deep(.vjs-tree-node.is-highlight) { background: rgba(255,255,255,.06) !important; }
.res-json-pretty :deep(.vjs-tree-node-actions) { background: transparent !important; }
.res-json-pretty :deep(.vjs-tree-node:hover .vjs-tree-node-actions) { background: rgba(255,255,255,.06) !important; }
/* console 详情块（Apifox 风格） */
.res-console-line { padding: 3px 0; }
.res-console-msg { font-family: 'JetBrains Mono', Consolas, Menlo, monospace; font-size: 12px; line-height: 1.6; }
.res-console-detail {
	margin: 4px 0 10px 14px;
	padding: 8px 10px;
	background: #0f1115;
	border: 1px solid #262b33;
	border-radius: 6px;
	max-height: 280px;
	overflow: auto;
	font-family: 'JetBrains Mono', Consolas, Menlo, monospace;
	font-size: 12px;
	line-height: 1.55;
	color: #c9d1d9;
	white-space: pre-wrap;
	word-break: break-all;
}
.res-console-panel { height: 100%; overflow-y: auto; background: #1e1e1e; padding: 8px 12px; font-family: 'Consolas','Monaco',monospace; font-size: 12px; }
.res-console-line { padding: 2px 0; line-height: 1.6; color: #d4d4d4; }
.console-error { color: #f48771; }
.console-warn { color: #dcdcaa; }
.console-info { color: #9cdcfe; }
/* 实际请求 Apifox 风格分区 */
.res-raw-meta {
	display: flex; align-items: center; gap: 10px;
	padding: 8px 12px; margin-bottom: 8px;
	background: #f6f8fa; border: 1px solid #e4e7ed; border-radius: 6px;
	font-family: 'JetBrains Mono', Consolas, Menlo, monospace; font-size: 12px;
}
.res-raw-method {
	padding: 2px 8px; border-radius: 4px;
	background: #409eff; color: #fff; font-weight: 600; font-size: 11px;
}
.res-raw-url { color: #303133; word-break: break-all; }
.res-raw-section { margin-bottom: 8px; }
.res-raw-section-title {
	font-size: 12px; font-weight: 600; color: #606266;
	margin-bottom: 4px; padding-left: 2px;
}
.raw-header-wrap {
	background: #1e1e1e;
	border: 1px solid #2d2d2d;
	border-radius: 6px;
	overflow: visible;
}
.raw-header-table { width: 100%; border-collapse: collapse; }
.raw-header-table thead { position: sticky; top: 0; z-index: 1; }
.res-raw-body {
	margin: 0; padding: 10px 12px;
	background: #0f1115; border: 1px solid #262b33; border-radius: 6px;
	font-family: 'JetBrains Mono', Consolas, Menlo, monospace; font-size: 12px; line-height: 1.55;
	color: #c9d1d9; white-space: pre-wrap; word-break: break-all;
	max-height: 200px; overflow: auto;
}
/* 控制台逐行输出 */
.res-console-outline {
	font-family: 'JetBrains Mono', Consolas, Menlo, monospace;
	font-size: 12px; line-height: 1.55; color: #c9d1d9;
}
.res-raw-panel { height: 100%; display: flex; flex-direction: column; background: #1e1e1e; overflow-y: auto; overflow-x: hidden; }
.res-raw-toolbar { display: flex; align-items: center; gap: 2px; padding: 6px 12px; background: #252526; border-bottom: 1px solid #3c3c3c; flex-shrink: 0; flex-wrap: wrap; }
.raw-lang-item { padding: 3px 10px; border-radius: 3px; font-size: 12px; color: #cccccc; cursor: pointer; user-select: none; transition: all .15s; white-space: nowrap; }
.raw-lang-item:hover { color: #fff; background: #3c3c3c; }
.raw-lang-item.active { background: #0e639c; color: #fff; }
.res-raw-editor { flex: none; min-height: 0; overflow: visible; padding: 12px; }
.res-raw-code { margin: 0; font-family: 'Consolas','Monaco',monospace; font-size: 12px; color: #d4d4d4; white-space: pre-wrap; word-break: break-all; line-height: 1.6; }
.res-empty { height: 100%; display: flex; align-items: center; justify-content: center; color: #909399; font-size: 13px; }
.op-pane { height: 100%; display: flex; flex-direction: column; min-height: 0; }
.op-scroll { flex: 1; min-height: 0; overflow-y: auto; padding: 4px 0; }
.op-footer { flex-shrink: 0; padding-top: 10px; background: var(--el-bg-color); position: sticky; bottom: 0; }
.body-pane { height: 100%; display: flex; flex-direction: column; min-height: 0; }
.body-type-bar { display: flex; align-items: center; gap: 2px; padding: 6px 0 8px; border-bottom: 1px solid var(--el-border-color-lighter); flex-shrink: 0; flex-wrap: wrap; }
.body-type-item { padding: 3px 10px; border-radius: 4px; font-size: 13px; color: var(--el-text-color-regular); cursor: pointer; user-select: none; transition: all .15s; white-space: nowrap; }
.body-type-item:hover { color: #409eff; background: var(--el-color-primary-light-9); }
.body-type-item.active { background: #409eff; color: #fff; font-weight: 500; }
.body-type-bar-right { margin-left: auto; }
.body-content { flex: 1; min-height: 0; overflow: auto; padding-top: 8px; }
.body-empty { height: 100%; display: flex; align-items: center; justify-content: center; color: var(--el-text-color-placeholder); font-size: 14px; }
.body-editor { height: 100%; }
.body-binary { padding: 8px 0; }
.body-kv { width: 100%; }
.kv-header { display: flex; align-items: center; padding: 4px 0; border-bottom: 1px solid var(--el-border-color-lighter); margin-bottom: 4px; font-size: 12px; color: var(--el-text-color-placeholder); }
.kv-row { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.kv-col-check { width: 24px; flex-shrink: 0; } .kv-col-key { flex: 1; } .kv-col-val { flex: 1; } .kv-col-act { width: 40px; flex-shrink: 0; }
.kv-actions { display: flex; align-items: center; gap: 8px; margin-top: 6px; flex-wrap: wrap; }
.auth-hint { margin: 4px 0 0 130px; max-width: 520px; font-size: 12px; color: var(--el-text-color-placeholder); line-height: 1.5; }

.bulk-edit-format { font-size: 13px; color: var(--el-text-color-secondary); }
.bulk-edit-textarea :deep(textarea) { font-family: Consolas, Monaco, 'Courier New', monospace; font-size: 13px; line-height: 1.5; }
.bulk-edit-tip { margin-top: 8px; font-size: 12px; color: var(--el-text-color-placeholder); }
.header-icon { margin-right: 6px; }
.tab-info { display: flex; align-items: center; gap: 4px; font-size: 13px; }
.code, .size { font-size: 13px; color: #409eff; margin-left: 4px; font-weight: 500; }

.res-dark-key { color: #9cdcfe; white-space: nowrap; }
.res-dark-val { color: #ce9178; word-break: break-all; }
.res-dark-empty { height: 100%; display: flex; align-items: center; justify-content: center; color: #555; font-size: 13px; background: #1e1e1e; font-family: 'Consolas','Monaco',monospace; }
.res-ops-title { display: flex; align-items: flex-start; gap: 8px; padding: 7px 16px; line-height: 1.5; }
.ops-fail { color: #f48771; }
.ops-icon { flex-shrink: 0; font-weight: 700; }
.res-ops-body { padding: 0 16px 8px; background: #252526; }

.res-dark-kv-panel { height: 100%; overflow-y: auto; background: #1e1e1e; }
.res-dark-kv-table { width: 100%; border-collapse: collapse; font-size: 12px; font-family: 'Consolas','Monaco',monospace; }
.res-dark-kv-table thead tr { background: #252526; }
.res-dark-kv-table th { color: #858585; font-weight: 500; padding: 7px 16px; text-align: left; border-bottom: 1px solid #3c3c3c; white-space: nowrap; font-size: 11px; letter-spacing: .5px; text-transform: uppercase; }
.res-dark-kv-table td { padding: 5px 16px; border-bottom: 1px solid #2d2d2d; vertical-align: top; }
.res-dark-kv-table tr:hover td { background: #2a2d2e; }
.res-dark-key { color: #9cdcfe; white-space: nowrap; }
.res-dark-val { color: #ce9178; word-break: break-all; }
.res-dark-muted { color: #858585; }
.res-dark-empty { height: 100%; display: flex; align-items: center; justify-content: center; color: #555; font-size: 13px; background: #1e1e1e; font-family: 'Consolas','Monaco',monospace; }
/* 脚本输出详细块 */
.res-ops-output {
	margin: 6px 0 10px 26px;
	padding: 10px 12px;
	background: #0f1115;
	border: 1px solid #262b33;
	border-radius: 6px;
	max-height: 320px;
	overflow: auto;
}
.res-ops-output pre {
	margin: 0;
	font-family: 'JetBrains Mono', Consolas, Menlo, monospace;
	font-size: 12px;
	line-height: 1.6;
	color: #c9d1d9;
	white-space: pre-wrap;
	word-break: break-all;
}
.res-ops-panel { height: 100%; overflow-y: auto; background: #1e1e1e; padding: 8px 0; font-family: 'Consolas','Monaco',monospace; font-size: 12px; }
.res-ops-item { border-bottom: 1px solid #2d2d2d; }
.res-ops-title { display: flex; align-items: flex-start; gap: 8px; padding: 7px 16px; line-height: 1.5; }
.ops-ok { color: #4ec9b0; }
.ops-fail { color: #f48771; }
.ops-icon { flex-shrink: 0; font-weight: 700; }
.res-ops-body { padding: 0 16px 8px; background: #252526; }
.code-editor-wrap { display: flex; flex-direction: column; background: #1e1e1e; border-radius: 6px; overflow: hidden; border: 1px solid #3c3c3c; flex: 1; }
.code-editor-lang { padding: 4px 12px; background: #252526; color: #858585; font-size: 11px; font-family: 'Consolas','Monaco',monospace; letter-spacing: .5px; border-bottom: 1px solid #3c3c3c; flex-shrink: 0; }
.code-textarea { flex: 1; width: 100%; min-height: 160px; background: #1e1e1e; color: #d4d4d4; border: none; outline: none; resize: vertical; padding: 12px; font-family: 'Consolas','Monaco',monospace; font-size: 13px; line-height: 1.6; tab-size: 2; box-sizing: border-box; }
.code-textarea::placeholder { color: #555; }
.code-textarea:focus { background: #1e1e1e; }
.json-editor-inner { flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
.json-editor-inner :deep(.jsoneditor-vue) { height: 100% !important; background: #1e1e1e; }
.json-editor-inner :deep(.jsoneditor) { border: none !important; background: #1e1e1e; }
.json-editor-inner :deep(.jsoneditor-menu) { background: #252526 !important; border-bottom: 1px solid #3c3c3c !important; }
.json-editor-inner :deep(.jsoneditor-menu button) { color: #ccc !important; }
.json-editor-inner :deep(.jsoneditor-tree) { background: #1e1e1e !important; color: #d4d4d4 !important; }
.json-editor-inner :deep(.jsoneditor-field) { color: #9cdcfe !important; }
.json-editor-inner :deep(.jsoneditor-value.jsoneditor-string) { color: #ce9178 !important; }
.json-editor-inner :deep(.jsoneditor-value.jsoneditor-number) { color: #b5cea8 !important; }
.json-editor-inner :deep(.jsoneditor-value.jsoneditor-boolean) { color: #569cd6 !important; }
.json-editor-inner :deep(.jsoneditor-value.jsoneditor-null) { color: #569cd6 !important; }
.json-editor-inner :deep(.ace_editor) { background: #1e1e1e !important; }
.json-editor-inner :deep(.ace_gutter) { background: #252526 !important; color: #858585 !important; }
.json-editor-inner :deep(.ace_content) { color: #d4d4d4 !important; }
.settings-pane { padding: 8px 4px; display: flex; flex-direction: column; gap: 0; }
.settings-item { display: flex; align-items: center; justify-content: space-between; padding: 14px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.settings-item:last-child { border-bottom: none; }
.settings-label { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--el-text-color-primary); }
.settings-help { font-size: 14px; color: var(--el-text-color-placeholder); cursor: help; }
.settings-help:hover { color: var(--el-text-color-regular); }
.cert-section { padding: 0; }
.cert-section-header { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 12px; }
.cert-section-title { font-size: 15px; font-weight: 600; color: var(--el-text-color-primary); margin-bottom: 3px; }
.cert-section-sub { font-size: 12px; color: var(--el-text-color-placeholder); }
.cert-field-row { display: flex; align-items: center; gap: 16px; margin-top: 8px; }
.cert-field-label { font-size: 13px; color: var(--el-text-color-regular); width: 70px; flex-shrink: 0; }
.cert-empty { font-size: 13px; color: var(--el-text-color-placeholder); padding: 12px 0; }
.cert-client-item { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; background: var(--el-fill-color-light); border-radius: 6px; margin-bottom: 6px; }
.cert-client-domain { font-size: 13px; color: var(--el-text-color-primary); font-family: monospace; margin-right: 8px; }
.cert-client-tag { display: inline-block; padding: 1px 6px; background: var(--el-color-primary-light-9); color: #409eff; border-radius: 3px; font-size: 11px; margin-right: 4px; }
.cert-breadcrumb { display: flex; align-items: center; margin-bottom: 4px; font-size: 13px; }
.main-tabs { flex-shrink: 0; }
.main-tabs :deep(.el-tabs__header) { margin: 0 0 8px; background: var(--el-bg-color); border-bottom: 2px solid var(--el-border-color); padding: 0 12px; }
.main-tabs :deep(.el-tabs__item) { height: 40px; line-height: 40px; font-size: 13px; color: var(--el-text-color-regular); padding: 0 16px; }
.main-tabs :deep(.el-tabs__item.is-active) { color: #409eff; font-weight: 600; }
.main-tabs :deep(.el-tabs__active-bar) { height: 2px; background: #409eff; }
.main-tabs :deep(.el-tabs__nav-wrap::after) { display: none; }
.side-panel { flex: 1; min-height: 0; overflow-y: auto; padding: 16px; background: var(--el-bg-color); border-radius: 8px; border: 1px solid var(--el-border-color); }
.history-side-panel { padding: 0; overflow: hidden; display: flex; flex-direction: column; }
.mock-panel { }
.mock-section { }
.mock-section-title { font-size: 14px; font-weight: 600; color: var(--el-text-color-primary); margin-bottom: 10px; }
.mock-section-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.mock-addr-bar { display: flex; align-items: center; gap: 10px; background: var(--el-fill-color-light); border-radius: 6px; padding: 8px 12px; }
.mock-url { font-family: monospace; font-size: 12px; color: #409eff; flex: 1; word-break: break-all; }
.mock-hint { margin-top: 10px; padding: 10px 12px; background: var(--el-fill-color-lighter); border-radius: 6px; font-size: 12px; color: var(--el-text-color-regular); line-height: 1.7; }
.mock-hint p { margin: 0 0 4px; font-weight: 600; color: var(--el-text-color-primary); }
.mock-hint ol { margin: 0; padding-left: 18px; }
.mock-scroll-list {
	width: 100%;
	box-sizing: border-box;
	border: 1px solid var(--el-border-color-lighter);
	border-radius: 6px;
	padding: 8px;
	overflow-x: hidden;
	overflow-y: auto;
	background: var(--el-fill-color-blank);
}
.mock-param-scroll { max-height: 160px; min-height: 48px; }
.mock-header-scroll { max-height: 120px; min-height: 48px; }
.mock-scroll-empty {
	font-size: 12px;
	color: var(--el-text-color-placeholder);
	text-align: center;
	padding: 12px 0;
}
.mock-param-row {
	display: flex;
	align-items: center;
	gap: 8px;
	margin-bottom: 8px;
	width: 100%;
	flex-wrap: nowrap;
}
.mock-param-row:last-child { margin-bottom: 0; }

.doc-panel { padding: 0; overflow: hidden; display: flex; flex-direction: column; }
.res-code-toolbar { display: flex; justify-content: flex-end; padding: 5px 10px; background: #252526; border-bottom: 1px solid #3c3c3c; flex-shrink: 0; }
.res-copy-btn { display: inline-flex; align-items: center; gap: 4px; padding: 3px 10px; background: transparent; border: 1px solid #4a4a4a; border-radius: 3px; color: #aaa; font-size: 11px; cursor: pointer; transition: all .15s; }
.res-copy-btn:hover { background: #3c3c3c; color: #e0e0e0; border-color: #666; }
.res-copy-btn.copied { color: #4ec9b0; border-color: #4ec9b0; }
.ws-panel { flex: 1 1 auto; display: flex; flex-direction: column; gap: 10px; min-height: 0; background: var(--el-bg-color); border: 1px solid var(--el-border-color); border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,.05); padding: 10px; }
.ws-badge { margin-right: 8px; border: none; }
.ws-msg-editor { display: flex; flex-direction: column; gap: 8px; }
.ws-format-row { display: flex; align-items: center; gap: 10px; }
.ws-send-options { display: flex; align-items: center; gap: 16px; }
.ws-status { font-size: 13px; }
.ws-muted { font-size: 12px; color: #909399; }
.ws-response { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; gap: 6px; }
.ws-response-title { font-size: 13px; color: var(--el-text-color-secondary); }
.ws-history { flex: 1 1 auto; overflow: auto; border: 1px solid var(--el-border-color-lighter); border-radius: 6px; padding: 10px; display: flex; flex-direction: column; gap: 8px; min-height: 140px; }
.ws-msg { display: flex; align-items: flex-start; gap: 8px; }
.ws-msg.sent { flex-direction: row; }
.ws-msg-time { font-size: 12px; color: #909399; white-space: nowrap; margin-top: 2px; }
.ws-msg-tag { font-size: 12px; border-radius: 4px; padding: 1px 6px; white-space: nowrap; }
.ws-msg-tag.sent { background: #ecf5ff; color: #409eff; }
.ws-msg-tag.recv { background: #f0f9eb; color: #67c23a; }
.ws-msg-content { margin: 0; font-size: 13px; background: var(--el-fill-color-light); border-radius: 4px; padding: 6px 10px; white-space: pre-wrap; word-break: break-all; flex: 1; }
.webhook-bar { display: flex; gap: 8px; margin-top: 8px; align-items: center; }
.webhook-tip { font-size: 13px; color: var(--el-text-color-secondary); white-space: nowrap; }
.ws-params-head {
	display: grid;
	grid-template-columns: 28px 1fr 1fr 110px 1fr 48px;
	gap: 6px;
	align-items: center;
	margin-bottom: 4px;
	font-size: 12px;
	color: var(--el-text-color-secondary);
}
.ws-params-row {
	display: grid;
	grid-template-columns: 28px 1fr 1fr 110px 1fr 48px;
	gap: 6px;
	align-items: center;
	margin-bottom: 6px;
}
.ws-sub-title { font-size: 12px; color: var(--el-text-color-secondary); margin: 10px 0 6px; }
.ws-config-row { display: flex; align-items: center; justify-content: space-between; max-width: 320px; padding: 10px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.ws-config-label { font-size: 13px; color: var(--el-text-color-primary); }
.ws-config-tip { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 10px; line-height: 1.6; }
.webhook-tip-box { max-width: 340px; }
.webhook-tip-text { font-size: 12px; color: var(--el-text-color-regular); line-height: 1.7; margin-bottom: 8px; }
.webhook-tip-img { width: 100%; border-radius: 6px; border: 1px solid var(--el-border-color-lighter); }
.webhook-tip-popper { max-width: 360px !important; }
.bulk-mode { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.bulk-hint { font-size: 12px; color: #909399; }
.bulk-foot-hint { margin-top: 6px; font-size: 12px; color: #909399; line-height: 1.6; }
.bulk-csv-link { color: #7c3aed; cursor: pointer; }
.bulk-csv-rules { max-height: 420px; overflow: auto; }
.bulk-csv-title { font-weight: 600; margin-bottom: 6px; font-size: 13px; }
.bulk-csv-row { display: flex; gap: 10px; margin-bottom: 4px; font-size: 12px; }
.bulk-csv-row b { flex: 0 0 56px; }
.bulk-csv-row span { color: #606266; }
.bulk-csv-divider { border-top: 1px solid var(--el-border-color-lighter); margin: 10px 0; }
.bulk-csv-spec { margin-bottom: 8px; }
.bulk-csv-desc { font-size: 12px; color: #606266; line-height: 1.6; margin-bottom: 4px; }
.bulk-csv-code { display: block; background: #1e1e1e; color: #d4d4d4; border-radius: 4px; padding: 6px 10px; font-size: 12px; white-space: pre-wrap; }
</style>

<style lang="scss">
/* Webhook tooltip：白底黑字（popper 挂载到 body，需全局样式） */
.webhook-tip-popper {
	background: #ffffff !important;
	color: #333333 !important;
	border: 1px solid var(--el-border-color-light) !important;
	box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12) !important;
	padding: 8px 10px;
	max-width: 360px;
}
.webhook-tip-popper .webhook-tip-text {
	color: #333333 !important;
}
.webhook-tip-popper .el-popper__arrow::before {
	background: #ffffff !important;
	border-color: var(--el-border-color-light) !important;
}
</style>
