export class ApiError extends Error {
  status: number
  code: string
  details: unknown
  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...init })
  const text = await res.text()
  const body = text ? JSON.parse(text) : null
  if (!res.ok) {
    const code = body?.error ?? body?.detail?.error ?? 'http_error'
    const message = body?.message ?? body?.detail?.message ?? (typeof body?.detail === 'string' ? body.detail : res.statusText)
    throw new ApiError(res.status, code, message, body?.details)
  }
  return body as T
}

export const api = {
  get: <T>(path: string, options?: Pick<RequestInit, 'signal'>) => request<T>(path, options),
  post: <T>(path: string, data?: unknown) => request<T>(path, { method: 'POST', body: data === undefined ? undefined : JSON.stringify(data) }),
  patch: <T>(path: string, data?: unknown) => request<T>(path, { method: 'PATCH', body: data === undefined ? undefined : JSON.stringify(data) }),
  del: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}

export type DataMode = 'live' | 'mock' | 'mixed'

export interface Score { score: number; reason: string; confidence: number; method: string; evidence_ids: string[] }

export interface Opportunity {
  id: string
  pain_cluster_id: string
  title: string
  description?: string | null
  target_user?: string | null
  core_pain?: string | null
  proposed_solution?: string | null
  wedge?: string | null
  monetization?: string | null
  distribution?: string | null
  build_type?: string | null
  build_difficulty?: string | null
  why_now?: string | null
  competitor_weakness?: string | null
  risks: string[]
  next_action?: string | null
  status: string
  opportunity_score: number
  confidence: number
  data_mode: DataMode
  version: number
  first_seen: string
  last_seen: string
  signal_count: number
  growth: number
  generated_by: string
  created_at?: string
  updated_at?: string
  cluster_label: string
  persona?: string | null
  category?: string | null
  stage: string
  velocity: number
  acceleration: number
  unique_users: number
  source_count: number
  scores: Record<string, Score>
  competition?: { competitor_count: number; density: number; maturity: number } | null
  pick_reason?: string
}

export interface Evidence { id: string; kind: string; signal_id?: string; product_id?: string; source_id: string; quote: string; url: string; occurred_at?: string; origin: DataMode }

export interface PainSignal {
  id: string; signal_id: string; problem: string; context?: string; severity?: number; frequency?: number; willingness_to_pay?: number
  existing_workaround?: string; current_solution?: string; friction: string[]; evidence_quote?: string; confidence: number; generated_by: string
  title: string; url: string; source_id: string; origin: DataMode; author?: string; created_at?: string; engagement: Record<string, number>
}

export interface Competitor {
  product_id: string; name: string; similarity: number; votes: number; rating?: number | null; pricing?: string | null; origin: DataMode
  url?: string; website?: string; tagline?: string; launched_at?: string; review_count?: number; pricing_origin?: string
  insights?: { pros: string[]; cons: string[]; complaints: string[]; summary?: string; derived_from: string; sample_size: number } | null
}

export interface CompetitionProfile {
  competitor_count: number; density: number; maturity: number; avg_rating?: number | null; review_volume: number; recent_launches_90d: number
  common_features: string[]; common_complaints: string[]; pricing_distribution: Record<string, number>; competitors: Competitor[]; data_mode: DataMode; computed_at: string
}

export interface OpportunityDetail extends Opportunity {
  evidence: Evidence[]
  pain_signals: PainSignal[]
  competition?: CompetitionProfile | null
  status_log: { from_status?: string; to_status: string; note?: string; created_at: string }[]
  trend_series: number[]
  brief?: { id: string; generated_by: string; created_at: string } | null
  allowed_transitions: string[]
}

export interface BuilderBrief {
  id: string; opportunity_id: string; generated_by: string; created_at: string
  problem_definition: string; target_user: string; jtbd: string[]; mvp_scope: string
  core_features: { name: string; priority?: string; why?: string }[]; pricing_idea: string
  competitors: { name: string; weakness?: string }[]; differentiation: string; technical_difficulty: string
  recommended_stack: string[]; go_to_market: string[]; validation_plan: string[]
}

