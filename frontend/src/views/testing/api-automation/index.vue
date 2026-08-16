<template>
	<div class="api-automation-root">
		<ApiList v-if="currentService === null" @select-service="onSelectService" />
		<ApiServiceDetail
			v-else
			:serviceId="currentService.id"
			:serviceName="currentService.name"
			:sourceType="currentService.source_type"
			:sourceAddr="currentService.source_addr"
			@back="onBack"
			@update-source="onUpdateSource"
		/>
	</div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import ApiList from './api_list.vue';
import ApiServiceDetail from './api_service_detail.vue';

type ServiceInfo = {
	id: number;
	name: string;
	source_type?: string;
	source_addr?: string;
};

const currentService = ref<ServiceInfo | null>(null);

const route = useRoute();
const router = useRouter();

function onSelectService(service: ServiceInfo) {
	currentService.value = {
		id: service.id,
		name: service.name,
		source_type: service.source_type || '',
		source_addr: service.source_addr || '',
	};
	// URL 持久化：刷新后停留在当前第二层级页面
	router.replace({
		query: {
			...route.query,
			serviceId: String(service.id),
			serviceName: service.name,
			sourceType: service.source_type || '',
			sourceAddr: service.source_addr || '',
		},
	});
}

function onUpdateSource(payload: { source_type?: string; source_addr?: string }) {
	if (!currentService.value) return;
	currentService.value = {
		...currentService.value,
		...(payload.source_type !== undefined ? { source_type: payload.source_type } : {}),
		...(payload.source_addr !== undefined ? { source_addr: payload.source_addr } : {}),
	};
}

function onBack() {
	currentService.value = null;
	const q = { ...route.query };
	delete q.serviceId;
	delete q.serviceName;
	delete q.sourceType;
	delete q.sourceAddr;
	router.replace({ query: q });
}

onMounted(() => {
	// 刷新恢复：URL 带 serviceId 时直接停留在第二层级（服务详情）
	const sid = route.query.serviceId;
	if (sid) {
		currentService.value = {
			id: Number(sid),
			name: String(route.query.serviceName || ''),
			source_type: String(route.query.sourceType || ''),
			source_addr: String(route.query.sourceAddr || ''),
		};
	}
});
</script>

<style scoped>
.api-automation-root {
	position: absolute;
	inset: 0;
	display: flex;
	flex-direction: column;
	overflow: hidden;
}
</style>
