<template>
	<el-dialog v-model="inner" title="绑定数据源" width="640px" destroy-on-close class="bind-ds-dialog" append-to-body>
		<el-form label-width="110px" class="bd-form">
			<el-form-item label="模块" required>
				<el-input :model-value="moduleName" size="small" style="width: 240px" disabled />
			</el-form-item>
			<el-form-item label="导入频率" required>
				<el-select v-model="form.frequency" size="small" style="width: 200px">
					<el-option label="手动触发" value="manual" />
					<el-option label="每隔 30 分钟" value="30m" />
					<el-option label="每隔 1 小时" value="1h" />
					<el-option label="每隔 3 小时" value="3h" />
					<el-option label="每隔 6 小时" value="6h" />
					<el-option label="每隔 12 小时" value="12h" />
					<el-option label="每隔 24 小时" value="24h" />
				</el-select>
			</el-form-item>
			<el-form-item label="数据源格式" required>
				<el-radio-group v-model="form.data_source_type">
					<el-radio-button value="swagger">OpenAPI/Swagger</el-radio-button>
					<el-radio-button value="apifox">Apifox</el-radio-button>
				</el-radio-group>
			</el-form-item>
			<el-form-item label="数据源名称" required>
				<el-input v-model="form.name" placeholder="请输入名称" size="small" style="width: 320px" />
			</el-form-item>
			<el-form-item label="数据源" required>
				<el-radio-group v-model="form.data_source">
					<el-radio value="url">URL</el-radio>
					<el-radio value="git">Git 仓库</el-radio>
				</el-radio-group>
			</el-form-item>
			<template v-if="form.data_source === 'url' && form.data_source_type === 'swagger'">
				<el-form-item label="URL" required>
					<el-input v-model="form.url" placeholder="输入 json 或 yaml 数据文件的 URL" size="small" style="width: 100%" />
					<span style="margin-left: 8px; flex: 0 0 auto; display: flex; align-items: center; gap: 4px">
						<span class="bd-hint">Basic Auth</span>
						<el-switch v-model="form.basic_auth.enabled" size="small" />
					</span>
				</el-form-item>
				<template v-if="form.basic_auth.enabled">
					<el-form-item label="账号">
						<el-input v-model="form.basic_auth.username" placeholder="账号" size="small" style="width: 320px" />
					</el-form-item>
					<el-form-item label="密码">
						<el-input v-model="form.basic_auth.password" type="password" placeholder="密码" show-password size="small" style="width: 320px" />
					</el-form-item>
				</template>
			</template>
			<template v-if="form.data_source === 'url' && form.data_source_type === 'apifox'">
				<el-form-item label="URL" required>
					<el-input v-model="form.url" placeholder="https://app.apifox.com/project/xxx 或 s.apifox.cn 分享链接" size="small" style="width: 100%" />
				</el-form-item>
			</template>
			<template v-else-if="form.data_source === 'git'">
				<el-form-item label="仓库地址" required>
					<el-input v-model="form.url" placeholder="https://git.example.com/group/repo.git" size="small" style="width: 100%" />
				</el-form-item>
				<el-form-item label=" ">
					<span class="bd-warn">Git 仓库数据源暂未支持，请使用 URL 数据源</span>
				</el-form-item>
			</template>

			<!-- 高级设置 -->
			<el-divider content-position="left" style="margin: 12px 0">
				<span class="bd-adv-toggle" @click="advOpen = !advOpen">
					高级设置 <el-icon :style="{ transform: advOpen ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform .2s' }"><ArrowRight /></el-icon>
				</span>
			</el-divider>
			<template v-if="advOpen">
				<el-tabs v-model="advTab" size="small">
					<el-tab-pane label="接口" name="api">
						<el-form-item label="导入到目录">
							<el-select v-model="form.pid" size="small" style="width: 240px" clearable>
																<el-option v-for="d in dirList" :key="d.id" :label="d.path" :value="d.id" />
							</el-select>
						</el-form-item>
						<el-form-item label="匹配到相同接口时">
							<span class="bd-hint">（根据 <a class="bd-link" @click="openIdKeyDialog">{{ idKeyLabel(form.match_id_key) }}</a>）</span>
						</el-form-item>
						<el-form-item label=" ">
							<div style="display: flex; align-items: center; gap: 16px; width: 100%">
								<el-select v-model="form.match_mode" size="small" style="width: 240px">
									<el-option label="覆盖已有接口" value="overwrite" />
									<el-option label="智能合并" value="smart_merge" />
									<el-option label="不导入" value="skip" />
								</el-select>
								<span v-if="form.match_mode !== 'skip'" style="display: flex; align-items: center; gap: 6px">
									<span class="bd-hint">更新接口所在目录</span>
									<el-switch v-model="form.update_location" size="small" />
								</span>
							</div>
						</el-form-item>
						<div class="bd-switch-row">
							<span class="bd-switch-label">接口路径加上 basePath</span>
							<el-switch v-model="form.base_path_enabled" size="small" />
						</div>
						<el-form-item v-if="form.base_path_enabled" label="BasePath">
							<el-input v-model="form.base_path" placeholder="/api/v1" size="small" style="width: 240px" />
						</el-form-item>
						<div class="bd-switch-row">
							<span class="bd-switch-label">删除不在数据源中的资源</span>
							<el-switch v-model="form.delete_missing" size="small" />
						</div>
						<div class="bd-switch-row">
							<span class="bd-switch-label">导入 Security Scheme</span>
							<el-switch v-model="form.import_security" size="small" />
						</div>
						<div class="bd-switch-row">
							<span class="bd-switch-label">将目录的 Auth 设置为 OpenAPI 的全局 Security</span>
							<el-switch v-model="form.global_auth" size="small" />
						</div>
						<template v-if="form.import_security">
							<div class="bd-cond-label">当导入的接口有设置 Security 时，将 Auth 设置为</div>
							<el-radio-group v-model="form.has_sec_strategy" class="bd-radio-col">
								<el-radio value="scheme">对应的鉴权组件</el-radio>
								<el-radio value="inherit">继承父级</el-radio>
								<el-radio value="none">无需鉴权</el-radio>
							</el-radio-group>
							<div class="bd-cond-label">当导入的接口未设置 Security 时，将 Auth 设置为</div>
							<el-radio-group v-model="form.no_sec_strategy" class="bd-radio-col">
								<el-radio value="inherit">继承父级</el-radio>
								<el-radio value="none">无需鉴权</el-radio>
								<el-radio value="scheme">对应的鉴权组件</el-radio>
							</el-radio-group>
						</template>
						<div class="bd-switch-row">
							<span class="bd-switch-label">将文件里的 Info 导入
								<el-tooltip placement="top" :width="360">
									<template #content>
										<div class="bd-info-tip">文件里的 OpenAPI Info（summary、description、termsOfService、contact、license、version）导入并覆盖当前项目中的对应内容。</div>
									</template>
									<el-icon class="bd-info-icon"><InfoFilled /></el-icon>
								</el-tooltip>
							</span>
							<el-switch v-model="form.import_info" size="small" />
						</div>
					</el-tab-pane>
					<el-tab-pane label="数据模型" name="model">
						<div class="bd-empty">数据模型同步暂未支持（当前仅同步接口）</div>
					</el-tab-pane>
				</el-tabs>
			</template>
		</el-form>

		<!-- 编辑分组的接口唯一标识 -->
		<el-dialog v-model="idKeyVisible" title="编辑分组的接口唯一标识" width="480px" append-to-body destroy-on-close>
			<el-form label-width="110px">
				<el-form-item label="导入到分组">
					<el-select v-model="idKeyPid" size="small" style="width: 100%" clearable>
												<el-option v-for="d in dirList" :key="d.id" :label="d.path" :value="d.id" />
					</el-select>
				</el-form-item>
				<el-form-item label="接口唯一标识">
					<el-select v-model="idKeyValue" size="small" style="width: 100%">
						<el-option label="继承父级" value="inherit" />
						<el-option label="Method & Path" value="method_path" />
						<el-option label="OperationId" value="operation_id" />
						<el-option label="Query 参数" value="query" />
						<el-option label="Body 参数" value="body" />
						<el-option label="Header 参数" value="header" />
					</el-select>
				</el-form-item>
			</el-form>
			<template #footer>
				<el-button @click="idKeyVisible = false">取消</el-button>
				<el-button type="primary" @click="saveIdKey">保存</el-button>
			</template>
		</el-dialog>

		<template #footer>
			<div style="display: flex; align-items: center; gap: 8px">
				<el-button :loading="syncing" @click="doSync" style="margin-right: auto">立即导入</el-button>
				<el-button v-if="isEdit" type="danger" plain :loading="deleting" @click="doDelete">删除</el-button>
				<el-button @click="inner = false">取消</el-button>
				<el-button type="primary" :loading="saving" @click="doSave">保存</el-button>
			</div>
		</template>
	</el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { ArrowRight, InfoFilled } from '@element-plus/icons-vue';
