import { useState } from 'react'
import type { HistoryEntry } from '../hooks/useSession'
import type { SessionSummary } from '../api/client'
import { getTrajectory } from '../api/client'

export interface EditStep {
  text: string
  imageUrl: string | null
}

interface SessionDetail {
  steps: EditStep[]
}

interface Props {
  sessions: SessionSummary[]
  history: HistoryEntry[]
  currentIndex: number
  currentSessionId: string | null
  activePastSessionId?: string | null
  activePastStepIdx?: number
  isLoading?: boolean
  onSelect: (index: number) => void
  onPastStepSelect: (sessionId: string, steps: EditStep[], idx: number) => void
  onNewImage: () => void
}

/** Parse trajectory events into ordered (text, imageUrl) pairs. */
function extractSteps(events: any[]): EditStep[] {
  const steps: EditStep[] = []

  const uploadEv = events.find(ev => ev.type === 'image_upload')
  if (uploadEv) {
    steps.push({
      text: uploadEv.payload?.filename || '원본 이미지',
      imageUrl: uploadEv.payload?.image_url || null,
    })
  }

  // Pair each chat_input with the next edit_applied's image_url
  for (let i = 0; i < events.length; i++) {
    const ev = events[i]
    if (ev.type === 'chat_input' && ev.payload?.user_text) {
      let imageUrl: string | null = null
      for (let j = i + 1; j < events.length; j++) {
        if (events[j].type === 'edit_applied') {
          imageUrl = events[j].payload?.image_url || null
          break
        }
      }
      steps.push({ text: ev.payload.user_text as string, imageUrl })
    }
  }

  return steps
}

function formatDate(iso: string): string {
  try {
    // Treat naive datetimes (no Z / offset) as UTC
    const utcStr = iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z'
    return new Date(utcStr).toLocaleString('ko-KR', {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
    })
  } catch {
    return ''
  }
}

export default function HistoryBar({
  sessions,
  history,
  currentIndex,
  currentSessionId,
  activePastSessionId,
  activePastStepIdx,
  isLoading,
  onSelect,
  onPastStepSelect,
  onNewImage,
}: Props) {
  // Accordion: only one past session expanded at a time
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [detailCache, setDetailCache] = useState<Record<string, SessionDetail | 'loading'>>({})

  const toggleSession = async (sessionId: string) => {
    if (expandedId === sessionId) {
      setExpandedId(null)
      return
    }
    setExpandedId(sessionId)
    if (!detailCache[sessionId]) {
      setDetailCache(prev => ({ ...prev, [sessionId]: 'loading' }))
      const traj = await getTrajectory(sessionId)
      const steps = traj ? extractSteps(traj.events || []) : []
      setDetailCache(prev => ({ ...prev, [sessionId]: { steps } }))
    }
  }

  const pastSessions = sessions.filter(s => s.session_id !== currentSessionId)

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 pt-5 pb-2 shrink-0">
        <p className="text-xs font-bold text-gray-800 uppercase tracking-widest">Sessions</p>
      </div>

      <div className="flex-1 overflow-y-auto min-h-0 pb-2">

        {/* Past sessions — oldest first (already sorted by backend) */}
        {pastSessions.map(s => {
          const detail = detailCache[s.session_id]
          const isExpanded = expandedId === s.session_id

          return (
            <div key={s.session_id}>
              <button
                onClick={() => toggleSession(s.session_id)}
                className="w-full flex items-start gap-2 px-4 py-2 hover:bg-gray-100 text-left transition-colors"
              >
                <span className={`text-gray-400 text-[10px] mt-0.5 shrink-0 transition-transform duration-150 inline-block ${isExpanded ? 'rotate-90' : ''}`}>
                  ▶
                </span>
                <div className="min-w-0">
                  <p className="text-xs text-gray-700 leading-snug line-clamp-2">{s.summary}</p>
                  <p className="text-[10px] text-gray-400 mt-0.5">{formatDate(s.updated_at || s.created_at)}</p>
                </div>
              </button>

              {isExpanded && (
                <div className="pl-7 pr-3 pb-2">
                  {detail === 'loading' ? (
                    <p className="text-[10px] text-gray-400 py-1">로딩 중...</p>
                  ) : !detail || (detail as SessionDetail).steps.length === 0 ? (
                    <p className="text-[10px] text-gray-400 py-1">편집 기록 없음</p>
                  ) : (
                    (detail as SessionDetail).steps.map((step, i) => {
                      const steps = (detail as SessionDetail).steps
                      const isLast = i === steps.length - 1
                      const isActive = activePastSessionId === s.session_id && activePastStepIdx === i
                      return (
                        <div key={i} className="relative flex gap-0">
                          {!isLast && (
                            <div className="absolute left-[5px] top-4 bottom-0 w-px bg-gray-100" />
                          )}
                          <button
                            onClick={() => onPastStepSelect(s.session_id, steps, i)}
                            className="flex gap-2.5 items-start py-1.5 w-full text-left group"
                          >
                            <div className={`w-2.5 h-2.5 rounded-full mt-0.5 shrink-0 transition-colors ${
                              isActive ? 'bg-blue-500' : 'bg-gray-200 group-hover:bg-blue-400'
                            }`} />
                            <span className={`text-[10px] leading-snug break-words transition-colors ${
                              isActive ? 'font-bold text-gray-900' : 'text-gray-500 group-hover:text-gray-800'
                            }`}>
                              {step.text}
                            </span>
                          </button>
                        </div>
                      )
                    })
                  )}
                </div>
              )}
            </div>
          )
        })}

        {/* Divider between past and current */}
        {pastSessions.length > 0 && currentSessionId && (
          <div className="mx-4 border-t border-gray-200 my-2" />
        )}

        {/* Current session timeline */}
        {currentSessionId && history.length > 0 && (
          <div>
            <div className="px-4 py-1.5 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-blue-500 shrink-0 animate-pulse" />
              <span className="text-xs font-semibold text-blue-600">Current Session</span>
            </div>
            <div className="pl-5 pr-3">
              {history.map((entry, i) => {
                const isActive = i === currentIndex
                const isLast = i === history.length - 1
                return (
                  <div key={i} className="relative flex gap-0">
                    {!isLast && (
                      <div className="absolute left-[5px] top-4 bottom-0 w-px bg-gray-200" />
                    )}
                    <button
                      onClick={() => onSelect(i)}
                      className="flex gap-2.5 items-start py-1.5 w-full text-left group"
                    >
                      <div className={`w-2.5 h-2.5 rounded-full mt-0.5 shrink-0 transition-colors ${
                        isActive ? 'bg-blue-500' : 'bg-gray-300 group-hover:bg-gray-400'
                      }`} />
                      <span className={`text-xs leading-snug break-words ${
                        isActive ? 'font-bold text-gray-900' : 'text-gray-500'
                      }`}>
                        {entry.label}
                      </span>
                    </button>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {!currentSessionId && pastSessions.length === 0 && (
          <p className="px-4 text-xs text-gray-400 mt-2">세션 없음</p>
        )}
      </div>

      <div className="p-4 border-t border-gray-200 shrink-0">
        <button
          onClick={onNewImage}
          disabled={isLoading}
          className="text-xs text-blue-500 hover:text-blue-700 font-medium disabled:opacity-40 disabled:cursor-not-allowed"
        >
          + New Session
        </button>
      </div>
    </div>
  )
}
