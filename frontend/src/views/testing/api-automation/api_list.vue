<template>
	<div class="api-list-container">
		<el-card shadow="hover" :body-style="{ paddingBottom: '0' }">
			<el-form :inline="true" :model="searchParams" class="search-form">
				<el-form-item label="服务名称">
					<el-input
						v-model="searchParams.name"
						placeholder="请输入服务名称"
						clearable
						style="width: 180px"
						@keyup.enter="loadList"
					/>
				</el-form-item>
				<el-form-item label="业务线">
					<el-select
						v-model="searchParams.business_id"
						placeholder="请选择业务线"
						clearable
						style="width: 160px"
					>
						<el-option
							v-for="b in businessOptions"
							:key="b.id"
							:label="b.name"
							:value="b.id"
						/>
					</el-select>
				</el-form-item>
				<el-form-item label="负责人">
					<el-select
						v-model="searchParams.manager"
						placeholder="请选择负责人"
						clearable
						filterable
						style="width: 160px"
					>
						<el-option
							v-for="u in userOptions"
							:key="u.id"
							:label="u.username"
							:value="u.id"
						/>
					</el-select>
				</el-form-item>
				<el-form-item>
					<el-button type="primary" @click="handleSearch">
						<el-icon><ele-Search /></el-icon>
						搜索
					</el-button>
					<el-button @click="resetSearch">
						<el-icon><ele-Refresh /></el-icon>
						重置
					</el-button>
				</el-form-item>
			</el-form>
		</el-card>

		<el-card shadow="hover" style="margin-top: 8px">
			<el-row :gutter="10" style="margin-bottom: 8px">
				<el-col :span="1.5">
					<el-button type="primary" plain @click="openAddDialog">
						<el-icon><ele-Plus /></el-icon>
						新增
					</el-button>
				</el-col>
			</el-row>
			<el-table
				ref="tableRef"
				v-loading="loading"
				:data="tableData"
				border
				stripe
				empty-text="暂无数据"
				table-layout="auto"
				style="width: 100%"
				@row-dblclick="onRowDblClick"
			>
				<el-table-column width="40" align="center">
					<template #default>
						<span class="drag-handle" style="cursor: grab; color: #909399; font-size: 16px;">⠿</span>
					</template>
				</el-table-column>
				<el-table-column type="index" label="序号" width="60" align="center" />
				<el-table-column prop="name" label="服务名称" min-width="140" show-overflow-tooltip />
				<el-table-column prop="project_name" label="所属项目" min-width="120" show-overflow-tooltip />
				<el-table-column prop="manager_name" label="负责人" width="100" align="center" show-overflow-tooltip>
					<template #default="{ row }">
						{{ row.manager_name || '-' }}
					</template>
				</el-table-column>
				<el-table-column label="操作" width="200" align="center" fixed="right">
					<template #default="{ row }">
						<span class="action-cell">
							<el-button type="primary" size="small" plain @click.stop="openServiceDetail(row)">详情</el-button>
							<el-button type="warning" size="small" @click.stop="openEditDialog(row)">修改</el-button>
							<el-button type="danger" size="small" @click.stop="deleteService(row)">删除</el-button>
						</span>
					</template>
				</el-table-column>
			</el-table>

			<div style="margin-top: 12px">
				<el-pagination
					v-show="total > 0"
					background
					v-model:current-page="currentPage"
					v-model:page-size="pageSize"
					:page-sizes="[10, 20, 50, 100]"
					layout="total, sizes, prev, pager, next, jumper"
					:total="total"
					@size-change="loadList"
					@current-change="loadList"
				/>
			</div>
		</el-card>

		<!-- 新增/编辑对话框 -->
		<el-dialog
			v-model="dialogVisible"
			:title="isEdit ? '编辑服务' : '新增服务'"
			width="520px"
			@close="resetForm"
		>
			<el-form ref="formRef" :model="formData" :rules="formRules" label-width="100px">
				<el-form-item label="服务名称" prop="name">
					<el-input v-model="formData.name" placeholder="请输入服务名称" />
				</el-form-item>
				<el-form-item label="所属项目" prop="api_project_id">
					<el-select v-model="formData.api_project_id" placeholder="请选择项目" style="width: 100%">
						<el-option
							v-for="p in projectOptions"
							:key="p.id"
							:label="p.name"
							:value="p.id"
						/>
					</el-select>
				</el-form-item>
				<el-form-item label="负责人">
					<el-select v-model="formData.manager" placeholder="请选择负责人" clearable filterable style="width: 100%">
						<el-option
							v-for="u in userOptions"
							:key="u.id"
							:label="u.username"
							:value="u.id"
						/>
					</el-select>
				</el-form-item>
			</el-form>
			<template #footer>
				<el-button @click="dialogVisible = false">取消</el-button>
				<el-button type="primary" :loading="submitting" @click="submitForm">确定</el-button>
			</template>
		</el-dialog>
			<!-- 环境管理（新版 EnvManageCenter） -->
	<EnvManageCenter ref="envCenterRef" :service-id="curEnvServiceId" />
	</div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import type { FormInstance, FormRules } from 'element-plus';
