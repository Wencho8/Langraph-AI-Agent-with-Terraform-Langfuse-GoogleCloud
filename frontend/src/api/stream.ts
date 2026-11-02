import { ApiError, responseError, type ChartBlock, type MessageBlock } from './client'

export type ToolStep = { id: string; name: string; status: 'running' | 'completed' | 'failed' | 'cancelled'; duration_ms?: number }

export function finishPending(steps: ToolStep[]): ToolStep[] {
  return steps.map(step => step.status === 'running' ? { ...step, status: 'cancelled' } : step)
}

export type ChatEvent =
  | { event: 'started'; data: { turn_id: string } }
  | { event: 'delta'; data: { text: string } }
  | { event: 'tool_status'; data: ToolStep }
  | { event: 'chart'; data: { block: ChartBlock } }
  | { event: 'completed'; data: { text: string; blocks?: MessageBlock[] } }
  | { event: 'error'; data: { code: string; message: string } }

export async function readEvents(body: ReadableStream<Uint8Array>, onEvent: (event: ChatEvent) => void) {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = '', terminal = false
  try {
    while (true) {
      const { done, value } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })
      let boundary: RegExpExecArray | null
      while ((boundary = /\r?\n\r?\n/.exec(buffer))) {
        const frame = buffer.slice(0, boundary.index)
        buffer = buffer.slice(boundary.index + boundary[0].length)
        const lines = frame.split(/\r?\n/)
        const name = lines.find(line => line.startsWith('event:'))?.slice(6).trim()
        const data = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n')
        if (!name || !data) continue
        if (terminal || !['started', 'delta', 'chart', 'tool_status', 'completed', 'error'].includes(name)) throw new ApiError(502, 'invalid_stream', 'La respuesta llegó incompleta.')
        const event = { event: name, data: JSON.parse(data) } as ChatEvent
        onEvent(event)
        if (name === 'completed' || name === 'error') terminal = true
      }
      if (done) break
    }
    if (!terminal || buffer.trim()) throw new ApiError(502, 'incomplete_stream', 'La conexión se cortó antes de completar la respuesta.')
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}

export async function streamChat(message: string, csrf: string, signal: AbortSignal, onEvent: (event: ChatEvent) => void) {
  const response = await fetch('/v1/chat/messages', {
    method: 'POST', credentials: 'same-origin', signal,
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
    body: JSON.stringify({ message }),
  })
  if (!response.ok) throw await responseError(response)
  if (!response.body) throw new ApiError(502, 'invalid_stream', 'No se recibió una respuesta.')
  await readEvents(response.body, onEvent)
}
