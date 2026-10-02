import type { DocStatus } from '../../lib/api'
import type { IconName } from '../icons'

export type Tab = 'agent' | 'creation' | 'ai' | 'materials' | 'versions' | 'variants' | 'publish'
export type View = 'split' | 'edit' | 'preview'
export interface Selection { start: number; end: number; text: string }

export const LANES: Record<string, string> = {
  AI_COMMERCIALIZATION: 'AI 商业化',
  INDUSTRY: '产业与利润池',
  COMPANY: '公司与战略',
  BUSINESS_MODEL: '商业模式',
  GLOBALIZATION: '全球化与中国映射',
  OTHER: '其他',
}

export const REWRITE_LABEL: Record<string, string> = {
  concise: '精简',
  expand: '扩写',
  plain: '更口语',
  professional: '更专业',
  logic: '加强逻辑',
  punchy: '更有张力',
  english: '译成英文',
  custom: '自定义指令',
}

export const TABS: { id: Tab; label: string; icon: IconName }[] = [
  { id: 'agent', label: '创作 Agent', icon: 'spark' },
  { id: 'creation', label: '创作规划', icon: 'compass' },
  { id: 'ai', label: 'AI 助手', icon: 'sparkles' },
  { id: 'materials', label: '素材', icon: 'library' },
  { id: 'versions', label: '版本', icon: 'history' },
  { id: 'variants', label: '平台版本', icon: 'layers' },
  { id: 'publish', label: '发布', icon: 'send' },
]

export const STATUS_ICON: Record<DocStatus, IconName> = {
  idea: 'spark',
  draft: 'edit',
  ready: 'check',
  published: 'send',
  archived: 'trash',
}

export function countWords(text: string): number {
  const stripped = text.replace(/[#*`>[\]()_~|-]/g, ' ')
  const cjk = (stripped.match(/[\u4e00-\u9fff\u3400-\u4dbf]/g) ?? []).length
  const words = (stripped.match(/[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*/g) ?? []).length
  return cjk + words
}

export function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string)
}

export function actionName(a: string): string {
  return ({ angles: '选题角度', outline: '大纲', draft: '初稿', titles: '标题', rewrite: '改写', variant: '平台版本', summary: '摘要' } as Record<string, string>)[a] ?? a
}