export interface TodayPayload {
  day: string; picks: Opportunity[]; also_on_radar: Opportunity[]; thresholds: { min_score: number; min_confidence: number }
  brief_md?: string | null; brief_at?: string | null; last_job?: { id: string; job_type: string; status: string; started_at: string; finished_at?: string } | null
  data: { signals: number; live: number; mock: number }
}

export interface RadarCluster {
  id: string; label: string; summary?: string; persona?: string; category?: string; stage: string; velocity: number; acceleration: number
  signal_count: number; unique_users: number; source_count: number; first_seen?: string; last_seen?: string; data_mode: DataMode; analysis_status: string
  opportunity_id?: string | null; opportunity_score?: number | null; opportunity_status?: string | null; series: number[]; window_signals: number
}

export interface ExploreResult {
  session_id: string; query: string; data_mode: DataMode; overview?: string | null; sources: Record<string, { mode: string; ok: boolean; signals?: number; error?: string }>
  new_signals: number; recalled_signals: number
  clusters: { id: string; label: string; summary?: string; persona?: string; category?: string; signal_count: number; unique_users: number; source_count: number; data_mode: DataMode; relevance: number; coverage: string; closest_products: { id: string; name: string; similarity: number; origin: DataMode }[]; complaints: string[]; signals: { id: string; title: string; url: string; source_id: string; origin: DataMode; excerpt: string }[] }[]
  products: { id: string; name: string; tagline: string; url: string; votes: number; rating?: number; pricing?: string; launched_at?: string; similarity: number; origin: DataMode }[]
  gaps: { cluster_id: string; label: string; coverage: string; complaints: string[] }[]
  opportunity_draft?: { id?: string; title?: string; core_pain?: string; proposed_solution?: string; wedge?: string; opportunity_score?: number; confidence?: number; data_mode?: DataMode; generated_by?: string; unavailable?: string } | null
  warnings: string[]
}

export interface AskResult { id: string; question: string; plan: Record<string, unknown>; answer_md: string; citations: string[]; candidates: { id: string; title: string; opportunity_score: number; confidence: number; data_mode: DataMode; status: string }[]; generated_by: string; data_mode: DataMode }

export interface Source {
  id: string; name: string; adapter: string; kind: string; mode: string; enabled: number; reliability: number; max_per_round: number; note?: string
  last_attempt_at?: string; last_success_at?: string; last_error?: string; consecutive_failures?: number; last_item_count?: number; latency_ms?: number
  signals: number; signals_7d: number; products: number; config: Record<string, unknown>
}

export interface Job {
  id: string; job_type: string; started_at: string; finished_at?: string; status: string; stats: Record<string, unknown>; error?: string; ai_calls: number
  interrupted?: boolean
  steps: { step: string; status: string; started_at: string; finished_at?: string; counts: Record<string, unknown>; error?: string }[]
}

export interface Settings {
  models: Record<string, { enabled: boolean; model?: string | null; call_limit_24h?: number | null }>
  embedding: { provider: string; dim: number; degraded: boolean }
  classifier: { provider: string }
  producthunt_mode: string; producthunt_token_set: boolean; github_token_set: boolean; timezone: string; daily_hour: number; budget_cny_24h: number
  usage_24h: Record<string, { calls: number; cost: number; input_tokens?: number; output_tokens?: number }>
  usage_7d_by_task: { task: string; model: string; calls: number; input_tokens: number; output_tokens: number; cost: number; failures: number }[]
  pipeline: Record<string, number>; weights: Record<string, number>; db_path: string; config_dir: string
}


// ───────────────────────── studio ─────────────────────────

export type Platform = 'wechat' | 'xiaohongshu' | 'zhihu' | 'toutiao' | 'x'
export type DocStatus = 'idea' | 'draft' | 'ready' | 'published' | 'archived'

