/**
 * 统一通知系统API接口
 */
import request from '/@/utils/request';

// 通知配置相关接口
export interface NotificationConfig {
  id?: number
  name: string
  config_type: 'webhook_feishu' | 'webhook_wechat' | 'webhook_dingtalk' | 'telegram' | 'email'
  notification_config: Record<string, any>
  is_default: boolean
  is_active: boolean
  creation_date?: string
  created_by?: number
}

export interface NotificationConfigCreate {
  name: string
  config_type: 'webhook_feishu' | 'webhook_wechat' | 'webhook_dingtalk' | 'telegram' | 'email'
  notification_config: Record<string, any>
  is_default?: boolean
  is_active?: boolean
}

export interface NotificationConfigUpdate {
  name?: string
  config_type?: 'webhook_feishu' | 'webhook_wechat' | 'webhook_dingtalk' | 'telegram' | 'email'
  notification_config?: Record<string, any>
  is_default?: boolean
  is_active?: boolean
}

// 通知历史相关接口
export interface NotificationHistory {
  id: number
  config_id: number
  title: string
  content: string
  recipient?: string
  status: 'pending' | 'success' | 'failed'
  error_message?: string
  sent_at?: number
  response_data?: Record<string, any>
  creation_date: string
}

// 任务通知设置相关接口
export interface TaskNotificationSetting {
  id?: number
  task_id: number
  task_type: 'APP' | 'WEB_UI' | 'API'
  notification_config_id: number
  is_enabled: boolean
  notify_on_success: boolean
  notify_on_failure: boolean
  creation_date?: string
}

export interface TaskNotificationSettingCreate {
  task_id: number
  task_type: 'APP' | 'WEB_UI' | 'API'
  notification_config_id: number
  is_enabled?: boolean
  notify_on_success?: boolean
  notify_on_failure?: boolean
}

export interface TaskNotificationSettingUpdate {
  notification_config_id?: number
  is_enabled?: boolean
  notify_on_success?: boolean
  notify_on_failure?: boolean
}

// 发送通知相关接口
export interface SendNotificationRequest {
  config_id: number
  title: string
  content: string
  recipient?: string
}

export interface SendNotificationResponse {
  success: boolean
  message: string
  history_id?: number
}

// 通知配置管理API
export function useNotificationConfigApi() {
  return {
  // 获取配置列表
  getConfigs: (params?: {
    config_type?: string
    is_active?: boolean
    skip?: number
    limit?: number
  }) => {
    return request({
      url: '/v1/Ntesterc_notifications/configs',
      method: 'GET',
      params
    })
  },

  // 获取配置详情
  getConfig: (id: number) => {
    return request({
      url: `/v1/Ntesterc_notifications/configs/${id}`,
      method: 'GET'
    })
  },

  // 创建配置
  createConfig: (data: NotificationConfigCreate) => {
    return request({
      url: '/v1/Ntesterc_notifications/configs',
      method: 'POST',
      data
    })
  },

  // 更新配置
  updateConfig: (id: number, data: NotificationConfigUpdate) => {
    return request({
      url: `/v1/Ntesterc_notifications/configs/${id}`,
      method: 'PUT',
      data
    })
  },

  // 删除配置
  deleteConfig: (id: number) => {
    return request({
      url: `/v1/Ntesterc_notifications/configs/${id}`,
      method: 'DELETE'
    })
  },

  // 批量删除配置
  batchDeleteConfigs: (ids: number[]) => {
    return request({
      url: '/v1/Ntesterc_notifications/configs',
      method: 'DELETE',
      data: { ids }
    })
  },

  // 设置默认配置
  setDefaultConfig: (id: number) => {
    return request({
      url: `/v1/Ntesterc_notifications/configs/${id}/set-default`,
      method: 'POST'
    })
  },

  // 测试配置
  testConfig: (id: number) => {
    return request({
      url: `/v1/Ntesterc_notifications/configs/${id}/test`,
      method: 'POST'
    })
  }
  }
}

// 通知历史管理API
export function useNotificationHistoryApi() {
  return {
  // 获取通知历史
  getHistories: (params?: {
    config_id?: number
    status?: string
    days?: number
    skip?: number
    limit?: number
  }) => {
    return request({
      url: '/v1/Ntesterc_notifications/histories',
      method: 'GET',
      params
    })
  },

  // 删除通知历史记录
  deleteHistory: (id: number) => {
    return request({
      url: `/v1/Ntesterc_notifications/histories/${id}`,
      method: 'DELETE'
    })
  },

  // 批量删除通知历史记录
  batchDeleteHistories: (ids: number[]) => {
    return request({
      url: '/v1/Ntesterc_notifications/histories',
      method: 'DELETE',
      data: { ids }
    })
  }
  }
}

// 任务通知设置API
export function useTaskNotificationApi() {
  return {
  // 获取任务通知设置
  getTaskSettings: (params?: {
    task_id?: number
    task_type?: string
    notification_config_id?: number
    skip?: number
    limit?: number
  }) => {
    return request({
      url: '/v1/Ntesterc_notifications/task-settings',
      method: 'GET',
      params
    })
  },

  // 创建任务通知设置
  createTaskSetting: (data: TaskNotificationSettingCreate) => {
    return request({
      url: '/v1/Ntesterc_notifications/task-settings',
      method: 'POST',
      data
    })
  },

  // 更新任务通知设置
  updateTaskSetting: (id: number, data: TaskNotificationSettingUpdate) => {
    return request({
      url: `/v1/Ntesterc_notifications/task-settings/${id}`,
      method: 'PUT',
      data
    })
  },

  // 删除任务通知设置
  deleteTaskSetting: (id: number) => {
    return request({
      url: `/v1/Ntesterc_notifications/task-settings/${id}`,
      method: 'DELETE'
    })
  },

  // 批量删除任务通知设置
  batchDeleteTaskSettings: (ids: number[]) => {
    return request({
      url: '/v1/Ntesterc_notifications/task-settings',
      method: 'DELETE',
      data: { ids }
    })
  }
  }
}

// 发送通知API
export function useNotificationSendApi() {
  return {
  // 发送通知
  sendNotification: (data: SendNotificationRequest) => {
    return request({
      url: '/v1/Ntesterc_notifications/send',
      method: 'POST',
      data
    })
  },

  // 获取支持的通知类型
  getNotificationTypes: () => {
    return request({
      url: '/v1/Ntesterc_notifications/types',
      method: 'GET'
    })
  }
  }
}

// import 后可移除
export const notificationConfigApi = useNotificationConfigApi()
export const notificationHistoryApi = useNotificationHistoryApi()
export const taskNotificationApi = useTaskNotificationApi()
export const notificationSendApi = useNotificationSendApi()