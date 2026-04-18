import { useState, useCallback, useRef, useEffect } from 'react'
import { useSession } from './hooks/useSession'
import ImageViewer from './components/ImageViewer'
import ChatPanel from './components/ChatPanel'
import HistoryBar, { type EditStep } from './components/HistoryBar'
import * as api from './api/client'

interface PastView {
  sessionId: string
  steps: EditStep[]
  idx: number
}

export default function App() {
  const session = useSession()
  const [historyIndex, setHistoryIndex] = useState(0)
  const [nicknameInput, setNicknameInput] = useState('')
  const [nickname, setNickname] = useState<string | null>(null)
  const [isEditingNickname, setIsEditingNickname] = useState(false)
  const [nicknameEditInput, setNicknameEditInput] = useState('')
  const [sessions, setSessions] = useState<api.SessionSummary[]>([])
  const [showScrollHint, setShowScrollHint] = useState(false)
  const [isHoldingOriginal, setIsHoldingOriginal] = useState(false)
  const [pastView, setPastView] = useState<PastView | null>(null)
  const [preInput, setPreInput] = useState('')

  const fileInputRef = useRef<HTMLInputElement>(null)
  const mainRef = useRef<HTMLElement>(null)
  const historyLengthRef = useRef(0)
  const prevHistoryLenRef = useRef(0)
  const pastViewRef = useRef<PastView | null>(null)

  // Keep refs in sync
  useEffect(() => { historyLengthRef.current = session.history.length }, [session.history.length])
  useEffect(() => { pastViewRef.current = pastView }, [pastView])

  // Fetch sessions by nickname
  const fetchSessions = useCallback(async (nick: string) => {
    const data = await api.getSessionsByNickname(nick)
    setSessions(data)
  }, [])

  useEffect(() => {
    if (nickname) fetchSessions(nickname)
  }, [nickname, fetchSessions])

  // Re-fetch after session ends
  useEffect(() => {
    if (!session.sessionId && nickname) fetchSessions(nickname)
  }, [session.sessionId, nickname, fetchSessions])

  // When new edit result arrives: show scroll hint, clear pastView, jump to latest
  useEffect(() => {
    const len = session.history.length
    if (len > prevHistoryLenRef.current) {
      if (len > 1) {
        setShowScrollHint(true)
        const t = setTimeout(() => setShowScrollHint(false), 2500)
        prevHistoryLenRef.current = len
        setPastView(null)
        setHistoryIndex(len - 1)
        return () => clearTimeout(t)
      }
      prevHistoryLenRef.current = len
    }
  }, [session.history.length])

  // Wheel event: navigate history or past view.
  // Attached to window (not mainRef) because mainRef doesn't exist at mount time
  // (user starts on the login screen). At event time mainRef is already set,
  // so we use it to scope the handler to the image area only.
  useEffect(() => {
    const handleWheel = (e: WheelEvent) => {
      const mainEl = mainRef.current
      if (!mainEl || !mainEl.contains(e.target as Node)) return

      const pv = pastViewRef.current
      if (pv) {
        if (pv.steps.length <= 1) return
        e.preventDefault()
        setPastView(prev => {
          if (!prev) return prev
          const newIdx = e.deltaY < 0
            ? Math.max(0, prev.idx - 1)
            : Math.min(prev.steps.length - 1, prev.idx + 1)
          return newIdx === prev.idx ? prev : { ...prev, idx: newIdx }
        })
      } else if (historyLengthRef.current > 1) {
        e.preventDefault()
        setHistoryIndex(prev => {
          if (e.deltaY < 0) return Math.max(0, prev - 1)
          return Math.min(historyLengthRef.current - 1, prev + 1)
        })
      }
    }

    window.addEventListener('wheel', handleWheel, { passive: false })
    return () => window.removeEventListener('wheel', handleWheel)
  }, []) // attach once to window; state and refs accessed at event time

  // Compute image source (data URI or Cloudinary URL)
  const displayImageSrc = (() => {
    const toB64Src = (b64: string | null | undefined) =>
      b64 ? `data:image/jpeg;base64,${b64}` : null
    const entryToSrc = (entry: { imageB64?: string; imageUrl?: string } | null | undefined) => {
      if (!entry) return null
      return entry.imageUrl ?? toB64Src(entry.imageB64)
    }

    if (isHoldingOriginal) {
      if (pastView?.steps[0]?.imageUrl) return pastView.steps[0].imageUrl
      return entryToSrc(session.history[0])
    }
    if (pastView) {
      return pastView.steps[pastView.idx]?.imageUrl || null
    }
    if (session.sessionId) {
      if (historyIndex < session.history.length) {
        return entryToSrc(session.history[historyIndex])
      }
      return toB64Src(session.currentImageB64)
    }
    return null
  })()

  const handleHistorySelect = (index: number) => {
    setPastView(null)
    setHistoryIndex(index)
  }

  const handlePastStepSelect = (sessionId: string, steps: EditStep[], idx: number) => {
    setPastView({ sessionId, steps, idx })
  }

  const handleSend = async (text: string) => {
    if (pastView) {
      // Resume from the selected past step image, then apply the edit
      const imageUrl = pastView.steps[pastView.idx]?.imageUrl
        ?? pastView.steps[0]?.imageUrl
      if (imageUrl && nickname) {
        const { sessionId: origId, steps, idx } = pastView
        setPastView(null)
        await session.resumeAndSend(origId, imageUrl, text, nickname, steps, idx)
        // Explicitly refresh session list so the restored session appears
        await fetchSessions(nickname)
      }
      return
    }

    // If the user is viewing an older step, pass that image as the edit source
    const latestIdx = session.history.length - 1
    const inputB64 = historyIndex < latestIdx
      ? session.history[historyIndex]?.imageB64
      : undefined

    await session.sendMessage(text, inputB64)
    // historyIndex updated by the useEffect watching session.history.length
  }

  const handleNicknameSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = nicknameInput.trim()
    if (trimmed) setNickname(trimmed)
  }

  // Title click → reset session, keep nickname
  const handleTitleClick = async () => {
    if (!session.sessionId && !pastView) return
    // Force-save trajectory before clearing state so the session appears in the list
    if (session.sessionId) {
      try { await api.endSession(session.sessionId) } catch { /* non-fatal */ }
    }
    session.resetSession()
    setPastView(null)
    setPreInput('')
    setHistoryIndex(0)
    setIsHoldingOriginal(false)
    if (nickname) await fetchSessions(nickname)
  }

  // Nickname inline edit
  const handleNicknameClick = () => {
    setNicknameEditInput(nickname ?? '')
    setIsEditingNickname(true)
  }

  const commitNicknameEdit = () => {
    const trimmed = nicknameEditInput.trim()
    if (trimmed && trimmed !== nickname) {
      session.resetSession()
      setPastView(null)
      setNickname(trimmed)
      setPreInput('')
      setHistoryIndex(0)
      setSessions([])
    }
    setIsEditingNickname(false)
  }

  const handleNewImage = async () => {
    // Force-save trajectory before clearing state so the session appears in the list
    if (session.sessionId) {
      try { await api.endSession(session.sessionId) } catch { /* non-fatal */ }
    }
    session.resetSession()
    setPastView(null)
    setPreInput('')
    setHistoryIndex(0)
    setIsHoldingOriginal(false)
    if (nickname) await fetchSessions(nickname)
  }

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file || !nickname) return
    e.target.value = ''
    await session.uploadImage(file, nickname)
    setHistoryIndex(0)
  }

  const handlePreSubmit = async () => {
    if (!nickname || session.isLoading || !preInput.trim()) return
    if (pastView) {
      // Resume from selected past step, using the input text as the first edit
      const imageUrl = pastView.steps[pastView.idx]?.imageUrl
        ?? pastView.steps[0]?.imageUrl
      if (imageUrl) {
        const { sessionId: origId, steps, idx } = pastView
        setPastView(null)
        await session.resumeAndSend(origId, imageUrl, preInput.trim(), nickname, steps, idx)
        await fetchSessions(nickname)
        setPreInput('')
        setHistoryIndex(0)
        return
      }
    }
    await session.generateFromText(preInput.trim(), nickname)
    setPreInput('')
    setHistoryIndex(0)
  }

  const handlePreKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handlePreSubmit()
    }
  }

  const showImage = !!(session.sessionId || pastView) && !!displayImageSrc

  // ── Nickname input screen ──────────────────────────────────────────────────
  if (!nickname) {
    return (
      <div className="h-screen overflow-hidden bg-gray-50 flex items-center justify-center">
        <form
          onSubmit={handleNicknameSubmit}
          className="bg-white rounded-2xl shadow-sm border border-gray-200 p-10 flex flex-col items-center gap-6 w-full max-w-sm"
        >
          <img src="/vibe_logo.png" alt="Vibe Editor" className="w-24 h-24 object-contain" />
          <div className="text-center">
            <h1 className="text-xl font-bold text-gray-900">Vibe Editor</h1>
            <p className="text-sm text-gray-500 mt-1">닉네임을 입력하고 시작하세요</p>
          </div>
          <input
            type="text"
            value={nicknameInput}
            onChange={(e) => setNicknameInput(e.target.value)}
            placeholder="닉네임 입력"
            maxLength={30}
            autoFocus
            className="w-full border border-gray-300 rounded-xl px-4 py-3 text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-300 text-center"
          />
          <button
            type="submit"
            disabled={!nicknameInput.trim()}
            className="w-full bg-blue-500 hover:bg-blue-600 disabled:bg-gray-200 disabled:text-gray-400 text-white font-semibold rounded-xl py-3 text-sm transition-colors"
          >
            시작하기
          </button>
          <p className="text-[11px] text-gray-400 text-center">
            Your edits and images are stored on the server.
          </p>
        </form>
      </div>
    )
  }

  // ── Main UI ───────────────────────────────────────────────────────────────
  return (
    <div className="h-screen overflow-hidden bg-gray-50 flex flex-col font-sans">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 flex items-center px-6 py-3 shrink-0">
        <button
          onClick={handleTitleClick}
          disabled={session.isLoading}
          className="flex items-center gap-2 hover:opacity-80 transition-opacity disabled:opacity-50"
          title="처음으로"
        >
          <img src="/vibe_logo.png" alt="" className="h-8 w-auto object-contain" />
          <span className="text-lg font-bold text-gray-900 tracking-tight">Vibe Editor</span>
        </button>

        <div className="flex-1 flex justify-center">
          {isEditingNickname ? (
            <form onSubmit={(e) => { e.preventDefault(); commitNicknameEdit() }}>
              <input
                value={nicknameEditInput}
                onChange={e => setNicknameEditInput(e.target.value)}
                onBlur={commitNicknameEdit}
                autoFocus
                maxLength={30}
                className="text-xs font-semibold tracking-widest text-blue-600 uppercase border-b border-blue-400 bg-transparent outline-none text-center w-32"
              />
            </form>
          ) : (
            <button
              onClick={handleNicknameClick}
              className="text-xs font-semibold tracking-widest text-blue-600 uppercase hover:underline underline-offset-2"
              title="클릭하여 닉네임 변경"
            >
              {nickname}
            </button>
          )}
        </div>

        {session.sessionId && (
          <button
            onClick={session.saveImage}
            className="text-xs text-gray-500 hover:text-gray-800 border border-gray-200 rounded-full px-3 py-1 transition-colors"
          >
            Save
          </button>
        )}
      </header>

      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* Left sidebar */}
        <aside className="hidden md:flex w-52 shrink-0 flex-col border-r border-gray-200 bg-gray-50 overflow-y-auto">
          <HistoryBar
            sessions={sessions}
            history={session.history}
            currentIndex={historyIndex}
            currentSessionId={session.sessionId}
            activePastSessionId={pastView?.sessionId}
            activePastStepIdx={pastView?.idx}
            isLoading={session.isLoading}
            onSelect={handleHistorySelect}
            onPastStepSelect={handlePastStepSelect}
            onNewImage={handleNewImage}
          />
        </aside>

        {/* Main column */}
        <div className="flex flex-1 flex-col min-h-0 min-w-0">
          {/* Image area */}
          <main
            ref={mainRef}
            className="flex items-center justify-center p-4 overflow-hidden shrink-0"
            style={{ height: '78vh' }}
          >
            {showImage ? (
              <ImageViewer
                imageSrc={displayImageSrc!}
                isLoading={session.isLoading}
                showScrollHint={showScrollHint && !isHoldingOriginal && !pastView}
                onMouseDown={() => setIsHoldingOriginal(true)}
                onMouseUp={() => setIsHoldingOriginal(false)}
                onMouseLeave={() => setIsHoldingOriginal(false)}
              />
            ) : session.isLoading ? (
              <div className="flex flex-col items-center gap-4">
                <div className="w-10 h-10 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
                <p className="text-gray-500 text-sm">처리 중...</p>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-3 text-center select-none pointer-events-none">
                <div className="w-16 h-16 bg-gray-100 rounded-2xl flex items-center justify-center">
                  <svg className="w-8 h-8 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                  </svg>
                </div>
                <p className="text-sm text-gray-400">이미지를 업로드하거나 텍스트로 생성하세요</p>
              </div>
            )}
          </main>

          {/* Input panel */}
          {session.sessionId ? (
            <ChatPanel
              isLoading={session.isLoading}
              onSend={handleSend}
              onSave={session.saveImage}
              error={session.error}
            />
          ) : (
            <div className="bg-white border-t border-gray-200 px-6 py-4 shrink-0">
              {session.error && <p className="text-red-500 text-xs mb-2 text-center">{session.error}</p>}
              <div className={`flex items-center gap-3 bg-gray-50 border rounded-full px-4 py-2.5 transition-colors ${
                session.isLoading ? 'border-gray-200 opacity-70' : 'border-gray-200 hover:border-gray-300 focus-within:border-blue-300'
              }`}>
                <button
                  onClick={() => fileInputRef.current?.click()}
                  disabled={session.isLoading}
                  className="text-gray-400 hover:text-gray-600 shrink-0 disabled:opacity-40"
                  title="이미지 업로드"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                  </svg>
                </button>
                <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={handleFileChange} />
                <input
                  value={preInput}
                  onChange={(e) => setPreInput(e.target.value)}
                  onKeyDown={handlePreKey}
                  placeholder={pastView ? "이 시점부터 편집을 계속하세요..." : "이미지를 업로드하거나 원하는 이미지를 설명하세요..."}
                  disabled={session.isLoading}
                  className="flex-1 bg-transparent text-sm text-gray-700 placeholder-gray-400 outline-none"
                />
                <button
                  onClick={handlePreSubmit}
                  disabled={session.isLoading || !preInput.trim()}
                  className="w-9 h-9 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-300 text-white rounded-full flex items-center justify-center transition-colors shrink-0"
                >
                  {session.isLoading ? (
                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  ) : (
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 12h14m-7-7 7 7-7 7" />
                    </svg>
                  )}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
