/** The epics of one space, in the order of `epics` in its config: first is the highest priority. */
import { useState } from 'react'
import { toast } from 'sonner'

import { EpicSection } from '@/components/overview/epic-section'
import type { Panel } from '@/components/panel/story-panel'
import { spaceRequest } from '@/lib/api'
import type { Dashboard, Space } from '@/lib/types'

export function EpicList({
  space,
  selected,
  onSelect,
  onPanel,
  refresh,
}: {
  space: Space
  selected: string | null
  onSelect: (spaceId: string, storyId: string) => void
  onPanel: (panel: Panel) => void
  refresh: () => Promise<Dashboard | null>
}) {
  // `dragging` is the index of the dragged epic, `slot` the gap it would land in (0 = above the first).
  const [dragging, setDragging] = useState<number | null>(null)
  const [slot, setSlot] = useState<number | null>(null)
  const epics = space.epics
  const sortable = epics.length > 1

  const stop = () => {
    setDragging(null)
    setSlot(null)
  }

  const drop = async () => {
    if (dragging === null || slot === null) return stop()
    const epic = epics[dragging]
    const position = slot > dragging ? slot - 1 : slot
    stop()
    if (position === dragging) return
    try {
      await spaceRequest('PATCH', space.id, space.version, `/epics/${encodeURIComponent(epic.id)}`, { position })
    } catch (problem) {
      toast.error(`Moving failed: ${(problem as Error).message}`)
    }
    await refresh()
  }

  return (
    <div className="flex flex-col gap-2.5">
      {epics.map((epic, index) => (
        <div
          key={epic.id}
          className="relative"
          onDragOver={(event) => {
            // Only an epic of this list lands here; the half of the card under the pointer picks the gap.
            if (dragging === null) return
            event.preventDefault()
            event.dataTransfer.dropEffect = 'move'
            const box = event.currentTarget.getBoundingClientRect()
            setSlot(event.clientY < box.top + box.height / 2 ? index : index + 1)
          }}
          onDrop={(event) => {
            if (dragging === null) return
            event.preventDefault()
            void drop()
          }}
        >
          {slot === index && dragging !== null ? <DropLine className="-top-[7px]" /> : null}
          <EpicSection
            spaceId={space.id}
            epic={epic}
            selected={selected}
            onSelect={onSelect}
            onPanel={onPanel}
            refresh={refresh}
            dragging={dragging === index}
            onDragStart={sortable ? () => setDragging(index) : undefined}
            onDragEnd={stop}
          />
          {slot === epics.length && index === epics.length - 1 && dragging !== null ? (
            <DropLine className="-bottom-[7px]" />
          ) : null}
        </div>
      ))}
    </div>
  )
}

function DropLine({ className }: { className: string }) {
  return <span className={`bg-primary pointer-events-none absolute inset-x-0 h-0.5 rounded-full ${className}`} />
}
