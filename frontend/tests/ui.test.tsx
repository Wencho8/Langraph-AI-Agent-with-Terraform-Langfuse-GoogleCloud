import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App'
import AuthForm from '../src/auth/AuthForm'
import Chat from '../src/chat/Chat'
import { api, ApiError, type Session } from '../src/api/client'
import { streamChat, type ChatEvent } from '../src/api/stream'

vi.mock('../src/api/client', async original => ({ ...await original<typeof import('../src/api/client')>(), api: vi.fn() }))
vi.mock('../src/api/stream', async original => ({ ...await original<typeof import('../src/api/stream')>(), streamChat: vi.fn() }))
const session: Session = { user: { id: 'alice', username: 'alice', display_name: 'Alice' }, csrf_token: 'csrf', expires_at: new Date(Date.now() + 86400000).toISOString() }
const mockedApi = vi.mocked(api)
const mockedStream = vi.mocked(streamChat)
beforeEach(() => { vi.resetAllMocks(); mockedApi.mockResolvedValue([]) })

describe('access screens', () => {
  it('shows login only for an absent session; dependencies offer retry', async () => {
    mockedApi.mockRejectedValue(new ApiError(503, 'dependency_unavailable', 'unavailable'))
    render(<App />)
    expect(await screen.findByRole('button', { name: 'Volver a intentar' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Contraseña')).not.toBeInTheDocument()
    mockedApi.mockRejectedValue(new ApiError(401, 'unauthenticated', 'sign in'))
    fireEvent.click(screen.getByRole('button', { name: 'Volver a intentar' }))
    expect(await screen.findByLabelText('Contraseña')).toBeInTheDocument()
  })
  it('validates repeated password before submitting registration', async () => {
    render(<AuthForm onLogin={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Creá una cuenta' }))
    fireEvent.change(screen.getByLabelText('Contraseña'), { target: { value: 'long enough password' } })
    fireEvent.change(screen.getByLabelText('Repetí la contraseña'), { target: { value: 'different password' } })
    fireEvent.submit(screen.getByRole('button', { name: /Crear mi cuenta/ }).closest('form')!)
    expect(await screen.findByRole('alert')).toHaveTextContent('no coinciden')
    expect(mockedApi).not.toHaveBeenCalled()
  })
})

async function composer() {
  const input = await screen.findByRole('textbox', { name: 'Tu mensaje' })
  await waitFor(() => expect(input).not.toBeDisabled())
  fireEvent.change(input, { target: { value: 'A finance question' } })
  return { input, form: input.closest('form')! }
}

describe('chat lifecycle', () => {
  it('locks synchronously, streams, and replaces deltas with the canonical answer', async () => {
    let emit!: (event: ChatEvent) => void, finish!: () => void
    mockedStream.mockImplementation((_message, _csrf, _signal, onEvent) => { emit = onEvent; return new Promise(resolve => { finish = resolve }) })
    render(<Chat session={session} onExpired={vi.fn()} />)
    const { input, form } = await composer()
    fireEvent.submit(form); fireEvent.submit(form)
    expect(input).toBeDisabled(); expect(mockedStream).toHaveBeenCalledTimes(1)
    act(() => { emit({ event: 'started', data: { turn_id: 'one' } }); emit({ event: 'delta', data: { text: '**partial draft**' } }) })
    expect(screen.getByText('partial draft').tagName).toBe('STRONG')
    mockedApi.mockResolvedValue([{ id: 'saved', role: 'assistant', content: '**Final answer**', turn_id: 'one', created_at: '' }])
    await act(async () => { emit({ event: 'completed', data: { text: '**Final answer**' } }); finish() })
    await waitFor(() => expect(input).not.toBeDisabled())
    expect(screen.getAllByText('Final answer')).toHaveLength(1)
    expect(screen.getByText('Final answer').tagName).toBe('STRONG')
    expect(screen.queryByText('partial draft')).not.toBeInTheDocument()
  })
  it.each([409, 429, 503, 502])('unlocks the composer after HTTP/stream failure %s', async status => {
    mockedStream.mockRejectedValue(new ApiError(status, 'fixture_failure', 'Try again'))
    render(<Chat session={session} onExpired={vi.fn()} />)
    const { input, form } = await composer()
    fireEvent.submit(form)
    expect(await screen.findByRole('alert')).toHaveTextContent('Try again')
    await waitFor(() => expect(input).not.toBeDisabled())
    expect(input).toHaveValue('A finance question')
  })
  it('expires authentication on 401', async () => {
    const expired = vi.fn()
    mockedStream.mockRejectedValue(new ApiError(401, 'unauthenticated', 'expired'))
    render(<Chat session={session} onExpired={expired} />)
    fireEvent.submit((await composer()).form)
    await waitFor(() => expect(expired).toHaveBeenCalled())
  })
  it('aborts an old stream and ignores its late results after switching users', async () => {
    let signal!: AbortSignal, emit!: (event: ChatEvent) => void, finish!: () => void
    mockedStream.mockImplementation((_message, _csrf, passedSignal, onEvent) => { signal = passedSignal; emit = onEvent; return new Promise(resolve => { finish = resolve }) })
    const view = render(<Chat key="alice" session={session} onExpired={vi.fn()} />)
    fireEvent.submit((await composer()).form)
    view.rerender(<Chat key="bob" session={{ ...session, user: { id: 'bob', username: 'bob', display_name: 'Bob' } }} onExpired={vi.fn()} />)
    expect(signal.aborted).toBe(true)
    await act(async () => { emit({ event: 'delta', data: { text: 'OLD PRIVATE MESSAGE' } }); finish() })
    expect(screen.queryByText('OLD PRIVATE MESSAGE')).not.toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: /Hola, Bob/ })).toBeInTheDocument()
  })
})
