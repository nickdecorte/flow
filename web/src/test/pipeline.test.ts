import { describe, expect, it } from 'vitest'

import {
  agentDot,
  canContinue,
  columnLabel,
  dropTargets,
  hasPersona,
  inSpaces,
  personaTargets,
  resolveSelection,
  selectionLabel,
  taskTotal,
  toggleSpace,
} from '@/lib/pipeline'
import type { Agents, Dashboard, Persona, Specification, Task } from '@/lib/types'

const COLUMNS = ['todo', 'in-analysis', 'in-development', 'in-review', 'done']
const PERSONA_COLUMNS = ['in-analysis', 'in-development', 'in-review']

/** The transitions the server derives from `drop_allowed`: forward onto a persona column, plus In review → In development. */
const TRANSITIONS = [
  { from: 'todo', to: 'in-analysis' },
  { from: 'in-analysis', to: 'in-development' },
  { from: 'in-analysis', to: 'in-review' },
  { from: 'in-development', to: 'in-review' },
  { from: 'in-review', to: 'in-development' },
]

const persona = (column: string, withContinue: boolean): Persona => ({
  key: column,
  label: column,
  exists: true,
  name: `${column}-persona`,
  model: '',
  role: 'role',
  start: 'start',
  continue: withContinue ? 'continue' : '',
  version: 'v1',
  editable: true,
  problem: null,
})

const dashboard = (personas: Record<string, Persona>): Dashboard =>
  ({
    columns: COLUMNS.map((key) => ({ key, label: key === 'in-analysis' ? 'In analysis' : key })),
    personaColumns: PERSONA_COLUMNS,
    transitions: TRANSITIONS,
    doneColumn: 'done',
    personas,
  }) as Dashboard

const ALL_PERSONAS = dashboard({
  'in-analysis': persona('in-analysis', true),
  'in-development': persona('in-development', true),
  'in-review': persona('in-review', false),
})

describe('dropTargets', () => {
  it('offers the persona columns of the allowed transitions plus Done', () => {
    expect(dropTargets(ALL_PERSONAS, 'todo')).toEqual(['in-analysis', 'done'])
    expect(dropTargets(ALL_PERSONAS, 'in-analysis')).toEqual(['in-development', 'in-review', 'done'])
    expect(dropTargets(ALL_PERSONAS, 'in-review')).toEqual(['in-development', 'done'])
  })

  it('drops a column without a persona, keeping Done', () => {
    const data = dashboard({ 'in-development': persona('in-development', true) })
    expect(personaTargets(data, 'todo')).toEqual([])
    expect(dropTargets(data, 'todo')).toEqual(['done'])
    expect(dropTargets(data, 'in-analysis')).toEqual(['in-development', 'done'])
  })

  it('leaves a card in Done without any target', () => {
    expect(dropTargets(ALL_PERSONAS, 'done')).toEqual([])
  })

  it('never offers a column whose persona file is missing', () => {
    const data = dashboard({ 'in-analysis': { ...persona('in-analysis', true), exists: false } })
    expect(hasPersona(data, 'in-analysis')).toBe(false)
    expect(dropTargets(data, 'todo')).toEqual(['done'])
  })
})

describe('canContinue', () => {
  it('needs a persona with a Continue text in the card’s own column', () => {
    expect(canContinue(ALL_PERSONAS, 'in-development')).toBe(true)
    expect(canContinue(ALL_PERSONAS, 'in-review')).toBe(false)
    expect(canContinue(ALL_PERSONAS, 'todo')).toBe(false)
  })
})

describe('taskTotal', () => {
  it('leaves dropped tasks out of the total', () => {
    const tasks = [
      { title: 'a', note: '', state: 'done' },
      { title: 'b', note: '', state: 'pending' },
      { title: 'c', note: '', state: 'dropped' },
    ] satisfies Task[]
    expect(taskTotal({ done: 1, waiting: 0, blocked: 0, pending: 1, dropped: 1 }, tasks)).toBe(2)
    expect(taskTotal({ done: 1, waiting: 0, blocked: 0, pending: 2, dropped: 0 }, tasks)).toBe(3)
  })
})

const SPACES = [
  { id: 'a', name: 'Alpha' },
  { id: 'b', name: 'Beta' },
  { id: 'c', name: 'Gamma' },
]

describe('toggleSpace', () => {
  it('adds an unchecked space and removes a checked one', () => {
    expect(toggleSpace(['a'], 'b')).toEqual(['a', 'b'])
    expect(toggleSpace(['a', 'b'], 'a')).toEqual(['b'])
  })

  it('keeps the last checked space', () => {
    expect(toggleSpace(['a'], 'a')).toEqual(['a'])
  })
})

