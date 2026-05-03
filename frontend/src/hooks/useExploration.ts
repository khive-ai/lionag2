import { useState, useCallback, useRef } from 'react'
import type {
  ExplorationState,
  ExplorationNode,
  SSEEvent,
  AgentRoleConfig,
} from '../types'

const INITIAL_STATE: ExplorationState = {
  status: 'idle',
  nodes: {},
  rootId: null,
  selectedNodeId: null,
  synthesis: '',
  revised: '',
  corrections: '',
  paperSections: {},
  pdfPath: null,
  quality: null,
  elapsedS: 0,
  startTime: 0,
}

function makeNode(
  id: string,
  topic: string,
  depth: number,
  parent_id: string | null,
): ExplorationNode {
  return {
    id,
    topic,
    depth,
    parent_id,
    status: 'pending',
    findings: [],
    code_blocks: [],
    children: [],
    agent_log: [],
    events: [],
  }
}

function parseSSEChunk(chunk: string): SSEEvent[] {
  const events: SSEEvent[] = []
  const blocks = chunk.split(/\n\n+/)
  for (const block of blocks) {
    const lines = block.split('\n')
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const json = line.slice(6).trim()
        if (!json) continue
        try {
          const parsed = JSON.parse(json)
          events.push(parsed as SSEEvent)
        } catch {
          // skip malformed
        }
      }
    }
  }
  return events
}

function appendEvent(node: ExplorationNode, evt: ExplorationNode['events'][number]): ExplorationNode {
  return { ...node, events: [...node.events, evt] }
}

function applyEvent(prev: ExplorationState, event: SSEEvent): ExplorationState {
  switch (event.type) {
    case 'tree_init': {
      const root = makeNode(event.root_id, event.topic, 0, null)
      return {
        ...prev,
        status: 'exploring',
        nodes: { [event.root_id]: root },
        rootId: event.root_id,
        selectedNodeId: event.root_id,
      }
    }

    case 'node_active': {
      const existing = prev.nodes[event.node_id]
      const updated: ExplorationNode = existing
        ? { ...existing, status: 'active', topic: event.topic }
        : makeNode(event.node_id, event.topic, event.depth, null)
      updated.status = 'active'
      return {
        ...prev,
        nodes: { ...prev.nodes, [event.node_id]: updated },
        selectedNodeId: prev.selectedNodeId ?? event.node_id,
      }
    }

    case 'node_recall': {
      const node = prev.nodes[event.node_id]
      if (!node) return prev
      return {
        ...prev,
        nodes: {
          ...prev.nodes,
          [event.node_id]: { ...node, agent_log: [...node.agent_log, `recall: ${event.recalled}`] },
        },
      }
    }

    case 'team_active': {
      const node = prev.nodes[event.node_id]
      if (!node) return prev
      return {
        ...prev,
        nodes: { ...prev.nodes, [event.node_id]: { ...node, agents: event.agents } },
      }
    }

    case 'agent_message': {
      const node = prev.nodes[event.node_id]
      if (!node) return prev
      return {
        ...prev,
        nodes: {
          ...prev.nodes,
          [event.node_id]: appendEvent(node, {
            ts: event.timestamp,
            agent: event.agent,
            kind: 'message',
            content: event.content,
          }),
        },
      }
    }

    case 'tool_call': {
      const node = prev.nodes[event.node_id]
      if (!node) return prev
      return {
        ...prev,
        nodes: {
          ...prev.nodes,
          [event.node_id]: appendEvent(node, {
            ts: event.timestamp,
            agent: event.agent,
            kind: 'tool_call',
            tool: event.tool,
            args: event.args,
          }),
        },
      }
    }

    case 'tool_result': {
      const node = prev.nodes[event.node_id]
      if (!node) return prev
      return {
        ...prev,
        nodes: {
          ...prev.nodes,
          [event.node_id]: appendEvent(node, {
            ts: event.timestamp,
            agent: event.agent,
            kind: 'tool_result',
            output: event.output,
          }),
        },
      }
    }

    case 'speaker_change': {
      const node = prev.nodes[event.node_id]
      if (!node) return prev
      return {
        ...prev,
        nodes: {
          ...prev.nodes,
          [event.node_id]: appendEvent(node, {
            ts: event.timestamp,
            agent: '',
            kind: 'speaker_change',
            content: event.info,
          }),
        },
      }
    }

    case 'finding': {
      const node = prev.nodes[event.node_id]
      if (!node) return prev
      return {
        ...prev,
        nodes: {
          ...prev.nodes,
          [event.node_id]: {
            ...node,
            findings: [...node.findings, { claim: event.claim, evidence: event.evidence }],
          },
        },
      }
    }

    case 'code_start': {
      const node = prev.nodes[event.node_id]
      if (!node) return prev
      return {
        ...prev,
        nodes: {
          ...prev.nodes,
          [event.node_id]: {
            ...node,
            code_blocks: [...node.code_blocks, { code: event.code, output: '', exit_code: -1 }],
          },
        },
      }
    }

    case 'code_result': {
      const node = prev.nodes[event.node_id]
      if (!node || node.code_blocks.length === 0) return prev
      const blocks = [...node.code_blocks]
      blocks[blocks.length - 1] = {
        ...blocks[blocks.length - 1],
        output: event.output,
        exit_code: event.exit_code,
      }
      return {
        ...prev,
        nodes: { ...prev.nodes, [event.node_id]: { ...node, code_blocks: blocks } },
      }
    }

    case 'child_spawned': {
      const parent = prev.nodes[event.parent_id]
      const child = makeNode(event.child_id, event.question, event.depth, event.parent_id)
      const updatedParent = parent
        ? { ...parent, children: [...parent.children, event.child_id] }
        : parent
      return {
        ...prev,
        nodes: {
          ...prev.nodes,
          ...(updatedParent ? { [event.parent_id]: updatedParent } : {}),
          [event.child_id]: child,
        },
      }
    }

    case 'node_complete': {
      const node = prev.nodes[event.node_id]
      if (!node) return prev
      return {
        ...prev,
        nodes: { ...prev.nodes, [event.node_id]: { ...node, status: 'complete' } },
      }
    }

    case 'node_pruned': {
      const node = prev.nodes[event.node_id]
      if (!node) return prev
      return {
        ...prev,
        nodes: {
          ...prev.nodes,
          [event.node_id]: {
            ...node,
            status: 'pruned',
            agent_log: [...node.agent_log, `pruned: ${event.reason}`],
          },
        },
      }
    }

    case 'node_error': {
      const node = prev.nodes[event.node_id]
      if (!node) return prev
      return {
        ...prev,
        nodes: {
          ...prev.nodes,
          [event.node_id]: { ...node, agent_log: [...node.agent_log, `error: ${event.error}`] },
        },
      }
    }

    case 'node_searching': {
      const snode = prev.nodes[event.node_id]
      if (!snode) return prev
      return {
        ...prev,
        nodes: {
          ...prev.nodes,
          [event.node_id]: { ...snode, agent_log: [...snode.agent_log, 'team starting...'] },
        },
      }
    }

    case 'pivot': {
      const pnode = prev.nodes[event.node_id]
      if (!pnode) return prev
      return {
        ...prev,
        nodes: {
          ...prev.nodes,
          [event.node_id]: { ...pnode, agent_log: [...pnode.agent_log, `PIVOT: ${event.pivot}`] },
        },
      }
    }

    case 'paper_part': {
      const sections = { ...prev.paperSections }
      sections[event.section] = (sections[event.section] ?? 0) + 1
      return { ...prev, paperSections: sections }
    }

    case 'cross_check_start':
      return { ...prev, status: 'cross_checking' as ExplorationState['status'] }

    case 'pdf_ready':
      return { ...prev, pdfPath: event.path || null }

    case 'cross_check':
      return { ...prev, corrections: event.corrections }

    case 'synthesis_start':
      return { ...prev, status: 'synthesizing' }

    case 'synthesis':
      return { ...prev, synthesis: prev.synthesis + event.text }

    case 'self_correct_start':
      return { ...prev, status: 'self_correcting' }

    case 'self_correct':
      return { ...prev, revised: event.revised }

    case 'quality_eval':
      return { ...prev, quality: event.metrics }

    case 'exploration_done':
      return { ...prev, status: 'done', pdfPath: event.pdf_path ?? prev.pdfPath }

    case 'error':
      return { ...prev, status: 'error', errorMessage: event.message }

    default:
      return prev
  }
}