import { ElMessage } from 'element-plus';
import { api_tree, useApiAutomationApi } from '/@/api/v1/testing/apiAutomation';

const props = defineProps<{
	modelValue: boolean;
	serviceId: number;
	moduleName: string;
	existing?: Record<string, any> | null;
	moduleId?: number;
}>();

const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void; (e: 'saved'): void; (e: 'syncOk', result: any): void }>();

const inner = ref(false);
watch(
	() => props.modelValue,
	(v) => {
		inner.value = v;
		if (v) {
			advOpen.value = false;
			loadDirs();
			if (props.existing && props.existing.url) {
				form.value = {
					...defaultForm(),
					...props.existing,
					basic_auth: { enabled: !!props.existing.basic_auth?.username, username: props.existing.basic_auth?.username || '', password: props.existing.basic_auth?.password || '' },
				};
			} else {
				form.value = defaultForm();
			}
		}
	},
	{ immediate: true }
);
watch(inner, (v) => emit('update:modelValue', v));

const advOpen = ref(false);
const idKeyVisible = ref(false);
const idKeyPid = ref(0);
const idKeyValue = ref('method_path');

const idKeyLabel = (v: string) =>
	v === 'inherit' ? '继承父级' : v === 'operation_id' ? 'OperationId' : v === 'query' ? 'Query 参数' : v === 'body' ? 'Body 参数' : v === 'header' ? 'Header 参数' : 'Method & Path';

