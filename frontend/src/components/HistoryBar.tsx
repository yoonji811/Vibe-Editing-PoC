import { useState } from 'react'
import type { HistoryEntry } from '../hooks/useSession'
import type { SessionSummary, TreeNode } from '../api/client'
import { getTrajectory, getEditTree } from '../api/client'

/** Truncate text to first N words. */
function truncateLabel(text: string, maxWords = 5): string {
  const words = text.trim().split(/\s+/)
  if (words.length <= maxWords) return text
  return words.slice(0, maxWords).join(' ') + '…'
}

/** Find deepest leaf in current-session TreeNode[]. */
function findDeepestLeafForTree(nodes: TreeNode[], startId: string): string {
  const nodeMap = new Map(nodes.map(n => [n.edit_id, n]))
  let current = startId
  while (true) {
    const node = nodeMap.get(current)
    if (!node || node.children_ids.length === 0) break
    current = node.children_ids[0]
  }
  return current
}

export interface EditStep {
  text: string
  imageUrl: string | null
}

interface SessionDetail {
  steps: EditStep[]
}

/** Tree node reconstructed from trajectory events. */
interface PastTreeNode {
  editId: string
  parentEditId: string | null
  prompt: string
  childrenIds: string[]
}

/** Reconstruct tree from trajectory events. */
function reconstructTree(events: any[]): PastTreeNode[] {
  const nodes: PastTreeNode[] = []
  const nodeMap = new Map<string, PastTreeNode>()

  for (const ev of events) {
    const editId = ev.payload?.edit_id
    if (!editId) continue

    if (nodeMap.has(editId)) continue

    const parentId = ev.payload?.parent_edit_id ?? null
    const prompt =
      ev.type === 'image_upload'
        ? 'original'
        : ev.payload?.user_text ?? ev.payload?.intent_classified ?? editId.slice(0, 6)

    const node: PastTreeNode = { editId, parentEditId: parentId, prompt, childrenIds: [] }
    nodeMap.set(editId, node)
    nodes.push(node)

    if (parentId && nodeMap.has(parentId)) {
      const parent = nodeMap.get(parentId)!
      if (!parent.childrenIds.includes(editId)) {
        parent.childrenIds.push(editId)
      }
    }
  }

  return nodes
}

/** Get ancestor chain root → ... → targetId */
function getAncestorChain(nodes: PastTreeNode[], targetId: string): PastTreeNode[] {
  const nodeMap = new Map(nodes.map(n => [n.editId, n]))
  const chain: PastTreeNode[] = []
  let current: string | null = targetId
  while (current) {
    const node = nodeMap.get(current)
    if (!node) break
    chain.push(node)
    current = node.parentEditId
  }
  chain.reverse()
  return chain
}

/** Find deepest leaf starting from a node. */
function findDeepestLeaf(nodes: PastTreeNode[], startId: string): string {
  const nodeMap = new Map(nodes.map(n => [n.editId, n]))
  let current = startId
  while (true) {
    const node = nodeMap.get(current)
    if (!node || node.childrenIds.length === 0) break
    current = node.childrenIds[0]
  }
  return current
}

interface Props {
  sessions: SessionSummary[]
  history: HistoryEntry[]
  currentEditId: string | null
  editTree: TreeNode[]
  currentSessionId: string | null
  activePastSessionId?: string | null
  activePastStepIdx?: number
  isLoading?: boolean
  onSelect: (editId: string) => void
  onNavigateNode: (editId: string) => Promise<void>
  onPastStepSelect: (sessionId: string, steps: EditStep[], idx: number) => void
  onNewImage: () => void
}

/** Parse trajectory events into ordered (text, imageUrl) pairs — for pastStepSelect compat. */
function extractSteps(events: any[]): EditStep[] {
  const steps: EditStep[] = []

  const uploadEv = events.find(ev => ev.type === 'image_upload')
  if (uploadEv) {
    steps.push({
      text: uploadEv.payload?.filename || '원본 이미지',
      imageUrl: uploadEv.payload?.image_url || null,
    })
  }

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
    const utcStr = iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z'
    return new Date(utcStr).toLocaleString('ko-KR', {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
    })
  } catch {
    return ''
  }
}

