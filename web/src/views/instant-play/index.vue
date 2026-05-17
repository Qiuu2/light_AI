<!--
  即时播放 — 左表单 + 右状态卡片

  接口（不动）:
    fetchLightResources    GET   /api/light/resources         （媒体/终端选项）
    startInstantPlay       POST  /api/light/instant-play
    stopInstantPlay        POST  /api/light/instant-play/stop
-->
<template>
  <div class="light-page">
    <page-header
      title="即时播放"
      subtitle="临时调用设备实时播放接口；未选择媒体时不会发送 media 字段"
    >
      <template #status>
        <el-tag v-if="playing" size="small" type="warning" effect="plain">
          <i class="el-icon-loading" />
          正在播放
        </el-tag>
      </template>
      <el-button size="small" icon="el-icon-refresh" :loading="loading" @click="loadResources">
        刷新资源
      </el-button>
    </page-header>

    <div class="lt-instant-layout">
      <!-- 左：表单 -->
      <el-card shadow="never" class="lt-instant-form">
        <div slot="header" class="lt-instant-form__h">
          <span>播放参数</span>
          <span class="lt-muted lt-tiny">填写完成后点击执行</span>
        </div>

        <el-form size="small" label-width="92px">
          <el-row :gutter="14">
            <el-col :span="12">
              <el-form-item label="媒体">
                <el-select
                  v-model="selectedMedia"
                  multiple filterable allow-create default-first-option
                  class="lt-full" placeholder="可不选"
                >
                  <el-option
                    v-for="it in mediaOptions"
                    :key="it.value"
                    :label="it.label"
                    :value="it.value"
                  />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="终端 / 分组">
                <el-select
                  v-model="selectedTerminal"
                  multiple filterable allow-create default-first-option
                  class="lt-full" placeholder="如 1_70, 2_447"
                >
                  <el-option
                    v-for="it in terminalOptions"
                    :key="it.value"
                    :label="it.label"
                    :value="it.value"
                  />
                </el-select>
              </el-form-item>
            </el-col>

            <el-col :span="8">
              <el-form-item label="播放模式">
                <el-select v-model="form.playmode" class="lt-full">
                  <el-option label="按时长" value="0" />
                  <el-option label="按次数" value="1" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="10">
              <el-form-item label="时长">
                <div class="lt-time-with-unit">
                  <el-input v-model="form.timehour" :disabled="isByCount" />
                  <span class="lt-unit">时</span>
                  <el-input v-model="form.timeminute" :disabled="isByCount" />
                  <span class="lt-unit">分</span>
                  <el-input v-model="form.timesecond" :disabled="isByCount" />
                  <span class="lt-unit">秒</span>
                </div>
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="次数">
                <el-input v-model="form.times" :disabled="!isByCount" />
              </el-form-item>
            </el-col>

            <el-col :span="16">
              <el-form-item label="音量">
                <div class="lt-volume-row">
                  <el-slider v-model="volumeNum" :min="0" :max="100" class="lt-volume-slider" />
                  <el-input-number
                    v-model="volumeNum"
                    :min="0"
                    :max="100"
                    size="small"
                    controls-position="right"
                    class="lt-volume-input"
                  />
                </div>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="播放顺序">
                <el-select v-model="form.random" class="lt-full">
                  <el-option label="顺序" value="0" />
                  <el-option label="随机" value="1" />
                </el-select>
              </el-form-item>
            </el-col>

            <el-col :span="24">
              <el-form-item label="本地分区">
                <zone-chips
                  :value="checkedAreas"
                  :keys="['area0','area1','area2','area3','area4','area5']"
                  :labels="['分区1','分区2','分区3','分区4','分区5','分区6']"
                  @update:value="checkedAreas = $event"
                />
              </el-form-item>
            </el-col>

            <el-col :span="24">
              <el-form-item label="电源">
                <el-checkbox :value="checkedAreas.includes('area6')" @change="togglePower('area6', $event)">
                  功放电源
                </el-checkbox>
                <el-checkbox :value="checkedAreas.includes('area7')" @change="togglePower('area7', $event)">
                  外控电源
                </el-checkbox>
              </el-form-item>
            </el-col>
          </el-row>
        </el-form>

        <div class="lt-instant-form__footer">
          <el-button
            type="primary"
            size="small"
            icon="el-icon-video-play"
            :loading="submitting"
            @click="submit"
          >
            执行即时播放
          </el-button>
          <el-button
            size="small"
            type="danger"
            plain
            icon="el-icon-video-pause"
            :loading="stopping"
            :disabled="!playing"
            @click="stopNow"
          >
            停止即时播放
          </el-button>
          <el-button size="small" @click="resetForm">重置</el-button>
        </div>
      </el-card>

      <!-- 右：状态 -->
      <play-status-card
        :playing="playing"
        :active-zones="checkedAreas"
        :media-label="mediaLabel"
        :terminal-label="terminalLabel"
        :duration-label="durationLabel"
      />
    </div>

    <el-card v-if="lastRaw" shadow="never" class="lt-raw-card">
      <div slot="header" class="lt-raw-card__h">
        <span>最近一次接口响应</span>
        <el-button type="text" size="mini" @click="lastRaw = ''">关闭</el-button>
      </div>
      <pre class="lt-raw-card__pre">{{ lastRaw }}</pre>
    </el-card>
  </div>
