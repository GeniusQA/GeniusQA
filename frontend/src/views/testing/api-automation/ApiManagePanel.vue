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
								<el-dropdown-item command="import_api">导入接口</el-dropdown-item>
							</el-dropdown-menu>
						</template>
					</el-dropdown>
				</div>
				<el-tree
					ref="treeRef"
					:data="treeData"
					:props="{ children: 'children', label: 'name' }"
					node-key="id"
					:filter-node-method="filterNode"
					draggable
					:allow-drop="allowDrop"
					class="api-tree"
					@node-click="onNodeClick"
					@node-drop="handleNodeDrop"
				>
					<template #default="{ data }">
						<div class="tree-node">
							<div class="node-left">
								<el-icon v-if="data.type===0" class="icon-folder" style="color:#7c3aed"><Grid /></el-icon>
								<el-icon v-else-if="data.type===1" class="icon-folder"><FolderOpened /></el-icon>
								<el-icon v-else-if="data.type===3" class="icon-case"><Link /></el-icon>
								<span v-if="(data.type===2||data.type===3) && data.protocol !== 'websocket' && data.protocol !== 'webhook'" class="method-badge" :style="{background: methodColor(data.method)}">{{ methodLabel(data.method) }}</span>
								<span v-if="data.type===2 && data.protocol==='websocket'" class="proto-badge proto-ws">WS</span>
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
				<div v-if="!apiTabs.length" class="detail-empty">
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
				<el-button type="primary" :loading="pulling" @click="confirmImport">导入</el-button>
			</template>
		</el-dialog>

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
						<el-option label="Webhook" value="webhook" />
					</el-select>
				</el-form-item>
				<el-form-item v-if="menuForm.type === 2" label="父级目录">
					<el-select v-model="menuForm.pid" style="width:100%" filterable clearable placeholder="选择父级目录（不选=根级）">
						<el-option-group v-if="folderOptions.dirs.length" label="目录">
							<el-option v-for="d in folderOptions.dirs" :key="d.id" :label="d.path" :value="d.id" />
						</el-option-group>
					</el-select>
				</el-form-item>
				<el-form-item v-if="menuForm.type === 1" label="父级目录">
					<el-select v-model="menuForm.pid" style="width:100%" filterable placeholder="选择父级目录（选模块=根级）">
						<el-option-group v-if="folderOptions.mods.length" label="模块">
							<el-option v-for="m in folderOptions.mods" :key="m.id" :label="m.path" :value="m.id" />
						</el-option-group>
						<el-option-group v-if="folderOptions.dirs.length" label="目录">
							<el-option v-for="d in folderOptions.dirs" :key="d.id" :label="d.path" :value="d.id" />
						</el-option-group>
					</el-select>

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
import { computed, onMounted, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import type { UploadFile, UploadInstance, UploadProps, UploadRawFile } from 'element-plus';
import { ArrowDown, FolderOpened, Link, MoreFilled, Document, Grid, UploadFilled } from '@element-plus/icons-vue';
import ApiDetail from './api_detail.vue';
import ApiDbPopover from './components/ApiDbPopover.vue';
import ApiDocPanel from './components/ApiDocPanel.vue';
import ApiHistoryPanel from './components/ApiHistoryPanel.vue';
import ApiMockPanel from './components/ApiMockPanel.vue';
import {
	api_tree, api_info, add_menu, del_menu, edit_menu, copy_menu, useApiAutomationApi,
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

const loadTree = async () => {
	try {
		const r: any = await api_tree({ search: { api_service_id: props.serviceId } });
		treeData.value = r?.data || [];
	} catch { treeData.value = []; }
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

const onNodeClick = async (data: any) => {
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

const confirmImport = async () => {
	if (importSourceType.value === 'curl') {
		await importByCurl();
		return;
	}
	if (importSourceType.value === 'apifox') {
		await importByUrl();
		return;
	}
	if (importSourceType.value === 'postman') {
		await importByFile();
		return;
	}
	if (importTab.value === 'url') {
		await importByUrl();
		return;
	}
	await importByFile();
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
			} else if (n.type === 1) {
				const p = prefix ? prefix + ' / ' + n.name : n.name
				dirs.push({ id: n.id, path: p })
				walk(n.children || [], p)
			}
		}
	}
	walk(treeData.value || [], '')
	return { mods, dirs }
});

const menuDialogVisible = ref(false);
const menuDialogTitle = ref('');
const menuForm = ref({ name: '', type: 1, pid: 0, editId: 0, mode: 'add' as 'add' | 'edit', protocol: 'http' });

const handleAddCommand = (cmd: string) => {
	if (cmd === 'import_api') {
		openImportDialog();
		return;
	}
	if (cmd === 'add_module') {
		menuForm.value = { name: '', type: 0, pid: 0, editId: 0, mode: 'add_module' };
		menuDialogTitle.value = '添加模块';
		menuDialogVisible.value = true;
		return;
	}
	menuForm.value = { name: '', type: cmd === 'add_folder' ? 1 : 2, pid: 0, editId: 0, mode: 'add', protocol: 'http' };
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
		try {
			await add_api_service({ name: menuForm.value.name, api_project_id: props.serviceId || 0 });
			ElMessage.success('模块已创建（自动生成"接口"根目录）');
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
		try {
			await ElMessageBox.confirm(`确定删除模块「${data.name}」？所属根目录、子目录、接口将一并删除！`, '删除模块', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' });
		} catch { return; }
		try {
			await del_api_service({ id: Number(data.api_service_id) });
			ElMessage.success('模块已删除');
			loadTree();
		} catch (e: any) {
			ElMessage.error(e?.message || '删除失败');
		}
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
.tree-panel { width: 260px; flex-shrink: 0; border-right: 1px solid var(--el-border-color); display: flex; flex-direction: column; overflow: hidden; background: var(--el-bg-color); }
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
</style>
