import { Boxes, KanbanSquare, LayoutList, ListChecks, UserRoundCog, Workflow } from 'lucide-react'

import { Checkbox } from '@/components/ui/checkbox'
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupAction,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
} from '@/components/ui/sidebar'
import type { View } from '@/hooks/use-dashboard'
import { toggleSpace } from '@/lib/pipeline'

const WORK: { key: View; label: string; icon: typeof LayoutList }[] = [
  { key: 'overview', label: 'Backlog', icon: LayoutList },
  { key: 'pipeline', label: 'Board', icon: KanbanSquare },
]

export function AppSidebar({
  view,
  onView,
  spaces,
  selected,
  onSelect,
  onNewSpace,
}: {
  view: View
  onView: (view: View) => void
  spaces: { id: string; name: string }[]
  selected: string[]
  onSelect: (next: string[]) => void
  onNewSpace: () => void
}) {
  return (
    <Sidebar>
      <SidebarHeader className="px-3 py-3">
        <div className="flex items-center gap-2">
          <span className="bg-sidebar-primary text-sidebar-primary-foreground flex size-7 items-center justify-center rounded-md">
            <Workflow className="size-4" />
          </span>
          <span className="text-base font-semibold">Flow</span>
        </div>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Spaces</SidebarGroupLabel>
          {selected.length < spaces.length ? (
            <SidebarGroupAction title="Show all spaces" onClick={() => onSelect(spaces.map((s) => s.id))}>
              <ListChecks />
            </SidebarGroupAction>
          ) : null}
          <SidebarGroupContent>
            <SidebarMenu>
              {spaces.map((space) => {
                const checked = selected.includes(space.id)
                const last = checked && selected.length === 1
                return (
                  <SidebarMenuItem key={space.id}>
                    {/* A label, not a button: the checkbox is the button, and clicking the row toggles it. */}
                    <SidebarMenuButton asChild className="cursor-pointer">
                      <label title={last ? 'At least one space stays selected' : undefined}>
                        <Checkbox
                          checked={checked}
                          disabled={last}
                          onCheckedChange={() => onSelect(toggleSpace(selected, space.id))}
                        />
                        <span>{space.name}</span>
                      </label>
                    </SidebarMenuButton>
                    {last ? null : (
                      <SidebarMenuAction
                        showOnHover
                        className="aspect-auto h-5 w-auto px-1.5 text-xs"
                        title={`Show only ${space.name}`}
                        onClick={() => onSelect([space.id])}
                      >
                        Only
                      </SidebarMenuAction>
                    )}
                  </SidebarMenuItem>
                )
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
        <SidebarGroup>
          <SidebarGroupLabel>Work</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {WORK.map((item) => (
                <SidebarMenuItem key={item.key}>
                  <SidebarMenuButton isActive={item.key === view} onClick={() => onView(item.key)}>
                    <item.icon />
                    <span>{item.label}</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
        <SidebarGroup>
          <SidebarGroupLabel>Manage</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton isActive={view === 'personas'} onClick={() => onView('personas')}>
                  <UserRoundCog />
                  <span>Personas</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton onClick={onNewSpace} title="New space">
                  <Boxes />
                  <span>Spaces</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </Sidebar>
  )
}
