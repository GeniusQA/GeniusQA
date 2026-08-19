<template>
	<div class="doc-panel-wrap">
		<div class="doc-toolbar">
			<div class="doc-toolbar-left">
				<span v-if="displayInfo" class="doc-method-badge" :style="{ background: methodColor }">{{ methodName }}</span>
				<span v-if="displayInfo" class="doc-path" :title="displayInfo.url">{{ displayInfo.url || '-' }}</span>
			</div>
			<div class="doc-toolbar-right">
				<template v-if="editing">
					<el-button size="small" @click="cancelEdit">取消</el-button>
					<el-button size="small" type="primary" :loading="saving" @click="saveDoc">保存</el-button>
				</template>
				<template v-else>
					<el-button size="small" type="primary" plain @click="startEdit">编辑</el-button>
					<el-button size="small" type="success" plain @click="createFromScratch" v-if="!hasDocument">新建文档</el-button>
					<el-button size="small" @click="openHistory">历史记录</el-button>
					<el-button size="small" @click="exportOpenApi" :disabled="!hasDocument">导出 OpenAPI</el-button>
				</template>
			</div>
		</div>

		<template v-if="editing">
			<div class="doc-section">
				<div class="doc-section-title">基本信息</div>
				<el-form label-width="80px" size="small">
					<el-form-item label="摘要">
						<el-input v-model="draft.summary" placeholder="接口摘要" />
					</el-form-item>
					<el-form-item label="说明">
						<el-input v-model="draft.description" type="textarea" :rows="2" placeholder="接口说明" />
					</el-form-item>
				</el-form>
			</div>

			<div class="doc-section">
				<div class="doc-section-title-row">
					<div class="doc-section-title">请求参数</div>
					<el-button type="primary" link size="small" @click="draft.parameters.push(emptyParam())">+ 新增参数</el-button>
				</div>
				<el-table :data="draft.parameters" border stripe size="small" empty-text="暂无请求参数">
					<el-table-column label="参数名" min-width="120">
						<template #default="{ row }"><el-input v-model="row.name" size="small" placeholder="name" /></template>
					</el-table-column>
					<el-table-column label="位置" width="110">
						<template #default="{ row }">
							<el-select v-model="row.in" size="small" style="width:100%">
								<el-option label="query" value="query" />
								<el-option label="path" value="path" />
								<el-option label="header" value="header" />
								<el-option label="cookie" value="cookie" />
							</el-select>
						</template>
					</el-table-column>
					<el-table-column label="类型" width="110">
						<template #default="{ row }">
							<el-select v-model="row.type" size="small" style="width:100%" allow-create filterable>
								<el-option v-for="t in typeOptions" :key="t" :label="t" :value="t" />
							</el-select>
						</template>
					</el-table-column>
					<el-table-column label="必填" width="70" align="center">
						<template #default="{ row }"><el-checkbox v-model="row.required" /></template>
					</el-table-column>
					<el-table-column label="说明" min-width="160">
						<template #default="{ row }"><el-input v-model="row.description" size="small" placeholder="说明" /></template>
					</el-table-column>
					<el-table-column label="操作" width="70" align="center">
						<template #default="{ $index }">
							<el-button type="danger" link size="small" @click="draft.parameters.splice($index, 1)">删除</el-button>
						</template>
					</el-table-column>
				</el-table>
			</div>

			<div class="doc-section">
				<div class="doc-section-title-row">
					<div class="doc-section-title">Body 参数</div>
					<div class="doc-section-actions">
						<el-select v-model="draft.requestBodyType" size="small" style="width:220px" allow-create filterable>
							<el-option label="application/json" value="application/json" />
							<el-option label="multipart/form-data" value="multipart/form-data" />
							<el-option label="application/x-www-form-urlencoded" value="application/x-www-form-urlencoded" />
						</el-select>
						<el-button type="primary" link size="small" @click="draft.bodyFields.push(emptyField())">+ 新增字段</el-button>
					</div>
				</div>
				<el-table :data="draft.bodyFields" border stripe size="small" empty-text="暂无 Body 字段">
					<el-table-column label="字段名" min-width="120">
						<template #default="{ row }"><el-input v-model="row.name" size="small" placeholder="field" /></template>
					</el-table-column>
					<el-table-column label="类型" width="110">
						<template #default="{ row }">
							<el-select v-model="row.type" size="small" style="width:100%" allow-create filterable>
								<el-option v-for="t in typeOptions" :key="t" :label="t" :value="t" />
							</el-select>
						</template>
					</el-table-column>
					<el-table-column label="必填" width="70" align="center">
						<template #default="{ row }"><el-checkbox v-model="row.required" /></template>
					</el-table-column>
					<el-table-column label="说明" min-width="160">
						<template #default="{ row }"><el-input v-model="row.description" size="small" placeholder="说明" /></template>
					</el-table-column>
					<el-table-column label="操作" width="70" align="center">
						<template #default="{ $index }">
							<el-button type="danger" link size="small" @click="draft.bodyFields.splice($index, 1)">删除</el-button>
						</template>
					</el-table-column>
				</el-table>
			</div>

			<div class="doc-section">
				<div class="doc-section-title-row">
					<div class="doc-section-title">返回响应</div>
					<el-button type="primary" link size="small" @click="addResponse">+ 新增响应</el-button>
				</div>
				<div v-for="(resp, ri) in draft.responses" :key="ri" class="doc-response-edit">
					<div class="doc-response-edit-header">
						<el-input-number v-model="resp.code" :min="100" :max="599" size="small" controls-position="right" />
						<el-input v-model="resp.description" size="small" placeholder="响应说明" style="flex:1" />
						<el-button type="danger" link size="small" @click="draft.responses.splice(ri, 1)">删除响应</el-button>
						<el-button type="primary" link size="small" @click="resp.fields.push(emptyField())">+ 字段</el-button>
					</div>
					<el-table :data="resp.fields" border stripe size="small" empty-text="暂无字段（可填示例 JSON）" style="margin-top:8px">
						<el-table-column label="字段名" min-width="120">
							<template #default="{ row }"><el-input v-model="row.name" size="small" /></template>
						</el-table-column>
						<el-table-column label="类型" width="110">
							<template #default="{ row }">
								<el-select v-model="row.type" size="small" style="width:100%" allow-create filterable>
									<el-option v-for="t in typeOptions" :key="t" :label="t" :value="t" />
								</el-select>
							</template>
						</el-table-column>
						<el-table-column label="说明" min-width="160">
							<template #default="{ row }"><el-input v-model="row.description" size="small" /></template>
						</el-table-column>
						<el-table-column label="操作" width="70" align="center">
							<template #default="{ $index }">
								<el-button type="danger" link size="small" @click="resp.fields.splice($index, 1)">删除</el-button>
							</template>
						</el-table-column>
					</el-table>
					<el-input
						v-if="!resp.fields.length"
						v-model="resp.example"
						type="textarea"
						:rows="3"
						placeholder='无字段时可填响应示例 JSON，如 {"code":0,"msg":"ok"}'
						style="margin-top:8px"
					/>
				</div>
				<div v-if="!draft.responses.length" class="doc-empty-hint">暂无响应，点击「新增响应」</div>
			</div>
		</template>

		<template v-else-if="displayInfo">
			<div v-if="displayInfo.description" class="doc-desc-block">{{ displayInfo.description }}</div>

			<div v-if="displayInfo.parameters.length" class="doc-section">
				<div class="doc-section-title">请求参数</div>
				<el-table :data="displayInfo.parameters" border stripe size="small" empty-text="暂无请求参数">
					<el-table-column prop="name" label="参数名" min-width="140" show-overflow-tooltip>
						<template #default="{ row }"><span class="doc-param-name">{{ row.name }}</span></template>
					</el-table-column>
					<el-table-column label="位置" width="100" align="center">
						<template #default="{ row }">
							<span class="doc-in-badge" :class="'in-' + row.in">{{ row.in }}</span>
						</template>
					</el-table-column>
					<el-table-column label="类型" width="110" align="center">
						<template #default="{ row }"><span class="doc-type">{{ row.type || '-' }}</span></template>
					</el-table-column>
					<el-table-column label="必填" width="80" align="center">
						<template #default="{ row }">
							<el-tag v-if="row.required" size="small" type="danger" effect="plain">必填</el-tag>
							<span v-else class="doc-optional">可选</span>
						</template>
					</el-table-column>
					<el-table-column prop="description" label="说明" min-width="180" show-overflow-tooltip>
						<template #default="{ row }">{{ row.description || '-' }}</template>
					</el-table-column>
				</el-table>
			</div>

			<div v-if="showBodySection" class="doc-section">
				<div class="doc-section-title">Body 参数</div>
				<div v-if="displayInfo.requestBodyType" class="doc-content-type">
					Content-Type: <code>{{ displayInfo.requestBodyType }}</code>
				</div>
				<el-table
					v-if="displayInfo.bodyFields.length"
					:data="displayInfo.bodyFields"
					border
					stripe
					size="small"
					empty-text="暂无 Body 参数"
				>
					<el-table-column prop="name" label="字段名" min-width="140" show-overflow-tooltip>
						<template #default="{ row }"><span class="doc-param-name">{{ row.name }}</span></template>
					</el-table-column>
					<el-table-column label="类型" width="110" align="center">
						<template #default="{ row }"><span class="doc-type">{{ row.type || '-' }}</span></template>
					</el-table-column>
					<el-table-column label="必填" width="80" align="center">
						<template #default="{ row }">
							<el-tag v-if="row.required" size="small" type="danger" effect="plain">必填</el-tag>
							<span v-else class="doc-optional">可选</span>
						</template>
					</el-table-column>
					<el-table-column prop="description" label="说明" min-width="180" show-overflow-tooltip>
						<template #default="{ row }">{{ row.description || '-' }}</template>
					</el-table-column>
				</el-table>
				<div v-else-if="displayInfo.requestBodyRaw" class="doc-raw-schema">
					<pre class="doc-pre">{{ displayInfo.requestBodyRaw }}</pre>
				</div>
			</div>

			<div v-if="displayInfo.responses.length" class="doc-section">
				<div class="doc-section-title">返回响应</div>
				<div v-for="resp in displayInfo.responses" :key="resp.code" class="doc-response-item">
					<div class="doc-response-header">
						<el-tag
							size="small"
							:type="resp.code >= 200 && resp.code < 300 ? 'success' : resp.code >= 400 ? 'danger' : 'warning'"
							effect="light"
						>{{ resp.code }}</el-tag>
						<span class="doc-response-desc">{{ resp.description || '-' }}</span>
						<span v-if="resp.contentType" class="doc-response-ct">{{ resp.contentType }}</span>
					</div>
					<el-table
						v-if="resp.fields.length"
						:data="resp.fields"
						border
						stripe
						size="small"
						style="margin-top: 8px"
					>
						<el-table-column prop="name" label="字段名" min-width="140" show-overflow-tooltip>
							<template #default="{ row }"><span class="doc-param-name">{{ row.name }}</span></template>
						</el-table-column>
						<el-table-column label="类型" width="110" align="center">
							<template #default="{ row }"><span class="doc-type">{{ row.type || '-' }}</span></template>
						</el-table-column>
						<el-table-column prop="description" label="说明" min-width="180" show-overflow-tooltip>
							<template #default="{ row }">{{ row.description || '-' }}</template>
						</el-table-column>
					</el-table>
					<div v-else-if="resp.example" class="doc-raw-schema">
						<pre class="doc-pre">{{ resp.example }}</pre>
					</div>
				</div>
			</div>

			<div v-if="!displayInfo.parameters.length && !showBodySection && !displayInfo.responses.length" class="doc-empty">
				<p>文档内容为空，点击「编辑」补充参数与响应</p>
			</div>
		</template>

		<div v-else class="doc-empty">
			<el-icon style="font-size:36px;color:#dcdfe6"><Document /></el-icon>
			<p>暂无接口文档</p>
			<el-button type="primary" size="small" style="margin-top:8px" @click="createFromScratch">新建文档</el-button>
		</div>

		<ApiDocHistoryDialog
			v-model="historyVisible"
			:api-id="apiId"
			:api-data="apiData"
			@restore="onDocRestored"
		/>
		</div>
		</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { Document } from '@element-plus/icons-vue';
