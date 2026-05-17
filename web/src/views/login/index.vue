<template>
  <div class="login-container" :style="backgroundStyle">
    <div class="login-overlay" />
    <div class="login-panel">
      <section class="login-copy">
        <div class="brand-logo-shell">
          <div class="brand-logo-glow" />
          <img :src="brandLogo" :alt="brandName" class="brand-logo">
        </div>
        <div class="brand-text">
          <p class="brand-kicker">{{ brandSubtitle }}</p>
          <h1 class="login-title">
            <span class="title-line">{{ titlePrimary }}</span>
            <span class="title-line">{{ titleSecondary }}</span>
          </h1>
          <p class="login-subtitle">{{ brandDescription }}</p>
        </div>
      </section>

      <section class="login-card">
        <div class="card-header">
          <h2 class="card-title">账号密码登录</h2>
          <p class="card-subtitle">请先确认本站点对应的远端地址，再输入远端平台账号和密码完成身份校验。</p>
        </div>

        <el-alert
          v-if="errorMessage"
          :title="errorMessage"
          type="error"
          :closable="false"
          show-icon
          class="inline-alert"
        />

        <el-form @submit.native.prevent="handleLogin">
          <label class="field-label" for="login-remote-base-url">远端地址</label>
          <div class="remote-input-row">
            <el-input
              id="login-remote-base-url"
              v-model="form.remoteBaseUrl"
              :readonly="remoteBaseUrlLocked"
              :clearable="!remoteBaseUrlLocked"
              placeholder="请输入设备 IP，例如 192.168.1.88"
            />
            <el-button class="remote-edit-button" @click="toggleRemoteBaseUrlEdit">
              {{ remoteBaseUrlLocked ? '修改地址' : '取消修改' }}
            </el-button>
          </div>
          <p class="remote-hint">
            只需填设备 IP（如 192.168.1.88）；端口不是 80 时可写 192.168.1.88:99 这种形式。
          </p>

          <label class="field-label field-gap" for="login-username">账号</label>
          <el-input
            id="login-username"
            v-model.trim="form.username"
            placeholder="请输入账号"
            autocomplete="username"
          />

          <label class="field-label field-gap" for="login-password">密码</label>
          <el-input
            id="login-password"
            v-model="form.password"
            type="password"
            placeholder="请输入密码"
            autocomplete="current-password"
            show-password
            @keyup.enter.native="handleLogin"
          />

          <el-button class="action-button" type="primary" :loading="submitting" @click="handleLogin">
            登录并继续
          </el-button>
        </el-form>
      </section>
    </div>
  </div>
</template>

<script>
import defaultSettings from '@/settings'
import heroBackground from '../../../interface.png'
import brandLogo from '../../../only_logo.png'

const REMOTE_BASE_URL_STORAGE_KEY = 'AI_SPEAKER_REMOTE_BASE_URL'

