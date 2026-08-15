<template>
	<el-dialog
		v-model="visible"
		:title="embedded ? '' : dialogTitle"
		:width="embedded ? '100%' : '760px'"
		destroy-on-close
		:append-to-body="!embedded"
		:modal="!embedded"
		:show-close="!embedded"
		:class="embedded ? 'cp-embedded-dialog' : ''"
		:style="embedded ? 'position:relative' : ''"
		@closed="onClosed"
	>
		<div class="common-params-tip">{{ curMenuId ? "目录参数：对当前目录（根目录/子目录）及其下所有接口生效，可配置 Auth、前置操作、后置操作" : "模块级全局参数：对本模块所有接口生效（Header/Cookie/Query/Body）" }}</div>
					<div class="common-params-tip">
			对本模块下所有接口生效。发送时自动合并；接口内同名参数优先生效。
		</div>
		<el-tabs v-model="activeTab">
			<el-tab-pane name="header">
				<template #label>
					<el-badge :show-zero="false" :value="countEnabled(form.header)" :offset="[10, 2]" type="danger">Header</el-badge>
				</template>
				<div class="kv-list">
					<div v-for="(row, i) in form.header" :key="'h'+i" class="kv-row">
						<el-checkbox v-model="row.status" />
						<el-input v-model="row.key" placeholder="Header 名" size="small" />
						<el-input v-model="row.value" placeholder="Header 值" size="small" />
						<el-button type="danger" link size="small" @click="form.header.splice(i, 1)">删除</el-button>
					</div>
					<el-button type="primary" link size="small" @click="form.header.push(emptyKv())">+ 添加 Header</el-button>
				</div>
			</el-tab-pane>
			<el-tab-pane name="cookie">
				<template #label>
					<el-badge :show-zero="false" :value="countEnabled(form.cookie)" :offset="[10, 2]" type="danger">Cookie</el-badge>
				</template>
				<div class="kv-list">
					<div v-for="(row, i) in form.cookie" :key="'c'+i" class="kv-row">
						<el-checkbox v-model="row.status" />
						<el-input v-model="row.key" placeholder="Cookie 名" size="small" style="flex:1.2" />
						<el-input v-model="row.value" placeholder="Cookie 值" size="small" style="flex:1.4" />
						<el-input v-model="row.domain" placeholder="Domain（可选）" size="small" style="flex:1" />
						<el-button type="danger" link size="small" @click="form.cookie.splice(i, 1)">删除</el-button>
					</div>
					<el-button type="primary" link size="small" @click="form.cookie.push(emptyCookie())">+ 添加 Cookie</el-button>
				</div>
			</el-tab-pane>
			<el-tab-pane name="query">
				<template #label>
					<el-badge :show-zero="false" :value="countEnabled(form.query)" :offset="[10, 2]" type="danger">Query</el-badge>
				</template>
				<div class="kv-list">
					<div v-for="(row, i) in form.query" :key="'q'+i" class="kv-row">
						<el-checkbox v-model="row.status" />
						<el-input v-model="row.key" placeholder="参数名" size="small" />
						<el-input v-model="row.value" placeholder="参数值" size="small" />
						<el-button type="danger" link size="small" @click="form.query.splice(i, 1)">删除</el-button>
					</div>
					<el-button type="primary" link size="small" @click="form.query.push(emptyKv())">+ 添加 Query</el-button>
				</div>
			</el-tab-pane>
			<el-tab-pane name="body">
				<template #label>
					<el-badge :show-zero="false" :value="countEnabled(form.body)" :offset="[10, 2]" type="danger">Body</el-badge>
				</template>
				<div class="common-params-tip" style="margin-bottom:8px">
					以键值形式合并到 JSON / form-data / x-www-form-urlencoded（接口同名键覆盖）。
				</div>
				<div class="kv-list">
					<div v-for="(row, i) in form.body" :key="'b'+i" class="kv-row">
						<el-checkbox v-model="row.status" />
						<el-input v-model="row.key" placeholder="字段名" size="small" />
						<el-input v-model="row.value" placeholder="字段值" size="small" />
						<el-button type="danger" link size="small" @click="form.body.splice(i, 1)">删除</el-button>
					</div>
					<el-button type="primary" link size="small" @click="form.body.push(emptyKv())">+ 添加 Body 字段</el-button>
				</div>
			</el-tab-pane>
						</el-tabs>
		<template #footer>
			<el-button v-if="!embedded" @click="visible = false">取消</el-button>
			<el-button type="primary" :loading="saving" @click="save">保存</el-button>
		</template>
	</el-dialog>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { get_common_params, save_common_params } from '/@/api/v1/testing/apiAutomation';

import OperationPanel from './OperationPanel.vue';

