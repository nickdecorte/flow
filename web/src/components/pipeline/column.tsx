import { Plus, Settings } from 'lucide-react'

import type { Dragging } from '@/components/pipeline/board'
import { SpecificationCard } from '@/components/pipeline/specification-card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useData } from '@/hooks/use-dashboard'
import { cardKey, hasPersona } from '@/lib/pipeline'
import type { Specification } from '@/lib/types'

export function Column({
  column,
  label,
  specifications,
  dropOk,
  dropTarget,
  onDragEnter,
  onDragLeave,
  onDrop,
  dragging,
  onDragStart,
  onDragEnd,
  onStart,
  onOpen,
  onPersona,
  onAdd,
}: {
  column: string
  label: string
  specifications: Specification[]
  dropOk: boolean
  dropTarget: boolean
  onDragEnter: () => void
  onDragLeave: () => void
  onDrop: () => void
  dragging: Dragging | null
  onDragStart: (dragging: Dragging) => void
  onDragEnd: () => void
  onStart: (spaceId: string, storyId: string, from: string, to: string) => Promise<void>
  onOpen: (specification: Specification) => void
  onPersona: (column: string) => void
  /** Only for the column a new story can be created in. */
  onAdd?: () => void
}) {
  const data = useData()
  // Emphasis by ring thickness, not by colour: a live drop target is thicker than a merely allowed one.
  const ring = dropTarget ? 'ring-2 ring-ring' : dropOk ? 'ring-1 ring-border' : ''

  return (
    <section
      data-column={column}
      className={`bg-muted/40 flex min-w-[260px] flex-1 flex-col rounded-xl ring-inset ${ring}`}
      onDragOver={(event) => {
        if (!dropOk) return
        event.preventDefault()
        event.dataTransfer.dropEffect = 'move'
        onDragEnter()
      }}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) onDragLeave()
      }}
      onDrop={(event) => {
        if (!dropOk) return
        event.preventDefault()
        onDrop()
      }}
    >
      <h3 className="text-muted-foreground flex shrink-0 items-center gap-1.5 px-3 py-2.5 text-sm tracking-wide uppercase">
        {label}
        <span className="bg-border text-foreground inline-block min-w-5 rounded-full px-1.5 text-center text-xs">
          {specifications.length}
        </span>
        {data.personaColumns.includes(column) ? (
          <>
            {hasPersona(data, column) ? (
              <Badge variant="secondary" className="rounded-md normal-case">
                {data.personas[column].name}
              </Badge>
            ) : null}
            <Button
              variant="ghost"
              size="icon"
              className="ml-auto size-7"
              title={`Persona of ${label}`}
              onClick={() => onPersona(column)}
            >
              <Settings />
            </Button>
          </>
        ) : null}
        {onAdd ? (
          <Button variant="ghost" size="icon" className="ml-auto size-7" title={`New story in ${label}`} onClick={onAdd}>
            <Plus />
          </Button>
        ) : null}
      </h3>
      <ScrollArea className="min-h-0 flex-1">
        <div className="flex flex-col gap-2.5 px-2.5 pb-2.5">
          {specifications.length ? (
            specifications.map((specification) => {
              const key = cardKey(specification.space, specification.story)
              return (
                <SpecificationCard
                  key={key}
                  specification={specification}
                  isDragging={dragging?.space === specification.space && dragging?.story === specification.story}
                  onDragStart={onDragStart}
                  onDragEnd={onDragEnd}
                  onStart={onStart}
                  onOpen={() => onOpen(specification)}
                />
              )
            })
          ) : (
            <p className="text-muted-foreground m-1">—</p>
          )}
        </div>
      </ScrollArea>
    </section>
  )
}