</template>

<script>
import { fetchLightResources, startInstantPlay, stopInstantPlay } from '@/api/lightService'
import PageHeader from '@/components/PageHeader'
import ZoneChips from './components/ZoneChips.vue'
import PlayStatusCard from './components/PlayStatusCard.vue'

function listFromPayload(payload) {
  if (Array.isArray(payload)) return payload
  if (!payload || typeof payload !== 'object') return []
  if (Array.isArray(payload.data)) return payload.data
  if (payload.data && Array.isArray(payload.data.data)) return payload.data.data
  if (Array.isArray(payload.rows)) return payload.rows
  if (Array.isArray(payload.list)) return payload.list
  return []
}

function optionLabel(item) {
  return item.label || item.text || item.name || item.medianame ||
         item.terminalname || item.ip || item.id || item.mediaid ||
         item.terminalid || ''
}

function treeLeafOptions(payload, valuePrefix = '') {
  const options = []
  const walk = (node) => {
    if (Array.isArray(node)) { node.forEach(walk); return }
    if (!node || typeof node !== 'object') return
    if (Array.isArray(node.item) && node.item.length) { node.item.forEach(walk); return }
    const rawId = node.id || node.value || node.code
    if (rawId === undefined || rawId === null || rawId === '') return
    const id = String(rawId).trim()
    if (!id || id.indexOf('dir_') === 0) return
    const value = valuePrefix && !id.startsWith('1_') && !id.startsWith('2_')
      ? `${valuePrefix}${id}` : id
    options.push({
      value,
      label: String(node.text || node.name || node.label || optionLabel(node) || id),
      raw: node
    })
  }
  walk(payload)
  return options
}

