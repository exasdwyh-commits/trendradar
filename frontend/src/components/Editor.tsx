import { useEffect, useMemo, useRef, useState } from 'react'
import { EditorContent, useEditor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'
import Link from '@tiptap/extension-link'
import {
  Bold, Italic, Heading2, Heading3, List, ListOrdered, Quote,
  Undo2, Redo2, Link2, Save, Sparkles, Image as ImageIcon,
  History, BookOpen, Share2, CheckCircle2
} from 'lucide-react'
import type { DocumentDetail, Evidence, MediaAsset, PlatformVariant } from '../types'

type Props = {
  document: DocumentDetail
  saving: boolean
  onSave: (title: string, json: Record<string, unknown>, html: string, text: string, note?: string) => Promise<void>
  onRestore: (version: number) => Promise<void>
  onImagePlan: () => Promise<void>
  onVariant: (platform: string) => Promise<void>
  onAiEdit: (payload:{
    selected_text:string
    instruction:string
    before_context:string
    after_context:string
  }) => Promise<{replacement:string;warning?:string;used_evidence_ids?:string[]}>
}

const platformName: Record<string,string> = {
  WECHAT: '公众号', XIAOHONGSHU: '小红书', ZHIHU: '知乎', TOUTIAO: '头条', X: 'X'
}

function ToolbarButton({title, active, onClick, children}:{title:string;active?:boolean;onClick:()=>void;children:React.ReactNode}) {
  return <button className={`tool-button ${active ? 'active' : ''}`} title={title} onMouseDown={e=>{e.preventDefault();onClick()}}>{children}</button>
}

function EvidenceList({items}:{items:Evidence[]}) {
  if (!items.length) return <div className="side-empty">这篇文章没有绑定研究证据。空白文章也可以独立创作。</div>
  return <div className="evidence-list">{items.map(item=>
    <a className="evidence-item" key={item.id} href={item.url} target="_blank" rel="noreferrer">
      <div className="micro-row"><span className={`pill role-${item.source_role.toLowerCase()}`}>{item.source_role}</span><span className="pill">{item.kind}</span>{item.relation&&<span className={`pill relation-${item.relation.toLowerCase()}`}>{item.relation}</span>}</div>
      <strong>{item.title}</strong>
      <small>{item.source_id}{item.published_at ? ` · ${item.published_at.slice(0,10)}` : ''}</small>
      {item.summary && <p>{item.summary}</p>}
    </a>
  )}</div>
}

function MediaList({items, onGenerate}:{items:MediaAsset[];onGenerate:()=>Promise<void>}) {
  return <div>
    <button className="side-action" onClick={()=>void onGenerate()}><Sparkles size={15}/>生成这篇文章的配图方案</button>
    {!items.length ? <div className="side-empty">先写完结构，再让系统判断真正需要哪几张图。</div> :
      <div className="asset-list">{items.map(item=>
        <div className="asset-card" key={item.id}>
          <div className="micro-row"><span className="pill">{item.asset_type}</span><span className="pill">{item.aspect_ratio || '—'}</span></div>
          <strong>{item.title}</strong>
          <p>{item.brief}</p>
          {item.placement && <small>位置：{item.placement}</small>}
          {item.prompt && <details><summary>生成提示词</summary><p className="prompt">{item.prompt}</p></details>}
        </div>
      )}</div>
    }
  </div>
}

function VersionList({document, onRestore}:{document:DocumentDetail;onRestore:(v:number)=>Promise<void>}) {
  return <div className="version-list">{document.versions.map(v=>
    <div className="version-row" key={v.id}>
      <div><strong>v{v.version_number}</strong><span>{v.source}</span></div>
      <small>{v.created_at.replace('T',' ').slice(0,16)}</small>
      {v.version_number !== document.current_version &&
        <button onClick={()=>void onRestore(v.version_number)}>恢复</button>}
    </div>
  )}</div>
}

function PlatformList({items,onVariant}:{items:PlatformVariant[];onVariant:(platform:string)=>Promise<void>}) {
  const platforms=['WECHAT','XIAOHONGSHU','ZHIHU','TOUTIAO']
  return <div>
    <div className="platform-grid">{platforms.map(p=>
      <button className="platform-create" key={p} onClick={()=>void onVariant(p)}>
        <Share2 size={15}/><span>生成{platformName[p]}版</span>
      </button>
    )}</div>
    <div className="variant-mini-list">{items.map(v=>
      <div className="variant-mini" key={v.id}>
        <span className="pill">{platformName[v.platform] || v.platform}</span>
        <strong>{v.title}</strong>
        <small>{v.status}</small>
      </div>
    )}</div>
  </div>
}

export default function Editor({
  document, saving, onSave, onRestore, onImagePlan, onVariant, onAiEdit
}:Props) {
  const [title,setTitle]=useState(document.title)
  const [tab,setTab]=useState<'evidence'|'media'|'versions'|'platforms'>('evidence')
  const [dirty,setDirty]=useState(false)
  const [aiEditing,setAiEditing]=useState(false)
  const lastSaved=useRef(document.current_version)

  const initialContent=useMemo(
    ()=>document.current?.content_json || {type:'doc',content:[{type:'paragraph'}]},
    [document.id]
  )

  const editor=useEditor({
    extensions:[
      StarterKit,
      Placeholder.configure({placeholder:'从一个判断开始。写你真正相信、也愿意被未来验证的东西。'}),
      Link.configure({openOnClick:false,autolink:true}),
    ],
    content: initialContent,
    editorProps:{attributes:{class:'editor-prose'}},
    onUpdate:()=>setDirty(true),
  })

  useEffect(()=>{
    setTitle(document.title)
    lastSaved.current=document.current_version
    setDirty(false)
    if(editor && document.current?.content_json) editor.commands.setContent(document.current.content_json)
  },[document.id, document.current_version])

  useEffect(()=>{
    if(!dirty || !editor) return
    const timer=window.setTimeout(async()=>{
      await onSave(title,editor.getJSON() as Record<string,unknown>,editor.getHTML(),editor.getText(), '自动保存')
      lastSaved.current += 1
      setDirty(false)
    },1500)
    return ()=>window.clearTimeout(timer)
  },[dirty,title,editor,onSave])

  if(!editor) return <div className="empty-state">正在初始化编辑器…</div>

  const setLink=()=>{
    const previous=editor.getAttributes('link').href
    const url=window.prompt('链接地址',previous || 'https://')
    if(url===null) return
    if(url==='') editor.chain().focus().extendMarkRange('link').unsetLink().run()
    else editor.chain().focus().extendMarkRange('link').setLink({href:url}).run()
  }
  const manualSave=()=>void onSave(title,editor.getJSON() as Record<string,unknown>,editor.getHTML(),editor.getText(),'手动保存').then(()=>setDirty(false))
  const aiEditSelection=async()=>{
    const {from,to}=editor.state.selection
    if(from===to){
      window.alert('请先选中要修改的一段文字。')
      return
    }
    const selected=editor.state.doc.textBetween(from,to,'\n').trim()
    if(!selected)return
    const instruction=window.prompt('怎么修改选中内容？例如：精简30%、加强逻辑、降低AI腔、把反方写得更强。')
    if(!instruction?.trim())return
    const size=editor.state.doc.content.size
    const before=editor.state.doc.textBetween(Math.max(0,from-900),from,'\n')
    const after=editor.state.doc.textBetween(to,Math.min(size,to+900),'\n')
    setAiEditing(true)
    try{
      const result=await onAiEdit({
        selected_text:selected,
        instruction:instruction.trim(),
        before_context:before,
        after_context:after,
      })
      editor.chain().focus().insertContentAt({from,to},result.replacement).run()
      setDirty(true)
      if(result.warning)window.alert('AI编辑提示：'+result.warning)
    }finally{
      setAiEditing(false)
    }
  }


  const tabs=[
    ['evidence','证据',BookOpen],['media','配图',ImageIcon],['versions','版本',History],['platforms','平台',Share2]
  ] as const

  return <div className="studio-shell">
    <section className="editor-column">
      <div className="doc-topbar">
        <input className="doc-title" value={title} onChange={e=>{setTitle(e.target.value);setDirty(true)}} placeholder="文章标题"/>
        <div className="save-state">{saving ? '保存中…' : dirty ? '未保存' : <><CheckCircle2 size={14}/>已保存 v{document.current_version}</>}</div>
      </div>

      <div className="editor-toolbar">
        <ToolbarButton title="粗体" active={editor.isActive('bold')} onClick={()=>editor.chain().focus().toggleBold().run()}><Bold size={16}/></ToolbarButton>
        <ToolbarButton title="斜体" active={editor.isActive('italic')} onClick={()=>editor.chain().focus().toggleItalic().run()}><Italic size={16}/></ToolbarButton>
        <span className="tool-sep"/>
        <ToolbarButton title="二级标题" active={editor.isActive('heading',{level:2})} onClick={()=>editor.chain().focus().toggleHeading({level:2}).run()}><Heading2 size={16}/></ToolbarButton>
        <ToolbarButton title="三级标题" active={editor.isActive('heading',{level:3})} onClick={()=>editor.chain().focus().toggleHeading({level:3}).run()}><Heading3 size={16}/></ToolbarButton>
        <ToolbarButton title="无序列表" active={editor.isActive('bulletList')} onClick={()=>editor.chain().focus().toggleBulletList().run()}><List size={16}/></ToolbarButton>
        <ToolbarButton title="有序列表" active={editor.isActive('orderedList')} onClick={()=>editor.chain().focus().toggleOrderedList().run()}><ListOrdered size={16}/></ToolbarButton>
        <ToolbarButton title="引用" active={editor.isActive('blockquote')} onClick={()=>editor.chain().focus().toggleBlockquote().run()}><Quote size={16}/></ToolbarButton>
        <ToolbarButton title="链接" active={editor.isActive('link')} onClick={setLink}><Link2 size={16}/></ToolbarButton>
        <ToolbarButton title="AI修改选中内容" onClick={()=>void aiEditSelection()}><Sparkles size={16}/>{aiEditing&&<span className="tool-mini">处理中</span>}</ToolbarButton>
        <span className="tool-sep"/>
        <ToolbarButton title="撤销" onClick={()=>editor.chain().focus().undo().run()}><Undo2 size={16}/></ToolbarButton>
        <ToolbarButton title="重做" onClick={()=>editor.chain().focus().redo().run()}><Redo2 size={16}/></ToolbarButton>
        <button className="manual-save" onClick={manualSave}><Save size={15}/>保存版本</button>
      </div>

      {document.thesis && <div className="thesis-pin"><span>核心判断</span><strong>{document.thesis}</strong></div>}
      <EditorContent editor={editor}/>
    </section>

    <aside className="editor-side">
      <div className="side-tabs">{tabs.map(([key,label,Icon])=>
        <button key={key} className={tab===key?'active':''} onClick={()=>setTab(key)}><Icon size={15}/>{label}</button>
      )}</div>
      <div className="side-scroll">
        {tab==='evidence' && <EvidenceList items={document.evidence}/>}
        {tab==='media' && <MediaList items={document.media_assets} onGenerate={onImagePlan}/>}
        {tab==='versions' && <VersionList document={document} onRestore={onRestore}/>}
        {tab==='platforms' && <PlatformList items={document.platform_variants} onVariant={onVariant}/>}
      </div>
    </aside>
  </div>
}
