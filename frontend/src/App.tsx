import { useState } from 'react'
import { useSession } from './hooks/useSession'
import ImageUploader from './components/ImageUploader'
import ImageViewer from './components/ImageViewer'
import ChatPanel from './components/ChatPanel'
import HistoryBar from './components/HistoryBar'

export default function App() {
  const session = useSession()
  const [historyIndex, setHistoryIndex] = useState(0)
  const [nicknameInput, setNicknameInput] = useState('')
  const [nickname, setNickname] = useState<string | null>(null)

  const displayImage =
    historyIndex < session.history.length
      ? session.history[historyIndex].imageB64
      : session.currentImageB64

  const handleHistorySelect = (index: number) => setHistoryIndex(index)

  const handleSend = async (text: string) => {
    await session.sendMessage(text)
    setHistoryIndex(session.history.length)
  }

  const handleNicknameSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = nicknameInput.trim()
    if (trimmed) setNickname(trimmed)
  }

  const handleUpload = async (file: File) => {
    if (!nickname) return
    await session.uploadImage(file, nickname)
  }

  const handleReset = () => {
    session.resetSession()
    setNickname(null)
    setNicknameInput('')
    setHistoryIndex(0)
  }

  // Step 1: Nickname input
  if (!nickname) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <form onSubmit={handleNicknameSubmit} className="bg-white rounded-2xl shadow-sm border border-gray-200 p-10 flex flex-col items-center gap-6 w-full max-w-sm">
          <div className="w-12 h-12 bg-blue-50 rounded-xl flex items-center justify-center">
            <svg className="w-6 h-6 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
            </svg>
          </div>
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
        </form>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col font-sans">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 flex items-center px-6 py-3 shrink-0">
        <span className="text-lg font-bold text-gray-900 tracking-tight">Vibe Editor</span>
        <div className="flex-1 flex justify-center">
          <span className="text-xs font-semibold tracking-widest text-blue-600 uppercase">{nickname}</span>
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
        <aside className="hidden md:flex w-44 shrink-0 flex-col border-r border-gray-200 bg-gray-50 overflow-y-auto">
          {session.sessionId ? (
            <HistoryBar
              history={session.history}
              currentIndex={historyIndex}
              onSelect={handleHistorySelect}
              onNewImage={handleReset}
            />
          ) : (
            <div className="px-4 pt-5">
              <p className="text-xs font-bold text-gray-800 uppercase tracking-widest">Recent States</p>
              <p className="text-xs text-gray-400 mt-0.5">Edit Timeline</p>
            </div>
          )}
        </aside>

        {/* Main column */}
        <div className="flex flex-1 flex-col min-h-0 min-w-0">
          {/* Image area */}
          <main className="flex-1 flex items-center justify-center p-6 min-h-0 overflow-hidden">
            {session.sessionId && displayImage ? (
              <ImageViewer imageB64={displayImage} />
            ) : (
              <ImageUploader onUpload={handleUpload} isLoading={session.isLoading} />
            )}
          </main>

          {/* Instruction input — always visible when session active */}
          {session.sessionId && (
            <ChatPanel
              isLoading={session.isLoading}
              onSend={handleSend}
              onSave={session.saveImage}
              error={session.error}
            />
          )}

          {/* Upload error */}
          {!session.sessionId && session.error && (
            <p className="text-center text-red-500 text-sm pb-4">{session.error}</p>
          )}
        </div>
      </div>
    </div>
  )
}
