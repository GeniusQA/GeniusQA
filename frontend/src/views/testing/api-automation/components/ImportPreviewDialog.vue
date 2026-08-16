<template>
	<el-dialog v-model="inner" title="导入预览 & 配置" width="960px" destroy-on-close class="import-preview-dialog" append-to-body>
		<div class="ipv-body">
			<!-- 左侧：预览 & 勾选 -->
			<div class="ipv-left">
				<div class="ipv-panel-title">预览 & 勾选</div>
				<el-input v-model="treeFilter" placeholder="搜索..." size="small" clearable class="ipv-search" />
				<el-tree
					ref="treeRef"
					:data="treeData"
					show-checkbox
					node-key="key"
					:default-checked-keys="allKeys"
					:filter-node-method="filterNode"
					class="ipv-tree"
				>
					<template #default="{ data }">
						<div class="ipv-node">
							<span class="ipv-method" :style="{ background: methodColor(data.method) }">{{ data.method }}</span>
							<span class="ipv-node-name">{{ data.name }}</span>
							<span class="ipv-node-url">{{ data.url }}</span>
						</div>
					</template>
				</el-tree>
			</div>
			<!-- 右侧：配置 -->
			<div class="ipv-right">
				<div class="ipv-panel-title">导入配置</div>
				<div class="ipv-config">
					<div class="ipv-label">导入到</div>
					<el-radio-group v-model="importTo" class="ipv-radio-row">
						<el-radio value="new">创建新模块</el-radio>
						<el-radio value="existing">已有模块</el-radio>
					</el-radio-group>
					<template v-if="importTo === 'new'">
						<el-input v-model="moduleName" placeholder="模块名称" size="small" class="ipv-input" />
					</template>
					<template v-else>
						<div class="ipv-label">选择模块</div>
						<el-select v-model="selectedSvc" size="small" style="width: 100%" @change="onSvcChange">
							<el-option v-for="s in svcList" :key="s.id" :label="s.name" :value="s.id" />
						</el-select>
						<div class="ipv-label" style="margin-top: 10px">目标目录</div>
						<el-select v-model="targetPid" size="small" style="width: 100%">
							<el-option label="根目录" :value="0" />
							<el-option v-for="d in dirList" :key="d.id" :label="d.path" :value="d.id" />
						</el-select>
					</template>
					<div class="ipv-switch-row">
						<span class="ipv-switch-label">为每个接口自动生成一个调试用例</span>
						<el-switch v-model="genCase" />
					</div>
					<div class="ipv-switch-row">
						<span class="ipv-switch-label">将 OpenAPI/Swagger 里的 Servers 导入为环境</span>
						<el-switch v-model="serversToEnv" />
					</div>
					<div class="ipv-switch-row">
						<span class="ipv-switch-label">导入 Security Scheme</span>
						<el-switch v-model="importSecurity" />
					</div>
					<div class="ipv-switch-row">
						<span class="ipv-switch-label">将目录 Auth 设置为 OpenAPI 的全局 Security</span>
						<el-switch v-model="globalAuth" />
					</div>
					<div class="ipv-switch-row">
						<span class="ipv-switch-label">导入数据模型（OpenAPI schemas）</span>
						<el-switch v-model="importModels" />
					</div>
					<template v-if="importModels">
						<div class="ipv-label" style="margin-top: 6px">匹配到同名数据模型时</div>
						<el-select v-model="modelMatchMode" size="small" style="width: 100%">
							<el-option label="覆盖已有数据模型" value="overwrite" />
							<el-option label="智能合并" value="smart_merge" />
							<el-option label="不导入" value="skip" />
						</el-select>
						<div class="ipv-label" style="margin-top: 6px">目标目录（数据模型）</div>
						<el-select v-model="modelPid" size="small" style="width: 100%" clearable>
							<el-option label="数据模型（根）" :value="0" />
							<el-option v-for="d in dirList" :key="d.id" :label="d.path" :value="d.id" />
						</el-select>
					</template>
					<div class="ipv-switch-row">
						<span class="ipv-switch-label">将文件里的 Info 导入</span>
						<el-switch v-model="importInfo" />
					</div>
					<div class="ipv-label" style="margin-top: 8px">接口 Summary 为空时使用</div>
					<el-select v-model="nameRule" size="small" style="width: 100%">
						<el-option label="使用 operationId" value="operation_id" />
						<el-option label="使用 path" value="path" />
						<el-option label="从 description 提取" value="description" />
					</el-select>
					<el-collapse v-model="conflictOpen" class="ipv-collapse">
						<el-collapse-item name="conflict" title="项目内已经存在相同资源时，如何处理">
							<div class="ipv-label">匹配到相同接口时（根据 {{ idKeyLabel(matchIdKey) }}）</div>
							<el-select v-model="matchMode" size="small" style="width: 100%">
								<el-option label="覆盖已有接口" value="overwrite" />
								<el-option label="智能合并" value="smart_merge" />
								<el-option label="不导入" value="skip" />
							</el-select>
							<div class="ipv-label" style="margin-top: 6px">接口唯一标识</div>
							<el-select v-model="matchIdKey" size="small" style="width: 100%">
								<el-option label="Method & Path" value="method_path" />
								<el-option label="OperationId" value="operation_id" />
								<el-option label="Query 参数" value="query" />
								<el-option label="Body 参数" value="body" />
								<el-option label="Header 参数" value="header" />
							</el-select>
							<div v-if="matchMode !== 'skip'" class="ipv-switch-row" style="margin-top: 6px">
								<span class="ipv-switch-label">更新接口所在目录</span>
								<el-switch v-model="updateLocation" size="small" />
							</div>
						</el-collapse-item>
						<el-collapse-item name="missing" title="项目内已经存在，但新数据源中不存在的资源，如何处理">
							<div class="ipv-switch-row">
								<span class="ipv-switch-label">删除不在数据源中的资源</span>
								<el-switch v-model="deleteMissing" size="small" />
							</div>
						</el-collapse-item>
					</el-collapse>
					<template v-if="importSecurity">
						<div class="ipv-label" style="margin-top: 10px">当导入的接口有设置 Security 时</div>
						<el-radio-group v-model="hasSecStrategy" class="ipv-radio-col">
							<el-radio value="inherit">继承父级</el-radio>
							<el-radio value="none">无需鉴权</el-radio>
							<el-radio value="scheme">对应的鉴权组件</el-radio>
						</el-radio-group>
						<div class="ipv-label" style="margin-top: 8px">未设置 Security 时</div>
						<el-radio-group v-model="noSecStrategy" class="ipv-radio-col">
							<el-radio value="inherit">继承父级</el-radio>
							<el-radio value="none">无需鉴权</el-radio>
							<el-radio value="scheme">对应的鉴权组件</el-radio>
						</el-radio-group>
					</template>
				</div>
			</div>
		</div>
		<template #footer>
			<el-button @click="inner = false">取消</el-button>
			<el-button type="primary" :loading="importing" @click="doImport" style="flex: 1">确定导入</el-button>
		</template>
	</el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { api_tree, api_service_list, pull_api_doc } from '/@/api/v1/testing/apiAutomation';

