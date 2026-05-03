import { useMemo } from 'react'
import type { ExplorationState, ExplorationNode, AgentEvent } from '../types'

interface SourceRow {
  url: string
  title: string
  agent: string
  node: string
}

function extractUrls(events: AgentEvent[]): SourceRow[] {
  const out: SourceRow[] = []
  const seen = new Set<string>()
  for (const e of events) {
    const text = e.kind === 'tool_result' ? e.output ?? '' : e.kind === 'message' ? e.content ?? '' : ''
    if (!text) continue
    const matches = text.matchAll(/https?:\/\/[^\s)\]>"']+/gi)
    for (const m of matches) {
      const url = m[0].replace(/[).,;]+$/, '')
      if (seen.has(url)) continue
      seen.add(url)
      // Try to find a nearby title — look at the start of the line
      const lineStart = text.lastIndexOf('\n', m.index) + 1
      const lineEnd = text.indexOf('\n', m.index)
      const line = text.slice(lineStart, lineEnd === -1 ? undefined : lineEnd)
      const titleMatch = line.match(/^[-*]?\s*([^|]{5,200}?)(?:\s*[|:].*)?$/)
      const title = titleMatch ? titleMatch[1].trim() : url
      out.push({ url, title, agent: e.agent || '?', node: '' })
    }
  }
  return out
}

interface Props {
  state: ExplorationState
}

export function ResearchReport({ state }: Props) {
  const stats = useMemo(() => {
    const allEvents: AgentEvent[] = []
    const toolCounts: Record<string, number> = {}
    let totalCode = 0
    let totalAgentMessages = 0
    const nodesByStatus: Record<string, number> = {}
    for (const node of Object.values(state.nodes) as ExplorationNode[]) {
      nodesByStatus[node.status] = (nodesByStatus[node.status] ?? 0) + 1
      totalCode += node.code_blocks.length
      for (const e of node.events) {
        allEvents.push(e)
        if (e.kind === 'tool_call' && e.tool) {
          const t = e.tool.replace(/^_/, '')
          toolCounts[t] = (toolCounts[t] ?? 0) + 1
        }
        if (e.kind === 'message') totalAgentMessages++
      }
    }
    const sources = extractUrls(allEvents)
    return {
      nodes: Object.keys(state.nodes).length,
      nodesByStatus,
      totalAgentMessages,
      toolCounts,
      totalCode,
      sources,
    }
  }, [state.nodes])

  if (stats.nodes === 0) return null

  return (
    <div className="border border-stone-200 rounded-lg bg-white">
      <div className="px-4 py-2 border-b border-stone-200 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-stone-800">Research process report</h3>
        {state.pdfPath && (
          <a
            href={`file://${state.pdfPath}`}
            target="_blank"
            rel="noreferrer"
            className="text-xs text-indigo-700 hover:underline"
          >
            open PDF
          </a>
        )}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 px-4 py-3 border-b border-stone-200">
        <Stat label="Exploration nodes" value={stats.nodes} sublabel={
          Object.entries(stats.nodesByStatus).map(([k, v]) => `${k}:${v}`).join(' · ')
        } />
        <Stat label="Agent turns" value={stats.totalAgentMessages} />
        <Stat label="Code executions" value={stats.totalCode} />
        <Stat label="Sources collected" value={stats.sources.length} />
        <Stat label="Elapsed" value={`${state.elapsedS}s`} />
        {state.quality && (
          <>
            <Stat label="Citations counted" value={state.quality.citation_count} />
            <Stat label="Evidence quality" value={state.quality.evidence_quality.toFixed(2)} />
            <Stat label="Verdict" value={state.quality.verdict} />
          </>
        )}
      </div>

      {Object.keys(stats.toolCounts).length > 0 && (
        <div className="px-4 py-3 border-b border-stone-200">
          <div className="text-[11px] text-stone-500 uppercase tracking-wider mb-1">Tool calls</div>
          <div className="flex flex-wrap gap-2">
            {Object.entries(stats.toolCounts)
              .sort((a, b) => b[1] - a[1])
              .map(([tool, count]) => (
                <span
                  key={tool}
                  className="text-xs font-mono px-2 py-0.5 rounded bg-stone-100 border border-stone-200 text-stone-700"
                >
                  {tool} <span className="text-stone-500">×{count}</span>
                </span>
              ))}
          </div>
        </div>
      )}

      {stats.sources.length > 0 && (
        <div className="px-4 py-3">
          <div className="text-[11px] text-stone-500 uppercase tracking-wider mb-1">
            Sources ({stats.sources.length})
          </div>
          <ul className="space-y-1 max-h-60 overflow-y-auto">
            {stats.sources.map((s, i) => (
              <li key={i} className="text-xs text-stone-700 leading-snug">
                <span className="text-stone-400 font-mono">[{i + 1}]</span>{' '}
                <a
                  href={s.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-indigo-700 hover:underline break-all"
                >
                  {s.title === s.url ? s.url : s.title}
                </a>
                {s.title !== s.url && (
                  <div className="ml-6 text-[10px] text-stone-400 break-all">{s.url}</div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function Stat({ label, value, sublabel }: { label: string; value: number | string; sublabel?: string }) {
  return (
    <div>
      <div className="text-[10px] text-stone-500 uppercase tracking-wider">{label}</div>
      <div className="text-lg font-semibold text-stone-900">{value}</div>
      {sublabel && <div className="text-[10px] text-stone-400 font-mono">{sublabel}</div>}
    </div>
  )
}
