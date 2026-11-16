import { FilePlus2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { AgentDot, Labels, StatusPill } from '@/components/status'
import { Button } from '@/components/ui/button'
import { TableCell, TableRow } from '@/components/ui/table'
import { mutate, storyUrl } from '@/lib/api'
import type { Dashboard, Story } from '@/lib/types'

/**
 * As wide as the right half of the epic header — bar 220px + counter 60px + two `size-7` buttons
 * + three `gap-3` + `pr-3.5` = 89 spacing units — so the pill starts where the bar starts.
 */
export const STATUS_COLUMN = 'w-89 pr-3.5 pl-0'

export function StoryRow({
  spaceId,
  story,
  selected,
  onSelect,
  refresh,
}: {
  spaceId: string
  story: Story
  selected: boolean
  onSelect: (spaceId: string, storyId: string) => void
  refresh: () => Promise<Dashboard | null>
}) {
  const [adding, setAdding] = useState(false)

  // A new empty specification in Todo for a story without one; the panel then shows it.
  const addSpecification = async (event: React.MouseEvent) => {
    event.stopPropagation()
    setAdding(true)
    try {
      await mutate('POST', storyUrl(spaceId, story.id))
    } catch (problem) {
      toast.error(`Creating the specification failed: ${(problem as Error).message}`)
      setAdding(false)
      return
    }
    await refresh()
    onSelect(spaceId, story.id)
  }

  return (
    <TableRow
      onClick={() => onSelect(spaceId, story.id)}
      data-state={selected ? 'selected' : undefined}
      className="cursor-pointer"
    >
      <TableCell className="w-[90px] py-1.5 pl-3.5 align-top font-mono">{story.id}</TableCell>
      <TableCell className="py-1.5 align-top whitespace-normal">
        {story.title}
        <Labels labels={story.labels} />
      </TableCell>
      <TableCell className={`py-1.5 align-top ${STATUS_COLUMN}`}>
        {/* The pill starts at the epic's progress bar, the action ends where its last button ends. */}
        <div className="flex items-center gap-3">
          <StatusPill status={story.status} />
          <AgentDot space={spaceId} story={story.id} status={story.status} ready={story.ready} />
          {!story.specification && story.status !== 'done' ? (
            <Button
              variant="outline"
              size="icon"
              className="ml-auto size-7 shrink-0 disabled:cursor-progress"
              onClick={addSpecification}
              disabled={adding}
              title={`Empty specification in Todo for ${story.id}`}
            >
              <FilePlus2 />
            </Button>
          ) : null}
        </div>
      </TableCell>
    </TableRow>
  )
}
