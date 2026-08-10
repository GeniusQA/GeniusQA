<template>
  <el-form ref="loginFormRef" :model="state.ruleForm" :rules="loginRules" size="large" class="login-content-form" :validate-on-rule-change="false">
    <el-form-item class="login-animation1" prop="userName">
      <el-input text placeholder="请输入用户名" v-model="state.ruleForm.userName" clearable
                autocomplete="off">
        <template #prefix>
          <el-icon class="el-input__icon">
            <ele-User/>
          </el-icon>
        </template>
      </el-input>
    </el-form-item>
    <el-form-item class="login-animation2" prop="password">
      <el-input :type="state.isShowPassword ? 'text' : 'password'" placeholder="请输入登录密码"
                v-model="state.ruleForm.password" autocomplete="off">
        <template #prefix>
          <el-icon class="el-input__icon">
            <ele-Unlock/>
          </el-icon>
        </template>
        <template #suffix>
          <i
              class="iconfont el-input__icon login-content-password"
              :class="state.isShowPassword ? 'icon-yincangmima' : 'icon-xianshimima'"
              @click="state.isShowPassword = !state.isShowPassword"
          >
          </i>
        </template>
      </el-input>
    </el-form-item>
    <el-form-item v-if="captchaEnable" class="login-animation3" prop="code">
      <div class="captcha-row">
        <div class="captcha-input-wrap">
          <el-input text maxlength="8" placeholder="请输入验证码" v-model="state.ruleForm.code" clearable
                    autocomplete="off" @keyup.enter="onSignIn">
            <template #prefix>
              <el-icon class="el-input__icon">
                <ele-Position/>
              </el-icon>
            </template>
          </el-input>
        </div>
        <div class="captcha-img-wrap">
          <Captcha
            ref="captchaRef"
            :img-base="captchaImg"
            :width="100"
            :height="40"
            @refresh="loadCaptcha"
          />
        </div>
      </div>
    </el-form-item>
    <el-form-item class="login-animation4">
      <el-button type="primary" class="login-content-submit" v-waves @click="onSignIn"
                 :loading="state.loading.signIn">
        <span>登 录</span>
      </el-button>
    </el-form-item>
  </el-form>
</template>

<script setup lang="ts" name="loginAccount">
import {computed, onMounted, reactive, ref} from 'vue';
import {useRoute, useRouter} from 'vue-router';
import {ElMessage} from 'element-plus';
import Captcha from '/@/components/Captcha/index.vue';
import {initBackEndControlRoutes} from '/@/router/backEnd';
import {Session} from '/@/utils/storage';
import {formatAxis} from '/@/utils/formatTime';
import {NextLoading} from '/@/utils/loading';
import {useUserApi} from "/@/api/v1/system/user";
import {useAuthApi} from "/@/api/v1/system/auth";
import {useUserStore} from "/@/stores/user";

const loginFormRef = ref();
const captchaRef = ref();
const route = useRoute();
const router = useRouter();

const captchaEnable = ref(true);
const captchaKey = ref('');
const captchaImg = ref('');

const state = reactive({
  isShowPassword: false,
  ruleForm: {
    userName: '',
    password: '',
    code: '',
  },
  loading: {
    signIn: false,
  },
});

const loginRules = computed(() => {
  const rules: Record<string, any[]> = {
    userName: [
      { required: true, message: '请输入用户名' },
      { min: 2, max: 20, message: '用户名长度在 2 到 20 个字符' }
    ],
    password: [
      { required: true, message: '请输入密码' },
      { min: 6, max: 20, message: '密码长度在 6 到 20 个字符' }
    ],
  };
  if (captchaEnable.value) {
    rules.code = [
      { required: true, message: '请输入验证码' },
      { min: 3, max: 8, message: '验证码长度不正确' },
    ];
  }
  return rules;
});

