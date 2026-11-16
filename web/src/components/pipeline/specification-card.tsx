import { Play } from 'lucide-react'
import { useState } from 'react'

import type { Dragging } from '@/components/pipeline/board'
import { AgentDot, Bar, ExecutionLabel, IdChip } from '@/components/status'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { useData } from '@/hooks/use-dashboard'
import { canContinue, cardKey, columnLabel, dropTargets, taskTotal } from '@/lib/pipeline'
import type { Specification } from '@/lib/types'

export function SpecificationCard({
  specification,
  isDragging,
  onDragStart,
  onDragEnd,
  onStart,
  onOpen,
}: {
  specification: Specification
  isDragging: boolean
  onDragStart: (dragging: Dragging) => void
  onDragEnd: () => void
  onStart: (spaceId: string, storyId: string, from: string, to: string) => Promise<void>
  onOpen: () => void
}) {
  const data = useData()
  const [starting, setStarting] = useState(false)
  const total = taskTotal(specification.counts, specification.tasks)
  const targets = dropTargets(data, specification.status)
  const draggable = targets.length > 0

  return (
    <Card
      size="sm"
      className={`gap-2 ${draggable ? 'cursor-grab' : ''} ${isDragging ? 'opacity-50' : ''}`}
      draggable={draggable}
      title={draggable ? `Drag to ${targets.map((target) => columnLabel(data, target)).join(', ')}` : undefined}
      onDragStart={(event) => {
        event.dataTransfer.setData('text/plain', cardKey(specification.space, specification.story))
        event.dataTransfer.effectAllowed = 'move'
        onDragStart({ space: specification.space, story: specification.story, from: specification.status })
      }}
      onDragEnd={onDragEnd}
    >
      <CardHeader className="flex flex-wrap items-center gap-0.5">
        <span className="text-muted-foreground mr-1.5 text-xs">{specification.spaceName}</span>
        <IdChip>{specification.story}</IdChip>
        <ExecutionLabel execution={specification.execution} />
        <span className="ml-1.5 flex items-center">
          <AgentDot
            space={specification.space}
            story={specification.story}
            status={specification.status}
            ready={specification.ready}
          />
        </span>
        {canContinue(data, specification.status) ? (
          <Button
            variant="outline"
            size="icon"
            className="ml-auto size-7 disabled:cursor-progress"
            title={`Continue with ${data.personas[specification.status].name}`}
            disabled={starting}
            onClick={async () => {
              setStarting(true)
              await onStart(specification.space, specification.story, specification.status, specification.status)
              setStarting(false)
            }}
          >
            <Play />
          </Button>
        ) : null}
      </CardHeader>
      <CardContent className="flex flex-col gap-1">
        <Button
          variant="link"
          className="h-auto justify-start p-0 text-left font-semibold whitespace-normal"
          onClick={onOpen}
        >
          {specification.title}
        </Button>
        <div className="mt-1 flex items-center gap-2">
          <Bar counts={specification.counts} order={data.taskStates} prefix="t" names={data.taskLabels} />
          <span className="text-muted-foreground text-xs whitespace-nowrap">
            {specification.counts.done}/{total}
          </span>
        </div>
        {specification.counts.blocked || specification.counts.waiting ? (
          <div className="flex gap-2">
            {specification.counts.blocked ? (
              <span className="text-task-blocked text-xs font-semibold">
                ● {specification.counts.blocked} blocked
              </span>
            ) : null}
            {specification.counts.waiting ? (
              <span className="text-task-waiting text-xs font-semibold">● {specification.counts.waiting} waiting</span>
            ) : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}
