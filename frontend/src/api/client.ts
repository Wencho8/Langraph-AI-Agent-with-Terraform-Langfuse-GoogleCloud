export type PriceSeries = { instrument_id: string; symbol: string; market: string; currency: string | null; source: string; start: string; end: string; adjustment: string; settlement: string; as_of: string | null; points: { date: string; close: number }[] }
export type ChartBlock = { type: 'chart'; id: string; title: string; comparison: 'absolute' | 'base_100'; series: PriceSeries[]; note: string }
export type MessageBlock = { type: 'text'; text: string } | ChartBlock

export function appendText(blocks: MessageBlock[], text: string): MessageBlock[] {
  const last = blocks.at(-1)
  return last?.type === 'text' ? [...blocks.slice(0, -1), { type: 'text', text: last.text + text }] : [...blocks, { type: 'text', text }]
}

export type User = { id: string; display_name: string; username: string; is_admin?: boolean }
export type Session = { user: User; csrf_token: string; expires_at: string }
export type Message = { id: string; turn_id: string; role: 'user' | 'assistant'; content: string; created_at: string; blocks?: MessageBlock[] }

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) { super(message) }
}

const messages: Record<string, string> = {
  account_blocked: 'Un administrador debe aprobar tu cuenta antes de que puedas ingresar.',
  invalid_credentials: 'El usuario o la contraseña no son correctos.',
  username_taken: 'Ese username ya está en uso. Probá con otro.',
  validation_error: 'Revisá los campos. La contraseña debe tener entre 15 y 128 caracteres y ambas deben coincidir.',
  unauthenticated: 'Tu sesión terminó. Volvé a iniciar sesión.',
  forbidden: 'No pudimos validar la solicitud. Recargá la página e intentá de nuevo.',
  session_busy: 'Tu conversación está respondiendo en otra ventana. Esperá e intentá de nuevo.',
  rate_limited: 'Enviaste demasiados mensajes. Esperá un momento.',
  auth_rate_limited: 'Demasiados intentos. Esperá un minuto antes de volver a intentar.',
  runtime_saturated: 'El asistente está ocupado. Intentá de nuevo en un momento.',
  dependency_unavailable: 'El servicio no está disponible por ahora. Intentá de nuevo.',
  auth_busy: 'El servicio de acceso está ocupado. Intentá de nuevo en un momento.',
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return messages[error.code] || error.message
  return 'No pudimos conectar con el servidor. Revisá tu conexión e intentá de nuevo.'
}

export async function responseError(response: Response): Promise<ApiError> {
  const body = await response.json().catch(() => ({}))
  return new ApiError(response.status, body.code || 'request_failed', body.message || 'No se pudo completar la solicitud.')
}

export async function api<T>(path: string, options: { method?: string; body?: unknown; csrf?: string; signal?: AbortSignal } = {}): Promise<T> {
  const response = await fetch('/v1' + path, {
    method: options.method || 'GET', credentials: 'same-origin', signal: options.signal,
    headers: { ...(options.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(options.csrf ? { 'X-CSRF-Token': options.csrf } : {}) },
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  })
  if (!response.ok) throw await responseError(response)
  return response.status === 204 ? undefined as T : await response.json() as T
}
