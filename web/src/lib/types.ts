/** The shapes the dashboard API returns; see `app/server.py` and `app/sdlc.py`. */

export type Counts = Record<string, number>

export type Meta = {
  columns: { key: string; label: string }[]
  statusOrder: string[]
  statusLabels: Record<string, string>
  taskStates: string[]
  taskLabels: Record<string, string>
  executionModes: string[]
  personaColumns: string[]
  personaKeys: string[]
  personaVariables: Record<string, string[]>
  transitions: { from: string; to: string }[]
  todoColumn: string
  doneColumn: string
}

export type Story = {
  id: string
  title: string
  description?: string
  descriptionHtml?: string
  status: string
  /** The story's step is finished (`flow.py ready`): its card shows green. */
  ready: boolean
  labels: string[]
  specification: string | null
}

export type Epic = {
  id: string
  title: string
  stories: Story[]
  counts: Counts
}

/** `/api/spaces/{id}`: a space with its epics; `version` guards every change to it. */
export type Space = {
  id: string
  name: string
  title: string
  path: string
  config: string
  version: string
  epics: Epic[]
}

/** `/api/spaces`: the same space without its epics. */
export type SpaceSummary = {
  id: string
  name: string
  title: string
  path: string
  counts: Counts
}

export type Task = { title: string; note: string; state: string }

/** `/api/specifications`: a card on the Board. `status` is the column it stands in. */
export type Specification = {
  file: string
  path: string
  title: string
  execution: string
  date: string
  tasks: Task[]
  counts: Counts
  space: string
  spaceName: string
  story: string
  status: string
  ready: boolean
}

/** The persona that belongs to no column: started from the header, without Continue. */
export const PRODUCT_OWNER = 'product-owner'

export type Persona = {
  key: string
  label: string
  exists: boolean
  name: string
  model: string
  role: string
  start: string
  continue: string
  version: string | null
  editable: boolean
  problem: string | null
}

export type DeletionPreview = {
  stories: { id: string; title: string }[]
  specifications: { file: string; title: string; status: string; path: string }[]
}

/** Everything one `load()` fetched, the way the page draws it. */
export type Dashboard = Meta & {
  spaces: Space[]
  specifications: Specification[]
  personas: Record<string, Persona>
}

/** The agent in a story's herdr tab: the persona from the tab name, and herdr's agent state. */
export type Agent = { persona: string | null; state: string }

/** The `agents` event of `/api/events`: by `space|story`; `available` is false while herdr cannot be reached. */
export type Agents = { available: boolean; agents: Record<string, Agent> }
