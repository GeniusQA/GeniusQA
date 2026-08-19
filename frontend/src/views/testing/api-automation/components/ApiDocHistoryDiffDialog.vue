<template>
	<el-dialog v-model="inner" title="差异对比" width="900px" append-to-body destroy-on-close class="doc-diff-dialog">
		<div v-if="loading" class="docd-loading"><el-icon class="is-loading"><Loading /></el-icon> 加载中...</div>
		<template v-else-if="diffData">
			<div class="docd-head">
				<div class="docd-version old">
					<el-tag type="danger">前一个版本</el-tag>
					<el-select
						v-model="selectedLeftId"
						:teleported="false"
						popper-class="docd-select-popper"
						size="small"
						class="docd-select"
						@change="onLeftChange"
					>
						<el-option
							v-for="item in leftOptions"
							:key="item.id"
							:label="formatOptionLabel(item)"
							:value="item.id"
						/>
					</el-select>
					<el-button
						v-if="selectedLeft"
						type="primary"
						link
						size="small"
						@click="restoreVersion(selectedLeft)"
					>
						还原此版本
					</el-button>
				</div>
				<div class="docd-arrow">→</div>
				<div class="docd-version new">
					<el-tag type="success">该版本</el-tag>
					<el-select
						v-model="selectedRightId"
						:teleported="false"
						popper-class="docd-select-popper"
						size="small"
						class="docd-select"
						@change="onRightChange"
					>
						<el-option
							v-for="item in rightOptions"
							:key="item.id"
							:label="formatOptionLabel(item)"
							:value="item.id"
						/>
					</el-select>
					<el-button
						v-if="selectedRight"
						type="primary"
						link
						size="small"
						@click="restoreVersion(selectedRight)"
					>
						还原此版本
					</el-button>
				</div>
			</div>

			<div class="docd-summary">
				<span class="docd-sum-item add">新增 {{ diffData.summary?.add || 0 }}</span>
				<span class="docd-sum-item del">删除 {{ diffData.summary?.delete || 0 }}</span>
				<span class="docd-sum-item mod">修改 {{ diffData.summary?.edit || 0 }}</span>
			</div>

			<el-collapse v-model="activeNames">
				<el-collapse-item v-if="diffData.changes?.length" name="changes" title="内容">
					<div v-for="(change, idx) in diffData.changes" :key="idx" class="docd-change-row">
						<div class="docd-change-key">{{ change.key }}</div>
						<div class="docd-change-body">
							<div v-for="(item, iidx) in change.items || []" :key="iidx" class="docd-change-item">
								<el-tag v-if="item.type === 'add'" size="small" type="success">新增</el-tag>
								<el-tag v-else-if="item.type === 'delete'" size="small" type="danger">删除</el-tag>
								<el-tag v-else size="small" type="warning">修改</el-tag>
								<div class="docd-value">
									<pre v-if="item.old !== undefined" class="docd-old">{{ formatValue(item.old) }}</pre>
									<pre v-if="item.new !== undefined" class="docd-new">{{ formatValue(item.new) }}</pre>
								</div>
							</div>
						</div>
					</div>
				</el-collapse-item>
			</el-collapse>
		</template>
	</el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { Loading } from '@element-plus/icons-vue';
import { ElMessage } from 'element-plus';
import { useApiAutomationApi } from '/@/api/v1/testing/apiAutomation';

