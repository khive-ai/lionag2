export type NodeStatus = 'pending' | 'active' | 'complete' | 'pruned'

export interface Citation {
  title: string
  authors?: string
  year?: string
  url?: string
  relevance?: string
}

export interface Finding {
  claim: string
  evidence: string
  citations?: Citation[]
  novelty?: string
  confidence?: number
  code_ref?: string | null
  spawned_child?: string
}

export interface CodeBlock {
  code: string
  output: string
  exit_code: number
}

export interface AgentEvent {
  ts: number
  agent: string
  kind: 'message' | 'tool_call' | 'tool_result' | 'speaker_change'
  content?: string
  tool?: string
  args?: string
  output?: string
}

export interface ExplorationNode {
  id: string
  topic: string
  depth: number
  parent_id: string | null
  status: NodeStatus
  findings: Finding[]
  code_blocks: CodeBlock[]
  children: string[]
  agent_log: string[]
  agents?: { name: string; role: string; tools: string[] }[]
  events: AgentEvent[]
}

export interface AgentRoleConfig {
  name: string
  role: string
  tools: string[]
  system_prompt: string
}

export interface QualityMetrics {
  citation_count: number
  novelty_score: number
  evidence_quality: number
  contradiction_count: number
  correction_count: number
  coverage_score: number
  paper_completeness: number
  verdict: string
}

export type SSEEvent =
  | { type: 'tree_init'; root_id: string; topic: string; max_depth: number; timestamp: number }
  | { type: 'node_active'; node_id: string; topic: string; depth: number; timestamp: number }
  | { type: 'node_recall'; node_id: string; recalled: string; timestamp: number }
  | { type: 'team_active'; node_id: string; agents: { name: string; role: string; tools: string[] }[]; timestamp: number }
  | { type: 'agent_message'; node_id: string; agent: string; content: string; timestamp: number }
  | { type: 'tool_call'; node_id: string; agent: string; tool: string; args: string; timestamp: number }
  | { type: 'tool_result'; node_id: string; agent: string; output: string; timestamp: number }
  | { type: 'speaker_change'; node_id: string; info: string; timestamp: number }
  | { type: 'finding'; node_id: string; claim: string; evidence: string; timestamp: number }
  | { type: 'code_start'; node_id: string; code: string; purpose?: string; timestamp: number }
  | { type: 'code_result'; node_id: string; output: string; exit_code: number; timestamp: number }
  | { type: 'child_spawned'; parent_id: string; child_id: string; question: string; novelty_score: number; depth: number; timestamp: number }
  | { type: 'node_complete'; node_id: string; finding_count: number; children_count: number; timestamp: number }
  | { type: 'node_pruned'; node_id: string; question: string; reason: string; timestamp: number }
  | { type: 'node_error'; node_id: string; error: string; timestamp: number }
  | { type: 'node_searching'; node_id: string; agents?: string[]; timestamp: number }
  | { type: 'pivot'; node_id: string; pivot: string; timestamp: number }
  | { type: 'paper_part'; node_id: string; section: string; content: string; confidence: number; timestamp: number }
  | { type: 'cross_check_start'; timestamp: number }
  | { type: 'cross_check'; corrections: string; timestamp: number }
  | { type: 'synthesis_start'; timestamp: number }
  | { type: 'self_correct_start'; timestamp: number }
  | { type: 'self_correct'; revised: string; original_length: number; revised_length: number; timestamp: number }
  | { type: 'pdf_generating'; timestamp: number }
  | { type: 'pdf_ready'; path: string; error?: string; timestamp: number }
  | { type: 'synthesis'; text: string; timestamp: number }
  | { type: 'exploration_done'; total_nodes: number; total_findings: number; max_depth_reached: number; pdf_path?: string; timestamp: number }
  | { type: 'quality_eval_start'; timestamp: number }
  | { type: 'quality_eval'; metrics: QualityMetrics; timestamp: number }
  | { type: 'error'; message: string }

export type RunStatus = 'idle' | 'exploring' | 'cross_checking' | 'synthesizing' | 'self_correcting' | 'done' | 'error'

export interface ExplorationState {
  status: RunStatus
  nodes: Record<string, ExplorationNode>
  rootId: string | null
  selectedNodeId: string | null
  synthesis: string
  revised: string
  corrections: string
  paperSections: Record<string, number>
  pdfPath: string | null
  quality: QualityMetrics | null
  elapsedS: number
  startTime: number
  errorMessage?: string
}
