import { useState } from 'react'
import { useSession } from './hooks/useSession'
import ImageUploader from './components/ImageUploader'
import ImageViewer from './components/ImageViewer'
import ChatPanel from './components/ChatPanel'
import HistoryBar from './components/HistoryBar'

export default function App() {
  const session = useSession()
  const [historyIndex, setHistoryIndex] = useState(0)

  const displayImage =
    historyIndex < session.history.length
      ? session.history[historyIndex].imageB64
      : session.currentImageB64

  const handleHistorySelect = (index: number) => setHistoryIndex(index)

  const handleSend = async (text: string) => {
    await session.sendMessage(text)
    setHistoryIndex(session.history.length)
  }

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col font-sans">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 flex items-center px-6 py-3 shrink-0">
        <span className="text-lg font-bold text-gray-900 tracking-tight">Vibe Editor</span>
        <div className="flex-1 flex justify-center">
          <span className="text-xs font-semibold tracking-widest text-blue-600 uppercase">Editor</span>
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
              onNewImage={session.resetSession}
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
              <ImageUploader onUpload={session.uploadImage} isLoading={session.isLoading} />
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
