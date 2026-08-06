const TOKEN_KEY = 'math_coach_token';

export class ApiError extends Error {
  status: number;

  constructor(message: string, status = 500) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

type UnauthorizedHandler = () => void;

let onUnauthorized: UnauthorizedHandler | null = null;

export function setUnauthorizedHandler(handler: UnauthorizedHandler | null) {
  onUnauthorized = handler;
}

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || '';
}

export function setToken(token: string | null | undefined) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export async function apiRequest<T = unknown>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers || {});
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(path, { ...options, headers });

  if (response.status === 401) {
    setToken(null);
    onUnauthorized?.();
  }

  if (!response.ok) {
    let detail = response.statusText || '请求失败';
    try {
      const payload = await response.json();
      detail = payload.detail || payload.error || detail;
      if (Array.isArray(detail)) {
        detail = detail.map((item: { msg?: string } | string) =>
          typeof item === 'string' ? item : item.msg || JSON.stringify(item),
        ).join('; ');
      }
    } catch {
      // ignore parse errors
    }
    throw new ApiError(String(detail || '请求失败'), response.status);
  }

  if (response.status === 204) return null as T;
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) return response.json() as Promise<T>;
  return response as unknown as T;
}

export async function consumeSse(
  response: Response,
  onEvent: (event: Record<string, unknown>) => void,
): Promise<void> {
  if (!response.body) throw new ApiError('浏览器不支持流式响应', 500);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split('\n\n');
    buffer = chunks.pop() || '';
    for (const chunk of chunks) {
      const line = chunk.split('\n').find((item) => item.startsWith('data: '));
      if (!line) continue;
      onEvent(JSON.parse(line.slice(6)));
    }
  }
}