import { save_api } from '/@/api/v1/testing/apiAutomation';
import ApiDocHistoryDialog from './ApiDocHistoryDialog.vue';

const props = defineProps<{ apiData: any; apiId?: number | null }>();
const emit = defineEmits<{ (e: 'updated', document: Record<string, any>): void }>();

const METHOD_MAP: Record<number, { label: string; color: string }> = {
	1: { label: 'GET', color: '#67C23A' },
	2: { label: 'POST', color: '#409EFF' },
	3: { label: 'PUT', color: '#E6A23C' },
	4: { label: 'DELETE', color: '#F56C6C' },
	5: { label: 'PATCH', color: '#8E44AD' },
	6: { label: 'OPTIONS', color: '#909399' },
};

const BODY_IN = new Set(['body', 'formdata', 'formData']);
const typeOptions = ['string', 'integer', 'number', 'boolean', 'array', 'object', 'file'];

type FieldRow = { name: string; type: string; required: boolean; description: string };
type ParamRow = FieldRow & { in: string };
type RespRow = { code: number; description: string; fields: FieldRow[]; example: string; contentType?: string };

const editing = ref(false);
const saving = ref(false);
const localDoc = ref<Record<string, any> | null>(null);

const draft = reactive<{
	summary: string;
	description: string;
	parameters: ParamRow[];
	bodyFields: FieldRow[];
	requestBodyType: string;
	responses: RespRow[];
}>({
	summary: '',
	description: '',
	parameters: [],
	bodyFields: [],
	requestBodyType: 'application/json',
	responses: [],
});

