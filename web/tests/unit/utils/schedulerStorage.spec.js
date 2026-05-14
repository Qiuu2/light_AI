import {
  clearBroadcastDraft,
  diffPlanDraft,
  discardInvalidPlanDrafts,
  loadSchedulerDrafts,
  recoverInvalidPlanDrafts,
  saveBroadcastDraft,
  savePlanDraft
} from '@/utils/schedulerStorage'

describe('schedulerStorage broadcast drafts', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('does not mark broadcasts dirty when the draft matches the base snapshot', () => {
    const baseRows = [
      {
        id: '501',
        name: 'afternoon-bell',
        durationMode: 'loop',
        loop: 1,
        location: [['zone-a', 'right-1']]
      }
    ]

    const draftState = saveBroadcastDraft(baseRows, baseRows)

    expect(draftState.dirtyScopes).toEqual([])
    expect(draftState.broadcasts).toEqual([])
    expect(draftState.broadcastDirtyIds).toEqual([])
    expect(draftState.broadcastDeletedIds).toEqual([])
    expect(draftState.broadcastBaseSnapshot).toEqual([])
    expect(loadSchedulerDrafts().dirtyScopes).toEqual([])
  })

  it('marks broadcasts dirty when the draft differs from the base snapshot', () => {
    const baseRows = [
      {
        id: '501',
        name: 'afternoon-bell',
        durationMode: 'loop',
        loop: 1,
        location: [['zone-a', 'right-1']]
      }
    ]
    const draftRows = [
      {
        id: '501',
        name: 'draft-bell',
        durationMode: 'loop',
        loop: 1,
        location: [['zone-a', 'right-1']]
      }
    ]

    const draftState = saveBroadcastDraft(draftRows, baseRows)

    expect(draftState.dirtyScopes).toEqual(['broadcasts'])
    expect(draftState.broadcasts).toEqual(draftRows)
    expect(draftState.broadcastDirtyIds).toEqual(['501'])
    expect(draftState.broadcastDeletedIds).toEqual([])
    expect(draftState.broadcastBaseSnapshot).toEqual(baseRows)
    expect(loadSchedulerDrafts().dirtyScopes).toEqual(['broadcasts'])
  })

  it('marks added broadcasts dirty by row id', () => {
    const baseRows = [
      {
        id: '501',
        name: 'afternoon-bell',
        durationMode: 'loop',
        loop: 1,
        location: [['zone-a', 'right-1']]
      }
    ]
    const draftRows = [
      ...baseRows,
      {
        id: 'draft-broadcast-1',
        taskid: 'draft-broadcast-1',
        name: 'new-bell',
        durationMode: 'loop',
        loop: 1,
        location: [['zone-a', 'right-2']]
      }
    ]

    const draftState = saveBroadcastDraft(draftRows, baseRows)

    expect(draftState.broadcastDirtyIds).toEqual(['draft-broadcast-1'])
    expect(draftState.broadcastDeletedIds).toEqual([])
    expect(draftState.dirtyScopes).toEqual(['broadcasts'])
  })

  it('marks deleted broadcasts dirty by row id', () => {
    const baseRows = [
      {
        id: '501',
        name: 'afternoon-bell',
        durationMode: 'loop',
        loop: 1,
        location: [['zone-a', 'right-1']]
      },
      {
        id: '502',
        name: 'evening-bell',
        durationMode: 'loop',
        loop: 1,
        location: [['zone-a', 'right-2']]
      }
    ]
    const draftRows = [baseRows[0]]

    const draftState = saveBroadcastDraft(draftRows, baseRows)

    expect(draftState.broadcastDirtyIds).toEqual([])
    expect(draftState.broadcastDeletedIds).toEqual(['502'])
    expect(draftState.dirtyScopes).toEqual(['broadcasts'])
  })

  it('clears an existing broadcast draft when the current rows match the base snapshot again', () => {
    const baseRows = [
      {
        id: '501',
        name: 'afternoon-bell',
        durationMode: 'loop',
        loop: 1,
        location: [['zone-a', 'right-1']]
      }
    ]

    saveBroadcastDraft([
      {
        id: '501',
        name: 'draft-bell',
        durationMode: 'loop',
        loop: 1,
        location: [['zone-a', 'right-1']]
      }
    ], baseRows)
    const clearedState = saveBroadcastDraft(baseRows, baseRows)

    expect(clearedState.dirtyScopes).toEqual([])
    expect(clearedState.broadcastDirtyIds).toEqual([])
    expect(clearedState.broadcastDeletedIds).toEqual([])
    expect(loadSchedulerDrafts().dirtyScopes).toEqual([])

    const finalState = clearBroadcastDraft()
    expect(finalState.dirtyScopes).toEqual([])
  })
})

