import React, { useEffect, useRef } from 'react'
import type { ExplorationNode, CodeBlock, Finding, AgentEvent } from '../types'

function renderMarkdown(text: string): React.ReactNode {
  const lines = text.split('\n')
  const nodes: React.ReactNode[] = []
  let bulletBuffer: string[] = []

  const flushBullets = (key: string) => {
    if (bulletBuffer.length === 0) return
    nodes.push(
      <ul key={key} className="list-disc list-inside space-y-0.5 my-1 text-stone-700">
        {bulletBuffer.map((item, i) => (
          <li key={i} className="text-sm leading-relaxed">{inlineMarkdown(item)}</li>
        ))}
      </ul>,
    )
    bulletBuffer = []
  }

  lines.forEach((line, idx) => {
    const key = String(idx)
    const headingMatch = /^#{1,3}\s+(.+)$/.exec(line)
    if (headingMatch) {
      flushBullets(`bullets-${key}`)
      nodes.push(
        <h3 key={key} className="text-sm font-semibold text-stone-900 mt-3 mb-1 border-b border-stone-200 pb-0.5">
          {headingMatch[1]}
        </h3>,
      )
      return
    }
    const bulletMatch = /^[-*]\s+(.+)$/.exec(line)
    if (bulletMatch) {
      bulletBuffer.push(bulletMatch[1])
      return
    }
    flushBullets(`bullets-${key}`)
    if (line.trim() === '') {
      nodes.push(<div key={key} className="h-1" />)
      return
    }
    nodes.push(
      <p key={key} className="text-sm text-stone-800 leading-relaxed">{inlineMarkdown(line)}</p>,
    )
  })

  flushBullets('bullets-end')
  return <>{nodes}</>
}

function inlineMarkdown(text: string): React.ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*)/)
  if (parts.length === 1) return text
  return (
    <>
      {parts.map((part, i) => {
        const boldMatch = /^\*\*([^*]+)\*\*$/.exec(part)
        if (boldMatch) return <strong key={i} className="font-semibold text-stone-900">{boldMatch[1]}</strong>
        return part
      })}
    </>
  )
}

function CodePanel({ block }: { block: CodeBlock }) {
  const pending = block.exit_code === -1
  return (
    <div className="border border-stone-300 rounded bg-white overflow-hidden">
      <div className="px-3 py-1 border-b border-stone-200 flex items-center gap-2 bg-stone-50">
        <span className="text-[11px] font-mono text-stone-500">python</span>
        {pending ? (
          <span className="text-[11px] font-mono text-amber-600 animate-pulse">running...</span>
        ) : (
          <span className={`text-[11px] font-mono ${block.exit_code === 0 ? 'text-emerald-700' : 'text-red-600'}`}>
            {block.exit_code === 0 ? '✓ exit 0' : `exit ${block.exit_code}`}
          </span>
        )}
      </div>
      <pre className="px-3 py-2 text-xs font-mono text-stone-800 bg-white overflow-x-auto whitespace-pre-wrap break-words">
        {block.code}
      </pre>
      {block.output && (
        <pre className="px-3 py-2 text-xs font-mono text-stone-700 border-t border-stone-200 bg-stone-50 overflow-x-auto whitespace-pre-wrap break-words">
          {block.output}
        </pre>
      )}
    </div>
  )
}

const AGENT_COLORS: Record<string, string> = {
  Surveyor: 'bg-sky-100 text-sky-800 border-sky-300',
  Analyst: 'bg-violet-100 text-violet-800 border-violet-300',
  Critic: 'bg-rose-100 text-rose-800 border-rose-300',
  User: 'bg-stone-100 text-stone-700 border-stone-300',
}

