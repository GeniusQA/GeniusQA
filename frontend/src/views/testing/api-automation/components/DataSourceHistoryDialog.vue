<template>
	<el-dialog v-model="inner" title="数据源导入历史" width="720px" append-to-body destroy-on-close class="ds-history-dialog">
		<div v-if="loading" class="dsh-loading"><el-icon class="is-loading"><Loading /></el-icon> 加载中...</div>
		<div v-else-if="!groupedHistory.length" class="dsh-empty">暂无导入历史</div>
		<div v-else class="dsh-list">
			<div v-for="group in groupedHistory" :key="group.date" class="dsh-group">
				<div class="dsh-date">{{ group.date }}</div>
				<div v-for="(item, idx) in group.items" :key="item.id" class="dsh-item">
					<div class="dsh-item-left">
						<div class="dsh-time">{{ item.created_at?.split(' ')[1] || '-' }}</div>
						<div class="dsh-user">{{ item.created_by ? `用户 ${item.created_by}` : '系统' }}</div>
					</div>
					<div class="dsh-item-center">
						<el-tag size="small" type="info">{{ sourceTypeLabel(item.source_type) }}</el-tag>
						<span class="dsh-stats">
							<span class="dsh-stat add">+{{ item.stats?.imported || 0 }}</span>
							<span class="dsh-stat update">~{{ item.stats?.updated || 0 }}</span>
							<span class="dsh-stat unchanged">={{ item.stats?.unchanged || 0 }}</span>
							<span class="dsh-stat folder">目录 {{ item.stats?.folders || 0 }}</span>
						</span>
					</div>
					<div class="dsh-item-right">
						<el-button
							v-if="group.indexBase + idx > 0"
							link
							type="primary"
							size="small"
							@click="openDiff(item, group.indexBase + idx)"
						>
							与历史对比
						</el-button>
						<el-button link type="danger" size="small" @click="doDelete(item)">删除</el-button>
					</div>
				</div>
			</div>
		</div>

		<DataSourceHistoryDiffDialog
			v-model="diffVisible"
			:history-a="diffHistoryA"
			:history-b="diffHistoryB"
			:history-list="historyList"
		/>
	</el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { Loading } from '@element-plus/icons-vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useApiAutomationApi } from '/@/api/v1/testing/apiAutomation';
import DataSourceHistoryDiffDialog from './DataSourceHistoryDiffDialog.vue';

const props = defineProps<{
	modelValue: boolean;
	serviceId: number;
	moduleId?: number;
}>();

const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>();

const inner = computed({
	get: () => props.modelValue,
	set: (v: boolean) => emit('update:modelValue', v),
});

const loading = ref(false);
const historyList = ref<any[]>([]);
const diffVisible = ref(false);
const diffHistoryA = ref<any>(null);
const diffHistoryB = ref<any>(null);

const groupedHistory = computed(() => {
	const groups: Record<string, any[]> = {};
	let indexBase = 0;
	for (const item of historyList.value) {
		const date = String(item.created_at || '').split(' ')[0] || '未知日期';
		if (!groups[date]) groups[date] = [];
		groups[date].push(item);
	}
	return Object.keys(groups)
		.sort((a, b) => (a < b ? 1 : -1))
		.map((date) => {
			const items = groups[date];
			const res = { date, items, indexBase };
			indexBase += items.length;
			return res;
		});
});

const sourceTypeLabel = (t: string) =>
	t === 'apifox' ? 'Apifox' : t === 'postman' ? 'Postman' : t === 'curl' ? 'cURL' : 'OpenAPI/Swagger';

const loadHistory = async () => {
	if (!props.serviceId) return;
	loading.value = true;
	try {
		const r: any = await useApiAutomationApi().dataSourceHistory({
			api_service_id: props.serviceId,
			module_id: props.moduleId || undefined,
			page: 1,
			pageSize: 100,
		});
		if (r?.code === 200) {
			historyList.value = r.data?.rows || [];
		}
	} catch (e: any) {
		ElMessage.error(e?.message || '加载历史失败');
	} finally {
		loading.value = false;
	}
};

const openDiff = (item: any, currentIndex: number) => {
	if (currentIndex <= 0 || !historyList.value[currentIndex - 1]) return;
	diffHistoryA.value = historyList.value[currentIndex - 1];
	diffHistoryB.value = item;
	diffVisible.value = true;
};

const doDelete = async (item: any) => {
	try {
		await ElMessageBox.confirm('删除后无法恢复，是否继续？', '提示', { type: 'warning' });
		const r: any = await useApiAutomationApi().dataSourceHistoryDelete({ id: item.id });
		if (r?.code === 200) {
			ElMessage.success('删除成功');
			loadHistory();
		} else {
			ElMessage.error(r?.message || '删除失败');
		}
	} catch {
		// cancel
	}
};

watch(
	() => props.modelValue,
	(v) => {
		if (v) loadHistory();
	},
	{ immediate: true }
);
</script>

<style scoped>
.dsh-loading {
	text-align: center;
	padding: 40px 0;
	color: var(--el-text-color-secondary);
	font-size: 14px;
}
.dsh-empty {
	text-align: center;
	padding: 50px 0;
	color: var(--el-text-color-secondary);
	font-size: 14px;
}
.dsh-group {
	margin-bottom: 18px;
}
.dsh-date {
	font-size: 13px;
	font-weight: 600;
	color: var(--el-text-color-primary);
	margin-bottom: 8px;
	padding-left: 8px;
}
.dsh-item {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 12px;
	padding: 12px 14px;
	border-radius: 8px;
	background: var(--el-fill-color-light);
	margin-bottom: 8px;
}
.dsh-item-left {
	display: flex;
	flex-direction: column;
	gap: 4px;
	min-width: 90px;
}
.dsh-time {
	font-size: 14px;
	font-weight: 600;
	color: var(--el-text-color-primary);
}
.dsh-user {
	font-size: 12px;
	color: var(--el-text-color-secondary);
}
.dsh-item-center {
	flex: 1;
	display: flex;
	align-items: center;
	gap: 12px;
	flex-wrap: wrap;
}
.dsh-stats {
	display: flex;
	align-items: center;
	gap: 10px;
	font-size: 13px;
}
.dsh-stat {
	white-space: nowrap;
}
.dsh-stat.add { color: #10b981; }
.dsh-stat.update { color: #f59e0b; }
.dsh-stat.unchanged { color: var(--el-text-color-secondary); }
.dsh-stat.folder { color: var(--el-text-color-regular); }
.dsh-item-right {
	display: flex;
	align-items: center;
	gap: 4px;
}
</style>
