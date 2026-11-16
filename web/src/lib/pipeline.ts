/** Pure rules the board draws with: no React, no fetch. */
import type { Agents, Counts, Dashboard, Specification, Task } from '@/lib/types'

/** A card is a story with a specification; `space|story` is its key. */
export const cardKey = (spaceId: string, storyId: string) => `${spaceId}|${storyId}`

type SpaceRef = { id: string; name: string }

/** Checks or unchecks one space; the last checked space stays, so the selection is never empty. */
export const toggleSpace = (selected: string[], id: string): string[] => {
  if (!selected.includes(id)) return [...selected, id]
  return selected.length > 1 ? selected.filter((s) => s !== id) : selected
}

const parseIds = (raw: string | null): string[] | null => {
  if (raw === null) return null
  try {
    const parsed: unknown = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === 'string') : null
  } catch {
    return null
  }
}

/**
 * The selection after a load, in `spaces` order. `stored` is the raw `sdlc.spaces` (a JSON array of
 * IDs) and wins when it parses; otherwise `legacy`, the raw `sdlc.space` name, is migrated once.
 * Unknown IDs are dropped, and anything that leaves nothing selected selects every space.
 */
export const resolveSelection = (stored: string | null, legacy: string | null, spaces: SpaceRef[]): string[] => {
  const all = spaces.map((s) => s.id)
  const ids = parseIds(stored) ?? (legacy === null ? [] : spaces.filter((s) => s.name === legacy).map((s) => s.id))
  const valid = all.filter((id) => ids.includes(id))
  return valid.length > 0 ? valid : all
}

/** The space filter of the sidebar: a card shows when its space is selected. */
export const inSpaces = (specification: Specification, selected: string[]) => selected.includes(specification.space)

/** The breadcrumb: the name of one space, `All spaces` for all of several, `N spaces` otherwise. */
export const selectionLabel = (selected: string[], spaces: SpaceRef[]): string => {
  if (selected.length === 1) return spaces.find((s) => s.id === selected[0])?.name ?? selected[0]
  if (selected.length > 1 && selected.length === spaces.length) return 'All spaces'
  return `${selected.length} spaces`
}

export const hasPersona = (data: Dashboard, column: string) => Boolean(data.personas[column]?.exists)

/** The columns a card may move to because they run a persona on a drop. */
export const personaTargets = (data: Dashboard, source: string) =>
  data.transitions.filter((t) => t.from === source && hasPersona(data, t.to)).map((t) => t.to)

/** Where a card may be dropped: its persona targets, plus Done — unless it already is Done. */
export const dropTargets = (data: Dashboard, source: string) =>
  source === data.doneColumn ? [] : [...personaTargets(data, source), data.doneColumn]

/** ▶ only exists when the card's own column has a persona with a Continue text. */
export const canContinue = (data: Dashboard, column: string) =>
  hasPersona(data, column) && Boolean(data.personas[column].continue)

export const columnLabel = (data: Dashboard, column: string) =>
  data.columns.find((c) => c.key === column)?.label ?? column

/** Dropped tasks do not count towards the total shown on a card. */
export const taskTotal = (counts: Counts, tasks: Task[]) => tasks.length - counts.dropped

export type Dot = { color: 'green' | 'yellow' | 'red'; title: string }

/** herdr agent states in which the agent waits for the human. */
const NEEDS_YOU = ['blocked', 'idle', 'done', 'error']

/** Who takes over after the persona column `column`: the next persona's name, else that column's label; Done after In review. */
const nextStep = (data: Dashboard, column: string): string | null => {
  const index = data.personaColumns.indexOf(column)
  if (index < 0) return null
  const next = data.personaColumns[index + 1]
  if (!next) return columnLabel(data, data.doneColumn)
  return hasPersona(data, next) ? data.personas[next].name : columnLabel(data, next)
}

/**
 * The dot of a story: green when its step is ready (above everything), yellow while its agent works,
 * red while its agent waits for you; none without an agent, or while herdr is unknown or offline.
 */
export const agentDot = (data: Dashboard, status: string, ready: boolean, agents: Agents | null, key: string): Dot | null => {
  if (ready) {
    const next = nextStep(data, status)
    return { color: 'green', title: next ? `Ready for ${next}` : 'Ready' }
  }
  const agent = agents?.available ? agents.agents[key] : undefined
  if (!agent) return null
  const title = `${agent.persona ?? 'Agent'} · ${agent.state}`
  if (agent.state === 'working') return { color: 'yellow', title }
  return NEEDS_YOU.includes(agent.state) ? { color: 'red', title } : null
}