export default {
  name: 'LoginView',
  data() {
    return {
      submitting: false,
      errorMessage: '',
      remoteBaseUrlLocked: false,
      savedRemoteBaseUrl: '',
      form: {
        remoteBaseUrl: '',
        username: '',
        password: ''
      },
      redirect: '/',
      brandLogo,
      heroBackground
    }
  },
  computed: {
    backgroundStyle() {
      return {
        backgroundImage: `url(${this.heroBackground})`
      }
    },
    brandName() {
      return defaultSettings.brandName || '航天广电AI'
    },
    brandProductName() {
      return defaultSettings.brandProductName || defaultSettings.title || '航天广电AI智慧音响调度平台'
    },
    brandSubtitle() {
      return defaultSettings.brandSubtitle || '智慧音响调度平台'
    },
    brandDescription() {
      return defaultSettings.brandDescription || '面向校园广播、终端联动与智能编排场景打造的一体化智能调度中枢。'
    },
    titlePrimary() {
      return this.brandName
    },
    titleSecondary() {
      const productName = this.brandProductName || ''
      if (productName.startsWith(this.brandName)) {
        const trimmed = productName.slice(this.brandName.length).trim()
        return trimmed || this.brandSubtitle
      }
      return productName || this.brandSubtitle
    }
  },
  created() {
    const redirect = this.$route.query && this.$route.query.redirect
    this.redirect = redirect ? decodeURIComponent(redirect) : '/'
    this.initializeRemoteBaseUrl()
  },
  methods: {
    getIncomingSearchValue(key) {
      const search = new URLSearchParams(window.location.search || '')
      const value = search.get(key)
      return value ? String(value).trim() : ''
    },
    normalizeRemoteApiPath(path) {
      const text = String(path || '').trim()
      if (!text) return ''
      const normalized = text.startsWith('/') ? text : `/${text}`
      return normalized.replace(/\/+$/, '') || '/'
    },
    inferRemoteBaseUrlFromLocation() {
      const protocol = String(window.location.protocol || '').trim()
      const hostname = String(window.location.hostname || '').trim()
      const port = String(defaultSettings.remoteApiPort || '').trim()
      const path = this.normalizeRemoteApiPath(defaultSettings.remoteApiPath)
      if (!protocol || !hostname) return ''
      return `${protocol}//${hostname}${port ? `:${port}` : ''}${path}`
    },
    storageAvailable() {
      try {
        return Boolean(window && window.localStorage)
      } catch (error) {
        return false
      }
    },
    persistConfirmedRemoteBaseUrl(remoteBaseUrl) {
      const value = String(remoteBaseUrl || '').trim()
      if (!value || !this.storageAvailable()) return
      window.localStorage.setItem(REMOTE_BASE_URL_STORAGE_KEY, value)
    },
    getSavedRemoteBaseUrl() {
      if (!this.storageAvailable()) return ''
      return String(window.localStorage.getItem(REMOTE_BASE_URL_STORAGE_KEY) || '').trim()
    },
    initializeRemoteBaseUrl() {
      const explicitRemoteBaseUrl =
        this.getIncomingSearchValue('remote_base_url') ||
        this.getIncomingSearchValue('remoteBaseUrl') ||
        String((this.$route.query && (this.$route.query.remote_base_url || this.$route.query.remoteBaseUrl)) || '').trim()
      if (explicitRemoteBaseUrl) {
        this.form.remoteBaseUrl = explicitRemoteBaseUrl
        this.savedRemoteBaseUrl = this.getSavedRemoteBaseUrl()
        this.remoteBaseUrlLocked = false
        return
      }
      const savedRemoteBaseUrl = this.getSavedRemoteBaseUrl()
      this.savedRemoteBaseUrl = savedRemoteBaseUrl
      if (savedRemoteBaseUrl) {
        this.form.remoteBaseUrl = savedRemoteBaseUrl
        this.remoteBaseUrlLocked = true
      }
    },
    toggleRemoteBaseUrlEdit() {
      if (this.remoteBaseUrlLocked) {
        this.remoteBaseUrlLocked = false
        return
      }
      this.form.remoteBaseUrl = this.savedRemoteBaseUrl
      this.remoteBaseUrlLocked = Boolean(this.savedRemoteBaseUrl)
    },
    normalizeRemoteBaseUrl(raw) {
      // 用户只填 IP（如 192.168.1.88 或 192.168.1.88:99）时自动补 http:// 前缀。
      // 已有 http:// / https:// 的保持不动。末尾的 / 去掉。
      const trimmed = String(raw || '').trim().replace(/\/+$/, '')
      if (!trimmed) return ''
      if (/^https?:\/\//i.test(trimmed)) return trimmed
      return `http://${trimmed}`
    },
    async handleLogin() {
      const normalizedRemote = this.normalizeRemoteBaseUrl(this.form.remoteBaseUrl)
      if (!normalizedRemote) {
        this.errorMessage = '请输入设备 IP'
        return
      }
      this.form.remoteBaseUrl = normalizedRemote
      if (!this.form.username || !this.form.password) {
        this.errorMessage = '请输入完整的账号和密码'
        return
      }
      this.submitting = true
      this.errorMessage = ''
      try {
        await this.$store.dispatch('user/login', this.form)
        this.persistConfirmedRemoteBaseUrl(this.form.remoteBaseUrl)
        this.savedRemoteBaseUrl = String(this.form.remoteBaseUrl || '').trim()
        this.remoteBaseUrlLocked = Boolean(this.savedRemoteBaseUrl)
        this.$router.replace(this.redirect || '/')
      } catch (error) {
        const detail = error && error.response && error.response.data && error.response.data.detail
        this.errorMessage = (detail && detail.message) || (typeof detail === 'string' ? detail : '') || error.message || '登录失败'
      } finally {
        this.submitting = false
      }
    }
  }
}
</script>

<style lang="scss" scoped>
.login-container {
  position: relative;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px;
  overflow: hidden;
  background-repeat: no-repeat;
  background-size: cover;
  background-position: center;
}

.login-overlay {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(circle at 52% 44%, rgba(108, 160, 255, 0.18) 0%, rgba(108, 160, 255, 0.08) 18%, transparent 42%),
    linear-gradient(90deg, rgba(3, 8, 19, 0.84) 0%, rgba(6, 13, 27, 0.68) 30%, rgba(6, 13, 27, 0.5) 54%, rgba(5, 10, 21, 0.76) 100%),
    linear-gradient(180deg, rgba(2, 6, 15, 0.34), rgba(2, 6, 15, 0.62));
}

.login-panel {
  position: relative;
  z-index: 1;
  width: min(1180px, 100%);
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(360px, 430px);
  gap: 72px;
  align-items: center;
}

.login-copy {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  min-height: 640px;
  padding-left: clamp(12px, 3vw, 48px);
  color: #f3f7ff;
}

.brand-logo-shell {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: min(520px, 92%);
  min-height: 124px;
  margin-bottom: 30px;
}

.brand-logo-glow {
  position: absolute;
  inset: auto 14% -10% 14%;
  height: 52%;
  border-radius: 999px;
  background: radial-gradient(circle, rgba(250, 204, 94, 0.14) 0%, rgba(250, 204, 94, 0.05) 40%, transparent 72%);
  filter: blur(26px);
  opacity: 0.86;
  pointer-events: none;
}

.brand-logo {
  position: relative;
  z-index: 1;
  width: min(100%, 420px);
  display: block;
  filter:
    drop-shadow(0 10px 26px rgba(4, 9, 20, 0.24))
    drop-shadow(0 0 18px rgba(255, 210, 98, 0.06));
}

.brand-text {
  max-width: 560px;
}

.brand-kicker {
  margin: 0 0 14px;
  font-size: 18px;
  letter-spacing: 0.28em;
  color: rgba(201, 214, 239, 0.78);
}

.login-title {
  margin: 0;
  font-weight: 700;
  font-size: clamp(42px, 5.1vw, 64px);
  line-height: 1.05;
  letter-spacing: 0.01em;
}

.title-line {
  display: block;
}

.login-subtitle {
  max-width: 520px;
  margin: 22px 0 0;
  font-size: 20px;
  line-height: 1.85;
  color: rgba(220, 229, 244, 0.8);
}

.login-card {
  position: relative;
  padding: 34px 28px 30px;
  border-radius: 28px;
  border: 1px solid rgba(145, 181, 255, 0.24);
  background:
    linear-gradient(180deg, rgba(30, 43, 73, 0.3), rgba(11, 20, 38, 0.76)),
    rgba(8, 15, 29, 0.7);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.1),
    0 20px 48px rgba(2, 8, 19, 0.34);
  backdrop-filter: blur(20px);
}