describe('resolveSelection', () => {
  it('keeps a valid stored selection in the order of the spaces', () => {
    expect(resolveSelection('["c","a"]', null, SPACES)).toEqual(['a', 'c'])
  })

  it('drops stored IDs that no longer exist', () => {
    expect(resolveSelection('["b","gone"]', null, SPACES)).toEqual(['b'])
  })

  it('selects every space when nothing valid is left', () => {
    expect(resolveSelection('["gone"]', null, SPACES)).toEqual(['a', 'b', 'c'])
    expect(resolveSelection('[]', null, SPACES)).toEqual(['a', 'b', 'c'])
    expect(resolveSelection(null, null, SPACES)).toEqual(['a', 'b', 'c'])
  })

  it('selects every space when the stored value is corrupt', () => {
    expect(resolveSelection('not json', null, SPACES)).toEqual(['a', 'b', 'c'])
    expect(resolveSelection('{"a":1}', null, SPACES)).toEqual(['a', 'b', 'c'])
  })

  it('migrates a legacy space name to its ID', () => {
    expect(resolveSelection(null, 'Beta', SPACES)).toEqual(['b'])
  })

  it('migrates legacy All or an unknown legacy name to every space', () => {
    expect(resolveSelection(null, 'All', SPACES)).toEqual(['a', 'b', 'c'])
    expect(resolveSelection(null, 'Gone', SPACES)).toEqual(['a', 'b', 'c'])
  })

  it('prefers the stored selection over the legacy name', () => {
    expect(resolveSelection('["c"]', 'Beta', SPACES)).toEqual(['c'])
  })
})

describe('inSpaces', () => {
  const card = { space: 'b', spaceName: 'Beta' } as Specification

  it('keeps a card whose space ID is selected', () => {
    expect(inSpaces(card, ['a', 'b'])).toBe(true)
    expect(inSpaces(card, ['a', 'c'])).toBe(false)
    expect(inSpaces(card, ['Beta'])).toBe(false)
  })
})

describe('selectionLabel', () => {
  it('names one space, says All spaces for all, and counts otherwise', () => {
    expect(selectionLabel(['b'], SPACES)).toBe('Beta')
    expect(selectionLabel(['a', 'b', 'c'], SPACES)).toBe('All spaces')
    expect(selectionLabel(['a', 'c'], SPACES)).toBe('2 spaces')
  })

  it('names the only space even though it is all of them', () => {
    expect(selectionLabel(['a'], SPACES.slice(0, 1))).toBe('Alpha')
  })
})

describe('columnLabel', () => {
  it('falls back to the key when the column is unknown', () => {
    expect(columnLabel(ALL_PERSONAS, 'in-analysis')).toBe('In analysis')
    expect(columnLabel(ALL_PERSONAS, 'made-up')).toBe('made-up')
  })
})

describe('agentDot', () => {
  const KEY = 'flow|E1S1'
  const online = (state: string, persona: string | null = 'Analyst'): Agents => ({
    available: true,
    agents: { [KEY]: { persona, state } },
  })

  it('is green when the step is ready, whatever the agent does', () => {
    expect(agentDot(ALL_PERSONAS, 'in-analysis', true, online('working'), KEY)).toEqual({
      color: 'green',
      title: 'Ready for in-development-persona',
    })
  })

  it('names the next column when it has no persona, and Done after In review', () => {
    const noReviewer = dashboard({ 'in-analysis': persona('in-analysis', true) })
    expect(agentDot(noReviewer, 'in-development', true, null, KEY)?.title).toBe('Ready for in-review')
    expect(agentDot(ALL_PERSONAS, 'in-review', true, null, KEY)?.title).toBe(
      `Ready for ${columnLabel(ALL_PERSONAS, 'done')}`,
    )
  })

  it('stays green while herdr is offline or unknown', () => {
    expect(agentDot(ALL_PERSONAS, 'in-analysis', true, { available: false, agents: {} }, KEY)?.color).toBe('green')
    expect(agentDot(ALL_PERSONAS, 'in-analysis', true, null, KEY)?.color).toBe('green')
  })

  it('is yellow while the agent works', () => {
    expect(agentDot(ALL_PERSONAS, 'in-analysis', false, online('working'), KEY)).toEqual({
      color: 'yellow',
      title: 'Analyst · working',
    })
  })

  it('is red for every state in which the agent waits for you', () => {
    for (const state of ['blocked', 'idle', 'done', 'error']) {
      expect(agentDot(ALL_PERSONAS, 'in-analysis', false, online(state), KEY)).toEqual({
        color: 'red',
        title: `Analyst · ${state}`,
      })
    }
  })

  it('names a tab without persona Agent', () => {
    expect(agentDot(ALL_PERSONAS, 'in-analysis', false, online('idle', null), KEY)?.title).toBe('Agent · idle')
  })

  it('shows nothing without an agent, while herdr is offline or unknown, or for an unknown state', () => {
    expect(agentDot(ALL_PERSONAS, 'in-analysis', false, { available: true, agents: {} }, KEY)).toBeNull()
    expect(agentDot(ALL_PERSONAS, 'in-analysis', false, { ...online('working'), available: false }, KEY)).toBeNull()
    expect(agentDot(ALL_PERSONAS, 'in-analysis', false, null, KEY)).toBeNull()
    expect(agentDot(ALL_PERSONAS, 'in-analysis', false, online('starting'), KEY)).toBeNull()
  })
})
