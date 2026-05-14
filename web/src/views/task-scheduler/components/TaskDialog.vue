<!--
  TaskDialog — 新增 / 编辑任务弹窗（共用）

  特性：
    - 编辑模式下显示 detailWarning（部分字段加载失败提示）
    - 编辑模式下 programId / taskId 只读
    - 高级设置（分区 / 电源 / 预开迟关 / 随机）默认展开
    - 提交时把完整 form / selectedMedia / selectedTerminal / checkedDays
      作为 payload emit 给父组件 (父组件负责 buildPayload + API)

  Props:
    visible          Boolean   (用 :visible.sync)
    mode             'create' | 'edit'
    initial          Object    弹窗打开时的初值
                               {form, selectedMedia, selectedTerminal, checkedDays}
    mediaOptions     Array     [{value, label}, ...]
    terminalOptions  Array     同上
    detailWarning    String    编辑时详情接口失败的提示
    detailLoading    Boolean   编辑时正在拉详情
    saving           Boolean   提交中

  Events:
    update:visible
    submit(payload)  payload = {form, selectedMedia, selectedTerminal, checkedDays}
-->
<template>
  <el-dialog
    :title="dialogTitle"
    :visible="visible"
    width="760px"
    :close-on-click-modal="false"
    append-to-body
    custom-class="lt-task-dialog"
    @update:visible="(v) => $emit('update:visible', v)"
  >
    <el-alert
      v-if="detailWarning"
      :title="detailWarning"
      type="warning"
      show-icon
      :closable="false"
      class="lt-task-dialog__warning"
    />

    <el-form ref="form" :model="form" size="small" label-width="92px" v-loading="detailLoading">
      <!-- 基础信息 ─────────────────── -->
      <el-row :gutter="14">
        <el-col :span="12">
          <el-form-item label="方案 ID" required>
            <el-input
              v-model="form.programId"
              :disabled="mode === 'edit'"
              placeholder="例如 1"
            />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="任务 ID">
            <el-input
              v-model="form.taskId"
              :disabled="mode === 'create'"
              :placeholder="mode === 'create' ? '由后端生成' : ''"
            />
          </el-form-item>
        </el-col>

        <el-col :span="12">
          <el-form-item label="任务名称" required>
            <el-input v-model="form.taskname" placeholder="例如：起床铃" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="播放时间" required>
            <el-time-picker
              v-model="form.time"
              value-format="HH:mm:ss"
              format="HH:mm:ss"
              placeholder="选择时间"
              class="lt-full"
            />
          </el-form-item>
        </el-col>

        <el-col :span="12">
          <el-form-item label="媒体">
            <el-select
              v-model="localMedia"
              multiple
              filterable
              allow-create
              default-first-option
              class="lt-full"
              placeholder="可手输或选择"
            >
              <el-option
                v-for="item in mediaOptions"
                :key="item.value"
                :label="item.label"
                :value="item.value"
              />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="终端 / 分组">
            <el-select
              v-model="localTerminal"
              multiple
              filterable
              allow-create
              default-first-option
              class="lt-full"
              placeholder="如 2_446 或 1_70"
            >
              <el-option
                v-for="item in terminalOptions"
                :key="item.value"
                :label="item.label"
                :value="item.value"
              />
            </el-select>
          </el-form-item>
        </el-col>

        <!-- 播放模式 + 时长 + 次数/音量 -->
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
            <div class="lt-triple">
              <el-input v-model="form.timehour" placeholder="时" />
              <el-input v-model="form.timeminute" placeholder="分" />
              <el-input v-model="form.timesecond" placeholder="秒" />
            </div>
          </el-form-item>
        </el-col>
        <el-col :span="6">
          <el-form-item label="次数">
            <el-input v-model="form.times" />
          </el-form-item>
        </el-col>

        <!-- 音量(滑块) + 星期 -->
        <el-col :span="24">
          <el-form-item label="音量">
            <div class="lt-volume-row">
              <el-slider v-model="volumeNum" :min="0" :max="100" class="lt-volume-slider" />
              <span class="lt-volume-num lt-mono">{{ form.volume }}</span>
            </div>
          </el-form-item>
        </el-col>

        <el-col :span="24">
          <el-form-item label="星期">
            <div class="lt-day-chips">
              <span
                v-for="(d, i) in dayOptions"
                :key="d.key"
                class="lt-chip"
                :class="{ 'is-on': checkedDays.includes(d.key) }"
                @click="toggleDay(d.key)"
              >
                <i v-if="checkedDays.includes(d.key)" class="el-icon-check lt-chip__check" />
                {{ d.label }}
              </span>
              <el-button type="text" size="mini" class="lt-day-link" @click="setDayPreset('all')">全选</el-button>
              <el-button type="text" size="mini" class="lt-day-link lt-day-link--muted" @click="setDayPreset('weekday')">工作日</el-button>
            </div>
          </el-form-item>
        </el-col>
      </el-row>

      <!-- 高级设置 ─────────────────── -->
      <el-divider content-position="left">高级设置</el-divider>

      <el-row :gutter="14">
        <!-- 分区 -->
        <el-col :span="24">
          <el-form-item label="本地分区">
            <div class="lt-zone-chips">
              <span
                v-for="i in 6"
                :key="'z' + i"
                class="lt-chip"
                :class="{ 'is-on': isAreaOn('area' + (i - 1)) }"
                @click="toggleArea('area' + (i - 1))"
              >
                <i v-if="isAreaOn('area' + (i - 1))" class="el-icon-check lt-chip__check" />
                分区{{ i }}
              </span>
              <el-button type="text" size="mini" class="lt-day-link" @click="setZonePreset('all')">全选</el-button>
              <el-button type="text" size="mini" class="lt-day-link lt-day-link--muted" @click="setZonePreset('none')">清空</el-button>
            </div>
          </el-form-item>
        </el-col>

        <!-- 电源 -->
        <el-col :span="12">
          <el-form-item label="电源控制">
            <el-checkbox v-model="powerAmp">功放电源</el-checkbox>
            <el-checkbox v-model="powerExt">外控电源</el-checkbox>
          </el-form-item>
        </el-col>

        <!-- 预开/迟关 -->
        <el-col :span="12">
          <el-form-item label="预开 / 迟关">
            <div class="lt-double">
              <el-input v-model="form.pretime">
                <template slot="append">秒</template>
              </el-input>
              <el-input v-model="form.delaytime">
                <template slot="append">秒</template>
              </el-input>
            </div>
          </el-form-item>
        </el-col>

        <!-- 随机 + workmode -->
        <el-col :span="12">
          <el-form-item label="随机播放">
            <el-switch
              :value="form.random === '1'"
              @change="(v) => form.random = v ? '1' : '0'"
            />
            <span class="lt-form-hint">乱序循环媒体列表</span>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="工作模式">
            <el-select v-model="form.workmode" class="lt-full">
              <el-option label="0 — 默认" value="0" />
              <el-option label="1" value="1" />
              <el-option label="2" value="2" />
            </el-select>
          </el-form-item>
        </el-col>
      </el-row>
    </el-form>

    <span slot="footer" class="lt-task-dialog__footer">
      <el-button size="small" @click="close">取消</el-button>
      <el-button
        type="primary"
        size="small"
        :loading="saving || detailLoading"
        @click="onSubmit"
      >
        {{ mode === 'create' ? '提交' : '保存修改' }}
      </el-button>
    </span>
  </el-dialog>
