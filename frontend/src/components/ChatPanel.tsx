import { useState } from 'react'
import type { Recommendation } from '../api/client'

interface Props {
  isLoading: boolean
  onSend: (text: string, selectedRecommendationIndex?: number) => void
  onSave: () => void
  error: string | null
  recommendations?: Recommendation[]
  isLoadingRecommendations?: boolean
}

export default function ChatPanel({
  isLoading,
  onSend,
  error,
  recommendations = [],
  isLoadingRecommendations = false,
}: Props) {
  const [input, setInput] = useState('')
  const [selectedIndex, setSelectedIndex] = useState<number | undefined>(undefined)

  const submit = () => {
    const text = input.trim()
    if (!text || isLoading) return
    const idx = selectedIndex
    setInput('')
    setSelectedIndex(undefined)
    onSend(text, idx)
  }

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  const handleChipClick = (rec: Recommendation, index: number) => {
    setInput(rec.text)
    setSelectedIndex(index)
  }

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setInput(e.target.value)
    // Clear selected index if user modifies the text
    setSelectedIndex(undefined)
  }

  const showRecommendations = !isLoading && (isLoadingRecommendations || recommendations.length > 0)

  return (
    <div className="bg-white border-t border-gray-200 px-6 py-4 shrink-0">
      {error && <p className="text-red-500 text-xs mb-2 text-center">{error}</p>}

      {/* Recommendations above input */}
      {showRecommendations && (
        <div className="flex items-center justify-center gap-2 mb-3 flex-wrap">
          {isLoadingRecommendations ? (
            <>
              <div className="h-7 w-28 bg-gray-100 rounded-full animate-pulse" />
              <div className="h-7 w-32 bg-gray-100 rounded-full animate-pulse" />
              <div className="h-7 w-24 bg-gray-100 rounded-full animate-pulse" />
            </>
          ) : (
            recommendations.map((rec, i) => (
              <button
                key={i}
                onClick={() => handleChipClick(rec, i)}
                className="text-xs text-gray-500 hover:text-blue-600 bg-gray-50 hover:bg-blue-50 border border-gray-200 hover:border-blue-200 rounded-full px-3 py-1.5 transition-colors"
              >
                {rec.text}
              </button>
            ))
          )}
        </div>
      )}

      <div className={`flex items-center gap-3 bg-gray-50 border rounded-full px-4 py-2.5 transition-colors ${
        isLoading ? 'border-gray-200 opacity-70' : 'border-gray-200 hover:border-gray-300 focus-within:border-blue-300'
      }`}>
        <input
          value={input}
          onChange={handleInputChange}
          onKeyDown={onKey}
          placeholder='Instruct the Editor... (e.g. "Make it brighter")'
          disabled={isLoading}
          className="flex-1 bg-transparent text-sm text-gray-700 placeholder-gray-400 outline-none"
        />
        {/* Mic */}
        <button className="text-gray-400 hover:text-gray-600 shrink-0" title="Voice input">
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v4M8 23h8" />
          </svg>
        </button>
        {/* Send */}
        <button
          onClick={submit}
          disabled={isLoading || !input.trim()}
          className="w-9 h-9 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-300 text-white rounded-full flex items-center justify-center transition-colors shrink-0"
        >
          {isLoading ? (
            <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
          ) : (
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 12h14m-7-7 7 7-7 7" />
            </svg>
          )}
        </button>
      </div>
    </div>
  )
}
