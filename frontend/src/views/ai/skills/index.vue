<template>
  <div class="skill-page">
    <div class="skill-toolbar">
      <div class="toolbar-left">
        <h2 class="page-title">Skill 管理</h2>
        <el-select v-model="projectId" placeholder="选择项目" style="width: 220px" @change="onProjectChange">
          <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
        </el-select>
      </div>
      <div class="toolbar-actions">
        <el-button type="success" @click="openEditDialog()">新建 Skill</el-button>
        <el-button type="primary" @click="openGitDialog">Git 导入</el-button>
        <el-dropdown split-button @click="openUploadDialog('zip')">
          本地导入
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="openUploadDialog('zip')">上传 ZIP 包</el-dropdown-item>
              <el-dropdown-item @click="openUploadDialog('folder')">上传文件夹</el-dropdown-item>
              <el-dropdown-item divided @click="openLocalClaudeDialog">本机 Claude Skill</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-button type="warning" @click="goToExternalAgent">Agents集成</el-button>
        <el-button type="danger" plain :disabled="!selectedIds.length" @click="onBatchDelete">
          批量删除{{ selectedIds.length ? ` (${selectedIds.length})` : '' }}
        </el-button>
      </div>
    </div>

    <div class="skill-filters">
      <el-checkbox
        v-model="selectAllPage"
        :indeterminate="isIndeterminate"
        :disabled="!rows.length"
        @change="onToggleSelectAll"
      >
        全选本页
      </el-checkbox>
      <el-input
        v-model="query.search"
        clearable
        placeholder="搜索技能名称"
        style="width: 220px"
        @keyup.enter="loadSkills"
      />
      <el-input
        v-model="query.scenario_category"
        clearable
        placeholder="场景分类"
        style="width: 220px"
        @keyup.enter="loadSkills"
      />
      <el-button type="primary" @click="loadSkills">查询</el-button>
      <el-button @click="resetQuery">重置</el-button>
    </div>

    <div v-loading="loading" class="skill-grid-wrap">
      <div v-if="!projectId" class="skill-empty">请先选择项目</div>
      <div v-else-if="!rows.length" class="skill-empty">暂无 Skill，可新建、Git 导入或本地导入</div>
      <div v-else class="skill-grid">
        <article v-for="s in rows" :key="s.id" class="skill-card" :class="{ 'is-selected': selectedIds.includes(s.id) }">
          <header class="skill-card__head">
            <div class="skill-card__identity">
              <div class="skill-card__title-row">
                <el-checkbox :model-value="selectedIds.includes(s.id)" @change="(v: boolean) => onToggleSelect(s.id, v)" />
                <h3 class="skill-card__name" :title="s.name">{{ s.name }}</h3>
              </div>
              <div class="skill-card__tags">
                <el-tag size="small" type="info">场景：{{ s.scenario_category || '未分类' }}</el-tag>
                <el-tag size="small">{{ s.source_type || '-' }}</el-tag>
              </div>
            </div>
            <el-switch
              v-model="s.is_active"
              inline-prompt
              active-text="开"
              inactive-text="关"
              @change="onToggleActive(s)"
            />
          </header>

          <p class="skill-card__desc" :title="s.description || ''">
            {{ s.description || '暂无描述' }}
          </p>

          <div class="skill-card__meta">
            <div class="meta-row" :title="s.allowed_tools || ''">
              <span class="meta-label">工具</span>
              <span class="meta-value">{{ s.allowed_tools || '-' }}</span>
            </div>
            <div class="meta-row" :title="s.skill_path || ''">
              <span class="meta-label">目录</span>
              <span class="meta-value">{{ s.skill_path || '-' }}</span>
            </div>
          </div>

          <footer class="skill-card__foot">
            <div class="foot-main">
              <el-button link type="primary" @click="openEditDialog(s)">编辑</el-button>
              <el-button link type="primary" @click="onViewContent(s)">查看内容</el-button>
            </div>
            <el-button link type="danger" class="foot-delete" @click="onDelete(s)">删除</el-button>
          </footer>
        </article>
      </div>
    </div>

    <div class="pager">
      <el-pagination
        v-model:current-page="query.page"
        v-model:page-size="query.page_size"
        :total="total"
        :page-sizes="[12, 24, 48, 96]"
        layout="total, sizes, prev, pager, next, jumper"
        @current-change="loadSkills"
        @size-change="loadSkills"
      />
    </div>

    <el-dialog v-model="gitDialogVisible" :title="gitStep === 1 ? 'Git 导入 Skill' : '选择要导入的 Skill'" width="640px">
      <template v-if="gitStep === 1">
        <el-form label-width="90px">
          <el-form-item label="仓库地址" required>
            <el-input v-model="gitForm.repo_url" placeholder="https://github.com/... 或 https://gitee.com/..." />
          </el-form-item>
          <el-form-item label="分类">
            <el-input v-model="gitForm.scenario_category" placeholder="如 superpowers，可不填" />
          </el-form-item>
          <el-form-item label="分支">
            <el-input v-model="gitForm.branch" placeholder="默认主分支，可不填" />
          </el-form-item>
        </el-form>
      </template>

      <template v-else>
        <div class="preview-tip">
          仓库 <code>{{ gitForm.repo_url }}</code> 共发现 {{ previewSkills.length }} 个 Skill，请勾选要导入的项：
        </div>
        <div v-loading="gitSubmitting" class="preview-list">
          <el-checkbox-group v-model="selectedSkillNames">
            <div v-for="s in previewSkills" :key="s.name" class="preview-item">
              <el-checkbox :value="s.name">
                <div class="preview-item__head">
                  <span class="preview-item__name">{{ s.display_name }}</span>
                  <el-tag v-if="s.already_imported" size="small" type="warning">已导入</el-tag>
                </div>
                <div class="preview-item__desc">{{ s.description || '暂无描述' }}</div>
              </el-checkbox>
            </div>
          </el-checkbox-group>
          <div v-if="!previewSkills.length" class="preview-empty">未扫描到任何 Skill</div>
        </div>
      </template>

      <template #footer>
        <template v-if="gitStep === 1">
          <el-button @click="gitDialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="gitPreviewing" @click="previewGitImport">预览</el-button>
        </template>
        <template v-else>
          <el-button @click="gitStep = 1">上一步</el-button>
          <el-button type="primary" :loading="gitSubmitting" @click="submitGitImport">导入选中</el-button>
        </template>
      </template>
    </el-dialog>

    <el-dialog v-model="uploadDialogVisible" title="本地导入 Skill" width="560px" @closed="resetUploadForm">
      <el-form label-width="90px">
        <el-form-item label="方式">
          <el-radio-group v-model="uploadMode">
            <el-radio-button label="zip">上传 ZIP 包</el-radio-button>
            <el-radio-button label="folder">上传文件夹</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="分类" required>
          <el-input v-model="uploadForm.scenario_category" placeholder="请选择或填写场景分类" />
        </el-form-item>
        <el-form-item v-if="uploadMode === 'zip'" label="ZIP 文件" required>
          <el-upload
            ref="uploadRef"
            :key="uploadKey"
            :show-file-list="true"
            :auto-upload="false"
            accept=".zip"
            :limit="1"
            :on-change="onUploadFileChange"
            :on-remove="() => (uploadForm.file = null)"
          >
            <el-button>选择 ZIP</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item v-else label="文件夹" required>
          <input
            ref="folderInputRef"
            type="file"
            webkitdirectory
            directory
            multiple
            style="display: none"
            @change="onFolderChange"
          />
          <div class="folder-upload">
            <el-button @click="folderInputRef?.click()">选择文件夹</el-button>
            <span v-if="folderName" class="folder-name">{{ folderName }}（{{ folderFiles.length }} 个文件）</span>
            <span v-else class="folder-placeholder">请选择包含 SKILL.md 或 skills/ 子目录的文件夹</span>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="uploadDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploadSubmitting" @click="submitUploadImport">导入</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="contentDialogVisible" :title="`Skill 目录：${contentSkillName}`" width="960px" class="content-dialog">
      <div class="content-layout">
        <div class="content-tree-pane">
          <div class="pane-title">目录结构</div>
          <el-tree
            v-if="contentTree.length"
            :data="contentTree"
            node-key="path"
            :props="{ label: 'name', children: 'children' }"
            highlight-current
            default-expand-all
            @node-click="onContentTreeClick"
          >
            <template #default="{ data }">
              <span class="tree-node" :class="{ 'is-file': data.type === 'file', 'is-dir': data.type === 'dir' }">
                [{{ data.type === 'dir' ? 'dir' : 'file' }}] {{ data.name }}
              </span>
            </template>
          </el-tree>
          <div v-else class="tree-empty">无本地目录或目录为空</div>
        </div>
        <div class="content-file-pane">
          <div class="pane-title">{{ contentFilePath || '文件内容' }}</div>
          <el-input v-model="skillContent" type="textarea" :rows="24" readonly />
        </div>
      </div>
    </el-dialog>

    <el-dialog v-model="localClaudeVisible" title="本机 Claude Skill" width="720px">
      <div v-loading="localClaudeLoading" class="local-claude-list">
        <el-empty v-if="!localClaudeItems.length" description="未在 ~/.claude/skills/ 发现 Skill" />
        <el-table v-else :data="localClaudeItems" max-height="420" size="small">
          <el-table-column prop="name" label="名称" min-width="140" show-overflow-tooltip />
          <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip />
          <el-table-column prop="allowed_tools" label="工具" min-width="120" show-overflow-tooltip>
            <template #default="{ row }">
              {{ row.allowed_tools?.join(', ') || '-' }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="90" fixed="right">
            <template #default="{ row }">
              <el-button
                link
                type="primary"
                :loading="localClaudeImporting === row.local_name"
                @click="onImportLocalClaude(row)"
              >
                导入
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <template #footer>
        <el-button @click="localClaudeVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editDialogVisible" :title="editForm.id ? '编辑 Skill' : '新建 Skill'" width="620px">
      <el-form label-width="100px">
        <el-form-item label="技能名称">
          <el-input v-model="editForm.name" placeholder="如 agent-browser-skill" />
        </el-form-item>
        <el-form-item label="技能描述">
          <el-input v-model="editForm.description" type="textarea" :rows="3" placeholder="请输入技能描述" />
        </el-form-item>
        <el-form-item label="场景分类">
          <el-input v-model="editForm.scenario_category" placeholder="如 agent-browser-skill" />
        </el-form-item>
        <el-form-item label="来源类型">
          <el-select v-model="editForm.source_type" style="width: 100%">
            <el-option label="builtin" value="builtin" />
            <el-option label="github" value="github" />
            <el-option label="gitee" value="gitee" />
            <el-option label="upload" value="upload" />
          </el-select>
        </el-form-item>
        <el-form-item label="仓库URL">
          <el-input v-model="editForm.repo_url" placeholder="可选，来源为 git 时填写" />
        </el-form-item>
        <el-form-item label="技能目录">
          <el-input v-model="editForm.skill_path" placeholder="本地技能目录路径（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="editSubmitting" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import type { UploadFile } from 'element-plus';
import { useProjectApi } from '/@/api/v1/projects/project';
import { skillsApi } from '/@/api/v1/ai/skills';

const router = useRouter();
const projectApi = useProjectApi();

const loading = ref(false);
const projects = ref<Array<{ id: number; name: string }>>([]);
const projectId = ref<number | null>(null);
const rows = ref<any[]>([]);
const total = ref(0);
const selectedIds = ref<number[]>([]);
const query = reactive({
  search: '',
  scenario_category: '',
  page: 1,
  page_size: 12,
});

const selectAllPage = computed({
  get: () => rows.value.length > 0 && rows.value.every((r) => selectedIds.value.includes(r.id)),
  set: () => undefined,
});
const isIndeterminate = computed(() => {
  const n = rows.value.filter((r) => selectedIds.value.includes(r.id)).length;
  return n > 0 && n < rows.value.length;
});

const gitDialogVisible = ref(false);
const gitStep = ref(1);
const gitPreviewing = ref(false);
const gitSubmitting = ref(false);
const gitForm = reactive({
  repo_url: '',
  name: '',
  scenario_category: '',
  branch: '',
});
const previewSkills = ref<any[]>([]);
const selectedSkillNames = ref<string[]>([]);

const uploadDialogVisible = ref(false);
const uploadSubmitting = ref(false);
const uploadRef = ref<any>(null);
const uploadKey = ref(0);
const uploadMode = ref<'zip' | 'folder'>('zip');
const folderInputRef = ref<HTMLInputElement | null>(null);
const folderName = ref('');
const folderFiles = ref<File[]>([]);
const uploadForm = reactive<{ scenario_category: string; file: File | null }>({
  scenario_category: '',
  file: null,
});

const contentDialogVisible = ref(false);
const contentSkillName = ref('');
const contentSkillId = ref<number | null>(null);
const contentTree = ref<any[]>([]);
const contentFilePath = ref('');
const skillContent = ref('');

const editDialogVisible = ref(false);
const editSubmitting = ref(false);
const editForm = reactive<any>({
  id: undefined,
  name: '',
  description: '',
  scenario_category: '',
  source_type: 'builtin',
  repo_url: '',
  skill_path: '',
});

const localClaudeVisible = ref(false);
const localClaudeLoading = ref(false);
const localClaudeImporting = ref<string>('');
const localClaudeItems = ref<any[]>([]);

const loadProjects = async () => {
  const res: any = await projectApi.getList({ page: 1, page_size: 100 });
  projects.value = res?.data?.items || [];
  if (!projectId.value && projects.value.length) {
    projectId.value = projects.value[0].id;
  }
};

const loadSkills = async () => {
  if (!projectId.value) return;
  loading.value = true;
  try {
    const res: any = await skillsApi.list(projectId.value, query);
    rows.value = res?.data?.items || [];
    total.value = res?.data?.total || 0;
    const idSet = new Set(rows.value.map((r: any) => r.id));
    selectedIds.value = selectedIds.value.filter((id) => idSet.has(id));
  } finally {
    loading.value = false;
  }
};

const onProjectChange = () => {
  query.page = 1;
  selectedIds.value = [];
  loadSkills();
};

const resetQuery = () => {
  query.search = '';
  query.scenario_category = '';
  query.page = 1;
  loadSkills();
};

const onToggleSelect = (id: number, checked: boolean) => {
  if (checked) {
    if (!selectedIds.value.includes(id)) selectedIds.value = [...selectedIds.value, id];
  } else {
    selectedIds.value = selectedIds.value.filter((x) => x !== id);
  }
};

const onToggleSelectAll = (checked: boolean | string | number) => {
  if (checked) {
    const pageIds = rows.value.map((r) => r.id);
    selectedIds.value = Array.from(new Set([...selectedIds.value, ...pageIds]));
  } else {
    const pageIdSet = new Set(rows.value.map((r) => r.id));
    selectedIds.value = selectedIds.value.filter((id) => !pageIdSet.has(id));
  }
};

const openGitDialog = () => {
  gitForm.repo_url = '';
  gitForm.name = '';
  gitForm.scenario_category = '';
  gitForm.branch = '';
  gitStep.value = 1;
  previewSkills.value = [];
  selectedSkillNames.value = [];
  gitDialogVisible.value = true;
};

const previewGitImport = async () => {
  if (!projectId.value) return;
  if (!gitForm.repo_url.trim()) {
    ElMessage.warning('请填写仓库地址');
    return;
  }
  gitPreviewing.value = true;
  try {
    const res: any = await skillsApi.importGitPreview(projectId.value, {
      repo_url: gitForm.repo_url.trim(),
      branch: gitForm.branch.trim() || undefined,
    });
    previewSkills.value = res?.data?.skills || [];
    selectedSkillNames.value = previewSkills.value.map((s: any) => s.name);
    if (!previewSkills.value.length) {
      ElMessage.warning('该仓库未扫描到任何 Skill');
      return;
    }
    gitStep.value = 2;
  } catch (e: any) {
    ElMessage.error(e?.message || '拉取仓库失败');
  } finally {
    gitPreviewing.value = false;
  }
};

const submitGitImport = async () => {
  if (!projectId.value) return;
  if (!selectedSkillNames.value.length) {
    ElMessage.warning('请至少选择一个 Skill');
    return;
  }
  gitSubmitting.value = true;
  try {
    const res: any = await skillsApi.importGitSelected(projectId.value, {
      repo_url: gitForm.repo_url.trim(),
      scenario_category: gitForm.scenario_category.trim(),
      branch: gitForm.branch.trim() || undefined,
      selected: selectedSkillNames.value,
    });
    const count = res?.data?.count ?? 0;
    ElMessage.success(res?.message || `导入成功（创建 ${count} 个 skill）`);
    gitDialogVisible.value = false;
    await loadSkills();
  } catch (e: any) {
    ElMessage.error(e?.message || '导入失败');
  } finally {
    gitSubmitting.value = false;
  }
};

const resetUploadForm = () => {
  uploadForm.scenario_category = '';
  uploadForm.file = null;
  uploadMode.value = 'zip';
  folderName.value = '';
  folderFiles.value = [];
  uploadKey.value += 1;
  uploadRef.value?.clearFiles?.();
  if (folderInputRef.value) {
    folderInputRef.value.value = '';
  }
};

const openUploadDialog = (mode: 'zip' | 'folder' = 'zip') => {
  resetUploadForm();
  uploadMode.value = mode;
  uploadDialogVisible.value = true;
};

const onUploadFileChange = (file: UploadFile) => {
  uploadForm.file = (file.raw as File) || null;
};

const onFolderChange = (e: Event) => {
  const files = Array.from((e.target as HTMLInputElement).files || []);
  if (!files.length) {
    folderName.value = '';
    folderFiles.value = [];
    return;
  }
  const firstRel = files[0].webkitRelativePath || '';
  const root = firstRel.split('/')[0] || files[0].name;
  folderName.value = root;
  folderFiles.value = files;
};

const submitUploadImport = async () => {
  if (!projectId.value) return;
  if (!uploadForm.scenario_category.trim()) {
    ElMessage.warning('请填写场景分类');
    return;
  }
  uploadSubmitting.value = true;
  try {
    let res: any;
    if (uploadMode.value === 'zip') {
      if (!uploadForm.file) {
        ElMessage.warning('请选择 ZIP 文件');
        return;
      }
      res = await skillsApi.importUpload(projectId.value, uploadForm.file, {
        scenario_category: uploadForm.scenario_category.trim(),
      });
    } else {
      if (!folderFiles.value.length) {
        ElMessage.warning('请选择文件夹');
        return;
      }
      const fd = new FormData();
      folderFiles.value.forEach((f) => {
        fd.append('files', f);
        fd.append('paths', f.webkitRelativePath || f.name);
      });
      res = await skillsApi.importUploadFolder(projectId.value, fd, {
        scenario_category: uploadForm.scenario_category.trim(),
      });
    }
    const count = res?.data?.count ?? 0;
    ElMessage.success(res?.message || `导入成功（创建 ${count} 个 skill）`);
    uploadDialogVisible.value = false;
    resetUploadForm();
    await loadSkills();
  } catch (e: any) {
    ElMessage.error(e?.message || '导入失败（同名技能不允许重复导入）');
  } finally {
    uploadSubmitting.value = false;
  }
};

const openEditDialog = (row?: any) => {
  if (row) {
    editForm.id = row.id;
    editForm.name = row.name || '';
    editForm.description = row.description || '';
    editForm.scenario_category = row.scenario_category || '';
    editForm.source_type = row.source_type || 'builtin';
    editForm.repo_url = row.repo_url || '';
    editForm.skill_path = row.skill_path || '';
  } else {
    editForm.id = undefined;
    editForm.name = '';
    editForm.description = '';
    editForm.scenario_category = '';
    editForm.source_type = 'builtin';
    editForm.repo_url = '';
    editForm.skill_path = '';
  }
  editDialogVisible.value = true;
};

const submitEdit = async () => {
  if (!projectId.value) return;
  if (!editForm.name.trim()) {
    ElMessage.warning('请填写技能名称');
    return;
  }
  editSubmitting.value = true;
  try {
    const payload = {
      name: editForm.name.trim(),
      description: editForm.description,
      scenario_category: editForm.scenario_category,
      source_type: editForm.source_type,
      repo_url: editForm.repo_url,
      skill_path: editForm.skill_path,
    };
    if (editForm.id) {
      await skillsApi.update(projectId.value, editForm.id, payload);
      ElMessage.success('更新成功');
    } else {
      await skillsApi.create(projectId.value, payload);
      ElMessage.success('创建成功');
    }
    editDialogVisible.value = false;
    await loadSkills();
  } catch (e: any) {
    ElMessage.error(e?.message || '保存失败（技能名称不可重复）');
  } finally {
    editSubmitting.value = false;
  }
};

const onToggleActive = async (row: any) => {
  if (!projectId.value) return;
  try {
    await skillsApi.update(projectId.value, row.id, { is_active: row.is_active });
    ElMessage.success('状态已更新');
  } catch (e: any) {
    row.is_active = !row.is_active;
    ElMessage.error(e?.message || '更新失败');
  }
};

const onDelete = async (row: any) => {
  if (!projectId.value) return;
  await ElMessageBox.confirm(
    `确认删除技能「${row.name}」？将同时删除本地对应目录，且不可恢复。`,
    '删除确认',
    { type: 'warning' }
  );
  await skillsApi.remove(projectId.value, row.id);
  selectedIds.value = selectedIds.value.filter((id) => id !== row.id);
  ElMessage.success('删除成功');
  await loadSkills();
};

const onBatchDelete = async () => {
  if (!projectId.value || !selectedIds.value.length) return;
  await ElMessageBox.confirm(
    `确认批量删除选中的 ${selectedIds.value.length} 个技能？将同时删除本地对应目录。`,
    '批量删除',
    { type: 'warning' }
  );
  const res: any = await skillsApi.batchRemove(projectId.value, { skill_ids: selectedIds.value });
  selectedIds.value = [];
  ElMessage.success(res?.message || '批量删除成功');
  await loadSkills();
};

const openLocalClaudeDialog = async () => {
  if (!projectId.value) return;
  localClaudeVisible.value = true;
  localClaudeLoading.value = true;
  localClaudeItems.value = [];
  try {
    const res: any = await skillsApi.listLocalClaudeSkills(projectId.value);
    localClaudeItems.value = res?.data?.items || [];
  } catch (e: any) {
    ElMessage.error(e?.message || '读取本机 Claude Skill 失败');
  } finally {
    localClaudeLoading.value = false;
  }
};

const goToExternalAgent = () => {
  if (!projectId.value) {
    ElMessage.warning('请先选择项目');
    return;
  }
  router.push({ path: '/ai/skills/external-agent', query: { project_id: String(projectId.value) } });
};

const onImportLocalClaude = async (row: any) => {
  if (!projectId.value) return;
  localClaudeImporting.value = row.local_name;
  try {
    const res: any = await skillsApi.importLocalClaudeSkill(projectId.value, {
      local_name: row.local_name,
      name: row.name,
      scenario_category: row.name,
    });
    ElMessage.success(res?.message || '导入成功');
    await loadSkills();
  } catch (e: any) {
    ElMessage.error(e?.message || '导入失败');
  } finally {
    localClaudeImporting.value = '';
  }
};

const onViewContent = async (row: any) => {
  if (!projectId.value) return;
  contentSkillId.value = row.id;
  contentSkillName.value = row.name || '';
  contentFilePath.value = 'SKILL.md';
  const res: any = await skillsApi.content(projectId.value, row.id, { file_path: 'SKILL.md' });
  contentTree.value = res?.data?.tree || [];
  skillContent.value = res?.data?.content || '';
  contentFilePath.value = res?.data?.file_path || 'SKILL.md';
  contentDialogVisible.value = true;
};

const onContentTreeClick = async (node: any) => {
  if (!projectId.value || !contentSkillId.value) return;
  if (node?.type !== 'file') return;
  contentFilePath.value = node.path;
  const res: any = await skillsApi.content(projectId.value, contentSkillId.value, { file_path: node.path });
  skillContent.value = res?.data?.content || '';
};

onMounted(async () => {
  await loadProjects();
  await loadSkills();
});
</script>

<style scoped>
.skill-page {
  padding: 16px 20px 24px;
}
.skill-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.toolbar-left {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}
.page-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.toolbar-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.skill-filters {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.skill-grid-wrap {
  min-height: 220px;
}
.skill-empty {
  padding: 48px 16px;
  text-align: center;
  color: var(--el-text-color-secondary);
  font-size: 14px;
  background: var(--el-fill-color-blank);
  border: 1px dashed var(--el-border-color);
  border-radius: 10px;
}
.skill-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 14px;
}
.skill-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 12px;
  background: var(--el-bg-color);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.skill-card.is-selected {
  border-color: var(--el-color-primary-light-3);
  box-shadow: 0 0 0 1px var(--el-color-primary-light-5);
}
.skill-card:hover {
  border-color: var(--el-color-primary-light-5);
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.06);
}
.skill-card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.skill-card__identity {
  min-width: 0;
  flex: 1;
}
.skill-card__title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  margin-bottom: 8px;
}
.skill-card__name {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  line-height: 1.3;
  color: var(--el-text-color-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.skill-card__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.skill-card__desc {
  margin: 0;
  min-height: 40px;
  font-size: 13px;
  line-height: 1.5;
  color: var(--el-text-color-secondary);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.skill-card__meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--el-fill-color-light);
}
.meta-row {
  display: flex;
  gap: 8px;
  min-width: 0;
  font-size: 12px;
  line-height: 1.4;
}
.meta-label {
  flex: 0 0 32px;
  color: var(--el-text-color-secondary);
}
.meta-value {
  min-width: 0;
  color: var(--el-text-color-regular);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.skill-card__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: auto;
  padding-top: 12px;
  border-top: 1px solid var(--el-border-color-extra-light);
}
.foot-main {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  flex-wrap: nowrap;
}
.foot-main :deep(.el-button + .el-button) {
  margin-left: 0;
}
.foot-delete {
  flex-shrink: 0;
}
.preview-tip {
  margin-bottom: 12px;
  font-size: 13px;
  color: var(--el-text-color-regular);
  line-height: 1.6;
}
.preview-tip code {
  padding: 1px 6px;
  background: var(--el-fill-color-light);
  border-radius: 4px;
  font-size: 12px;
  word-break: break-all;
}
.preview-list {
  max-height: 420px;
  overflow: auto;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 4px 12px;
}
.preview-item {
  padding: 10px 0;
  border-bottom: 1px solid var(--el-border-color-extra-light);
}
.preview-item:last-child {
  border-bottom: none;
}
.preview-item :deep(.el-checkbox) {
  width: 100%;
  height: auto;
  white-space: normal;
}
.preview-item__head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.preview-item__name {
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.preview-item__desc {
  margin-top: 2px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}
.preview-empty {
  padding: 24px 0;
  text-align: center;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.pager {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
.content-layout {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 14px;
  min-height: 480px;
}
.content-tree-pane,
.content-file-pane {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 10px 12px;
  overflow: auto;
}
.pane-title {
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-regular);
  word-break: break-all;
}
.tree-empty {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  padding: 12px 0;
}
.tree-node {
  font-size: 13px;
}
.tree-node.is-file {
  cursor: pointer;
}
@media (max-width: 900px) {
  .content-layout {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 768px) {
  .skill-grid {
    grid-template-columns: 1fr;
  }
}
.folder-upload {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.folder-name {
  font-size: 13px;
  color: var(--el-text-color-primary);
}
.folder-placeholder {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
</style>