</template>

<script>
const DAY_OPTIONS = [
  { key: 'day0', label: '周一' },
  { key: 'day1', label: '周二' },
  { key: 'day2', label: '周三' },
  { key: 'day3', label: '周四' },
  { key: 'day4', label: '周五' },
  { key: 'day5', label: '周六' },
  { key: 'day6', label: '周日' }
]

function defaultForm() {
  return {
    programId: '1',
    taskId: '',
    taskname: '',
    time: '08:00:00',
    playmode: '0',
    timehour: '0',
    timeminute: '3',
    timesecond: '0',
    times: '1',
    volume: '80',
    enableordis: '0',
    workmode: '0',
    pretime: '10',
    delaytime: '10',
    random: '0',
    area0: '1',
    area1: '1',
    area2: '1',
    area3: '1',
    area4: '1',
    area5: '1',
    area6: '1',
    area7: '0'
  }
}

export default {
  name: 'TaskDialog',
  props: {
    visible: { type: Boolean, default: false },
    mode: { type: String, default: 'create' },
    initial: { type: Object, default: null },
    mediaOptions: { type: Array, default: () => [] },
    terminalOptions: { type: Array, default: () => [] },
    detailWarning: { type: String, default: '' },
    detailLoading: { type: Boolean, default: false },
    saving: { type: Boolean, default: false }
  },
  data() {
    return {
      dayOptions: DAY_OPTIONS,
      form: defaultForm(),
      localMedia: [],
      localTerminal: [],
      checkedDays: DAY_OPTIONS.map((d) => d.key)
    }
  },
  computed: {
    dialogTitle() {
      return this.mode === 'create' ? '新增任务' : '编辑任务'
    },
    volumeNum: {
      get() {
        const n = Number(this.form.volume)
        return Number.isFinite(n) ? n : 80
      },
      set(v) {
        this.form.volume = String(v)
      }
    },
    powerAmp: {
      get() { return this.isAreaOn('area6') },
      set(v) { this.form.area6 = v ? '1' : '0' }
    },
    powerExt: {
      get() { return this.isAreaOn('area7') },
      set(v) { this.form.area7 = v ? '1' : '0' }
    }
  },
  watch: {
    visible(val) {
      if (val) this.applyInitial()
    }
  },
  methods: {
    applyInitial() {
      const init = this.initial || {}
      this.form = Object.assign(defaultForm(), init.form || {})
      this.localMedia = Array.isArray(init.selectedMedia) ? init.selectedMedia.slice() : []
      this.localTerminal = Array.isArray(init.selectedTerminal) ? init.selectedTerminal.slice() : []
      this.checkedDays = Array.isArray(init.checkedDays) && init.checkedDays.length
        ? init.checkedDays.slice()
        : DAY_OPTIONS.map((d) => d.key)
    },
    toggleDay(key) {
      const idx = this.checkedDays.indexOf(key)
      if (idx === -1) this.checkedDays.push(key)
      else this.checkedDays.splice(idx, 1)
    },
    setDayPreset(preset) {
      if (preset === 'all') {
        this.checkedDays = DAY_OPTIONS.map((d) => d.key)
      } else if (preset === 'weekday') {
        this.checkedDays = ['day0', 'day1', 'day2', 'day3', 'day4']
      }
    },
    isAreaOn(key) {
      return String(this.form[key]) === '1'
    },
    toggleArea(key) {
      this.$set(this.form, key, this.isAreaOn(key) ? '0' : '1')
    },
    setZonePreset(preset) {
      const values = ['0', '1', '2', '3', '4', '5'].map((i) => 'area' + i)
      const target = preset === 'all' ? '1' : '0'
      values.forEach((k) => this.$set(this.form, k, target))
    },
    close() {
      this.$emit('update:visible', false)
    },
    onSubmit() {
      // 简单校验
      if (this.mode === 'create' && !String(this.form.programId || '').trim()) {
        return this.$message.warning('请填写方案 ID')
      }
      if (this.mode === 'edit' && !String(this.form.taskId || '').trim()) {
        return this.$message.warning('请填写任务 ID')
      }
      if (!String(this.form.taskname || '').trim()) {
        return this.$message.warning('请填写任务名称')
      }
      this.$emit('submit', {
        form: Object.assign({}, this.form),
        selectedMedia: this.localMedia.slice(),
        selectedTerminal: this.localTerminal.slice(),
        checkedDays: this.checkedDays.slice()
      })
    }
  }
}
</script>

