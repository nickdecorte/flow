/** The agents: one per persona column, started on a drop, and the Product Owner, started from the header. */
import { UserRoundCog } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { useData } from '@/hooks/use-dashboard'
import { PRODUCT_OWNER } from '@/lib/types'

export function PersonasPage({ onPersona }: { onPersona: (key: string) => void }) {
  const { personaKeys, personas } = useData()

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="text-base font-semibold">Personas</h2>
        <p className="text-muted-foreground">
          One persona per column: the agent that starts when a card drops on it. The Product Owner starts from the
          header button and breaks an idea down into epics and stories.
        </p>
      </div>
      <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
        {personaKeys.map((key) => {
          const persona = personas[key]
          if (!persona?.exists) {
            return (
              <Card key={key} className="justify-center">
                <CardContent>
                  <Empty className="p-0">
                    <EmptyHeader>
                      <EmptyMedia variant="icon">
                        <UserRoundCog />
                      </EmptyMedia>
                      <EmptyTitle>{persona?.label ?? key}</EmptyTitle>
                      <EmptyDescription>
                        {persona?.problem
                          ? persona.problem
                          : key === PRODUCT_OWNER
                            ? 'Not created yet; the Product Owner button is disabled.'
                            : 'Not created yet; the column accepts no drops.'}
                      </EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                      <Button variant="outline" size="sm" onClick={() => onPersona(key)}>
                        Create
                      </Button>
                    </EmptyContent>
                  </Empty>
                </CardContent>
              </Card>
            )
          }
          return (
            <Card key={key}>
              <CardHeader>
                <CardDescription>{persona.label}</CardDescription>
                <CardTitle className="text-base">{persona.name}</CardTitle>
                <CardAction>
                  <Badge variant="secondary">{persona.model || 'default model'}</Badge>
                </CardAction>
              </CardHeader>
              <CardContent className="flex flex-col gap-2">
                {persona.problem ? (
                  <p className="text-destructive border-destructive rounded-lg border px-2.5 py-2">
                    {persona.problem}
                  </p>
                ) : null}
                <p className="text-muted-foreground line-clamp-6 whitespace-pre-line">{persona.role}</p>
              </CardContent>
              <CardFooter className="border-t py-3">
                <Button variant="outline" size="sm" onClick={() => onPersona(key)}>
                  Edit
                </Button>
              </CardFooter>
            </Card>
          )
        })}
      </div>
    </div>
  )
}
