<template>
	<el-dialog v-model="inner" title="导入预览 & 配置" width="760px" destroy-on-close class="import-preview-dialog" append-to-body>
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
		const walk = (nodes: any[], prefix: string) => {
			for (const n of nodes || []) {
				if (n.type === 1) {
					const p = prefix ? prefix + ' / ' + n.name : n.name;
					dirs.push({ id: n.id, path: p });
					walk(n.children || [], p);
				} else if (n.type === 0) {
					walk(n.children || [], n.name);
				}
			}
		};
		walk(tree, '');
		dirList.value = dirs;
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
.ipv-body { display: flex; gap: 14px; min-height: 360px; }
.ipv-left { flex: 1.2; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; padding: 10px; display: flex; flex-direction: column; }
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
</style>
