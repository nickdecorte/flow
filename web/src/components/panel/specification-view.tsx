import { TriangleAlert } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Bar, ExecutionLabel, StatusPill } from '@/components/status'
import { Alert, AlertTitle } from '@/components/ui/alert'
import { useData } from '@/hooks/use-dashboard'
import { columnLabel, taskTotal } from '@/lib/pipeline'
import type { Specification } from '@/lib/types'

/** The specification's metadata and its markdown, rendered by the server from the local file. */
export function SpecificationView({
  specification,
  loadHtml,
}: {
  specification: Specification
  loadHtml: (spaceId: string, storyId: string) => Promise<string>
}) {
  const data = useData()
  const [html, setHtml] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let current = true
    setHtml(null)
    setError(null)
    loadHtml(specification.space, specification.story).then(
      (loaded) => current && setHtml(loaded),
      (problem: Error) => current && setError(`Loading the specification failed: ${problem.message}`),
    )
    return () => {
      current = false
    }
  }, [loadHtml, specification.space, specification.story])

  if (error)
    return (
      <Alert variant="destructive" className="my-6">
        <TriangleAlert />
        <AlertTitle>{error}</AlertTitle>
      </Alert>
    )

  return (
    <>
      <div className="text-muted-foreground my-3.5 flex items-center gap-2.5 text-xs">
        <StatusPill status={specification.status} />
        <span>{columnLabel(data, specification.status)}</span>
        <ExecutionLabel execution={specification.execution} />
        <span className="shrink-0 grow-0 basis-40">
          <Bar counts={specification.counts} order={data.taskStates} prefix="t" names={data.taskLabels} />
        </span>
        <span className="shrink-0 whitespace-nowrap">
          {specification.counts.done}/{taskTotal(specification.counts, specification.tasks)} tasks
        </span>
        <a className="underline" href={`file://${encodeURI(specification.path)}`} title={specification.path}>
          open .md
        </a>
      </div>
      {html === null ? null : <div className="specification-body" dangerouslySetInnerHTML={{ __html: html }} />}
    </>
  )
}
