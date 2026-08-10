import request from '/@/utils/request';

/**
 * AI 测试任务中心 API
 * 多 Agent 流水线任务：需求分析 → 用例生成 → 执行 → 评审
 * 注意：平台 request 封装 baseURL 已含 /api 前缀（VITE_API_PREFIX），路径统一写 /v1/...
 */
export const useAgentTaskApi = () => ({
	// 任务列表（分页）
	getTaskList: (params: any) =>
		request.get('/v1/Ntesterc_agent/tasks', { params }),

	// 任务详情（含产物）
	getTaskDetail: (taskId: number) =>
		request.get(`/v1/Ntesterc_agent/tasks/${taskId}`),

	// 创建任务
	createTask: (data: any) =>
		request.post('/v1/Ntesterc_agent/tasks', data),

	// 更新任务
	updateTask: (taskId: number, data: any) =>
		request.put(`/v1/Ntesterc_agent/tasks/${taskId}`, data),

	// 确认执行（HITL 通过）
	confirmTask: (taskId: number) =>
		request.post(`/v1/Ntesterc_agent/tasks/${taskId}/confirm`),

	// 驳回用例（HITL 拒绝）
	rejectTask: (taskId: number) =>
		request.post(`/v1/Ntesterc_agent/tasks/${taskId}/reject`),

	// 重跑任务
	rerunTask: (taskId: number) =>
		request.post(`/v1/Ntesterc_agent/tasks/${taskId}/rerun`),

	// 删除任务
	deleteTask: (taskId: number) =>
		request.delete(`/v1/Ntesterc_agent/tasks/${taskId}`),
});
