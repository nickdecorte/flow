/**
 * One `load()` fetches everything in parallel; every change reloads all of it. `/api/events` pushes
 * the herdr agents, and says when a file changed (an agent, a shell or another page wrote it).
 */
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'

import { api, storyUrl } from '@/lib/api'
import { cardKey, resolveSelection } from '@/lib/pipeline'
import type { Agents, Dashboard, Space, SpaceSummary } from '@/lib/types'

export type View = 'overview' | 'pipeline' | 'personas'
const VIEWS: View[] = ['overview', 'pipeline', 'personas']

/** Everything loaded, for the components that only draw it. */
export const DashboardContext = createContext<Dashboard | null>(null)

export function useData(): Dashboard {
  const data = useContext(DashboardContext)
  if (!data) throw new Error('No dashboard data')
  return data
}

/** The herdr agents from the last `agents` event; null until the first one and while the stream is down. */
export const AgentsContext = createContext<Agents | null>(null)

export const useAgents = () => useContext(AgentsContext)

const storedView = (): View => {
  const stored = localStorage.getItem('sdlc.tab') as View | null
  return stored && VIEWS.includes(stored) ? stored : 'overview'
}

async function load(): Promise<Dashboard> {
  const [meta, summaries, specifications, personas] = await Promise.all([
    api('/api/meta'),
    api('/api/spaces'),
    api('/api/specifications'),
    api('/api/personas'),
  ])
  const spaces: Space[] = await Promise.all(
    (summaries as SpaceSummary[]).map((s) => api(`/api/spaces/${encodeURIComponent(s.id)}`)),
  )
  return {
    ...meta,
    spaces,
    specifications,
    personas: Object.fromEntries((personas as Dashboard['personas'][string][]).map((p) => [p.key, p])),
  }
}

export type DashboardState = {
  data: Dashboard | null
  agents: Agents | null
  error: string | null
  view: View
  setView: (view: View) => void
  /** The IDs of the selected spaces; empty until the first load, never empty after it. */
  spaces: string[]
  setSpaces: (next: string[]) => void
  specificationHtml: (spaceId: string, storyId: string) => Promise<string>
  /** The freshly loaded data, so a caller can look up what it just created; `null` after a failure. */
  refresh: () => Promise<Dashboard | null>
}

export function useDashboard(): DashboardState {
  const [data, setData] = useState<Dashboard | null>(null)
  const [agents, setAgents] = useState<Agents | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [view, setViewState] = useState<View>(storedView)
  const [spaces, setSpacesState] = useState<string[]>([])
  const html = useRef<Record<string, string>>({})

  const refresh = useCallback(async () => {
    let loaded: Dashboard
    try {
      loaded = await load()
    } catch (problem) {
      setError(`API unreachable: ${(problem as Error).message}`)
      return null
    }
    html.current = {}
    setError(null)
    setData(loaded)
    // Resolve after the load: unknown IDs drop out, and a legacy `sdlc.space` name is migrated once.
    const legacy = localStorage.getItem('sdlc.space')
    const selection = resolveSelection(localStorage.getItem('sdlc.spaces'), legacy, loaded.spaces)
    localStorage.setItem('sdlc.spaces', JSON.stringify(selection))
    if (legacy !== null) localStorage.removeItem('sdlc.space')
    setSpacesState(selection)
    return loaded
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  // The first load is the effect above; a reconnect may have missed `changed` events, so it reloads.
  useEffect(() => {
    const source = new EventSource('/api/events')
    let connected = false
    source.addEventListener('agents', (event) => setAgents(JSON.parse((event as MessageEvent).data)))
    source.addEventListener('changed', () => void refresh())
    source.onopen = () => {
      if (connected) void refresh()
      connected = true
    }
    source.onerror = () => setAgents(null)
    return () => source.close()
  }, [refresh])

  const setView = useCallback((next: View) => {
    localStorage.setItem('sdlc.tab', next)
    setViewState(next)
  }, [])

  const setSpaces = useCallback((next: string[]) => {
    localStorage.setItem('sdlc.spaces', JSON.stringify(next))
    setSpacesState(next)
  }, [])

  const specificationHtml = useCallback(async (spaceId: string, storyId: string) => {
    const key = cardKey(spaceId, storyId)
    if (!(key in html.current)) html.current[key] = (await api(storyUrl(spaceId, storyId))).html
    return html.current[key]
  }, [])

  return { data, agents, error, view, setView, spaces, setSpaces, specificationHtml, refresh }
}