const props = defineProps<{
	modelValue: boolean;
	previewList: any[];
	serviceId: number;
	serviceName?: string;
	importParams: Record<string, any>;
}>();

const emit = defineEmits<{
	(e: 'update:modelValue', v: boolean): void;
	(e: 'imported'): void;
}>();

const inner = ref(false);
watch(
	() => props.modelValue,
	(v) => {
		inner.value = v;
		if (v) {
			treeFilter.value = '';
			importTo.value = 'existing';
			moduleName.value = '';
			targetPid.value = 0;
			genCase.value = true;
			serversToEnv.value = false;
			importSecurity.value = true;
			globalAuth.value = true;
			hasSecStrategy.value = 'inherit';
			noSecStrategy.value = 'inherit';
			matchMode.value = 'overwrite';
			matchIdKey.value = 'method_path';
			nameRule.value = 'operation_id';
			importInfo.value = true;
			importModels.value = true;
			modelMatchMode.value = 'overwrite';
			modelPid.value = 0;
			conflictOpen.value = [];
			updateLocation.value = false;
			deleteMissing.value = false;
			selectedSvc.value = Number(props.serviceId) || 0;
			loadSvcList();
			loadDirs();
			// 等树渲染后勾选全部
			setTimeout(() => {
				treeRef.value?.setCheckedKeys(props.previewList.map((p: any) => p.key));
			}, 50);
		}
	},
	{ immediate: true }
);
watch(inner, (v) => emit('update:modelValue', v));

