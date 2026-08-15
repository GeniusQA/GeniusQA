<template>
	<el-dialog v-model="visible" title="环境管理" width="1000px" top="5vh" destroy-on-close @closed="onClosed">
		<div class="env-center">
			<!-- 左栏：分组菜单 -->
			<div class="env-side">
				<div class="env-group-title">全局</div>
				<div class="env-menu-item" :class="{ active: section === 'global-var' }" @click="section = 'global-var'">
					<el-icon><DataBoard /></el-icon><span>全局变量</span>
				</div>
				<div class="env-menu-item" :class="{ active: section === 'global-params' }" @click="switchParams">
					<el-icon><Setting /></el-icon><span>全局参数</span>
				</div>

				<div class="env-group-title">环境</div>
				<div
					v-for="e in envList"
					:key="e.id"
					class="env-menu-item"
					:class="{ active: section === 'env' && curEnv?.id === e.id }"
					@click="selectEnv(e)"
				>
					<el-icon><Connection /></el-icon><span>{{ e.name }}</span>
				</div>
				<div class="env-menu-item env-add" @click="startNewEnv()">
					<el-icon><ele-Plus /></el-icon><span>新建环境</span>
				</div>

				<div class="env-group-title">数据库</div>
				<div class="env-menu-item" :class="{ active: section === 'db' }" @click="section = 'db'">
					<el-icon><Coin /></el-icon><span>数据库连接</span>
				</div>
			</div>

			<!-- 右栏：内容区 -->
			<div class="env-main">
				<!-- 全局变量 -->
				<template v-if="section === 'global-var'">
					<ApiVarPopover :service-id="serviceId" />
				</template>

				<!-- 全局参数 -->
				<template v-else-if="section === 'global-params'">
					<ApiCommonParamsDialog :service-id="serviceId" embedded ref="cpRef" />
				</template>

				<!-- 环境详情 -->
				<template v-else-if="section === 'env' && curEnv">
					<div class="env-detail">
						<div class="env-detail-head">
							<el-input
								v-model="curEnv.name"
								:placeholder="curEnv.id == null ? '新建环境' : '编辑环境'"
								class="env-name-input"
								size="large"
							/>
							<el-button v-if="curEnv.id != null" size="small" type="danger" plain class="env-del-btn" @click="deleteEnv(curEnv)">删除</el-button>
						</div>

						<div class="env-block-tip">子目录及接口默认继承所属模块的前置 URL，默认会使用此设置，一般情况下无需修改。</div>
<div class="env-block-title">前置 URL</div>
						<div v-for="(f, idx) in envFrontUrls" :key="'f' + idx" class="env-row">
							<span class="env-front-module">{{ moduleName(f.menu_id) }}</span>
							<el-popover placement="bottom" :width="150" trigger="click" popper-class="front-proto-popover">
								<template #reference>
									<el-button link size="small" class="env-front-more"><el-icon><MoreFilled /></el-icon></el-button>
								</template>
								<div class="proto-check-title">协议</div>
								<el-checkbox :model-value="moduleChecks(f.menu_id).http" :disabled="!!moduleChecks(f.menu_id).autoFlags.http" @change="(v: any) => toggleProto(f.menu_id, 'http', v)">Http</el-checkbox>
								<el-checkbox :model-value="moduleChecks(f.menu_id).websocket" :disabled="!!moduleChecks(f.menu_id).autoFlags.websocket" @change="(v: any) => toggleProto(f.menu_id, 'websocket', v)">WebSocket</el-checkbox>
								<el-checkbox :model-value="moduleChecks(f.menu_id).socketio" :disabled="!!moduleChecks(f.menu_id).autoFlags.socketio" @change="(v: any) => toggleProto(f.menu_id, 'socketio', v)">Socket.IO</el-checkbox>
							</el-popover>
							<span class="proto-mini" :class="'proto-mini-' + (f.protocol || 'http')">{{ protoLabel(f.protocol) }}</span>
							<el-input v-model="f.url" :placeholder="(f.protocol || 'http') === 'websocket' ? 'wss:// 起始的 WebSocket 前置 URL' : (f.protocol || 'http') === 'socketio' ? 'wss:// 起始的 Socket.IO 前置 URL' : 'https:// 起始的前置 URL'" size="small" style="flex:1" />
						</div>


						<div class="env-block-title">环境变量</div>
						<div v-for="(item, idx) in curEnv.variable" :key="'v' + idx" class="env-row">
							<el-input v-model="item.name" placeholder="变量名（如 token）" size="small" />
							<el-input v-model="item.value" placeholder="变量值" size="small" />
							<el-button type="danger" link size="small" @click="curEnv.variable.splice(idx, 1)" class="env-del-icon"><el-icon><Delete /></el-icon></el-button>
						</div>
						<div class="env-tip">环境变量：脚本 ntest.set 的变量会自动写入此处，可被 {{变量名}} 引用</div>

						<div class="env-detail-foot">
							<el-button type="primary" :loading="envSaving" @click="saveCurEnv">保存</el-button>
						</div>
					</div>
				</template>
				<div v-else-if="section === 'env'" class="env-empty">请选择左侧环境</div>

				<!-- 数据库 -->
				<template v-else-if="section === 'db'">
					<ApiDbPopover />
				</template>
			</div>
		</div>

	</el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { Delete, MoreFilled } from '@element-plus/icons-vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { api_env, save_env, add_env, del_env, api_tree } from '/@/api/v1/testing/apiAutomation';