export interface BriefItem {
  id: string; day: string; section: 'story' | 'signal' | 'opportunity'; ref_type: string; ref_id: string; rank: number
  title: string; url?: string | null; source_name?: string | null; lane?: string | null; lane_name?: string | null
  summary: string; why: string; angles: string[]; score: number; origin: DataMode; status: 'new' | 'saved' | 'dismissed' | 'used'
  material_id?: string | null; document_id?: string | null; meta: Record<string, unknown>; created_at: string
}

export interface BriefPage {
  day: string; today: string; days: string[]
  sections: { story: BriefItem[]; signal: BriefItem[]; opportunity: BriefItem[] }
  counts: Record<string, number>
  recent_materials: { id: string; kind: string; title: string; url?: string | null; source_name?: string | null; origin: string; created_at: string }[]
  data_mode: DataMode; models: { fast: boolean; analysis: boolean }; lanes: Record<string, string>
  last_job?: { started_at: string; status: string; job_type: string } | null
}

export interface Material {
  id: string; kind: string; title: string; url?: string | null; source_name?: string | null; author?: string | null; published_at?: string | null
  summary: string; quote: string; content: string; ref_type?: string | null; ref_id?: string | null; lane?: string | null; tags: string[]
  origin: 'live' | 'mock' | 'manual'; archived: number; created_at: string; updated_at: string
  relation?: string; document_count?: number; documents?: { id: string; title: string; status: string }[]
}

export interface DocumentSummary {
  id: string; title: string; status: DocStatus; lane?: string | null; thesis: string; target_platform: Platform; word_count: number
  data_mode: DataMode; current_version: number; created_at: string; updated_at: string; material_count: number; variant_count: number; publication_count: number
}

export interface DocVersion { id: string; version_number: number; title: string; source: string; note?: string | null; word_count: number; created_at: string; content_md?: string }
export interface Variant { id: string; document_id: string; platform: Platform; platform_name?: string; title: string; content_md: string; meta: { tags?: string[] }; generated_by: string; warnings: string[]; created_at: string; plain_text?: string }
export interface Publication { id: string; document_id: string; variant_id?: string | null; platform: Platform; external_url?: string | null; note?: string | null; published_at: string; title?: string }
export interface AIAction { id: string; action: string; mode?: string | null; input_excerpt?: string | null; output: Record<string, unknown>; model: string; generated_by: string; warnings: string[]; accepted: number; created_at: string }

export interface DocumentFull extends Omit<DocumentSummary, 'material_count' | 'variant_count' | 'publication_count'> {
  content_md: string; seed_material_id?: string | null; meta: Record<string, unknown>
  materials: Material[]; versions: DocVersion[]; variants: Variant[]; publications: Publication[]; ai_actions: AIAction[]
}

export interface AIResult { id: string; action: string; output: Record<string, unknown>; model: string; generated_by: string; warnings: string[] }

export interface Capabilities { actions: string[]; rewrite_modes: Record<string, string>; platforms: Record<Platform, string>; platform_rules: Record<string, string>; writing_slot: string; model_available: boolean }

export interface PublishCenter {
  documents: (DocumentSummary & { variant_platforms: string[]; published_platforms: string[] })[]
  publications: Publication[]
  platforms: Record<Platform, string>
}

export interface WorkbenchOverview {
  counts: Record<DocStatus, number>
  resume: DocumentSummary | null
  recent_documents: DocumentSummary[]
  ready_documents: DocumentSummary[]
  material_count: number
  recent_materials: BriefPage['recent_materials']
  topics: BriefItem[]
  topic_count: number
  brief_day: string
  today: string
}

export const PLATFORM_NAME: Record<Platform, string> = { wechat: '公众号', xiaohongshu: '小红书', zhihu: '知乎', toutiao: '头条', x: 'X' }
export const DOC_STATUS_NAME: Record<DocStatus, string> = { idea: '灵感', draft: '草稿', ready: '待发', published: '已发布', archived: '已归档' }
