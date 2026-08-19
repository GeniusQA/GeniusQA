<template>
	<div class="ds-history-panel">
		<div class="ds-history-toolbar">
			<el-button size="small" @click="reload">刷新</el-button>
		</div>

		<el-table
			v-loading="loading"
			:data="list"
			border
			stripe
			empty-text="暂无导入历史"
			style="width: 100%"
		>
			<el-table-column type="index" label="序号" width="60" align="center" />
			<el-table-column label="数据源" min-width="160" show-overflow-tooltip>
				<template #default="{ row }">
					<div class="ds-source-info">
						<span class="ds-source-type">{{ sourceTypeLabel(row.source_type) }}</span>
						<span class="ds-source-url">{{ row.source_url || '-' }}</span>
					</div>
				</template>
			</el-table-column>
			<el-table-column label="导入时间" width="170" align="center">
				<template #default="{ row }">{{ row.created_at }}</template>
			</el-table-column>
			<el-table-column label="导入统计" min-width="200" align="center">
				<template #default="{ row }">
					<div class="ds-stats">
						<el-tag size="small" type="success" effect="light">新增 {{ row.stats?.imported || 0 }}</el-tag>
						<el-tag size="small" type="warning" effect="light">修改 {{ row.stats?.updated || 0 }}</el-tag>
						<el-tag size="small" type="info" effect="light">未变 {{ row.stats?.unchanged || 0 }}</el-tag>
						<el-tag size="small" type="primary" effect="light">目录 {{ row.stats?.folders || 0 }}</el-tag>
					</div>
				</template>
			</el-table-column>
			<el-table-column label="操作" width="120" align="center" fixed="right">
				<template #default="{ row, $index }">
					<el-button
						type="primary"
						link
						size="small"
						:disabled="!canDiff($index)"
						@click.stop="openDiff(row, $index)"
					>
						与历史对比
					</el-button>
				</template>
			</el-table-column>
		</el-table>

		<div class="ds-history-pagination" v-show="total > 0">
			<el-pagination
				background
				v-model:current-page="currentPage"
				v-model:page-size="pageSize"
				:page-sizes="[10, 20, 50, 100]"
				layout="total, sizes, prev, pager, next, jumper"
				:total="total"
				@size-change="load"
				@current-change="load"
			/>
		</div>

		<DataSourceHistoryDiffDialog
			v-model="diffVisible"
			:history-a="diffHistoryA"
			:history-b="diffHistoryB"
			:history-list="list"
		/>
	</div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { useApiAutomationApi } from '/@/api/v1/testing/apiAutomation';
import DataSourceHistoryDiffDialog from './DataSourceHistoryDiffDialog.vue';

const props = defineProps<{ apiData?: any }>();

const loading = ref(false);
const list = ref<any[]>([]);
const total = ref(0);
const currentPage = ref(1);
const pageSize = ref(10);

const diffVisible = ref(false);
const diffHistoryA = ref<any>(null);
const diffHistoryB = ref<any>(null);

const api = useApiAutomationApi();

const serviceId = computed(() => {
	const d = props.apiData || {};
	const candidates = [d.api_service_id, d.service_id, d.api_info?.api_service_id, d.api_info?.service_id];
	for (const c of candidates) {
		const n = Number(c);
		if (Number.isFinite(n) && n > 0) return n;
	}
	return null;
});

const moduleId = computed(() => {
	const d = props.apiData || {};
	const candidates = [d.module_id, d.api_info?.module_id];
	for (const c of candidates) {
		const n = Number(c);
		if (Number.isFinite(n) && n > 0) return n;
	}
	return null;
});

const sourceTypeLabel = (t?: string) => {
	const map: Record<string, string> = { swagger: 'OpenAPI/Swagger', apifox: 'Apifox' };
	return map[t || ''] || (t || '未知');
};

const parseResult = (raw: any) => {
	const data = raw?.data ?? raw ?? {};
	const rows = Array.isArray(data?.rows) ? data.rows : (Array.isArray(data) ? data : []);
	const t = Number(data?.rowTotal ?? rows.length) || 0;
	return { rows, total: t };
};

const load = async () => {
	if (!serviceId.value) {
		list.value = [];
		total.value = 0;
		return;
	}
	loading.value = true;
	try {
		const payload: Record<string, any> = {
			api_service_id: serviceId.value,
			page: currentPage.value,
			pageSize: pageSize.value,
		};
		if (moduleId.value) payload.module_id = moduleId.value;
		const r: any = await api.dataSourceHistory(payload);
		const parsed = parseResult(r);
		list.value = parsed.rows;
		total.value = parsed.total;
	} catch (e: any) {
		ElMessage.error(e?.message || '加载导入历史失败');
		list.value = [];
		total.value = 0;
	} finally {
		loading.value = false;
	}
};

const reload = () => {
	currentPage.value = 1;
	load();
};

const canDiff = (index: number) => index < list.value.length - 1;

const openDiff = (row: any, index: number) => {
	if (!canDiff(index)) return;
	diffHistoryA.value = list.value[index + 1];
	diffHistoryB.value = row;
	diffVisible.value = true;
};

watch(
	() => [serviceId.value, moduleId.value],
	() => {
		currentPage.value = 1;
		load();
	},
	{ immediate: true }
);
</script>

<style scoped>
.ds-history-panel {
	padding: 12px;
	height: 100%;
	display: flex;
	flex-direction: column;
}
.ds-history-toolbar {
	display: flex;
	justify-content: flex-end;
	margin-bottom: 10px;
}
.ds-source-info {
	display: flex;
	flex-direction: column;
	gap: 4px;
}
.ds-source-type {
	font-size: 13px;
	font-weight: 600;
	color: var(--el-text-color-primary);
}
.ds-source-url {
	font-size: 12px;
	color: var(--el-text-color-secondary);
}
.ds-stats {
	display: flex;
	justify-content: center;
	gap: 6px;
	flex-wrap: wrap;
}
.ds-history-pagination {
	margin-top: 10px;
	display: flex;
	justify-content: flex-end;
}
</style>
