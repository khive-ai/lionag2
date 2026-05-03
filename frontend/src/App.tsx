import { useEffect, useState } from 'react'
import { useExploration } from './hooks/useExploration'
import { ExplorationTree } from './components/ExplorationTree'
import { NodeWorkspace } from './components/NodeWorkspace'
import { StatusBar } from './components/StatusBar'
import { AgentConfigEditor } from './components/AgentConfigEditor'
import { ResearchReport } from './components/ResearchReport'
import type { AgentRoleConfig } from './types'

const DEFAULT_AGENTS: AgentRoleConfig[] = [
  {
    name: 'Surveyor',
    role: 'Literature researcher',
    tools: ['tavily_search', 'fetch_url', 'memory_recall', 'graph_search', 'list_messages'],
    system_prompt: '',
  },
  {
    name: 'Analyst',
    role: 'Quantitative analyst',
    tools: ['tavily_search', 'fetch_url', 'run_code', 'memory_recall', 'memory_remember', 'graph_add_entity', 'graph_add_link'],
    system_prompt: '',
  },
  {
    name: 'Critic',
    role: 'Research critic',
    tools: ['tavily_search', 'fetch_url', 'memory_recall', 'graph_neighbors', 'send_message'],
    system_prompt: '',
  },
]

export default function App() {
  const { state, runExplore, selectNode } = useExploration()
  const [topic, setTopic] = useState('')
  const [maxDepth, setMaxDepth] = useState(2)
  const [maxConcurrent, setMaxConcurrent] = useState(8)
  const [agents, setAgents] = useState<AgentRoleConfig[]>(DEFAULT_AGENTS)
  const [editorOpen, setEditorOpen] = useState(false)
  const [view, setView] = useState<'workspace' | 'report'>('workspace')

  const isRunning = state.status === 'exploring' || state.status === 'cross_checking' || state.status === 'synthesizing' || state.status === 'self_correcting'
  const showSynthesis = state.synthesis.length > 0

  // Fetch the live default config from the server so prompts match exactly
  useEffect(() => {
    let cancelled = false
    fetch(`${import.meta.env.VITE_API_URL ?? ''}/api/explore/config`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (cancelled || !d?.agents) return
        setAgents(d.agents as AgentRoleConfig[])
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])

  const handleExplore = () => {
    const trimmed = topic.trim()
    if (!trimmed || isRunning) return
    runExplore({ topic: trimmed, maxDepth, maxConcurrent, agents })
  }

  const selectedNode = state.selectedNodeId ? state.nodes[state.selectedNodeId] : null

  return (
    <div className="flex flex-col h-screen bg-stone-50 text-stone-900 overflow-hidden">
      {/* Header */}
      <header className="flex items-center gap-2 px-4 py-3 border-b border-stone-200 bg-white flex-shrink-0">
        <span className="font-mono text-sm select-none">
          <span className="text-stone-400">lion</span>
          <span className="text-indigo-700 font-semibold">ag2</span>
        </span>
        <div className="w-px h-4 bg-stone-200 flex-shrink-0" />

        <input
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleExplore()}
          placeholder="Research question..."
          disabled={isRunning}
          className="flex-1 bg-white border border-stone-300 text-sm rounded px-3 py-1.5 focus:outline-none focus:border-indigo-500 placeholder:text-stone-400 disabled:opacity-50"
        />

        <label className="text-xs text-stone-600 flex items-center gap-1">
          depth
          <input
            type="number"
            min={1}
            max={6}
            value={maxDepth}
            onChange={(e) => setMaxDepth(Math.max(1, Math.min(6, parseInt(e.target.value) || 1)))}
            disabled={isRunning}
            className="w-12 text-sm border border-stone-300 rounded px-2 py-1 focus:outline-none focus:border-indigo-500"
          />
        </label>
        <label className="text-xs text-stone-600 flex items-center gap-1">
          parallel
          <input
            type="number"
            min={1}
            max={16}
            value={maxConcurrent}
            onChange={(e) => setMaxConcurrent(Math.max(1, Math.min(16, parseInt(e.target.value) || 1)))}
            disabled={isRunning}
            className="w-12 text-sm border border-stone-300 rounded px-2 py-1 focus:outline-none focus:border-indigo-500"
          />
        </label>

        <button
          onClick={() => setEditorOpen(true)}
          disabled={isRunning}
          className="text-xs px-3 py-1.5 rounded border border-stone-300 hover:bg-stone-50 text-stone-700 disabled:opacity-50"
        >
          agents ({agents.length})
        </button>

        <button
          type="button"
          onClick={handleExplore}
          disabled={isRunning || !topic.trim()}
          className="px-4 py-1.5 text-xs font-semibold bg-indigo-700 text-white rounded hover:bg-indigo-800 disabled:opacity-40 flex-shrink-0"
        >
          {isRunning ? state.status + '...' : 'explore'}
        </button>
      </header>

      <main className="flex flex-1 overflow-hidden">
        {/* Left: tree */}
        <aside className="w-[24%] flex-shrink-0 border-r border-stone-200 flex flex-col overflow-hidden bg-white">
          <div className="px-3 py-2 border-b border-stone-200 flex-shrink-0">
            <span className="text-[10px] font-mono text-stone-500 uppercase tracking-wider">
              exploration tree
            </span>
          </div>
          <div className="flex-1 overflow-hidden">
            <ExplorationTree
              nodes={state.nodes}
              rootId={state.rootId}
              selectedId={state.selectedNodeId}
              onSelect={selectNode}
            />
          </div>
        </aside>

        {/* Right: workspace + report toggle */}
        <section className="flex-1 overflow-hidden flex flex-col bg-stone-50">
          <div className="px-3 py-2 border-b border-stone-200 flex items-center gap-2 bg-white">
            <button
              onClick={() => setView('workspace')}
              className={`text-xs px-3 py-1 rounded ${
                view === 'workspace' ? 'bg-indigo-100 text-indigo-700 font-medium' : 'text-stone-600 hover:bg-stone-100'
              }`}
            >
              workspace
            </button>
            <button
              onClick={() => setView('report')}
              className={`text-xs px-3 py-1 rounded ${
                view === 'report' ? 'bg-indigo-100 text-indigo-700 font-medium' : 'text-stone-600 hover:bg-stone-100'
              }`}
            >
              report{showSynthesis ? ' • paper ready' : ''}
            </button>
            {selectedNode && view === 'workspace' && (
              <span
                className={`ml-auto text-[10px] font-mono px-1.5 py-0.5 rounded ${
                  selectedNode.status === 'active'
                    ? 'text-amber-700 bg-amber-100'
                    : selectedNode.status === 'complete'
                    ? 'text-emerald-700 bg-emerald-100'
                    : 'text-stone-500 bg-stone-100'
                }`}
              >
                {selectedNode.status}
              </span>
            )}
          </div>
          <div className="flex-1 overflow-hidden flex flex-col">
            {view === 'workspace' ? (
              <NodeWorkspace
                node={selectedNode}
                allNodes={state.nodes}
                synthesis={state.synthesis}
                showSynthesis={showSynthesis}
                revised={state.revised}
              />
            ) : (
              <div className="flex-1 overflow-y-auto p-4 space-y-3">
                <ResearchReport state={state} />
                {state.synthesis && (
                  <PaperPanel title="Synthesis (markdown)" text={state.synthesis} />
                )}
                {state.revised && state.revised !== state.synthesis && (
                  <PaperPanel title="Self-corrected revision" text={state.revised} />
                )}
                {state.corrections && (
                  <PaperPanel title="Cross-section corrections" text={state.corrections} mono />
                )}
              </div>
            )}
          </div>
        </section>
      </main>

      <StatusBar state={state} />

      <AgentConfigEditor
        open={editorOpen}
        initialAgents={agents}
        onClose={() => setEditorOpen(false)}
        onSave={(next) => setAgents(next)}
      />
    </div>
  )
}

function PaperPanel({ title, text, mono }: { title: string; text: string; mono?: boolean }) {
  return (
    <div className="border border-stone-200 rounded-lg bg-white">
      <div className="px-4 py-2 border-b border-stone-200">
        <h3 className="text-sm font-semibold text-stone-800">{title}</h3>
      </div>
      <pre
        className={`px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap break-words ${
          mono ? 'font-mono text-xs text-stone-700' : 'text-stone-800'
        }`}
        style={{ fontFamily: mono ? undefined : 'Georgia, serif' }}
      >
        {text}
      </pre>
    </div>
  )
}