const emptyParam = (): ParamRow => ({ name: '', in: 'query', type: 'string', required: false, description: '' });
const emptyField = (): FieldRow => ({ name: '', type: 'string', required: false, description: '' });
const addResponse = () => {
	draft.responses.push({ code: 200, description: '成功', fields: [], example: '' });
};

const info = computed(() => props.apiData?.api_info || props.apiData || {});
const apiId = computed(() => {
	const candidates = [
		props.apiId,
		props.apiData?.api_id,
		props.apiData?.api_info?.id,
		props.apiData?.api_info?.api_id,
		info.value?.api_id,
		info.value?.id,
	];
	for (const c of candidates) {
		const n = Number(c);
		if (Number.isFinite(n) && n > 0) return n;
	}
	return 0;
});

const schemaType = (v: any): string => {
	if (!v || typeof v !== 'object') return '-';
	if (v.type) return v.type;
	if (v.$ref) return String(v.$ref).split('/').pop() || '-';
	if (v.items) return `array<${schemaType(v.items)}>`;
	return '-';
};

const fieldsFromSchema = (schema: any): FieldRow[] => {
	if (!schema || typeof schema !== 'object') return [];
	const target = schema.properties
		? schema
		: (schema.items?.properties ? schema.items : null);
	if (!target?.properties) return [];
	const required: string[] = Array.isArray(target.required) ? target.required : (Array.isArray(schema.required) ? schema.required : []);
	return Object.entries(target.properties).map(([k, v]: any) => ({
		name: k,
		type: schemaType(v) || 'string',
		required: required.includes(k),
		description: v?.description || '',
	}));
};