export default {
  name: 'InstantPlay',
  components: { PageHeader, ZoneChips, PlayStatusCard },

  data() {
    return {
      loading: false,
      submitting: false,
      stopping: false,
      playing: false,
      resources: {},
      selectedMedia: [],
      selectedTerminal: [],
      // area0-5 默认 6 个分区全选 + 功放(area6) 默认勾，外控(area7) 默认不勾
      checkedAreas: ['area0', 'area1', 'area2', 'area3', 'area4', 'area5', 'area6'],
      lastRaw: '',
      form: this.defaultForm()
    }
  },

  computed: {
    volumeNum: {
      get() {
        const n = Number(this.form.volume)
        return Number.isFinite(n) ? n : 80
      },
      set(v) { this.form.volume = String(v) }
    },
    // 播放模式：'0'=按时长（time* 可用，times 灰）；'1'=按次数（反之）
    isByCount() {
      return String(this.form.playmode) === '1'
    },
    mediaOptions() {
      const normalized = listFromPayload(this.resources.media_options)
      if (normalized.length) return normalized
      const treeOptions = treeLeafOptions(this.resources.media)
      if (treeOptions.length) return treeOptions
      return listFromPayload(this.resources.media)
        .map((item) => ({
          value: String(item.mediaid || item.id || item.media_id || optionLabel(item)),
          label: String(optionLabel(item))
        }))
        .filter((it) => it.value)
    },
    terminalOptions() {
      const normalized = listFromPayload(this.resources.terminal_options)
      if (normalized.length) return normalized
      const treeOptions = treeLeafOptions(this.resources.terminal, '2_')
      if (treeOptions.length) return treeOptions
      return listFromPayload(this.resources.terminal)
        .map((item) => {
          const id = item.terminalid || item.id || item.terminal_id || optionLabel(item)
          return {
            value: String(item.value || item.code || id),
            label: String(optionLabel(item))
          }
        })
        .filter((it) => it.value)
    },
    mediaLabel() {
      if (!this.selectedMedia.length) return ''
      const map = {}
      this.mediaOptions.forEach((o) => { map[o.value] = o.label })
      return this.selectedMedia.map((v) => map[v] || v).join('、')
    },
    terminalLabel() {
      if (!this.selectedTerminal.length) return ''
      const map = {}
      this.terminalOptions.forEach((o) => { map[o.value] = o.label })
      return this.selectedTerminal.map((v) => map[v] || v).join('、')
    },
    durationLabel() {
      const mode = String(this.form.playmode) === '1' ? '次数' : '时长'
      if (mode === '次数') return `按次数 · ${this.form.times} 次`
      const h = Number(this.form.timehour) || 0
      const m = Number(this.form.timeminute) || 0
      const s = Number(this.form.timesecond) || 0
      return `按时长 · ${h}时${m}分${s}秒`
    }
  },

  created() { this.loadResources() },

  methods: {
    defaultForm() {
      return {
        playmode: '0',
        timehour: '0',
        timeminute: '2',
        timesecond: '0',
        times: '1',
        volume: '80',
        random: '0'
      }
    },
    async loadResources() {
      this.loading = true
      try {
        const resp = await fetchLightResources()
        this.resources = (resp && resp.data) || {}
      } catch (err) {
        this.$message.error(this.errorText(err, '加载资源失败'))
      } finally {
        this.loading = false
      }
    },
    togglePower(key, checked) {
      const next = this.checkedAreas.slice()
      const idx = next.indexOf(key)
      if (checked && idx === -1) next.push(key)
      else if (!checked && idx !== -1) next.splice(idx, 1)
      this.checkedAreas = next
    },
    buildPayload() {
      const payload = {
        media: this.selectedMedia.join(','),
        terminal: this.selectedTerminal.join(','),
        playmode: this.form.playmode,
        timehour: this.form.timehour,
        timeminute: this.form.timeminute,
        timesecond: this.form.timesecond,
        times: this.form.times,
        volume: String(this.form.volume),
        random: this.form.random
      }
      const allAreas = ['area0','area1','area2','area3','area4','area5','area6','area7']
      allAreas.forEach((k) => { payload[k] = this.checkedAreas.includes(k) ? '1' : '0' })
      Object.keys(payload).forEach((k) => {
        if (payload[k] === '' || payload[k] === undefined || payload[k] === null) delete payload[k]
      })
      return payload
    },
    async submit() {
      this.submitting = true
      try {
        const resp = await startInstantPlay(this.buildPayload())
        const ok = resp && resp.success !== false
        this.showResult(resp, '即时播放请求已提交')
        if (ok) this.playing = true
      } catch (err) {
        this.$message.error(this.errorText(err, '即时播放失败'))
      } finally {
        this.submitting = false
      }
    },
    async stopNow() {
      this.stopping = true
      try {
        const resp = await stopInstantPlay()
        const ok = resp && resp.success !== false
        this.showResult(resp, '停止即时播放请求已提交')
        if (ok) this.playing = false
      } catch (err) {
        this.$message.error(this.errorText(err, '停止失败'))
      } finally {
        this.stopping = false
      }
    },
    resetForm() {
      this.form = this.defaultForm()
      this.selectedMedia = []
      this.selectedTerminal = []
      this.checkedAreas = ['area0','area1','area2','area3','area4','area5','area6']
    },
    showResult(resp, fallback) {
      this.lastRaw = JSON.stringify(resp, null, 2)
      const ok = resp && resp.success !== false
      this.$message[ok ? 'success' : 'warning']((resp && resp.message) || fallback)
    },
    errorText(err, fallback) {
      return err && err.response && err.response.data && err.response.data.detail
        ? err.response.data.detail
        : fallback
    }
  }
}
</script>

<style lang="scss" scoped>
.lt-instant-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: 12px;
  align-items: start;
}
.lt-instant-form {
  &__h {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 13px;
    font-weight: 600;
  }
  &__footer {
    padding-top: 4px;
    border-top: 1px solid var(--lt-line-soft);
    margin-top: 6px;
    padding-top: 12px;
    display: flex;
    gap: 8px;
  }
}

.lt-full { width: 100%; }
.lt-triple {
  display: grid;
  gap: 6px;
  grid-template-columns: repeat(3, 1fr);
}

.lt-volume-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.lt-volume-slider { flex: 1; }
.lt-volume-num {
  width: 36px;
  text-align: right;
  font-size: 13px;
  color: var(--lt-t1);
}
.lt-volume-input {
  width: 110px;
  flex-shrink: 0;
}

/* 时长「时 分 秒」三段带单位 */
.lt-time-with-unit {
  display: flex;
  align-items: center;
  gap: 4px;
}
.lt-time-with-unit ::v-deep .el-input {
  width: 56px;
}
.lt-time-with-unit ::v-deep .el-input__inner {
  padding: 0 6px;
  text-align: center;
}
.lt-time-with-unit .lt-unit {
  font-size: 12px;
  color: var(--lt-t3);
  flex-shrink: 0;
}

.lt-raw-card {
  margin-top: 12px;
  &__h {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 13px;
  }
  &__pre {
    margin: 0;
    white-space: pre-wrap;
    word-break: break-word;
    font-size: 12px;
    font-family: var(--lt-mono);
    color: var(--lt-t2);
    max-height: 240px;
    overflow: auto;
  }
}

.lt-muted { color: var(--lt-t3); }
.lt-tiny { font-size: 11px; }
.lt-mono { font-family: var(--lt-mono); }

@media (max-width: 1080px) {
  .lt-instant-layout {
    grid-template-columns: 1fr;
  }
}
</style>
