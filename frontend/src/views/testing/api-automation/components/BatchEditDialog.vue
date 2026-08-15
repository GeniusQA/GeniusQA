<template>
	<el-dialog v-model="inner" title="批量编辑" width="560px" append-to-body>
		<div class="batch-mode">
			<el-radio-group v-model="batchMode" size="small">
				<el-radio-button label="comma">逗号模式</el-radio-button>
				<el-radio-button label="colon">冒号模式</el-radio-button>
			</el-radio-group>
			<span class="batch-hint">格式：参数名,默认值（逗号模式）或 参数名:默认值（冒号模式）</span>
		</div>
		<el-input
			v-model="batchText"
			type="textarea"
			:rows="9"
			placeholder="字段之间以英文冒号(:)分隔，多条记录以换行分隔"
		/>
		<template #footer>
			<el-button @click="inner = false">取消</el-button>
			<el-button type="primary" @click="apply">确定</el-button>
		</template>
	</el-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';

const props = defineProps<{
	modelValue: boolean;
	target: string;
}>();
const emit = defineEmits<{
	(e: 'update:modelValue', v: boolean): void;
	(e: 'apply', rows: { key: string; value: string; status: boolean; type: string; remark: string }[]): void;
}>();

const inner = ref(false);
watch(
	() => props.modelValue,
	(v) => {
		inner.value = v;
	},
	{ immediate: true }
);
watch(inner, (v) => emit('update:modelValue', v));

const batchMode = ref<'comma' | 'colon'>('comma');
const batchText = ref('');

const apply = () => {
	const sep = batchMode.value === 'comma' ? ',' : ':';
	const lines = batchText.value.split('\n').map((l) => l.trim()).filter(Boolean);
	const rows = lines.map((l) => {
		const idx = l.indexOf(sep);
		if (idx > 0) {
			return { key: l.slice(0, idx).trim(), value: l.slice(idx + 1).trim(), status: true, type: 'String', remark: '' };
		}
		return { key: l, value: '', status: true, type: 'String', remark: '' };
	});
	emit('apply', rows);
	inner.value = false;
	batchText.value = '';
};
</script>

<style scoped>
.batch-mode {
	display: flex;
	align-items: center;
	gap: 12px;
	margin-bottom: 10px;
}
.batch-hint {
	font-size: 12px;
	color: #909399;
}
</style>
