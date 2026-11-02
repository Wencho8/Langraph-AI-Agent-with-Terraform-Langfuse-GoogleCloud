import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, ApiError, errorMessage, type Message, type Session, type MessageBlock, appendText } from '../api/client'
import { streamChat, finishPending, type ToolStep } from '../api/stream'
import ToolActivity from './ToolActivity'
import Icon from '../Icon'
import AssistantMessage from './AssistantMessage'

type DisplayMessage = Message & { unsaved?: boolean; streaming?: boolean }
const suggestions = [
  { label: 'Ver un gráfico de YPF', prompt: 'Mostrame un gráfico de YPFD del último mes y explicame su evolución.' },
  { label: 'Comparar AL30 y GD30', prompt: 'Compará AL30 y GD30 durante el último mes con un gráfico base 100.' },
  { label: 'Entender una ON', prompt: '¿Qué es una obligación negociable y qué riesgos debería revisar?' },
]

export default function Chat({ session, onExpired }: { session: Session; onExpired: () => void }) {
  const [items, setItems] = useState<DisplayMessage[]>([])
  const [activity, setActivity] = useState<Record<string, ToolStep[]>>({})
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [historyFailed, setHistoryFailed] = useState(false)
  const [loggingOut, setLoggingOut] = useState(false)
  const busyRef = useRef(false)
  const epoch = useRef(0)
  const stream = useRef<AbortController | null>(null)
  const tail = useRef<HTMLDivElement>(null)

  async function loadHistory(version = epoch.current, signal?: AbortSignal) {
    try {
      const history = await api<Message[]>('/chat/messages', { signal })
      if (version === epoch.current) { setItems(history); setHistoryFailed(false); return history }
    } catch (error) {
      if (version !== epoch.current || signal?.aborted) return
      if (error instanceof ApiError && error.status === 401) onExpired()
      else { setError(errorMessage(error)); setHistoryFailed(true) }
    } finally { if (version === epoch.current) setLoading(false) }
  }

  useEffect(() => {
    const controller = new AbortController()
    const version = ++epoch.current
    void loadHistory(version, controller.signal)
    return () => { epoch.current++; controller.abort(); stream.current?.abort() }
    // This component is keyed by account and unmounted on logout/expiration.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => { tail.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [items, activity])

  async function send(event: FormEvent) {
    event.preventDefault()
    const message = draft.trim()
    if (!message || busyRef.current || loading || historyFailed || loggingOut) return
    busyRef.current = true; setBusy(true); setError(''); setDraft('')
    const version = epoch.current
    const controller = new AbortController()
    stream.current = controller
    const userId = crypto.randomUUID(), answerId = crypto.randomUUID()
    let text = '', turnId = '', started = false
    let blocks: MessageBlock[] = []
    setItems(previous => [...previous,
      { id: userId, turn_id: '', role: 'user', content: message, created_at: '' },
      { id: answerId, turn_id: '', role: 'assistant', content: '', created_at: '', streaming: true },
    ])
    try {
      await streamChat(message, session.csrf_token, controller.signal, event => {
        if (version !== epoch.current) return
        if (event.event === 'started') {
          started = true; turnId = event.data.turn_id
          setItems(previous => previous.map(item => item.id === answerId ? { ...item, turn_id: turnId } : item))
        }
        if (event.event === 'tool_status') {
          const update = event.data
          setActivity(previous => {
            const steps = previous[turnId] || []
            const next = steps.some(step => step.id === update.id) ? steps.map(step => step.id === update.id ? update : step) : [...steps, update]
            return { ...previous, [turnId]: next }
          })
        }
        if (event.event === 'error') throw new ApiError(event.data.code === 'unauthenticated' ? 401 : 502, event.data.code, event.data.message)
        if (event.event === 'chart') {
          blocks = [...blocks, event.data.block]
          setItems(previous => previous.map(item => item.id === answerId ? { ...item, blocks, turn_id: turnId } : item))
        }
        if (event.event === 'delta' || event.event === 'completed') {
          blocks = event.event === 'delta' ? appendText(blocks, event.data.text) : event.data.blocks || blocks
          text = event.event === 'delta' ? text + event.data.text : event.data.text
          setItems(previous => previous.map(item => item.id === answerId ? { ...item, content: text, blocks, turn_id: turnId } : item))
        }
      })
      if (version === epoch.current) await loadHistory(version, controller.signal)
    } catch (error) {
      if (version !== epoch.current || controller.signal.aborted) return
      if (error instanceof ApiError && error.status === 401) { onExpired(); return }
      const history = await loadHistory(version, controller.signal)
      if (version !== epoch.current) return
      setError(errorMessage(error))
      if (!started) setDraft(message)
      if (started && (text || blocks.length || turnId)) {
        const partial: DisplayMessage = { id: answerId, turn_id: turnId, role: 'assistant', content: text, blocks, created_at: '', unsaved: true }
        setItems(previous => [...(history || previous.filter(item => item.id !== answerId)), partial])
      }
    } finally {
      if (version === epoch.current) {
        setActivity(previous => ({ ...previous, [turnId]: finishPending(previous[turnId] || []) }))
        setItems(previous => previous.map(item => item.id === answerId ? { ...item, streaming: false } : item))
        busyRef.current = false; setBusy(false); stream.current = null
      }
    }
  }

  async function logout() {
    if (loggingOut) return
    setLoggingOut(true); setError(''); epoch.current++; stream.current?.abort()
    try {
      await api('/auth/logout', { method: 'POST', body: {}, csrf: session.csrf_token })
      onExpired()
    } catch (error) {
      setError(errorMessage(error)); await loadHistory(); busyRef.current = false; setBusy(false); setLoggingOut(false)
    }
  }

  return <div className="flex h-dvh bg-white font-sans text-slate-900 antialiased">
    <aside className="hidden w-60 shrink-0 flex-col border-r border-slate-800 bg-[#161b26] px-4 py-6 text-slate-300 md:flex">
      <a href="/" className="mb-10 flex items-center gap-3 px-2" aria-label="Chatbot de finanzas, inicio"><span className="grid size-9 place-items-center rounded-xl bg-indigo-500 text-white"><Icon name="chat" /></span><div><span className="block text-sm font-semibold text-white">Chatbot</span><span className="text-[11px] text-slate-500">Finanzas</span></div></a>
      <span className="mb-3 px-3 text-[10px] font-medium uppercase tracking-widest text-slate-500">Tu espacio</span>
      <div className="flex items-center gap-2.5 rounded-xl border border-white/5 bg-white/8 px-3 py-3 text-xs font-medium text-white"><Icon name="chat" className="size-4 text-indigo-300" />Mi conversación<span className="ml-auto size-1.5 rounded-full bg-indigo-400" /></div>
      <div className="mt-auto flex items-center gap-3 border-t border-white/8 px-2 pt-5"><span className="grid size-9 shrink-0 place-items-center rounded-full bg-indigo-400/15 text-xs font-semibold text-indigo-200">{session.user.display_name[0]?.toUpperCase()}</span><div className="min-w-0"><strong className="block truncate text-xs font-medium text-slate-200">{session.user.display_name}</strong><span className="block truncate text-[11px] text-slate-500">@{session.user.username}</span></div></div>
    </aside>
    <main className="flex min-w-0 flex-1 flex-col">
      <header className="flex shrink-0 items-center justify-between gap-3 border-b border-slate-100 px-5 py-4 sm:px-8">
        <div className="flex items-center gap-3"><span className="grid size-9 place-items-center rounded-xl bg-indigo-50 text-indigo-600 md:hidden"><Icon name="chat" /></span><div><h1 className="text-sm font-semibold tracking-tight">Chatbot de finanzas</h1><span className="mt-1 flex items-center gap-1.5 text-[10px] text-slate-400"><Icon name="lock" className="size-2.5" />Conversación privada</span></div></div>
        <button className="flex items-center gap-2 rounded-lg px-3 py-2 text-xs text-slate-500 transition hover:bg-slate-100 hover:text-slate-900 disabled:opacity-50" onClick={logout} disabled={loggingOut}><span>{loggingOut ? 'Saliendo…' : 'Cerrar sesión'}</span><Icon name="logout" className="size-4" /></button>
      </header>
      <div className="flex-1 overflow-y-auto px-5 py-6 sm:px-8" aria-label="Conversación" aria-busy={busy || loading}>
        {loading ? <p className="mt-16 text-center text-sm text-slate-400">Cargando conversación…</p> : items.length === 0 && !historyFailed ? <section className="mx-auto flex min-h-[60%] max-w-2xl flex-col items-center justify-center py-10 text-center">
          <span className="mb-6 grid size-14 place-items-center rounded-2xl border border-indigo-100 bg-indigo-50 text-indigo-500"><Icon name="spark" className="size-7" /></span><h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">Hola, {session.user.display_name}.</h2><p className="mt-2 text-sm text-slate-400">¿En qué te ayudo?</p>
          <div className="mt-8 grid w-full gap-2 sm:grid-cols-3">{suggestions.map(suggestion => <button className="group flex items-start justify-between gap-3 rounded-2xl border border-slate-200 bg-white p-4 text-left text-xs leading-relaxed text-slate-500 transition hover:border-indigo-200 hover:bg-indigo-50/40 hover:text-slate-800" key={suggestion.label} onClick={() => setDraft(suggestion.prompt)}>{suggestion.label}<Icon name="chevron" className="mt-0.5 size-3 shrink-0 text-slate-300 group-hover:text-indigo-400" /></button>)}</div>
        </section> : null}
        <div className="mx-auto max-w-3xl space-y-6">{items.map(item => <article key={item.id} className={'flex gap-3 ' + (item.role === 'user' ? 'justify-end' : 'justify-start')}>
          {item.role === 'assistant' && <span className="mt-1 grid size-8 shrink-0 place-items-center rounded-xl border border-indigo-100 bg-indigo-50 text-indigo-500"><Icon name="spark" className="size-4" /></span>}
          <div className={'min-w-0 max-w-[88%] ' + (item.role === 'user' ? 'rounded-2xl rounded-tr-sm bg-slate-100 px-4 py-3' : 'w-full py-1.5')}>
            <span className="mb-2 block text-[10px] font-medium text-slate-400">{item.role === 'assistant' ? 'Asistente' : 'Vos'}</span>
            {item.role === 'assistant' && item.streaming && <span className="mb-1 inline-flex items-center gap-2 text-xs text-slate-400" role="status"><span className="size-1.5 animate-pulse rounded-full bg-indigo-400" />{item.content ? 'Respondiendo…' : 'Pensando…'}</span>}
            {item.role === 'assistant' && <ToolActivity active={!!item.streaming} steps={activity[item.turn_id] || []} expanded={!collapsed[item.turn_id]} onToggle={() => setCollapsed(previous => ({ ...previous, [item.turn_id]: !previous[item.turn_id] }))} />}
            {(item.content || item.blocks?.length) ? item.role === 'assistant' ? <AssistantMessage content={item.content} blocks={item.blocks} /> : <p className="whitespace-pre-wrap text-[13px] leading-7 wrap-anywhere text-slate-700 sm:text-sm">{item.content}</p> : null}
            {item.unsaved && <small className="mt-2 block text-[10px] text-amber-600">Respuesta parcial · no guardada</small>}
          </div>
        </article>)}</div><div ref={tail} />
      </div>
      <div className="mx-auto w-full max-w-3xl shrink-0 px-4 pb-4 pt-2 sm:px-6 sm:pb-5">
        {error && <div className="mb-3 rounded-xl border border-red-100 bg-red-50 px-4 py-3 text-xs leading-relaxed text-red-700" role="alert">{error}{historyFailed && <button className="mt-1 block underline" onClick={() => { setLoading(true); setError(''); void loadHistory() }}>Reintentar historial</button>}</div>}
        {!loading && !historyFailed && items.length > 0 && <div className="mb-3 flex flex-wrap gap-2" aria-label="Sugerencias para continuar">
          {suggestions.slice(0, 2).map(suggestion => <button type="button" key={suggestion.label} disabled={busy || loggingOut} onClick={() => setDraft(suggestion.prompt)} className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-[11px] text-slate-500 shadow-sm transition hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600 focus-visible:outline-2 focus-visible:outline-indigo-400 disabled:cursor-not-allowed disabled:opacity-40"><Icon name="spark" className="size-3 text-indigo-400" />{suggestion.label}</button>)}
        </div>}
        <form className="rounded-2xl border border-slate-200 bg-white px-4 pb-3 pt-4 shadow-lg shadow-slate-200/25 transition focus-within:border-indigo-300 focus-within:ring-3 focus-within:ring-indigo-50" onSubmit={send}>
          <label className="sr-only" htmlFor="message">Tu mensaje</label>
          <textarea className="min-h-12 max-h-40 w-full resize-none border-0 bg-transparent text-sm leading-relaxed text-slate-800 outline-none placeholder:text-slate-400 disabled:cursor-wait" id="message" rows={2} value={draft} maxLength={8000} disabled={busy || loading || historyFailed || loggingOut} placeholder={busy ? 'El asistente está respondiendo…' : 'Escribí tu mensaje…'} onChange={event => setDraft(event.target.value)}
            onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form?.requestSubmit() } }} />
          <div className="mt-2 flex items-center justify-between gap-3"><span className="text-[10px] text-slate-400">{busy ? 'Respondiendo…' : 'Enter para enviar · Shift + Enter para nueva línea'}</span><button className="grid size-8 place-items-center rounded-xl bg-indigo-600 text-white transition hover:bg-indigo-500 disabled:bg-slate-100 disabled:text-slate-300" aria-label="Enviar mensaje" disabled={busy || loading || historyFailed || loggingOut || !draft.trim()}>{busy ? <span className="size-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" /> : <Icon name="arrow" className="size-4" />}</button></div>
        </form>
        <p className="mt-3 text-center text-[10px] text-slate-400">Puede cometer errores. Verificá la información.</p>
      </div>
    </main>
  </div>
}
