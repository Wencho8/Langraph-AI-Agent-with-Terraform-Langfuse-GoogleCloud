import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { waitFor } from '@testing-library/react'
import { api } from '../src/api/client'
import { streamChat, type ChatEvent } from '../src/api/stream'
import { getToken, saveToken } from '../src/api/transport'

const fetchMock = vi.fn()
beforeEach(() => {
  vi.stubEnv('VITE_API_BASE_URL', 'https://api.example/')
  vi.stubGlobal('fetch', fetchMock)
  fetchMock.mockReset()
  sessionStorage.clear()
})
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs() })

it('uses the direct API and Bearer without cookies, and clears a revoked session', async () => {
  saveToken('fixture-token')
  fetchMock.mockResolvedValueOnce(new Response('[]')).mockResolvedValueOnce(new Response('{"code":"unauthenticated"}', { status: 401 }))
  await api('/chat/messages')
  const [url, options] = fetchMock.mock.calls[0]
  expect(url).toBe('https://api.example/v1/chat/messages')
  expect(options.credentials).toBe('omit')
  expect(options.headers.get('Authorization')).toBe('Bearer fixture-token')
  await expect(api('/auth/session')).rejects.toMatchObject({ status: 401 })
  expect(getToken()).toBeNull()
})

it('does not clear a newer login when an old request returns 401', async () => {
  saveToken('old-token')
  let finish!: (response: Response) => void
  fetchMock.mockReturnValue(new Promise(resolve => { finish = resolve }))
  const request = api('/auth/session')
  saveToken('new-token')
  finish(new Response('{}', { status: 401 }))
  await expect(request).rejects.toMatchObject({ status: 401 })
  expect(getToken()).toBe('new-token')
})

it('delivers streaming events before the response is completed through the same authenticated transport', async () => {
  saveToken('fixture-token')
  let controller!: ReadableStreamDefaultController<Uint8Array>
  const body = new ReadableStream<Uint8Array>({ start(value) { controller = value } })
  fetchMock.mockResolvedValue(new Response(body))
  const events: ChatEvent[] = []
  const pending = streamChat('Hello', new AbortController().signal, event => events.push(event))
  const encode = (text: string) => new TextEncoder().encode(text)
  controller.enqueue(encode('event: started\ndata: {"turn_id":"one"}\n\n'))
  await waitFor(() => expect(events.map(event => event.event)).toEqual(['started']))
  expect(fetchMock.mock.calls[0][0]).toBe('https://api.example/v1/chat/messages')
  expect(fetchMock.mock.calls[0][1].headers.get('Authorization')).toBe('Bearer fixture-token')
  controller.enqueue(encode('event: delta\ndata: {"text":"Hi"}\n\nevent: completed\ndata: {"text":"Hi"}\n\n'))
  controller.close()
  await pending
  expect(events.map(event => event.event)).toEqual(['started', 'delta', 'completed'])
})
