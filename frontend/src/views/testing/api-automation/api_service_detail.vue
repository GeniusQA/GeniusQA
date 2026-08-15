<template>
	<div class="service-detail-container">
		<!-- 顶部操作栏 -->
		<div class="service-detail-header">
			<div class="header-left">
				<el-button type="primary" plain size="small" @click="emit('back')">
					<el-icon><ele-ArrowLeft /></el-icon>
					返回接口列表
				</el-button>
				<span class="service-name">{{ serviceName }}</span>
			</div>
			<div class="header-right">
				<el-select
					ref="envSelectRef"
					v-model="selectedEnvId"
					placeholder="请选择环境"
					clearable
					style="width: 180px"
				>
					<el-option
						v-for="env in envList"
						:key="env.id"
						:label="env.name"
						:value="env.id"
					/>
					<template #footer>
						<div class="env-manage-entry" @click.stop="openEnvCenter">
							<el-icon><Setting /></el-icon>
							<span>管理环境</span>
						</div>
					</template>
				</el-select>
			</div>
		</div>

		<!-- Tab 区域 -->
		<el-tabs v-model="activeTab" type="border-card" class="service-detail-tabs">
			<el-tab-pane label="接口管理" name="manage">
				<ApiManagePanel
					:serviceId="currentServiceId"
					:envId="selectedEnvId"
					:envList="envList"
					:sourceType="sourceType"
					:sourceAddr="sourceAddr"
					@update-source="(p) => emit('update-source', p)"
				/>
			</el-tab-pane>
			<el-tab-pane label="用例管理" name="case">
				<ApiCaseManagement :serviceId="currentServiceId" :envId="selectedEnvId" />
			</el-tab-pane>
			<el-tab-pane label="脚本中心" name="script">
				<ScriptCenter :serviceId="currentServiceId" />
			</el-tab-pane>
			<el-tab-pane label="数据查询" name="querydb">
				<QueryDbTab ref="queryDbRef" :serviceId="currentServiceId" />
			</el-tab-pane>
			<el-tab-pane label="代码覆盖率" name="precision">
				<PrecisionTestTab :serviceId="currentServiceId" />
			</el-tab-pane>
			<el-tab-pane label="执行结果" name="result">
				<ApiResultList :serviceId="currentServiceId" />
			</el-tab-pane>
			<el-tab-pane label="代码生成" name="codegen">
				<ApiCodegen />
			</el-tab-pane>
		</el-tabs>

		

		<EnvManageCenter ref="envCenterRef" :service-id="currentServiceId" />
	</div>
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useApiAutomationApi } from '/@/api/v1/testing/apiAutomation';
import { Local } from '/@/utils/storage';
import ApiManagePanel from './ApiManagePanel.vue';
import EnvManageCenter from './components/EnvManageCenter.vue';
import ApiResultList from './api_result_list.vue';
import ApiCodegen from './api_codegen.vue';
import ScriptCenter from './ScriptCenter.vue';
import QueryDbTab from './QueryDbTab.vue';

// api_case_management.vue will be created in task 9 - use async import with fallback
const ApiCaseManagement = defineAsyncComponent({
	loader: () => import('./api_case_management.vue'),
	errorComponent: {
		template: '<div style="padding: 20px; color: #909399;">用例管理组件加载中，请稍后...</div>',
	},
	delay: 200,
	timeout: 5000,
});

const PrecisionTestTab = defineAsyncComponent({
	loader: () => import('/@/views/testing/precision-test/PrecisionTestTab.vue'),
	errorComponent: {
		template: '<div style="padding: 20px; color: #909399;">覆盖率测试组件加载中，请稍后...</div>',
	},
	delay: 200,
	timeout: 5000,
});
const props = defineProps<{
	serviceId: number;
	serviceName: string;
	sourceType?: string;
	sourceAddr?: string;
}>();

const emit = defineEmits<{
	(e: 'back'): void;
	(e: 'update-source', payload: { source_type?: string; source_addr?: string }): void;
}>();

const activeTab = ref<'manage' | 'case' | 'script' | 'querydb' | 'precision' | 'result' | 'codegen'>('manage');
const selectedEnvId = ref<number | null>(null);
const queryDbRef = ref<InstanceType<typeof QueryDbTab> | null>(null);

