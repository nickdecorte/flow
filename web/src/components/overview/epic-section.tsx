import { ChevronRight, GripVertical, ListPlus, Pencil } from 'lucide-react'

import { STATUS_COLUMN, StoryRow } from '@/components/overview/story-row'
import type { Panel } from '@/components/panel/story-panel'
import { Bar } from '@/components/status'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Table, TableBody, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useData } from '@/hooks/use-dashboard'
import { cardKey } from '@/lib/pipeline'
import type { Dashboard, Epic } from '@/lib/types'

export function EpicSection({
  spaceId,
  epic,
  selected,
  onSelect,
  onPanel,
  refresh,
  dragging = false,
  onDragStart,
  onDragEnd,
}: {
  spaceId: string
  epic: Epic
  selected: string | null
  onSelect: (spaceId: string, storyId: string) => void
  onPanel: (panel: Panel) => void
  refresh: () => Promise<Dashboard | null>
  /** This epic is the one being dragged. */
  dragging?: boolean
  /** Set when the epic can move to another place in its space's list; shows the grip. */
  onDragStart?: () => void
  onDragEnd?: () => void
}) {
  const { statusOrder, statusLabels } = useData()
  const done = epic.counts.done || 0

  return (
    <Collapsible
      defaultOpen={done < epic.stories.length || !epic.stories.length}
      className={`group/epic ${dragging ? 'opacity-50' : ''}`}
      asChild
    >
      <Card size="sm" className="gap-0 py-0" data-epic={epic.id}>
        <CardHeader className="flex items-center gap-3 px-3.5 py-2.5">
          {onDragStart ? (
            // Only the grip drags, so selecting the title or clicking a button never starts a drag.
            <span
              draggable
              className="text-muted-foreground hover:text-foreground -mr-1.5 cursor-grab active:cursor-grabbing"
              title={`Drag ${epic.id} to change its priority`}
              onDragStart={(event) => {
                const card = event.currentTarget.closest('[data-epic]')
                if (card) event.dataTransfer.setDragImage(card, 16, 16)
                event.dataTransfer.setData('text/plain', epic.id)
                event.dataTransfer.effectAllowed = 'move'
                onDragStart()
              }}
              onDragEnd={onDragEnd}
            >
              <GripVertical className="size-4" />
            </span>
          ) : null}
          {/* Only the title toggles; the buttons next to it keep doing their own thing. */}
          <CollapsibleTrigger className="flex min-w-0 flex-1 cursor-pointer items-center gap-1.5 text-left">
            <ChevronRight className="text-muted-foreground size-4 shrink-0 transition-transform group-data-[state=open]/epic:rotate-90" />
            <span className="truncate">
              <b>{epic.id}</b> {epic.title}
            </span>
          </CollapsibleTrigger>
          <Bar
            counts={epic.counts}
            order={statusOrder}
            prefix="s"
            names={statusLabels}
            className="hidden w-[220px] shrink-0 md:flex"
          />
          <span className="text-muted-foreground w-[60px] shrink-0 tabular-nums">
            {done}/{epic.stories.length}
          </span>
          <Button
            variant="outline"
            size="icon"
            className="size-7"
            title={`New story in ${epic.id}`}
            onClick={() => onPanel({ kind: 'story-form', space: spaceId, epic: epic.id })}
          >
            <ListPlus />
          </Button>
          <Button
            variant="outline"
            size="icon"
            className="size-7"
            title={`Rename or delete ${epic.id}`}
            onClick={() => onPanel({ kind: 'epic', space: spaceId, epic: epic.id })}
          >
            <Pencil />
          </Button>
        </CardHeader>
        <CollapsibleContent>
          <CardContent className="border-t px-0 pt-0">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="h-8 w-[90px] pl-3.5">ID</TableHead>
                  <TableHead className="h-8">Title</TableHead>
                  <TableHead className={`h-8 ${STATUS_COLUMN}`}>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {epic.stories.map((story) => (
                  <StoryRow
                    key={story.id}
                    spaceId={spaceId}
                    story={story}
                    selected={selected === cardKey(spaceId, story.id)}
                    onSelect={onSelect}
                    refresh={refresh}
                  />
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </CollapsibleContent>
      </Card>
    </Collapsible>
  )
}
