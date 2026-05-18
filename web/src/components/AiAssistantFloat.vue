<template>
  <div class="ai-assistant-root">
    <button
      v-if="isMobileLayout && !mobilePanelVisible"
      type="button"
      class="ai-mobile-trigger"
      @click="openMobilePanel"
    >
      <i class="el-icon-microphone" />
      <span>AI助手</span>
    </button>
    <div
      v-show="!isMobileLayout || mobilePanelVisible"
      class="ai-float"
      :class="{
        collapsed: !isMobileLayout && collapsed,
        'is-mobile': isMobileLayout,
        'is-mobile-open': isMobileLayout && mobilePanelVisible
      }"
      :style="panelStyle"
      @mousedown.stop
    >
      <div class="ai-header" @mousedown.prevent="startDrag">
        <div class="title">
          <i class="el-icon-microphone" />
          <span>AI助手</span>
        </div>
        <div class="actions" @mousedown.stop>
          <el-tooltip content="查看成功日志" placement="top">
            <el-button
              class="header-log-btn"
              size="mini"
              icon="el-icon-document"
              @click.stop="openHistoryDrawer"
            >
              成功日志
            </el-button>
          </el-tooltip>
          <el-button v-if="!isMobileLayout" type="text" size="mini" @click.stop="toggleCollapse">
            <i :class="collapsed ? 'el-icon-arrow-down' : 'el-icon-arrow-up'" />
          </el-button>
          <el-button v-else type="text" size="mini" @click.stop="closeMobilePanel">
            <i class="el-icon-close" />
          </el-button>
        </div>
      </div>

      <div v-show="isMobileLayout || !collapsed" class="ai-body">
        <p class="desc">输入语音指令，支持：播放/停止任务，打开分区或功放/外控电源。</p>

        <div ref="chatBox" class="chat-box">
          <div v-for="msg in conversation" :key="msg.id" :class="['chat-line', msg.role]">
            <div :class="['bubble', { 'bubble-warning': msg.role === 'ai' && !msg.pending && isWarningMessage(msg.text), 'bubble-pending': msg.pending }]">
              <div v-if="msg.pending" class="thinking-text">
                <span>深度思考中</span>
                <span class="thinking-dots" aria-hidden="true">
                  <i />
                  <i />
                  <i />
                </span>
              </div>
              <div v-else-if="msg.role === 'ai'" class="text" v-html="msg.text" />
              <div v-else class="text">{{ msg.text }}</div>
              <div
                v-if="msg.role === 'ai' && !msg.pending && getDialogStateBadge(msg.meta)"
                :class="['dialog-state-badge', { 'is-confirm': normalizeDialogStateDetail(msg.meta) === 'confirm_interrupt_switch' }]"
              >
                {{ getDialogStateBadge(msg.meta) }}
              </div>
              <div v-if="msg.role === 'ai' && !msg.pending && hasPendingChoices(msg.meta)" class="pending-panel">
                <div class="pending-title">{{ getPendingTitle(msg.meta) }}</div>
                <div v-if="getPendingHint(msg.meta)" class="pending-hint">{{ getPendingHint(msg.meta) }}</div>
                <div class="pending-choices">
                  <el-button
                    v-for="choice in getPendingChoices(msg.meta)"
                    :key="choice.key"
                    class="pending-choice"
                    size="mini"
                    type="primary"
                    plain
                    :disabled="aiLoading"
                    @click="submitPendingChoice(choice)"
                  >
                    <span class="pending-choice-main">{{ choice.label }}</span>
                    <span v-if="choice.description" class="pending-choice-sub">{{ choice.description }}</span>
                  </el-button>
                </div>
              </div>
              <div v-if="msg.role === 'ai' && !msg.pending && shouldShowDiagnostics(msg.meta)" class="diagnostic-panel">
                <details class="diagnostic-details">
                  <summary>查看远端诊断</summary>
                  <div
                    v-for="(diag, idx) in msg.meta.diagnostics"
                    :key="`${msg.id}-diag-${idx}`"
                    :class="['diagnostic-item', { failed: !diag.ok }]"
                  >
                    <div class="diagnostic-grid">
                      <div class="diagnostic-row">
                        <span class="diagnostic-label">diagnostic_id</span>
                        <span>{{ diag.diagnostic_id || '-' }}</span>
                      </div>
                      <div class="diagnostic-row">
                        <span class="diagnostic-label">phase</span>
                        <span>{{ diag.phase || '-' }}</span>
                      </div>
                      <div class="diagnostic-row">
                        <span class="diagnostic-label">path</span>
                        <span>{{ diag.path || '-' }}</span>
                      </div>
                      <div class="diagnostic-row">
                        <span class="diagnostic-label">status</span>
                        <span>{{ formatDiagnosticStatus(diag) }}</span>
                      </div>
                      <div class="diagnostic-row">
                        <span class="diagnostic-label">elapsed_ms</span>
                        <span>{{ formatDiagnosticElapsed(diag) }}</span>
                      </div>
                    </div>
                    <div v-if="!diag.ok" class="diagnostic-failure">
                      <div class="diagnostic-block">
                        <div class="diagnostic-label">request_payload</div>
                        <pre>{{ formatDiagnosticValue(diag.request_payload) }}</pre>
                      </div>
                      <div class="diagnostic-block">
                        <div class="diagnostic-label">response_body</div>
                        <pre>{{ formatDiagnosticValue(diag.response_body) }}</pre>
                      </div>
                      <div class="diagnostic-block">
                        <div class="diagnostic-label">error_detail</div>
                        <pre>{{ formatDiagnosticValue(diag.error_detail) }}</pre>
                      </div>
                    </div>
                  </div>
                </details>
              </div>
            </div>
          </div>
          <div v-if="!conversation.length" class="placeholder">
            试着说：「播放大课间任务」「停止午休铃任务」「给操场播放国歌」「打开 1 号分区」「打开功放电源」
          </div>
        </div>

        <el-input
          ref="commandInput"
          v-model="command"
          type="textarea"
          :rows="3"
          placeholder="请输入指令文本"
          @keydown.native.enter.prevent="handleEnter"
        />
        <div class="ai-actions">
          <el-tooltip content="指令大全" placement="top">
            <el-button size="mini" icon="el-icon-reading" @click="openManualDrawer">
              指令大全
            </el-button>
          </el-tooltip>
          <el-button
            type="primary"
            icon="el-icon-microphone"
            size="mini"
            :loading="aiLoading"
            :disabled="aiLoading"
            @click="sendToAssistant"
          >
            发送
          </el-button>
          <el-button size="mini" @click="command = ''">清空</el-button>
        </div>
      </div>
    </div>

    <el-drawer
      :visible.sync="manualDrawer"
      :direction="isMobileLayout ? 'btt' : 'rtl'"
      :size="isMobileLayout ? '100%' : '380px'"
      :with-header="false"
      :append-to-body="true"
      :custom-class="isMobileLayout ? 'manual-drawer manual-drawer-mobile' : 'manual-drawer'"
      @open="handleManualOpen"
      @close="handleManualClose"
    >
      <div class="manual-shell">
        <div class="manual-header">
          <div class="manual-title">
            <span class="manual-icon">📖</span>
            <div>
              <div class="manual-title-text">指令大全</div>
              <div class="manual-title-sub">点击例句即可填入输入框，随时可改。</div>
            </div>
          </div>
          <el-button type="text" icon="el-icon-close" @click="manualDrawer = false" />
        </div>

        <div class="manual-search">
          <el-input
            v-model="manualSearch"
            size="small"
            clearable
            placeholder="搜索功能，如：音量、新建作息..."
          >
            <i slot="prefix" class="el-icon-search" />
          </el-input>
        </div>

        <div class="manual-body">
          <el-tabs v-model="manualActiveTab" :tab-position="isMobileLayout ? 'top' : 'left'" class="manual-tabs">
            <el-tab-pane
              v-for="module in filteredModules"
              :key="module.id"
              :name="module.id"
              :label="module.tabLabel"
            >
              <div class="module-intro">
                <div class="module-title">{{ module.title }}</div>
                <div class="module-desc">{{ module.desc }}</div>
              </div>

              <el-collapse
                accordion
                class="manual-collapse"
                :value="getManualOpen(module.id)"
                @input="setManualOpen(module.id, $event)"
              >
                <el-collapse-item
                  v-for="item in module.items"
                  :key="item.id"
                  :name="item.id"
                >
                  <template slot="title">
                    <div class="collapse-title">
                      <span class="collapse-name">{{ item.title }}</span>
                      <el-tag size="mini" type="info" effect="plain">功能</el-tag>
                    </div>
                  </template>

                  <div class="manual-card">
                    <div class="card-row">
                      <div class="card-label">功能名称</div>
                      <div class="card-value">{{ item.title }}</div>
                    </div>

                    <div v-if="hasManualVariants(item)" class="card-row">
                      <div class="card-label">分类切换</div>
                      <div class="card-value">
                        <el-radio-group
                          :value="getManualVariant(item)"
                          size="mini"
                          class="variant-switch"
                          @input="setManualVariant(item, $event)"
                        >
                          <el-radio-button
                            v-for="option in getManualVariantOptions(item)"
                            :key="`${item.id}-variant-${option.value}`"
                            :label="option.value"
                          >
                            {{ option.label }}
                          </el-radio-button>
                        </el-radio-group>
                      </div>
                    </div>

                    <div v-if="getManualTemplate(item)" class="card-row">
                      <div class="card-label">核心指令</div>
                      <div class="card-value">
                        <div class="template-line">
                          <span
                            v-for="(seg, idx) in parseTemplate(item)"
                            :key="`${item.id}-${idx}`"
                          >
                            <span v-if="seg.type === 'text'">{{ seg.text }}</span>
                            <el-popover
                              v-else
                              placement="top"
                              trigger="click"
                              :value="getSlotPopoverVisible(item, seg)"
                              :width="isStructuredTimeSlot(seg) ? 320 : 240"
                              @input="setSlotPopoverVisible(item, seg, $event)"
                              @show="prepareSlotPicker(item, seg)"
                            >
                              <div class="slot-picker">
                                <div class="slot-picker-title">{{ seg.display }} 选项</div>
                                <template v-if="isStructuredTimeSlot(seg)">
                                  <div class="time-range-picker">
                                    <div class="time-range-presets">
                                      <button
                                        v-for="preset in getStructuredTimePresets(seg)"
                                        :key="`${item.id}-${seg.key}-${preset}`"
                                        type="button"
                                        :class="[
                                          'time-range-preset',
                                          { active: getStructuredTimeField(item, seg.key, 'anchor') === preset }
                                        ]"
                                        @click="updateStructuredTimeField(item, seg.key, 'anchor', preset)"
                                      >
                                        {{ preset }}
                                      </button>
                                    </div>
                                    <el-input
                                      :value="getStructuredTimeField(item, seg.key, 'detail')"
                                      size="small"
                                      clearable
                                      placeholder="例如：下午2点到6点"
                                      @input="updateStructuredTimeField(item, seg.key, 'detail', $event)"
                                    />
                                    <div
                                      :class="[
                                        'time-range-hint',
                                        { invalid: Boolean(getStructuredTimeError(item, seg.key)) }
                                      ]"
                                    >
                                      {{ getStructuredTimeError(item, seg.key) || '先选今天/明天/周一，再补充具体时间段' }}
                                    </div>
                                    <div class="time-range-preview">
                                      {{ getStructuredTimePreview(item, seg.key) }}
                                    </div>
                                    <div class="time-range-actions">
                                      <el-button
                                        size="mini"
                                        @click="clearStructuredTimeField(item, seg.key)"
                                      >
                                        清空
                                      </el-button>
                                      <el-button
                                        type="primary"
                                        size="mini"
                                        :disabled="!canConfirmStructuredTime(item, seg.key)"
                                        @click="confirmStructuredTime(item, seg.key)"
                                      >
                                        确认填入
                                      </el-button>
                                    </div>
                                  </div>
                                </template>
                                <template v-else-if="isCalendarDateSlot(seg)">
                                  <div class="calendar-picker">
                                    <el-date-picker
                                      :value="getCalendarDateField(item, seg.key, 'date', seg.slotType)"
                                      type="date"
                                      value-format="yyyy-MM-dd"
                                      format="yyyy-MM-dd"
                                      placeholder="选择日期"
                                      class="calendar-picker-input"
                                      @input="updateCalendarDateField(item, seg.key, 'date', $event, seg.slotType)"
                                    />
                                    <div class="calendar-preview">
                                      {{ getCalendarPreview(item, seg.key, seg.slotType) }}
                                    </div>
                                    <div class="time-range-actions">
                                      <el-button
                                        size="mini"
                                        @click="clearCalendarField(item, seg.key, seg.slotType)"
                                      >
                                        清空
                                      </el-button>
                                      <el-button
                                        type="primary"
                                        size="mini"
                                        :disabled="!canConfirmCalendar(item, seg.key, seg.slotType)"
                                        @click="confirmCalendarValue(item, seg.key, seg.slotType)"
                                      >
                                        确认填入
                                      </el-button>
                                    </div>
                                  </div>
                                </template>
                                <template v-else-if="isCalendarDateRangeSlot(seg)">
                                  <div class="calendar-picker">
                                    <el-date-picker
                                      :value="getCalendarDateField(item, seg.key, 'range', seg.slotType)"
                                      type="daterange"
                                      value-format="yyyy-MM-dd"
                                      format="yyyy-MM-dd"
                                      range-separator="至"
                                      start-placeholder="开始日期"
                                      end-placeholder="结束日期"
                                      unlink-panels
                                      class="calendar-picker-input"
                                      @input="updateCalendarDateField(item, seg.key, 'range', $event, seg.slotType)"
                                    />
                                    <div class="calendar-preview">
                                      {{ getCalendarPreview(item, seg.key, seg.slotType) }}
                                    </div>
                                    <div class="time-range-actions">
                                      <el-button
                                        size="mini"
                                        @click="clearCalendarField(item, seg.key, seg.slotType)"
                                      >
                                        清空
                                      </el-button>
                                      <el-button
                                        type="primary"
                                        size="mini"
                                        :disabled="!canConfirmCalendar(item, seg.key, seg.slotType)"
                                        @click="confirmCalendarValue(item, seg.key, seg.slotType)"
                                      >
                                        确认填入
                                      </el-button>
                                    </div>
                                  </div>
                                </template>
                                <template v-else-if="isCalendarDateWithModeSlot(seg)">
                                  <div class="calendar-picker">
                                    <el-radio-group
                                      :value="getCalendarDateField(item, seg.key, 'mode', seg.slotType)"
                                      size="mini"
                                      class="calendar-mode-switch"
                                      @input="updateCalendarDateMode(item, seg.key, $event)"
                                    >
                                      <el-radio-button label="single">单日</el-radio-button>
                                      <el-radio-button label="range">多日</el-radio-button>
                                    </el-radio-group>
                                    <el-date-picker
                                      v-if="getCalendarDateField(item, seg.key, 'mode', seg.slotType) === 'single'"
                                      :value="getCalendarDateField(item, seg.key, 'date', seg.slotType)"
                                      type="date"
                                      value-format="yyyy-MM-dd"
                                      format="yyyy-MM-dd"
                                      placeholder="选择日期"
                                      class="calendar-picker-input"
                                      @input="updateCalendarDateField(item, seg.key, 'date', $event, seg.slotType)"
                                    />
                                    <el-date-picker
                                      v-else
                                      :value="getCalendarDateField(item, seg.key, 'range', seg.slotType)"
                                      type="daterange"
                                      value-format="yyyy-MM-dd"
                                      format="yyyy-MM-dd"
                                      range-separator="至"
                                      start-placeholder="开始日期"
                                      end-placeholder="结束日期"
                                      unlink-panels
                                      class="calendar-picker-input"
                                      @input="updateCalendarDateField(item, seg.key, 'range', $event, seg.slotType)"
                                    />
                                    <div class="calendar-preview">
                                      {{ getCalendarPreview(item, seg.key, seg.slotType) }}
                                    </div>
                                    <div class="time-range-actions">
                                      <el-button
                                        size="mini"
                                        @click="clearCalendarField(item, seg.key, seg.slotType)"
                                      >
                                        清空
                                      </el-button>
                                      <el-button
                                        type="primary"
                                        size="mini"
                                        :disabled="!canConfirmCalendar(item, seg.key, seg.slotType)"
                                        @click="confirmCalendarValue(item, seg.key, seg.slotType)"
                                      >
                                        确认填入
                                      </el-button>
                                    </div>
                                  </div>
                                </template>
                                <el-select
                                  v-else-if="seg.slotType === 'zonePower'"
                                  :value="getZonePowerArray(item, seg.key)"
                                  multiple
                                  collapse-tags
                                  size="small"
                                  :placeholder="getSlotPlaceholder(item, seg)"
                                  @input="setZonePowerArray(item, seg.key, $event)"
                                >
                                  <el-option
                                    v-for="opt in zonePowerOptions"
                                    :key="opt.value"
                                    :label="opt.label"
                                    :value="opt.value"
                                  />
                                </el-select>
                                <el-select
                                  v-else-if="seg.slotType === 'terminalGroup'"
                                  :value="getTerminalGroupArray(item, seg.key)"
                                  multiple
                                  collapse-tags
                                  filterable
                                  size="small"
                                  :loading="isSlotLoading(item, seg)"
                                  :placeholder="getSlotPlaceholder(item, seg)"
                                  @input="setTerminalGroupArray(item, seg.key, $event)"
                                >
                                  <el-option-group
                                    v-if="terminalGroupGroupOptions.length"
                                    label="终端分组"
                                  >
                                    <el-option
                                      v-for="opt in terminalGroupGroupOptions"
                                      :key="opt.value"
                                      :label="opt.label"
                                      :value="opt.value"
                                    />
                                  </el-option-group>
                                  <el-option-group
                                    v-if="terminalGroupTerminalOptions.length"
                                    label="单独终端"
                                  >
                                    <el-option
                                      v-for="opt in terminalGroupTerminalOptions"
                                      :key="opt.value"
                                      :label="opt.label"
                                      :value="opt.value"
                                    />
                                  </el-option-group>
                                </el-select>
                                <el-select
                                  v-else-if="seg.slotType === 'zoneMixed'"
                                  :value="getZoneMixedArray(item, seg.key)"
                                  multiple
                                  collapse-tags
                                  filterable
                                  size="small"
                                  :loading="isSlotLoading(item, seg)"
                                  :placeholder="getSlotPlaceholder(item, seg)"
                                  @input="setZoneMixedArray(item, seg.key, $event)"
                                >
                                  <el-option-group
                                    v-if="zoneMixedGroupOptions.length"
                                    label="终端分组"
                                  >
                                    <el-option
                                      v-for="opt in zoneMixedGroupOptions"
                                      :key="opt.value"
                                      :label="opt.label"
                                      :value="opt.value"
                                    />
                                  </el-option-group>
                                  <el-option-group label="硬件分区 / 电源">
                                    <el-option
                                      v-for="opt in zonePowerOptions"
                                      :key="opt.value"
                                      :label="opt.label"
                                      :value="opt.value"
                                    />
                                  </el-option-group>
                                </el-select>
                                <el-select
                                  v-else-if="usesSelectableOptions(seg)"
                                  :value="getSlotValue(item, seg.key)"
                                  filterable
                                  allow-create
                                  default-first-option
                                  size="small"
                                  :loading="isSlotLoading(item, seg)"
                                  :disabled="isSlotDisabled(item, seg)"
                                  :placeholder="getSlotPlaceholder(item, seg)"
                                  @input="setSlotValue(item, seg.key, $event)"
                                >
                                  <el-option
                                    v-for="opt in getSlotOptions(seg.slotType, item, seg)"
                                    :key="opt.value"
                                    :label="opt.displayLabel || opt.label"
                                    :value="opt.value"
                                  >
                                    <div v-if="seg.slotType === 'schedule'" class="schedule-option">
                                      <span>{{ opt.label }}</span>
                                      <span
                                        v-if="isScheduleOptionEnabled(opt)"
                                        class="schedule-option-status"
                                      >
                                        (启动)
                                      </span>
                                    </div>
                                    <span v-else>{{ opt.label }}</span>
                                  </el-option>
                                </el-select>
                                <el-input
                                  v-else
                                  :value="getSlotValue(item, seg.key)"
                                  size="small"
                                  clearable
                                  :placeholder="getSlotPlaceholder(item, seg)"
                                  @input="setSlotValue(item, seg.key, $event)"
                                />
                              </div>
                              <span
                                slot="reference"
                                :class="[
                                  'slot-chip',
                                  {
                                    active: !!getSlotValue(item, seg.key),
                                    'slot-chip-schedule': isScheduleSlot(seg) && isSelectedScheduleEnabled(item, seg)
                                  }
                                ]"
                              >
                                <span>{{ getSlotDisplay(item, seg) }}</span>
                                <span
                                  v-if="isScheduleSlot(seg) && isSelectedScheduleEnabled(item, seg)"
                                  class="slot-chip-status"
                                >
                                  (启动)
                                </span>
                              </span>
                            </el-popover>
                          </span>
                        </div>
                        <el-button type="text" size="mini" class="fill-link" @click="fillFromTemplate(item)">
                          点击填入
                        </el-button>
                      </div>
                    </div>

                    <div class="card-row">
                      <div class="card-label">🗣️ 推荐指令示例</div>
                      <div class="card-value">
                        <div
                          v-for="(example, idx) in getManualExamples(item)"
                          :key="`${item.id}-ex-${idx}`"
                          class="example-item"
                          @click="fillCommand(example)"
                        >
                          <i class="el-icon-chat-line-round" />
                          <span class="example-text">{{ example }}</span>
                        </div>
                      </div>
                    </div>

                    <div class="card-row">
                      <div class="card-label">💡 必填参数提示</div>
                      <div class="card-value">
                        <el-tag
                          v-for="(param, idx) in formatRequired(item)"
                          :key="`${item.id}-req-${idx}`"
                          size="mini"
                          type="warning"
                          effect="plain"
                        >
                          {{ param }}
                        </el-tag>
                      </div>
                    </div>

                    <div v-if="item.formType === 'cloneSchedule'" class="card-row form-row">
                      <div class="card-label">⚡ 只需填空</div>
                      <div class="card-value">
                        <div class="form-grid">
                          <div class="form-field">
                            <div class="form-label">源方案</div>
                            <el-select
                              :value="formState.cloneSchedule.source"
                              filterable
                              allow-create
                              size="small"
                              placeholder="选择或输入源方案"
                              @input="updateCloneForm('source', $event)"
                              @focus="ensureSlotOptions('schedule')"
                            >
                              <el-option
                                v-for="opt in getSlotOptions('schedule')"
                                :key="`clone-source-${opt.value}`"
                                :label="opt.displayLabel || opt.label"
                                :value="opt.value"
                              >
                                <div class="schedule-option">
                                  <span>{{ opt.label }}</span>
                                  <span
                                    v-if="isScheduleOptionEnabled(opt)"
                                    class="schedule-option-status"
                                  >
                                    (启动)
                                  </span>
                                </div>
                              </el-option>
                            </el-select>
                          </div>
                          <div class="form-field">
                            <div class="form-label">偏移时间(分钟)</div>
                            <el-input-number
                              :value="formState.cloneSchedule.offset"
                              size="small"
                              :min="-300"
                              :max="300"
                              @input="updateCloneForm('offset', $event)"
                            />
                          </div>
                          <div class="form-field">
                            <div class="form-label">新名称</div>
                            <el-input
                              :value="formState.cloneSchedule.name"
                              size="small"
                              placeholder="如：冬季作息"
                              @input="updateCloneForm('name', $event)"
                            />
                          </div>
                        </div>
                        <el-button type="primary" size="mini" @click="applyCloneSchedule">
                          生成指令
                        </el-button>
                      </div>
                    </div>
                  </div>
                </el-collapse-item>
              </el-collapse>

              <div v-if="!module.items.length" class="empty-state">
                未找到相关指令
              </div>
            </el-tab-pane>
          </el-tabs>
        </div>

        <div class="manual-footer">
          <i class="el-icon-info" />
          <span>{{ currentTip }}</span>
        </div>
      </div>
    </el-drawer>

    <el-drawer
      :visible.sync="historyDrawer"
      :direction="isMobileLayout ? 'btt' : 'rtl'"
      :size="isMobileLayout ? '100%' : '420px'"
      :with-header="false"
      :append-to-body="true"
      :custom-class="isMobileLayout ? 'log-drawer log-drawer-mobile' : 'log-drawer'"
      @open="fetchAssistantLogs"
    >
      <div class="log-shell">
        <div class="log-header">
          <div>
            <div class="log-title">成功指令日志</div>
            <div class="log-subtitle">保存成功执行后的用户输入与助手回复。</div>
          </div>
          <div class="log-header-actions">
            <el-button
              type="text"
              size="mini"
              icon="el-icon-refresh-right"
              :loading="historyLoading"
              @click="fetchAssistantLogs"
            >
              刷新
            </el-button>
            <el-button type="text" icon="el-icon-close" @click="historyDrawer = false" />
          </div>
        </div>

        <div class="log-body">
          <div v-if="historyLoading && !historyEntries.length" class="empty-state">
            正在加载成功日志...
          </div>
          <div v-else-if="!historyEntries.length" class="empty-state">
            暂无成功执行的指令记录
          </div>
          <div v-else class="log-list">
            <div v-for="entry in historyEntries" :key="entry.id" class="log-card">
              <div class="log-card-row">
                <div class="log-card-label">用户输入</div>
                <div class="log-card-value">{{ entry.text || '未记录指令文本' }}</div>
              </div>
              <div class="log-card-row">
                <div class="log-card-label">助手回复</div>
                <div class="log-card-value">{{ entry.reply || '-' }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script>
import axios from 'axios'
import { getToken } from '@/utils/auth'
import { emitAssistantRefresh, offAssistantRefresh, onAssistantRefresh } from '@/utils/assistantRefreshBus'
import { mapHttpErrorToUserMessage } from '@/utils/httpError'

const api = axios.create({
  timeout: 30000
})

const DEFAULT_ALLOWED_SCHEDULE_KINDS = ['小学', '中学', '高中', '大学']
const DEFAULT_ALLOWED_SCHEDULE_SEASONS = ['夏季', '冬季']

api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers = config.headers || {}
    config.headers['X-Token'] = token
  }
  return config
})

