import request from '/@/utils/request';

/**
 * Web 管理模块 API
 */
export function useWebManagementApi() {
  return {
    

    // 获取元素菜单树
    element_tree: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web_element/element_tree',
        method: 'POST',
        data,
      });
    },

    // 新增元素菜单
    add_element_menu: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web_element/add_menu',
        method: 'POST',
        data,
      });
    },

    // 编辑元素菜单
    edit_element_menu: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web_element/edit_menu',
        method: 'POST',
        data,
      });
    },

    // 删除元素菜单
    del_element_menu: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web_element/del_menu',
        method: 'POST',
        data,
      });
    },

    // 获取元素列表
    get_element_list: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web_element/get_element_list',
        method: 'POST',
        data,
      });
    },

    // 新增元素
    add_element: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web_element/add_element',
        method: 'POST',
        data,
      });
    },

    // 编辑元素
    edit_element: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web_element/edit_element',
        method: 'POST',
        data,
      });
    },

    // 删除元素
    del_element: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web_element/del_element',
        method: 'POST',
        data,
      });
    },

    // 获取元素选择树
    get_element_select: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web_element/get_element_select',
        method: 'POST',
        data,
      });
    },

  

    // 获取 Web 脚本菜单树
    web_menu: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web/web_menu',
        method: 'POST',
        data,
      });
    },

    // 新增 Web 脚本菜单
    add_web_menu: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web/add_menu',
        method: 'POST',
        data,
      });
    },

    // 删除 Web 脚本菜单
    del_web_menu: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web/del_menu',
        method: 'POST',
        data,
      });
    },

    // 重命名 Web 脚本菜单
    rename_web_menu: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web/rename_menu',
        method: 'POST',
        data,
      });
    },

    // 根据菜单 ID 获取子脚本列表
    menu_script_list: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web/menu_script_list',
        method: 'POST',
        data,
      });
    },

    // 获取单个 Web 脚本
    get_web_script: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web/get_web_script',
        method: 'POST',
        data,
      });
    },

    // 保存 Web 脚本
    save_web_script: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web/save_script',
        method: 'POST',
        data,
      });
    },

    // 导入元素脚本
    input_element: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web/input_element',
        method: 'POST',
        data,
      });
    },

    // 获取全部脚本菜单列表
    get_web_script_list: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web/get_script_list',
        method: 'POST',
        data,
      });
    },

    // Web 脚本集列表
    web_group_list: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web/web_group_list',
        method: 'POST',
        data,
      });
    },

    // 新增 Web 脚本集
    add_web_group: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web/add_web_group',
        method: 'POST',
        data,
      });
    },

    // 编辑 Web 脚本集
    edit_web_group: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web/edit_web_group',
        method: 'POST',
        data,
      });
    },

    // 删除 Web 脚本集
    del_web_group: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web/del_web_group',
        method: 'POST',
        data,
      });
    },

    // 获取全部 Web 脚本集
    web_group_select: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web/web_group_select',
        method: 'POST',
        data,
      });
    },

    // 场景编辑时根据脚本树选择脚本
    group_add_script: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web/group_add_script',
        method: 'POST',
        data,
      });
    },

    

    // 执行 Web 脚本
    run_web_script: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web/run_web_script',
        method: 'POST',
        data,
      });
    },

    // 停止 Web 执行进程
    stop_web_script: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web/stop_web_script',
        method: 'POST',
        data,
      });
    },

    // 停止一次 Web 执行
    stop_web_result: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web/stop_web_result',
        method: 'POST',
        data,
      });
    },

    // 删除一次 Web 执行记录
    del_web_result: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web/del_web_result',
        method: 'POST',
        data,
      });
    },

    // 获取单次执行的步骤结果
    get_web_result: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web/get_web_result',
        method: 'POST',
        data,
      });
    },

    // 获取执行日志
    get_web_result_log: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web/get_web_result_log',
        method: 'POST',
        data,
      });
    },

    // 获取 Web 结果列表
    get_web_result_list: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web/get_web_result_list',
        method: 'POST',
        data,
      });
    },

    // 获取执行汇总报告
    get_web_result_report: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web/get_web_result_report',
        method: 'POST',
        data,
      });
    },

    // 获取单个脚本在某浏览器下的执行详情
    get_web_result_detail: (data: any) => {
      return request({
        url: '/v1/Ntesterc_web/web/get_web_result_detail',
        method: 'POST',
        data,
      });
    },

    // AI 生成脚本步骤（方案 B：截图+DOM→LLM）
    ai_generate_script: (data: { url: string; description: string; browser_type?: string; viewport_width?: number; viewport_height?: number }) => {
      return request({
        url: '/v1/Ntesterc_web/web/ai_generate_script',
        method: 'POST',
        data,
      });
    },
  };
}

