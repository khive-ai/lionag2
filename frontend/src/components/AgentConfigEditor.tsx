import { useEffect, useState } from 'react'
import type { AgentRoleConfig } from '../types'

const ALL_TOOLS = [
  'tavily_search',
  'fetch_url',
  'run_code',
  'memory_recall',
  'memory_remember',
  'graph_search',
  'graph_neighbors',
  'graph_add_entity',
  'graph_add_link',
  'list_messages',
  'send_message',
]

interface Props {
  open: boolean
  initialAgents: AgentRoleConfig[]
  onClose: () => void
  onSave: (agents: AgentRoleConfig[]) => void
}

export function AgentConfigEditor({ open, initialAgents, onClose, onSave }: Props) {
  const [agents, setAgents] = useState<AgentRoleConfig[]>(initialAgents)

  useEffect(() => {
    setAgents(initialAgents)
  }, [initialAgents])

  if (!open) return null

  const updateField = (idx: number, key: keyof AgentRoleConfig, value: string | string[]) => {
    setAgents((prev) => prev.map((a, i) => (i === idx ? { ...a, [key]: value } : a)))
  }

  const toggleTool = (idx: number, tool: string) => {
    setAgents((prev) =>
      prev.map((a, i) => {
        if (i !== idx) return a
        const tools = a.tools.includes(tool) ? a.tools.filter((t) => t !== tool) : [...a.tools, tool]
        return { ...a, tools }
      }),
    )
  }

  const addAgent = () => {
    setAgents((prev) => [
      ...prev,
      {
        name: `Agent${prev.length + 1}`,
        role: 'specialist',
        tools: ['tavily_search', 'memory_recall'],
        system_prompt: 'You are a specialist. Describe your workflow.',
      },
    ])
  }

  const removeAgent = (idx: number) => {
    setAgents((prev) => prev.filter((_, i) => i !== idx))
  }

  const moveAgent = (idx: number, dir: -1 | 1) => {
    setAgents((prev) => {
      const next = [...prev]
      const target = idx + dir
      if (target < 0 || target >= next.length) return prev
      ;[next[idx], next[target]] = [next[target], next[idx]]
      return next
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-stone-900/40 backdrop-blur-sm">
      <div className="bg-white rounded-lg shadow-xl border border-stone-200 w-[min(900px,95vw)] max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-3 border-b border-stone-200">
          <div>
            <h2 className="text-base font-semibold text-stone-900">Agent roster</h2>
            <p className="text-xs text-stone-500 mt-0.5">
              The first agent is the entry point. Each agent's <code>after_work</code> automatically chains to the next.
            </p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={addAgent}
              className="text-xs px-3 py-1.5 rounded border border-stone-300 hover:bg-stone-50 text-stone-700"
            >
              + add agent
            </button>
            <button
              onClick={() => {
                onSave(agents)
                onClose()
              }}
              className="text-xs px-3 py-1.5 rounded bg-indigo-700 text-white hover:bg-indigo-800"
            >
              save & close
            </button>
            <button
              onClick={onClose}
              className="text-xs px-3 py-1.5 rounded border border-stone-300 text-stone-600 hover:bg-stone-50"
            >
              cancel
            </button>
          </div>
        </div>

        <div className="overflow-y-auto p-4 space-y-3">
          {agents.map((a, idx) => (
            <div key={idx} className="border border-stone-200 rounded p-3 bg-stone-50/40">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-700 uppercase tracking-wider">
                  agent {idx + 1}
                  {idx === 0 ? ' • entry' : ''}
                  {idx === agents.length - 1 ? ' • terminal' : ''}
                </span>
                <button
                  onClick={() => moveAgent(idx, -1)}
                  disabled={idx === 0}
                  className="text-xs text-stone-500 disabled:opacity-30 px-1"
                >
                  ↑
                </button>
                <button
                  onClick={() => moveAgent(idx, 1)}
                  disabled={idx === agents.length - 1}
                  className="text-xs text-stone-500 disabled:opacity-30 px-1"
                >
                  ↓
                </button>
                <button
                  onClick={() => removeAgent(idx)}
                  disabled={agents.length <= 1}
                  className="ml-auto text-xs text-red-600 disabled:opacity-30 px-1"
                >
                  remove
                </button>
              </div>

              <div className="grid grid-cols-2 gap-2 mb-2">
                <label className="block">
                  <span className="text-[11px] text-stone-600 uppercase tracking-wider">name</span>
                  <input
                    value={a.name}
                    onChange={(e) => updateField(idx, 'name', e.target.value)}
                    className="mt-0.5 w-full text-sm border border-stone-300 rounded px-2 py-1 focus:outline-none focus:border-indigo-500"
                  />
                </label>
                <label className="block">
                  <span className="text-[11px] text-stone-600 uppercase tracking-wider">role</span>
                  <input
                    value={a.role}
                    onChange={(e) => updateField(idx, 'role', e.target.value)}
                    className="mt-0.5 w-full text-sm border border-stone-300 rounded px-2 py-1 focus:outline-none focus:border-indigo-500"
                  />
                </label>
              </div>

              <div className="mb-2">
                <span className="text-[11px] text-stone-600 uppercase tracking-wider">tools</span>
                <div className="mt-1 flex flex-wrap gap-1">
                  {ALL_TOOLS.map((tool) => (
                    <button
                      key={tool}
                      onClick={() => toggleTool(idx, tool)}
                      className={`text-[11px] font-mono px-2 py-0.5 rounded border transition-colors ${
                        a.tools.includes(tool)
                          ? 'border-indigo-500 bg-indigo-50 text-indigo-700'
                          : 'border-stone-300 bg-white text-stone-500 hover:border-stone-400'
                      }`}
                    >
                      {tool}
                    </button>
                  ))}
                </div>
              </div>

              <label className="block">
                <span className="text-[11px] text-stone-600 uppercase tracking-wider">system prompt</span>
                <textarea
                  value={a.system_prompt}
                  onChange={(e) => updateField(idx, 'system_prompt', e.target.value)}
                  rows={5}
                  className="mt-0.5 w-full text-xs font-mono border border-stone-300 rounded px-2 py-1 focus:outline-none focus:border-indigo-500"
                />
              </label>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
