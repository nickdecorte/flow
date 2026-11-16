import { TriangleAlert } from 'lucide-react'
import { useState } from 'react'

import { AppHeader } from '@/components/app-header'
import { AppSidebar } from '@/components/app-sidebar'
import { ProductOwnerButton } from '@/components/product-owner-button'
import { Overview } from '@/components/overview/overview'
import { ItemDialog } from '@/components/panel/item-dialog'
import { StoryPanel, type Panel } from '@/components/panel/story-panel'
import { PersonasPage } from '@/components/personas/personas-page'
import { Board } from '@/components/pipeline/board'
import { Alert, AlertTitle } from '@/components/ui/alert'
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar'
import { Toaster } from '@/components/ui/sonner'
import { AgentsContext, DashboardContext, useDashboard } from '@/hooks/use-dashboard'
import { cardKey, selectionLabel } from '@/lib/pipeline'
import { PRODUCT_OWNER } from '@/lib/types'

export default function App() {
  const dashboard = useDashboard()
  const { data, agents, error, view } = dashboard
  const [selected, setSelected] = useState<string | null>(null)
  const [panel, setPanel] = useState<Panel | null>(null)

  const closePanel = () => {
    setPanel(null)
    setSelected(null)
  }

  const selectStory = (spaceId: string, storyId: string) => {
    setSelected(cardKey(spaceId, storyId))
    setPanel({ kind: 'story', space: spaceId, story: storyId })
  }

  return (
    <SidebarProvider>
      <AppSidebar
        view={view}
        onView={(next) => {
          dashboard.setView(next)
          closePanel()
        }}
        spaces={data?.spaces ?? []}
        selected={dashboard.spaces}
        onSelect={(next) => {
          dashboard.setSpaces(next)
          closePanel()
        }}
        onNewSpace={() => setPanel({ kind: 'space' })}
      />
      <SidebarInset>
        <AppHeader
          view={view}
          label={data ? selectionLabel(dashboard.spaces, data.spaces) : ''}
          herdrOffline={agents?.available === false}
          actions={
            data && view !== 'personas' ? (
              <ProductOwnerButton
                spaces={data.spaces.filter((s) => dashboard.spaces.includes(s.id))}
                hasPersona={Boolean(data.personas[PRODUCT_OWNER]?.exists)}
              />
            ) : null
          }
        />
        <div className="flex-1 p-4">
          {error ? (
            <Alert variant="destructive" className="my-6">
              <TriangleAlert />
              <AlertTitle>{error}</AlertTitle>
            </Alert>
          ) : data ? (
            <DashboardContext value={data}>
              <AgentsContext value={agents}>
                {view === 'overview' ? (
                  <Overview
                    selectedSpaces={dashboard.spaces}
                    selected={selected}
                    onSelect={selectStory}
                    onPanel={setPanel}
                    refresh={dashboard.refresh}
                  />
                ) : view === 'personas' ? (
                  <PersonasPage onPersona={(key) => setPanel({ kind: 'persona', key })} />
                ) : (
                  <Board
                    selectedSpaces={dashboard.spaces}
                    refresh={dashboard.refresh}
                    onOpen={(specification) =>
                      setPanel({ kind: 'specification', space: specification.space, story: specification.story })
                    }
                    onPersona={(column) => setPanel({ kind: 'persona', key: column })}
                    onNewStory={() => setPanel({ kind: 'todo-story', spaces: dashboard.spaces })}
                  />
                )}
                <StoryPanel
                  panel={panel}
                  onClose={closePanel}
                  loadHtml={dashboard.specificationHtml}
                  refresh={dashboard.refresh}
                  onEdit={setPanel}
                />
                <ItemDialog
                  panel={panel && panel.kind !== 'story' && panel.kind !== 'specification' ? panel : null}
                  onClose={closePanel}
                  refresh={dashboard.refresh}
                  onStory={selectStory}
                  onSpace={(id) => {
                    dashboard.setSpaces(dashboard.spaces.includes(id) ? dashboard.spaces : [...dashboard.spaces, id])
                    dashboard.setView('overview')
                    closePanel()
                  }}
                />
              </AgentsContext>
            </DashboardContext>
          ) : null}
        </div>
      </SidebarInset>
      <Toaster />
    </SidebarProvider>
  )
}
