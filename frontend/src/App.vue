<template>
  <el-config-provider :size="getGlobalComponentSize" :locale="zhCn">
    <router-view v-show="setLockScreen"/>
    <LockScreen v-if="themeConfig.isLockScreen"/>
    <Settings ref="settingsRef" v-show="setLockScreen"/>
    <CloseFull v-if="!themeConfig.isLockScreen"/>
    <Upgrade v-if="getVersion"/>
  </el-config-provider>
</template>

<script setup lang="ts">
import { defineAsyncComponent, computed, ref, onBeforeMount, onMounted, onUnmounted, nextTick, watch } from 'vue';
import { useRoute } from 'vue-router';
import zhCn from 'element-plus/es/locale/lang/zh-cn';
import { storeToRefs } from "/@/stores";
import { useTagsViewRoutes } from '/@/stores/tagsViewRoutes';
import { useThemeConfig } from '/@/stores/themeConfig';
import other from '/@/utils/other';
import { Local, Session } from '/@/utils/storage';
import mittBus from '/@/utils/mitt';
import setIntroduction from '/@/utils/setIconfont';
import LockScreen from "/@/layout/lockScreen/index.vue"

defineOptions({ name: 'App' })

// 引入组件
// const LockScreen = defineAsyncComponent(() => import('/@/layout/lockScreen/index.vue'));
const Settings = defineAsyncComponent(() => import('/@/layout/navBars/topBar/settings/index.vue'));
const CloseFull = defineAsyncComponent(() => import('/@/layout/navBars/topBar/closeFull.vue'));
const Upgrade = defineAsyncComponent(() => import('/@/layout/upgrade/index.vue'));

// 定义变量内容
const settingsRef = ref();
const route = useRoute();
const stores = useTagsViewRoutes();
const storesThemeConfig = useThemeConfig();
const { themeConfig } = storeToRefs(storesThemeConfig);

// 设置锁屏时组件显示隐藏
const setLockScreen = computed(() => {
  // 防止锁屏后，刷新出现不相关界面
  return themeConfig.value.isLockScreen ? themeConfig.value.lockScreenTime > 1 : themeConfig.value.lockScreenTime >= 0;
});

// 获取版本号
const getVersion = computed(() => {
  let isVersion = false;
  if (route.path !== '/login') {
    // @ts-ignore
    if ((Local.get('version') && Local.get('version') !== __VERSION__) || !Local.get('version')) isVersion = true;
  }
  return isVersion;
});
// 获取全局组件大小
const getGlobalComponentSize = computed(() => {
  return other.globalComponentSize();
});
// ── 按需服务心跳：页面可见时每 30s ping /healthz（经网关），隐藏/关闭时停止 ──
let heartbeatTimer: any = null;
const startHeartbeat = () => {
  stopHeartbeat();
  const ping = () => {
    try {
      // 相对路径：经域名访问时走网关，保持按需服务存活；静默失败不影响页面
      fetch('/api/v1/Ntesterc_api/healthz', { cache: 'no-store' }).catch(() => {});
    } catch { /* ignore */ }
  };
  ping();
  heartbeatTimer = setInterval(ping, 30000);
};
const stopHeartbeat = () => {
  if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = null; }
};
const onVisibility = () => {
  if (document.visibilityState === 'visible') startHeartbeat();
  else stopHeartbeat();
};

// 设置初始化，防止刷新时恢复默认
onBeforeMount(() => {
  // 设置批量第三方 icon 图标
  setIntroduction.cssCdn();
  // 设置批量第三方 js
  setIntroduction.jsCdn();
});
// 页面加载时
onMounted(() => {
  nextTick(() => {
    // 监听布局配'置弹窗点击打开
    mittBus.on('openSettingsDrawer', () => {
      settingsRef.value.openDrawer();
    });
    // 获取缓存中的布局配置
    if (Local.get('themeConfig')) {
      const savedConfig = Local.get('themeConfig');
      // 兼容旧拼写 wartermark -> watermark（v2.0.3 修正）
      if (savedConfig && ('isWartermark' in savedConfig || 'wartermarkText' in savedConfig)) {
        if ('isWartermark' in savedConfig) {
          savedConfig.isWatermark = savedConfig.isWartermark;
          delete savedConfig.isWartermark;
        }
        if ('wartermarkText' in savedConfig) {
          savedConfig.watermarkText = savedConfig.wartermarkText;
          delete savedConfig.wartermarkText;
        }
        Local.set('themeConfig', savedConfig);
      }
      storesThemeConfig.setThemeConfig({ themeConfig: savedConfig });
      document.documentElement.style.cssText = Local.get('themeConfigStyle');
    }
    // 获取缓存中的全屏配置
    if (Session.get('isTagsViewCurrenFull')) {
      stores.setCurrenFullscreen(Session.get('isTagsViewCurrenFull'));
    }
  });
});
// 页面销毁时，关闭监听布局配置/i18n监听
onMounted(() => {
  startHeartbeat();
  document.addEventListener('visibilitychange', onVisibility);
});
onUnmounted(() => {
  stopHeartbeat();
  document.removeEventListener('visibilitychange', onVisibility);
});
onUnmounted(() => {
  mittBus.off('openSettingsDrawer', () => {
  });
});
// 监听路由的变化，设置网站标题
watch(
    () => route.path,
    () => {
      other.useTitle();
    },
    {
      deep: true,
    }
);
</script>