import Sortable from 'sortablejs';
import EnvManageCenter from './components/EnvManageCenter.vue';
import { useApiAutomationApi } from '/@/api/v1/testing/apiAutomation';
import { useUserApi } from '/@/api/v1/system/user';
import { useProjectApi } from '/@/api/v1/projects/project';

const emit = defineEmits<{
	(e: 'select-service', service: {
		id: number;
		name: string;
		source_type?: string;
		source_addr?: string;
	}): void;
}>();

const {
	api_service,
	add_api_service,
	edit_api_service,
	del_api_service,
	pull_api_doc,
	api_service_sort,
} = useApiAutomationApi();

const { getList: getUserList } = useUserApi();
const { getList: getProjectList } = useProjectApi();

// ---- 列表状态 ----
const loading = ref(false);
const tableData = ref<any[]>([]);
const total = ref(0);
const currentPage = ref(1);
const pageSize = ref(20);
const searchParams = reactive({ name: '', business_id: null as number | null, manager: null as number | null });

// ---- 拖拽排序 ----
const tableRef = ref<any>(null);
let sortableInstance: Sortable | null = null;

const initSortable = () => {
	if (sortableInstance) {
		sortableInstance.destroy();
		sortableInstance = null;
	}
	const el = tableRef.value?.$el?.querySelector('.el-table__body tbody');
	if (!el) return;
	sortableInstance = Sortable.create(el, {
		handle: '.drag-handle',
		animation: 150,
		onEnd: async ({ newIndex, oldIndex }) => {
			if (newIndex === undefined || oldIndex === undefined || newIndex === oldIndex) return;
			const moved = tableData.value.splice(oldIndex, 1)[0];
			tableData.value.splice(newIndex, 0, moved);
			try {
				await api_service_sort({ ids: tableData.value.map((r: any) => r.id) });
			} catch (e: any) {
				ElMessage.error(e?.message || '排序保存失败');
			}
		},
	});
};

// ---- 筛选选项 ----
const userOptions = ref<any[]>([]);
const businessOptions = ref<any[]>([]);

const loadFilterOptions = async () => {
	// 负责人下拉：项目成员并集（未加入任何项目的用户不显示）
	try {
		const projectApi = useProjectApi();
		const seen = new Set<number>();
		const members: any[] = [];
		for (const p of projectOptions.value || []) {
			try {
				const mr: any = await projectApi.getMemberList(p.id);
				if (mr?.code === 200 && Array.isArray(mr.data)) {
					for (const m of mr.data) {
						const uid = Number(m.user_id ?? m.id ?? 0);
						if (uid && !seen.has(uid)) {
							seen.add(uid);
							members.push({ id: uid, username: m.username || String(uid) });
						}
					}
				}
			} catch {}
		}
		userOptions.value = members;
	} catch {
		userOptions.value = [];
	}
	// 业务线暂无独立接口，保持空列表（可后续扩展）
	businessOptions.value = [];
};

// ---- 拉取状态 ----
const pullingIds = ref<Set<number>>(new Set());

const pullStatusMeta = (status: number | null | undefined) => {
	switch (status) {
		case 1: return { text: '成功', type: 'success' as const };
		case 2: return { text: '失败', type: 'danger' as const };
		default: return { text: '未拉取', type: 'info' as const };
	}
};

// ---- 项目选项 ----
const projectOptions = ref<any[]>([]);

const loadProjects = async () => {
	try {
		const res: any = await getProjectList({ page: 1, page_size: 100 });
		const raw = res?.data;
		projectOptions.value = Array.isArray(raw?.items) ? raw.items
			: Array.isArray(raw?.content) ? raw.content
			: Array.isArray(raw) ? raw : [];
	} catch {
		projectOptions.value = [];
	}
};

// ---- 加载列表 ----
const loadList = async () => {
	loading.value = true;
	// 确保用户列表已加载，用于显示负责人名称
	if (!userOptions.value.length) await loadFilterOptions();
	try {
		const res: any = await api_service({
			page: currentPage.value,
			pageSize: pageSize.value,
			search: {
				name: searchParams.name || undefined,
				manager: searchParams.manager ?? undefined,
				business_id: searchParams.business_id ?? undefined,
			},
		});
		const raw = res?.data;
		const list = Array.isArray(raw?.content) ? raw.content : (Array.isArray(raw) ? raw : []);
		// 补充项目名称和负责人名称
		tableData.value = list.map((item: any) => ({
			...item,
			project_name: item.project_name || item.api_project?.name || projectOptions.value.find((p: any) => p.id === item.api_project_id)?.name || '-',
			manager_name: item.manager_name || userOptions.value.find((u: any) => u.id === item.manager)?.username || (item.manager ? String(item.manager) : '-'),
		}));
		total.value = typeof raw?.total === 'number' ? raw.total : list.length;
	} finally {
		loading.value = false;
	}
	await nextTick();
	initSortable();
};

