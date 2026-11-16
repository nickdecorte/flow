/** A persona: the role, the first message, and for a column persona the one behind ▶. */
import { useState } from 'react'

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
import { Textarea } from '@/components/ui/textarea'
import { useData } from '@/hooks/use-dashboard'
import { mutate } from '@/lib/api'
import { PRODUCT_OWNER, type Dashboard } from '@/lib/types'

type Message = { kind: 'ok' | 'error'; text: string }

/** The two lines above the persona form: what the persona is for, and its name. */
export function personaHead(data: Dashboard, key: string): { hint: string; title: string } {
  const persona = data.personas[key]
  return {
    hint: `Persona · ${persona.label}`,
    title: persona.exists ? persona.name : 'Create persona',
  }
}

export function PersonaForm({
  personaKey,
  refresh,
  onClose,
}: {
  personaKey: string
  refresh: () => Promise<Dashboard | null>
  onClose: () => void
}) {
  const data = useData()
  const persona = data.personas[personaKey]
  const productOwner = personaKey === PRODUCT_OWNER
  const [message, setMessage] = useState<Message | null>(null)
  const [asking, setAsking] = useState(false)
  const readOnly = persona.exists && !persona.editable

  const save = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const fields = new FormData(event.currentTarget)
    const body = Object.fromEntries(
      ['name', 'model', 'role', 'start', 'continue'].map((field) => [field, String(fields.get(field) ?? '')]),
    )
    try {
      await mutate('PUT', `/api/personas/${personaKey}`, { ...body, version: persona.version })
      await refresh()
      setMessage({ kind: 'ok', text: 'Saved' })
    } catch (problem) {
      setMessage({ kind: 'error', text: (problem as Error).message })
    }
  }

  const remove = async () => {
    setAsking(false)
    try {
      await mutate('DELETE', `/api/personas/${personaKey}?version=${encodeURIComponent(persona.version ?? '')}`)
    } catch (problem) {
      setMessage({ kind: 'error', text: (problem as Error).message })
      return
    }
    await refresh()
    onClose()
  }

  return (
    <>
      <form className="flex w-full flex-col gap-3" onSubmit={save}>
        {message ? (
          <div
            className={`rounded-lg border px-2.5 py-2 text-sm ${
              message.kind === 'ok' ? 'border-task-done text-task-done' : 'border-destructive text-destructive'
            }`}
          >
            {message.text}
          </div>
        ) : null}
        {readOnly ? (
          <div className="text-destructive border-destructive rounded-lg border px-2.5 py-2 text-sm">
            This file cannot be edited from the dashboard: {persona.problem}. Edit personas/{personaKey}.md in
            your editor.
          </div>
        ) : null}
        <Field label="Name">
          <Input name="name" defaultValue={persona.name} readOnly={readOnly} />
        </Field>
        <Field label="Model" hint="Empty = your default model in omp, e.g. opus">
          <Input name="model" defaultValue={persona.model} readOnly={readOnly} />
        </Field>
        <Field label="Role" hint="Applies to the whole session (system prompt)">
          <Textarea name="role" rows={14} defaultValue={persona.role} readOnly={readOnly} />
        </Field>
        <Field
          label="Start"
          hint={productOwner ? 'First message when you start the Product Owner' : `First message when a card drops on ${persona.label}`}
        >
          <Textarea name="start" rows={5} defaultValue={persona.start} readOnly={readOnly} />
        </Field>
        {productOwner ? null : (
          <Field label="Continue" hint="First message on ▶ on a card in this column; empty = no ▶">
            <Textarea name="continue" rows={4} defaultValue={persona.continue} readOnly={readOnly} />
          </Field>
        )}
        <div className="text-muted-foreground text-xs">
          Variables:{' '}
          {data.personaVariables[personaKey].map((variable) => (
            <code key={variable} className="bg-muted mr-1 rounded border px-1">{`{{${variable}}}`}</code>
          ))}
        </div>
        <div className="flex gap-2">
          {readOnly ? null : <Button type="submit">Save</Button>}
          {persona.exists ? (
            <Button
              type="button"
              variant="outline"
              className="text-destructive border-destructive/50 ml-auto"
              onClick={() => setAsking(true)}
            >
              Delete
            </Button>
          ) : null}
        </div>
      </form>
      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {productOwner ? 'Delete the Product Owner?' : `Delete the persona of ${persona.label}?`}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {productOwner ? 'The Product Owner button is then disabled.' : 'The column then no longer accepts drops.'}
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
