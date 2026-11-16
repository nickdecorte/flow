/** The one header of the shell: the sidebar toggle, where you are, herdr's reachability, and on Backlog and Board the Product Owner. */
import { CircleOff } from 'lucide-react'
import type { ReactNode } from 'react'

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb'
import { Separator } from '@/components/ui/separator'
import { SidebarTrigger } from '@/components/ui/sidebar'
import type { View } from '@/hooks/use-dashboard'

export const VIEW_LABELS: Record<View, string> = {
  overview: 'Backlog',
  pipeline: 'Board',
  personas: 'Personas',
}

export function AppHeader({
  view,
  label,
  herdrOffline,
  actions,
}: {
  view: View
  label: string
  herdrOffline: boolean
  actions?: ReactNode
}) {
  return (
    <header className="bg-background sticky top-0 z-20 flex h-12 shrink-0 items-center gap-2 border-b px-3">
      <SidebarTrigger />
      <Separator orientation="vertical" className="mr-1 h-4" />
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem>{label}</BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>{VIEW_LABELS[view]}</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>
      <div className="ml-auto flex items-center gap-3">
        {herdrOffline ? (
          <span
            className="text-muted-foreground flex items-center gap-1 text-xs"
            title="herdr-app or hc cannot be reached: agent states are not shown"
          >
            <CircleOff className="size-3.5" />
            herdr offline
          </span>
        ) : null}
        {actions}
      </div>
    </header>
  )
}