const openIdKeyDialog = () => {
	idKeyPid.value = form.value.pid || 0;
	idKeyValue.value = form.value.match_id_key || 'method_path';
	idKeyVisible.value = true;
};

const saveIdKey = async () => {
	const finalKey = idKeyValue.value === 'inherit' ? 'method_path' : idKeyValue.value;
	form.value.match_id_key = finalKey;
	// 写入分组（目录）的 common_params.id_key（合并，不覆盖其他配置）
	let targetPid = idKeyPid.value || form.value.pid || 0;
	if (!targetPid) {
		const root = dirList.value.find((d: any) => d.pid === 0);
		targetPid = root?.id || 0;
	}
	try {
		if (targetPid) {
			const { edit_menu } = await import('/@/api/v1/testing/apiAutomation');
			const dir = dirList.value.find((d: any) => d.id === targetPid);
			let cp: Record<string, any> = {};
			try { cp = dir?.common_params ? JSON.parse(dir.common_params) : {}; } catch { cp = {}; }
			if (!cp || typeof cp !== 'object') cp = {};
			cp.id_key = finalKey;
			await edit_menu({ id: targetPid, name: dir?.name || '', common_params: JSON.stringify(cp) } as any);
		}
	} catch { /* 静默 */ }
	idKeyVisible.value = false;
	ElMessage.success('接口唯一标识已更新');
};
const advTab = ref('api');
const dirList = ref<any[]>([]);
const saving = ref(false);
const syncing = ref(false);
const deleting = ref(false);
const isEdit = computed(() => !!props.existing?.url);

const defaultForm = () => ({
	frequency: '3h',
	data_source_type: 'swagger',
	name: '',
	data_source: 'url',
	url: '',
	basic_auth: { enabled: false, username: '', password: '' },
	pid: 0,
	match_mode: 'overwrite',
	match_id_key: 'method_path',
	base_path_enabled: false,
	base_path: '',
	delete_missing: false,
	import_security: true,
	global_auth: true,
	update_location: false,
	has_sec_strategy: 'scheme',
	no_sec_strategy: 'inherit',
	import_info: true,
	import_models: true,
	model_match_mode: 'overwrite',
	model_pid: 0,
});
const form = ref(defaultForm());