export default {
  name: 'AiAssistantFloat',
  data() {
    return {
      command: '',
      aiLoading: false,
      pendingAssistantMessageId: null,
      collapsed: false,
      mobilePanelVisible: false,
      conversation: [],
      position: {
        top: 140,
        left: 0
      },
      dragState: null,
      panelWidth: 320,
      manualDrawer: false,
      historyDrawer: false,
      historyLoading: false,
      historyEntries: [],
      assistantSettingsLoading: false,
      assistantSettingsSaving: false,
      schoolKindPopoverVisible: false,
      defaultScheduleKind: '',
      defaultScheduleSeason: '',
      allowedScheduleKinds: DEFAULT_ALLOWED_SCHEDULE_KINDS.slice(),
      allowedScheduleSeasons: DEFAULT_ALLOWED_SCHEDULE_SEASONS.slice(),
      manualSearch: '',
      manualActiveTab: 'broadcast',
      manualOpenMap: {},
      manualTipIndex: 0,
      manualTipTimer: null,
      manualTips: [
        '💡 提示：“取消”只是跳过一次，“删除”才是永久移除。',
        '💡 提示：不指定区域时，可能默认对全校播放。',
        '💡 提示：尽量说清时间与地点，命中率更高。'
      ],
      slotOptions: {
        terminal: [],
        zone: [],
        schedule: [],
        media: [],
        broadcastTask: [],
        playMedia: [],
        currentTask: [],
        target: [],
        // 「终端」槽位的原始数据：terminal 分组 + 单独物理终端，分别保留。
        // 在 template 用 computed terminalGroupOptions 转成两个 el-option-group。
        terminalGroupRaw: { groups: [], terminals: [] }
      },
      slotLoading: {
        terminal: false,
        zone: false,
        schedule: false,
        media: false,
        broadcastTask: false,
        playMedia: false,
        currentTask: false,
        terminalGroup: false
      },
      taskOptionsBySchedule: {},
      taskLoadingBySchedule: {},
      // 打开分区/电源 多选选项 — 分区槽位固定 6 个 (area0~5)，
      // 功放=area6、外控=area7，与 TaskDialog/InstantPlay 的硬件约定保持一致。
      zonePowerOptions: [
        { label: '1 号分区', value: 'z1' },
        { label: '2 号分区', value: 'z2' },
        { label: '3 号分区', value: 'z3' },
        { label: '4 号分区', value: 'z4' },
        { label: '5 号分区', value: 'z5' },
        { label: '6 号分区', value: 'z6' },
        { label: '功放电源', value: 'amp' },
        { label: '外控电源', value: 'ext' }
      ],
      manualVariantState: {},
      slotPopoverVisible: {},
      structuredTimeSelections: {},
      calendarDateSelections: {},
      slotSelections: {},
      formState: {
        cloneSchedule: {
          source: '',
          offset: 30,
          name: ''
        }
      },
      manualModules: [
        {
          id: 'broadcast',
          tabLabel: '广播控制',
          title: '广播控制 — 当前 AI 助手支持的全部能力',
          desc: '当前只识别以下 4 类指令；新增/编辑任务、修改作息请到「作息管理」页面操作。',
          items: [
            {
              id: 'play-task',
              title: '播放任务',
              template: '播放[任务名称]任务',
              examples: ['播放大课间任务', '执行升旗仪式任务', '马上播午休铃'],
              required: ['任务名称'],
              slotMap: { 任务名称: { type: 'currentTask', display: '任务名称' } }
            },
            {
              id: 'stop-task',
              title: '停止任务',
              template: '停止[任务名称]任务',
              examples: ['停止午休铃任务', '终止升旗任务', '把眼保健操任务停掉'],
              required: ['任务名称'],
              slotMap: { 任务名称: { type: 'currentTask', display: '任务名称' } }
            },
            {
              id: 'temp-play-media',
              title: '临时播放媒体',
              // 终端 = 分组+单独终端，区域 = 硬件分区+功放/外控，两者都可选填（至少填一个用户自己把握）。
              // 用"和"明确分隔，避免拼出 "操场1 号分区" 这种 NLU 难拆的串；空槽会触发 fillFromTemplate 的 connector skip。
              template: '给[终端]和[区域]播放[媒体]，音量[音量]',
              examples: ['给操场播放国歌，音量80', '在 1 号分区播放眼保健操，音量60', '所有分区播放上课铃，音量100'],
              required: ['媒体'],
              slotMap: {
                终端: { type: 'terminalGroup', display: '终端' },
                区域: { type: 'zonePower', display: '区域' },
                媒体: { type: 'playMedia', display: '媒体' },
                音量: { type: 'text', display: '音量(0-100, 留空为80)' }
              }
            },
            {
              id: 'open-zone-power',
              title: '打开分区 / 电源',
              template: '打开[分区或电源]',
              examples: [
                '打开 1 号分区',
                '打开 1 到 6 号分区',
                '打开 1、3、5 号分区',
                '打开全部分区',
                '打开功放电源',
                '打开外控电源',
                '打开 1 号分区和功放'
              ],
              required: ['分区或电源'],
              slotMap: { '分区或电源': { type: 'zonePower', display: '分区或电源' } }
            },
            {
              id: 'stop-temp',
              title: '停止临时播放',
              template: '停止临时播放',
              examples: ['停止所有临时播放', '关闭临时广播', '停止刚刚的播放'],
              required: [],
              slotMap: {}
            }
          ]
        }
      ]
    }
  },
  computed: {
    isMobileLayout() {
      return this.$store?.state?.app?.device === 'mobile'
    },
    // zoneMixed 下拉中"终端分组"段的选项。提成 computed 避免每次模板渲染都 .map() 生成新数组。
    zoneMixedGroupOptions() {
      return (this.slotOptions.zone || []).map((opt) => ({
        label: opt.label || opt.value,
        value: `g:${opt.value}`
      }))
    },
    // terminalGroup 槽位：终端分组（g:）+ 单独物理终端（t:）。
    // value 前缀让 parse/format 能区分两类来源。
    terminalGroupGroupOptions() {
      return (this.slotOptions.terminalGroupRaw?.groups || [])
        .map((opt) => ({
          label: String(opt.label || opt.value || '').trim(),
          value: `g:${String(opt.label || opt.value || '').trim()}`
        }))
        .filter((opt) => opt.label)
    },
    terminalGroupTerminalOptions() {
      return (this.slotOptions.terminalGroupRaw?.terminals || [])
        .map((opt) => ({
          label: String(opt.label || opt.value || '').trim(),
          value: `t:${String(opt.label || opt.value || '').trim()}`
        }))
        .filter((opt) => opt.label)
    },
    panelStyle() {
      if (this.isMobileLayout) return null
      return {
        top: `${this.position.top}px`,
        left: `${this.position.left}px`
      }
    },
    filteredModules() {
      const keyword = String(this.manualSearch || '').trim().toLowerCase()
      if (!keyword) return this.manualModules
      const result = []
      this.manualModules.forEach((module) => {
        const moduleText = `${module.title} ${module.desc} ${module.tabLabel}`.toLowerCase()
        const moduleMatch = moduleText.includes(keyword)
        const items = module.items.filter((item) => {
          const itemText = this.buildManualSearchText(item).toLowerCase()
          return itemText.includes(keyword)
        })
        if (moduleMatch) {
          result.push({ ...module })
        } else if (items.length) {
          result.push({ ...module, items })
        }
      })
      return result
    },
    aiDiagnosticsEnabled() {
      const raw = String(process.env.VUE_APP_AI_DIAGNOSTICS || '').trim()
      if (raw === '1') return true
      if (raw === '0') return false
      return process.env.NODE_ENV !== 'production'
    },
    currentTip() {
      if (!this.manualTips.length) return ''
      return this.manualTips[this.manualTipIndex % this.manualTips.length]
    },
    hasScheduleTemplateSelection() {
      return Boolean(this.defaultScheduleKind && this.defaultScheduleSeason)
    },
    scheduleTemplateSelectionLabel() {
      return [this.defaultScheduleKind, this.defaultScheduleSeason].filter(Boolean).join(' / ')
    }
  },
  watch: {
    isMobileLayout: {
      immediate: true,
      handler(value) {
        if (!value) return
        this.mobilePanelVisible = false
        this.collapsed = false
      }
    },
    filteredModules: {
      handler(list) {
        if (!list.length) return
        const exists = list.some((mod) => mod.id === this.manualActiveTab)
        if (!exists) {
          this.manualActiveTab = list[0].id
        }
      },
      immediate: true
    }
  },
  created() {
    this.initManualOpenMap()
    this.initManualVariantState()
    // Removed fetchAssistantSettings — schedule template settings are no longer in scope.
    onAssistantRefresh(this.handleAssistantRefresh)
  },
  mounted() {
    this.position.left = window.innerWidth - this.panelWidth - 24
    window.addEventListener('resize', this.handleResize)
  },
  beforeDestroy() {
    offAssistantRefresh(this.handleAssistantRefresh)
    this.removeDragListeners()
    window.removeEventListener('resize', this.handleResize)
    this.stopTipTimer()
  },
  methods: {
    toggleCollapse() {
      if (this.isMobileLayout) return
      this.collapsed = !this.collapsed
    },
    handleResize() {
      if (this.isMobileLayout) return
      const maxLeft = window.innerWidth - this.panelWidth - 12
      if (this.position.left > maxLeft) this.position.left = maxLeft
    },
    openMobilePanel() {
      this.mobilePanelVisible = true
      this.$nextTick(() => {
        const box = this.$refs.chatBox
        if (box) box.scrollTop = box.scrollHeight
        const input = this.$refs.commandInput
        if (input && typeof input.focus === 'function') {
          input.focus()
        }
      })
    },
    closeMobilePanel() {
      this.mobilePanelVisible = false
    },
    openManualDrawer() {
      this.manualDrawer = true
    },
    openHistoryDrawer() {
      this.historyDrawer = true
    },
    handleManualOpen() {
      this.setManualTabFromContext()
      this.refreshManualSlotOptions({ force: true })
      this.startTipTimer()
    },
    handleManualClose() {
      this.stopTipTimer()
    },
    handleAssistantRefresh(payload = {}) {
      const authBackendSync = String(payload?.reason || '').trim() === 'auth_backend_sync'
      if (authBackendSync) {
        this.resetSlotOptions([
          'terminal',
          'zone',
          'target',
          'schedule',
          'media',
          'playMedia',
          'broadcastTask'
        ])
        if (this.manualDrawer) {
          this.refreshManualSlotOptions({ force: true })
        }
        return
      }
      const actions = this.collectRefreshActions(payload)
      const scheduleChanged = this.hasAnyAction(actions, [
        'create_schedule',
        'delete_schedule',
        'shift_schedule_later',
        'shift_schedule_earlier'
      ])
      const zoneChanged = this.hasAnyAction(actions, [
        'create_zone',
        'delete_zone',
        'add_terminal_to_zone',
        'remove_terminal_from_zone'
      ])
      const playMediaChanged = this.hasAnyAction(actions, ['play_media'])
      const mediaLibraryChanged = this.hasAnyAction(actions, ['replace_media_in_task'])
      if (!scheduleChanged && !zoneChanged && !playMediaChanged && !mediaLibraryChanged) return
      const staleTypes = []
      if (scheduleChanged) staleTypes.push('schedule')
      if (zoneChanged) staleTypes.push('zone', 'target')
      if (playMediaChanged) staleTypes.push('playMedia')
      if (mediaLibraryChanged) staleTypes.push('media', 'playMedia')
      this.resetSlotOptions(staleTypes)
      if (this.manualDrawer) {
        this.refreshManualSlotOptions({
          force: true,
          types: [
            ...(scheduleChanged ? ['schedule'] : []),
            ...(zoneChanged ? ['zone'] : []),
            ...(playMediaChanged ? ['playMedia'] : []),
            ...(mediaLibraryChanged ? ['media', 'playMedia'] : [])
          ]
        })
      }
    },
    initManualOpenMap() {
      this.manualModules.forEach((module) => {
        if (!this.manualOpenMap[module.id]) {
          this.$set(this.manualOpenMap, module.id, '')
        }
      })
    },
    initManualVariantState() {
      this.manualModules.forEach((module) => {
        module.items.forEach((item) => {
          if (!this.hasManualVariants(item)) return
          if (!this.manualVariantState[item.id]) {
            this.$set(this.manualVariantState, item.id, this.getDefaultManualVariant(item))
          }
        })
      })
    },
    buildManualSearchText(item) {
      const parts = [item.title]
      if (item.template) parts.push(item.template)
      parts.push(...(item.examples || []), ...(item.required || []))
      if (this.hasManualVariants(item)) {
        Object.values(item.variants || {}).forEach((variant) => {
          parts.push(variant.template || '')
          parts.push(...(variant.examples || []), ...(variant.required || []))
        })
      }
      return parts.filter(Boolean).join(' ')
    },
    hasManualVariants(item) {
      return Boolean(item && item.variants && Object.keys(item.variants).length)
    },
    getDefaultManualVariant(item) {
      if (!this.hasManualVariants(item)) return ''
      return item.defaultVariant || Object.keys(item.variants || {})[0] || ''
    },
    getManualVariant(item) {
      if (!this.hasManualVariants(item)) return ''
      return this.manualVariantState[item.id] || this.getDefaultManualVariant(item)
    },
    getManualVariantOptions(item) {
      if (!this.hasManualVariants(item)) return []
      if (Array.isArray(item.variantOptions) && item.variantOptions.length) {
        return item.variantOptions
      }
      return Object.keys(item.variants || {}).map((key) => ({ label: key, value: key }))
    },
    getManualExamples(item) {
      const manualItem = this.resolveManualItem(item)
      return Array.isArray(manualItem.examples) ? manualItem.examples : []
    },
    resolveManualItem(item, variantKey = '') {
      if (!this.hasManualVariants(item)) return item || {}
      const key = variantKey || this.getManualVariant(item)
      const variant = (item.variants && item.variants[key]) || {}
      return {
        ...item,
        ...variant,
        id: item.id,
        title: item.title
      }
    },
    setManualVariant(item, value) {
      if (!this.hasManualVariants(item)) return
      const nextVariant = String(value || '').trim()
      if (!nextVariant) return
      const currentVariant = this.getManualVariant(item)
      if (currentVariant === nextVariant) return
      const currentItem = this.resolveManualItem(item, currentVariant)
      const nextItem = this.resolveManualItem(item, nextVariant)
      const currentSelections = { ...(this.slotSelections[item.id] || {}) }
      const nextKeys = Object.keys(nextItem.slotMap || {})
      const nextSelections = {}
      nextKeys.forEach((key) => {
        if (Object.prototype.hasOwnProperty.call(currentSelections, key)) {
          nextSelections[key] = currentSelections[key]
        }
      })
      Object.keys(nextItem.slotMap || {}).forEach((key) => {
        const slotMeta = nextItem.slotMap[key]
        if (['calendarDate', 'calendarDateRange', 'calendarDateWithMode'].includes(slotMeta?.type)) {
          delete nextSelections[key]
        }
      })
      this.$set(this.manualVariantState, item.id, nextVariant)
      this.$set(this.slotSelections, item.id, nextSelections)
      this.resetCalendarSlots(item, currentItem)
      this.resetCalendarSlots(item, nextItem)
      if (this.hasTaskSlot(nextItem) && this.getSelectedScheduleValue(item)) {
        this.ensureTaskOptionsForItem(item)
      }
      if (this.hasTaskSlot(currentItem) && !this.hasTaskSlot(nextItem)) {
        this.resetDependentTaskSlots(item, currentItem)
      }
    },
    resetCalendarSlots(item, manualItem = null) {
      const resolvedItem = manualItem || this.resolveManualItem(item)
      const itemId = this.normalizeManualItemId(item)
      const calendarKeys = Object.keys(resolvedItem.slotMap || {}).filter((key) => {
        const slotMeta = resolvedItem.slotMap[key]
        return ['calendarDate', 'calendarDateRange', 'calendarDateWithMode'].includes(slotMeta?.type)
      })
      if (!calendarKeys.length) return
      calendarKeys.forEach((calendarKey) => {
        this.resetCalendarDateState(itemId, calendarKey)
        if (this.slotSelections[itemId] && this.slotSelections[itemId][calendarKey]) {
          this.$delete(this.slotSelections[itemId], calendarKey)
        }
      })
    },
    hasTaskSlot(item) {
      return Object.values((item && item.slotMap) || {}).some((slot) => slot && slot.type === 'task')
    },
    getManualOpen(moduleId) {
      return this.manualOpenMap[moduleId] || ''
    },
    setManualOpen(moduleId, value) {
      this.$set(this.manualOpenMap, moduleId, value)
    },
    setManualTabFromContext() {
      // 精简后只有一个广播控制 tab，无需根据路径切换
      this.manualActiveTab = 'broadcast'
    },
    startTipTimer() {
      if (this.manualTipTimer) return
      this.manualTipTimer = window.setInterval(() => {
        this.manualTipIndex = (this.manualTipIndex + 1) % this.manualTips.length
      }, 4500)
    },
    stopTipTimer() {
      if (this.manualTipTimer) {
        clearInterval(this.manualTipTimer)
        this.manualTipTimer = null
      }
    },
    normalizeAssistantLogs(data) {
      const list = Array.isArray(data?.items) ? data.items : []
      return list
        .filter((item) => item && typeof item === 'object')
        .map((item, index) => ({
          id: `${index}-${item.text || ''}-${item.reply || ''}`,
          text: item.text || '',
          reply: item.reply || ''
        }))
    },
    formatRequestErrorMessage(err, requestPath, fallbackText, scene = 'generic') {
      return mapHttpErrorToUserMessage(err, {
        scene,
        fallbackText,
        requestPath
      })
    },
    isAssistantUnavailableError(err) {
      const status = err?.response?.status
      return !err?.response || status >= 500
    },
    async fetchAssistantLogs() {
      if (this.historyLoading) return
      this.historyLoading = true
      try {
        const base = process.env.VUE_APP_BASE_API || ''
        const requestPath = `${base}/data/assistant_command_logs`
        const { data } = await api.get(requestPath, {
          params: { limit: 100 }
        })
        this.historyEntries = this.normalizeAssistantLogs(data)
      } catch (err) {
        if (this.historyDrawer) {
          const requestPath = `${process.env.VUE_APP_BASE_API || ''}/data/assistant_command_logs`
          this.$message.error(
            this.formatRequestErrorMessage(err, requestPath, '成功日志加载失败，请检查后端接口', 'assistant_logs')
          )
        }
      } finally {
        this.historyLoading = false
      }
    },
    normalizeAssistantSettingsOptions(items, fallback) {
      const normalized = Array.isArray(items)
        ? items.map((item) => String(item || '').trim()).filter(Boolean)
        : []
      return normalized.length ? normalized : fallback.slice()
    },
    applyAssistantSettings(data) {
      this.defaultScheduleKind = String(data?.default_schedule_kind || '').trim()
      this.defaultScheduleSeason = String(data?.default_schedule_season || '').trim()
      this.allowedScheduleKinds = this.normalizeAssistantSettingsOptions(
        data?.allowed_schedule_kinds,
        DEFAULT_ALLOWED_SCHEDULE_KINDS
      )
      this.allowedScheduleSeasons = this.normalizeAssistantSettingsOptions(
        data?.allowed_schedule_seasons,
        DEFAULT_ALLOWED_SCHEDULE_SEASONS
      )
    },
    async fetchAssistantSettings(options = {}) {
      if (this.assistantSettingsLoading) return
      this.assistantSettingsLoading = true
      try {
        const base = process.env.VUE_APP_BASE_API || ''
        const requestPath = `${base}/data/assistant_settings`
        const { data } = await api.get(requestPath)
        this.applyAssistantSettings(data)
      } catch (err) {
        if (!options.silent) {
          const requestPath = `${process.env.VUE_APP_BASE_API || ''}/data/assistant_settings`
          this.$message.error(
            this.formatRequestErrorMessage(err, requestPath, '作息模板配置加载失败，请检查后端接口', 'assistant_settings')
          )
        }
      } finally {
        this.assistantSettingsLoading = false
      }
    },
    async saveAssistantSettings(payload) {
      if (this.assistantSettingsSaving) return
      this.assistantSettingsSaving = true
      try {
        const base = process.env.VUE_APP_BASE_API || ''
        const requestPath = `${base}/data/assistant_settings`
        const { data } = await api.put(requestPath, payload)
        this.applyAssistantSettings(data)
        this.schoolKindPopoverVisible = false
        this.$message.success(
          this.scheduleTemplateSelectionLabel
            ? `默认作息模板已设置为${this.scheduleTemplateSelectionLabel}`
            : '已清空默认作息模板'
        )
      } catch (err) {
        const requestPath = `${process.env.VUE_APP_BASE_API || ''}/data/assistant_settings`
        this.$message.error(
          this.formatRequestErrorMessage(err, requestPath, '作息模板配置保存失败，请检查后端接口', 'assistant_settings')
        )
        await this.fetchAssistantSettings({ silent: true })
      } finally {
        this.assistantSettingsSaving = false
      }
    },
    async handleScheduleKindChange(value) {
      const nextValue = String(value || '').trim()
      await this.saveAssistantSettings({
        default_schedule_kind: nextValue,
        default_schedule_season: this.defaultScheduleSeason
      })
    },
    async handleScheduleSeasonChange(value) {
      const nextValue = String(value || '').trim()
      await this.saveAssistantSettings({
        default_schedule_kind: this.defaultScheduleKind,
        default_schedule_season: nextValue
      })
    },
    getManualTemplate(item) {
      return this.resolveManualItem(item)?.template || ''
    },
    parseTemplate(item) {
      const manualItem = this.resolveManualItem(item)
      const template = manualItem?.template || ''
      const parts = []
      const regex = /\[([^\]]+)\]/g
      let lastIndex = 0
      let match
      while ((match = regex.exec(template)) !== null) {
        if (match.index > lastIndex) {
          parts.push({ type: 'text', text: template.slice(lastIndex, match.index) })
        }
        const key = match[1]
        const slotMeta = (manualItem.slotMap && manualItem.slotMap[key]) || { type: 'text', display: key }
        parts.push({
          type: 'slot',
          key,
          slotType: slotMeta.type || 'text',
          display: slotMeta.display || key,
          dependsOn: slotMeta.dependsOn || '',
          presets: Array.isArray(slotMeta.presets) ? slotMeta.presets : [],
          options: Array.isArray(slotMeta.options) ? slotMeta.options : []
        })
        lastIndex = match.index + match[0].length
      }
      if (lastIndex < template.length) {
        parts.push({ type: 'text', text: template.slice(lastIndex) })
      }
      return parts
    },
    normalizeManualItemId(itemOrId) {
      if (itemOrId && typeof itemOrId === 'object') return itemOrId.id
      return itemOrId
    },
    getSlotValue(itemOrId, key) {
      const itemId = this.normalizeManualItemId(itemOrId)
      return (this.slotSelections[itemId] || {})[key] || ''
    },
    getSlotPopoverKey(itemOrId, segOrKey) {
      const itemId = this.normalizeManualItemId(itemOrId)
      const slotKey = typeof segOrKey === 'object' ? segOrKey.key : segOrKey
      return `${itemId}:${slotKey}`
    },
    getSlotPopoverVisible(itemOrId, segOrKey) {
      const popoverKey = this.getSlotPopoverKey(itemOrId, segOrKey)
      return Boolean(this.slotPopoverVisible[popoverKey])
    },
    setSlotPopoverVisible(itemOrId, segOrKey, visible) {
      const popoverKey = this.getSlotPopoverKey(itemOrId, segOrKey)
      this.$set(this.slotPopoverVisible, popoverKey, Boolean(visible))
    },
    setSlotValue(itemOrId, key, value) {
      const itemId = this.normalizeManualItemId(itemOrId)
      const previousValue = this.getSlotValue(itemId, key)
      if (!this.slotSelections[itemId]) {
        this.$set(this.slotSelections, itemId, {})
      }
      this.$set(this.slotSelections[itemId], key, value)
      if (itemOrId && typeof itemOrId === 'object') {
        const manualItem = this.resolveManualItem(itemOrId)
        const slotMeta = (manualItem.slotMap && manualItem.slotMap[key]) || {}
        if (slotMeta.type === 'schedule' && previousValue !== value) {
          this.resetDependentTaskSlots(itemOrId, manualItem)
          if (value) {
            this.ensureTaskOptionsForItem(itemOrId)
          }
        }
      }
    },
    resetDependentTaskSlots(item, manualItem = null) {
      const resolvedItem = manualItem || this.resolveManualItem(item)
      const taskKeys = Object.keys(resolvedItem.slotMap || {}).filter((key) => {
        const slotMeta = resolvedItem.slotMap[key]
        return slotMeta && slotMeta.type === 'task'
      })
      if (!taskKeys.length) return
      const itemId = this.normalizeManualItemId(item)
      if (!this.slotSelections[itemId]) return
      taskKeys.forEach((taskKey) => {
        if (this.slotSelections[itemId][taskKey]) {
          this.$set(this.slotSelections[itemId], taskKey, '')
        }
      })
    },
    getSlotDisplay(itemOrId, seg) {
      const value = this.getSlotValue(itemOrId, seg.key)
      return value || seg.display
    },
    isCalendarDateSlot(seg) {
      return seg?.slotType === 'calendarDate'
    },
    isCalendarDateRangeSlot(seg) {
      return seg?.slotType === 'calendarDateRange'
    },
    isCalendarDateWithModeSlot(seg) {
      return seg?.slotType === 'calendarDateWithMode'
    },
    isStructuredTimeSlot(seg) {
      return seg?.slotType === 'structuredTimeRange'
    },
    normalizeCalendarDate(value) {
      const text = String(value || '').trim()
      return /^\d{4}-\d{2}-\d{2}$/.test(text) ? text : ''
    },
    parseCalendarRangeText(value) {
      const text = String(value || '').trim()
      if (!text) return []
      if (text.includes('到')) {
        const parts = text
          .split('到')
          .map((item) => this.normalizeCalendarDate(item))
          .filter(Boolean)
        if (parts.length >= 2) return [parts[0], parts[1]]
      }
      const single = this.normalizeCalendarDate(text)
      return single ? [single, single] : []
    },
    getCalendarDateState(itemOrId, key, slotType = 'calendarDate') {
      const itemId = this.normalizeManualItemId(itemOrId)
      const stateKey = `${itemId}:${key}`
      if (!this.calendarDateSelections[stateKey]) {
        const currentValue = this.getSlotValue(itemId, key)
        const range = this.parseCalendarRangeText(currentValue)
        this.$set(this.calendarDateSelections, stateKey, {
          mode: slotType === 'calendarDateWithMode' && range.length >= 2 && range[0] !== range[1] ? 'range' : 'single',
          date: range.length ? range[0] : this.normalizeCalendarDate(currentValue),
          range
        })
      }
      return this.calendarDateSelections[stateKey]
    },
    getCalendarDateField(itemOrId, key, field, slotType = 'calendarDateWithMode') {
      const state = this.getCalendarDateState(itemOrId, key, slotType)
      if (field === 'range') {
        return Array.isArray(state.range) ? state.range : []
      }
      return state[field] || ''
    },
    updateCalendarDateField(itemOrId, key, field, value, slotType = 'calendarDateWithMode') {
      const state = this.getCalendarDateState(itemOrId, key, slotType)
      if (field === 'range') {
        const range = Array.isArray(value)
          ? value.map((item) => this.normalizeCalendarDate(item)).filter(Boolean)
          : []
        this.$set(state, 'range', range.length >= 2 ? [range[0], range[1]] : [])
        return
      }
      this.$set(state, field, this.normalizeCalendarDate(value))
    },
    updateCalendarDateMode(itemOrId, key, mode) {
      const nextMode = mode === 'range' ? 'range' : 'single'
      const state = this.getCalendarDateState(itemOrId, key, 'calendarDateWithMode')
      this.$set(state, 'mode', nextMode)
      this.$set(state, 'date', '')
      this.$set(state, 'range', [])
      this.setSlotValue(itemOrId, key, '')
    },
    resetCalendarDateState(itemOrId, key) {
      const itemId = this.normalizeManualItemId(itemOrId)
      const stateKey = `${itemId}:${key}`
      if (this.calendarDateSelections[stateKey]) {
        this.$delete(this.calendarDateSelections, stateKey)
      }
    },
    clearCalendarField(itemOrId, key, slotType = 'calendarDate') {
      const state = this.getCalendarDateState(itemOrId, key, slotType)
      this.$set(state, 'date', '')
      this.$set(state, 'range', [])
      if (slotType === 'calendarDateWithMode') {
        this.$set(state, 'mode', 'single')
      }
      this.setSlotValue(itemOrId, key, '')
    },
    formatCalendarValue(itemOrId, key, slotType = 'calendarDate') {
      const state = this.getCalendarDateState(itemOrId, key, slotType)
      if (slotType === 'calendarDate') {
        return this.normalizeCalendarDate(state.date)
      }
      if (slotType === 'calendarDateRange') {
        const range = Array.isArray(state.range) ? state.range : []
        if (range.length < 2) return ''
        return `${range[0]}到${range[1]}`
      }
      if (state.mode === 'range') {
        const range = Array.isArray(state.range) ? state.range : []
        if (range.length < 2) return ''
        return `${range[0]}到${range[1]}`
      }
      return this.normalizeCalendarDate(state.date)
    },
    canConfirmCalendar(itemOrId, key, slotType = 'calendarDate') {
      return Boolean(this.formatCalendarValue(itemOrId, key, slotType))
    },
    getCalendarPreview(itemOrId, key, slotType = 'calendarDate') {
      const value = this.formatCalendarValue(itemOrId, key, slotType)
      return value ? `已选：${value}` : '已选：未完成'
    },
    confirmCalendarValue(itemOrId, key, slotType = 'calendarDate') {
      const value = this.formatCalendarValue(itemOrId, key, slotType)
      if (!value) return
      this.setSlotValue(itemOrId, key, value)
      this.setSlotPopoverVisible(itemOrId, key, false)
    },
    parseStructuredTimeValue(value) {
      const text = String(value || '').trim()
      const presets = this.getStructuredTimePresets()
      const matchedPreset = presets.find((preset) => text.startsWith(preset))
      if (!matchedPreset) {
        return { anchor: '', detail: text }
      }
      return {
        anchor: matchedPreset,
        detail: text.slice(matchedPreset.length).trim()
      }
    },
    getStructuredTimePresets(seg = null) {
      if (Array.isArray(seg?.presets) && seg.presets.length) return seg.presets
      return ['今天', '明天', '后天', '周一', '周二', '周三', '周四', '周五', '周六', '周日']
    },
    getStructuredTimeState(itemOrId, key) {
      const itemId = this.normalizeManualItemId(itemOrId)
      const stateKey = `${itemId}:${key}`
      if (!this.structuredTimeSelections[stateKey]) {
        const initial = this.parseStructuredTimeValue(this.getSlotValue(itemId, key))
        this.$set(this.structuredTimeSelections, stateKey, initial)
      }
      return this.structuredTimeSelections[stateKey]
    },
    getStructuredTimeField(itemOrId, key, field) {
      const state = this.getStructuredTimeState(itemOrId, key)
      return state[field] || ''
    },
    updateStructuredTimeField(itemOrId, key, field, value) {
      const state = this.getStructuredTimeState(itemOrId, key)
      this.$set(state, field, String(value || '').trim())
    },
    clearStructuredTimeField(itemOrId, key) {
      const state = this.getStructuredTimeState(itemOrId, key)
      this.$set(state, 'anchor', '')
      this.$set(state, 'detail', '')
      this.setSlotValue(itemOrId, key, '')
    },
    formatStructuredTimeValue(itemOrId, key) {
      const state = this.getStructuredTimeState(itemOrId, key)
      if (!state.anchor || !state.detail) return ''
      return `${state.anchor}${state.detail}`
    },
    getStructuredTimeError(itemOrId, key) {
      const state = this.getStructuredTimeState(itemOrId, key)
      if (!state.anchor || !state.detail) {
        return ''
      }
      return ''
    },
    canConfirmStructuredTime(itemOrId, key) {
      const state = this.getStructuredTimeState(itemOrId, key)
      if (!state.anchor || !state.detail) return false
      return !this.getStructuredTimeError(itemOrId, key)
    },
    getStructuredTimePreview(itemOrId, key) {
      const value = this.formatStructuredTimeValue(itemOrId, key)
      return value ? `已选：${value}` : '已选：未完成'
    },
    confirmStructuredTime(itemOrId, key) {
      if (!this.canConfirmStructuredTime(itemOrId, key)) return
      const value = this.formatStructuredTimeValue(itemOrId, key)
      this.setSlotValue(itemOrId, key, value)
      this.setSlotPopoverVisible(itemOrId, key, false)
    },
    usesSelectableOptions(seg) {
      return ['terminal', 'zone', 'schedule', 'media', 'playMedia', 'target', 'task', 'broadcastTask', 'currentTask', 'textChoice'].includes(seg?.slotType)
    },
    // terminalGroup 不走通用 usesSelectableOptions 渲染（它有自己的双 option-group 模板分支）。
    isScheduleSlot(seg) {
      return seg?.slotType === 'schedule'
    },
    getSlotOptions(type, item = null, seg = null) {
      if (type === 'target') {
        return this.slotOptions.target || []
      }
      if (type === 'task') {
        return this.getTaskOptionsForItem(item)
      }
      if (type === 'broadcastTask') {
        return this.slotOptions.broadcastTask || []
      }
      if (type === 'currentTask') {
        return this.slotOptions.currentTask || []
      }
      if (type === 'textChoice') {
        return (Array.isArray(seg?.options) ? seg.options : []).map((value) => ({
          label: String(value),
          value: String(value)
        }))
      }
      return this.slotOptions[type] || []
    },
    getSlotPlaceholder(item, seg) {
      if (seg?.slotType === 'task' && !this.getSelectedScheduleValue(item)) {
        return '先选方案'
      }
      if (seg?.slotType === 'broadcastTask') return '选择文件广播任务'
      if (seg?.slotType === 'currentTask') return '选择当前作息下的任务'
      if (seg?.slotType === 'terminalGroup') return '选终端分组 / 单独终端'
      if (seg?.slotType === 'schedule') return '选择方案'
      if (seg?.slotType === 'calendarDate') return '请选择日期'
      if (seg?.slotType === 'calendarDateRange') return '请选择日期范围'
      if (seg?.slotType === 'calendarDateWithMode') return '请选择单日或多日'
      if (seg?.slotType === 'structuredTimeRange') return '先选今天/明天/周一，再补时间'
      if (seg?.slotType === 'textChoice') return '请选择动作'
      if (seg?.slotType === 'zonePower') return '勾选分区 / 功放 / 外控'
      if (seg?.slotType === 'zoneMixed') return '选分组 / 硬件分区 / 电源'
      if (this.usesSelectableOptions(seg)) return '选择或输入'
      return '请输入'
    },
    isSlotDisabled(item, seg) {
      if (seg?.slotType === 'task') {
        return !this.getSelectedScheduleValue(item)
      }
      return false
    },
    isSlotLoading(item, seg) {
      if (seg?.slotType === 'task') {
        const scheduleName = this.getSelectedScheduleValue(item)
        return Boolean(scheduleName && this.taskLoadingBySchedule[scheduleName])
      }
      if (seg?.slotType === 'broadcastTask') {
        return Boolean(this.slotLoading.broadcastTask)
      }
      if (seg?.slotType === 'currentTask') {
        return Boolean(this.slotLoading.currentTask)
      }
      if (seg?.slotType === 'terminalGroup') {
        return Boolean(this.slotLoading.terminalGroup)
      }
      if (seg?.slotType === 'zoneMixed') {
        return Boolean(this.slotLoading.zone)
      }
      return false
    },
    prepareSlotPicker(item, seg) {
      if (this.isStructuredTimeSlot(seg)) {
        this.getStructuredTimeState(item, seg.key)
        return
      }
      if (this.isCalendarDateSlot(seg) || this.isCalendarDateRangeSlot(seg) || this.isCalendarDateWithModeSlot(seg)) {
        this.getCalendarDateState(item, seg.key, seg.slotType)
        return
      }
      if (seg?.slotType === 'task') {
        this.ensureTaskOptionsForItem(item)
        return
      }
      if (seg?.slotType && !['text', 'structuredTimeRange', 'calendarDate', 'calendarDateRange', 'calendarDateWithMode', 'textChoice', 'zonePower'].includes(seg.slotType)) {
        // 临时播放媒体：每次打开槽位都强制拉最新媒体 & 分区，
        // 避免在指令大全里看到的还是几天前的旧媒体列表。
        const itemId = this.normalizeManualItemId(item)
        const isTemp = itemId === 'temp-play-media'
        if (seg.slotType === 'zoneMixed') {
          // zoneMixed 借用 'zone' 接口拉 terminal-groups，硬件分区/电源是本地常量。
          this.ensureSlotOptions('zone', { force: isTemp })
          return
        }
        const force = (isTemp && (seg.slotType === 'playMedia' || seg.slotType === 'zone' || seg.slotType === 'terminalGroup'))
          || seg.slotType === 'currentTask'
        this.ensureSlotOptions(seg.slotType, { force })
      }
    },
    getZonePowerArray(item, key) {
      return this.parseZonePower(this.getSlotValue(item, key))
    },
    setZonePowerArray(item, key, arr) {
      this.setSlotValue(item, key, this.formatZonePower(Array.isArray(arr) ? arr : []))
    },
    formatZonePower(values) {
      const zones = []
      let amp = false
      let ext = false
      values.forEach((v) => {
        if (v === 'amp') amp = true
        else if (v === 'ext') ext = true
        else {
          const m = /^z([1-6])$/.exec(v)
          if (m) zones.push(Number(m[1]))
        }
      })
      zones.sort((a, b) => a - b)
      const parts = []
      if (zones.length === 6) parts.push('全部分区')
      else if (zones.length) parts.push(`${zones.join('、')} 号分区`)
      if (amp) parts.push('功放电源')
      if (ext) parts.push('外控电源')
      return parts.join('、')
    },
    // ───── terminalGroup: 终端分组 + 单独终端 多选 ─────
    // value 内部表示用 g:<name> / t:<name> 前缀区分两类来源；
    // 输出文本是裸名称 join '、'，让后端 NLU 走现有 terminal_name → _remote_terminal_map 路径。
    getTerminalGroupArray(item, key) {
      return this.parseTerminalGroup(this.getSlotValue(item, key))
    },
    setTerminalGroupArray(item, key, arr) {
      this.setSlotValue(item, key, this.formatTerminalGroup(Array.isArray(arr) ? arr : []))
    },
    formatTerminalGroup(values) {
      const groups = []
      const terms = []
      values.forEach((v) => {
        if (typeof v !== 'string') return
        if (v.startsWith('g:')) {
          const name = v.slice(2).trim()
          if (name) groups.push(name)
        } else if (v.startsWith('t:')) {
          const name = v.slice(2).trim()
          if (name) terms.push(name)
        }
      })
      // 每个名字后面带上类型锚点("X分组" / "X终端")，给 NLU 一个清晰的命名实体边界。
      // 后端 resolver 查 map 时会剥掉后缀重试，不会破坏匹配。
      // 名字本身已经以同类后缀结尾的（如远端返回的就叫"操场分组"）就不重复加。
      const withSuffix = (name, suffix, sniffEnd) => (
        sniffEnd.test(name) ? name : `${name}${suffix}`
      )
      const parts = [
        ...groups.map((g) => withSuffix(g, '分组', /[组区]$/)),
        ...terms.map((t) => withSuffix(t, '终端', /终端$/))
      ]
      return parts.join('、')
    },
    parseTerminalGroup(str) {
      const text = String(str || '').trim()
      if (!text) return []
      const raw = this.slotOptions.terminalGroupRaw || { groups: [], terminals: [] }
      // 把分组名 + 终端名合并成一张表，最长优先匹配，避免短名嵌套到长名里
      const candidates = []
      ;(raw.groups || []).forEach((opt) => {
        const name = String(opt?.label || '').trim()
        if (name) candidates.push({ name, kind: 'g' })
      })
      ;(raw.terminals || []).forEach((opt) => {
        const name = String(opt?.label || '').trim()
        if (name) candidates.push({ name, kind: 't' })
      })
      candidates.sort((a, b) => b.name.length - a.name.length)
      let remaining = text
      const set = new Set()
      const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      candidates.forEach(({ name, kind }) => {
        // 先尝试匹配带锚点的变体（"X分组" / "X终端"），命中后再 fallback 到裸名。
        // 防止用户原文里"操场分组"被裸名"操场"先吃掉、把锚点剩在 remaining 里污染后续。
        const suffix = kind === 'g' ? '分组' : '终端'
        const variants = name.endsWith(suffix[1] || suffix)
          ? [name]
          : [`${name}${suffix}`, name]
        for (const variant of variants) {
          const re = new RegExp(escape(variant), 'g')
          if (re.test(remaining)) {
            set.add(`${kind}:${name}`)
            remaining = remaining.replace(new RegExp(escape(variant), 'g'), ' ')
            break
          }
        }
      })
      return Array.from(set)
    },
    // ───── zoneMixed: 终端分组 + 硬件分区 + 功放/外控 三合一多选 ─────
    // 注：分组选项的 value 用 g:<name> 前缀，避免与硬件分区 value (z1..z6/amp/ext) 冲突。
    // 选项列表见 computed.zoneMixedGroupOptions。
    getZoneMixedArray(item, key) {
      return this.parseZoneMixed(this.getSlotValue(item, key))
    },
    setZoneMixedArray(item, key, arr) {
      this.setSlotValue(item, key, this.formatZoneMixed(Array.isArray(arr) ? arr : []))
    },
    formatZoneMixed(values) {
      const groups = []
      const zones = []
      let amp = false
      let ext = false
      values.forEach((v) => {
        if (v === 'amp') amp = true
        else if (v === 'ext') ext = true
        else {
          const m = /^z([1-6])$/.exec(v)
          if (m) zones.push(Number(m[1]))
          else if (typeof v === 'string' && v.startsWith('g:')) {
            const name = v.slice(2).trim()
            if (name) groups.push(name)
          }
        }
      })
      zones.sort((a, b) => a - b)
      const parts = []
      // 终端分组放最前，便于后端 NLU 命名实体识别；硬件分区紧随
      groups.forEach((g) => parts.push(g))
      if (zones.length === 6) parts.push('全部分区')
      else zones.forEach((n) => parts.push(`${n} 号分区`))
      if (amp) parts.push('功放电源')
      if (ext) parts.push('外控电源')
      return parts.join('、')
    },
    parseZoneMixed(str) {
      const text = String(str || '').trim()
      if (!text) return []
      const set = new Set()
      // 1) 先匹配已知终端分组名（最长优先，避免短名嵌套）
      // 跳过纯数字命名的分组（如 "1"），它们会和 "N 号分区" 里的数字混淆
      const names = (this.slotOptions.zone || [])
        .map((o) => String(o.value || '').trim())
        .filter((name) => name && !/^\d+$/.test(name))
        .sort((a, b) => b.length - a.length)
      let remaining = text
      names.forEach((name) => {
        const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
        const re = new RegExp(escaped, 'g')
        if (re.test(remaining)) {
          set.add(`g:${name}`)
          remaining = remaining.replace(new RegExp(escaped, 'g'), ' ')
        }
      })
      // 2) 解析硬件分区（含"全部分区" / "1 到 6 号分区" / "1、3、5 号分区"）
      if (/全部分区|全部.*分区|所有分区|所有.*分区/.test(remaining)) {
        ['z1', 'z2', 'z3', 'z4', 'z5', 'z6'].forEach((z) => set.add(z))
      } else {
        const range = remaining.match(/(\d+)\s*[到~-]\s*(\d+)\s*号分区/)
        if (range) {
          const a = Number(range[1])
          const b = Number(range[2])
          const lo = Math.max(1, Math.min(a, b))
          const hi = Math.min(6, Math.max(a, b))
          for (let i = lo; i <= hi; i += 1) set.add(`z${i}`)
        }
        const singles = remaining.matchAll(/(\d+)\s*号分区/g)
        for (const m of singles) {
          const num = parseInt(m[1], 10)
          if (num >= 1 && num <= 6) set.add(`z${num}`)
        }
      }
      // 3) 电源
      if (/功放/.test(remaining)) set.add('amp')
      if (/外控/.test(remaining)) set.add('ext')
      return Array.from(set)
    },
    parseZonePower(str) {
      const text = String(str || '').trim()
      if (!text) return []
      const set = new Set()
      if (/全部分区|全部.*分区|所有分区|所有.*分区/.test(text)) {
        ['z1', 'z2', 'z3', 'z4', 'z5', 'z6'].forEach((z) => set.add(z))
      } else {
        // 匹配形如 "1、3、5 号分区" 或 "1 到 6 号分区"
        const rangeMatch = text.match(/(\d+)\s*[到~-]\s*(\d+)\s*号分区/)
        if (rangeMatch) {
          const a = Number(rangeMatch[1])
          const b = Number(rangeMatch[2])
          const lo = Math.max(1, Math.min(a, b))
          const hi = Math.min(6, Math.max(a, b))
          for (let i = lo; i <= hi; i += 1) set.add(`z${i}`)
        }
        const listMatch = text.match(/([\d、,，\s]+)号分区/)
        if (listMatch) {
          listMatch[1].split(/[、,，\s]+/).forEach((n) => {
            const num = parseInt(n, 10)
            if (num >= 1 && num <= 6) set.add(`z${num}`)
          })
        }
        // 兜底：单个 "N 号分区"
        const singles = text.matchAll(/(\d+)\s*号分区/g)
        for (const m of singles) {
          const num = parseInt(m[1], 10)
          if (num >= 1 && num <= 6) set.add(`z${num}`)
        }
      }
      if (/功放/.test(text)) set.add('amp')
      if (/外控/.test(text)) set.add('ext')
      return Array.from(set)
    },
    getScheduleSlotKey(item) {
      const manualItem = this.resolveManualItem(item)
      return Object.keys(manualItem.slotMap || {}).find((key) => {
        const slotMeta = manualItem.slotMap[key]
        return slotMeta && slotMeta.type === 'schedule'
      }) || ''
    },
    getSelectedScheduleValue(item) {
      const scheduleKey = this.getScheduleSlotKey(item)
      return scheduleKey ? String(this.getSlotValue(item, scheduleKey) || '').trim() : ''
    },
    getScheduleOption(value) {
      const scheduleValue = String(value || '').trim()
      if (!scheduleValue) return null
      return (this.slotOptions.schedule || []).find((item) => item.value === scheduleValue) || null
    },
    isScheduleOptionEnabled(option) {
      return String(option?.status || '').trim() === '启用'
    },
    isSelectedScheduleEnabled(item, seg) {
      const value = this.getSlotValue(item, seg.key)
      return this.isScheduleOptionEnabled(this.getScheduleOption(value))
    },
    getTaskOptionsForItem(item) {
      const scheduleName = this.getSelectedScheduleValue(item)
      if (!scheduleName) return []
      return this.taskOptionsBySchedule[scheduleName] || []
    },
    async ensureTaskOptionsForItem(item, options = {}) {
      const scheduleName = this.getSelectedScheduleValue(item)
      if (!scheduleName) return
      const force = Boolean(options.force)
      const existing = this.taskOptionsBySchedule[scheduleName]
      if (!force && Array.isArray(existing)) return
      if (this.taskLoadingBySchedule[scheduleName]) return
      this.$set(this.taskLoadingBySchedule, scheduleName, true)
      try {
        const base = process.env.VUE_APP_BASE_API || ''
        const requestPath = `${base}/data/broadcast_schedules/schedules/${encodeURIComponent(scheduleName)}/tasks`
        const { data } = await api.get(requestPath, { params: { _ts: Date.now() }})
        const tasks = Array.isArray(data?.tasks) ? data.tasks : []
        const names = tasks.map((task) => this.pickTaskName(task)).filter(Boolean)
        this.$set(this.taskOptionsBySchedule, scheduleName, this.uniqueOptions(names))
      } catch (err) {
        if (this.manualDrawer) {
          const requestPath = `${process.env.VUE_APP_BASE_API || ''}/data/broadcast_schedules/schedules/${encodeURIComponent(scheduleName)}/tasks`
          this.$message.error(
            this.formatRequestErrorMessage(err, requestPath, `方案“${scheduleName}”的任务列表加载失败`, 'page_data')
          )
        }
      } finally {
        this.$set(this.taskLoadingBySchedule, scheduleName, false)
      }
    },
    collectRefreshActions(payload = {}) {
      const actions = new Set()
      const intent = String(payload?.intent || '').trim()
      if (intent) actions.add(intent)
      const logs = Array.isArray(payload?.action_log) ? payload.action_log : []
      logs.forEach((item) => {
        const action = String(item?.action || '').trim()
        if (action) actions.add(action)
      })
      return actions
    },
    hasAnyAction(actions, candidates) {
      return candidates.some((item) => actions.has(item))
    },
    resetSlotOptions(types = []) {
      const uniqueTypes = Array.from(new Set((Array.isArray(types) ? types : []).filter(Boolean)))
      uniqueTypes.forEach((type) => {
        if (type === 'target') {
          this.slotOptions.target = []
          return
        }
        if (type === 'terminalGroup') {
          // terminalGroupRaw 不是数组，需特判重置成空的双段结构
          this.slotOptions.terminalGroupRaw = { groups: [], terminals: [] }
          return
        }
        if (Object.prototype.hasOwnProperty.call(this.slotOptions, type)) {
          this.slotOptions[type] = []
        }
      })
      if (uniqueTypes.includes('terminal') || uniqueTypes.includes('zone')) {
        this.slotOptions.target = []
      }
      if (uniqueTypes.includes('schedule') || uniqueTypes.includes('task') || uniqueTypes.includes('broadcastTask')) {
        this.taskOptionsBySchedule = {}
        this.taskLoadingBySchedule = {}
      }
    },
    refreshManualSlotOptions(options = {}) {
      const types = Array.isArray(options.types) && options.types.length
        ? options.types
        : ['terminal', 'zone', 'schedule', 'media', 'playMedia', 'broadcastTask', 'terminalGroup']
      types.forEach((type) => this.ensureSlotOptions(type, { force: Boolean(options.force) }))
    },
    buildSlotRequestParams(type, force = false) {
      const params = { _ts: Date.now() }
      if (force && (type === 'terminal' || type === 'zone')) {
        params.force = true
      }
      if (type === 'playMedia') {
        params.folderid = 3
      }
      return params
    },
    ensureSlotOptions(type, options = {}) {
      const force = Boolean(options.force)
      if (type === 'target') {
        this.ensureSlotOptions('terminal', options)
        this.ensureSlotOptions('zone', options)
        return
      }
      if (type === 'terminalGroup') {
        // terminalGroupRaw 是 {groups, terminals} 结构，不能走通用 array check
        const raw = this.slotOptions.terminalGroupRaw || { groups: [], terminals: [] }
        const has = (raw.groups || []).length || (raw.terminals || []).length
        if (!force && has) return
        if (this.slotLoading.terminalGroup) return
      } else {
        const existing = this.slotOptions[type]
        if (!force && Array.isArray(existing) && existing.length) return
        if (this.slotLoading[type]) return
      }
      const base = process.env.VUE_APP_BASE_API || ''
      const params = this.buildSlotRequestParams(type, force)
      if (type === 'terminal') {
        this.slotLoading.terminal = true
        api.get(`${base}/api/light/terminals`, { params })
          .then(({ data }) => {
            const list = this.normalizeList(data)
            this.slotOptions.terminal = this.uniqueOptions(list)
            this.syncTargetOptions()
          })
          .finally(() => {
            this.slotLoading.terminal = false
          })
      }
      if (type === 'zone') {
        this.slotLoading.zone = true
        api.get(`${base}/api/light/terminal-groups`, { params })
          .then(({ data }) => {
            const list = this.normalizeList(data)
            this.slotOptions.zone = this.uniqueOptions(list)
            this.syncTargetOptions()
          })
          .finally(() => {
            this.slotLoading.zone = false
          })
      }
      if (type === 'schedule') {
        this.slotLoading.schedule = true
        api.get(`${base}/data/broadcast_schedules`, { params })
          .then(({ data }) => {
            const schedules = Array.isArray(data?.schedules) ? data.schedules : []
            this.slotOptions.schedule = this.normalizeScheduleOptions(schedules)
          })
          .finally(() => {
            this.slotLoading.schedule = false
          })
      }
      if (type === 'media' || type === 'playMedia') {
        // 远端 /action/getmedia 才是真实的媒体库；本地 all_audio.json 是历史快照。
        this.slotLoading[type] = true
        api.get(`${base}/api/light/media`, { params })
          .then(({ data }) => {
            const options = Array.isArray(data?.options) ? data.options : []
            this.slotOptions[type] = options
              .map((opt) => ({
                label: String(opt.label || opt.value || '').trim(),
                value: String(opt.label || opt.value || '').trim()
              }))
              .filter((opt) => opt.value)
          })
          .finally(() => {
            this.slotLoading[type] = false
          })
      }
      if (type === 'currentTask') {
        // 拉当前启用作息方案下的任务（gettaskinfo），用于"播放任务/停止任务"下拉。
        this.slotLoading.currentTask = true
        api.get(`${base}/api/light/current-schedule-tasks`, { params })
          .then(({ data }) => {
            const tasks = Array.isArray(data?.data?.tasks)
              ? data.data.tasks
              : (Array.isArray(data?.tasks) ? data.tasks : [])
            const names = tasks
              .map((t) => String(t?.taskname || t?.name || '').trim())
              .filter(Boolean)
            this.slotOptions.currentTask = this.uniqueOptions(names)
          })
          .finally(() => {
            this.slotLoading.currentTask = false
          })
      }
      if (type === 'terminalGroup') {
        // 拉终端分组 + 单独物理终端。后端 /playable-targets 已经做了去重 + 前缀(1_/2_)。
        // 前端只用 label（人类可读名），value 会在 computed 里再加 g:/t: 前缀做 UI 内部区分。
        this.slotLoading.terminalGroup = true
        api.get(`${base}/api/light/playable-targets`, { params })
          .then(({ data }) => {
            const groups = Array.isArray(data?.groups) ? data.groups : []
            const terminals = Array.isArray(data?.terminals) ? data.terminals : []
            const pickLabel = (opt) => String(opt?.label || opt?.value || '').trim()
            this.slotOptions.terminalGroupRaw = {
              groups: groups
                .map((opt) => ({ label: pickLabel(opt), value: pickLabel(opt) }))
                .filter((opt) => opt.label),
              terminals: terminals
                .map((opt) => ({ label: pickLabel(opt), value: pickLabel(opt) }))
                .filter((opt) => opt.label)
            }
          })
          .finally(() => {
            this.slotLoading.terminalGroup = false
          })
      }
      if (type === 'broadcastTask') {
        this.slotLoading.broadcastTask = true
        api.get(`${base}/data/broadcast_schedules/broadcasts`, { params })
          .then(({ data }) => {
            const broadcasts = Array.isArray(data?.broadcasts) ? data.broadcasts : []
            const names = broadcasts.map((task) => this.pickTaskName(task)).filter(Boolean)
            this.slotOptions.broadcastTask = this.uniqueOptions(names)
          })
          .finally(() => {
            this.slotLoading.broadcastTask = false
          })
      }
    },
    normalizeScheduleOptions(list) {
      const optionMap = new Map()
      list.forEach((item) => {
        if (!item || typeof item !== 'object') return
        const value = String(item.schedule_name || item.name || '').trim()
        if (!value) return
        const status = String(item.status || '启用').trim() || '启用'
        const existing = optionMap.get(value)
        if (!existing || (existing.status !== '启用' && status === '启用')) {
          optionMap.set(value, {
            label: value,
            value,
            status,
            displayLabel: status === '启用' ? `${value} (启动)` : value
          })
        }
      })
      return Array.from(optionMap.values())
    },
    normalizeList(data, keys = ['name', 'terminalname', 'terminalName', 'zonename', 'zoneName', 'label']) {
      if (Array.isArray(data)) {
        return data.map((item) => this.pickName(item, keys)).filter(Boolean)
      }
      if (data && typeof data === 'object') {
        const list = data.data || data.rows || data.list || []
        if (Array.isArray(list)) {
          return list.map((item) => this.pickName(item, keys)).filter(Boolean)
        }
        if (list && Array.isArray(list.rows)) {
          return list.rows.map((item) => this.pickName(item, keys)).filter(Boolean)
        }
      }
      return []
    },
    pickName(item, keys) {
      if (!item || typeof item !== 'object') return ''
      for (const key of keys) {
        if (item[key]) return String(item[key])
      }
      return ''
    },
    pickTaskName(item) {
      if (!item || typeof item !== 'object') return ''
      return String(item.taskname || item.customName || item.audio || item.name || '').trim()
    },
    uniqueOptions(list) {
      const seen = new Set()
      return list
        .map((value) => String(value).trim())
        .filter((value) => value && !seen.has(value) && seen.add(value))
        .map((value) => ({ label: value, value }))
    },
    syncTargetOptions() {
      const targets = [
        ...(this.slotOptions.zone || []).map((item) => item.value),
        ...(this.slotOptions.terminal || []).map((item) => item.value)
      ]
      this.slotOptions.target = this.uniqueOptions(targets)
    },
    fillCommand(text) {
      if (!text) return
      this.command = text
      this.manualDrawer = false
      this.$nextTick(() => {
        const input = this.$refs.commandInput
        if (input && typeof input.focus === 'function') {
          input.focus()
        }
      })
    },
    fillFromTemplate(item) {
      const segments = this.parseTemplate(item)
      const manualItem = this.resolveManualItem(item)
      const requiredKeys = Array.isArray(manualItem.required) ? manualItem.required : []
      // 第一遍：每个 seg 标记成 text / filled / empty
      const parts = segments.map((seg) => {
        if (seg.type === 'text') return { kind: 'text', text: seg.text }
        const value = this.getSlotValue(item, seg.key)
        if (value) return { kind: 'filled', text: value }
        if (!requiredKeys.includes(seg.key)) return { kind: 'empty', text: '' }
        // 必填但空 → 仍塞 display 占位（保留原视觉提示，提交时后端会报缺）
        return { kind: 'filled', text: seg.display }
      })
      // 第二遍：把"纯连接词"的 text 段（紧贴 empty 槽的）也干掉，避免出现孤立的"和"/"、"。
      const connectorOnly = /^[\s、,，和]+$/
      for (let i = 0; i < parts.length; i += 1) {
        if (parts[i].kind !== 'empty') continue
        if (i > 0 && parts[i - 1].kind === 'text' && connectorOnly.test(parts[i - 1].text)) {
          parts[i - 1] = { kind: 'empty', text: '' }
        }
        if (i < parts.length - 1 && parts[i + 1].kind === 'text' && connectorOnly.test(parts[i + 1].text)) {
          parts[i + 1] = { kind: 'empty', text: '' }
        }
      }
      let text = parts.map((p) => p.text).join('')
      // 兜底清理：可选槽空着时遗留的 "，音量" / "音量XX" 之类末尾散文字
      text = text.replace(/[，,]\s*音量\s*$/u, '').trim()
      this.fillCommand(text)
    },
    formatRequired(item) {
      const manualItem = this.resolveManualItem(item)
      if (!manualItem.required || !manualItem.required.length) return ['无需参数']
      return manualItem.required
    },
    updateCloneForm(key, value) {
      this.$set(this.formState.cloneSchedule, key, value)
    },
    applyCloneSchedule() {
      const source = this.formState.cloneSchedule.source || '春季作息'
      const offset = Number(this.formState.cloneSchedule.offset || 0)
      const name = this.formState.cloneSchedule.name || '新作息'
      const offsetText = `${Math.abs(offset)}分钟`
      const direction = offset >= 0 ? '往后推迟' : '往前提前'
      const sentence = `请复制“${source}”，所有任务${direction}${offsetText}，创建为“${name}”。`
      this.fillCommand(sentence)
    },
    startDrag(e) {
      if (this.isMobileLayout) return
      this.dragState = {
        startX: e.clientX,
        startY: e.clientY,
        originLeft: this.position.left,
        originTop: this.position.top
      }
      document.addEventListener('mousemove', this.onDrag)
      document.addEventListener('mouseup', this.stopDrag)
    },
    onDrag(e) {
      if (this.isMobileLayout) return
      if (!this.dragState) return
      const deltaX = e.clientX - this.dragState.startX
      const deltaY = e.clientY - this.dragState.startY
      const nextLeft = this.dragState.originLeft + deltaX
      const nextTop = this.dragState.originTop + deltaY
      const maxLeft = window.innerWidth - this.panelWidth - 12
      const maxTop = window.innerHeight - 100
      this.position.left = Math.min(Math.max(12, nextLeft), maxLeft)
      this.position.top = Math.min(Math.max(60, nextTop), maxTop)
    },
    stopDrag() {
      this.dragState = null
      this.removeDragListeners()
    },
    removeDragListeners() {
      document.removeEventListener('mousemove', this.onDrag)
      document.removeEventListener('mouseup', this.stopDrag)
    },
    missingSlotsText(list) {
      if (!list || !list.length) return '无'
      return list.join('、')
    },
    pushMessage(role, text, meta = null, options = {}) {
      const message = {
        id: `${Date.now()}-${Math.random()}`,
        role,
        text,
        meta,
        pending: Boolean(options.pending)
      }
      this.conversation.push(message)
      this.$nextTick(() => {
        const box = this.$refs.chatBox
        if (box) box.scrollTop = box.scrollHeight
      })
      return message.id
    },
    replaceMessage(messageId, patch) {
      const index = this.conversation.findIndex((item) => item.id === messageId)
      if (index < 0) {
        return false
      }
      const current = this.conversation[index]
      this.$set(this.conversation, index, {
        ...current,
        ...(patch || {})
      })
      this.$nextTick(() => {
        const box = this.$refs.chatBox
        if (box) box.scrollTop = box.scrollHeight
      })
      return true
    },
    formatActionLog(actionLog) {
      if (!Array.isArray(actionLog) || !actionLog.length) return ''
      const labels = {
        set_task: '新增任务',
        task_cancel: '删除任务',
        task_migrate: '迁移任务',
        play_now: '立即播放',
        task_status: '状态切换',
        volume_adjust: '音量调整'
      }
      return actionLog.map((entry) => {
        const label = labels[entry.action] || entry.action || '操作'
        const ids = Array.isArray(entry.task_ids) ? entry.task_ids.join(', ') : ''
        const schedule = entry.schedule_name || '-'
        const timeRange = entry.time_range
        const rangeText = timeRange?.start || timeRange?.end
          ? `${timeRange?.start || ''} ~ ${timeRange?.end || ''}`.trim()
          : '无'
        const newRange = entry.new_time_range
        const newRangeText = newRange?.start || newRange?.end
          ? `${newRange?.start || ''} ~ ${newRange?.end || ''}`.trim()
          : ''
        const detailParts = []
        if (entry.details?.status) detailParts.push(`状态: ${entry.details.status}`)
        if (entry.details?.volume !== undefined) detailParts.push(`音量: ${entry.details.volume}`)
        if (entry.details?.audio) detailParts.push(`音频: ${entry.details.audio}`)
        const details = detailParts.length ? ` (${detailParts.join('，')})` : ''
        const newRangeLine = newRangeText ? `，新时间: ${newRangeText}` : ''
        return `${label}${details}\n排程: ${schedule}\n任务ID: ${ids || '无'}\n时间: ${rangeText}${newRangeLine}`
      }).join('\n\n')
    },
    isWarningMessage(text) {
      if (!text) return false
      return text.includes('⚠️') || text.includes('断线') || text.includes('播放失败')
    },
    normalizeDiagnostics(list) {
      if (!Array.isArray(list)) return []
      return list.filter((item) => item && typeof item === 'object').map((item) => ({
        diagnostic_id: item.diagnostic_id || '',
        action: item.action || '',
        phase: item.phase || '',
        path: item.path || '',
        request_payload: item.request_payload ?? null,
        status_code: item.status_code ?? null,
        elapsed_ms: item.elapsed_ms ?? null,
        ok: Boolean(item.ok),
        response_body: item.response_body ?? null,
        error_detail: item.error_detail || '',
        timeout: Boolean(item.timeout)
      }))
    },
    shouldShowDiagnostics(meta) {
      return Boolean(
        this.aiDiagnosticsEnabled &&
        meta &&
        Array.isArray(meta.diagnostics) &&
        meta.diagnostics.length
      )
    },
    formatDiagnosticValue(value) {
      if (value === null || value === undefined || value === '') return '-'
      if (typeof value === 'string') return value
      try {
        return JSON.stringify(value, null, 2)
      } catch (err) {
        return String(value)
      }
    },
    formatDiagnosticStatus(diag) {
      if (!diag) return '-'
      const status = diag.timeout ? 'timeout' : (diag.status_code ?? '-')
      return diag.ok ? `成功 ${status}` : `失败 ${status}`
    },
    formatDiagnosticElapsed(diag) {
      if (!diag || diag.elapsed_ms === null || diag.elapsed_ms === undefined || diag.elapsed_ms === '') {
        return '-'
      }
      return `${diag.elapsed_ms} ms`
    },
    normalizePendingAction(pendingAction) {
      if (!pendingAction || typeof pendingAction !== 'object') return null
      const rawChoices = Array.isArray(pendingAction.choices) ? pendingAction.choices : []
      const choices = rawChoices
        .map((choice, index) => {
          if (choice === null || choice === undefined || choice === '') {
            return null
          }
          if (typeof choice === 'string') {
            const label = choice.trim()
            if (!label) return null
            return {
              key: `${index}-${label}`,
              label,
              value: label,
              description: ''
            }
          }
          if (typeof choice !== 'object') {
            const label = String(choice).trim()
            if (!label) return null
            return {
              key: `${index}-${label}`,
              label,
              value: label,
              description: ''
            }
          }
          const label = String(choice.label || choice.text || choice.name || choice.value || '').trim()
          if (!label) return null
          const value = String(choice.value || choice.text || choice.label || label).trim()
          return {
            key: String(choice.id || choice.key || `${index}-${value}`),
            label,
            value,
            description: String(choice.description || choice.hint || choice.detail || '').trim()
          }
        })
        .filter(Boolean)
      if (!choices.length) return null
      return {
        title: String(pendingAction.title || pendingAction.prompt || '请从候选项中选择一个目标。'),
        hint: String(pendingAction.hint || pendingAction.message || '').trim(),
        choices
      }
    },
    hasPendingChoices(meta) {
      return Boolean(this.normalizePendingAction(meta && meta.pending_action))
    },
    getPendingChoices(meta) {
      const normalized = this.normalizePendingAction(meta && meta.pending_action)
      return normalized ? normalized.choices : []
    },
    getPendingTitle(meta) {
      const normalized = this.normalizePendingAction(meta && meta.pending_action)
      return normalized ? normalized.title : ''
    },
    getPendingHint(meta) {
      const normalized = this.normalizePendingAction(meta && meta.pending_action)
      return normalized ? normalized.hint : ''
    },
    normalizeDialogStateDetail(meta) {
      return String(meta?.dialog_state_detail || '').trim()
    },
    getDialogStateBadge(meta) {
      const detail = this.normalizeDialogStateDetail(meta)
      if (detail === 'confirm_interrupt_switch') return '切换确认'
      return ''
    },
    async submitAssistantText(userText) {
      if (this.aiLoading) return
      const text = String(userText || '').trim()
      if (!text) return
      this.pushMessage('user', text)
      this.aiLoading = true
      const pendingId = this.pushMessage('ai', '深度思考中...', null, { pending: true })
      this.pendingAssistantMessageId = pendingId
      try {
        const base = process.env.VUE_APP_BASE_API || ''
        const requestPath = `${base}/assistant/chat`
        const { data } = await api.post(requestPath, { text })
        const speech = data.output_speech || data.reply || '已收到指令。'
        const diagnostics = this.normalizeDiagnostics(data.diagnostics)
        const pendingAction = this.normalizePendingAction(data.pending_action)
        const replaced = this.replaceMessage(pendingId, {
          text: speech,
          meta: {
            intent: data.intent,
            confidence: data.confidence,
            dialog_state_detail: data.dialog_state_detail,
            missing_slots: data.missing_slots,
            diagnostics,
            pending_action: pendingAction ? { ...data.pending_action, choices: pendingAction.choices } : null
          },
          pending: false
        })
        if (!replaced) {
          this.pushMessage('ai', speech, {
            intent: data.intent,
            confidence: data.confidence,
            dialog_state_detail: data.dialog_state_detail,
            missing_slots: data.missing_slots,
            diagnostics,
            pending_action: pendingAction ? { ...data.pending_action, choices: pendingAction.choices } : null
          })
        }
        const actionLog = Array.isArray(data.action_log) ? data.action_log : []
        if (actionLog.length) {
          this.fetchAssistantLogs()
        }
        const runtimeScope = actionLog.reduce((scope, item) => {
          if (scope) return scope
          const detailScope = String(item?.details?.runtime_scope || '').trim()
          if (detailScope) return detailScope
          return String(item?.action || '').trim() === 'play_media' ? 'temp_task' : ''
        }, '')
        const warnings = Array.isArray(data.warnings) ? data.warnings : []
        if (warnings.length) {
          warnings.forEach((warning) => {
            const title = warning?.title || '设备异常警告'
            const message = warning?.content || warning?.message || ''
            if (message) {
              this.$notify({
                title,
                message,
                type: 'error',
                duration: 0
              })
            }
          })
        }
        const missingSlots = Array.isArray(data.missing_slots) ? data.missing_slots : []
        const dialogStateDetail = String(data.dialog_state_detail || 'complete').trim() || 'complete'
        const refreshIntents = [
          'create_schedule',
          'delete_schedule',
          'move_schedule',
          'swap_schedule',
          'cancel_schedule',
          'enable_schedule',
          'disable_schedule',
          'shift_schedule_later',
          'shift_schedule_earlier',
          'replace_media_in_task',
          'create_zone',
          'delete_zone',
          'enable_terminal',
          'disable_terminal',
          'add_terminal_to_zone',
          'remove_terminal_from_zone',
          'add_terminal_to_task',
          'remove_terminal_from_task',
          'play_media',
          'play_task',
          'stop_task',
          'pause_task',
          'resume_task',
          'adjust_volume'
        ]
        const shouldRefresh = actionLog.length || (
          !missingSlots.length &&
          dialogStateDetail === 'complete' &&
          refreshIntents.includes(data.intent)
        )
        if (shouldRefresh) {
          const refreshPayload = {
            intent: data.intent,
            slots: data.slots,
            action_log: actionLog,
            dialog_state_detail: dialogStateDetail,
            runtime_scope: runtimeScope || undefined
          }
          try {
            const scheduleResp = await api.get(`${base}/data/broadcast_schedules`, { params: { _ts: Date.now() }})
            emitAssistantRefresh({
              ...refreshPayload,
              schedules: scheduleResp.data
            })
          } catch (err) {
            emitAssistantRefresh(refreshPayload)
          }
        }
      } catch (err) {
        const requestPath = `${process.env.VUE_APP_BASE_API || ''}/assistant/chat`
        const failureText = this.isAssistantUnavailableError(err)
          ? '当前网络不稳定，请重新发送。'
          : this.formatRequestErrorMessage(err, requestPath, '助手调用失败，请检查后端接口', 'assistant_chat')
        const replaced = this.replaceMessage(pendingId, {
          text: failureText,
          meta: null,
          pending: false
        })
        if (!replaced) {
          this.pushMessage('ai', failureText)
        }
      } finally {
        if (this.pendingAssistantMessageId === pendingId) {
          this.pendingAssistantMessageId = null
        }
        this.aiLoading = false
      }
    },
    async sendToAssistant() {
      const userText = String(this.command || '').trim()
      if (!userText) {
        this.$message.warning('请先输入指令文本')
        return
      }
      this.command = ''
      await this.submitAssistantText(userText)
    },
    async submitPendingChoice(choice) {
      if (!choice || this.aiLoading) return
      const text = String(choice.value || choice.label || '').trim()
      if (!text) return
      try {
        await this.submitAssistantText(text)
      } catch (err) {
        // submitAssistantText already rendered the failure bubble.
      }
    },
    handleEnter(e) {
      if (e.shiftKey) return
      this.sendToAssistant()
    }
  }
}
</script>