interface PastSessionCache {
  steps: EditStep[]
  tree: PastTreeNode[]
  leafId: string | null
  /** editId → Cloudinary image URL, built from trajectory events */
  imageMap: Map<string, string>
}

/** Build editId → imageUrl map from raw trajectory events.
 *  Covers image_upload (root) and chat_input/edit_applied pairs. */
function buildImageMap(events: any[]): Map<string, string> {
  const map = new Map<string, string>()

  // Root: image_upload event
  for (const ev of events) {
    if (ev.type === 'image_upload' && ev.payload?.edit_id && ev.payload?.image_url) {
      map.set(ev.payload.edit_id, ev.payload.image_url)
    }
  }

  // Edits: pair chat_input (has edit_id) with the next edit_applied (has image_url)
  for (let i = 0; i < events.length; i++) {
    const ev = events[i]
    // Some backends put edit_id + image_url directly on edit_applied
    if (ev.type === 'edit_applied' && ev.payload?.edit_id && ev.payload?.image_url) {
      map.set(ev.payload.edit_id, ev.payload.image_url)
      continue
    }
    // Fallback: chat_input carries edit_id; look ahead for edit_applied's image_url
    if (ev.type === 'chat_input' && ev.payload?.edit_id) {
      const editId = ev.payload.edit_id
      if (map.has(editId)) continue
      for (let j = i + 1; j < events.length; j++) {
        if (events[j].type === 'edit_applied') {
          const url = events[j].payload?.image_url
          if (url) map.set(editId, url)
          break
        }
        // Stop at the next chat_input to avoid cross-branch pairing
        if (events[j].type === 'chat_input') break
      }
    }
  }

  return map
}