const loadDirs = async () => {
	try {
		const r: any = await api_tree({ search: { api_service_id: props.serviceId } });
		const raw = r?.data;
		const tree = Array.isArray(raw) ? raw : [];
				const dirs: any[] = [];
		// 树顶层为模块（type=5）：模块默认项=模块名（值=模块「接口」根目录 id），子目录缩进展示，「接口」根不列出
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
						// 数据模型不属于目录，不展示
						continue;
					}
					if (n.type === 1) {
						dirs.push({ id: n.id, path: '　'.repeat(depth) + n.name, pid: n.pid || 0, common_params: n.common_params || null, name: n.name });
						walkDir(n.children || [], depth + 1);
					}
				}
			};
			walkDir(mod.children || [], 1);
			dirs.push({ id: ifaceRootId, path: mod.name, pid: 0, common_params: mod.common_params || null, name: mod.name });
		};
		// 只展示当前关联模块，不匹配其他模块的目录
		const cur = tree.find((n: any) => Number(n.id) === Number(props.moduleId || 0));
		if (cur) walkMod(cur);
		if (!dirs.length) dirs.push({ id: 0, path: props.moduleName || '', pid: 0, common_params: null, name: props.moduleName || '' });
		dirList.value = dirs;
		if (!form.value.pid && dirList.value.length) form.value.pid = dirList.value[0].id;
	} catch { dirList.value = []; }
};

const buildConfig = () => {
	const f = form.value;
	return {
		data_source_type: f.data_source_type,
		name: f.name,
		data_source: f.data_source,
		url: f.url.trim(),
		frequency: f.frequency,
		basic_auth: f.basic_auth.enabled ? { username: f.basic_auth.username.trim(), password: f.basic_auth.password } : null,
		pid: f.pid || 0,
		match_mode: f.match_mode,
		match_id_key: f.match_id_key,
		base_path: f.base_path_enabled ? f.base_path.trim() : '',
		delete_missing: f.delete_missing,
		import_security: f.import_security,
		global_auth: f.global_auth,
		update_location: f.update_location,
		has_sec_strategy: f.has_sec_strategy,
		no_sec_strategy: f.no_sec_strategy,
		import_info: f.import_info,
		import_models: f.import_models,
		model_match_mode: f.model_match_mode,
		model_pid: f.model_pid || 0,
	};
};

const validate = () => {
	if (!form.value.name.trim()) { ElMessage.warning('请输入数据源名称'); return false; }
	if (!form.value.url.trim()) { ElMessage.warning('请输入数据源 URL'); return false; }
	return true;
};

const doSave = async () => {
	if (!validate()) return;
	saving.value = true;
	try {
		await useApiAutomationApi().saveDataSource({ service_id: props.serviceId, module_id: props.moduleId || 0, config: buildConfig() });
		ElMessage.success('数据源已保存');
		inner.value = false;
		emit('saved');
	} catch (e: any) {
		ElMessage.error(e?.message || '保存失败');
	} finally { saving.value = false; }
};

const doDelete = async () => {
	deleting.value = true;
	try {
		await useApiAutomationApi().saveDataSource({ service_id: props.serviceId, config: {} });
		ElMessage.success('数据源已删除');
		inner.value = false;
		emit('saved');
	} catch (e: any) {
		ElMessage.error(e?.message || '删除失败');
	} finally { deleting.value = false; }
};

const doSync = async () => {
	if (!validate()) return;
	syncing.value = true;
	try {
		// 立即导入：用表单配置临时拉取（不保存数据源，只有点「保存」才写库）
		const r: any = await useApiAutomationApi().syncDataSource({ service_id: props.serviceId, module_id: props.moduleId || 0, config: buildConfig() });
		if (r?.code === 200) {
			emit('syncOk', r.data || { imported: 0, updated: 0, folders: 0, models: 0 });
		} else {
			ElMessage.error(r?.message || '同步失败');
		}
	} catch (e: any) {
		ElMessage.error(e?.message || '同步失败');
	} finally { syncing.value = false; }
};
</script>

<style scoped>
.bd-form .el-form-item { margin-bottom: 14px; }
.bd-hint { font-size: 12px; color: var(--el-text-color-secondary); }
.bd-warn { font-size: 12px; color: #e6a23c; }
.bd-adv-toggle { cursor: pointer; font-size: 13px; color: var(--el-text-color-regular); display: inline-flex; align-items: center; gap: 4px; }
.bd-switch-row { display: flex; align-items: center; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.bd-switch-label { font-size: 13px; color: var(--el-text-color-primary); }
.bd-cond-label { font-size: 12px; color: var(--el-text-color-secondary); margin: 10px 0 4px; }
.bd-radio-col { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; }
.bd-empty { font-size: 12px; color: var(--el-text-color-secondary); text-align: center; padding: 30px 0; }
.bd-link { color: #7c3aed; cursor: pointer; }
.bd-info-icon { margin-left: 4px; color: var(--el-text-color-secondary); cursor: help; vertical-align: middle; }
.bd-info-tip { font-size: 12px; line-height: 1.7; color: var(--el-text-color-regular); }
</style>