<style lang="scss" scoped>
.ai-assistant-root {
  position: relative;
  z-index: 2000;
}

.ai-float {
  position: fixed;
  right: 24px;
  bottom: 24px;
  width: 320px;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 14px 28px rgba(31, 45, 61, 0.16);
  z-index: 2000;
  cursor: default;
  transition: box-shadow 0.2s ease;
}

.ai-mobile-trigger {
  position: fixed;
  right: calc(16px + var(--safe-right));
  bottom: calc(16px + var(--safe-bottom));
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 52px;
  padding: 0 18px;
  border: none;
  border-radius: 999px;
  background: linear-gradient(135deg, #1f2d3d 0%, #2f6fbf 100%);
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  box-shadow: 0 16px 32px rgba(31, 45, 61, 0.24);
}

.ai-float.collapsed {
  width: 320px;
  height: 46px;
  overflow: hidden;
}

.ai-float.collapsed .ai-header {
  border-bottom: none;
}

.ai-float:hover {
  box-shadow: 0 18px 32px rgba(31, 45, 61, 0.2);
}

.ai-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-bottom: 1px solid #ebeef5;
  cursor: move;
  user-select: none;
}

.title {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #1f2d3d;
  font-weight: 600;
  flex-shrink: 0;
}

.header-school-kind {
  display: inline-flex;
  align-items: center;
}

