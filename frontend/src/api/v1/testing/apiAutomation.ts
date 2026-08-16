import request from '/@/utils/request';

const postApiAutomation = <T = any>(url: string, data?: any) => {
  return request<T>({
    url,
    method: 'post',
    data,
  });
};

export function useApiAutomationApi() {
  return {
    // AI 脚本校验（语法/规范/试运行/AI 审查）
    script_validate: (data: any) => request.post('/v1/Ntesterc_api/script/validate', data),
    // ---------- 服务 ----------
    api_service: (data: { page?: number; pageSize?: number; search?: { api_project_id?: number | null; name?: string; manager?: number | null; business_id?: number | null } } = {}) =>
      postApiAutomation('/v1/Ntesterc_api/api_service', data),
    add_api_service: (data: { name: string; api_project_id: number; img?: string | null; description?: string | null }) =>
      postApiAutomation('/v1/Ntesterc_api/add_api_service', data),
    edit_api_service: (data: { id: number; name?: string; api_project_id?: number; img?: string | null; description?: string | null }) =>
      postApiAutomation('/v1/Ntesterc_api/edit_api_service', data),
    del_api_service: (data: { id: number }) => postApiAutomation('/v1/Ntesterc_api/del_api_service', data),
    api_service_list: (data: { project_id?: number | null } = {}) => postApiAutomation('/v1/Ntesterc_api/api_service_list', data),
    get_common_params: (data: { api_service_id: number }) =>
      postApiAutomation('/v1/Ntesterc_api/get_common_params', data),
    save_common_params: (data: { api_service_id: number; common_params: Record<string, any> }) =>
      postApiAutomation('/v1/Ntesterc_api/save_common_params', data),

    // ---------- 树/菜单 ----------
    api_tree: (data: { search?: Record<string, any> } = {}) => postApiAutomation('/v1/Ntesterc_api/api_tree', data),
    api_tree_list: (data: Record<string, any> = {}) => postApiAutomation('/v1/Ntesterc_api/api_tree_list', data),
    sort_menu: (data: { pid: number; ids: (number | string)[] }) => postApiAutomation('/v1/Ntesterc_api/sort_menu', data),
    upload_script_file: (file: File) => {
    	const fd = new FormData()
    	fd.append('file', file)
    	return request.post('/v1/Ntesterc_api/upload_script_file', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
    },
    del_script_file: (data: { path: string }) => postApiAutomation('/v1/Ntesterc_api/del_script_file', data),
    add_menu: (data: { name: string; pid: number; type: number; api_service_id: number }) =>
      postApiAutomation('/v1/Ntesterc_api/add_menu', data),
    edit_menu: (data: { id: number; name: string }) => postApiAutomation('/v1/Ntesterc_api/edit_menu', data),
    del_menu: (data: { id: number; type?: number }) => postApiAutomation('/v1/Ntesterc_api/del_menu', data),
    copy_menu: (data: { id: number; api_id: number }) => postApiAutomation('/v1/Ntesterc_api/copy_menu', data),

    // ---------- API 接口详情/保存/发送 ----------
    api_info: (data: { api_id: number }) => postApiAutomation('/v1/Ntesterc_api/api_info', data),
    save_api: (data: { id: number; url?: string; req?: Record<string, any>; document?: Record<string, any>; name?: string; description?: string }) =>
      postApiAutomation('/v1/Ntesterc_api/save_api', data),
    save_api_case: (data: Record<string, any>) => postApiAutomation('/v1/Ntesterc_api/save_api_case', data),
    api_send: (data: { id?: number; env_id?: number; url?: string; req?: Record<string, any> }) =>
      postApiAutomation('/v1/Ntesterc_api/api_send', data),
    req_history: (data: Record<string, any> = {}) => postApiAutomation('/v1/Ntesterc_api/req_history', data),
    del_req_history: (data: { id: number }) => postApiAutomation('/v1/Ntesterc_api/del_req_history', data),
    edit_history: (data: { api_id: number }) => postApiAutomation('/v1/Ntesterc_api/edit_history', data),

    // ---------- 环境 ----------
    api_env: (data: Record<string, any> = {}) => postApiAutomation('/v1/Ntesterc_api/api_env', data),
    env_info: (data: { id: number }) => postApiAutomation('/v1/Ntesterc_api/env_info', data),
    save_env: (data: { env_list: Array<Record<string, any>> }) => postApiAutomation('/v1/Ntesterc_api/save_env', data),
    add_env: (data: { name: string; config?: any[]; variable?: any[] }) => postApiAutomation('/v1/Ntesterc_api/add_env', data),
    del_env: (data: { id: number }) => postApiAutomation('/v1/Ntesterc_api/del_env', data),

    // ---------- 全局变量 ----------
    api_var_list: (data: Record<string, any> = {}) => postApiAutomation('/v1/Ntesterc_api/api_var_list', data),
    add_var: (data: { name: string; value: string }) => postApiAutomation('/v1/Ntesterc_api/add_var', data),
    edit_var: (data: { id: number; name: string; value: string }) => postApiAutomation('/v1/Ntesterc_api/edit_var', data),
    del_var: (data: { id: number }) => postApiAutomation('/v1/Ntesterc_api/del_var', data),

    // ---------- 数据库配置 ----------
    api_db: (data: Record<string, any> = {}) => postApiAutomation('/v1/Ntesterc_api/api_db', data),
    api_db_list: (data: Record<string, any> = {}) => postApiAutomation('/v1/Ntesterc_api/api_db_list', data),
    add_api_db: (data: { name: string; config?: Record<string, any> }) => postApiAutomation('/v1/Ntesterc_api/add_api_db', data),
    edit_api_db: (data: { id: number; name?: string; config?: Record<string, any> }) => postApiAutomation('/v1/Ntesterc_api/edit_api_db', data),
    del_api_db: (data: { id: number }) => postApiAutomation('/v1/Ntesterc_api/del_api_db', data),
    test_db_conn: (data: { id: number }) => postApiAutomation('/v1/Ntesterc_api/test_db_conn', data),

    curlImport: (data: Record<string, any>) => postApiAutomation('/v1/Ntesterc_api/import_curl', data),
    wsTest: (data: Record<string, any>) => postApiAutomation('/v1/Ntesterc_api/ws_test', data),
    saveDataSource: (data: Record<string, any>) => postApiAutomation('/v1/Ntesterc_api/save_data_source', data),
    syncDataSource: (data: Record<string, any>) => postApiAutomation('/v1/Ntesterc_api/sync_data_source', data),
    pull_api_doc: (data: {
      api_service_id: number;
      source_type: 'swagger' | 'apifox' | 'postman';
      doc_url?: string;
      cookies?: string;
      doc_content?: Record<string, any>;
    }) => postApiAutomation('/v1/Ntesterc_api/pull_api_doc', data),

    // ---------- 用例/执行 ----------
    api_script_list: (data: { page?: number; pageSize?: number } = {}) => postApiAutomation('/v1/Ntesterc_api/api_script_list', data),
    add_api_script: (data: Record<string, any>) => postApiAutomation('/v1/Ntesterc_api/add_api_script', data),
    edit_api_script: (data: Record<string, any>) => postApiAutomation('/v1/Ntesterc_api/edit_api_script', data),
    del_api_script: (data: { id: number }) => postApiAutomation('/v1/Ntesterc_api/del_api_script', data),
    get_api_script_list: (data: Record<string, any> = {}) => postApiAutomation('/v1/Ntesterc_api/get_api_script_list', data),
    get_api_case: (data: { script?: any[] } = {}) => postApiAutomation('/v1/Ntesterc_api/get_api_case', data),
    run_api_script: (data: Record<string, any>) => postApiAutomation('/v1/Ntesterc_api/run_api_script', data),
    get_api_script_result: (data: { result_id: number }) => postApiAutomation('/v1/Ntesterc_api/get_api_script_result', data),
    get_api_script_result_list: (data: { page?: number; pageSize?: number; search?: Record<string, any>; api_service_id?: number | null } = {}) =>
      postApiAutomation('/v1/Ntesterc_api/get_api_script_result_list', data),
    get_api_script_result_detail: (data: { result_id: number }) => postApiAutomation('/v1/Ntesterc_api/get_api_script_result_detail', data),
    get_api_script_result_detail_list: (data: { result_id: number; menu_id: string }) =>
      postApiAutomation('/v1/Ntesterc_api/get_api_script_result_detail_list', data),
    get_api_script_result_report_list: (data: { result_id: number; menu_id: string }) =>
      postApiAutomation('/v1/Ntesterc_api/get_api_script_result_report_list', data),
    get_api_script_log: (data: { result_id: string }) => postApiAutomation('/v1/Ntesterc_api/get_api_script_log', data),
    get_api_script_report_log: (data: { result_id: string; menu_id: string }) =>
      postApiAutomation('/v1/Ntesterc_api/get_api_script_report_log', data),
    stop_api_script_result: (data: { result_id: number }) =>
      postApiAutomation('/v1/Ntesterc_api/stop_api_script_result', data),
    del_api_script_result: (data: { result_id: number }) =>
      postApiAutomation('/v1/Ntesterc_api/del_api_script_result', data),

    // ---------- 外部调用 ----------
    service_api_update: (data: Record<string, any>) => postApiAutomation('/v1/Ntesterc_api/service_api_update', data),
    gitlab_ci_notice: (data: Record<string, any>) => postApiAutomation('/v1/Ntesterc_api/gitlab_ci_notice', data),

    // ---------- 代码生成 ----------
    generate_code: (data: {
      source_type: 'swagger' | 'apifox' | 'case' | 'custom';
      framework: 'pytest' | 'unittest' | 'testng' | 'jest';
      api_ids?: number[];
      custom_apis?: any[];
      base_url?: string;
      class_name?: string;
      service_id?: number;
    }) => postApiAutomation('/v1/Ntesterc_api/generate_code', data),
    run_generated_code: (data: { code: string; framework: string; exec_mode?: 'sandbox' | 'native' }) =>
      postApiAutomation('/v1/Ntesterc_api/run_generated_code', data),

    // ---------- 服务排序 ----------
    api_service_sort: (data: { ids: number[] }) =>
      postApiAutomation('/v1/Ntesterc_api/api_service_sort', data),

    // ---------- 用例集（Suite）----------
    api_suite_list: (data: { api_service_id: number }) =>
      postApiAutomation('/v1/Ntesterc_api/api_suite_list', data),
    add_api_suite: (data: { name: string; parent?: number | null; api_service_id: number }) =>
      postApiAutomation('/v1/Ntesterc_api/add_api_suite', data),
    edit_api_suite: (data: { id: number; name: string }) =>
      postApiAutomation('/v1/Ntesterc_api/edit_api_suite', data),
    del_api_suite: (data: { id: number }) =>
      postApiAutomation('/v1/Ntesterc_api/del_api_suite', data),
    api_suite_sort: (data: { ids: number[] }) =>
      postApiAutomation('/v1/Ntesterc_api/api_suite_sort', data),

    // ---------- 用例（Case）----------
    api_case_list: (data: { suite_id: number }) =>
      postApiAutomation('/v1/Ntesterc_api/api_case_list', data),
    add_api_case: (data: { name: string; description?: string; suite_id: number; script?: any[]; case_type?: number; step_rely?: number }) =>
      postApiAutomation('/v1/Ntesterc_api/add_api_case', data),
    edit_api_case: (data: { id: number; name?: string; description?: string; script?: any[]; case_type?: number; step_rely?: number }) =>
      postApiAutomation('/v1/Ntesterc_api/edit_api_case', data),
    del_api_case: (data: { id: number }) =>
      postApiAutomation('/v1/Ntesterc_api/del_api_case', data),
    run_api_case: (data: { case_ids: number[]; env_id: number; name?: string }) =>
      postApiAutomation('/v1/Ntesterc_api/run_api_case', data),
    save_api_case_to_suite: (data: { name: string; description?: string; suite_id: number; script?: any[]; case_type?: number }) =>
      postApiAutomation('/v1/Ntesterc_api/save_api_case_to_suite', data),

    // ---------- 公共脚本（NtestScript）----------
    ntest_script_list: (data: { api_service_id: number }) =>
      postApiAutomation('/v1/Ntesterc_api/ntest_script_list', data),
    add_ntest_script: (data: { name: string; description?: string; code?: string; api_service_id: number }) =>
      postApiAutomation('/v1/Ntesterc_api/add_ntest_script', data),
    edit_ntest_script: (data: { id: number; name?: string; description?: string; code?: string }) =>
      postApiAutomation('/v1/Ntesterc_api/edit_ntest_script', data),
    del_ntest_script: (data: { id: number }) =>
      postApiAutomation('/v1/Ntesterc_api/del_ntest_script', data),

    // ---------- 数据查询（QueryDB）----------
    get_db_databases: (data: { db_id: number }) =>
      postApiAutomation('/v1/Ntesterc_api/get_db_databases', data),
    get_db_tables: (data: { db_id: number; database: string }) =>
      postApiAutomation('/v1/Ntesterc_api/get_db_tables', data),
    execute_db_query: (data: { db_id: number; sql: string }) =>
      postApiAutomation('/v1/Ntesterc_api/execute_db_query', data),
  };
}
export const apiAutomationApi = useApiAutomationApi();
export const {
  api_service,
  add_api_service,
  edit_api_service,
  del_api_service,
  api_service_list,
  get_common_params,
  save_common_params,
  api_tree,
  api_tree_list,
  add_menu,
  sort_menu,
  upload_script_file,
  del_script_file,
  edit_menu,
  del_menu,
  copy_menu,
  api_info,
  save_api,
  save_api_case,
  api_send,
  req_history,
  del_req_history,
  edit_history,
  api_env,
  env_info,
  save_env,
  add_env,
  del_env,
  api_var_list,
  add_var,
  edit_var,
  del_var,
  api_db,
  api_db_list,
  add_api_db,
  edit_api_db,
  del_api_db,
  test_db_conn,
  pull_api_doc,
  api_script_list,
  add_api_script,
  edit_api_script,
  del_api_script,
  get_api_script_list,
  get_api_case,
  run_api_script,
  get_api_script_result,
  get_api_script_result_list,
  get_api_script_result_detail,
  get_api_script_result_detail_list,
  get_api_script_result_report_list,
  get_api_script_log,
  get_api_script_report_log,
  stop_api_script_result,
  del_api_script_result,
  service_api_update,
  gitlab_ci_notice,
} = apiAutomationApi;

