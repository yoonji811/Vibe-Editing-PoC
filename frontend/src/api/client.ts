const BASE = import.meta.env.VITE_API_URL ?? ''

export interface SessionCreateResponse {
  session_id: string
  created_at: string
  original_image_b64: string
  width: number
  height: number
  filename: string
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  timestamp: string
}

export interface SessionInfoResponse {
  session_id: string
  created_at: string
  current_image_b64: string | null
  edit_count: number
  chat_history: ChatMessage[]
}

export interface EditResponse {
  session_id: string
  result_image_b64: string | null
  chat_message: string
  intent: string
  engine: string | null
  operation: string | null
  params: Record<string, unknown> | null
  latency_ms: number
}

export async function createSession(file: File, userNickname: string): Promise<SessionCreateResponse> {
  const form = new FormData()
  form.append('file', file)
  form.append('user_nickname', userNickname)
  const res = await fetch(`${BASE}/api/session/new`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getSession(sessionId: string): Promise<SessionInfoResponse> {
  const res = await fetch(`${BASE}/api/session/${sessionId}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function editImage(sessionId: string, userText: string): Promise<EditResponse> {
  const res = await fetch(`${BASE}/api/edit/${sessionId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_text: userText }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function generateSession(prompt: string, userNickname: string): Promise<SessionCreateResponse> {
  const form = new FormData()
  form.append('prompt', prompt)
  form.append('user_nickname', userNickname)
  const res = await fetch(`${BASE}/api/session/generate`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function recordSave(sessionId: string): Promise<void> {
  await fetch(`${BASE}/api/trajectory/${sessionId}/save`, { method: 'POST' })
}