import ApiVarPopover from './ApiVarPopover.vue';
import ApiCommonParamsDialog from './ApiCommonParamsDialog.vue';
import ApiDbPopover from './ApiDbPopover.vue';

const props = defineProps<{ serviceId?: number | string }>();

const visible = ref(false);
const section = ref<'global-var' | 'global-params' | 'env' | 'db'>('global-var');

// ---- 环境列表 ----
const envList = ref<any[]>([]);
const curEnv = ref<any>(null);
const envSaving = ref(false);
const cpRef = ref<any>(null);

const loadEnvList = async () => {
	try {
		const res: any = await api_env();
		const raw = res?.data;
		envList.value = Array.isArray(raw) ? raw : (Array.isArray(raw?.content) ? raw.content : []);
	} catch {
		envList.value = [];
	}
};

const selectEnv = (e: any) => {
	curEnv.value = {
		id: e.id,
		name: e.name || '',
		config: Array.isArray(e.config) ? e.config.map((c: any) => ({ ...c })) : [],
		variable: Array.isArray(e.variable) ? e.variable.map((v: any) => ({ ...v })) : [],
	};
	section.value = 'env';
	loadFrontUrls();
	loadMenuTree();
};

// ---- 模块级前置 URL（__front_urls__ 特殊配置项）----
const FRONT_KEY = '__front_urls__';
const frontUrlMenuOptions = ref<any[]>([]);
const loadMenuTree = async () => {
	try {
		const r: any = await api_tree({ search: { api_service_id: props.serviceId } });
		frontUrlMenuOptions.value = (r?.data || [])
			.map((n: any) => ({ id: n.id, name: n.name }));
	} catch {
		frontUrlMenuOptions.value = [];
	}
};
const envFrontUrls = ref<any[]>([]);
const loadFrontUrls = () => {
	const cfg = curEnv.value?.config || [];
	const item = cfg.find((c: any) => String(c.name || '').trim() === FRONT_KEY);
	try {
		const arr = item ? JSON.parse(item.value || '[]') : [];
		envFrontUrls.value = Array.isArray(arr) ? arr.map((x: any) => ({ ...x, protocol: x.protocol || 'http' })) : [];
	} catch {
		envFrontUrls.value = [];
	}
};