export interface RunOptions {
  topic: string
  maxDepth?: number
  maxConcurrent?: number
  agents?: AgentRoleConfig[]
}

export function useExploration() {
  const [state, setState] = useState<ExplorationState>(INITIAL_STATE)
  const abortRef = useRef<AbortController | null>(null)
  const startTimeRef = useRef<number>(0)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const stopTimer = () => {
    if (timerRef.current !== null) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
  }

  const selectNode = useCallback((nodeId: string) => {
    setState((prev) => ({ ...prev, selectedNodeId: nodeId }))
  }, [])

  const consumeStream = async (response: Response) => {
    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let terminal = false

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        const boundary = buffer.lastIndexOf('\n\n')
        if (boundary === -1) continue

        const processable = buffer.slice(0, boundary + 2)
        buffer = buffer.slice(boundary + 2)

        const parsed = parseSSEChunk(processable)
        for (const event of parsed) {
          setState((prev) => applyEvent(prev, event))
          if (event.type === 'exploration_done' || event.type === 'error') {
            stopTimer()
            terminal = true
          }
        }
      }

      if (buffer.trim()) {
        const parsed = parseSSEChunk(buffer)
        for (const event of parsed) {
          setState((prev) => applyEvent(prev, event))
          if (event.type === 'exploration_done' || event.type === 'error') {
            stopTimer()
            terminal = true
          }
        }
      }
    } finally {
      reader.releaseLock()
      if (!terminal) stopTimer()
    }
  }

  const runExplore = useCallback(async (opts: RunOptions) => {
    if (abortRef.current) {
      abortRef.current.abort()
    }

    const controller = new AbortController()
    abortRef.current = controller
    startTimeRef.current = Date.now()

    setState({ ...INITIAL_STATE, status: 'exploring', startTime: startTimeRef.current })

    stopTimer()
    timerRef.current = setInterval(() => {
      setState((prev) =>
        prev.status !== 'done' && prev.status !== 'error' && prev.status !== 'idle'
          ? { ...prev, elapsedS: Math.round((Date.now() - startTimeRef.current) / 1000) }
          : prev,
      )
    }, 1000)

    try {
      const body: Record<string, unknown> = {
        topic: opts.topic,
        max_depth: opts.maxDepth ?? 2,
        max_concurrent: opts.maxConcurrent ?? 2,
      }
      if (opts.agents && opts.agents.length > 0) body.agents = opts.agents

      const response = await fetch(`${import.meta.env.VITE_API_URL ?? ''}/api/explore`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal,
      })

      if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`)

      await consumeStream(response)
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') return
      setState((prev) => ({
        ...prev,
        status: 'error',
        errorMessage: err instanceof Error ? err.message : 'Unknown error',
      }))
    } finally {
      stopTimer()
    }
  }, [])

  const reset = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
    }
    stopTimer()
    setState(INITIAL_STATE)
  }, [])

  return { state, runExplore, selectNode, reset }
}
