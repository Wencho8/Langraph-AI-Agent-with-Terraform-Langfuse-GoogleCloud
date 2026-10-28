import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, errorMessage, type Session } from './api/client'
import AuthForm from './auth/AuthForm'
import Chat from './chat/Chat'
import AdminUsers from './admin/AdminUsers'

export default function App() {
  const [session, setSession] = useState<Session | null>(null)
  const [adminView, setAdminView] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const epoch = useRef(0)
  const expire = useCallback(() => { epoch.current++; setSession(null); setAdminView(false); setError('') }, [])

  useEffect(() => {
    const controller = new AbortController()
    const version = ++epoch.current
    setLoading(true); setError('')
    api<Session>('/auth/session', { signal: controller.signal }).then(session => {
      if (version === epoch.current) setSession(session)
    }).catch(error => {
      if (controller.signal.aborted || version !== epoch.current) return
      if (error instanceof ApiError && error.status === 401) setSession(null)
      else setError(errorMessage(error))
    }).finally(() => { if (!controller.signal.aborted && version === epoch.current) setLoading(false) })
    return () => controller.abort()
  }, [retry])

  useEffect(() => {
    if (!session) return
    const delay = Math.max(0, Date.parse(session.expires_at) - Date.now())
    const timer = setTimeout(expire, Math.min(delay, 2_147_483_647))
    return () => clearTimeout(timer)
  }, [session, expire])

  if (loading || error) return <main className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-slate-50 p-6 text-center text-slate-700"><h1 className="text-xl font-semibold">{loading ? 'Cargando…' : 'No pudimos conectar.'}</h1>
    {error && <><p role="alert" className="text-sm text-slate-500">{error}</p><button className="rounded-xl bg-indigo-600 px-5 py-3 text-sm text-white" onClick={() => setRetry(value => value + 1)}>Volver a intentar</button></>}</main>
  return session ? <>
    {session.user.is_admin && <button className="fixed bottom-4 left-4 z-50 rounded-xl bg-indigo-600 px-4 py-2 text-sm text-white shadow" onClick={() => setAdminView(value => !value)}>{adminView ? 'Volver al chat' : 'Administrar usuarios'}</button>}
    {adminView && session.user.is_admin ? <AdminUsers session={session} onExpired={expire} /> : <Chat key={session.user.id} session={session} onExpired={expire} />}
    </> : <AuthForm onLogin={session => { epoch.current++; setSession(session) }} />
}