.school-kind-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border: 1px solid #d5e2f5;
  border-radius: 999px;
  background: #f7fbff;
  color: #426189;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s ease, border-color 0.2s ease, color 0.2s ease;
}

.school-kind-chip:hover,
.school-kind-chip:focus {
  outline: none;
  border-color: #a9c7f2;
  background: #edf5ff;
  color: #2c4f7a;
}

.school-kind-popover {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.school-kind-popover-title {
  font-size: 12px;
  font-weight: 600;
  color: #324057;
}

.school-kind-popover-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.school-kind-popover-label {
  font-size: 12px;
  color: #5b6b82;
}

.school-kind-popover-select {
  width: 100%;
}

.actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 6px;
}

::v-deep .header-log-btn {
  padding: 7px 10px;
  border: 1px solid #dbe4f1;
  border-radius: 10px;
  background: #f8fbff;
  color: #5b6b82;
}

::v-deep .header-log-btn:hover,
::v-deep .header-log-btn:focus {
  color: #409eff;
  border-color: #bfd8ff;
  background: #edf5ff;
}

.ai-body {
  padding: 12px;
}

.desc {
  margin: 0 0 8px;
  color: #5e6d82;
  font-size: 13px;
}

.assistant-settings-card {
  margin-bottom: 10px;
  padding: 10px;
  border: 1px solid #e7edf5;
  border-radius: 10px;
  background: linear-gradient(135deg, #fdfefe, #f4f8ff);
}

.assistant-settings-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.assistant-settings-row + .assistant-settings-row {
  margin-top: 8px;
}

.assistant-settings-select {
  min-width: 160px;
}

.assistant-settings-label {
  font-size: 13px;
  font-weight: 600;
  color: #324057;
  white-space: nowrap;
}

.assistant-settings-hint {
  margin-top: 6px;
  font-size: 12px;
  color: #6b7a90;
  line-height: 1.5;
}

.assistant-settings-warning {
  margin-top: 8px;
  padding: 6px 8px;
  border-radius: 8px;
  background: #fff4e8;
  color: #c4561a;
  font-size: 12px;
  line-height: 1.5;
}

.chat-box {
  max-height: 220px;
  overflow-y: auto;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 8px;
  margin-bottom: 8px;
  background: #f9fbff;
  user-select: text;
  -webkit-user-select: text;
}

.chat-line {
  display: flex;
  margin-bottom: 6px;
}

.chat-line.user {
  justify-content: flex-end;
}

.chat-line.ai {
  justify-content: flex-start;
}

.bubble {
  max-width: 90%;
  padding: 8px 10px;
  border-radius: 10px;
  background: #fff;
  box-shadow: 0 4px 12px rgba(31, 45, 61, 0.08);
  font-size: 13px;
  color: #1f2d3d;
  user-select: text;
  -webkit-user-select: text;
}

.chat-line.user .bubble {
  background: #ecf5ff;
}

.bubble-pending {
  background: #f5f7fa;
  border: 1px solid #e4e7ed;
  color: #606266;
}

.chat-line.ai .bubble-warning {
  background: #fff1f0;
  border: 1px solid #ffccc7;
  color: #cf1322;
}

.chat-line.ai .bubble-warning .text {
  color: inherit;
}

.text {
  white-space: pre-wrap;
  user-select: text;
  -webkit-user-select: text;
}

.thinking-text {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #606266;
}

.thinking-dots {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.thinking-dots i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  opacity: 0.35;
  animation: thinking-dot-bounce 1s infinite ease-in-out;
}

.thinking-dots i:nth-child(2) {
  animation-delay: 0.15s;
}

.thinking-dots i:nth-child(3) {
  animation-delay: 0.3s;
}

.dialog-state-badge {
  display: inline-flex;
  align-items: center;
  margin-top: 8px;
  padding: 2px 8px;
  border-radius: 999px;
  background: #eef3f8;
  color: #51606f;
  font-size: 12px;
  font-weight: 600;
}

.dialog-state-badge.is-confirm {
  background: #fff4e5;
  color: #b26a00;
}

@keyframes thinking-dot-bounce {
  0%,
  80%,
  100% {
    transform: translateY(0);
    opacity: 0.35;
  }
  40% {
    transform: translateY(-3px);
    opacity: 1;
  }
}

.diagnostic-panel {
  margin-top: 8px;
  border-top: 1px dashed #dcdfe6;
  padding-top: 8px;
}

.pending-panel {
  margin-top: 8px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid #d9e6ff;
  background: linear-gradient(180deg, #f8fbff 0%, #eef5ff 100%);
}

.pending-title {
  font-size: 12px;
  font-weight: 600;
  color: #1f2d3d;
}

.pending-hint {
  margin-top: 4px;
  font-size: 12px;
  color: #627083;
}

.pending-choices {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.pending-choice {
  display: inline-flex;
  flex-direction: column;
  align-items: flex-start;
  min-width: 0;
  white-space: normal;
  line-height: 1.3;
  text-align: left;
}

.pending-choice-main {
  font-weight: 600;
}

.pending-choice-sub {
  margin-top: 2px;
  font-size: 11px;
  color: #627083;
}

.diagnostic-details summary {
  cursor: pointer;
  color: #409eff;
  font-size: 12px;
  outline: none;
}

.diagnostic-item {
  margin-top: 8px;
  padding: 8px;
  border-radius: 8px;
  background: #f5f7fa;
}

.diagnostic-item.failed {
  background: #fff7e6;
  border: 1px solid #ffd591;
}

.diagnostic-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 4px;
}

.diagnostic-row {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  line-height: 1.5;
  word-break: break-all;
}

.diagnostic-label {
  min-width: 88px;
  color: #909399;
  flex-shrink: 0;
}

.diagnostic-failure {
  margin-top: 8px;
}

.diagnostic-block {
  margin-top: 6px;
}

.diagnostic-block pre {
  margin: 4px 0 0;
  padding: 6px 8px;
  border-radius: 6px;
  background: #1f2937;
  color: #f9fafb;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.45;
}

.meta {
  margin-top: 4px;
  color: #5e6d82;
  font-size: 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.placeholder {
  color: #909399;
  text-align: center;
  font-size: 13px;
  padding: 12px 0;
}

.ai-actions {
  display: flex;
  gap: 8px;
  margin: 8px 0;
}

::v-deep .manual-drawer {
  .el-drawer__body {
    padding: 0;
    height: 100%;
  }
}

::v-deep .log-drawer {
  .el-drawer__body {
    padding: 0;
    height: 100%;
  }
}

.log-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #f6f8fb;
  color: #1f2d3d;
}

.log-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  padding: 16px;
  background: linear-gradient(135deg, #fffaf0, #ffffff 60%);
  border-bottom: 1px solid #e6ebf5;
}

.log-title {
  font-size: 16px;
  font-weight: 600;
}

.log-subtitle {
  margin-top: 4px;
  font-size: 12px;
  color: #6b7a90;
}

.log-header-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.log-body {
  flex: 1;
  overflow: auto;
  padding: 12px;
}

.log-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.log-card {
  background: #fff;
  border: 1px solid #e8eef7;
  border-radius: 14px;
  padding: 12px;
  box-shadow: 0 8px 18px rgba(31, 45, 61, 0.06);
}

.log-card-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.log-card-title {
  font-size: 14px;
  font-weight: 600;
  color: #1f2d3d;
  line-height: 1.5;
}

.log-card-time {
  flex-shrink: 0;
  font-size: 12px;
  color: #8a94a6;
}

.log-card-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  margin-top: 8px;
  font-size: 12px;
  color: #6b7a90;
}

.log-card-row {
  margin-top: 10px;
}

.log-card-label {
  font-size: 12px;
  color: #8a94a6;
  margin-bottom: 4px;
}

.log-card-value {
  font-size: 13px;
  color: #1f2d3d;
  line-height: 1.6;
  white-space: pre-wrap;
}

.log-card-detail {
  margin: 0;
  padding: 10px;
  border-radius: 10px;
  background: #f7f9fc;
  color: #243447;
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}

.manual-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: #f6f8fb;
  color: #1f2d3d;
}

