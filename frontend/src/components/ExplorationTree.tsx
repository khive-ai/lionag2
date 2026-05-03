import { useState } from 'react'
import type { ExplorationNode, NodeStatus } from '../types'

function StatusIcon({ status }: { status: NodeStatus }) {
  switch (status) {
    case 'pending':
      return <span className="text-stone-400 w-3 text-center flex-shrink-0">○</span>
    case 'active':
      return <span className="text-amber-600 w-3 text-center flex-shrink-0 animate-pulse">◉</span>
    case 'complete':
      return <span className="text-emerald-600 w-3 text-center flex-shrink-0">●</span>
    case 'pruned':
      return <span className="text-stone-400 w-3 text-center flex-shrink-0">✗</span>
  }
}

interface TreeNodeProps {
  node: ExplorationNode
  allNodes: Record<string, ExplorationNode>
  selectedId: string | null
  onSelect: (id: string) => void
  depth: number
}

function hasActiveDescendant(node: ExplorationNode, allNodes: Record<string, ExplorationNode>): boolean {
  if (node.status === 'active') return true
  return node.children.some((id) => {
    const child = allNodes[id]
    return child ? hasActiveDescendant(child, allNodes) : false
  })
}

function TreeNode({ node, allNodes, selectedId, onSelect, depth }: TreeNodeProps) {
  const children = node.children.map((id) => allNodes[id]).filter(Boolean)
  const isSelected = node.id === selectedId
  const isPruned = node.status === 'pruned'
  const isOnActivePath = hasActiveDescendant(node, allNodes) || node.status === 'active'
  const defaultExpanded = depth < 1 || isOnActivePath || isSelected
  const [expanded, setExpanded] = useState(defaultExpanded)

  return (
    <div>
      <button
        type="button"
        onClick={() => onSelect(node.id)}
        className={`w-full text-left flex items-center gap-1.5 py-1.5 pr-2 text-xs font-mono
          transition-colors rounded
          ${isSelected ? 'bg-indigo-100 text-indigo-900' : 'text-stone-700 hover:bg-stone-100'}`}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        {children.length > 0 ? (
          <span
            onClick={(e) => {
              e.stopPropagation()
              setExpanded((v) => !v)
            }}
            className="text-stone-400 w-3 flex-shrink-0 cursor-pointer hover:text-stone-700"
          >
            {expanded ? '▾' : '▸'}
          </span>
        ) : (
          <span className="w-3 flex-shrink-0" />
        )}
        <StatusIcon status={node.status} />
        <span className={`truncate flex-1 ${isPruned ? 'line-through text-stone-400' : ''}`}>
          {node.topic}
        </span>
        {node.findings.length > 0 && (
          <span className="text-stone-500 text-[10px] flex-shrink-0 ml-1">
            {node.findings.length}
          </span>
        )}
        {!expanded && children.length > 0 && (
          <span className="text-stone-500 text-[10px] flex-shrink-0 bg-stone-100 px-1 rounded">
            +{children.length}
          </span>
        )}
      </button>
      {expanded && children.map((child) => (
        <TreeNode
          key={child.id}
          node={child}
          allNodes={allNodes}
          selectedId={selectedId}
          onSelect={onSelect}
          depth={depth + 1}
        />
      ))}
    </div>
  )
}

interface ExplorationTreeProps {
  nodes: Record<string, ExplorationNode>
  rootId: string | null
  selectedId: string | null
  onSelect: (id: string) => void
}

export function ExplorationTree({ nodes, rootId, selectedId, onSelect }: ExplorationTreeProps) {
  const rootNode = rootId ? nodes[rootId] : null

  if (!rootNode) {
    return (
      <div className="flex items-center justify-center h-full p-4">
        <div className="text-center">
          <div className="text-stone-400 text-xs font-mono mb-1">no exploration</div>
          <div className="text-stone-400 text-[11px]">enter a topic above</div>
        </div>
      </div>
    )
  }

  return (
    <div className="overflow-y-auto h-full p-2">
      <TreeNode node={rootNode} allNodes={nodes} selectedId={selectedId} onSelect={onSelect} depth={0} />
    </div>
  )
}
