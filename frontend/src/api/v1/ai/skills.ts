import request from '/@/utils/request';

export function useSkillsApi() {
  return {
    list: (projectId: number, params?: Record<string, any>) =>
      request({
        url: `/v1/Ntesterc_skills/projects/${projectId}`,
        method: 'GET',
        params,
      }),
    create: (projectId: number, data: any) =>
      request({
        url: `/v1/Ntesterc_skills/projects/${projectId}`,
        method: 'POST',
        data,
      }),
    update: (projectId: number, skillId: number, data: any) =>
      request({
        url: `/v1/Ntesterc_skills/projects/${projectId}/${skillId}`,
        method: 'PUT',
        data,
      }),
    remove: (projectId: number, skillId: number) =>
      request({
        url: `/v1/Ntesterc_skills/projects/${projectId}/${skillId}`,
        method: 'DELETE',
      }),
    batchRemove: (projectId: number, data: { skill_ids?: number[]; delete_all?: boolean }) =>
      request({
        url: `/v1/Ntesterc_skills/projects/${projectId}/batch-delete`,
        method: 'POST',
        data,
      }),
    content: (projectId: number, skillId: number, params?: { file_path?: string }) =>
      request({
        url: `/v1/Ntesterc_skills/projects/${projectId}/${skillId}/content`,
        method: 'GET',
        params,
      }),
    manifest: (projectId: number, skillId: number) =>
      request({
        url: `/v1/Ntesterc_skills/projects/${projectId}/${skillId}/manifest`,
        method: 'GET',
      }),
    execute: (projectId: number, skillId: number, data?: { arguments?: Record<string, any>; session_id?: string }) =>
      request({
        url: `/v1/Ntesterc_skills/projects/${projectId}/${skillId}/execute`,
        method: 'POST',
        data: data || {},
      }),
    executeActionAsync: (
      projectId: number,
      skillId: number,
      data?: { action_name?: string; arguments?: Record<string, any>; session_id?: string; runner_type?: string }
    ) =>
      request({
        url: `/v1/Ntesterc_skills/projects/${projectId}/${skillId}/actions/execute`,
        method: 'POST',
        data: data || {},
      }),
    job: (projectId: number, jobId: number) =>
      request({
        url: `/v1/Ntesterc_skills/projects/${projectId}/jobs/${jobId}`,
        method: 'GET',
      }),
    jobArtifacts: (projectId: number, jobId: number) =>
      request({
        url: `/v1/Ntesterc_skills/projects/${projectId}/jobs/${jobId}/artifacts`,
        method: 'GET',
      }),
    jobStreamUrl: (projectId: number, jobId: number) => `/v1/Ntesterc_skills/projects/${projectId}/jobs/${jobId}/stream`,
    artifactDownloadUrl: (projectId: number, artifactId: number) =>
      `/v1/Ntesterc_skills/projects/${projectId}/artifacts/${artifactId}/download`,
    importGit: (projectId: number, data: any) =>
      request({
        url: `/v1/Ntesterc_skills/projects/${projectId}/import/git`,
        method: 'POST',
        data,
      }),
    importGitPreview: (projectId: number, data: any) =>
      request({
        url: `/v1/Ntesterc_skills/projects/${projectId}/import/git/preview`,
        method: 'POST',
        data,
      }),
    importGitSelected: (projectId: number, data: any) =>
      request({
        url: `/v1/Ntesterc_skills/projects/${projectId}/import/git/selected`,
        method: 'POST',
        data,
      }),
    importUpload: (projectId: number, file: File, params?: { scenario_category?: string; entry_command?: string }) => {
      const fd = new FormData();
      fd.append('file', file);
      return request({
        url: `/v1/Ntesterc_skills/projects/${projectId}/import/upload`,
        method: 'POST',
        params,
        data: fd,
        headers: { 'Content-Type': 'multipart/form-data' },
      });
    },
    importUploadFolder: (projectId: number, fd: FormData, params?: { scenario_category?: string; entry_command?: string }) =>
      request({
        url: `/v1/Ntesterc_skills/projects/${projectId}/import/upload-folder`,
        method: 'POST',
        params,
        data: fd,
        headers: { 'Content-Type': 'multipart/form-data' },
      }),
    // ===== 外部编程 Agent 集成（Claude Code / Codex / OpenCode 驱动 Playwright Test Agents / agent-device）=====
    detectHarness: (projectId: number) =>
      request({
        url: `/v1/Ntesterc_skills/projects/${projectId}/external-agent/harness`,
        method: 'GET',
      }),
    scaffoldPwTestAgents: (projectId: number, data: any) =>
      request({
        url: `/v1/Ntesterc_skills/projects/${projectId}/pw-test-agents/scaffold`,
        method: 'POST',
        data,
      }),
    registerAgentDevice: (projectId: number, data: any) =>
      request({
        url: `/v1/Ntesterc_skills/projects/${projectId}/agent-device/register`,
        method: 'POST',
        data,
      }),
    runExternalAgent: (projectId: number, data: any) =>
      request({
        url: `/v1/Ntesterc_skills/projects/${projectId}/external-agent/run`,
        method: 'POST',
        data,
      }),
  };
}

export const skillsApi = useSkillsApi();
