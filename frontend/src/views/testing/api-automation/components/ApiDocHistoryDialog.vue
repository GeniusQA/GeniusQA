<template>
	<el-dialog v-model="inner" title="接口文档历史记录" width="720px" append-to-body destroy-on-close>
		<div class="adh-list">
			<el-timeline v-if="list.length">
				<el-timeline-item
					v-for="(item, index) in list"
					:key="item.id"
					:icon="timelineIcon(item.operation_type)"
					:type="timelineType(item.operation_type)"
					:timestamp="item.created_at"
				>
					<div class="adh-item">
						<div class="adh-item-info">
							<span class="adh-item-name">{{ item.created_by_name || '未知用户' }}</span>
							<el-tag size="small" :type="timelineType(item.operation_type)" effect="light">
								{{ item.operation_label }}
							</el-tag>
							<span v-if="item.name" class="adh-item-title">{{ item.name }}</span>
						</div>
						<div class="adh-item-actions">
							<el-button
								v-if="index < list.length - 1"
								type="primary"
								link
								size="small"
								@click="openDiff(item, index)"
							>
								与历史对比
							</el-button>
							<el-popconfirm title="确定还原到该版本吗？" confirm-button-text="确定" cancel-button-text="取消" @confirm="restore(item)">
								<template #reference>
									<el-button type="primary" link size="small">还原此版本</el-button>
								</template>
							</el-popconfirm>
						</div>
					</div>
				</el-timeline-item>
			</el-timeline>
			<el-empty v-else description="暂无文档历史记录" />
		</div>

		<div class="adh-pagination" v-show="total > 0">
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

		<ApiDocHistoryDiffDialog
			v-model="diffVisible"
			:history-a="diffHistoryA"
			:history-b="diffHistoryB"
			:history-list="list"
		/>
	</el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { Edit, Plus, RefreshRight } from '@element-plus/icons-vue';
import { useApiAutomationApi } from '/@/api/v1/testing/apiAutomation';
import ApiDocHistoryDiffDialog from './ApiDocHistoryDiffDialog.vue';

const props = defineProps<{
	modelValue: boolean;
	apiId?: number | null;
	apiData?: any;
}>();
const emit = defineEmits<{
	(e: 'update:modelValue', v: boolean): void;
	(e: 'restore', document: Record<string, any>): void;
}>();

const inner = computed({
	get: () => props.modelValue,
	set: (v: boolean) => emit('update:modelValue', v),
});

const api = useApiAutomationApi();
const loading = ref(false);
const list = ref<any[]>([]);
const total = ref(0);
const currentPage = ref(1);
const pageSize = ref(20);

const diffVisible = ref(false);
const diffHistoryA = ref<any>(null);
const diffHistoryB = ref<any>(null);

const timelineType = (t?: string) => {
	const map: Record<string, any> = { create: 'success', edit: 'primary', restore: 'warning' };
	return map[t || ''] || 'info';
};
const timelineIcon = (t?: string) => {
	const map: Record<string, any> = { create: Plus, edit: Edit, restore: RefreshRight };
	return map[t || ''] || Edit;
};

const parseResult = (raw: any) => {
	const data = raw?.data ?? raw ?? {};
	const rows = Array.isArray(data?.rows) ? data.rows : (Array.isArray(data) ? data : []);
	return { rows, total: Number(data?.rowTotal ?? rows.length) || 0 };
};

const load = async () => {
	if (!props.apiId) {
		list.value = [];
		total.value = 0;
		return;
	}
	loading.value = true;
	try {
		const r: any = await api.apiDocHistory({
			api_id: props.apiId,
			page: currentPage.value,
			pageSize: pageSize.value,
		});
		const parsed = parseResult(r);
		list.value = parsed.rows;
		total.value = parsed.total;
	} catch (e: any) {
		ElMessage.error(e?.message || '加载历史记录失败');
		list.value = [];
		total.value = 0;
	} finally {
		loading.value = false;
	}
};

const openDiff = (row: any, index: number) => {
	if (index >= list.value.length - 1) return;
	diffHistoryA.value = list.value[index + 1];
	diffHistoryB.value = row;
	diffVisible.value = true;
};

const restore = async (item: any) => {
	try {
		const r: any = await api.apiDocHistoryRestore({ id: item.id });
		if (r?.code === 200) {
			ElMessage.success('还原成功');
			emit('restore', item.document || {});
			load();
			inner.value = false;
		} else {
			ElMessage.error(r?.message || '还原失败');
		}
	} catch (e: any) {
		ElMessage.error(e?.message || '还原失败');
	}
};

watch(
	() => [props.modelValue, props.apiId],
	() => {
		if (props.modelValue && props.apiId) {
			currentPage.value = 1;
			load();
		}
	},
	{ immediate: true }
);
</script>

<style scoped>
.adh-list {
	max-height: 520px;
	overflow-y: auto;
	padding: 8px 4px;
}
.adh-item {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 12px;
	padding: 6px 10px;
	background: var(--el-fill-color-light);
	border-radius: 6px;
}
.adh-item-info {
	display: flex;
	align-items: center;
	gap: 10px;
	flex: 1;
	min-width: 0;
}
.adh-item-name {
	font-weight: 600;
	color: var(--el-text-color-primary);
}
.adh-item-title {
	color: var(--el-text-color-secondary);
	font-size: 13px;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
	max-width: 220px;
}
.adh-item-actions {
	flex-shrink: 0;
}
.adh-pagination {
	margin-top: 14px;
	display: flex;
	justify-content: flex-end;
}
</style>