const treeFilter = ref('');
const treeRef = ref<any>();
const importTo = ref<'new' | 'existing'>('existing');
const moduleName = ref('');
const targetPid = ref(0);
const genCase = ref(true);
const serversToEnv = ref(false);
const importSecurity = ref(true);
const globalAuth = ref(true);
const hasSecStrategy = ref('inherit');
const noSecStrategy = ref('inherit');
const matchMode = ref('overwrite');
const matchIdKey = ref('method_path');
const nameRule = ref('operation_id');
const importInfo = ref(true);
const importModels = ref(true);
const modelMatchMode = ref('overwrite');
const modelPid = ref(0);
const conflictOpen = ref([]);
const updateLocation = ref(false);
const deleteMissing = ref(false);

const idKeyLabel = (v: string) =>
	v === 'operation_id' ? 'OperationId' : v === 'query' ? 'Query 参数' : v === 'body' ? 'Body 参数' : v === 'header' ? 'Header 参数' : 'Method & Path';
const dirList = ref<any[]>([]);
const svcList = ref<any[]>([]);
const selectedSvc = ref<number>(0);
const importing = ref(false);

const treeData = computed(() =>
	props.previewList.map((p: any, i: number) => ({
		key: String(p.key || `${p.method} ${p.url} ${i}`),
		name: p.name,
		method: p.method,
		url: p.url,
	}))
);
const allKeys = computed(() => treeData.value.map((n: any) => n.key));

const METHOD_MAP: Record<string, string> = {
	GET: '#67C23A', POST: '#409EFF', PUT: '#E6A23C', DELETE: '#F56C6C',
	PATCH: '#8E44AD', HEAD: '#909399', OPTIONS: '#909399',
};
const methodColor = (m: string) => METHOD_MAP[m] || '#909399';

const filterNode = (value: string, data: any) => {
	if (!value) return true;
	return String(data.name || '').includes(value) || String(data.url || '').includes(value) || String(data.method || '').includes(value.toUpperCase());
};

const loadSvcList = async () => {
	try {
		const r: any = await api_service_list({});
		svcList.value = Array.isArray(r?.data) ? r.data : [];
		if (!svcList.value.some((s: any) => Number(s.id) === selectedSvc.value)) {
			selectedSvc.value = svcList.value[0]?.id || 0;
		}
		loadDirs();
	} catch {
		svcList.value = [];
	}
};

const onSvcChange = () => {
	targetPid.value = 0;
	loadDirs();
};

const loadDirs = async () => {
	try {
		const svcId = importTo.value === 'existing' ? selectedSvc.value : props.serviceId;
		const r: any = await api_tree({ search: { api_service_id: svcId } });
		const raw = r?.data;
		const tree = Array.isArray(raw) ? raw : [];
				const dirs: any[] = [];
		// 树顶层为模块（type=5）：每个模块一个默认项（模块名→其「接口」根目录 id）+ 其子目录
		const walkMod = (mod: any) => {
			let ifaceRootId: any = mod.id;
			const walkDir = (nodes: any[], depth: number) => {
				for (const n of nodes || []) {
					if (n.type === 1 && Number(n.pid) === Number(mod.id) && n.name === '接口') {
						ifaceRootId = n.id;
						walkDir(n.children || [], 1);
						continue;
					}
					if (n.type === 1 && n.name === '数据模型') {
						continue;
					}
					if (n.type === 1) {
						dirs.push({ id: n.id, path: '　'.repeat(depth) + n.name });
						walkDir(n.children || [], depth + 1);
					}
				}
			};
			walkDir(mod.children || [], 1);
			dirs.push({ id: ifaceRootId, path: mod.name });
		};
		for (const m of tree) walkMod(m);
		if (!dirs.length) dirs.push({ id: 0, path: '' });
		dirList.value = dirs;
		if (!targetPid.value && dirList.value.length) targetPid.value = dirList.value[0].id;
	} catch {
		dirList.value = [];
	}
};

