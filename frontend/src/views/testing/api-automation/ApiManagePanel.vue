<template>
	<div class="manage-panel">
		<!-- 顶部工具栏 -->
		<div class="manage-toolbar">
			<div class="toolbar-row">
				<div class="toolbar-tools">
					<el-button type="primary" size="small" @click="openImportDialog">导入接口</el-button>
					<el-popover placement="bottom" :width="900" trigger="click">
						<template #reference>
							<el-button size="small" type="info">直连数据库</el-button>
						</template>
						<ApiDbPopover />
					</el-popover>
					<el-popover placement="bottom" :width="800" trigger="click">
						<template #reference>
							<el-button size="small" type="primary">全局变量</el-button>
						</template>
						<ApiVarPopover />
					</el-popover>
					<el-button size="small" type="warning" @click="commonParamsRef?.open()">全局参数</el-button>
				</div>
			</div>
		</div>

		<ApiCommonParamsDialog ref="commonParamsRef" :service-id="serviceId" />

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
								<el-dropdown-item command="add_folder">添加目录</el-dropdown-item>
								<el-dropdown-item command="add_api">添加接口</el-dropdown-item>
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
					class="api-tree"
					@node-click="onNodeClick"
				>
					<template #default="{ data }">
						<div class="tree-node">
							<div class="node-left">
								<el-icon v-if="data.type===1" class="icon-folder"><FolderOpened /></el-icon>
								<el-icon v-else-if="data.type===3" class="icon-case"><Link /></el-icon>
								<span v-if="data.type===2||data.type===3" class="method-badge" :style="{background: methodColor(data.method)}">{{ methodLabel(data.method) }}</span>
								<span class="node-name">{{ data.name }}</span>
							</div>
							<el-dropdown trigger="click" @command="(cmd) => handleNodeCommand(cmd, data)" @click.stop>
								<el-icon class="node-more"><MoreFilled /></el-icon>
								<template #dropdown>
									<el-dropdown-menu>
										<el-dropdown-item v-if="data.type===1" command="add_folder">添加子目录</el-dropdown-item>
										<el-dropdown-item v-if="data.type===1" command="add_api">添加接口</el-dropdown-item>
										<el-dropdown-item v-if="data.type===1" command="menu_params">目录参数</el-dropdown-item>
										<el-dropdown-item v-if="data.type===2" command="copy">复制接口</el-dropdown-item>
										<el-dropdown-item command="rename">重命名</el-dropdown-item>
										<el-dropdown-item command="delete" divided>删除</el-dropdown-item>
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
		<el-dialog v-model="importDialogVisible" title="导入接口" width="560px" destroy-on-close @closed="onImportDialogClosed">
			<el-tabs v-model="importTab">
				<el-tab-pane label="URL 导入" name="url">
					<el-form label-width="100px">
						<el-form-item label="文档类型" required>
							<el-select v-model="doc_source_type" style="width:100%">
								<el-option label="Swagger" value="swagger" />
								<el-option label="Apifox" value="apifox" />
							</el-select>
						</el-form-item>
						<el-form-item label="文档 URL" required>
							<el-input v-model="doc_source_url" placeholder="输入文档 URL" clearable />
						</el-form-item>
						<el-form-item v-if="doc_source_type === 'apifox'" label="Cookies" required>
							<el-input v-model="doc_source_cookies" placeholder="Apifox Cookies（必填）" clearable />
						</el-form-item>
					</el-form>
				</el-tab-pane>
				<el-tab-pane label="文件导入" name="file">
					<el-form label-width="100px">
						<el-form-item label="文档类型" required>
							<el-select v-model="file_source_type" style="width:100%">
								<el-option label="Swagger" value="swagger" />
								<el-option label="Apifox" value="apifox" />
							</el-select>
						</el-form-item>
						<el-form-item label="文档文件" required>
							<el-upload
								ref="uploadRef"
								:auto-upload="false"
								:limit="1"
								accept=".json"
								:on-change="onImportFileChange"
								:on-remove="onImportFileRemove"
								:on-exceed="onImportFileExceed"
							>
								<el-button size="small">选择 JSON 文件</el-button>
								<template #tip>
									<div class="el-upload__tip">支持 OpenAPI / Swagger JSON，以及 Apifox「导出项目」JSON；YAML 请先转为 JSON</div>
								</template>
							</el-upload>
						</el-form-item>
					</el-form>
				</el-tab-pane>
			</el-tabs>
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
			</el-form>
			<template #footer>
				<el-button @click="menuDialogVisible=false">取消</el-button>
				<el-button type="primary" @click="confirmMenu">确定</el-button>
			</template>
		</el-dialog>
	</div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import type { UploadFile, UploadInstance, UploadProps, UploadRawFile } from 'element-plus';
