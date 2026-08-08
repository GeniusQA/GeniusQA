/**
 * UI自动化测试模块接口
 */
import request from '/@/utils/request'
import axios from 'axios'
import { getApiBaseUrl } from '/@/utils/config'
import { Session } from '/@/utils/storage'

export function useUiAutomationApi() {
  const uiProjectApi = {
    create: (data: any) => request.post('/v1/Ntesterc_ui/projects', data),
    list: (params: any) => request.get('/v1/Ntesterc_ui/projects', { params }),
    get: (id: number) => request.get(`/v1/Ntesterc_ui/projects/${id}`),
    update: (id: number, data: any) => request.put(`/v1/Ntesterc_ui/projects/${id}`, data),
    delete: (id: number) => request.delete(`/v1/Ntesterc_ui/projects/${id}`),
    generateCode: (id: number, data: any) => request.post(`/v1/Ntesterc_ui/projects/${id}/generate-code`, data)
  }

  const uiElementGroupApi = {
    create: (data: any) => request.post('/v1/Ntesterc_ui/element-groups', data),
    tree: (uiProjectId: number) => request.get('/v1/Ntesterc_ui/element-groups/tree', { params: { ui_project_id: uiProjectId } }),
    update: (id: number, data: any) => request.put(`/v1/Ntesterc_ui/element-groups/${id}`, data),
    delete: (id: number) => request.delete(`/v1/Ntesterc_ui/element-groups/${id}`)
  }

  const uiElementApi = {
    create: (data: any) => request.post('/v1/Ntesterc_ui/elements', data),
    list: (params: any) => request.get('/v1/Ntesterc_ui/elements', { params }),
    get: (id: number) => request.get(`/v1/Ntesterc_ui/elements/${id}`),
    update: (id: number, data: any) => request.put(`/v1/Ntesterc_ui/elements/${id}`, data),
    delete: (id: number) => request.delete(`/v1/Ntesterc_ui/elements/${id}`),
    validateLocator: (data: any) => request.post('/v1/Ntesterc_ui/elements/validate-locator', data),
    suggestLocator: (data: any) => request.post('/v1/Ntesterc_ui/elements/suggest-locator', data)
  }

  const uiPageObjectApi = {
    create: (data: any) => request.post('/v1/Ntesterc_ui/page-objects', data),
    list: (params: any) => request.get('/v1/Ntesterc_ui/page-objects', { params }),
    get: (id: number) => request.get(`/v1/Ntesterc_ui/page-objects/${id}`),
    update: (id: number, data: any) => request.put(`/v1/Ntesterc_ui/page-objects/${id}`, data),
    delete: (id: number) => request.delete(`/v1/Ntesterc_ui/page-objects/${id}`),
    generateCode: (id: number, data: any) => request.post(`/v1/Ntesterc_ui/page-objects/${id}/generate-code`, data),
    previewCode: (id: number, params: any) => request.get(`/v1/Ntesterc_ui/page-objects/${id}/preview-code`, { params })
  }

  const uiTestCaseApi = {
    create: (data: any) => request.post('/v1/Ntesterc_ui/test-cases', data),
    list: (params: any) => request.get('/v1/Ntesterc_ui/test-cases', { params }),
    get: (id: number) => request.get(`/v1/Ntesterc_ui/test-cases/${id}`),
    update: (id: number, data: any) => request.put(`/v1/Ntesterc_ui/test-cases/${id}`, data),
    delete: (id: number) => request.delete(`/v1/Ntesterc_ui/test-cases/${id}`),
    execute: (id: number, data: any) => request.post(`/v1/Ntesterc_ui/test-cases/${id}/execute`, data),
    batchExecute: (data: any) => request.post('/v1/Ntesterc_ui/test-cases/batch-execute', data),
    generateCode: (id: number, data: any) => request.post(`/v1/Ntesterc_ui/test-cases/${id}/generate-code`, data)
  }

  const uiTestStepApi = {
    listByCase: (testCaseId: number) => request.get(`/v1/Ntesterc_ui/test-cases/${testCaseId}/steps`),
    create: (data: any) => request.post('/v1/Ntesterc_ui/test-steps', data),
    batchCreate: (data: any) => request.post('/v1/Ntesterc_ui/test-steps/batch', data),
    update: (id: number, data: any) => request.put(`/v1/Ntesterc_ui/test-steps/${id}`, data),
    delete: (id: number) => request.delete(`/v1/Ntesterc_ui/test-steps/${id}`),
    reorder: (data: any) => request.put('/v1/Ntesterc_ui/test-steps/reorder', data)
  }

  const uiTestSuiteApi = {
    create: (data: any) => request.post('/v1/Ntesterc_ui/test-suites', data),
    list: (params: any) => request.get('/v1/Ntesterc_ui/test-suites', { params }),
    get: (id: number) => request.get(`/v1/Ntesterc_ui/test-suites/${id}`),
    update: (id: number, data: any) => request.put(`/v1/Ntesterc_ui/test-suites/${id}`, data),
    delete: (id: number) => request.delete(`/v1/Ntesterc_ui/test-suites/${id}`),
    execute: (id: number, data: any) => request.post(`/v1/Ntesterc_ui/test-suites/${id}/execute`, data),
    batchExecute: (data: any) => request.post('/v1/Ntesterc_ui/test-suites/batch-execute', data)
  }

  const uiExecutionApi = {
    list: (params: any) => request.get('/v1/Ntesterc_ui/executions', { params }),
    get: (id: number) => request.get(`/v1/Ntesterc_ui/executions/${id}`),
    getStatus: (id: number) => request.get(`/v1/Ntesterc_ui/executions/${id}/status`),
    getLogs: (id: number) => request.get(`/v1/Ntesterc_ui/executions/${id}/logs`),
    stop: (id: number) => request.post(`/v1/Ntesterc_ui/executions/${id}/stop`),
    delete: (id: number) => request.delete(`/v1/Ntesterc_ui/executions/${id}`),
    statistics: (params: any) => request.get('/v1/Ntesterc_ui/executions/statistics', { params }),
    export: async (id: number, params: any) => {
      const service = axios.create({
        baseURL: getApiBaseUrl(),
        timeout: 50000,
      })
      const token = Session.get('token')
      const headers: any = { Accept: 'text/html' }
      if (token) {
        headers['Authorization'] = `Bearer ${token}`
        headers['token'] = token
      }
      const response = await service.get(`/v1/Ntesterc_ui/executions/${id}/export`, {
        params,
        responseType: 'text',
        headers
      })
      return { data: response.data }
    }
  }

  const uiBrowserApi = {
    check: (browserType: string) => request.get('/v1/Ntesterc_ui/browsers/check', { params: { browser_type: browserType } }),
    checkAll: () => request.get('/v1/Ntesterc_ui/browsers/check-all'),
    checkPlaywright: (browserType: string, headless = true) => request.get('/v1/Ntesterc_ui/browsers/check-playwright', { params: { browser_type: browserType, headless } }),
    getCustomPaths: () => request.get('/v1/Ntesterc_ui/browsers/custom-paths'),
    saveCustomPath: (data: any) => request.post('/v1/Ntesterc_ui/browsers/custom-paths', data),
    deleteCustomPath: (browserType: string) => request.delete(`/v1/Ntesterc_ui/browsers/custom-paths/${browserType}`),
    verifyCustomPath: (data: any) => request.post('/v1/Ntesterc_ui/browsers/verify-custom-path', data),
  }

  const uiRecordApi = {
    start: (uiProjectId: number, data: any) => request.post(`/v1/Ntesterc_ui/projects/${uiProjectId}/record/start`, data),
    stop: (sessionId: number) => request.post(`/v1/Ntesterc_ui/record/${sessionId}/stop`),
    steps: (sessionId: number) => request.get(`/v1/Ntesterc_ui/record/${sessionId}/steps`),
    pause: (sessionId: number) => request.post(`/v1/Ntesterc_ui/record/${sessionId}/pause`),
    resume: (sessionId: number) => request.post(`/v1/Ntesterc_ui/record/${sessionId}/resume`),
    assertMode: (sessionId: number, data: any) => request.post(`/v1/Ntesterc_ui/record/${sessionId}/assert-mode`, data),
    pick: (sessionId: number) => request.post(`/v1/Ntesterc_ui/record/${sessionId}/pick`),
    getPick: (sessionId: number) => request.get(`/v1/Ntesterc_ui/record/${sessionId}/pick`),
    importCodegen: (data: any) => request.post('/v1/Ntesterc_ui/record/import-codegen', data),
    importSide: (data: any) => request.post('/v1/Ntesterc_ui/record/import-side', data)
  }

  return {
    uiProjectApi,
    uiElementGroupApi,
    uiElementApi,
    uiPageObjectApi,
    uiTestCaseApi,
    uiTestStepApi,
    uiTestSuiteApi,
    uiExecutionApi,
    uiBrowserApi,
    uiRecordApi,
  }
}

export const uiAutomationApi = useUiAutomationApi()
export const {
  uiProjectApi,
  uiElementGroupApi,
  uiElementApi,
  uiPageObjectApi,
  uiTestCaseApi,
  uiTestStepApi,
  uiTestSuiteApi,
  uiExecutionApi,
  uiBrowserApi,
  uiRecordApi,
} = uiAutomationApi