describe('schedulerStorage plan drafts', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('isolates invalid legacy plan drafts without rewriting localStorage on load', () => {
    const rawDraftState = {
      plans: [
        { id: 'draft-invalid', name: '   ', tasks: [] },
        { id: 'draft-valid', schedule_name: 'summer-plan', tasks: [] }
      ],
      planDirtyIds: ['draft-invalid', 'draft-valid', 'missing-id'],
      planDeletedIds: ['draft-invalid', 'base-invalid', 'missing-delete'],
      planBaseSnapshot: [
        { id: 'base-invalid', schedule_name: '', tasks: [] },
        { id: 'base-valid', name: 'official-plan', tasks: [] }
      ],
      dirtyScopes: ['plans'],
      updatedAt: '2026-04-04T00:00:00.000Z'
    }

    localStorage.setItem('AI_SCHEDULER_DRAFTS_V1', JSON.stringify(rawDraftState))

    const draftState = loadSchedulerDrafts()

    expect(draftState.plans).toEqual([
      { id: 'draft-valid', name: 'summer-plan', tasks: [] }
    ])
    expect(draftState.planBaseSnapshot).toEqual([
      { id: 'base-valid', name: 'official-plan', tasks: [] }
    ])
    expect(draftState.invalidPlanDrafts).toEqual([
      { id: 'draft-invalid', name: '   ', tasks: [] }
    ])
    expect(draftState.invalidPlanBaseSnapshot).toEqual([
      { id: 'base-invalid', schedule_name: '', tasks: [] }
    ])
    expect(draftState.planDirtyIds).toEqual(['draft-valid'])
    expect(draftState.planDeletedIds).toEqual([])
    expect(draftState.planDraftIssues).toEqual([
      { type: 'invalid-plan-drafts', scope: 'plans', count: 1 },
      { type: 'invalid-plan-base-snapshot', scope: 'planBaseSnapshot', count: 1 },
      { type: 'dropped-plan-dirty-ids', scope: 'planDirtyIds', count: 2 },
      { type: 'dropped-plan-deleted-ids', scope: 'planDeletedIds', count: 3 }
    ])
    expect(JSON.parse(localStorage.getItem('AI_SCHEDULER_DRAFTS_V1'))).toEqual(rawDraftState)
  })

  it('persists explicit planDeletedIds and keeps invalid drafts isolated', () => {
    const draftState = savePlanDraft(
      [
        { id: 'draft-valid', name: 'evening-plan', tasks: [] }
      ],
      ['draft-valid'],
      [
        { id: 'base-valid', name: 'official-plan', tasks: [] }
      ],
      {
        planDeletedIds: ['base-valid'],
        invalidPlanDrafts: [{ id: 'invalid-row', name: '', tasks: [] }]
      }
    )

    expect(draftState.planDirtyIds).toEqual(['draft-valid'])
    expect(draftState.planDeletedIds).toEqual(['base-valid'])
    expect(draftState.invalidPlanDrafts).toEqual([{ id: 'invalid-row', name: '', tasks: [] }])

    const persisted = loadSchedulerDrafts()
    expect(persisted.planDeletedIds).toEqual(['base-valid'])
    expect(persisted.invalidPlanDrafts).toEqual([{ id: 'invalid-row', name: '', tasks: [] }])
  })

  it('discards invalid plan drafts only when explicitly requested', () => {
    savePlanDraft(
      [{ id: 'draft-valid', name: 'evening-plan', tasks: [] }],
      ['draft-valid'],
      [{ id: 'base-valid', name: 'official-plan', tasks: [] }],
      {
        invalidPlanDrafts: [{ id: 'invalid-row', name: '', tasks: [] }],
        invalidPlanBaseSnapshot: [{ id: 'invalid-base', schedule_name: '', tasks: [] }]
      }
    )

    const draftState = discardInvalidPlanDrafts()

    expect(draftState.invalidPlanDrafts).toEqual([])
    expect(draftState.invalidPlanBaseSnapshot).toEqual([])
    expect(draftState.plans).toEqual([{ id: 'draft-valid', name: 'evening-plan', tasks: [] }])
    expect(draftState.planBaseSnapshot).toEqual([{ id: 'base-valid', name: 'official-plan', tasks: [] }])
  })

  it('keeps unresolved invalid plan drafts isolated when recovery finds no usable name', () => {
    savePlanDraft(
      [{ id: 'draft-valid', name: 'evening-plan', tasks: [] }],
      ['draft-valid'],
      [{ id: 'base-valid', name: 'official-plan', tasks: [] }],
      {
        invalidPlanDrafts: [{ id: 'invalid-row', name: '', tasks: [] }]
      }
    )

    const draftState = recoverInvalidPlanDrafts()

    expect(draftState.plans).toEqual([{ id: 'draft-valid', name: 'evening-plan', tasks: [] }])
    expect(draftState.invalidPlanDrafts).toEqual([{ id: 'invalid-row', name: '', tasks: [] }])
  })
})

