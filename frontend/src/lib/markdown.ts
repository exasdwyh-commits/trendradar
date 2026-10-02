import DOMPurify from 'dompurify'
import { marked } from 'marked'

export function renderMarkdown(text: string): string {
  return DOMPurify.sanitize(marked.parse(text, { async: false }) as string, { USE_PROFILES: { html: true } })
}
