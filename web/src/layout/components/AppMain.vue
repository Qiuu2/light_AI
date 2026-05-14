<template>
  <section class="app-main">
    <transition name="fade-transform" mode="out-in">
      <router-view :key="key" />
    </transition>
  </section>
</template>

<script>
export default {
  name: 'AppMain',
  computed: {
    key() {
      return this.$route.path
    }
  }
}
</script>

<style scoped>
.app-main {
  min-height: calc(100vh - 50px);
  min-height: calc(100dvh - 50px);
  width: 100%;
  position: relative;
  overflow: visible;
}
.fixed-header+.app-main {
  padding-top: 50px;
}

@media (max-width: 768px) {
  .fixed-header+.app-main {
    padding-top: calc(50px + env(safe-area-inset-top));
  }
}
</style>

<style lang="scss">
// fix css style bug in open el-dialog
.el-popup-parent--hidden {
  .fixed-header {
    padding-right: 15px;
  }
}
</style>
