import { describe, expect, it } from 'vitest'
import { readEvents, type ChatEvent } from '../src/api/stream'

function body(chunks: Uint8Array[]) {
  return new ReadableStream<Uint8Array>({ start(controller) { chunks.forEach(chunk => controller.enqueue(chunk)); controller.close() } })
}

describe('SSE framing', () => {
  it('handles split frames and split UTF-8 without duplicating final text', async () => {
    const text = 'event: started\r\ndata: {"turn_id":"one"}\r\n\r\nevent: delta\ndata: {"text":"¿Ahorramos?"}\n\nevent: completed\ndata: {"text":"¿Ahorramos?"}\n\n'
    const encoded = new TextEncoder().encode(text)
    const events: ChatEvent[] = []
    await readEvents(body(Array.from(encoded, byte => Uint8Array.of(byte))), event => events.push(event))
    expect(events.map(event => event.event)).toEqual(['started', 'delta', 'completed'])
    expect((events[1] as Extract<ChatEvent, { event: 'delta' }>).data.text).toBe('¿Ahorramos?')
  })
  it('rejects EOF without completion and closes the stream', async () => {
    await expect(readEvents(body([new TextEncoder().encode('event: delta\ndata: {"text":"partial"}\n\n')]), () => {})).rejects.toMatchObject({ code: 'incomplete_stream' })
  })
  it('delivers tool progress between text chunks on the same response', async () => {
    const frames = [
      ['started', { turn_id: 'one' }],
      ['delta', { text: 'Voy a consultar.' }],
      ['tool_status', { id: 'call-1', name: 'get_quote', status: 'running' }],
      ['tool_status', { id: 'call-1', name: 'get_quote', status: 'completed', duration_ms: 125 }],
      ['delta', { text: ' Resultado.' }],
      ['completed', { text: 'Voy a consultar. Resultado.' }],
    ]
    const events: ChatEvent[] = []
    await readEvents(body(frames.map(([name, data]) => new TextEncoder().encode(`event: ${name}\ndata: ${JSON.stringify(data)}\n\n`))), event => events.push(event))
    expect(events.map(event => event.event)).toEqual(frames.map(([name]) => name))
    expect(events[3].data).toMatchObject({ id: 'call-1', status: 'completed', duration_ms: 125 })
  })
})