const syncFrontUrls = () => {
	const cfg = curEnv.value.config;
	const idx = cfg.findIndex((c: any) => String(c.name || '').trim() === FRONT_KEY);
	if (idx >= 0) cfg.splice(idx, 1);
	cfg.push({ name: FRONT_KEY, value: JSON.stringify(envFrontUrls.value) });
};
// ---- 前置 URL：模块「⋯」勾选协议，自动生成/删除对应协议输入框；auto 行禁用 ----
const moduleChecks = (menuId: any) => {
	const key = String(menuId || '');
	const rows = envFrontUrls.value.filter((r: any) => String(r.menu_id || '') === key);
	return {
		http: rows.some((r: any) => (r.protocol || 'http') === 'http'),
		websocket: rows.some((r: any) => r.protocol === 'websocket'),
		socketio: rows.some((r: any) => r.protocol === 'socketio'),
		autoFlags: {
			http: rows.some((r: any) => (r.protocol || 'http') === 'http' && !!r.auto),
			websocket: rows.some((r: any) => r.protocol === 'websocket' && !!r.auto),
			socketio: rows.some((r: any) => r.protocol === 'socketio' && !!r.auto),
		},
	};
};

const toggleProto = (menuId: any, proto: string, checked: any) => {
	const key = String(menuId || '');
	const has = envFrontUrls.value.some((r: any) => String(r.menu_id || '') === key && (r.protocol || 'http') === proto);
	if (checked && !has) {
		envFrontUrls.value.push({ menu_id: key, menu_name: '', url: '', protocol: proto });
	} else if (!checked && has) {
		const idx = envFrontUrls.value.findIndex((r: any) => String(r.menu_id || '') === key && (r.protocol || 'http') === proto);
		if (idx >= 0) envFrontUrls.value.splice(idx, 1);
	}
	syncFrontUrls();
};

const protoLabel = (p: any) => (p === 'websocket' ? 'WS' : p === 'socketio' ? 'Socket.IO' : 'HTTP');

const moduleName = (menuId: any): string => {
	const m = frontUrlMenuOptions.value.find((o: any) => String(o.id) === String(menuId));
	if (m) return m.name;
	const s = String(menuId ?? '');
	if (s.startsWith('svc_')) return '模块 ' + s.replace('svc_', '');
	return s;
};


// Apifox 交互：环境变量列表末尾始终保留一个空输入行，输入后自动另起一行
watch(
	() => curEnv.value?.variable,
	(list: any[] | undefined) => {
		if (Array.isArray(list)) {
			const last = list[list.length - 1];
			if (!last || String(last.name || '').trim()) {
				list.push({ name: '', value: '' });
			}
		}
	},
	{ deep: true, immediate: true }
);

const saveCurEnv = async () => {
	if (!curEnv.value) return;
	const envName = String(curEnv.value.name || '').trim();
	if (!envName) {
		ElMessage.warning('请输入环境名称');
		return;
	}
	envSaving.value = true;
	try {
		syncFrontUrls();
		const payload = {
			name: envName,
			config: curEnv.value.config.filter((c: any) => String(c.name || '').trim() === FRONT_KEY),
			variable: curEnv.value.variable.filter((v: any) => String(v.name || '').trim()),
		};
		if (curEnv.value.id == null) {
			await add_env(payload);
			ElMessage.success('新建成功');
			await loadEnvList();
			const created = envList.value.find((e: any) => e.name === envName);
			if (created) selectEnv(created);
		} else {
			await save_env({ env_list: [{ id: curEnv.value.id, ...payload }] });
			ElMessage.success('保存成功');
			await loadEnvList();
		}
	} catch (e: any) {
		ElMessage.error(e?.message || '保存失败');
	} finally {
		envSaving.value = false;
	}
};

// 新建环境：内联一页填写（名称 + 前置 URL + 环境变量），不再弹名称小窗
const startNewEnv = async () => {
	curEnv.value = { id: null as any, name: '', config: [], variable: [] };
	section.value = 'env';
	await loadMenuTree();
	envFrontUrls.value = frontUrlMenuOptions.value.map((m: any) => ({ menu_id: m.id, menu_name: m.name, url: '' }));
	syncFrontUrls();
};


const deleteEnv = async (e: any) => {
	try {
		await ElMessageBox.confirm(`确认删除环境「${e.name}」？`, '提示', { type: 'warning' });
		await del_env({ id: e.id });
		ElMessage.success('已删除');
		curEnv.value = null;
		section.value = 'env';
		await loadEnvList();
	} catch {}
};

// ---- 全局参数切换 ----
const switchParams = () => {
	section.value = 'global-params';
	setTimeout(() => cpRef.value?.open(), 0);
};

