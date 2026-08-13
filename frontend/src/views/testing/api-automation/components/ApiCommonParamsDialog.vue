<template>
	<el-dialog
		v-model="visible"
		title="全局参数"
		width="760px"
		destroy-on-close
		append-to-body
		@closed="onClosed"
	>
		<div class="common-params-tip">
			对本服务下所有接口生效。发送时自动合并；接口内同名参数优先生效。
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
						<el-tab-pane name="auth">
					<template #label><el-badge :show-zero="false" value="继承" :offset="[10, 2]" type="danger">Auth</el-badge></template>
					<div class="common-params-tip">父级鉴权：子级接口未单独配置鉴权时自动继承（接口配置了则用自己的）。</div>
					<el-form label-width="130px">
						<el-form-item label="认证类型：">
							<el-select v-model="form.auth.auth_type" style="width:280px">
								<el-option label="无认证" value="none" />
								<el-option label="Bearer Token" value="bearer" />
								<el-option label="JWT Bearer" value="jwt" />
								<el-option label="Basic Auth" value="basic" />
								<el-option label="API Key" value="apikey" />
							</el-select>
						</el-form-item>
						<template v-if="form.auth.auth_type === 'bearer'">
							<el-form-item label="Token：">
								<el-input v-model="form.auth.auth_token" placeholder="支持 {{变量}}，如 {{token}}" style="width:420px" />
							</el-form-item>
							<el-form-item label="前缀：">
								<el-input v-model="form.auth.auth_prefix" placeholder="默认 Bearer，可留空" style="width:200px" />
							</el-form-item>
						</template>
						<template v-if="form.auth.auth_type === 'jwt'">
							<el-form-item label="JWT Token：">
								<el-input v-model="form.auth.auth_token" type="textarea" :rows="3" placeholder="粘贴 JWT，支持 {{变量}}" style="width:480px" />
							</el-form-item>
							<el-form-item label="前缀：">
								<el-input v-model="form.auth.auth_prefix" placeholder="默认 Bearer" style="width:200px" />
							</el-form-item>
						</template>
						<template v-if="form.auth.auth_type === 'basic'">
							<el-form-item label="用户名：">
								<el-input v-model="form.auth.auth_username" placeholder="支持 {{变量}}" style="width:320px" />
							</el-form-item>
							<el-form-item label="密码：">
								<el-input v-model="form.auth.auth_password" type="password" show-password placeholder="支持 {{变量}}" style="width:320px" />
							</el-form-item>
						</template>
						<template v-if="form.auth.auth_type === 'apikey'">
							<el-form-item label="Key：">
								<el-input v-model="form.auth.auth_key" placeholder="如 X-API-KEY" style="width:320px" />
							</el-form-item>
							<el-form-item label="Value：">
								<el-input v-model="form.auth.auth_value" placeholder="支持 {{变量}}" style="width:320px" />
							</el-form-item>
							<el-form-item label="位置：">
								<el-radio-group v-model="form.auth.auth_in">
									<el-radio value="header">Header</el-radio>
									<el-radio value="query">Query</el-radio>
								</el-radio-group>
							</el-form-item>
						</template>
					</el-form>
				</el-tab-pane>
				<el-tab-pane name="before">
					<template #label><el-badge :show-zero="false" :value="form.before.length" :offset="[10, 2]" type="danger">前置操作</el-badge></template>
					<div class="common-params-tip">父级前置操作：子级接口自动继承执行（公共在前，接口自己的在后）。支持自定义脚本 / 等待时长 / 提取变量等。</div>
					<OperationPanel :items="form.before" mode="before" :env-list="[]" :tree-list="[]" :db-list="[]" :script-list="[]" :res-type-list="[]" :val-type-list="[]" />
				</el-tab-pane>
				<el-tab-pane name="after">
					<template #label><el-badge :show-zero="false" :value="form.after.length" :offset="[10, 2]" type="danger">后置操作</el-badge></template>
					<div class="common-params-tip">父级后置操作：子级接口自动继承执行（公共在前，接口自己的在后）。</div>
					<OperationPanel :items="form.after" mode="after" :env-list="[]" :tree-list="[]" :db-list="[]" :script-list="[]" :res-type-list="[]" :val-type-list="[]" />
				</el-tab-pane>
</el-tabs>
		<template #footer>
			<el-button @click="visible = false">取消</el-button>
			<el-button type="primary" :loading="saving" @click="save">保存</el-button>
		</template>
	</el-dialog>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { get_common_params, save_common_params } from '/@/api/v1/testing/apiAutomation';

import OperationPanel from './OperationPanel.vue';

const props = defineProps<{ serviceId: number }>();

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

const open = async () => {
	if (!props.serviceId) {
		ElMessage.warning('请先选择服务');
		return;
	}
	activeTab.value = 'header';
	visible.value = true;
	try {
		const res: any = await get_common_params({ api_service_id: props.serviceId });
		const data = res?.data || {};
		form.header = normalizeList(data.header);
		form.cookie = normalizeList(data.cookie || data.cookies, true);
		form.query = normalizeList(data.query || data.params);
		form.body = normalizeList(data.body);
		form.before = Array.isArray(data.before) ? JSON.parse(JSON.stringify(data.before)) : [];
		form.after = Array.isArray(data.after) ? JSON.parse(JSON.stringify(data.after)) : [];
		form.auth = (data.auth && typeof data.auth === 'object') ? JSON.parse(JSON.stringify(data.auth)) : { auth_type: 'none' };
		if (!form.auth.auth_type) form.auth.auth_type = 'none';
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
			common_params: {
				header: pack(form.header),
				cookie: pack(form.cookie, true),
				query: pack(form.query),
				body: pack(form.body),
				before: form.before,
				after: form.after,
				auth: form.auth,
			},
		});
		ElMessage.success('全局参数已保存');
		visible.value = false;
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
