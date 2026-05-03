import type { ExplorationState, RunStatus } from '../types'

const STATUS_DOT: Record<RunStatus, string> = {
  idle: 'bg-stone-300',
  exploring: 'bg-amber-500 animate-pulse',
  cross_checking: 'bg-amber-500 animate-pulse',
  synthesizing: 'bg-indigo-500 animate-pulse',
  self_correcting: 'bg-violet-500 animate-pulse',
  done: 'bg-emerald-500',
  error: 'bg-red-500',
}

const STATUS_COLOR: Record<RunStatus, string> = {
  idle: 'text-stone-500',
  exploring: 'text-amber-700',
  cross_checking: 'text-amber-700',
  synthesizing: 'text-indigo-700',
  self_correcting: 'text-violet-700',
  done: 'text-emerald-700',
  error: 'text-red-600',
}

const STATUS_LABEL: Record<RunStatus, string> = {
  idle: 'ready',
  exploring: 'exploring',
  cross_checking: 'cross-checking',
  synthesizing: 'synthesizing',
  self_correcting: 'self-correcting',
  done: 'done',
  error: 'error',
}

export function StatusBar({ state }: { state: ExplorationState }) {
  const { status, nodes, elapsedS, errorMessage } = state
  const nodeList = Object.values(nodes)
  const totalNodes = nodeList.length
  const totalFindings = nodeList.reduce((s, n) => s + n.findings.length, 0)
  const totalSpawned = nodeList.reduce((s, n) => s + n.children.length, 0)
  const maxDepth = nodeList.reduce((m, n) => Math.max(m, n.depth), 0)
  const activeNode = nodeList.find((n) => n.status === 'active')

  return (
    <div className="border-t border-stone-200 bg-white px-4 py-2 flex items-center gap-3 text-xs font-mono flex-shrink-0">
      <div className="flex items-center gap-2">
        <span className={`w-2 h-2 rounded-full flex-shrink-0 ${STATUS_DOT[status]}`} />
        <span className={STATUS_COLOR[status]}>{STATUS_LABEL[status]}</span>
      </div>

      {totalNodes > 0 && (
        <>
          <span className="text-stone-300">│</span>
          <span className="text-stone-500">
            depth <span className="text-stone-800">{activeNode ? activeNode.depth : maxDepth}</span>
          </span>
          <span className="text-stone-300">│</span>
          <span className="text-stone-500">
            <span className="text-stone-800">{totalNodes}</span> nodes
          </span>
          <span className="text-stone-300">│</span>
          <span className="text-stone-500">
            <span className="text-stone-800">{totalFindings}</span> findings
          </span>
          {totalSpawned > 0 && (
            <>
              <span className="text-stone-300">│</span>
              <span className="text-stone-500">
                <span className="text-stone-800">{totalSpawned}</span> spawned
              </span>
            </>
          )}
        </>
      )}

      {elapsedS > 0 && (
        <>
          <span className="text-stone-300">│</span>
          <span className="text-stone-500">
            <span className="text-stone-800">{elapsedS}</span>s
          </span>
        </>
      )}

      {state.pdfPath && (
        <>
          <span className="text-stone-300">│</span>
          <a href={`file://${state.pdfPath}`} target="_blank" rel="noreferrer" className="text-indigo-700 hover:underline">
            paper.pdf
          </a>
        </>
      )}

      {errorMessage && (
        <>
          <span className="text-stone-300">│</span>
          <span className="text-red-600 truncate max-w-xs">{errorMessage}</span>
        </>
      )}
    </div>
  )
}