const parseDoc = (doc: any, apiInfo: any) => {
	if (!doc || typeof doc !== 'object') return null;
	const method = apiInfo.req?.method ?? 2;
	const allParams: any[] = Array.isArray(doc.parameters) ? doc.parameters : [];
	const parameters: ParamRow[] = [];
	const bodyFromParams: FieldRow[] = [];

	for (const p of allParams) {
		const loc = String(p.in || 'query');
		const row = {
			name: p.name || '',
			in: loc,
			type: p.schema?.type || p.type || schemaType(p.schema) || 'string',
			required: !!p.required,
			description: p.description || '',
		};
		if (BODY_IN.has(loc) || BODY_IN.has(loc.toLowerCase())) {
			bodyFromParams.push({ name: row.name, type: row.type, required: row.required, description: row.description });
		} else {
			parameters.push(row as ParamRow);
		}
	}

	let requestBodyType = '';
	let bodyFields: FieldRow[] = [];
	let requestBodyRaw = '';
	let hasRequestBody = false;

	if (doc.requestBody) {
		hasRequestBody = true;
		const content = doc.requestBody.content || {};
		const ct = Object.keys(content)[0] || '';
		requestBodyType = ct || (doc.requestBody.required ? 'application/json' : '');
		const schema = ct ? (content[ct]?.schema || {}) : {};
		bodyFields = fieldsFromSchema(schema);
		if (!bodyFields.length && Object.keys(schema).length) {
			requestBodyRaw = JSON.stringify(schema, null, 2);
		}
	}

	if (!bodyFields.length && bodyFromParams.length) {
		bodyFields = bodyFromParams;
		if (!requestBodyType) {
			const hasFile = bodyFromParams.some((p) => String(p.type).toLowerCase() === 'file');
			requestBodyType = hasFile ? 'multipart/form-data' : 'application/x-www-form-urlencoded';
		}
		hasRequestBody = true;
	}

	const responses: RespRow[] = [];
	if (doc.responses) {
		for (const [code, resp] of Object.entries(doc.responses as Record<string, any>)) {
			const content = resp.content || {};
			const ct = Object.keys(content)[0] || '';
			const schema = ct ? (content[ct]?.schema || {}) : (resp.schema || {});
			const fields = fieldsFromSchema(schema);
			let example = '';
			if (!fields.length && schema && Object.keys(schema).length) {
				example = JSON.stringify(schema, null, 2);
			} else if (!fields.length && resp.example) {
				example = typeof resp.example === 'string' ? resp.example : JSON.stringify(resp.example, null, 2);
			}
			responses.push({
				code: Number(code) || Number(String(code).replace(/\D/g, '')) || 200,
				description: resp.description || '',
				contentType: ct,
				fields,
				example,
			});
		}
	}

	return {
		name: apiInfo.name || doc.summary || doc.operationId || '',
		url: apiInfo.url || '',
		method,
		description: doc.description || doc.summary || '',
		summary: doc.summary || '',
		parameters,
		bodyFields,
		requestBodyType,
		requestBodyRaw,
		hasRequestBody,
		responses,
	};
};

