/** The epic, story and space forms in the side panel, plus the delete confirmations. */
import { useState } from 'react'
import { toast } from 'sonner'

import { Field } from '@/components/panel/field'
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
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useData } from '@/hooks/use-dashboard'
import { api, mutate, spaceRequest, storyUrl } from '@/lib/api'
import { columnLabel } from '@/lib/pipeline'
import type { Dashboard, DeletionPreview, Space } from '@/lib/types'

export type ItemPanel =
  | { kind: 'epic'; space: string; epic?: string }
  | { kind: 'story-form'; space: string; epic?: string; story?: string }
  /** A new story straight into Todo, from the Board: one of `spaces`, any of its epics. */
  | { kind: 'todo-story'; spaces: string[] }
  | { kind: 'space' }

/** The two lines above an item form: where it lives, and what it is called. */
export function itemHead(data: Dashboard, panel: ItemPanel): { hint: string; title: string } {
  if (panel.kind === 'space') return { hint: 'Space', title: 'New space' }
  if (panel.kind === 'todo-story') return { hint: columnLabel(data, data.todoColumn), title: 'New story' }
  const space = data.spaces.find((s) => s.id === panel.space)
  const epic = space?.epics.find((e) => e.id === panel.epic)
  if (panel.kind === 'epic') {
    return {
      hint: `${space?.name}${epic ? ` · ${epic.id}` : ''}`,
      title: epic ? epic.title : 'New epic',
    }
  }
  const story = panel.story
    ? space?.epics.flatMap((e) => e.stories).find((s) => s.id === panel.story)
    : undefined
  return {
    hint: `${space?.name} · ${panel.story || panel.epic}`,
    title: story ? story.title : 'New story',
  }
}

export function ItemForm({
  panel,
  refresh,
  onClose,
  onStory,
  onSpace,
}: {
  panel: ItemPanel
  refresh: () => Promise<Dashboard | null>
  onClose: () => void
  onStory: (spaceId: string, storyId: string) => void
  onSpace: (id: string) => void
}) {
  const data = useData()
  const [error, setError] = useState<string | null>(null)
  const [todoSpace, setTodoSpace] = useState(panel.kind === 'todo-story' ? (panel.spaces[0] ?? '') : '')
  const [todoEpic, setTodoEpic] = useState('')
  const spaceId = panel.kind === 'space' ? null : panel.kind === 'todo-story' ? todoSpace : panel.space
  const space = data.spaces.find((s) => s.id === spaceId)
  const epic = panel.kind === 'epic' || panel.kind === 'story-form' ? space?.epics.find((e) => e.id === panel.epic) : undefined
  const story =
    panel.kind === 'story-form' && panel.story
      ? space?.epics.flatMap((e) => e.stories).find((s) => s.id === panel.story)
      : undefined
  // Default to the newest epic; a pick from another space no longer counts.
  const todoEpicId = space?.epics.some((e) => e.id === todoEpic) ? todoEpic : (space?.epics.at(-1)?.id ?? '')

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const fields = new FormData(event.currentTarget)
    const value = (name: string) => String(fields.get(name) ?? '')
    try {
      if (panel.kind === 'space') {
        const result = await mutate('POST', '/api/spaces', { name: value('name'), path: value('path') })
        const loaded = await refresh()
        const created = loaded?.spaces.find((s) => s.id === result.space)
        if (created) onSpace(created.id)
        return
      }
      const version = space!.version
      if (panel.kind === 'epic') {
        const path = panel.epic ? `/epics/${encodeURIComponent(panel.epic)}` : '/epics'
        await spaceRequest(panel.epic ? 'PATCH' : 'POST', panel.space, version, path, { title: value('title') })
        await refresh()
        onClose()
        return
      }
      const body = { title: value('title'), description: value('description'), labels: value('labels') }
      if (panel.kind === 'todo-story') {
        const created = await spaceRequest('POST', space!.id, version, `/epics/${encodeURIComponent(todoEpicId)}/stories`, body)
        try {
          await mutate('POST', storyUrl(space!.id, created.story))
        } catch (problem) {
          // The story exists now; submitting again would create a second one.
          toast.error(`${created.story} was created, but not its specification: ${(problem as Error).message}`)
        }
        await refresh()
        onStory(space!.id, created.story)
        return
      }
      const result = panel.story
        ? await spaceRequest('PATCH', panel.space, version, `/stories/${encodeURIComponent(panel.story)}`, body)
        : await spaceRequest('POST', panel.space, version, `/epics/${encodeURIComponent(panel.epic!)}/stories`, body)
      await refresh()
      onStory(panel.space, result.story)
    } catch (problem) {
      setError((problem as Error).message)
    }
  }

  return (
    <form className="flex w-full flex-col gap-3" onSubmit={submit}>
      {error ? (
        <div className="text-destructive border-destructive rounded-lg border px-2.5 py-2 text-sm">{error}</div>
      ) : null}
      {panel.kind === 'space' ? (
        <>
          <Field label="Name">
            <Input name="name" autoFocus />
          </Field>
          <Field label="Path" hint="Absolute or with ~; if the folder does not exist, it is created">
            <Input name="path" />
          </Field>
        </>
      ) : panel.kind === 'epic' ? (
        <Field label="Title">
          <Input name="title" defaultValue={epic?.title ?? ''} autoFocus />
        </Field>
      ) : (
        <>
          {panel.kind === 'todo-story' ? (
            <TodoPlace
              spaces={data.spaces.filter((s) => panel.spaces.includes(s.id))}
              space={todoSpace}
              epic={todoEpicId}
              onSpace={setTodoSpace}
              onEpic={setTodoEpic}
            />
          ) : null}
          <Field label="Title">
            <Input name="title" defaultValue={story?.title ?? ''} autoFocus />
          </Field>
          <Field label="Description" hint="Markdown, optional">
            <Textarea name="description" rows={8} defaultValue={story?.description ?? ''} />
          </Field>
          <Field label="Labels" hint="Lowercase letters, digits and dashes, separated by commas">
            <Input name="labels" defaultValue={(story?.labels ?? []).join(', ')} />
          </Field>
        </>
      )}
      <div className="flex gap-2">
        <Button type="submit" disabled={panel.kind === 'todo-story' && !todoEpicId}>
          {(panel.kind === 'epic' && panel.epic) || (panel.kind === 'story-form' && panel.story) ? 'Save' : 'Create'}
        </Button>
        {panel.kind === 'epic' && panel.epic ? (
          <DeleteItem
            kind="epic"
            spaceId={panel.space}
            id={panel.epic}
            title={epic?.title ?? ''}
            refresh={refresh}
            onDeleted={onClose}
            className="ml-auto"
          />
        ) : null}
      </div>
    </form>
  )
}

