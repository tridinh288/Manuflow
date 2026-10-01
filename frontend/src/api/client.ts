import axios from 'axios'

export const API_URL: string = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api/v1'

const TOKEN_KEY = 'manuflow.token'

/** The access token lives for the browser tab only (sessionStorage), never in a cookie. */
export const tokenStore = {
  get(): string | null {
    try {
      return sessionStorage.getItem(TOKEN_KEY)
    } catch {
      return null
    }
  },
  set(token: string): void {
    try {
      sessionStorage.setItem(TOKEN_KEY, token)
    } catch {
      /* private mode: the session simply ends with the page */
    }
  },
  clear(): void {
    try {
      sessionStorage.removeItem(TOKEN_KEY)
    } catch {
      /* nothing stored */
    }
  },
}

export const api = axios.create({ baseURL: API_URL, timeout: 15_000 })

api.interceptors.request.use((config) => {
  const token = tokenStore.get()
  if (token) config.headers.set('Authorization', `Bearer ${token}`)
  return config
})

let onUnauthorized: () => void = () => {}

/** Called when the API answers 401 (expired token, deactivated user, BR-AUTH-04). */
export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler
}

api.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (axios.isAxiosError(error) && error.response?.status === 401) {
      const url = error.config?.url ?? ''
      if (!url.includes('/auth/login')) onUnauthorized()
    }
    return Promise.reject(error)
  },
)

/** Request options carrying the submission's Idempotency-Key (B17, D-22). */
export function idem(key: string) {
  return { headers: { 'Idempotency-Key': key } }
}
