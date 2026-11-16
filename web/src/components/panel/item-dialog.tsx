/** Every form of the dashboard — epic, story, space, persona — in one dialog. */
import { ItemForm, itemHead, type ItemPanel } from '@/components/panel/item-forms'
import { PersonaForm, personaHead } from '@/components/panel/persona-form'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useData } from '@/hooks/use-dashboard'
import type { Dashboard } from '@/lib/types'

/** The panels that are a form, not a reading view. */
export type FormPanel = ItemPanel | { kind: 'persona'; key: string }

export function ItemDialog({
  panel,
  onClose,
  refresh,
  onStory,
  onSpace,
}: {
  panel: FormPanel | null
  onClose: () => void
  refresh: () => Promise<Dashboard | null>
  onStory: (spaceId: string, storyId: string) => void
  onSpace: (id: string) => void
}) {
  const data = useData()
  const head = panel ? (panel.kind === 'persona' ? personaHead(data, panel.key) : itemHead(data, panel)) : null

  return (
    <Dialog open={Boolean(panel)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[85svh] overflow-y-auto sm:max-w-[640px]">
        <DialogHeader className="gap-0">
          <DialogDescription className="text-xs">{head?.hint}</DialogDescription>
          <DialogTitle className="text-base font-semibold">{head?.title}</DialogTitle>
        </DialogHeader>
        {panel?.kind === 'persona' ? (
          <PersonaForm personaKey={panel.key} refresh={refresh} onClose={onClose} />
        ) : panel ? (
          <ItemForm panel={panel} refresh={refresh} onClose={onClose} onStory={onStory} onSpace={onSpace} />
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