.manual-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  background: #fff;
  border-bottom: 1px solid #e6ebf5;
}

.manual-title {
  display: flex;
  align-items: center;
  gap: 10px;
}

.manual-icon {
  font-size: 22px;
}

.manual-title-text {
  font-size: 16px;
  font-weight: 600;
}

.manual-title-sub {
  font-size: 12px;
  color: #6b7a90;
  margin-top: 4px;
}

.manual-search {
  padding: 12px 16px 8px;
  background: #fff;
  border-bottom: 1px solid #f0f2f5;
}

.manual-body {
  flex: 1;
  overflow: auto;
  min-height: 0;
  padding: 8px 12px 16px;
}

.manual-tabs {
  height: 100%;
  min-height: 0;
}

::v-deep .manual-tabs .el-tabs__header,
::v-deep .manual-tabs .el-tabs__nav-wrap,
::v-deep .manual-tabs .el-tabs__content,
::v-deep .manual-tabs .el-tab-pane {
  min-height: 0;
}

::v-deep .manual-tabs .el-tabs__content {
  height: 100%;
  overflow-y: auto;
  padding-left: 8px;
}

.module-intro {
  padding: 8px 4px 10px;
}

.module-title {
  font-weight: 600;
  font-size: 14px;
}

.module-desc {
  margin-top: 4px;
  font-size: 12px;
  color: #6b7a90;
}

