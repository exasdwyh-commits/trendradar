export function fmtDate(value?: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })
}

export function fmtDateTime(value?: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
}

export function ago(value?: string | null): string {
  if (!value) return '—'
  const ms = Date.now() - new Date(value).getTime()
  if (Number.isNaN(ms)) return value
  const m = Math.round(ms / 60000)
  if (m < 1) return '刚刚'
  if (m < 60) return `${m} 分钟前`
  const h = Math.round(m / 60)
  if (h < 48) return `${h} 小时前`
  return `${Math.round(h / 24)} 天前`
}

export function titleCase(value?: string | null): string {
  if (!value) return '—'
  return value.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

export const DIFFICULTY: Record<string, string> = { weekend: '一个周末', '2_weeks': '两周', '1_3_months': '1–3 个月', '3_plus_months': '3 个月以上' }
export const DIMENSIONS = ['pain', 'demand', 'growth', 'competition', 'gap', 'monetization', 'build_ease', 'distribution', 'confidence']
export const DIMENSION_LABEL: Record<string, string> = {
  pain: '痛感', demand: '需求量', growth: '增长', competition: '竞争', gap: '空白', monetization: '变现', build_ease: '构建难度', distribution: '分发', confidence: '证据置信度',
}

export const STAGE_NAME: Record<string, string> = { emerging: '爆发中', growing: '上升', stable: '平稳', fading: '减弱', new: '新出现' }
export const OPP_STATUS_NAME: Record<string, string> = { discovered: '已发现', watching: '观察中', promising: '有潜力', researching: '研究中', validated: '已验证', building: '构建中', rejected: '已否决', archived: '已归档' }
export const PERSONA_NAME: Record<string, string> = { developer: '开发者', freelancer: '自由职业者', small_business_owner: '小企业主', founder: '创始人', marketer: '营销人', designer: '设计师', student: '学生', consumer: '消费者', other: '其他' }
export function zh(map: Record<string, string>, value?: string | null): string {
  if (!value) return '—'
  return map[value] ?? titleCase(value)
}
