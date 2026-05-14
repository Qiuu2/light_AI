<template>
  <div :class="classObj" class="app-wrapper">
    <div v-if="device==='mobile'&&sidebar.opened" class="drawer-bg" @click="handleClickOutside" />
    <sidebar class="sidebar-container" />
    <div class="main-container">
      <div :class="{'fixed-header':fixedHeader}">
        <navbar />
      </div>
      <app-main />
      <ai-assistant-float />
    </div>
  </div>
</template>

<script>
import { Navbar, Sidebar, AppMain } from './components'
import AiAssistantFloat from '@/components/AiAssistantFloat'
import ResizeMixin from './mixin/ResizeHandler'

export default {
  name: 'Layout',
  components: {
    Navbar,
    Sidebar,
    AppMain,
    AiAssistantFloat
  },
  mixins: [ResizeMixin],
  computed: {
    sidebar() {
      return this.$store.state.app.sidebar
    },
    device() {
      return this.$store.state.app.device
    },
    fixedHeader() {
      return this.$store.state.settings.fixedHeader
    },
    classObj() {
      return {
        hideSidebar: !this.sidebar.opened,
        openSidebar: this.sidebar.opened,
        withoutAnimation: this.sidebar.withoutAnimation,
        mobile: this.device === 'mobile'
      }
    }
  },
  watch: {
    device: {
      immediate: true,
      handler() {
        this.syncBodyScrollLock()
      }
    },
    'sidebar.opened'() {
      this.syncBodyScrollLock()
    }
  },
  beforeDestroy() {
    this.releaseBodyScrollLock()
  },
  methods: {
    handleClickOutside() {
      this.$store.dispatch('app/closeSideBar', { withoutAnimation: false })
    },
    syncBodyScrollLock() {
      if (typeof document === 'undefined') return
      const shouldLock = this.device === 'mobile' && this.sidebar.opened
      document.body.classList.toggle('mobile-sidebar-open', shouldLock)
    },
    releaseBodyScrollLock() {
      if (typeof document === 'undefined') return
      document.body.classList.remove('mobile-sidebar-open')
    }
  }
}
</script>

<style lang="scss" scoped>
  @import "~@/styles/mixin.scss";
  @import "~@/styles/variables.scss";

  .app-wrapper {
    @include clearfix;
    position: relative;
    height: 100%;
    width: 100%;
    &.mobile.openSidebar{
      position: fixed;
      top: 0;
    }
  }
  .drawer-bg {
    background: #000;
    opacity: 0.3;
    width: 100%;
    top: 0;
    height: 100%;
    position: absolute;
    z-index: 999;
  }

  .fixed-header {
    position: fixed;
    top: 0;
    right: 0;
    z-index: 9;
    width: calc(100% - #{$sideBarWidth});
    transition: width 0.28s;
  }

  .hideSidebar .fixed-header {
    width: calc(100% - 54px)
  }

  .mobile .fixed-header {
    width: 100%;
  }

  @media (max-width: 768px) {
    .app-wrapper {
      min-height: 100dvh;
    }

    .drawer-bg {
      position: fixed;
    }

    .fixed-header {
      top: 0;
      right: 0;
      left: 0;
      width: 100%;
    }
  }
</style>