const props = defineProps<{
	serviceId: number | string;
	menuId?: number | string;
	embedded?: boolean;
}>();
const dialogTitle = ref(props.menuId ? '目录参数' : '全局参数');

const visible = ref(false);
const saving = ref(false);
const activeTab = ref('header');

type KvRow = { key: string; value: string; status: boolean; domain?: string };

const form = reactive<{
	header: KvRow[];
	cookie: KvRow[];
	query: KvRow[];
	body: KvRow[];
	before: any[];
	after: any[];
	auth: any;
}>({
	header: [],
	cookie: [],
	query: [],
	body: [],
	before: [],
	after: [],
	auth: { auth_type: 'none' },
});

const emptyKv = (): KvRow => ({ key: '', value: '', status: true });
const emptyCookie = (): KvRow => ({ key: '', value: '', status: true, domain: '' });

const countEnabled = (list: KvRow[]) => list.filter((x) => x.status !== false && String(x.key || '').trim()).length;

const normalizeList = (list: any[], cookie = false): KvRow[] => {
	if (!Array.isArray(list)) return [];
	return list
		.filter((x) => x && typeof x === 'object')
		.map((x) => {
			const key = String(x.key || x.name || '').trim();
			const row: KvRow = {
				key,
				value: x.value == null ? '' : String(x.value),
				status: x.status === false ? false : true,
			};
			if (cookie) row.domain = x.domain == null ? '' : String(x.domain);
			return row;
		})
		.filter((x) => x.key);
};

const curMenuId = ref<number | null>(null)
const open = async (menuId?: number | string) => {
	curMenuId.value = menuId ? Number(menuId) : (props.menuId ? Number(props.menuId) : null)
	dialogTitle.value = curMenuId.value ? '目录参数' : '全局参数'
	if (!props.serviceId) {
		ElMessage.warning('请先选择服务');
		return;
	}
	activeTab.value = 'header';
	visible.value = true;
	try {
		const res: any = await get_common_params({ api_service_id: props.serviceId, menu_id: curMenuId.value || undefined });
		const data = res?.data || {};
		form.header = normalizeList(data.header);
		form.cookie = normalizeList(data.cookie || data.cookies, true);
		form.query = normalizeList(data.query || data.params);
		form.body = normalizeList(data.body);
		if (!form.header.length) form.header.push(emptyKv());
		if (!form.cookie.length) form.cookie.push(emptyCookie());
		if (!form.query.length) form.query.push(emptyKv());
		if (!form.body.length) form.body.push(emptyKv());
	} catch (e: any) {
		ElMessage.error(e?.message || '加载全局参数失败');
	}
};

const save = async () => {
	saving.value = true;
	try {
		const pack = (list: KvRow[], cookie = false) =>
			list
				.filter((x) => String(x.key || '').trim())
				.map((x) => {
					const row: any = {
						key: String(x.key).trim(),
						value: x.value ?? '',
						status: x.status !== false,
					};
					if (cookie) row.domain = x.domain || '';
					return row;
				});
		await save_common_params({
			api_service_id: props.serviceId,
			menu_id: curMenuId.value || undefined,
			common_params: {
				header: pack(form.header),
				cookie: pack(form.cookie, true),
				query: pack(form.query),
				body: pack(form.body),
				before: [],
				after: [],
				auth: { auth_type: 'none' },
			},
		});
		ElMessage.success('全局参数已保存');
		if (!props.embedded) visible.value = false;
	} catch (e: any) {
		ElMessage.error(e?.message || '保存失败');
	} finally {
		saving.value = false;
	}
};

const onClosed = () => {
	form.header = [];
	form.cookie = [];
	form.query = [];
	form.body = [];
	form.before = [];
	form.after = [];
	form.auth = { auth_type: 'none' };
};

defineExpose({ open });
</script>

<style scoped>
.cp-embedded-dialog {
	box-shadow: none !important;
	border: none !important;
	border-radius: 0 !important;
	background: transparent !important;
}
.cp-embedded-dialog :deep(.el-dialog__header) {
	display: none;
}
.cp-embedded-dialog :deep(.el-dialog__body) {
	padding: 0;
	overflow: visible;
}
.cp-embedded-dialog :deep(.el-dialog__footer) {
	padding: 12px 0 0;
}
.common-params-tip {
	font-size: 12px;
	color: var(--el-text-color-secondary);
	margin-bottom: 10px;
	line-height: 1.5;
}
.kv-list {
	min-height: 220px;
	max-height: 360px;
	overflow: auto;
	padding-right: 4px;
}
.kv-row {
	display: flex;
	align-items: center;
	gap: 6px;
	margin-bottom: 6px;
}
.kv-row .el-input {
	flex: 1;
}
</style>
