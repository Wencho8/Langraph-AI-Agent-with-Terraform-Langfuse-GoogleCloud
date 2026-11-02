// All API requests share the same destination and session transport.
export function apiBaseUrl(): string {
  return (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '')
}

function tokenKey() { return 'chatbot-session:' + apiBaseUrl() }
export function getToken(): string | null { return sessionStorage.getItem(tokenKey()) }
export function saveToken(token: string) { sessionStorage.setItem(tokenKey(), token) }
export function clearToken() { sessionStorage.removeItem(tokenKey()) }

export async function fetchApi(path: string, options: RequestInit = {}): Promise<Response> {
  const token = getToken()
  const headers = new Headers(options.headers)
  if (token) headers.set('Authorization', 'Bearer ' + token)
  const response = await fetch(apiBaseUrl() + '/v1' + path, { ...options, headers, credentials: 'omit' })
  if (response.status === 401 && getToken() === token) clearToken()
  return response
}