const sourceDoc = computed(() => localDoc.value ?? info.value.document ?? null);
const hasDocument = computed(() => !!(sourceDoc.value && typeof sourceDoc.value === 'object' && Object.keys(sourceDoc.value).length));
const displayInfo = computed(() => parseDoc(sourceDoc.value, info.value));

const showBodySection = computed(() => {
	const d = displayInfo.value;
	if (!d) return false;
	return d.hasRequestBody || d.bodyFields.length > 0 || !!d.requestBodyRaw;
});

const methodName = computed(() => METHOD_MAP[displayInfo.value?.method ?? info.value.req?.method ?? 2]?.label || 'GET');
const methodColor = computed(() => METHOD_MAP[displayInfo.value?.method ?? info.value.req?.method ?? 2]?.color || '#409EFF');

watch(() => props.apiData, () => {
	localDoc.value = null;
	if (editing.value) cancelEdit();
}, { deep: true });

const seedFromReq = () => {
	const req = info.value.req || {};
	const parameters: ParamRow[] = [];
	for (const p of req.params || []) {
		if (!p?.key) continue;
		parameters.push({ name: String(p.key), in: 'query', type: 'string', required: !!p.status, description: '' });
	}
	for (const h of req.header || []) {
		if (!h?.key) continue;
		parameters.push({ name: String(h.key), in: 'header', type: 'string', required: !!h.status, description: '' });
	}
	const bodyFields: FieldRow[] = [];
	let requestBodyType = 'application/json';
	const bt = Number(req.body_type || 2);
	if (bt === 3) {
		requestBodyType = 'multipart/form-data';
		for (const f of req.form_data || []) {
			if (!f?.key) continue;
			bodyFields.push({ name: String(f.key), type: 'string', required: !!f.status, description: '' });
		}
	} else if (bt === 4) {
		requestBodyType = 'application/x-www-form-urlencoded';
		for (const f of req.form_urlencoded || []) {
			if (!f?.key) continue;
			bodyFields.push({ name: String(f.key), type: 'string', required: !!f.status, description: '' });
		}
	} else if (bt === 2) {
		try {
			const body = typeof req.body === 'string' ? JSON.parse(req.body || '{}') : (req.body || {});
			if (body && typeof body === 'object' && !Array.isArray(body)) {
				for (const [k, v] of Object.entries(body)) {
					const t = Array.isArray(v) ? 'array' : typeof v === 'number' ? 'number' : typeof v === 'boolean' ? 'boolean' : typeof v === 'object' ? 'object' : 'string';
					bodyFields.push({ name: k, type: t, required: false, description: '' });
				}
			}
		} catch { /* ignore */ }
	}
	return {
		summary: info.value.name || '',
		description: info.value.description || '',
		parameters,
		bodyFields,
		requestBodyType,
		responses: [{ code: 200, description: '成功', fields: [], example: '{"code":0,"data":{}}' }] as RespRow[],
	};
};