import { ArrowDown, FolderOpened, Link, MoreFilled, Document } from '@element-plus/icons-vue';
import ApiDetail from './api_detail.vue';
import ApiDbPopover from './components/ApiDbPopover.vue';
import ApiVarPopover from './components/ApiVarPopover.vue';
import ApiCommonParamsDialog from './components/ApiCommonParamsDialog.vue';
import ApiDocPanel from './components/ApiDocPanel.vue';
import ApiHistoryPanel from './components/ApiHistoryPanel.vue';
import ApiMockPanel from './components/ApiMockPanel.vue';
import {
	api_tree, api_info, add_menu, del_menu, edit_menu, copy_menu,
	pull_api_doc, edit_api_service,
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

const commonParamsRef = ref<InstanceType<typeof ApiCommonParamsDialog> | null>(null);

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
const importTab = ref<'url' | 'file'>('url');
const doc_source_type = ref('swagger');
const doc_source_url = ref('');
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

const openImportDialog = () => {
	applySourceFromProps();
	importTab.value = 'url';
	doc_source_cookies.value = '';
	importFileContent.value = null;
	uploadRef.value?.clearFiles();
	importDialogVisible.value = true;
};

const onImportDialogClosed = () => {
	importFileContent.value = null;
	uploadRef.value?.clearFiles();
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

	const lower = (raw.name || '').toLowerCase();
	if (lower.endsWith('.yaml') || lower.endsWith('.yml')) {
		ElMessage.warning('暂不支持 YAML，请先转为 JSON 再导入');
		uploadRef.value?.clearFiles();
		return;
	}

	try {
		const text = await readFileAsText(raw);
		const parsed = JSON.parse(text);
		if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
			throw new Error('文档内容必须是 JSON 对象');
		}
		importFileContent.value = parsed as Record<string, any>;
	} catch (e: any) {
		importFileContent.value = null;
		uploadRef.value?.clearFiles();
		ElMessage.error(e?.message?.includes('JSON') || e instanceof SyntaxError ? 'JSON 解析失败，请检查文件格式' : (e?.message || '文件解析失败'));
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
	if (importTab.value === 'url') {
		await importByUrl();
	} else {
		await importByFile();
	}
};

const importByUrl = async () => {
	if (!doc_source_url.value.trim()) {
		ElMessage.warning('请输入文档地址');
		return;
	}
	if (doc_source_type.value === 'apifox' && !doc_source_cookies.value.trim()) {
		ElMessage.warning('Apifox 需要填写 Cookies');
		return;
	}
	pulling.value = true;
	try {
		const source_type = normalizeSourceType(doc_source_type.value);
		const doc_url = doc_source_url.value.trim();
		try {
			await saveSourceNow(source_type, doc_url);
		} catch { /* 保存失败不阻断拉取 */ }
		await pull_api_doc({
			api_service_id: props.serviceId,
			source_type: source_type as 'swagger' | 'apifox',
			doc_url,
			...(source_type === 'apifox' ? { cookies: doc_source_cookies.value.trim() } : {}),
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
		ElMessage.warning('请选择要导入的 JSON 文件');
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
			doc_content: importFileContent.value,
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
const menuDialogVisible = ref(false);
const menuDialogTitle = ref('');
const menuForm = ref({ name: '', type: 1, pid: 0, editId: 0, mode: 'add' as 'add' | 'edit' });

const handleAddCommand = (cmd: string) => {
	menuForm.value = { name: '', type: cmd === 'add_folder' ? 1 : 2, pid: 0, editId: 0, mode: 'add' };
	menuDialogTitle.value = cmd === 'add_folder' ? '添加目录' : '添加接口';
	menuDialogVisible.value = true;
};

const handleNodeCommand = (cmd: string, data: any) => {
	if (cmd === 'menu_params') {
		commonParamsRef.value?.open(data.id)
		return
	}
	if (cmd === 'add_folder') {
		menuForm.value = { name: '', type: 1, pid: data.id, editId: 0, mode: 'add' };
		menuDialogTitle.value = '添加子目录';
		menuDialogVisible.value = true;
	} else if (cmd === 'add_api') {
		menuForm.value = { name: '', type: 2, pid: data.id, editId: 0, mode: 'add' };
		menuDialogTitle.value = '添加接口';
		menuDialogVisible.value = true;
	} else if (cmd === 'rename') {
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
	if (!menuForm.value.name.trim()) { ElMessage.warning('请输入名称'); return; }
	try {
		if (menuForm.value.mode === 'edit') {
			await edit_menu({ id: menuForm.value.editId, name: menuForm.value.name.trim() });
		} else {
			await add_menu({ name: menuForm.value.name.trim(), pid: menuForm.value.pid, type: menuForm.value.type, api_service_id: props.serviceId });
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

onMounted(() => { loadTree(); });
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
</style>
