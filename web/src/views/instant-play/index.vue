<template>
  <div class="light-page">
    <div class="page-head">
      <div>
        <h2>即时播放</h2>
        <p>临时播放直接调用设备实时播放接口，未选择媒体时不会发送 media 字段。</p>
      </div>
      <div class="head-actions">
        <el-button size="small" icon="el-icon-refresh" :loading="loading" @click="loadResources">刷新资源</el-button>
        <el-button size="small" type="danger" plain icon="el-icon-video-pause" :loading="stopping" @click="stopNow">停止即时播放</el-button>
      </div>
    </div>

    <el-card shadow="never" class="form-card">
      <el-form label-width="110px" size="small">
        <el-form-item label="媒体">
          <el-select v-model="selectedMedia" multiple filterable allow-create default-first-option class="full" placeholder="可不选">
            <el-option v-for="item in mediaOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="终端/分组">
          <el-select v-model="selectedTerminal" multiple filterable allow-create default-first-option class="full" placeholder="如 1_70, 2_447">
            <el-option v-for="item in terminalOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="播放模式">
              <el-select v-model="form.playmode" class="full">
                <el-option label="按时长" value="0" />
                <el-option label="按次数" value="1" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="时长">
              <div class="triple">
                <el-input v-model="form.timehour" placeholder="时" />
                <el-input v-model="form.timeminute" placeholder="分" />
                <el-input v-model="form.timesecond" placeholder="秒" />
              </div>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="次数">
              <el-input v-model="form.times" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="音量">
              <el-input-number v-model="form.volume" :min="0" :max="100" class="full" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="播放顺序">
              <el-select v-model="form.random" class="full">
                <el-option label="顺序播放" value="0" />
                <el-option label="随机播放" value="1" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="16">
            <el-form-item label="本地分区">
              <el-checkbox-group v-model="checkedAreas">
                <el-checkbox label="area0">分区1</el-checkbox>
                <el-checkbox label="area1">分区2</el-checkbox>
                <el-checkbox label="area2">分区3</el-checkbox>
                <el-checkbox label="area3">分区4</el-checkbox>
                <el-checkbox label="area4">分区5</el-checkbox>
                <el-checkbox label="area5">分区6</el-checkbox>
              </el-checkbox-group>
            </el-form-item>
            <el-form-item label="电源控制">
              <el-checkbox-group v-model="checkedAreas">
                <el-checkbox label="area6">功放电源</el-checkbox>
                <el-checkbox label="area7">外控电源</el-checkbox>
              </el-checkbox-group>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item>
          <el-button type="primary" icon="el-icon-video-play" :loading="submitting" @click="submit">执行即时播放</el-button>
          <el-button @click="resetForm">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card v-if="lastRaw" shadow="never" class="raw-card">
      <div slot="header">最近一次接口响应</div>
      <pre>{{ lastRaw }}</pre>
    </el-card>
  </div>
</template>

<script>
import { fetchLightResources, startInstantPlay, stopInstantPlay } from '@/api/lightService'

function listFromPayload(payload) {
  if (Array.isArray(payload)) return payload
  if (!payload || typeof payload !== 'object') return []
  if (Array.isArray(payload.data)) return payload.data
  if (payload.data && Array.isArray(payload.data.data)) return payload.data.data
  if (Array.isArray(payload.rows)) return payload.rows
  if (Array.isArray(payload.list)) return payload.list
  return []
}

function treeLeafOptions(payload, valuePrefix = '') {
  const options = []
  const walk = (node) => {
    if (Array.isArray(node)) {
      node.forEach(walk)
      return
    }
    if (!node || typeof node !== 'object') return
    if (Array.isArray(node.item) && node.item.length) {
      node.item.forEach(walk)
      return
    }
    const rawId = node.id || node.value || node.code
    if (rawId === undefined || rawId === null || rawId === '') return
    const id = String(rawId).trim()
    if (!id || id.indexOf('dir_') === 0) return
    const value = valuePrefix && !id.startsWith('1_') && !id.startsWith('2_') ? `${valuePrefix}${id}` : id
    options.push({
      value,
      label: String(node.text || node.name || node.label || optionLabel(node) || id),
      raw: node
    })
  }
  walk(payload)
  return options
}

