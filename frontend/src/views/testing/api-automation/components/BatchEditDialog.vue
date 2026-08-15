<template>
	<el-dialog v-model="inner" title="批量编辑" width="560px">
		<div class="batch-mode">
			<el-radio-group v-model="batchMode" size="small">
				<el-radio-button label="comma">逗号模式</el-radio-button>
				<el-radio-button label="colon">冒号模式</el-radio-button>
			</el-radio-group>
			<span class="batch-hint">{{ fmtHint }}</span>
		</div>
		<el-input
			v-model="batchText"
			type="textarea"
			:rows="9"
			:placeholder="phPlaceholder"
		/>
		<div class="batch-foot-hint">
			<template v-if="batchMode === 'comma'">
				数据格式遵循
				<el-popover placement="bottom-start" trigger="click" width="560">
					<template #reference>
						<a class="csv-link">《标准 CSV 规范》</a>
					</template>
					<div class="csv-rules">
						<div class="csv-rule-title">CSV 六列格式</div>
						<div v-for="r in csvRules" :key="r[0]" class="csv-rule-row">
							<b>{{ r[0] }}</b><span>{{ r[1] }}</span>
						</div>
						<div class="csv-spec-divider"></div>
						<div class="csv-rule-title">CSV 格式规范（RFC 4180）</div>
						<div v-for="(s, i) in csvSpecs" :key="i" class="csv-spec-item">
							<div class="csv-spec-desc"><b>{{ i + 1 }}.</b> {{ s.desc }}</div>
							<code class="csv-spec-code">{{ s.code }}</code>
						</div>
					</div>
				</el-popover>
				，字段之间以英文逗号(,)分隔，多条记录以换行分隔
			</template>
			<template v-else>字段之间以英文冒号(:)分隔，多条记录以换行分隔</template>
		</div>
		<template #footer>
			<el-button @click="inner = false">取消</el-button>
			<el-button type="primary" @click="apply">确定</el-button>
		</template>
	</el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';

const props = defineProps<{
	modelValue: boolean;
	target: string;
	initialText?: string;
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
		if (v) {
			batchMode.value = 'comma';
			batchText.value = props.initialText || '';
		}
	},
	{ immediate: true }
);
watch(inner, (v) => emit('update:modelValue', v));

const batchMode = ref<'comma' | 'colon'>('comma');
const batchText = ref('');
const fmtHint = computed(() =>
	batchMode.value === 'comma'
		? '格式：参数名,类型,必需,默认值,默认启用,说明'
		: '格式：参数名:默认值'
);
const phPlaceholder = computed(() =>
	batchMode.value === 'comma'
		? '如：X-MERCHANT-ID,string,true,MCH007881,true,商户号'
		: '如：X-MERCHANT-ID:MCH007881'
);
const csvRules: [string, string][] = [
	['参数名', '参数名称（必填）'],
	['类型', 'string / integer / boolean / number / array / object'],
	['必需', 'true / false'],
	['默认值', '参数默认值（object 类型不可填）'],
	['默认启用', 'true / false'],
	['说明', '参数说明（可选）'],
];
const csvSpecs: { desc: string; code: string }[] = [
	{
		desc: '文件中的各条记录必须位于不同行，其间以换行符 CRLF 分隔。例如：',
		code: 'aaa,bbb,ccc\nzzz,yyy,xxx',
	},
	{
		desc: '最后一条记录的末尾可以不包括换行符。例如：',
		code: 'aaa,bbb,ccc\nzzz,yyy,xxx',
	},
	{
		desc: '文件中的首条记录可以是字段名（但这不是必要的），且其所含的名称数量及存储规则须与其他记录保持一致。例如：',
		code: 'field_name,field_name,field_name\naaa,bbb,ccc\nzzz,yyy,xxx',
	},
	{
		desc: '每条记录中可以包含一个或多个字段，每个字段以半角逗号分隔。文件中的所有记录必须拥有相同数量的字段。字段中的空格属于字段取值，不可忽略。每条记录的最后一个字段之后不应再添加半角逗号。例如：',
		code: 'aaa,bbb,ccc',
	},
	{
		desc: '每个字段可以用半角双引号括起来（但这不一定是必要的）。如果字段没有被双引号括起来，那么字段中不应该出现双引号。例如：',
		code: '"aaa","bbb","ccc"\nzzz,yyy,xxx',
	},
	{
		desc: '含有换行符、半角双引号或半角逗号的字段应该用半角双引号括起来。例如：',
		code: '"aaa","b\nbb","ccc"\nzzz,yyy,xxx',
	},
	{
		desc: '如果字段被半角双引号括起来了，那么在表示字段取值中本身含有的半角双引号时，需要在其前方增加一个半角双引号。例如：',
		code: '"aaa","b""bb","ccc"',
	},
];
watch(() => props.initialText, (v) => { batchText.value = v || ''; });

const TYPES = ['string', 'integer', 'boolean', 'number', 'array', 'object'];
const TRUE_SET = new Set(['true', '1', '是', 'yes', 'y']);

const parseRow = (l: string) => {
	if (batchMode.value === 'comma') {
		// CSV 六列：参数名,类型,必需,默认值,默认启用,说明
		const parts = l.split(',').map((p) => p.trim());
		const row: any = { key: parts[0] || '', value: '', status: true, type: 'string', remark: '' };
		if (parts.length > 1 && TYPES.includes(parts[1].toLowerCase())) row.type = parts[1].toLowerCase();
		if (parts.length > 3) row.value = parts[3];
		if (parts.length > 4) row.status = TRUE_SET.has(parts[4].toLowerCase());
		if (parts.length > 5) row.remark = parts[5];
		return row;
	}
	// 冒号模式：参数名:默认值
	const idx = l.indexOf(':');
	if (idx > 0) {
		return { key: l.slice(0, idx).trim(), value: l.slice(idx + 1).trim(), status: true, type: 'string', remark: '' };
	}
	return { key: l, value: '', status: true, type: 'string', remark: '' };
};

const apply = () => {
	const lines = batchText.value.split('\n').map((l) => l.trim()).filter(Boolean);
	const rows = lines.map(parseRow);
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
.batch-foot-hint {
	margin-top: 6px;
	font-size: 12px;
	color: #909399;
	line-height: 1.6;
}
.csv-link {
	color: #7c3aed;
	cursor: pointer;
	text-decoration: underline;
}
.csv-rules {
	max-height: 420px;
	overflow-y: auto;
	padding-right: 4px;
}
.csv-rule-title {
	font-weight: 600;
	margin-bottom: 8px;
	color: #1f2937;
}
.csv-rule-row {
	display: flex;
	gap: 10px;
	padding: 4px 0;
	font-size: 13px;
}
.csv-rule-row b {
	min-width: 56px;
	color: #1f2937;
}
.csv-rule-row span {
	color: #4b5563;
}
.csv-spec-divider {
	border-top: 1px dashed #e5e7eb;
	margin: 10px 0;
}
.csv-spec-item {
	margin-bottom: 10px;
}
.csv-spec-desc {
	font-size: 13px;
	color: #1f2937;
	line-height: 1.5;
}
.csv-spec-desc b {
	margin-right: 4px;
}
.csv-spec-code {
	display: block;
	background: #1e2129;
	color: #e6edf3;
	border-radius: 4px;
	padding: 6px 10px;
	margin-top: 4px;
	font-family: Consolas, Menlo, Monaco, monospace;
	font-size: 12px;
	white-space: pre-wrap;
	word-break: break-all;
}
</style>