const open = async () => {
	visible.value = true;
	section.value = 'global-var';
	curEnv.value = null;
	await loadEnvList();
	loadFrontUrls();
};

const onClosed = () => {
	curEnv.value = null;
	section.value = 'global-var';
};

defineExpose({ open });
</script>

<style scoped>
.env-center {
	display: flex;
	height: 520px;
	border: 1px solid #e5e7eb;
	border-radius: 8px;
	overflow: hidden;
	background: #fff;
}
.env-side {
	width: 200px;
	flex-shrink: 0;
	border-right: 1px solid #e5e7eb;
	background: #fafbfc;
	padding: 10px 8px;
	overflow-y: auto;
}
.env-group-title {
	font-size: 12px;
	color: #9ca3af;
	padding: 8px 8px 4px;
	font-weight: 600;
}
.env-menu-item {
	display: flex;
	align-items: center;
	gap: 6px;
	padding: 7px 10px;
	border-radius: 6px;
	font-size: 13px;
	color: #374151;
	cursor: pointer;
	margin-bottom: 2px;
}
.env-menu-item:hover { background: #f0f1f3; }
.env-menu-item.active {
	background: #f3e8ff;
	color: #7c3aed;
	font-weight: 600;
}
.env-menu-item.env-add { color: #7c3aed; }
.env-main {
	flex: 1;
	padding: 14px 18px;
	overflow-y: auto;
	background: #fff;
}
.env-detail-head {
	display: flex;
	align-items: center;
	gap: 8px;
	margin-bottom: 14px;
}
.env-detail-title { font-size: 16px; font-weight: 700; margin-right: auto; }
.env-detail-head .env-del-btn { margin-left: auto; }
.env-front-module {
	flex: 1.2;
	min-width: 0;
	display: inline-flex;
	align-items: center;
	padding: 0 10px;
	height: 24px;
	font-size: 13px;
	font-weight: 500;
	color: #4c1d95;
	background: #f3e8ff;
	border-radius: 4px;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
.env-del-icon {
	padding: 4px 2px;
	font-size: 14px;
	color: #dc2626;
}
.env-name-input {
	width: 320px;
}
.env-name-input :deep(.el-input__wrapper) {
	box-shadow: none !important;
	background: transparent;
	padding: 0;
}
.env-name-input :deep(.el-input__inner) {
	font-size: 20px;
	font-weight: 600;
	color: #1f2937;
}
.env-name-input :deep(.el-input__inner::placeholder) {
	color: #6b7280;
}
.env-block-tip {
	font-size: 12px;
	color: #909399;
	line-height: 1.5;
	margin-bottom: 6px;
}
.env-block-title {
	font-size: 13px;
	font-weight: 600;
	color: #374151;
	margin: 14px 0 8px;
	border-left: 3px solid #7c3aed;
	padding-left: 8px;
}
.env-row {
	display: flex;
	gap: 8px;
	margin-bottom: 6px;
	align-items: center;
}
.env-row .el-input { flex: 1; }
.env-tip {
	font-size: 11px;
	color: #94a3b8;
	margin: 8px 0;
}
.env-detail-foot {
	text-align: right;
	margin-top: 16px;
	padding-top: 12px;
	border-top: 1px solid #f0f1f3;
}
.env-empty {
	display: flex;
	align-items: center;
	justify-content: center;
	height: 100%;
	color: #9ca3af;
	font-size: 13px;
}
.env-front-more { color: var(--el-text-color-secondary); }
.proto-mini {
	display: inline-flex;
	align-items: center;
	justify-content: center;
	font-size: 10px;
	line-height: 1;
	padding: 2px 5px;
	border-radius: 4px;
	color: #fff;
	flex: 0 0 auto;
}
.proto-mini-http { background: #409eff; }
.proto-mini-websocket { background: #7c4dff; }
.proto-mini-socketio { background: #e6a23c; }
.proto-check-title { font-weight: 600; margin-bottom: 6px; font-size: 13px; }
.front-proto-popover .el-checkbox { display: flex; margin-right: 0; margin-bottom: 6px; }
</style>