const fillDraftFromDisplay = () => {
	const d = displayInfo.value;
	if (d) {
		draft.summary = d.summary || d.name || '';
		draft.description = d.description || '';
		draft.parameters = d.parameters.map((p) => ({ ...p }));
		draft.bodyFields = d.bodyFields.map((f) => ({ ...f }));
		draft.requestBodyType = d.requestBodyType || 'application/json';
		draft.responses = d.responses.map((r) => ({
			code: Number(r.code) || 200,
			description: r.description || '',
			fields: (r.fields || []).map((f) => ({ ...f })),
			example: r.example || '',
			contentType: r.contentType,
		}));
	} else {
		Object.assign(draft, seedFromReq());
	}
};

const startEdit = () => {
	fillDraftFromDisplay();
	editing.value = true;
};

const createFromScratch = () => {
	Object.assign(draft, seedFromReq());
	editing.value = true;
};

const cancelEdit = () => {
	editing.value = false;
};

const fieldsToSchema = (fields: FieldRow[]) => {
	const properties: Record<string, any> = {};
	const required: string[] = [];
	for (const f of fields) {
		const name = String(f.name || '').trim();
		if (!name) continue;
		properties[name] = { type: f.type || 'string', description: f.description || '' };
		if (f.required) required.push(name);
	}
	const schema: Record<string, any> = { type: 'object', properties };
	if (required.length) schema.required = required;
	return schema;
};

const buildDocument = () => {
	const parameters = draft.parameters
		.filter((p) => String(p.name || '').trim())
		.map((p) => ({
			name: String(p.name).trim(),
			in: p.in || 'query',
			required: !!p.required,
			description: p.description || '',
			schema: { type: p.type || 'string' },
		}));

	const bodySchema = fieldsToSchema(draft.bodyFields);
	const hasBody = Object.keys(bodySchema.properties || {}).length > 0;
	const ct = draft.requestBodyType || 'application/json';

	const document: Record<string, any> = {
		summary: draft.summary || info.value.name || '',
		description: draft.description || '',
		parameters,
	};

	if (hasBody) {
		document.requestBody = {
			required: (bodySchema.required || []).length > 0,
			content: {
				[ct]: { schema: bodySchema },
			},
		};
	}

	const responses: Record<string, any> = {};
	for (const r of draft.responses) {
		const code = String(r.code || 200);
		const fields = fieldsToSchema(r.fields || []);
		const resp: Record<string, any> = { description: r.description || '' };
		if (Object.keys(fields.properties || {}).length) {
			resp.content = { 'application/json': { schema: fields } };
		} else if (r.example?.trim()) {
			try {
				const ex = JSON.parse(r.example);
				resp.content = {
					'application/json': {
						schema: { type: 'object', example: ex },
						example: ex,
					},
				};
			} catch {
				resp.content = {
					'application/json': {
						schema: { type: 'string', example: r.example },
						example: r.example,
					},
				};
			}
		}
		responses[code] = resp;
	}
	if (!Object.keys(responses).length) {
		responses['200'] = { description: '成功' };
	}
	document.responses = responses;
	return document;
};

