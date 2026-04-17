import { useState, useCallback } from 'react'
import * as api from '../api/client'

export interface HistoryEntry {
  imageB64: string
  label: string
  timestamp: string
}

export interface SessionHook {
  sessionId: string | null
  nickname: string | null
  currentImageB64: string | null
  history: HistoryEntry[]
  chatHistory: api.ChatMessage[]
  isLoading: boolean
  error: string | null
  uploadImage: (file: File, nickname: string) => Promise<void>
  generateFromText: (prompt: string, nickname: string) => Promise<void>
  sendMessage: (text: string) => Promise<void>
  saveImage: () => Promise<void>
  resetSession: () => void
}

export function useSession(): SessionHook {
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [nickname, setNickname] = useState<string | null>(null)
  const [currentImageB64, setCurrentImageB64] = useState<string | null>(null)
  const [history, setHistory] = useState<HistoryEntry[]>([])
  const [chatHistory, setChatHistory] = useState<api.ChatMessage[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const uploadImage = useCallback(async (file: File, userNickname: string) => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await api.createSession(file, userNickname)
      setSessionId(res.session_id)
      setNickname(userNickname)
      setCurrentImageB64(res.original_image_b64)
      setHistory([{ imageB64: res.original_image_b64, label: 'Original Image', timestamp: new Date().toISOString() }])
      setChatHistory([])
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setIsLoading(false)
    }
  }, [])

  const generateFromText = useCallback(async (prompt: string, userNickname: string) => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await api.generateSession(prompt, userNickname)
      setSessionId(res.session_id)
      setNickname(userNickname)
      setCurrentImageB64(res.original_image_b64)
      setHistory([{ imageB64: res.original_image_b64, label: 'Generated Image', timestamp: new Date().toISOString() }])
      setChatHistory([])
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setIsLoading(false)
    }
  }, [])

  const sendMessage = useCallback(
    async (text: string) => {
      if (!sessionId) return
      setIsLoading(true)
      setError(null)
      // Optimistic: add user message immediately
      const userMsg: api.ChatMessage = {
        role: 'user',
        content: text,
        timestamp: new Date().toISOString(),
      }
      setChatHistory((prev) => [...prev, userMsg])
      try {
        const res = await api.editImage(sessionId, text)
        // Assistant reply
        const assistantMsg: api.ChatMessage = {
          role: 'assistant',
          content: res.chat_message,
          timestamp: new Date().toISOString(),
        }
        setChatHistory((prev) => [...prev, assistantMsg])
        if (res.result_image_b64) {
          setCurrentImageB64(res.result_image_b64)
          const label = res.operation ?? res.intent ?? '편집'
          setHistory((prev) => [
            ...prev,
            { imageB64: res.result_image_b64!, label, timestamp: new Date().toISOString() },
          ])
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
        setChatHistory((prev) => prev.slice(0, -1)) // remove optimistic
      } finally {
        setIsLoading(false)
      }
    },
    [sessionId]
  )

  const saveImage = useCallback(async () => {
    if (!sessionId || !currentImageB64) return
    // Trigger download
    const a = document.createElement('a')
    a.href = `data:image/jpeg;base64,${currentImageB64}`
    a.download = `edited_${sessionId.slice(0, 8)}.jpg`
    a.click()
    await api.recordSave(sessionId)
  }, [sessionId, currentImageB64])

  const resetSession = useCallback(() => {
    setSessionId(null)
    setNickname(null)
    setCurrentImageB64(null)
    setHistory([])
    setChatHistory([])
    setError(null)
  }, [])

  return {
    sessionId,
    nickname,
    currentImageB64,
    history,
    chatHistory,
    isLoading,
    error,
    uploadImage,
    generateFromText,
    sendMessage,
    saveImage,
    resetSession,
  }
}