export default function HistoryBar({
  sessions,
  history,
  currentEditId,
  editTree,
  currentSessionId,
  activePastSessionId,
  activePastStepIdx,
  isLoading,
  onSelect,
  onNavigateNode,
  onPastStepSelect,
  onNewImage,
}: Props) {
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [detailCache, setDetailCache] = useState<Record<string, PastSessionCache | 'loading'>>({})
  // Track which leaf to show per past session (for branch switching)
  const [pastLeafId, setPastLeafId] = useState<Record<string, string>>({})
  // Track which node's branch panel is open
  const [expandedBranchId, setExpandedBranchId] = useState<string | null>(null)

  const toggleSession = async (sessionId: string) => {
    if (expandedId === sessionId) {
      setExpandedId(null)
      return
    }
    setExpandedId(sessionId)
    if (!detailCache[sessionId]) {
      setDetailCache(prev => ({ ...prev, [sessionId]: 'loading' }))
      const traj = await getTrajectory(sessionId)
      const events = traj?.events || []
      const steps = extractSteps(events)
      const tree = reconstructTree(events)
      const imageMap = buildImageMap(events)

      // Find the deepest leaf of the tree (default branch)
      const roots = tree.filter(n => !n.parentEditId)
      const leafId = roots.length > 0 ? findDeepestLeaf(tree, roots[0].editId) : null

      setDetailCache(prev => ({ ...prev, [sessionId]: { steps, tree, leafId, imageMap } }))
      if (leafId) {
        setPastLeafId(prev => ({ ...prev, [sessionId]: leafId }))
      }
    }
  }

  const pastSessions = sessions.filter(s => s.session_id !== currentSessionId)

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 pt-5 pb-2 shrink-0">
        <p className="text-xs font-bold text-gray-800 uppercase tracking-widest">Sessions</p>
      </div>

      <div className="flex-1 overflow-y-auto min-h-0 pb-2">

        {/* Past sessions */}
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
                  ) : !detail ? (
                    <p className="text-[10px] text-gray-400 py-1">편집 기록 없음</p>
                  ) : detail.tree.length > 0 ? (
                    // Tree view for past session
                    (() => {
                      const leafId = pastLeafId[s.session_id] ?? detail.leafId
                      const chain = leafId ? getAncestorChain(detail.tree, leafId) : []
                      if (chain.length === 0) {
                        return <p className="text-[10px] text-gray-400 py-1">편집 기록 없음</p>
                      }
                      return chain.map((node, i) => {
                        const isLast = i === chain.length - 1
                        const isActive = activePastSessionId === s.session_id && activePastStepIdx === i
                        // Use imageMap for branch-accurate image lookup
                        const nodeImageUrl = detail.imageMap.get(node.editId) ?? null
                        const hasImage = !!nodeImageUrl
                        const nextInChain = i < chain.length - 1 ? chain[i + 1].editId : null
                        const alternativeChildren = node.childrenIds.filter(id => id !== nextInChain)
                        const isBranchExpanded = expandedBranchId === node.editId
                        return (
                          <div key={node.editId}>
                            <div className="relative flex items-center gap-0">
                              {!isLast && (
                                <div className="absolute left-[5px] top-4 bottom-0 w-px bg-gray-100" />
                              )}
                              <button
                                onClick={() => {
                                  if (!hasImage) return
                                  const chainSteps: EditStep[] = chain.map(n => ({
                                    text: n.prompt === 'original' ? '원본 이미지' : n.prompt,
                                    imageUrl: detail.imageMap.get(n.editId) ?? null,
                                  }))
                                  onPastStepSelect(s.session_id, chainSteps, i)
                                }}
                                disabled={!hasImage}
                                className={`flex gap-2.5 items-start py-1.5 flex-1 text-left group ${hasImage ? '' : 'opacity-40 cursor-not-allowed'}`}
                              >
                                <div className={`w-2.5 h-2.5 rounded-full mt-0.5 shrink-0 transition-colors ${
                                  isActive ? 'bg-blue-500' : hasImage ? 'bg-gray-200 group-hover:bg-blue-400' : 'bg-gray-200'
                                }`} />
                                <span className={`text-[10px] leading-snug truncate transition-colors flex-1 ${
                                  isActive ? 'font-bold text-gray-900' : 'text-gray-500 group-hover:text-gray-800'
                                }`} title={node.prompt === 'original' ? '원본 이미지' : node.prompt}>
                                  {node.prompt === 'original' ? '원본 이미지' : truncateLabel(node.prompt)}
                                </span>
                              </button>
                              {alternativeChildren.length > 0 && (
                                <button
                                  onClick={() => setExpandedBranchId(prev => prev === node.editId ? null : node.editId)}
                                  className="ml-1 mr-1 text-[9px] bg-blue-50 text-blue-500 px-1.5 py-0.5 rounded-full shrink-0 hover:bg-blue-100"
                                >
                                  +{alternativeChildren.length}
                                </button>
                              )}
                            </div>
                            {isBranchExpanded && (
                              <div className="ml-5 pl-2 border-l border-blue-100 mb-1">
                                {alternativeChildren.map(childId => {
                                  const childNode = detail.tree.find(n => n.editId === childId)
                                  const label = childNode?.prompt === 'original' ? '원본 이미지' : (childNode?.prompt || childId.slice(0, 6))
                                  return (
                                    <button
                                      key={childId}
                                      onClick={() => {
                                        const leaf = findDeepestLeaf(detail.tree, childId)
                                        // Build branch-specific steps using the imageMap
                                        const newChain = getAncestorChain(detail.tree, leaf)
                                        const branchSteps: EditStep[] = newChain.map(node => ({
                                          text: node.prompt === 'original' ? '원본 이미지' : node.prompt,
                                          imageUrl: detail.imageMap.get(node.editId) ?? null,
                                        }))
                                        // Update HistoryBar timeline
                                        setPastLeafId(prev => ({ ...prev, [s.session_id]: leaf }))
                                        // Update main image view
                                        onPastStepSelect(s.session_id, branchSteps, branchSteps.length - 1)
                                        setExpandedBranchId(null)
                                      }}
                                      className="flex gap-2 items-center py-1 w-full text-left group hover:bg-gray-50 rounded"
                                    >
                                      <div className="w-1.5 h-1.5 rounded-full bg-blue-300 group-hover:bg-blue-500 shrink-0" />
                                      <span className="text-[10px] text-blue-500 group-hover:text-blue-700 truncate flex-1">{label}</span>
                                    </button>
                                  )
                                })}
                              </div>
                            )}
                          </div>
                        )
                      })
                    })()
                  ) : detail.steps.length > 0 ? (
                    // Fallback: flat list for sessions without edit_id in events
                    detail.steps.map((step, i) => {
                      const isLast = i === detail.steps.length - 1
                      const isActive = activePastSessionId === s.session_id && activePastStepIdx === i
                      const hasImage = !!step.imageUrl
                      return (
                        <div key={i} className="relative flex gap-0">
                          {!isLast && (
                            <div className="absolute left-[5px] top-4 bottom-0 w-px bg-gray-100" />
                          )}
                          <button
                            onClick={() => hasImage ? onPastStepSelect(s.session_id, detail.steps, i) : undefined}
                            disabled={!hasImage}
                            className={`flex gap-2.5 items-start py-1.5 w-full text-left group ${hasImage ? '' : 'opacity-40 cursor-not-allowed'}`}
                          >
                            <div className={`w-2.5 h-2.5 rounded-full mt-0.5 shrink-0 transition-colors ${
                              isActive ? 'bg-blue-500' : hasImage ? 'bg-gray-200 group-hover:bg-blue-400' : 'bg-gray-200'
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
                  ) : (
                    <p className="text-[10px] text-gray-400 py-1">편집 기록 없음</p>
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
        {currentSessionId && (
          <div>
            <div className="px-4 py-1.5 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-blue-500 shrink-0 animate-pulse" />
              <span className="text-xs font-semibold text-blue-600">Current Session</span>
            </div>
            {history.length > 0 ? (
              <div className="pl-5 pr-3">
                {history.map((entry, i) => {
                  const isActive = entry.editId === currentEditId
                  const isLast = i === history.length - 1
                  const node = editTree.find(n => n.edit_id === entry.editId)
                  const nextInChain = i < history.length - 1 ? history[i + 1].editId : null
                  const alternativeChildren = node
                    ? node.children_ids.filter(id => id !== nextInChain)
                    : []
                  const isBranchExpanded = expandedBranchId === entry.editId
                  return (
                    <div key={entry.editId || i}>
                      <div className="relative flex items-center gap-0">
                        {!isLast && (
                          <div className="absolute left-[5px] top-4 bottom-0 w-px bg-gray-200" />
                        )}
                        <button
                          onClick={() => entry.editId && onSelect(entry.editId)}
                          className="flex gap-2.5 items-start py-1.5 flex-1 text-left group"
                        >
                          <div className={`w-2.5 h-2.5 rounded-full mt-0.5 shrink-0 transition-colors ${
                            isActive ? 'bg-blue-500' : 'bg-gray-300 group-hover:bg-gray-400'
                          }`} />
                          <span className={`text-xs leading-snug truncate flex-1 ${
                            isActive ? 'font-bold text-gray-900' : 'text-gray-500'
                          }`} title={entry.label}>
                            {truncateLabel(entry.label)}
                          </span>
                        </button>
                        {alternativeChildren.length > 0 && (
                          <button
                            onClick={() => setExpandedBranchId(prev => prev === entry.editId ? null : entry.editId!)}
                            className="ml-1 mr-1 text-[9px] bg-blue-50 text-blue-500 px-1.5 py-0.5 rounded-full shrink-0 hover:bg-blue-100"
                          >
                            +{alternativeChildren.length}
                          </button>
                        )}
                      </div>
                      {isBranchExpanded && (
                        <div className="ml-5 pl-2 border-l border-blue-100 mb-1">
                          {alternativeChildren.map(childId => {
                            const childNode = editTree.find(n => n.edit_id === childId)
                            const label = childNode?.intent || childNode?.prompt || childId.slice(0, 6)
                            return (
                              <button
                                key={childId}
                                onClick={() => {
                                  const leaf = findDeepestLeafForTree(editTree, childId)
                                  onNavigateNode(leaf)
                                  setExpandedBranchId(null)
                                }}
                                className="flex gap-2 items-center py-1 w-full text-left group hover:bg-gray-50 rounded"
                              >
                                <div className="w-1.5 h-1.5 rounded-full bg-blue-300 group-hover:bg-blue-500 shrink-0" />
                                <span className="text-[10px] text-blue-500 group-hover:text-blue-700 truncate flex-1">{label}</span>
                              </button>
                            )
                          })}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            ) : (
              <p className="pl-5 text-[10px] text-gray-400">이미지를 업로드하면 편집 기록이 여기에 표시됩니다</p>
            )}
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