const saveDoc = async () => {
	if (!apiId.value) {
		ElMessage.warning('无法获取接口 ID');
		return;
	}
	saving.value = true;
	try {
		const document = buildDocument();
		await save_api({
			id: apiId.value,
			document,
			name: draft.summary || undefined,
			description: draft.description || undefined,
		});
		localDoc.value = document;
		if (props.apiData?.api_info) {
			props.apiData.api_info.document = document;
			if (draft.summary) props.apiData.api_info.name = draft.summary;
			if (draft.description) props.apiData.api_info.description = draft.description;
		} else if (props.apiData) {
			props.apiData.document = document;
		}
		emit('updated', document);
		editing.value = false;
		ElMessage.success('文档已保存');
	} catch (e: any) {
		ElMessage.error(e?.message || '保存失败');
	} finally {
		saving.value = false;
	}
};

const normalizeExportPath = (raw: string) => {
	let u = String(raw || '/').trim();
	u = u.replace(/\{\{[^{}]+\}\}/g, '{var}').replace(/\$\{[^}]+\}/g, '{var}');
	try {
		if (/^https?:\/\//i.test(u)) u = new URL(u).pathname;
	} catch { /* ignore */ }
	u = u.split('?')[0] || '/';
	if (!u.startsWith('/')) u = `/${u}`;
	return u || '/';
};

const historyVisible = ref(false);
const openHistory = () => {
	if (!apiId.value) {
		ElMessage.warning('无法获取接口 ID');
		return;
	}
	historyVisible.value = true;
};
const onDocRestored = (document: Record<string, any>) => {
	localDoc.value = document;
	if (props.apiData?.api_info) {
		props.apiData.api_info.document = document;
	} else if (props.apiData) {
		props.apiData.document = document;
	}
	emit('updated', document);
};