async function loadCaptcha() {
  try {
    const res: any = await useAuthApi().getCaptcha();
    const data = res?.data ?? res ?? {};
    captchaEnable.value = data.enable !== false;
    captchaKey.value = data.key || '';
    captchaImg.value = data.img_base || '';
    state.ruleForm.code = '';
  } catch (e) {
    console.error('获取验证码失败', e);
    captchaEnable.value = true;
  }
}

const currentTime = computed(() => {
  return formatAxis(new Date());
});

const onSignIn = async () => {
  if (!loginFormRef.value) return;

  await loginFormRef.value.validate((valid: boolean) => {
    if (!valid) {
      ElMessage.error('请检查输入信息');
      if (captchaEnable.value) {
        loadCaptcha();
      }
      return false;
    }

    state.loading.signIn = true;
    const payload: {
      username: string;
      password: string;
      captcha?: string;
      captcha_key?: string;
    } = {
      username: state.ruleForm.userName,
      password: state.ruleForm.password,
    };
    if (captchaEnable.value) {
      payload.captcha = state.ruleForm.code;
      payload.captcha_key = captchaKey.value;
    }

    useUserApi().signIn(payload)
        .then(async res => {
          const token = res.data.access_token || res.data.token;
          Session.set('token', token);
          if (res.data.refresh_token) {
            Session.set('refresh_token', res.data.refresh_token);
          }
          await useUserStore().setUserInfos();
          await initBackEndControlRoutes();
          signInSuccess(false);
        })
        .catch((e) => {
          console.log('错误信息： ', e)
          ElMessage.error(e?.message || '登录失败');
          state.loading.signIn = false;
          if (captchaEnable.value) {
            loadCaptcha();
          }
        })
  });
};

const signInSuccess = (isNoPower: boolean) => {
  if (isNoPower) {
    ElMessage.warning('抱歉，您没有登录权限');
    Session.clear();
  } else {
    let currentTimeInfo = currentTime.value;
    const params = route.query!.params || {}
    if (route.query?.redirect) {
      router.push({
        path: route.query?.redirect as string,
        query: Object.keys(params).length > 0 ? JSON.parse(params as any) : '',
      });
    } else {
      router.push('/home');
    }
    const signInText = '欢迎回来！';
    ElMessage.success(`${currentTimeInfo}，${signInText}`);
    NextLoading.start();
  }
  state.loading.signIn = false;
};

onMounted(() => {
  loadCaptcha();
});
</script>

<style scoped lang="scss">
.login-content-form {
  margin-top: 0;
  border: none;

  @for $i from 1 through 4 {
    .login-animation#{$i} {
      opacity: 0;
      animation-name: error-num;
      animation-duration: 0.5s;
      animation-fill-mode: forwards;
      animation-delay: calc($i / 10) + s;
    }
  }

  .login-content-password {
    display: inline-block;
    width: 20px;
    cursor: pointer;

    &:hover {
      color: var(--el-text-color-secondary);
    }
  }

  .login-content-code {
    width: 100%;
    padding: 0;
    font-weight: 600;
    letter-spacing: 5px;
    border-radius: 8px;
  }

  .login-content-submit {
    width: 100%;
    height: 40px;
    margin-top: 8px;
    border-radius: 8px;
    font-weight: 500;
    letter-spacing: 2px;
  }

  .login-animation4 {
    margin-bottom: 0;

    :deep(.el-form-item__content) {
      border-bottom: none !important;
    }
  }
}

.captcha-form-item {
  :deep(.el-form-item__content) {
    flex-wrap: nowrap;
  }
}
.captcha-row {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}
.captcha-input-wrap {
  flex: 1;
  min-width: 0;
}
.captcha-img-wrap {
  flex-shrink: 0;
  display: flex;
  align-items: center;

  :deep(.login-content-code) {
    height: 40px;
  }
}

@media (max-width: 480px) {
  .captcha-row {
    gap: 6px;
  }
  .login-content-submit {
    height: 44px !important;
    font-size: 15px;
  }
  .captcha-img-wrap :deep(.captcha-img),
  .captcha-img-wrap :deep(.captcha-placeholder) {
    width: 80px !important;
    height: 36px !important;
  }
}
</style>
