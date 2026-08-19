<template>
	<el-dialog v-model="inner" title="差异对比" width="900px" append-to-body destroy-on-close class="ds-diff-dialog">
		<div v-if="loading" class="dsd-loading"><el-icon class="is-loading"><Loading /></el-icon> 加载中...</div>
		<template v-else-if="diffData">
			<div class="dsd-head">
				<div class="dsd-version old">
					<el-tag type="danger">前一个版本</el-tag>
					<el-select
						v-model="selectedLeftId"
						:teleported="false"
						popper-class="dsd-select-popper"
						size="small"
						class="dsd-select"
						@change="onLeftChange"
					>
						<el-option
							v-for="item in leftOptions"
							:key="item.id"
							:label="item.created_at"
							:value="item.id"
						/>
					</el-select>
				</div>
				<div class="dsd-arrow">→</div>
				<div class="dsd-version new">
					<el-tag type="success">该版本</el-tag>
					<el-select
						v-model="selectedRightId"
						:teleported="false"
						popper-class="dsd-select-popper"
						size="small"
						class="dsd-select"
						@change="onRightChange"
					>
						<el-option
							v-for="item in rightOptions"
							:key="item.id"
							:label="item.created_at"
							:value="item.id"
						/>
					</el-select>
				</div>
			</div>
			<div class="dsd-summary">
				<span class="dsd-sum-item add">新增 {{ diffData.summary?.added || 0 }}</span>
				<span class="dsd-sum-item del">删除 {{ diffData.summary?.removed || 0 }}</span>
				<span class="dsd-sum-item mod">修改 {{ diffData.summary?.modified || 0 }}</span>
			</div>

			<el-collapse v-model="activeNames">
				<el-collapse-item v-if="diffData.added?.length" name="added" title="新增接口">
					<div v-for="(item, idx) in diffData.added" :key="'add-' + idx" class="dsd-row">
						<div class="dsd-row-key">
							<el-tag size="small" type="success">+</el-tag>
							<span class="dsd-method" :class="methodClass(item.method)">{{ item.method }}</span>
							<span class="dsd-url">{{ item.url }}</span>
							<span class="dsd-name">{{ item.name }}</span>
						</div>
					</div>
				</el-collapse-item>
				<el-collapse-item v-if="diffData.removed?.length" name="removed" title="删除接口">
					<div v-for="(item, idx) in diffData.removed" :key="'del-' + idx" class="dsd-row">
						<div class="dsd-row-key">
							<el-tag size="small" type="danger">-</el-tag>
							<span class="dsd-method" :class="methodClass(item.method)">{{ item.method }}</span>
							<span class="dsd-url">{{ item.url }}</span>
							<span class="dsd-name">{{ item.name }}</span>
						</div>
					</div>
				</el-collapse-item>
				<el-collapse-item v-if="diffData.modified?.length" name="modified" title="修改接口">
					<div v-for="(item, idx) in diffData.modified" :key="'mod-' + idx" class="dsd-row">
						<div class="dsd-row-key">
							<el-tag size="small" type="warning">~</el-tag>
							<span class="dsd-method" :class="methodClass(item.method)">{{ item.method }}</span>
							<span class="dsd-url">{{ item.url }}</span>
							<span class="dsd-name">{{ item.name }}</span>
						</div>
						<div class="dsd-changes">
							<div v-for="(c, cidx) in item.changes" :key="cidx" class="dsd-change">
								<div class="dsd-change-field">{{ fieldLabel(c.field) }}</div>
								<div class="dsd-change-values">
									<div v-if="c.old !== undefined && c.old !== ''" class="dsd-old">
										<el-icon><Remove /></el-icon>
										<pre>{{ formatValue(c.old) }}</pre>
									</div>
									<div v-if="c.new !== undefined && c.new !== ''" class="dsd-new">
										<el-icon><CirclePlus /></el-icon>
										<pre>{{ formatValue(c.new) }}</pre>
									</div>
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
import { Loading, Remove, CirclePlus } from '@element-plus/icons-vue';
import { ElMessage } from 'element-plus';
import { useApiAutomationApi } from '/@/api/v1/testing/apiAutomation';

const props = defineProps<{
	modelValue: boolean;
	historyA?: Record<string, any> | null;
	historyB?: Record<string, any> | null;
	historyList?: Record<string, any>[];
}>();

const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>();

const inner = computed({
	get: () => props.modelValue,
	set: (v: boolean) => emit('update:modelValue', v),
});

const loading = ref(false);
const diffData = ref<any>(null);
const activeNames = ref(['added', 'removed', 'modified']);

const selectedLeftId = ref<number | null>(null);
const selectedRightId = ref<number | null>(null);

const allHistory = computed(() => props.historyList || []);

const leftIndex = computed(() => allHistory.value.findIndex((h) => h.id === selectedLeftId.value));
const rightIndex = computed(() => allHistory.value.findIndex((h) => h.id === selectedRightId.value));

// 历史列表按时间从新到旧排列（index 越小越新）
// 左侧（旧版本）只能选比右侧更旧的版本：index > rightIndex
const leftOptions = computed(() => {
	const ri = rightIndex.value;
	if (ri < 0) return allHistory.value.slice(1);
	return allHistory.value.filter((_, idx) => idx > ri);
});

// 右侧（新版本）只能选比左侧更新的版本：index < leftIndex
const rightOptions = computed(() => {
	const li = leftIndex.value;
	if (li < 0) return allHistory.value.slice(0, -1);
	return allHistory.value.filter((_, idx) => idx < li);
});