/** Where a new Todo story goes: the space (only asked with more than one) and the epic. */
function TodoPlace({
  spaces,
  space,
  epic,
  onSpace,
  onEpic,
}: {
  spaces: Space[]
  space: string
  epic: string
  onSpace: (id: string) => void
  onEpic: (id: string) => void
}) {
  const epics = spaces.find((s) => s.id === space)?.epics ?? []
  return (
    <>
      {spaces.length > 1 ? (
        <Field label="Space">
          <Select value={space} onValueChange={onSpace}>
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {spaces.map((s) => (
                <SelectItem key={s.id} value={s.id}>
                  {s.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
      ) : null}
      {epics.length ? (
        <Field label="Epic">
          <Select value={epic} onValueChange={onEpic}>
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {epics.map((e) => (
                <SelectItem key={e.id} value={e.id}>
                  {e.id} · {e.title}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
      ) : (
        <div className="text-muted-foreground rounded-lg border px-2.5 py-2 text-sm">
          This space has no epics yet. Add one in the Backlog first.
        </div>
      )}
    </>
  )
}

/** Deletes an epic or a story after naming every story and specification that goes with it. */
export function DeleteItem({
  kind,
  spaceId,
  id,
  title,
  refresh,
  onDeleted,
  className,
}: {
  kind: 'epic' | 'story'
  spaceId: string
  id: string
  title: string
  refresh: () => Promise<Dashboard | null>
  onDeleted: () => void
  className?: string
}) {
  const data = useData()
  const [preview, setPreview] = useState<DeletionPreview | null>(null)

  const ask = async () => {
    try {
      setPreview(await api(`/api/spaces/${encodeURIComponent(spaceId)}/deletion?${kind}=${encodeURIComponent(id)}`))
    } catch (problem) {
      toast.error(`Deleting failed: ${(problem as Error).message}`)
    }
  }

  const remove = async () => {
    setPreview(null)
    const space = data.spaces.find((s) => s.id === spaceId)!
    try {
      await spaceRequest('DELETE', spaceId, space.version, `/${kind === 'epic' ? 'epics' : 'stories'}/${encodeURIComponent(id)}`)
    } catch (problem) {
      toast.error(`Deleting failed: ${(problem as Error).message}`)
      return
    }
    await refresh()
    onDeleted()
  }

  return (
    <>
      <Button type="button" variant="outline" className={`text-destructive border-destructive/50 ${className ?? ''}`} onClick={ask}>
        Delete
      </Button>
      <AlertDialog open={Boolean(preview)} onOpenChange={(open) => !open && setPreview(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Delete {kind === 'epic' ? 'epic' : 'story'} {id} "{title}"?
            </AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-2">
                {kind === 'epic' ? (
                  preview?.stories.length ? (
                    <div>
                      These stories go with it:
                      <ul className="list-disc pl-5">
                        {preview.stories.map((story) => (
                          <li key={story.id}>
                            {story.id} {story.title}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : (
                    <div>The epic has no stories.</div>
                  )
                ) : null}
                {preview?.specifications.length ? (
                  <div>
                    These specifications go too:
                    <ul className="list-disc pl-5">
                      {preview.specifications.map((specification) => (
                        <li key={specification.file}>
                          {specification.file} ({columnLabel(data, specification.status)})
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : (
                  <div>No specifications go.</div>
                )}
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={remove}>Delete</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
