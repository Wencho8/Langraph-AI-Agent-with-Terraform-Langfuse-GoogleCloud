import { useEffect, useState } from 'react'
import { api, ApiError, errorMessage, type Session } from '../api/client'

type Account = { id: string; display_name: string; username: string; blocked: boolean; is_admin: boolean }

export default function AdminUsers({ session, onExpired }: { session: Session; onExpired: () => void }) {
  const [users, setUsers] = useState<Account[]>([])
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setError(''); setUsers([])
    api<Account[]>('/auth/admin/users?offset=' + offset, { signal: controller.signal })
      .then(setUsers).catch(error => {
        if (controller.signal.aborted) return
        if (error instanceof ApiError && error.status === 401) onExpired()
        else setError(errorMessage(error))
      }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [offset, revision, onExpired])
  async function change(user: Account) {
    if (busy) return
    setBusy(true); setError('')
    try {
      await api('/auth/admin/users/' + user.id + '/access', { method: 'POST',
        body: { blocked: !user.blocked } })
      setRevision(value => value + 1)
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) onExpired()
      else setError(errorMessage(error))
    } finally { setBusy(false) }
  }
  return <main className="min-h-dvh bg-slate-50 p-6 pb-24 text-slate-900 sm:p-12">
    <section className="mx-auto max-w-4xl rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h1 className="text-xl font-semibold">Administrar usuarios</h1>
      <p className="mt-2 text-sm text-slate-500">Aprobá cuentas para permitir el acceso al chatbot.</p>
      {error && <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
      <button className="my-4 text-sm text-indigo-600 disabled:opacity-50" disabled={loading || busy} onClick={() => setRevision(value => value + 1)}>Actualizar</button>
      {loading ? <p>Cargando usuarios…</p> : <div className="overflow-x-auto"><table className="w-full text-left text-sm">
        <thead><tr className="border-b text-slate-500"><th className="p-3">Nombre / username</th><th>Estado</th><th>Acción</th></tr></thead>
        <tbody>{users.map(user => <tr key={user.id} className="border-b border-slate-100">
          <td className="p-3"><div className="font-medium">{user.display_name}</div><div className="text-slate-500">{user.username}{user.is_admin ? ' · Admin' : ''}</div></td>
          <td className={user.blocked ? 'text-amber-700' : 'text-emerald-700'}>{user.blocked ? 'Bloqueado / pendiente' : 'Aprobado'}</td>
          <td><button disabled={busy || user.id === session.user.id} onClick={() => change(user)} className="rounded-lg border border-slate-200 px-3 py-2 disabled:opacity-40">{user.blocked ? 'Aprobar' : 'Bloquear'}</button></td>
        </tr>)}</tbody></table>{!users.length && <p className="py-4 text-slate-500">No hay usuarios en esta página.</p>}</div>}
      <div className="mt-4 flex gap-4 text-sm text-indigo-600"><button disabled={offset === 0 || loading || busy} onClick={() => setOffset(value => Math.max(0, value - 100))}>Anterior</button><button disabled={users.length < 100 || loading || busy} onClick={() => setOffset(value => value + 100)}>Siguiente</button></div>
    </section>
  </main>
}