function ConversationTimeline({ events, isActive }: { events: AgentEvent[]; isActive: boolean }) {
  const bottomRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [events.length])

  if (events.length === 0 && !isActive) return null

  return (
    <div className="border border-stone-200 rounded overflow-hidden bg-white">
      <div className="px-3 py-1.5 border-b border-stone-200 bg-stone-50 flex items-center gap-2">
        <span className="text-[10px] font-mono text-stone-500 uppercase tracking-wider">
          conversation ({events.length})
        </span>
        {isActive && <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse flex-shrink-0" />}
      </div>
      <div className="px-3 py-2 max-h-[60vh] overflow-y-auto space-y-2">
        {events.length === 0 && isActive && (
          <div className="text-xs font-mono text-stone-400">team starting...</div>
        )}
        {events.map((e, i) => {
          if (e.kind === 'speaker_change') {
            return (
              <div key={i} className="text-[10px] font-mono text-stone-400 border-t border-dashed border-stone-200 pt-1">
                {e.content}
              </div>
            )
          }
          const colorClass = AGENT_COLORS[e.agent] ?? 'bg-stone-50 text-stone-700 border-stone-300'
          if (e.kind === 'tool_call') {
            return (
              <div key={i} className="flex gap-2">
                <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${colorClass} flex-shrink-0 self-start`}>
                  {e.agent}
                </span>
                <div className="flex-1 min-w-0 text-xs font-mono text-stone-600">
                  <span className="text-indigo-700">→ {e.tool?.replace(/^_/, '')}</span>
                  {e.args && <span className="text-stone-500"> ({e.args})</span>}
                </div>
              </div>
            )
          }
          if (e.kind === 'tool_result') {
            return (
              <div key={i} className="flex gap-2">
                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded border border-stone-200 bg-stone-50 text-stone-500 flex-shrink-0 self-start">
                  result
                </span>
                <pre className="flex-1 min-w-0 text-[11px] font-mono text-stone-600 whitespace-pre-wrap break-words bg-stone-50 px-2 py-1 rounded border border-stone-200 max-h-40 overflow-y-auto">
                  {e.output ?? ''}
                </pre>
              </div>
            )
          }
          // message
          return (
            <div key={i} className="flex gap-2">
              <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${colorClass} flex-shrink-0 self-start`}>
                {e.agent}
              </span>
              <div className="flex-1 min-w-0 text-sm text-stone-800 leading-relaxed whitespace-pre-wrap break-words">
                {e.content}
              </div>
            </div>
          )
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}

function FindingsPanel({
  findings,
  allNodes,
}: {
  findings: Finding[]
  allNodes: Record<string, ExplorationNode>
}) {
  if (findings.length === 0) return null
  return (
    <div className="border border-stone-200 rounded overflow-hidden bg-white">
      <div className="px-3 py-1.5 border-b border-stone-200 bg-stone-50">
        <span className="text-[10px] font-mono text-stone-500 uppercase tracking-wider">
          findings ({findings.length})
        </span>
      </div>
      <div className="divide-y divide-stone-100">
        {findings.map((f, i) => {
          const spawnedNode = f.spawned_child ? allNodes[f.spawned_child] : null
          return (
            <div key={i} className="px-3 py-2">
              <div className="flex items-start gap-2">
                <span className="text-stone-400 text-xs font-mono flex-shrink-0 mt-0.5">{i + 1}.</span>
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-stone-800 leading-relaxed">{f.claim}</div>
                  {f.evidence && (
                    <div className="text-xs text-stone-500 mt-1 leading-relaxed">{f.evidence}</div>
                  )}
                  <div className="flex items-center gap-2 mt-1">
                    {typeof f.confidence === 'number' && (
                      <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-stone-100 text-stone-600">
                        confidence {f.confidence.toFixed(2)}
                      </span>
                    )}
                    {f.novelty && (
                      <span className="text-[10px] font-mono text-stone-500">novelty: {f.novelty}</span>
                    )}
                  </div>
                  {f.citations && f.citations.length > 0 && (
                    <ul className="mt-1 space-y-0.5">
                      {f.citations.map((c, j) => (
                        <li key={j} className="text-[11px] text-stone-600">
                          {c.url ? (
                            <a href={c.url} target="_blank" rel="noreferrer" className="text-indigo-700 hover:underline">
                              {c.title}
                            </a>
                          ) : (
                            <span>{c.title}</span>
                          )}
                          {c.authors && <span className="text-stone-500"> — {c.authors}</span>}
                          {c.year && <span className="text-stone-500"> ({c.year})</span>}
                        </li>
                      ))}
                    </ul>
                  )}
                  {spawnedNode && (
                    <div className="mt-1 text-[11px] font-mono text-amber-700">
                      spawned → {spawnedNode.topic}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function SynthesisPanel({ text, title = 'Synthesis' }: { text: string; title?: string }) {
  return (
    <div className="border border-indigo-200 rounded-lg bg-white">
      <div className="px-4 py-2 border-b border-indigo-100 bg-indigo-50/40">
        <span className="text-sm font-semibold text-indigo-900">{title}</span>
      </div>
      <div className="px-4 py-3 space-y-1 overflow-y-auto max-h-[60vh]">
        {renderMarkdown(text)}
      </div>
    </div>
  )
}

interface NodeWorkspaceProps {
  node: ExplorationNode | null
  allNodes: Record<string, ExplorationNode>
  synthesis: string
  showSynthesis: boolean
  revised?: string
}

export function NodeWorkspace({ node, allNodes, synthesis, showSynthesis, revised }: NodeWorkspaceProps) {
  if (showSynthesis && synthesis.length > 0 && !node) {
    return (
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        <SynthesisPanel text={revised || synthesis} title={revised ? 'Self-corrected paper' : 'Synthesis'} />
      </div>
    )
  }

  if (!node) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <div className="text-stone-500 text-sm font-mono mb-1">no node selected</div>
          <div className="text-stone-400 text-xs">click a node in the tree, or run an exploration</div>
        </div>
      </div>
    )
  }

  const isActive = node.status === 'active'

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-3">
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${
              node.status === 'active' ? 'border-amber-300 text-amber-800 bg-amber-50' :
              node.status === 'complete' ? 'border-emerald-300 text-emerald-800 bg-emerald-50' :
              node.status === 'pruned' ? 'border-stone-300 text-stone-500 bg-stone-50' :
              'border-stone-300 text-stone-500 bg-stone-50'
            }`}>
              {node.status}
            </span>
            <span className="text-[10px] font-mono text-stone-500">depth {node.depth}</span>
            {node.agents && (
              <span className="text-[10px] font-mono text-stone-500">
                team: {node.agents.map(a => a.name).join(' → ')}
              </span>
            )}
          </div>
          <h2 className="text-sm font-medium text-stone-900 leading-relaxed">{node.topic}</h2>
          {node.parent_id && allNodes[node.parent_id] && (
            <div className="mt-1.5 text-[11px] font-mono text-stone-500 border-l-2 border-stone-300 pl-2">
              <span className="text-stone-400">spawned from:</span>{' '}
              <span className="text-stone-600">{allNodes[node.parent_id].topic}</span>
            </div>
          )}
        </div>
      </div>

      <ConversationTimeline events={node.events} isActive={isActive} />

      {node.code_blocks.length > 0 && (
        <div className="space-y-2">
          <div className="text-[10px] font-mono text-stone-500 uppercase tracking-wider">code executions</div>
          {node.code_blocks.map((block, i) => (
            <CodePanel key={i} block={block} />
          ))}
        </div>
      )}

      <FindingsPanel findings={node.findings} allNodes={allNodes} />

      {showSynthesis && synthesis.length > 0 && node.status !== 'active' && (
        <SynthesisPanel text={revised || synthesis} title={revised ? 'Self-corrected paper' : 'Synthesis'} />
      )}
    </div>
  )
}
