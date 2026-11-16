import { useState } from 'react'
import { toast } from 'sonner'

import { Column } from '@/components/pipeline/column'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { useData } from '@/hooks/use-dashboard'
import { mutate, storyUrl } from '@/lib/api'
import { cardKey, dropTargets, inSpaces } from '@/lib/pipeline'
import type { Dashboard, Specification } from '@/lib/types'

/** The card being dragged: its key and the column the page sees it in. */
export type Dragging = { space: string; story: string; from: string }

// Sonner keeps an id's options across updates, so a result on an id that showed an error must reset them.
const TRANSIENT = { duration: 4000, closeButton: false }
const STICKY = { duration: Infinity, closeButton: true }

export function Board({
  selectedSpaces,
  refresh,
  onOpen,
  onPersona,
  onNewStory,
}: {
  selectedSpaces: string[]
  refresh: () => Promise<Dashboard | null>
  onOpen: (specification: Specification) => void
  onPersona: (column: string) => void
  onNewStory: () => void
}) {
  const data = useData()
  const [dragging, setDragging] = useState<Dragging | null>(null)
  const [hovered, setHovered] = useState<string | null>(null)
  const [confirming, setConfirming] = useState<Specification | null>(null)
  const shown = data.specifications.filter((s) => inSpaces(s, selectedSpaces))

  /** Toasts live outside the card, so the story must be identifiable from the title alone. */
  const toastTitle = (spaceId: string, storyId: string) => {
    const specification = data.specifications.find((s) => s.space === spaceId && s.story === storyId)
    return specification ? `${storyId} · ${specification.title}` : storyId
  }

  /** Start the persona of `to`; `to === from` continues in the card's own column. */
  const start = async (spaceId: string, storyId: string, from: string, to: string) => {
    const key = cardKey(spaceId, storyId)
    const title = toastTitle(spaceId, storyId)
    toast.loading(title, { id: key, description: 'Starting session…', ...TRANSIENT })
    try {
      const body = await mutate('POST', `${storyUrl(spaceId, storyId)}/start`, { from, to })
      if (body.result === 'already_running') {
        toast.info(title, { id: key, description: `Session already running: opened tab ${body.tab} in ${body.space}`, ...TRANSIENT })
      } else {
        toast.success(title, { id: key, description: `Session started: tab ${body.tab} in ${body.space}`, ...TRANSIENT })
      }
    } catch (problem) {
      toast.error(title, { id: key, description: (problem as Error).message, ...STICKY })
    }
    await refresh()
  }

  const complete = async (specification: Specification) => {
    const key = cardKey(specification.space, specification.story)
    const title = toastTitle(specification.space, specification.story)
    toast.loading(title, { id: key, description: 'Closing…', ...TRANSIENT })
    try {
      const body = await mutate('POST', `${storyUrl(specification.space, specification.story)}/complete`, {
        from: specification.status,
      })
      toast.success(title, { id: key, description: `Closed: ${body.story} on done`, ...TRANSIENT })
    } catch (problem) {
      toast.error(title, { id: key, description: (problem as Error).message, ...STICKY })
    }
    await refresh()
  }

  const drop = (column: string) => {
    if (!dragging) return
    const { space: spaceId, story: storyId, from } = dragging
    setDragging(null)
    setHovered(null)
    if (column !== data.doneColumn) return void start(spaceId, storyId, from, column)
    const specification = data.specifications.find((s) => s.space === spaceId && s.story === storyId)
    if (specification) setConfirming(specification)
  }

  const open = confirming?.tasks.filter((t) => !['done', 'dropped'].includes(t.state)).length ?? 0

  return (
    <>
      {/* The board itself only scrolls sideways; each column scrolls its own cards. */}
      <div className="flex h-[calc(100svh-5rem)] gap-3 overflow-x-auto">
        {data.columns.map((column) => (
          <Column
            key={column.key}
            column={column.key}
            label={column.label}
            specifications={shown.filter((s) => s.status === column.key)}
            dropOk={Boolean(dragging) && dropTargets(data, dragging!.from).includes(column.key)}
            dropTarget={hovered === column.key}
            onDragEnter={() => setHovered(column.key)}
            onDragLeave={() => setHovered((current) => (current === column.key ? null : current))}
            onDrop={() => drop(column.key)}
            dragging={dragging}
            onDragStart={setDragging}
            onDragEnd={() => {
              setDragging(null)
              setHovered(null)
            }}
            onStart={start}
            onOpen={onOpen}
            onPersona={onPersona}
            onAdd={column.key === data.todoColumn ? onNewStory : undefined}
          />
        ))}
      </div>
      <AlertDialog open={Boolean(confirming)} onOpenChange={(next) => !next && setConfirming(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Move "{confirming?.title}" to Done?</AlertDialogTitle>
            <AlertDialogDescription>
              {confirming?.story} goes to done.
              {open ? ` Note: ${open} open ${open === 1 ? 'task' : 'tasks'} left.` : ''}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                const specification = confirming!
                setConfirming(null)
                void complete(specification)
              }}
            >
              To Done
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