const exportOpenApi = () => {
	const doc = sourceDoc.value;
	if (!doc) {
		ElMessage.warning('暂无文档可导出');
		return;
	}
	const method = String(methodName.value || 'GET').toLowerCase();
	const path = normalizeExportPath(info.value.url || '');
	const openapi = {
		openapi: '3.0.3',
		info: {
			title: info.value.name || doc.summary || 'API',
			description: doc.description || info.value.description || '',
			version: '1.0.0',
		},
		paths: {
			[path]: {
				[method]: {
					...doc,
					operationId: doc.operationId || `api_${apiId.value || 'export'}`,
				},
			},
		},
	};
	const blob = new Blob([JSON.stringify(openapi, null, 2)], { type: 'application/json;charset=utf-8' });
	const a = document.createElement('a');
	const safeName = String(info.value.name || 'api').replace(/[\\/:*?"<>|]/g, '_');
	a.href = URL.createObjectURL(blob);
	a.download = `${safeName}.openapi.json`;
	a.click();
	URL.revokeObjectURL(a.href);
	ElMessage.success('已导出 OpenAPI 3.0');
};
</script>

<style scoped>
.doc-panel-wrap {
	height: 100%;
	overflow-y: auto;
	background: var(--el-bg-color);
	box-sizing: border-box;
}
.doc-toolbar {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 12px;
	padding: 12px 16px;
	background: var(--el-fill-color-light);
	border-bottom: 1px solid var(--el-border-color);
	position: sticky;
	top: 0;
	z-index: 2;
}
.doc-toolbar-left {
	display: flex;
	align-items: center;
	gap: 10px;
	min-width: 0;
	flex: 1;
}
.doc-toolbar-right {
	display: flex;
	align-items: center;
	gap: 8px;
	flex-shrink: 0;
}
.doc-method-badge {
	display: inline-block;
	padding: 3px 10px;
	border-radius: 4px;
	color: #fff;
	font-size: 12px;
	font-weight: 700;
	letter-spacing: .5px;
	flex-shrink: 0;
}
.doc-path {
	font-family: Consolas, Monaco, monospace;
	font-size: 14px;
	color: var(--el-text-color-primary);
	word-break: break-all;
}
.doc-desc-block {
	padding: 10px 20px;
	font-size: 13px;
	line-height: 1.6;
	color: var(--el-text-color-regular);
	background: var(--el-color-warning-light-9);
	border-bottom: 1px solid var(--el-color-warning-light-5);
}
.doc-section {
	padding: 16px 20px;
	border-bottom: 1px solid var(--el-border-color-lighter);
}
.doc-section:last-child { border-bottom: none; }
.doc-section-title {
	font-size: 13px;
	font-weight: 600;
	color: var(--el-text-color-primary);
	margin-bottom: 12px;
	padding-left: 8px;
	border-left: 3px solid var(--el-color-primary);
}
.doc-section-title-row {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 12px;
	margin-bottom: 12px;
}
.doc-section-title-row .doc-section-title {
	margin-bottom: 0;
}
.doc-section-actions {
	display: flex;
	align-items: center;
	gap: 8px;
}
.doc-content-type {
	font-size: 12px;
	color: var(--el-text-color-secondary);
	margin-bottom: 8px;
}
.doc-content-type code {
	font-family: Consolas, Monaco, monospace;
	color: var(--el-color-primary);
}
.doc-param-name {
	font-family: Consolas, Monaco, monospace;
	font-weight: 600;
}
.doc-type {
	font-family: Consolas, Monaco, monospace;
	font-size: 12px;
	color: var(--el-color-success);
}
.doc-optional { color: var(--el-text-color-placeholder); font-size: 12px; }
.doc-in-badge {
	display: inline-block;
	padding: 1px 6px;
	border-radius: 3px;
	font-size: 11px;
	background: var(--el-fill-color);
	color: var(--el-text-color-regular);
}
.doc-in-badge.in-query { background: #ecf5ff; color: #409eff; }
.doc-in-badge.in-path { background: #fdf6ec; color: #e6a23c; }
.doc-in-badge.in-header { background: #f0f9eb; color: #67c23a; }
.doc-in-badge.in-cookie { background: #f4f4f5; color: #909399; }
.doc-response-item { margin-bottom: 14px; }
.doc-response-header {
	display: flex;
	align-items: center;
	gap: 10px;
}
.doc-response-desc { font-size: 13px; color: var(--el-text-color-regular); }
.doc-response-ct {
	margin-left: auto;
	font-size: 11px;
	color: var(--el-text-color-placeholder);
	font-family: Consolas, Monaco, monospace;
}
.doc-raw-schema {
	margin-top: 8px;
	background: var(--el-fill-color-lighter);
	border-radius: 4px;
	padding: 10px 12px;
	overflow: auto;
}
.doc-pre {
	margin: 0;
	font-family: Consolas, Monaco, monospace;
	font-size: 12px;
	line-height: 1.5;
	white-space: pre-wrap;
	word-break: break-all;
}
.doc-response-edit {
	padding: 10px;
	border: 1px solid var(--el-border-color-lighter);
	border-radius: 6px;
	margin-bottom: 12px;
}
.doc-response-edit-header {
	display: flex;
	align-items: center;
	gap: 8px;
}
.doc-empty, .doc-empty-hint {
	display: flex;
	flex-direction: column;
	align-items: center;
	justify-content: center;
	padding: 48px 20px;
	color: var(--el-text-color-placeholder);
	font-size: 13px;
}
.doc-empty-hint { padding: 16px; }
</style>