const selectedLeft = computed(() => allHistory.value.find((h) => h.id === selectedLeftId.value));
const selectedRight = computed(() => allHistory.value.find((h) => h.id === selectedRightId.value));

const methodClass = (m: string) => {
	const t = String(m || '').toLowerCase();
	return {
		'm-get': t === 'get',
		'm-post': t === 'post',
		'm-put': t === 'put',
		'm-del': t === 'delete' || t === 'del',
		'm-patch': t === 'patch',
	};
};

const fieldLabel = (f: string) => {
	const map: Record<string, string> = {
		name: '接口名称',
		description: '接口描述',
		method: '请求方法',
		url: '接口路径',
		params: 'Query 参数',
		body: '请求体',
		body_type: '请求体类型',
		header: '请求头',
		operation_id: 'OperationId',
		tags: '标签',
	};
	return map[f] || f;
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
		const r: any = await useApiAutomationApi().dataSourceHistoryDiff({
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
	// 右侧必须比左侧新；若当前右侧不在新选项中，重置为可选的最新版本
	const opts = rightOptions.value;
	if (!opts.find((h) => h.id === selectedRightId.value)) {
		selectedRightId.value = opts[0]?.id || null;
	}
	loadDiff();
};

const onRightChange = (val: number) => {
	selectedRightId.value = val;
	// 左侧必须比右侧旧；若当前左侧不在新选项中，重置为可选的最早版本
	const opts = leftOptions.value;
	if (!opts.find((h) => h.id === selectedLeftId.value)) {
		selectedLeftId.value = opts[opts.length - 1]?.id || null;
	}
	loadDiff();
};

const resetSelection = () => {
	const a = props.historyA;
	const b = props.historyB;
	const list = allHistory.value;
	if (!list.length) {
		selectedLeftId.value = a?.id || null;
		selectedRightId.value = b?.id || null;
		return;
	}
	// 默认：右侧为最新版本，左侧为传入的 historyA（或紧邻最新的下一个版本）
	selectedRightId.value = b?.id ?? list[0]?.id ?? null;
	selectedLeftId.value = a?.id ?? null;
	// 校验并修正：左侧必须比右侧旧
	const ri = list.findIndex((h) => h.id === selectedRightId.value);
	const li = list.findIndex((h) => h.id === selectedLeftId.value);
	if (li >= 0 && ri >= 0 && li <= ri) {
		// 传入的左侧不比右侧旧，取右侧之后第一个作为左侧
		selectedLeftId.value = list[ri + 1]?.id ?? null;
	}
	if (selectedLeftId.value == null) {
		selectedLeftId.value = list[ri + 1]?.id ?? list[list.length - 1]?.id ?? null;
	}
};

watch(
	() => [props.modelValue, props.historyA?.id, props.historyB?.id, props.historyList?.length],
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
.dsd-loading {
	text-align: center;
	padding: 60px 0;
	color: var(--el-text-color-secondary);
}
.dsd-head {
	display: flex;
	align-items: center;
	justify-content: center;
	gap: 16px;
	margin-bottom: 16px;
	padding: 12px;
	background: var(--el-fill-color-light);
	border-radius: 8px;
}
.dsd-version {
	display: flex;
	align-items: center;
	gap: 8px;
}
.dsd-select {
	width: 180px;
}
.dsd-arrow {
	font-size: 18px;
	color: var(--el-text-color-secondary);
}
.dsd-summary {
	display: flex;
	justify-content: center;
	gap: 24px;
	margin-bottom: 18px;
	font-size: 14px;
}
.dsd-sum-item {
	font-weight: 600;
}
.dsd-sum-item.add { color: #10b981; }
.dsd-sum-item.del { color: #f56c6c; }
.dsd-sum-item.mod { color: #f59e0b; }
.dsd-row {
	padding: 10px 0;
	border-bottom: 1px solid var(--el-border-color-lighter);
}
.dsd-row-key {
	display: flex;
	align-items: center;
	gap: 8px;
	font-size: 13px;
}
.dsd-method {
	font-weight: 600;
	font-size: 12px;
	padding: 2px 6px;
	border-radius: 4px;
	background: var(--el-fill-color);
	color: var(--el-text-color-regular);
}
.dsd-method.m-get { background: #e6f7ed; color: #10b981; }
.dsd-method.m-post { background: #e6f0ff; color: #3b82f6; }
.dsd-method.m-put { background: #fff7e6; color: #f59e0b; }
.dsd-method.m-del { background: #fee; color: #f56c6c; }
.dsd-method.m-patch { background: #f3e6ff; color: #8b5cf6; }
.dsd-url {
	font-family: monospace;
	color: var(--el-text-color-primary);
}
.dsd-name {
	color: var(--el-text-color-secondary);
}
.dsd-changes {
	margin-top: 10px;
	padding-left: 28px;
}
.dsd-change {
	margin-bottom: 10px;
}
.dsd-change-field {
	font-size: 12px;
	color: var(--el-text-color-secondary);
	margin-bottom: 6px;
}
.dsd-change-values {
	display: flex;
	flex-direction: column;
	gap: 6px;
}
.dsd-old,
.dsd-new {
	display: flex;
	align-items: flex-start;
	gap: 6px;
	padding: 8px 10px;
	border-radius: 4px;
	font-size: 13px;
}
.dsd-old {
	background: #fff0f0;
	color: #f56c6c;
}
.dsd-new {
	background: #f0fff4;
	color: #10b981;
}
.dsd-old pre,
.dsd-new pre {
	margin: 0;
	white-space: pre-wrap;
	word-break: break-all;
	font-family: inherit;
}
</style>

<style>
.dsd-select-popper {
	max-width: 260px;
}
</style>