describe('diffPlanDraft', () => {
  it('updates only the dirty plan and keeps untouched base plans', () => {
    const result = diffPlanDraft(
      [
        { id: 'A', name: 'plan-a' },
        { id: 'B', name: 'plan-b' }
      ],
      [
        { id: 'A', name: 'plan-a-updated' },
        { id: 'B', name: 'plan-b' }
      ],
      ['A'],
      []
    )

    expect(result.updated.map((plan) => plan.id)).toEqual(['A'])
    expect(result.unchanged.map((plan) => plan.id)).toEqual(['B'])
    expect(result.removed).toEqual([])
    expect(result.added).toEqual([])
  })

  it('removes only explicitly deleted base plans', () => {
    const result = diffPlanDraft(
      [
        { id: 'A', name: 'plan-a' },
        { id: 'B', name: 'plan-b' }
      ],
      [
        { id: 'A', name: 'plan-a' }
      ],
      [],
      ['B']
    )

    expect(result.removed.map((plan) => plan.id)).toEqual(['B'])
    expect(result.unchanged.map((plan) => plan.id)).toEqual(['A'])
  })

  it('adds only explicitly dirty new plans', () => {
    const result = diffPlanDraft(
      [
        { id: 'A', name: 'plan-a' }
      ],
      [
        { id: 'A', name: 'plan-a' },
        { id: 'C', name: 'plan-c' }
      ],
      ['C'],
      []
    )

    expect(result.added.map((plan) => plan.id)).toEqual(['C'])
    expect(result.unchanged.map((plan) => plan.id)).toEqual(['A'])
  })

  it('throws when a dirty id exists in neither current plans nor base snapshot', () => {
    expect(() => {
      diffPlanDraft(
        [{ id: 'A', name: 'plan-a' }],
        [{ id: 'A', name: 'plan-a' }],
        ['missing'],
        []
      )
    }).toThrow('missing')
  })

  it('keeps a base plan when it is absent from the current list but not explicitly deleted', () => {
    const result = diffPlanDraft(
      [
        { id: 'A', name: 'plan-a' },
        { id: 'B', name: 'plan-b' }
      ],
      [
        { id: 'A', name: 'plan-a' }
      ],
      [],
      []
    )

    expect(result.removed).toEqual([])
    expect(result.unchanged.map((plan) => plan.id)).toEqual(['A', 'B'])
  })
})
