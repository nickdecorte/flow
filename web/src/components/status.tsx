/** The small status drawings shared by the Backlog, the Board and the panel. */
import { Badge } from '@/components/ui/badge'
import { useAgents, useData } from '@/hooks/use-dashboard'
import { agentDot, cardKey, type Dot } from '@/lib/pipeline'
import type { Counts } from '@/lib/types'

// Tailwind only generates classes it reads in the source, so every token is spelled out per key.
const FILL: Record<'s' | 't', Record<string, string>> = {
  s: {
    'waiting-for-analysis': 'bg-status-waiting-for-analysis',
    todo: 'bg-status-todo',
    'in-analysis': 'bg-status-in-analysis',
    'in-development': 'bg-status-in-development',
    'in-review': 'bg-status-in-review',
    done: 'bg-status-done',
  },
  t: {
    done: 'bg-task-done',
    waiting: 'bg-task-waiting',
    blocked: 'bg-task-blocked',
    pending: 'bg-task-pending',
    dropped: 'bg-task-dropped',
  },
}

const PILL: Record<string, string> = {
  'waiting-for-analysis': 'border-status-waiting-for-analysis bg-status-waiting-for-analysis/20',
  todo: 'border-status-todo bg-status-todo/20',
  'in-analysis': 'border-status-in-analysis bg-status-in-analysis/20',
  'in-development': 'border-status-in-development bg-status-in-development/20',
  'in-review': 'border-status-in-review bg-status-in-review/20',
  done: 'border-status-done bg-status-done/20',
}

/** A segmented progress bar; `prefix` picks the colour tokens (`s` for statuses, `t` for tasks). */
export function Bar({
  counts,
  order,
  prefix,
  names,
  className,
}: {
  counts: Counts
  order: string[]
  prefix: 's' | 't'
  names: Record<string, string>
  className?: string
}) {
  return (
    <div className={`bg-border flex h-2.5 min-w-[120px] overflow-hidden rounded-[5px] ${className ?? ''}`}>
      {order
        .filter((key) => counts[key])
        .map((key) => (
          <span
            key={key}
            // The colour is a class; only the share of the bar is data and cannot be a class.
            className={FILL[prefix][key] ?? 'bg-muted-foreground'}
            style={{ flexGrow: counts[key] }}
            title={`${names[key]}: ${counts[key]}`}
          />
        ))}
    </div>
  )
}

export function StatusPill({ status }: { status: string }) {
  const { statusLabels } = useData()
  return (
    <Badge variant="outline" className={`rounded-full ${PILL[status] ?? ''}`}>
      {statusLabels[status]}
    </Badge>
  )
}

const DOT: Record<Dot['color'], string> = {
  green: 'bg-task-done',
  yellow: 'bg-task-waiting',
  red: 'bg-task-blocked',
}

/** The story's colour dot: ready, its agent working, or its agent waiting for you; nothing otherwise. */
export function AgentDot({ space, story, status, ready }: { space: string; story: string; status: string; ready: boolean }) {
  const dot = agentDot(useData(), status, ready, useAgents(), cardKey(space, story))
  if (!dot) return null
  return (
    <span
      role="img"
      aria-label={dot.title}
      title={dot.title}
      className={`inline-block size-2.5 shrink-0 rounded-full ${DOT[dot.color]}`}
    />
  )
}

export function Labels({ labels }: { labels: string[] }) {
  return (
    <>
      {labels.map((label) => (
        <Badge
          key={label}
          variant="outline"
          className={`ml-1.5 rounded-md ${label === 'buiten-mvp' ? 'line-through' : ''} ${
            label === 'beslissen' ? 'border-status-in-analysis text-status-in-analysis' : ''
          }`}
        >
          {label}
        </Badge>
      ))}
    </>
  )
}

/** The story ID, set in the same monospace chip as the old page. */
export function IdChip({ children }: { children: string }) {
  return (
    <span className="bg-background mr-1 inline-block rounded border px-1.5 font-mono text-xs">{children}</span>
  )
}

export function ExecutionLabel({ execution }: { execution: string }) {
  return (
    <Badge variant="secondary" className="ml-1.5 rounded-md" title="Execution">
      {execution}
    </Badge>
  )
}