function optionLabel(item) {
  return item.label || item.text || item.name || item.medianame || item.terminalname || item.ip || item.id || item.mediaid || item.terminalid || ''
}

export default {
  name: 'InstantPlay',
  data() {
    return {
      loading: false,
      submitting: false,
      stopping: false,
      resources: {},
      selectedMedia: [],
      selectedTerminal: [],
      checkedAreas: ['area0', 'area1', 'area2', 'area3', 'area4', 'area5', 'area6'],
      lastRaw: '',
      form: this.defaultForm()
    }
  },
  computed: {
    mediaOptions() {
      const normalized = listFromPayload(this.resources.media_options)
      if (normalized.length) return normalized
      const treeOptions = treeLeafOptions(this.resources.media)
      if (treeOptions.length) return treeOptions
      return listFromPayload(this.resources.media).map((item) => ({
        value: String(item.mediaid || item.id || item.media_id || optionLabel(item)),
        label: String(optionLabel(item))
      })).filter((item) => item.value)
    },
    terminalOptions() {
      const normalized = listFromPayload(this.resources.terminal_options)
      if (normalized.length) return normalized
      const treeOptions = treeLeafOptions(this.resources.terminal, '2_')
      if (treeOptions.length) return treeOptions
      return listFromPayload(this.resources.terminal).map((item) => {
        const id = item.terminalid || item.id || item.terminal_id || optionLabel(item)
        return {
          value: String(item.value || item.code || id),
          label: String(optionLabel(item))
        }
      }).filter((item) => item.value)
    }
  },
  created() {
    this.loadResources()
  },
  methods: {
    defaultForm() {
      return {
        playmode: '0',
        timehour: '0',
        timeminute: '2',
        timesecond: '0',
        times: '1',
        volume: 80,
        random: '0'
      }
    },
    async loadResources() {
      this.loading = true
      try {
        const resp = await fetchLightResources()
        this.resources = resp.data || {}
      } catch (err) {
        this.$message.error(this.errorText(err, '加载资源失败'))
      } finally {
        this.loading = false
      }
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
      const areaKeys = ['area0', 'area1', 'area2', 'area3', 'area4', 'area5', 'area6', 'area7']
      areaKeys.forEach((key) => {
        payload[key] = this.checkedAreas.includes(key) ? '1' : '0'
      })
      Object.keys(payload).forEach((key) => {
        if (payload[key] === '' || payload[key] === undefined || payload[key] === null) delete payload[key]
      })
      return payload
    },
    async submit() {
      this.submitting = true
      try {
        const resp = await startInstantPlay(this.buildPayload())
        this.showResult(resp, '即时播放请求已提交')
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
        this.showResult(resp, '停止即时播放请求已提交')
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
      this.checkedAreas = ['area0', 'area1', 'area2', 'area3', 'area4', 'area5', 'area6']
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

<style scoped>
.light-page {
  padding: 20px;
}
.page-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}
.page-head h2 {
  margin: 0;
  font-size: 22px;
  color: #1f2d3d;
}
.page-head p {
  margin: 6px 0 0;
  color: #606266;
  font-size: 13px;
}
.head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.form-card,
.raw-card {
  border-radius: 8px;
}
.raw-card {
  margin-top: 14px;
}
.raw-card pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
}
.full {
  width: 100%;
}
.triple {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
}
@media (max-width: 760px) {
  .page-head {
    flex-direction: column;
  }
  .head-actions {
    justify-content: flex-start;
    flex-wrap: wrap;
  }
}
</style>