const handleSearch = () => {
	currentPage.value = 1;
	loadList();
};

const resetSearch = () => {
	searchParams.name = '';
	searchParams.business_id = null;
	searchParams.manager = null;
	currentPage.value = 1;
	loadList();
};

// ---- 双击行进入详情 ----
const openServiceDetail = (row: any) => {
	emit('select-service', {
		id: row.id,
		name: row.name,
		source_type: row.source_type || '',
		source_addr: row.source_addr || '',
	});
};

const onRowDblClick = (row: any) => {
	openServiceDetail(row);
};

// ---- 拉取文档 ----
const pullDoc = async (row: any) => {
	pullingIds.value.add(row.id);
	try {
		await pull_api_doc({
			api_service_id: row.id,
			source_type: row.source_type || 'swagger',
			doc_url: row.source_addr,
		});
		ElMessage.success('拉取成功');
		await loadList();
	} catch (e: any) {
		ElMessage.error(e?.message || '拉取失败');
		await loadList();
	} finally {
		pullingIds.value.delete(row.id);
	}
};

// ---- 删除服务 ----
const deleteService = async (row: any) => {
	try {
		await ElMessageBox.confirm(`确认删除服务「${row.name}」？该操作不可恢复。`, '提示', {
			type: 'warning',
			confirmButtonText: '确定',
			cancelButtonText: '取消',
		});
		await del_api_service({ id: row.id });
		ElMessage.success('删除成功');
		await loadList();
	} catch (e: any) {
		if (e === 'cancel' || e === 'close') return;
		ElMessage.error(e?.message || '删除失败');
	}
};

// ---- 新增/编辑对话框 ----
const dialogVisible = ref(false);
const isEdit = ref(false);
const submitting = ref(false);
const formRef = ref<FormInstance>();

const formData = reactive({
	id: 0,
	name: '',
	api_project_id: null as number | null,
	source_type: '',
	source_addr: '',
	manager: null as number | null,
});

const formRules: FormRules = {
	name: [{ required: true, message: '请输入服务名称', trigger: 'blur' }],
	api_project_id: [{ required: true, message: '请选择所属项目', trigger: 'change' }],
};

const openAddDialog = async () => {
	isEdit.value = false;
	formData.id = 0;
	formData.name = '';
	formData.api_project_id = null;
	formData.source_type = '';
	formData.source_addr = '';
	formData.manager = null;
	dialogVisible.value = true;
	if (!projectOptions.value.length) await loadProjects();
};

const openEditDialog = async (row: any) => {
	isEdit.value = true;
	formData.id = row.id;
	formData.name = row.name;
	formData.api_project_id = row.api_project_id;
	formData.source_type = row.source_type || '';
	formData.source_addr = row.source_addr || '';
	formData.manager = row.manager ?? null;
	dialogVisible.value = true;
	if (!projectOptions.value.length) await loadProjects();
};

const resetForm = () => {
	formData.id = 0;
	formData.name = '';
	formData.api_project_id = null;
	formData.source_type = '';
	formData.source_addr = '';
	formData.manager = null;
	formRef.value?.clearValidate();
};

const submitForm = async () => {
	const valid = await formRef.value?.validate().catch(() => false);
	if (!valid) return;
	submitting.value = true;
	try {
		if (isEdit.value) {
			await edit_api_service({
				id: formData.id,
				name: formData.name,
				api_project_id: formData.api_project_id!,
				manager: formData.manager ?? undefined,
			} as any);
			ElMessage.success('修改成功');
		} else {
			await add_api_service({
				name: formData.name,
				api_project_id: formData.api_project_id!,
				manager: formData.manager ?? undefined,
			} as any);
			ElMessage.success('新增成功');
		}
		dialogVisible.value = false;
		await loadList();
	} catch (e: any) {
		ElMessage.error(e?.message || '操作失败');
	} finally {
		submitting.value = false;
	}
};

// ---- 环境管理（EnvManageCenter）----
const envCenterRef = ref<any>(null);
const curEnvServiceId = ref<number | undefined>(undefined);

const openEnvCenter = (row: any) => {
	curEnvServiceId.value = row?.id || undefined;
	setTimeout(() => envCenterRef.value?.open?.(), 30);
};

onMounted(async () => {
	await Promise.all([loadProjects(), loadFilterOptions()]);
	await loadList();
});

onUnmounted(() => {
	if (sortableInstance) {
		sortableInstance.destroy();
		sortableInstance = null;
	}
});
</script>

<style scoped>
.api-list-container {
	padding: 10px;
}

.search-form :deep(.el-form-item) {
	margin-right: 12px;
	margin-bottom: 12px;
}

.action-cell {
	white-space: nowrap;
}
</style>