.manual-collapse {
  background: transparent;
  border: none;
}

::v-deep .manual-collapse .el-collapse-item__header {
  background: #fff;
  border-radius: 10px;
  margin-bottom: 8px;
  padding: 0 12px;
  border: 1px solid #e8eef7;
}

::v-deep .manual-collapse .el-collapse-item__wrap {
  background: transparent;
  border: none;
}

.collapse-title {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  justify-content: space-between;
}

.collapse-name {
  font-weight: 600;
  color: #1f2d3d;
}

.manual-card {
  background: #fff;
  border: 1px solid #e8eef7;
  border-radius: 12px;
  padding: 12px;
  margin-bottom: 12px;
  box-shadow: 0 6px 14px rgba(31, 45, 61, 0.06);
}

.card-row {
  display: flex;
  gap: 10px;
  padding: 6px 0;
  flex-wrap: wrap;
}

.card-label {
  min-width: 96px;
  font-size: 12px;
  color: #6b7a90;
}

.card-value {
  flex: 1;
  font-size: 13px;
  color: #1f2d3d;
}

.template-line {
  line-height: 1.8;
}

.variant-switch {
  display: inline-flex;
}

.fill-link {
  padding: 0;
  margin-top: 6px;
}

.slot-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  margin: 0 2px;
  border-radius: 8px;
  border: 1px dashed #f5a623;
  background: #fff7e6;
  color: #8c5a00;
  cursor: pointer;
  font-size: 12px;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}
