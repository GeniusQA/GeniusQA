<template>
	<el-dialog v-model="inner" title="绑定数据源" width="640px" destroy-on-close class="bind-ds-dialog" append-to-body>
		<el-form label-width="110px" class="bd-form">
			<el-form-item label="目标分支" required>
				<el-input v-model="form.branch" placeholder="main" size="small" style="width: 200px" :disabled="form.data_source === 'url'" />
				<span class="bd-hint" v-if="form.data_source === 'url'">URL 数据源无需分支</span>
			</el-form-item>
			<el-form-item label="模块" required>
				<el-input :model-value="moduleName" size="small" style="width: 240px" disabled />
			</el-form-item>
			<el-form-item label="导入频率" required>
				<el-select v-model="form.frequency" size="small" style="width: 200px">
					<el-option label="每 30 分钟" value="30m" />
					<el-option label="每 1 小时" value="1h" />
					<el-option label="每隔 3 小时" value="3h" />
					<el-option label="每隔 6 小时" value="6h" />
					<el-option label="每隔 12 小时" value="12h" />
					<el-option label="每天" value="24h" />
				</el-select>
			</el-form-item>
			<el-form-item label="数据源格式" required>
				<el-radio-group v-model="form.data_source_type">
					<el-radio-button value="swagger">OpenAPI (Swagger)</el-radio-button>
					<el-radio-button value="apidoc">apiDoc</el-radio-button>
					<el-radio-button value="apifox">Apifox</el-radio-button>
					<el-radio-button value="knife4j">Knife4j</el-radio-button>
					<el-radio-button value="yapi">YApi</el-radio-button>
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
			<template v-if="form.data_source === 'url'">
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
			<template v-else>
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
								<el-option label="根目录" :value="0" />
								<el-option v-for="d in dirList" :key="d.id" :label="d.path" :value="d.id" />
							</el-select>
						</el-form-item>
						<el-form-item label="匹配到相同接口时">
							<span class="bd-hint">（根据 Method & Path）</span>
						</el-form-item>
						<el-form-item label=" ">
							<el-radio-group v-model="form.match_mode">
								<el-radio value="overwrite">覆盖已有接口</el-radio>
								<el-radio value="move">更新接口所在目录</el-radio>
							</el-radio-group>
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
							<span class="bd-switch-label">将文件里的 Info 导入</span>
							<el-switch v-model="form.import_info" size="small" />
						</div>
					</el-tab-pane>
					<el-tab-pane label="数据模型" name="model">
						<div class="bd-empty">数据模型同步暂未支持（当前仅同步接口）</div>
					</el-tab-pane>
				</el-tabs>
			</template>
		</el-form>
		<template #footer>
			<div style="display: flex; align-items: center; gap: 8px">
				<el-button :loading="syncing" @click="doSync" style="margin-right: auto">立即导入</el-button>
				<el-button @click="inner = false">取消</el-button>
				<el-button type="primary" :loading="saving" @click="doSave">保存</el-button>
			</div>
		</template>
	</el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { ArrowRight } from '@element-plus/icons-vue';
import { ElMessage } from 'element-plus';
import { api_tree, useApiAutomationApi } from '/@/api/v1/testing/apiAutomation';

const props = defineProps<{
	modelValue: boolean;
	serviceId: number;
	moduleName: string;
	existing?: Record<string, any> | null;
}>();

const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void; (e: 'saved'): void }>();

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
const advTab = ref('api');
const dirList = ref<any[]>([]);
const saving = ref(false);
const syncing = ref(false);

const defaultForm = () => ({
	branch: 'main',
	frequency: '3h',
	data_source_type: 'swagger',
	name: '',
	data_source: 'url',
	url: '',
	basic_auth: { enabled: false, username: '', password: '' },
	pid: 0,
	match_mode: 'overwrite',
	base_path_enabled: false,
	base_path: '',
	delete_missing: false,
	import_security: true,
	global_auth: true,
	has_sec_strategy: 'scheme',
	no_sec_strategy: 'inherit',
	import_info: true,
});
const form = ref(defaultForm());

const loadDirs = async () => {
	try {
		const r: any = await api_tree({ search: { api_service_id: props.serviceId } });
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
	} catch { dirList.value = []; }
};

const buildConfig = () => {
	const f = form.value;
	return {
		data_source_type: f.data_source_type,
		name: f.name,
		data_source: f.data_source,
		url: f.url.trim(),
		branch: f.branch.trim(),
		frequency: f.frequency,
		basic_auth: f.basic_auth.enabled ? { username: f.basic_auth.username.trim(), password: f.basic_auth.password } : null,
		pid: f.pid || 0,
		match_mode: f.match_mode,
		base_path: f.base_path_enabled ? f.base_path.trim() : '',
		delete_missing: f.delete_missing,
		import_security: f.import_security,
		global_auth: f.global_auth,
		has_sec_strategy: f.has_sec_strategy,
		no_sec_strategy: f.no_sec_strategy,
		import_info: f.import_info,
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
		await useApiAutomationApi().saveDataSource({ service_id: props.serviceId, config: buildConfig() });
		ElMessage.success('数据源已保存');
		inner.value = false;
		emit('saved');
	} catch (e: any) {
		ElMessage.error(e?.message || '保存失败');
	} finally { saving.value = false; }
};

const doSync = async () => {
	if (!validate()) return;
	syncing.value = true;
	try {
		await useApiAutomationApi().saveDataSource({ service_id: props.serviceId, config: buildConfig() });
		const r: any = await useApiAutomationApi().syncDataSource({ service_id: props.serviceId });
		if (r?.code === 200) {
			ElMessage.success(`同步完成：导入 ${r.data?.imported || 0} 个接口`);
			inner.value = false;
			emit('saved');
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
</style>