const doImport = async () => {
	if (importTo.value === 'new' && !moduleName.value.trim()) {
		ElMessage.warning('请填写模块名称');
		return;
	}
	const checked = treeRef.value?.getCheckedKeys() || [];
	if (!checked.length) {
		ElMessage.warning('请至少勾选一个接口');
		return;
	}
	importing.value = true;
	try {
		const r: any = await pull_api_doc({
			api_service_id: importTo.value === 'new' ? props.serviceId : selectedSvc.value,
			...props.importParams,
			selected: checked,
			create_module: importTo.value === 'new',
			module_name: moduleName.value.trim(),
			pid: importTo.value === 'new' ? 0 : targetPid.value,
			gen_case: genCase.value,
			servers_to_env: serversToEnv.value,
			import_security: importSecurity.value,
			global_auth: globalAuth.value,
			has_sec_strategy: hasSecStrategy.value,
			no_sec_strategy: noSecStrategy.value,
			match_mode: matchMode.value,
			match_id_key: matchIdKey.value,
			name_rule: nameRule.value,
			import_info: importInfo.value,
			import_models: importModels.value,
			model_match_mode: modelMatchMode.value,
			model_pid: modelPid.value,
			update_location: updateLocation.value,
			delete_missing: deleteMissing.value,
		});
		if (r?.code === 200) {
			ElMessage.success('导入成功');
			inner.value = false;
			emit('imported');
		} else {
			ElMessage.error(r?.message || '导入失败');
		}
	} catch (e: any) {
		ElMessage.error(e?.message || '导入失败');
	} finally {
		importing.value = false;
	}
};
</script>

<style scoped>
.ipv-body { display: flex; gap: 16px; min-height: 480px; }
.ipv-left { flex: 1.35; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; padding: 10px; display: flex; flex-direction: column; }
.ipv-right { flex: 1; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; padding: 12px; }
.ipv-panel-title { font-size: 13px; font-weight: 600; margin-bottom: 10px; }
.ipv-search { margin-bottom: 8px; }
.ipv-tree { flex: 1; overflow: auto; }
.ipv-node { display: flex; align-items: center; gap: 8px; min-width: 0; }
.ipv-method { font-size: 10px; color: #fff; border-radius: 4px; padding: 2px 6px; flex: 0 0 auto; }
.ipv-node-name { font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ipv-node-url { font-size: 11px; color: #909399; font-family: Consolas, Monaco, monospace; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ipv-config { display: flex; flex-direction: column; gap: 4px; }
.ipv-label { font-size: 12px; color: var(--el-text-color-secondary); margin-bottom: 4px; }
.ipv-radio-row { margin-bottom: 8px; }
.ipv-input { margin-bottom: 8px; }
.ipv-module-name { font-size: 13px; color: var(--el-text-color-primary); padding: 6px 10px; background: var(--el-fill-color-light); border-radius: 4px; }
.ipv-switch-row { display: flex; align-items: center; justify-content: space-between; margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--el-border-color-lighter); }
.ipv-switch-label { font-size: 12px; color: var(--el-text-color-regular); }
.ipv-radio-col { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; }
.ipv-collapse { margin-top: 8px; border: none; }
.ipv-collapse :deep(.el-collapse-item__header) { font-size: 13px; color: var(--el-text-color-regular); height: 36px; }
.ipv-collapse :deep(.el-collapse-item__wrap) { border-bottom: none; }
</style>
