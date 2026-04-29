import { useState, useCallback, useMemo } from 'react'
import * as api from '../api/client'

export interface HistoryEntry {
  imageB64?: string
  imageUrl?: string
  label: string
  timestamp: string
  editId?: string
  eventId?: string  // trajectory event UUID (for feedback)
}

export interface SessionHook {
  sessionId: string | null
  nickname: string | null
  currentImageB64: string | null
  currentEditId: string | null
  activeLeafId: string | null
  history: HistoryEntry[]
  editTree: api.TreeNode[]
  rootEditId: string | null
  chatHistory: api.ChatMessage[]
  isLoading: boolean
  error: string | null
  recommendations: api.Recommendation[]
  isLoadingRecommendations: boolean
  uploadImage: (file: File, nickname: string) => Promise<void>
  generateFromText: (prompt: string, nickname: string) => Promise<void>
  sendMessage: (text: string, inputImageB64?: string, selectedRecommendationIndex?: number, baseEditId?: string) => Promise<void>
  resumeAndSend: (originalSessionId: string, imageUrl: string, text: string, userNickname: string, priorSteps?: { text: string; imageUrl: string | null }[], resumeIdx?: number) => Promise<void>
  /** Move the cursor to a node within the current branch (no API call). */
  setCursorTo: (editId: string) => void
  /** Move cursor to node, fetch image from server if not cached. Does NOT change active branch. */
  moveCursorTo: (editId: string) => Promise<void>
  /** Navigate to an arbitrary node (may switch branch, fetches image if needed). */
  navigateToNode: (editId: string) => Promise<void>
  saveImage: () => Promise<void>
  resetSession: () => void
}

/** Compute ancestor chain from tree nodes: root → ... → targetId */
function getAncestorChain(nodes: api.TreeNode[], targetId: string | null): api.TreeNode[] {
  if (!targetId || nodes.length === 0) return []
  const nodeMap = new Map(nodes.map(n => [n.edit_id, n]))
  const chain: api.TreeNode[] = []
  let current = targetId
  while (current) {
    const node = nodeMap.get(current)
    if (!node) break
    chain.push(node)
    current = node.parent_edit_id ?? ''
    if (!current) break
  }
  chain.reverse()
  return chain
}