.login-card::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background:
    radial-gradient(circle at top left, rgba(109, 151, 255, 0.14), transparent 36%),
    radial-gradient(circle at bottom right, rgba(255, 255, 255, 0.06), transparent 28%);
  pointer-events: none;
}

.card-header,
.inline-alert,
.field-label,
.remote-hint,
.action-button,
::v-deep .el-input {
  position: relative;
  z-index: 1;
}

.card-header {
  margin-bottom: 26px;
}

.card-title {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  color: #f4f7ff;
}

.card-subtitle {
  margin: 12px 0 0;
  font-size: 14px;
  line-height: 1.8;
  color: rgba(208, 220, 243, 0.76);
}

.field-label {
  display: block;
  margin-bottom: 10px;
  font-size: 15px;
  font-weight: 600;
  color: rgba(232, 239, 250, 0.88);
}

.field-gap {
  margin-top: 20px;
}

.inline-alert {
  margin-bottom: 18px;
}

.remote-hint {
  margin: 10px 0 0;
  font-size: 12px;
  line-height: 1.7;
  color: rgba(197, 211, 235, 0.7);
}

.remote-input-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 108px;
  gap: 10px;
  align-items: center;
}

.remote-edit-button {
  width: 108px;
  height: 54px;
  border-radius: 999px;
  font-size: 14px;
  font-weight: 600;
}

.action-button {
  width: 100%;
  height: 54px;
  margin-top: 24px;
  border: 1px solid rgba(177, 203, 255, 0.2);
  border-radius: 999px;
  background: linear-gradient(180deg, rgba(124, 150, 202, 0.86), rgba(92, 112, 154, 0.9));
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.16),
    0 14px 28px rgba(7, 16, 31, 0.22);
  font-size: 18px;
  font-weight: 600;
}

::v-deep .el-input__inner {
  height: 54px;
  line-height: 54px;
  padding: 0 20px;
  border: 1px solid rgba(164, 193, 250, 0.18);
  border-radius: 999px;
  background: rgba(79, 91, 122, 0.34);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.08),
    inset 0 -10px 20px rgba(4, 9, 20, 0.14);
  color: #f4f7ff;
}

::v-deep .el-input__inner::placeholder {
  color: rgba(197, 211, 235, 0.42);
}

@media (max-width: 1080px) {
  .login-panel {
    gap: 40px;
  }

  .login-copy {
    min-height: auto;
    padding-left: 0;
  }
}

@media (max-width: 960px) {
  .login-container {
    padding: 24px 18px;
  }

  .login-panel {
    grid-template-columns: 1fr;
  }

  .login-copy {
    align-items: center;
    text-align: center;
    min-height: auto;
    padding-top: 24px;
  }

  .brand-logo-shell {
    width: min(520px, 100%);
  }

  .brand-text,
  .login-subtitle {
    max-width: 100%;
  }

  .login-card {
    width: min(430px, 100%);
    margin: 0 auto;
  }
}

@media (max-width: 640px) {
  .login-container {
    padding: 20px 14px;
  }

  .brand-logo-shell {
    min-height: 108px;
  }

  .brand-logo {
    width: min(100%, 340px);
  }

  .brand-kicker {
    font-size: 15px;
    letter-spacing: 0.2em;
  }

  .login-title {
    font-size: clamp(34px, 10vw, 46px);
  }

  .login-subtitle {
    margin-top: 16px;
    font-size: 16px;
    line-height: 1.75;
  }

  .login-card {
    padding: 28px 20px 24px;
    border-radius: 24px;
  }
}
</style>