.slot-chip > span {
  overflow: hidden;
  text-overflow: ellipsis;
}

.slot-chip.active {
  border-color: #91d5ff;
  background: #e6f7ff;
  color: #096dd9;
}

.slot-chip-schedule {
  background: #f6ffed;
  border-color: #95de64;
  color: #237804;
}

.slot-chip-status {
  color: #52c41a;
  font-weight: 600;
}

.slot-picker-title {
  font-size: 12px;
  color: #6b7a90;
  margin-bottom: 6px;
}

.time-range-picker {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.calendar-picker {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.calendar-picker-input {
  width: 100%;
}

.calendar-mode-switch {
  display: inline-flex;
  width: fit-content;
}

.time-range-presets {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.time-range-preset {
  border: 1px solid #d9e1f2;
  background: #f8fbff;
  color: #36506c;
  border-radius: 999px;
  padding: 5px 12px;
  font-size: 12px;
  cursor: pointer;
}

.time-range-preset.active,
.time-range-preset:hover {
  border-color: #91d5ff;
  background: #e6f7ff;
  color: #096dd9;
}

.time-range-hint {
  font-size: 12px;
  color: #6b7a90;
}

.time-range-hint.invalid {
  color: #d4380d;
}

.time-range-preview {
  padding: 8px 10px;
  border-radius: 8px;
  background: #f7faff;
  color: #1f2d3d;
  font-size: 12px;
}

.calendar-preview {
  padding: 8px 10px;
  border-radius: 8px;
  background: #f7faff;
  color: #1f2d3d;
  font-size: 12px;
}

.time-range-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.schedule-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.schedule-option-status {
  color: #52c41a;
  font-size: 12px;
  font-weight: 600;
}

.example-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  border-radius: 8px;
  border: 1px solid #e8eef7;
  background: #fbfdff;
  cursor: pointer;
  transition: all 0.15s ease;
}

.example-item + .example-item {
  margin-top: 6px;
}

.example-item:hover {
  border-color: #b6d4ff;
  box-shadow: 0 6px 12px rgba(31, 45, 61, 0.08);
}

.example-text {
  color: #1f2d3d;
}

.form-row .card-value {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 8px;
}

.form-label {
  font-size: 12px;
  color: #6b7a90;
  margin-bottom: 4px;
}

.manual-footer {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 16px;
  background: #fff;
  border-top: 1px solid #e6ebf5;
  font-size: 12px;
  color: #6b7a90;
}

.empty-state {
  text-align: center;
  color: #9aa4b2;
  font-size: 12px;
  padding: 16px 0;
}

@media (max-width: 768px) {
  .ai-float {
    top: calc(8px + var(--safe-top)) !important;
    right: calc(8px + var(--safe-right));
    bottom: calc(8px + var(--safe-bottom));
    left: calc(8px + var(--safe-left)) !important;
    width: auto;
    max-width: none;
    height: auto;
    border-radius: 18px;
    display: flex;
    flex-direction: column;
    box-shadow: 0 18px 40px rgba(31, 45, 61, 0.18);
  }

  .ai-float.is-mobile-open {
    min-height: calc(100dvh - var(--safe-top) - var(--safe-bottom) - 16px);
  }

  .ai-header {
    padding: 14px 14px 10px;
    cursor: default;
  }

  .actions {
    gap: 4px;
  }

  ::v-deep .header-log-btn {
    min-height: 40px;
    padding: 7px 12px;
  }

  .ai-body {
    flex: 1 1 auto;
    min-height: 0;
    display: flex;
    flex-direction: column;
    padding: 0 14px 14px;
  }

  .desc {
    margin-bottom: 10px;
  }

  .assistant-settings-card {
    margin-bottom: 12px;
  }

  .title {
    flex-wrap: wrap;
    align-items: flex-start;
  }

  .header-school-kind {
    width: 100%;
  }

  .school-kind-chip {
    width: 100%;
    justify-content: space-between;
  }

  .assistant-settings-row {
    align-items: stretch;
    flex-direction: column;
  }

  .assistant-settings-label {
    white-space: normal;
  }

  .assistant-settings-select {
    width: 100%;
  }

  .chat-box {
    flex: 1 1 auto;
    max-height: none;
    min-height: 0;
    margin-bottom: 10px;
    padding: 10px;
  }

  .bubble {
    max-width: 96%;
    padding: 10px 12px;
    font-size: 14px;
  }

  .pending-choice {
    min-height: 44px;
  }

  .ai-actions {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
    margin: 10px 0 0;
    padding-bottom: max(2px, var(--safe-bottom));
  }

  .manual-search {
    padding: 12px 16px;
  }

  .manual-body,
  .log-body {
    padding-bottom: calc(16px + var(--safe-bottom));
  }

  ::v-deep .manual-drawer-mobile .el-drawer,
  ::v-deep .log-drawer-mobile .el-drawer {
    border-radius: 18px 18px 0 0;
  }

  ::v-deep .manual-drawer-mobile .el-drawer__body,
  ::v-deep .log-drawer-mobile .el-drawer__body {
    height: 100%;
    padding-top: var(--safe-top);
  }

  ::v-deep .manual-tabs .el-tabs__header {
    margin-bottom: 10px;
  }

  ::v-deep .manual-tabs .el-tabs__nav-wrap::after {
    display: none;
  }

  ::v-deep .manual-tabs .el-tabs__content {
    padding-left: 0;
  }

  .card-label,
  .card-value {
    width: 100%;
  }
}
</style>
