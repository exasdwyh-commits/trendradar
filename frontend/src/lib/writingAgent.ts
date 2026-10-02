import type { Platform } from './api'

export interface AgentProposal {
  title: string; audience: string; question: string; proposition: string; gaps: string[]
  excerpts: { id: string; material_id: string; source_title?: string; fact: string; quote: string; stance: string }[]
  sections: { id: string; title: string; goal: string; target_words: number; evidence_ids: string[]; content_md: string }[]
}
interface AgentOutput {
  id: string; model: string; warnings: string[]; generated_by?: string
  output: { title?: string; content_md?: string; issues?: { quote: string; reason: string; suggestion: string }[] }
}
export interface AgentRun {
  id: string; document_id: string; revision: number; status: string; running: boolean
  state: {
    phase: string; instruction: string; platforms: Platform[]; proposal: AgentProposal | null
    drafts: (AgentOutput & { section_id: string; title: string })[]; draft_md: string
    review: AgentOutput | null; variants: (AgentOutput & { platform: Platform })[]
    warnings: string[]; error: string; model?: string
  }
}
export const AGENT_PHASES = ['planning', 'drafting', 'reviewing', 'variants']
export const AGENT_STATUS: Record<string, string> = {
  planning: '整理素材与规划', awaiting_outline: '等你确认大纲', drafting: '分节起草', reviewing: '审阅候选母稿',
  variants: '准备平台版本', awaiting_adoption: '等你审阅并采用', completed: '已采用到正文', failed: '当前步骤需要处理',
}
