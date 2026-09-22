export type Candidate = {
  id: string
  title: string
  event_summary?: string
  what_changed?: string
  why_now?: string
  profit_pool?: string
  who_benefits?: string
  who_loses?: string
  china_mapping?: string
  strongest_counter?: string
  evidence_gap?: string
  cognition_score: number
  content_score: number
  action: 'WRITE' | 'TRACK' | 'HOLD' | 'SKIP'
  cognition_status: string
  evidence_items?: number
  source_count?: number
  quality_source_count?: number
}

export type Evidence = {
  id: string
  title: string
  url: string
  summary?: string
  content?: string
  kind: 'FACT' | 'CLAIM' | 'INFER'
  source_role: 'PRIMARY' | 'VERIFIER' | 'DISCOVERY'
  source_id: string
  published_at?: string
  relation?: 'SUPPORT' | 'COUNTER' | 'CONTEXT'
  note?: string
}

export type ResearchUnit = {
  text: string
  evidence_ids: string[]
  note?: string
}

export type ResearchPack = {
  id: string
  facts: ResearchUnit[]
  claims: ResearchUnit[]
  inferences: ResearchUnit[]
  strongest_counter?: string
  evidence_gap?: string
  grounding?: {
    grounded_units: number
    evidence_ids: string[]
    evidence_count: number
    independent_source_count?: number
    quality_source_count?: number
    source_ids?: string[]
  }
}

export type Thesis = {
  id: string
  candidate_id: string
  candidate_title?: string
  thesis: string
  support_json?: string[]
  counter_json?: string[]
  falsification_signal?: string
  status: string
}

export type DocumentVersion = {
  id: string
  version_number: number
  title: string
  source: string
  note?: string
  created_at: string
}

export type MediaAsset = {
  id: string
  asset_type: string
  role: string
  title: string
  brief?: string
  placement?: string
  prompt?: string
  aspect_ratio?: string
  evidence_ids?: string[]
  source_url?: string
  status: string
}

export type PlatformVariant = {
  id: string
  document_id: string
  platform: 'WECHAT' | 'XIAOHONGSHU' | 'ZHIHU' | 'TOUTIAO' | 'X'
  title: string
  content_text: string
  content_html?: string
  status: string
  publication_status?: string
  external_url?: string
  published_at?: string
}

export type DocumentSummary = {
  id: string
  title: string
  status: string
  updated_at: string
  current_version: number
  candidate_title?: string
  thesis?: string
  variant_count: number
}

export type DocumentDetail = DocumentSummary & {
  article_id?: string
  candidate_id?: string
  thesis_id?: string
  current?: {
    version_number: number
    title: string
    content_json: Record<string, unknown>
    content_html: string
    plain_text: string
    source: string
    created_at: string
  }
  versions: DocumentVersion[]
  media_assets: MediaAsset[]
  platform_variants: PlatformVariant[]
  evidence: Evidence[]
}

export type Trend = {
  id: string
  name: string
  judgement: string
  stage: string
  momentum: string
  status: string
  profit_pool?: string
  china_relevance?: string
  watch_next?: string
  support_count: number
  counter_count: number
  uncertain_count: number
}

export type WorldModel = {
  summary?: string
  strengthened?: unknown[]
  weakened?: unknown[]
  diverging?: unknown[]
  new?: unknown[]
}

export type Health = {
  ok: boolean
  schema_version?: number
  last_run?: { status: string; started_at: string }
  models: Record<string, { enabled: boolean; model?: string }>
}
