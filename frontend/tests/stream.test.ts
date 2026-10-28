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
    expect(events[1].data.text).toBe('¿Ahorramos?')
  })
  it('rejects EOF without completion and closes the stream', async () => {
    await expect(readEvents(body([new TextEncoder().encode('event: delta\ndata: {"text":"partial"}\n\n')]), () => {})).rejects.toMatchObject({ code: 'incomplete_stream' })
  })
})
