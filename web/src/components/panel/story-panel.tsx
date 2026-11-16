import { FileText } from 'lucide-react'

import type { FormPanel } from '@/components/panel/item-dialog'
import { DeleteItem } from '@/components/panel/item-forms'
import { SpecificationView } from '@/components/panel/specification-view'
import { IdChip, Labels, StatusPill } from '@/components/status'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { useData } from '@/hooks/use-dashboard'
import type { Dashboard, Specification } from '@/lib/types'

/** What the side panel shows: a story or a card's specification; the forms live in the dialog. */
export type Panel =
  | { kind: 'story'; space: string; story: string }
  | { kind: 'specification'; space: string; story: string }
  | FormPanel

export function StoryPanel({
  panel,
  onClose,
  loadHtml,
  refresh,
  onEdit,
}: {
  panel: Panel | null
  onClose: () => void
  loadHtml: (spaceId: string, storyId: string) => Promise<string>
  refresh: () => Promise<Dashboard | null>
  onEdit: (panel: Panel) => void
}) {
  const data = useData()
  const showsStory = panel?.kind === 'story' || panel?.kind === 'specification'
  const space = showsStory ? data.spaces.find((s) => s.id === panel.space) : undefined
  const story = showsStory ? space?.epics.flatMap((e) => e.stories).find((s) => s.id === panel.story) : undefined
  const specification = showsStory
    ? data.specifications.find((s) => s.space === panel.space && s.story === panel.story)
    : undefined

  return (
    <Sheet open={showsStory} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="gap-0 overflow-y-auto data-[side=right]:w-[min(900px,85vw)] data-[side=right]:sm:max-w-[min(900px,85vw)]">
        {panel?.kind === 'story' && space && story ? (
          <SheetHeader className="gap-0 border-b pr-12">
            <div className="text-muted-foreground text-xs">
              {space.name} · {story.id}
            </div>
            <SheetTitle className="text-base font-semibold">{story.title}</SheetTitle>
            <div className="mt-1.5">
              <StatusPill status={story.status} />
              <Labels labels={story.labels} />
            </div>
            <div className="mt-2.5 flex gap-1.5">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => onEdit({ kind: 'story-form', space: space.id, story: story.id })}
              >
                Edit
              </Button>
              <DeleteItem
                kind="story"
                spaceId={space.id}
                id={story.id}
                title={story.title}
                refresh={refresh}
                onDeleted={onClose}
              />
            </div>
          </SheetHeader>
        ) : specification ? (
          <SpecificationHead specification={specification} />
        ) : (
          <SheetHeader>
            <SheetTitle>—</SheetTitle>
          </SheetHeader>
        )}
        <div className="px-5 pt-1 pb-8">
          {/* The description above the specification, for a story from the Backlog and a card from the Board alike. */}
          {story && (panel?.kind === 'story' || story.descriptionHtml) ? (
            <>
              {story.descriptionHtml ? (
                <>
                  <div className="text-muted-foreground mt-4 text-xs tracking-wide uppercase">Description</div>
                  <Card size="sm" className="mt-2 px-3.5">
                    <div
                      className="story-description"
                      dangerouslySetInnerHTML={{ __html: story.descriptionHtml }}
                    />
                  </Card>
                </>
              ) : null}
              <div className="text-muted-foreground mt-4 text-xs tracking-wide uppercase">Specification</div>
            </>
          ) : null}
          {specification ? (
            <SpecificationView specification={specification} loadHtml={loadHtml} />
          ) : panel?.kind === 'story' ? (
            <Empty className="my-4 border">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <FileText />
                </EmptyMedia>
                <EmptyTitle>No specification yet</EmptyTitle>
                <EmptyDescription>Create one with → Todo in the Backlog.</EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : null}
        </div>
      </SheetContent>
    </Sheet>
  )
}

function SpecificationHead({ specification }: { specification: Specification }) {
  return (
    <SheetHeader className="gap-0 border-b pr-12">
      <div className="text-muted-foreground text-xs">
        {specification.spaceName} · {specification.file}
      </div>
      <SheetTitle className="text-base font-semibold">{specification.title}</SheetTitle>
      <div className="mt-1.5">
        <IdChip>{specification.story}</IdChip>
      </div>
    </SheetHeader>
  )
}
