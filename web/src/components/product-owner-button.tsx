/** The header's Product Owner button: starts the Product Owner with one selected space as its home space. */
import { Lightbulb } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { mutate } from '@/lib/api'
import type { Space } from '@/lib/types'

// Sonner keeps an id's options across updates, so every result sets them again (as on the Board).
const TOAST = 'product-owner'
const TRANSIENT = { id: TOAST, duration: 4000, closeButton: false }
const STICKY = { id: TOAST, duration: Infinity, closeButton: true }

/** `spaces` are the selected spaces; with several, a dialog asks which one is the home space. */
export function ProductOwnerButton({ spaces, hasPersona }: { spaces: Space[]; hasPersona: boolean }) {
  const [choosing, setChoosing] = useState(false)
  const [home, setHome] = useState('')
  const [starting, setStarting] = useState(false)

  const start = async (space: Space) => {
    setChoosing(false)
    setStarting(true)
    toast.loading(`Starting Product Owner in ${space.name}…`, TRANSIENT)
    try {
      const body = await mutate('POST', `/api/spaces/${encodeURIComponent(space.id)}/product-owner`)
      toast.success(
        body.result === 'already_running'
          ? `Opened the running Product Owner in ${body.space}`
          : `Started Product Owner in ${body.space}`,
        TRANSIENT,
      )
    } catch (problem) {
      toast.error((problem as Error).message, STICKY)
    } finally {
      setStarting(false)
    }
  }

  const click = () => {
    if (spaces.length === 1) {
      void start(spaces[0])
      return
    }
    setHome(spaces[0]?.id ?? '')
    setChoosing(true)
  }

  const button = (
    <Button
      variant="outline"
      size="sm"
      className="ml-auto"
      disabled={!hasPersona || starting || spaces.length === 0}
      onClick={click}
    >
      <Lightbulb />
      Product Owner
    </Button>
  )

  return (
    <>
      {hasPersona ? (
        button
      ) : (
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="ml-auto" tabIndex={0}>
              {button}
            </span>
          </TooltipTrigger>
          <TooltipContent>No Product Owner persona</TooltipContent>
        </Tooltip>
      )}
      <Dialog open={choosing} onOpenChange={setChoosing}>
        <DialogContent className="sm:max-w-[420px]">
          <DialogHeader>
            <DialogTitle>Start the Product Owner</DialogTitle>
            <DialogDescription>
              Choose the home space: the session runs in its folder, and new epics go there unless the breakdown says
              otherwise.
            </DialogDescription>
          </DialogHeader>
          <RadioGroup value={home} onValueChange={setHome}>
            {spaces.map((space) => (
              <div key={space.id} className="flex items-center gap-2">
                <RadioGroupItem value={space.id} id={`home-${space.id}`} />
                <Label htmlFor={`home-${space.id}`}>{space.name}</Label>
              </div>
            ))}
          </RadioGroup>
          <DialogFooter>
            <Button
              disabled={!home}
              onClick={() => {
                const space = spaces.find((s) => s.id === home)
                if (space) void start(space)
              }}
            >
              Start
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
