import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from './api'
import { errorMessage, useToast } from '../components/toast'

export function useNewDocument() {
  const navigate = useNavigate()
  const { toast } = useToast()
  const [busy, setBusy] = useState(false)
  const pending = useRef(false)

  async function create() {
    if (pending.current) return
    pending.current = true
    setBusy(true)
    try {
      const doc = await api.post<{ id: string }>('/api/documents', { title: '', content_md: '', target_platform: 'wechat' })
      navigate(`/studio/${doc.id}`)
    } catch (error) {
      toast(errorMessage(error), 'bad')
    } finally {
      pending.current = false
      setBusy(false)
    }
  }

  return { create, busy }
}
