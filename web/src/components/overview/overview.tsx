import { FolderPlus } from 'lucide-react'

import { EpicList } from '@/components/overview/epic-list'
import type { Panel } from '@/components/panel/story-panel'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Bar } from '@/components/status'
import { useData } from '@/hooks/use-dashboard'
import type { Dashboard } from '@/lib/types'

export function Overview({
  selectedSpaces,
  selected,
  onSelect,
  onPanel,
  refresh,
}: {
  selectedSpaces: string[]
  selected: string | null
  onSelect: (spaceId: string, storyId: string) => void
  onPanel: (panel: Panel) => void
  refresh: () => Promise<Dashboard | null>
}) {
  const { spaces, statusOrder, statusLabels } = useData()
  const shown = spaces.filter((s) => selectedSpaces.includes(s.id))
  if (!shown.length) return <p className="text-muted-foreground py-6">No spaces yet. Create one with + space.</p>

  return (
    <div className="flex flex-col gap-8">
      {shown.map((current) => {
        const counts: Record<string, number> = {}
        for (const epic of current.epics) {
          for (const story of epic.stories) counts[story.status] = (counts[story.status] || 0) + 1
        }
        return (
          <section key={current.id} className="flex flex-col gap-3">
            <div className="flex items-center gap-3">
              <h2 className="text-base font-semibold">{current.title}</h2>
              <Button
                variant="outline"
                size="icon"
                className="ml-auto size-7"
                title={`New epic in ${current.name}`}
                onClick={() => onPanel({ kind: 'epic', space: current.id })}
              >
                <FolderPlus />
              </Button>
            </div>
            <Card size="sm" className="px-3.5">
              <Bar counts={counts} order={statusOrder} prefix="s" names={statusLabels} className="h-3.5" />
            </Card>
            {current.epics.length ? (
              <EpicList space={current} selected={selected} onSelect={onSelect} onPanel={onPanel} refresh={refresh} />
            ) : (
              <p className="text-muted-foreground py-6">No epics yet.</p>
            )}
          </section>
        )
      })}
    </div>
  )
}