const props = defineProps<{
	modelValue: boolean;
	historyA?: Record<string, any> | null;
	historyB?: Record<string, any> | null;
	historyList?: Record<string, any>[];
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
const diffData = ref<any>(null);
const activeNames = ref(['changes']);

const selectedLeftId = ref<number | null>(null);
const selectedRightId = ref<number | null>(null);

const allHistory = computed(() => props.historyList || []);
const leftIndex = computed(() => allHistory.value.findIndex((h) => h.id === selectedLeftId.value));
const rightIndex = computed(() => allHistory.value.findIndex((h) => h.id === selectedRightId.value));

const leftOptions = computed(() => {
	const ri = rightIndex.value;
	if (ri < 0) return allHistory.value.slice(1);
	return allHistory.value.filter((_, idx) => idx > ri);
});
const rightOptions = computed(() => {
	const li = leftIndex.value;
	if (li < 0) return allHistory.value.slice(0, -1);
	return allHistory.value.filter((_, idx) => idx < li);
});
const selectedLeft = computed(() => allHistory.value.find((h) => h.id === selectedLeftId.value));
const selectedRight = computed(() => allHistory.value.find((h) => h.id === selectedRightId.value));

const formatOptionLabel = (item: any) => {
	const name = item.created_by_name || '未知用户';
	return `${name} ${item.operation_label || ''} ${item.created_at || ''}`;
};
const formatValue = (v: any) => {
	if (v === null || v === undefined) return '';
	if (typeof v === 'object') return JSON.stringify(v, null, 2);
	return String(v);
};

const loadDiff = async () => {
	if (!selectedLeftId.value || !selectedRightId.value) return;
	loading.value = true;
	try {
		const r: any = await api.apiDocHistoryDiff({
			history_id_a: selectedLeftId.value,
			history_id_b: selectedRightId.value,
		});
		if (r?.code === 200) {
			diffData.value = r.data || null;
		} else {
			ElMessage.error(r?.message || '对比失败');
		}
	} catch (e: any) {
		ElMessage.error(e?.message || '对比失败');
	} finally {
		loading.value = false;
	}
};

const onLeftChange = (val: number) => {
	selectedLeftId.value = val;
	const opts = rightOptions.value;
	if (!opts.find((h) => h.id === selectedRightId.value)) {
		selectedRightId.value = opts[0]?.id || null;
	}
	loadDiff();
};
const onRightChange = (val: number) => {
	selectedRightId.value = val;
	const opts = leftOptions.value;
	if (!opts.find((h) => h.id === selectedLeftId.value)) {
		selectedLeftId.value = opts[opts.length - 1]?.id || null;
	}
	loadDiff();
};

const restoreVersion = async (item: any) => {
	try {
		const r: any = await api.apiDocHistoryRestore({ id: item.id });
		if (r?.code === 200) {
			ElMessage.success('还原成功');
			emit('restore', item.document || {});
			inner.value = false;
		} else {
			ElMessage.error(r?.message || '还原失败');
		}
	} catch (e: any) {
		ElMessage.error(e?.message || '还原失败');
	}
};

const resetSelection = () => {
	const a = props.historyA;
	const b = props.historyB;
	const list = allHistory.value;
	selectedRightId.value = b?.id ?? list[0]?.id ?? null;
	selectedLeftId.value = a?.id ?? null;
	const ri = list.findIndex((h) => h.id === selectedRightId.value);
	const li = list.findIndex((h) => h.id === selectedLeftId.value);
	if (li >= 0 && ri >= 0 && li <= ri) {
		selectedLeftId.value = list[ri + 1]?.id ?? null;
	}
	if (selectedLeftId.value == null) {
		selectedLeftId.value = list[ri + 1]?.id ?? list[list.length - 1]?.id ?? null;
	}
};

watch(
	() => [props.modelValue, props.historyA?.id, props.historyB?.id],
	() => {
		if (props.modelValue && props.historyA?.id && props.historyB?.id) {
			diffData.value = null;
			resetSelection();
			loadDiff();
		}
	},
	{ immediate: true }
);
</script>

<style scoped>
.docd-loading {
	text-align: center;
	padding: 60px 0;
	color: var(--el-text-color-secondary);
}
.docd-head {
	display: flex;
	align-items: center;
	justify-content: center;
	gap: 16px;
	margin-bottom: 16px;
	padding: 12px;
	background: var(--el-fill-color-light);
	border-radius: 8px;
}
.docd-version {
	display: flex;
	align-items: center;
	gap: 8px;
	flex-wrap: wrap;
	justify-content: center;
}
.docd-select {
	width: 220px;
}
.docd-arrow {
	font-size: 18px;
	color: var(--el-text-color-secondary);
}
.docd-summary {
	display: flex;
	justify-content: center;
	gap: 24px;
	margin-bottom: 18px;
	font-size: 14px;
}
.docd-sum-item { font-weight: 600; }
.docd-sum-item.add { color: #10b981; }
.docd-sum-item.del { color: #f56c6c; }
.docd-sum-item.mod { color: #f59e0b; }
.docd-change-row {
	padding: 10px 0;
	border-bottom: 1px solid var(--el-border-color-lighter);
}
.docd-change-row:last-child { border-bottom: none; }
.docd-change-key {
	font-weight: 600;
	font-size: 14px;
	margin-bottom: 8px;
}
.docd-change-item {
	display: flex;
	align-items: flex-start;
	gap: 8px;
	margin-bottom: 6px;
}
.docd-value {
	flex: 1;
	min-width: 0;
}
.docd-value pre {
	margin: 0 0 6px 0;
	padding: 8px 10px;
	border-radius: 4px;
	white-space: pre-wrap;
	word-break: break-all;
	font-family: Consolas, Monaco, monospace;
	font-size: 13px;
}
.docd-old { background: #fff0f0; color: #f56c6c; }
.docd-new { background: #f0fff4; color: #10b981; }
</style>

<style>
.docd-select-popper {
	max-width: 300px;
}
</style>
