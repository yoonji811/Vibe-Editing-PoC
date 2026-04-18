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

export interface SessionSummary {
  session_id: string
  created_at: string
  updated_at: string
  summary: string
  edit_count: number
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

export async function editImage(
  sessionId: string,
  userText: string,
  inputImageB64?: string,
): Promise<EditResponse> {
  const res = await fetch(`${BASE}/api/edit/${sessionId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      user_text: userText,
      ...(inputImageB64 ? { input_image_b64: inputImageB64 } : {}),
    }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export interface ResumeEditResponse {
  session_id: string
  original_image_b64: string
  created_at: string
  width: number
  height: number
  filename: string
  result_image_b64: string | null
  chat_message: string
  intent: string
  engine: string | null
  operation: string | null
  params: Record<string, unknown> | null
  latency_ms: number
}

export async function resumeAndEdit(
  sessionId: string,
  imageUrl: string,
  userNickname: string,
  stepIdx: number,
  userText: string,
): Promise<ResumeEditResponse> {
  const form = new FormData()
  form.append('image_url', imageUrl)
  form.append('user_nickname', userNickname)
  form.append('step_idx', String(stepIdx))
  form.append('user_text', userText)
  const res = await fetch(`${BASE}/api/session/resume-edit/${sessionId}`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function restoreSession(
  sessionId: string,
  imageUrl: string,
  userNickname: string,
  stepIdx: number,
): Promise<SessionCreateResponse> {
  const form = new FormData()
  form.append('image_url', imageUrl)
  form.append('user_nickname', userNickname)
  form.append('step_idx', String(stepIdx))
  const res = await fetch(`${BASE}/api/session/restore/${sessionId}`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function resumeSession(imageUrl: string, userNickname: string): Promise<SessionCreateResponse> {
  const form = new FormData()
  form.append('image_url', imageUrl)
  form.append('user_nickname', userNickname)
  const res = await fetch(`${BASE}/api/session/resume`, { method: 'POST', body: form })
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

export async function endSession(sessionId: string): Promise<void> {
  await fetch(`${BASE}/api/trajectory/${sessionId}/end`, { method: 'POST' })
}

export async function getSessionsByNickname(nickname: string): Promise<SessionSummary[]> {
  try {
    const res = await fetch(`${BASE}/api/trajectory/by-nickname/${encodeURIComponent(nickname)}`)
    if (!res.ok) return []
    return res.json()
  } catch {
    return []
  }
}

export async function getTrajectory(sessionId: string): Promise<any> {
  try {
    const res = await fetch(`${BASE}/api/trajectory/${sessionId}`)
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
}
