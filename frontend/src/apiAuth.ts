/** When KALSHI_API_BEARER_TOKEN is set server-side, set VITE_API_BEARER_TOKEN in frontend/.env to match. */
const TOKEN = (import.meta.env.VITE_API_BEARER_TOKEN as string | undefined)?.trim() ?? "";

export function apiAuthHeaders(): HeadersInit {
  if (!TOKEN) return {};
  return { Authorization: `Bearer ${TOKEN}` };
}

/** Merge bearer into init.headers for fetch(). */
export function withApiAuth(init: RequestInit = {}): RequestInit {
  const h = new Headers(init.headers);
  const auth = apiAuthHeaders() as Record<string, string>;
  for (const k of Object.keys(auth)) h.set(k, (auth as Record<string, string>)[k]!);
  return { ...init, headers: h };
}