const envStorageKey = (serviceId: number) => `api_automation:last_env_id:${serviceId}`;

const readLastEnvId = (serviceId: number): number | null => {
	try {
		const raw = Local.get(envStorageKey(serviceId));
		const n = Number(raw);
		return Number.isFinite(n) && n > 0 ? n : null;
	} catch {
		return null;
	}
};

const writeLastEnvId = (serviceId: number, envId: number | null) => {
	const key = envStorageKey(serviceId);
	if (envId == null || Number(envId) <= 0) {
		Local.remove(key);
		return;
	}
	Local.set(key, Number(envId));
};

const restoreSelectedEnv = () => {
	const lastId = readLastEnvId(currentServiceId.value);
	if (lastId == null) {
		selectedEnvId.value = null;
		return;
	}
	
	if (!envList.value.length) {
		selectedEnvId.value = lastId;
		return;
	}
	const exists = envList.value.some((e) => Number(e.id) === lastId);
	selectedEnvId.value = exists ? lastId : null;
	if (!exists) writeLastEnvId(currentServiceId.value, null);
};

watch(activeTab, (tab) => {
	if (tab === 'querydb') queryDbRef.value?.reloadDbList?.();
});

watch(selectedEnvId, (id) => {
	writeLastEnvId(currentServiceId.value, id);
});

const currentServiceId = ref<number>(props.serviceId);

watch(
	() => props.serviceId,
	(id) => {
		currentServiceId.value = id;
		restoreSelectedEnv();
	}
);

const { api_env } = useApiAutomationApi();

// ---- 环境列表 ----
const envList = ref<any[]>([]);
const envLoading = ref(false);
const envCenterRef = ref<any>(null);
const envSelectRef = ref<any>(null);
const openEnvCenter = () => {
	envSelectRef.value?.blur();
	envCenterRef.value?.open();
};

const filteredEnvList = computed(() =>
	envSearchName.value
		? envList.value.filter((e) => e.name?.includes(envSearchName.value))
		: envList.value
);



const loadEnvList = async () => {
	envLoading.value = true;
	try {
		const res: any = await api_env();
		const raw = res?.data;
		envList.value = Array.isArray(raw) ? raw : (Array.isArray(raw?.content) ? raw.content : []);
		restoreSelectedEnv();
	} catch {
		envList.value = [];
	} finally {
		envLoading.value = false;
	}
};

onMounted(() => {
	loadEnvList();
});
</script>

<style scoped>
.env-manage-entry {
	display: flex;
	align-items: center;
	justify-content: center;
	gap: 6px;
	padding: 9px 12px;
	border-top: 1px solid #e5e7eb;
	color: #7c3aed;
	font-size: 13px;
	line-height: 1;
	cursor: pointer;
}
.env-manage-entry .el-icon {
	display: inline-flex;
	align-items: center;
	justify-content: center;
}
.env-manage-entry:hover {
	background: #f3f4f6;
}

.service-detail-container {
	display: flex;
	flex-direction: column;
	height: 100%;
	padding: 10px;
}

.service-detail-header {
	display: flex;
	align-items: center;
	justify-content: space-between;
	margin-bottom: 8px;
	gap: 12px;
}

.header-left {
	display: flex;
	align-items: center;
	gap: 8px;
	min-width: 0;
	flex: 1;
}

.service-name {
	font-size: 16px;
	font-weight: 600;
	color: #303133;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}

.header-right {
	display: flex;
	align-items: center;
	gap: 8px;
	flex-shrink: 0;
}

.header-right :deep(.el-button + .el-button) {
	margin-left: 0;
}

.service-detail-tabs {
	flex: 1;
	display: flex;
	flex-direction: column;
	min-height: 0;
}

.service-detail-tabs :deep(.el-tabs__content) {
	flex: 1;
	min-height: 0;
	overflow: hidden;
	padding: 0 !important;
}

.service-detail-tabs :deep(.el-tab-pane) {
	height: 100%;
	overflow: hidden;
}

/* 恢复内层 apifox-tabs 的 padding，避免被外层 !important 覆盖 */
.service-detail-tabs :deep(.apifox-tabs .el-tabs__content) {
	padding: 10px 12px !important;
	overflow-y: auto !important;
}
</style>