export function useSession(): SessionHook {
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [nickname, setNickname] = useState<string | null>(null)
  const [currentImageB64, setCurrentImageB64] = useState<string | null>(null)
  // currentEditId: which node the user is VIEWING (cursor position in the branch)
  const [currentEditId, setCurrentEditId] = useState<string | null>(null)
  // activeLeafId: the leaf of the branch being displayed (determines which branch to show)
  const [activeLeafId, setActiveLeafId] = useState<string | null>(null)
  const [editTree, setEditTree] = useState<api.TreeNode[]>([])
  const [rootEditId, setRootEditId] = useState<string | null>(null)
  const [chatHistory, setChatHistory] = useState<api.ChatMessage[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [recommendations, setRecommendations] = useState<api.Recommendation[]>([])
  const [isLoadingRecommendations, setIsLoadingRecommendations] = useState(false)
  const [imageCache, setImageCache] = useState<Record<string, string>>({})

  const fetchRecommendations = useCallback(async (sid: string) => {
    setIsLoadingRecommendations(true)
    try {
      const recs = await api.getRecommendations(sid)
      setRecommendations(recs)
    } catch {
      setRecommendations([])
    } finally {
      setIsLoadingRecommendations(false)
    }
  }, [])

  // Derive history from tree: ancestor chain of activeLeafId (full branch)
  const history: HistoryEntry[] = useMemo(() => {
    const chain = getAncestorChain(editTree, activeLeafId)
    return chain.map(node => ({
      imageB64: imageCache[node.edit_id],
      label: node.prompt === 'original' ? 'Original Image' : (node.intent || node.prompt),
      timestamp: node.created_at,
      editId: node.edit_id,
      eventId: node.event_id,
    }))
  }, [editTree, activeLeafId, imageCache])

  const addTreeNode = useCallback((editId: string, parentEditId: string | null, prompt: string, intent: string, eventId?: string) => {
    setEditTree(prev => {
      const updated = prev.map(n =>
        n.edit_id === parentEditId && !n.children_ids.includes(editId)
          ? { ...n, children_ids: [...n.children_ids, editId] }
          : n
      )
      if (!updated.some(n => n.edit_id === editId)) {
        updated.push({
          edit_id: editId,
          parent_edit_id: parentEditId,
          prompt,
          intent,
          created_at: new Date().toISOString(),
          children_ids: [],
          event_id: eventId,
        })
      }
      return updated
    })
  }, [])

  const uploadImage = useCallback(async (file: File, userNickname: string) => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await api.createSession(file, userNickname)
      setSessionId(res.session_id)
      setNickname(userNickname)
      setCurrentImageB64(res.original_image_b64)
      setChatHistory([])
      setRecommendations([])

      const tree = await api.getEditTree(res.session_id)
      setEditTree(tree.nodes)
      setRootEditId(tree.root_edit_id)
      setCurrentEditId(tree.current_edit_id)
      setActiveLeafId(tree.current_edit_id)
      if (tree.current_edit_id) {
        setImageCache({ [tree.current_edit_id]: res.original_image_b64 })
      }

      fetchRecommendations(res.session_id)
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
      setChatHistory([])
      setRecommendations([])

      const tree = await api.getEditTree(res.session_id)
      setEditTree(tree.nodes)
      setRootEditId(tree.root_edit_id)
      setCurrentEditId(tree.current_edit_id)
      setActiveLeafId(tree.current_edit_id)
      if (tree.current_edit_id) {
        setImageCache({ [tree.current_edit_id]: res.original_image_b64 })
      }

      fetchRecommendations(res.session_id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setIsLoading(false)
    }
  }, [])

  const sendMessage = useCallback(
    async (text: string, inputImageB64?: string, selectedRecommendationIndex?: number, baseEditId?: string) => {
      if (!sessionId) return
      setIsLoading(true)
      setError(null)
      const userMsg: api.ChatMessage = {
        role: 'user',
        content: text,
        timestamp: new Date().toISOString(),
      }
      setChatHistory((prev) => [...prev, userMsg])
      try {
        const res = await api.editImage(sessionId, text, inputImageB64, selectedRecommendationIndex, baseEditId || currentEditId || undefined)
        const assistantMsg: api.ChatMessage = {
          role: 'assistant',
          content: res.chat_message,
          timestamp: new Date().toISOString(),
        }
        setChatHistory((prev) => [...prev, assistantMsg])

        if (res.result_image_b64) {
          setCurrentImageB64(res.result_image_b64)
          setRecommendations([])
        }

        if (res.edit_id) {
          setCurrentEditId(res.edit_id)
          if (res.result_image_b64) {
            setImageCache(prev => ({ ...prev, [res.edit_id!]: res.result_image_b64! }))
          }
          if (res.operation !== 'undo' && res.operation !== 'reset') {
            addTreeNode(res.edit_id, res.parent_edit_id ?? null, text, res.intent, res.event_id ?? undefined)
            // New edit = new leaf, switch branch to it
            setActiveLeafId(res.edit_id)
          }
          // Undo/reset: only move currentEditId (already set above).
          // Keep activeLeafId unchanged so the full branch stays visible.
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
        setChatHistory((prev) => prev.slice(0, -1))
      } finally {
        setIsLoading(false)
      }
    },
    [sessionId, currentEditId, addTreeNode]
  )

  /** Move cursor within the current branch — no API call, no branch switch. */
  const setCursorTo = useCallback((editId: string) => {
    setCurrentEditId(editId)
    const cached = imageCache[editId]
    if (cached) {
      setCurrentImageB64(cached)
    }
  }, [imageCache])

  /** Move cursor to node without changing branch — fetches image from server if not cached. */
  const moveCursorTo = useCallback(async (editId: string) => {
    setCurrentEditId(editId)
    const cached = imageCache[editId]
    if (cached) {
      setCurrentImageB64(cached)
      return
    }
    if (!sessionId) return
    try {
      const res = await api.navigateNode(sessionId, editId)
      if (res.ok) {
        setCurrentImageB64(res.image_b64)
        setImageCache(prev => ({ ...prev, [res.edit_id]: res.image_b64 }))
      }
    } catch { /* non-fatal */ }
  }, [sessionId, imageCache])

  /** Navigate to an arbitrary node — fetches fresh tree + image from server. */
  const navigateToNode = useCallback(async (editId: string) => {
    if (!sessionId) return
    try {
      // Optimistic: show cached image immediately while request is in-flight
      const cached = imageCache[editId]
      if (cached) setCurrentImageB64(cached)

      // Fetch image and authoritative tree in parallel
      const [navRes, treeRes] = await Promise.all([
        api.navigateNode(sessionId, editId),
        api.getEditTree(sessionId),
      ])

      if (!navRes.ok) return

      // Compute leaf from fresh server tree (avoids stale-closure on local editTree)
      const freshNodes = treeRes.nodes
      const nodeMap = new Map(freshNodes.map(n => [n.edit_id, n]))
      let leaf = editId
      while (true) {
        const n = nodeMap.get(leaf)
        if (!n || n.children_ids.length === 0) break
        leaf = n.children_ids[0]
      }

      setEditTree(freshNodes)
      setActiveLeafId(leaf)
      setCurrentEditId(editId)
      setCurrentImageB64(navRes.image_b64)
      setImageCache(prev => ({ ...prev, [navRes.edit_id]: navRes.image_b64 }))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [sessionId, imageCache])

  const resumeAndSend = useCallback(async (
    originalSessionId: string,
    imageUrl: string,
    text: string,
    userNickname: string,
    _priorSteps?: { text: string; imageUrl: string | null }[],
    resumeIdx?: number,
  ) => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await api.resumeAndEdit(
        originalSessionId,
        imageUrl,
        userNickname,
        resumeIdx ?? 0,
        text,
      )

      setSessionId(res.session_id)
      setNickname(userNickname)
      setCurrentImageB64(res.result_image_b64 ?? res.original_image_b64)

      const tree = await api.getEditTree(res.session_id)
      setEditTree(tree.nodes)
      setRootEditId(tree.root_edit_id)
      setCurrentEditId(tree.current_edit_id)
      setActiveLeafId(tree.current_edit_id)

      const cache: Record<string, string> = {}
      if (tree.root_edit_id) cache[tree.root_edit_id] = res.original_image_b64
      if (tree.current_edit_id && res.result_image_b64) {
        cache[tree.current_edit_id] = res.result_image_b64
      }
      setImageCache(cache)

      const now = new Date().toISOString()
      const userMsg: api.ChatMessage = { role: 'user', content: text, timestamp: now }
      const assistantMsg: api.ChatMessage = { role: 'assistant', content: res.chat_message, timestamp: now }
      setChatHistory([userMsg, assistantMsg])
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setIsLoading(false)
    }
  }, [])

  const saveImage = useCallback(async () => {
    if (!sessionId || !currentImageB64) return
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
    setCurrentEditId(null)
    setActiveLeafId(null)
    setEditTree([])
    setRootEditId(null)
    setImageCache({})
    setChatHistory([])
    setError(null)
    setRecommendations([])
    setIsLoadingRecommendations(false)
  }, [])

  return {
    sessionId,
    nickname,
    currentImageB64,
    currentEditId,
    activeLeafId,
    history,
    editTree,
    rootEditId,
    chatHistory,
    isLoading,
    error,
    recommendations,
    isLoadingRecommendations,
    uploadImage,
    generateFromText,
    sendMessage,
    resumeAndSend,
    setCursorTo,
    moveCursorTo,
    navigateToNode,
    saveImage,
    resetSession,
  }
}
