import { useEffect, useState } from 'react'
import { ArrowRight, Check, Download, ExternalLink, FileText, Plus } from 'lucide-react'
import { api } from '../api'
import Editor from '../components/Editor'
import { Empty, Header, Pill } from '../components/Common'
import type { DocumentDetail, DocumentSummary, PlatformVariant } from '../types'

const platformName:Record<string,string>={WECHAT:'公众号',XIAOHONGSHU:'小红书',ZHIHU:'知乎',TOUTIAO:'头条',X:'X'}

export function Studio({selected,onSelect,refreshKey,bump}:{selected:string|null;onSelect:(id:string)=>void;refreshKey:number;bump:()=>void}){
  const [documents,setDocuments]=useState<DocumentSummary[]>([])
  const [detail,setDetail]=useState<DocumentDetail|null>(null)
  const [saving,setSaving]=useState(false)
  const load=async()=>{const d=await api.get<{items:DocumentSummary[]}>('/api/documents');setDocuments(d.items)}
  useEffect(()=>{void load()},[refreshKey])
  useEffect(()=>{if(selected)api.get<DocumentDetail>('/api/documents/'+selected).then(setDetail);else setDetail(null)},[selected,refreshKey])
  const create=async()=>{const d=await api.post<{document_id:string}>('/api/documents',{title:'未命名文章'});await load();onSelect(d.document_id)}
  if(selected&&detail){
    const reload=async()=>setDetail(await api.get<DocumentDetail>('/api/documents/'+selected))
    const save=async(title:string,json:Record<string,unknown>,html:string,text:string,note?:string)=>{
      setSaving(true);try{await api.put('/api/documents/'+selected,{title,content_json:json,content_html:html,plain_text:text,source:'MANUAL',note});await reload();bump()}finally{setSaving(false)}
    }
    const restore=async(v:number)=>{await api.post('/api/documents/'+selected+'/restore/'+v);await reload();bump()}
    const imagePlan=async()=>{await api.post('/api/documents/'+selected+'/image-plan');await reload()}
    const variant=async(platform:string)=>{await api.post('/api/documents/'+selected+'/variant',{platform});await reload()}
    const aiEdit=async(payload:{selected_text:string;instruction:string;before_context:string;after_context:string})=>{
      return api.post<{replacement:string;warning?:string;used_evidence_ids?:string[]}>('/api/documents/'+selected+'/edit-selection',payload)
    }
    return <Editor document={detail} saving={saving} onSave={save} onRestore={restore} onImagePlan={imagePlan} onVariant={variant} onAiEdit={aiEdit}/>
  }
  return <>
    <Header eyebrow="CONTENT STUDIO" title="创作中心" sub="从系统选题开始，也可以完全从自己的想法开始。母稿是资产，不是一次性AI输出。"
      action={<button className="primary-button" onClick={()=>void create()}><Plus size={16}/>新建文章</button>}/>
    {!documents.length?<Empty>还没有文章。可以从已确认的观点进入，也可以直接新建空白稿。</Empty>:
      <div className="document-grid">{documents.map(d=><button className="document-card" key={d.id} onClick={()=>onSelect(d.id)}><div className="doc-icon"><FileText/></div><div className="doc-body"><div className="micro-row"><Pill>{d.status}</Pill><span>v{d.current_version}</span><span>{d.variant_count} 个平台版本</span></div><h2>{d.title}</h2><p>{d.thesis||d.candidate_title||'自主创作'}</p><small>更新于 {d.updated_at.replace('T',' ').slice(0,16)}</small></div><ArrowRight/></button>)}</div>}
  </>
}

export function Publish(){
  const [documents,setDocuments]=useState<DocumentSummary[]>([])
  const [variants,setVariants]=useState<PlatformVariant[]>([])
  const [busy,setBusy]=useState<string|null>(null)
  const load=async()=>{const [d,v]=await Promise.all([api.get<{items:DocumentSummary[]}>('/api/documents'),api.get<{items:PlatformVariant[]}>('/api/publish')]);setDocuments(d.items);setVariants(v.items)}
  useEffect(()=>{void load()},[])
  const generate=async(doc:string,platform:string)=>{setBusy(doc+platform);try{await api.post('/api/documents/'+doc+'/variant',{platform});await load()}finally{setBusy(null)}}
  const exportOne=async(id:string)=>{const d=await api.post<{url:string}>('/api/platform-variants/'+id+'/export');window.open(d.url,'_blank')}
  const published=async(id:string)=>{const url=window.prompt('可选：粘贴已发布页面链接')||undefined;await api.post('/api/platform-variants/'+id+'/published',{external_url:url});await load()}
  return <>
    <Header eyebrow="PUBLISHING" title="发布中心" sub="一篇母稿，多种平台表达。先做平台适配与导出；平台授权接入后再逐步升级为直发。"/>
    <section className="section">
      <div className="section-title"><h2>生成平台版本</h2><span>不简单截短，而是按平台重构表达</span></div>
      <div className="publish-docs">{documents.map(d=><div className="publish-doc" key={d.id}><div><h3>{d.title}</h3><p>{d.thesis||'自主创作母稿'}</p></div><div className="platform-actions">{['WECHAT','XIAOHONGSHU','ZHIHU','TOUTIAO'].map(p=><button disabled={busy===d.id+p} key={p} onClick={()=>void generate(d.id,p)}>{platformName[p]}</button>)}</div></div>)}</div>
    </section>
    <section className="section">
      <div className="section-title"><h2>发布队列</h2><span>当前支持平台版生成、导出与发布记录</span></div>
      {!variants.length?<Empty>还没有平台版本。</Empty>:<div className="variant-list">{variants.map(v=><article className="variant-card" key={v.id}><div className="variant-head"><Pill tone="blue">{platformName[v.platform]||v.platform}</Pill><Pill tone={v.status==='PUBLISHED'?'green':'neutral'}>{v.status}</Pill></div><h3>{v.title}</h3><p>{v.content_text?.slice(0,180)}{v.content_text?.length>180?'…':''}</p><div className="actions"><button className="ghost-button" onClick={()=>void exportOne(v.id)}><Download size={15}/>导出</button>{v.status!=='PUBLISHED'&&<button className="primary-button" onClick={()=>void published(v.id)}><Check size={15}/>标记已发布</button>}{v.external_url&&<a className="text-link" href={v.external_url} target="_blank" rel="noreferrer">打开发布页 <ExternalLink size={13}/></a>}</div></article>)}</div>}
    </section>
  </>
}
