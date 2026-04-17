import { useState } from 'react'
import { useSession } from './hooks/useSession'
import ImageUploader from './components/ImageUploader'
import ImageViewer from './components/ImageViewer'
import ChatPanel from './components/ChatPanel'
import HistoryBar from './components/HistoryBar'

type StartMode = 'upload' | 'generate'

export default function App() {
  const session = useSession()
  const [historyIndex, setHistoryIndex] = useState(0)
  const [nicknameInput, setNicknameInput] = useState('')
  const [nickname, setNickname] = useState<string | null>(null)
  const [startMode, setStartMode] = useState<StartMode>('upload')
  const [generatePrompt, setGeneratePrompt] = useState('')

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

  const handleGenerate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!nickname || !generatePrompt.trim()) return
    await session.generateFromText(generatePrompt.trim(), nickname)
    setHistoryIndex(0)
  }

  const handleReset = () => {
    session.resetSession()
    setNickname(null)
    setNicknameInput('')
    setGeneratePrompt('')
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
          {/* Image area — fixed height so chat is always visible */}
          <main className="flex items-center justify-center p-4 overflow-hidden shrink-0" style={{ height: '55vh' }}>
            {session.sessionId && displayImage ? (
              <ImageViewer imageB64={displayImage} />
            ) : session.isLoading ? (
              <div className="flex flex-col items-center gap-4">
                <div className="w-10 h-10 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
                <p className="text-gray-500 text-sm">
                  {startMode === 'generate' ? '이미지 생성 중...' : '업로드 중...'}
                </p>
              </div>
            ) : startMode === 'upload' ? (
              <ImageUploader onUpload={handleUpload} isLoading={session.isLoading} />
            ) : (
              /* Text-to-image input */
              <form onSubmit={handleGenerate} className="w-full max-w-lg flex flex-col items-center gap-5">
                <div className="w-12 h-12 bg-purple-50 rounded-xl flex items-center justify-center">
                  <svg className="w-6 h-6 text-purple-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.347.346A3.978 3.978 0 0112 16a3.978 3.978 0 01-2.828-1.172l-.347-.346z" />
                  </svg>
                </div>
                <div className="text-center">
                  <h2 className="text-xl font-bold text-gray-800">Generate from Text</h2>
                  <p className="text-sm text-gray-500 mt-1">원하는 이미지를 텍스트로 설명하세요</p>
                </div>
                <textarea
                  value={generatePrompt}
                  onChange={(e) => setGeneratePrompt(e.target.value)}
                  placeholder="예: A serene mountain lake at sunset with reflections..."
                  rows={3}
                  autoFocus
                  className="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-300 resize-none"
                />
                <button
                  type="submit"
                  disabled={!generatePrompt.trim() || session.isLoading}
                  className="w-full bg-purple-500 hover:bg-purple-600 disabled:bg-gray-200 disabled:text-gray-400 text-white font-semibold rounded-xl py-3 text-sm transition-colors"
                >
                  이미지 생성
                </button>
              </form>
            )}
          </main>

          {/* Mode toggle — only shown before session starts */}
          {!session.sessionId && !session.isLoading && (
            <div className="flex justify-center gap-2 pb-2 shrink-0">
              <button
                onClick={() => setStartMode('upload')}
                className={`text-xs px-4 py-1.5 rounded-full font-medium transition-colors ${
                  startMode === 'upload'
                    ? 'bg-blue-500 text-white'
                    : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
                }`}
              >
                이미지 업로드
              </button>
              <button
                onClick={() => setStartMode('generate')}
                className={`text-xs px-4 py-1.5 rounded-full font-medium transition-colors ${
                  startMode === 'generate'
                    ? 'bg-purple-500 text-white'
                    : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
                }`}
              >
                텍스트로 생성
              </button>
            </div>
          )}

          {/* Chat panel */}
          {session.sessionId && (
            <ChatPanel
              isLoading={session.isLoading}
              onSend={handleSend}
              onSave={session.saveImage}
              error={session.error}
            />
          )}

          {!session.sessionId && session.error && (
            <p className="text-center text-red-500 text-sm pb-4 shrink-0">{session.error}</p>
          )}
        </div>
      </div>
    </div>
  )
}
