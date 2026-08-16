<template>
	<el-dialog v-model="inner" title="绑定数据源" width="480px" append-to-body class="sync-result-dialog">
		<div class="sync-ok">
			<el-icon class="sync-check"><CircleCheckFilled /></el-icon>
			<span class="sync-title">同步数据成功</span>
		</div>
		<table class="sync-table">
			<thead>
				<tr>
					<th>类型</th>
					<th>新增</th>
					<th>修改</th>
				</tr>
			</thead>
			<tbody>
				<tr v-for="row in rows" :key="row.name">
					<td>{{ row.name }}</td>
					<td>{{ row.added || 0 }}</td>
					<td>{{ row.updated || 0 }}</td>
				</tr>
			</tbody>
		</table>
		<template #footer>
			<el-button type="primary" @click="inner = false">知道了</el-button>
		</template>
	</el-dialog>
</template>

<script lang="ts" setup>
import { computed, ref, watch } from 'vue';
import { CircleCheckFilled } from '@element-plus/icons-vue';

const props = defineProps<{
	modelValue: boolean;
	result?: Record<string, any> | null;
}>();

const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>();

const inner = computed({
	get: () => props.modelValue,
	set: (v: boolean) => emit('update:modelValue', v),
});

const rows = computed(() => {
	const r = props.result || {};
	const num = (v: any) => Number(v || 0);
	return [
		{ name: '接口/文档', added: num(r.imported), updated: num(r.updated) },
		{ name: '目录', added: num(r.folders), updated: 0 },
		{ name: '数据模型', added: num(r.models), updated: 0 },
		{ name: '环境', added: 0, updated: 0 },
		{ name: '场景用例', added: 0, updated: 0 },
		{ name: '测试套件', added: 0, updated: 0 },
		{ name: '快捷请求', added: 0, updated: 0 },
		{ name: '响应组件', added: 0, updated: 0 },
		{ name: '鉴权组件', added: 0, updated: 0 },
		{ name: '其他组件', added: 0, updated: 0 },
		{ name: '测试数据', added: 0, updated: 0 },
	];
});
</script>

<style scoped>
.sync-ok {
	display: flex;
	align-items: center;
	gap: 8px;
	margin-bottom: 14px;
}
.sync-check {
	font-size: 22px;
	color: #10b981;
}
.sync-title {
	font-size: 16px;
	font-weight: 600;
	color: var(--el-text-color-primary);
}
.sync-table {
	width: 100%;
	border-collapse: collapse;
	font-size: 13px;
}
.sync-table th {
	background: #f5f7fa;
	color: var(--el-text-color-secondary);
	font-weight: 500;
	text-align: left;
	padding: 8px 12px;
	border-bottom: 1px solid var(--el-border-color-lighter);
}
.sync-table td {
	padding: 8px 12px;
	border-bottom: 1px solid var(--el-border-color-extra-light);
	color: var(--el-text-color-primary);
}
.sync-table td:nth-child(2),
.sync-table td:nth-child(3) {
	text-align: right;
	font-variant-numeric: tabular-nums;
}
</style>
