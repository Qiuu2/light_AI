import TaskSchedulerPage from '@/views/task-scheduler/index.vue'

describe('TaskSchedulerPage terminal visibility', () => {
  it('filters built-in server terminals from fallback location options', () => {
    const { methods } = TaskSchedulerPage
    const ctx = {
      zoneValueLabel: (value) => `zone-${value}`,
      zoneDisplayLabel: (value) => `Zone ${value}`
    }

    const result = methods.mapLocationOptions.call(ctx, {
      data: [
        { id: 1, name: '服务器251', type: 0, zone: 1 },
        { id: 2, name: '教学楼终端', type: 1, zone: 1 },
        { id: 3, name: '操场终端', zone: 0 }
      ]
    })

    expect(result).toHaveLength(2)
    expect(result[0].children).toEqual([{ value: '教学楼终端', label: '教学楼终端' }])
    expect(result[1].children).toEqual([{ value: '操场终端', label: '操场终端' }])
    expect(JSON.stringify(result)).not.toContain('服务器251')
  })
})