<style lang="scss" scoped>
.lt-task-dialog__warning {
  margin-bottom: 14px;
}

.lt-full {
  width: 100%;
}
.lt-triple,
.lt-double {
  display: grid;
  gap: 6px;
}
.lt-triple {
  grid-template-columns: repeat(3, 1fr);
}
.lt-double {
  grid-template-columns: repeat(2, 1fr);
}

/* chip 通用 */
.lt-chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 4px 11px;
  border-radius: var(--lt-r);
  border: 1px solid var(--lt-line-strong);
  background: #fff;
  color: var(--lt-t2);
  font-size: 12px;
  cursor: pointer;
  user-select: none;
  transition: border-color .12s, color .12s, background .12s;
  line-height: 1.4;

  &:hover {
    border-color: var(--lt-p);
    color: var(--lt-p);
  }
  &.is-on {
    background: var(--lt-p-soft);
    border-color: var(--lt-p);
    color: var(--lt-p);
  }
  &__check {
    font-size: 10px;
    font-weight: 700;
  }
}

.lt-day-chips,
.lt-zone-chips {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  align-items: center;
}
.lt-day-link {
  color: var(--lt-p) !important;
}
.lt-day-link--muted {
  color: var(--lt-t3) !important;
}

.lt-volume-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.lt-volume-slider {
  flex: 1;
}
.lt-volume-num {
  width: 36px;
  text-align: right;
  font-size: 13px;
  color: var(--lt-t1);
}

.lt-form-hint {
  margin-left: 10px;
  font-size: 12px;
  color: var(--lt-t3);
}
</style>
