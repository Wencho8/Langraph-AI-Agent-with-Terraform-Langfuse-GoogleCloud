import { useRef, useState, type FormEvent } from 'react'
import { api, errorMessage, type Session } from '../api/client'
import Icon from '../Icon'
import { saveToken } from '../api/transport'

export default function AuthForm({ onLogin }: { onLogin: (session: Session) => void }) {
  const [register, setRegister] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const submitting = useRef(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting.current) return
    const form = new FormData(event.currentTarget)
    const password = String(form.get('password'))
    if (register && password !== form.get('confirmation')) { setError('Las contraseñas no coinciden.'); return }
    submitting.current = true; setBusy(true); setError('')
    try {
      const session = await api<(Session & { access_token: string }) | { status: 'pending_approval'; message: string }>(register ? '/auth/register' : '/auth/login', {
        method: 'POST', body: { username: form.get('username'), password,
          ...(register ? { display_name: form.get('name'), password_confirmation: form.get('confirmation') } : {}) },
      })
      if ('status' in session) { setRegister(false); setError(session.message); return }
      saveToken(session.access_token)
      onLogin({ user: session.user, expires_at: session.expires_at })
    } catch (error) { setError(errorMessage(error)) }
    finally { submitting.current = false; setBusy(false) }
  }

  const input = 'mt-2 w-full rounded-xl border border-slate-200 bg-slate-50/60 px-3.5 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-indigo-400 focus:bg-white focus:ring-3 focus:ring-indigo-100 disabled:opacity-60'
  const label = 'block text-xs font-medium text-slate-600'
  return <main className="flex min-h-dvh flex-col items-center justify-center bg-slate-50 px-5 py-10 font-sans text-slate-900">
    <a href="/" className="mb-8 flex items-center gap-3" aria-label="Chatbot de finanzas, inicio"><span className="grid size-11 place-items-center rounded-2xl bg-slate-900 text-white shadow-lg shadow-slate-900/10"><Icon name="chat" className="size-6" /></span><span className="text-lg font-semibold tracking-tight">Chatbot de finanzas</span></a>
    <section className="w-full max-w-[400px] rounded-3xl border border-slate-200/80 bg-white p-7 shadow-xl shadow-slate-200/35 sm:p-8">
      <div className="mb-7 grid grid-cols-2 rounded-xl bg-slate-100 p-1 text-xs font-medium" aria-label="Acceso">
        <button type="button" disabled={busy} aria-pressed={!register} onClick={() => { setRegister(false); setError('') }} className={'rounded-lg px-3 py-2.5 transition ' + (!register ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-800')}>Iniciá sesión</button>
        <button type="button" disabled={busy} aria-pressed={register} onClick={() => { setRegister(true); setError('') }} className={'rounded-lg px-3 py-2.5 transition ' + (register ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-800')}>Creá una cuenta</button>
      </div>
      <h1 className="mb-1.5 text-xl font-semibold tracking-tight">{register ? 'Crear cuenta' : 'Bienvenido'}</h1>
      <p className="mb-6 text-sm text-slate-500">{register ? 'Completá tus datos para empezar.' : 'Ingresá tus datos para continuar.'}</p>
      <form onSubmit={submit} className="space-y-4">
        {register && <label className={label}>Nombre<input className={input} name="name" autoComplete="given-name" required maxLength={120} placeholder="Tu nombre" disabled={busy} /></label>}
        <label className={label}>Username<input className={input} name="username" autoComplete="username" required minLength={3} maxLength={32} pattern="[A-Za-z0-9_.\-]{3,32}" placeholder="Tu usuario" disabled={busy} /></label>
        <label className={label}>Contraseña<input className={input} name="password" type="password" autoComplete={register ? 'new-password' : 'current-password'} required minLength={register ? 15 : 1} maxLength={128} placeholder={register ? 'Mínimo 15 caracteres' : 'Tu contraseña'} disabled={busy} /></label>
        {register && <label className={label}>Repetí la contraseña<input className={input} name="confirmation" type="password" autoComplete="new-password" required minLength={15} maxLength={128} placeholder="Repetí tu contraseña" disabled={busy} /></label>}
        {error && <p className="rounded-xl bg-red-50 px-3 py-2.5 text-xs leading-relaxed text-red-700" role="alert">{error}</p>}
        <button className="mt-2 flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 px-4 py-3 text-sm font-medium text-white shadow-sm transition hover:bg-indigo-500 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-500 disabled:opacity-50" type="submit" disabled={busy}>{busy ? 'Un momento…' : register ? 'Crear mi cuenta' : 'Iniciar sesión'}<Icon name="chevron" className="size-4" /></button>
      </form>
    </section>
    <p className="mt-6 flex items-center gap-1.5 text-[11px] text-slate-400"><Icon name="lock" className="size-3" />Tu conversación es privada.</p>
  </main>
}
