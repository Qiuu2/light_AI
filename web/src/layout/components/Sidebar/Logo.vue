<template>
  <div class="sidebar-logo-container" :class="{ collapse: collapse }">
    <transition name="sidebarLogoFade">
      <router-link
        :key="collapse ? 'collapse' : 'expand'"
        class="sidebar-logo-link"
        :class="{ 'is-collapse': collapse }"
        to="/"
      >
        <img :src="brandLogo" alt="浩探AI" class="sidebar-brand-logo">
      </router-link>
    </transition>
  </div>
</template>

<script>
import brandLogo from '../../../../only_logo.png'

export default {
  name: 'SidebarLogo',
  props: {
    collapse: {
      type: Boolean,
      required: true
    }
  },
  data() {
    return {
      brandLogo
    }
  }
}
</script>

<style lang="scss" scoped>
.sidebarLogoFade-enter-active {
  transition: opacity 0.35s ease;
}

.sidebarLogoFade-enter,
.sidebarLogoFade-leave-to {
  opacity: 0;
}

.sidebar-logo-container {
  width: 100%;
  height: 118px;
  padding: 12px 12px 14px;

  &.collapse {
    height: 68px;
    padding: 8px 8px 6px;
  }
}

.sidebar-logo-link {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  text-decoration: none;
}

.sidebar-brand-logo {
  width: min(100%, 188px);
  max-height: 78px;
  object-fit: contain;
  filter:
    drop-shadow(0 6px 14px rgba(5, 10, 20, 0.12))
    drop-shadow(0 0 8px rgba(249, 206, 99, 0.03));
}

.is-collapse .sidebar-brand-logo {
  width: min(100%, 40px);
  max-height: 40px;
}
</style>
