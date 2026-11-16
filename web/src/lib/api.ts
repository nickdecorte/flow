/** The two calls the dashboard makes: a plain GET, and a write that carries the session token. */

/** `server.py` puts the token in the page it serves; the bundle itself never holds it. */
const TOKEN = document.querySelector<HTMLMetaElement>('meta[name="sdlc-token"]')?.content ?? ''

async function result(response: Response): Promise<any> {
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.error || `${response.status} ${response.statusText}`)
  return body
}

export async function api(path: string): Promise<any> {
  return result(await fetch(path, { headers: { Accept: 'application/json' } }))
}

export async function mutate(method: string, path: string, body?: object): Promise<any> {
  return result(
    await fetch(path, {
      method,
      headers: { 'Content-Type': 'application/json', 'X-SDLC-Token': TOKEN },
      body: body ? JSON.stringify(body) : undefined,
    }),
  )
}

export const storyUrl = (spaceId: string, storyId: string) =>
  `/api/spaces/${encodeURIComponent(spaceId)}/stories/${encodeURIComponent(storyId)}/specification`

/** A change to a space; the server refuses it (409) when the file changed since `version`. */
export async function spaceRequest(
  method: string,
  spaceId: string,
  version: string,
  path: string,
  body?: object,
): Promise<any> {
  const url = `/api/spaces/${encodeURIComponent(spaceId)}${path}`
  if (method === 'DELETE') return mutate(method, `${url}?version=${encodeURIComponent(version)}`)
  return mutate(method, url, { ...body, version })
}
