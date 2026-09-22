import type { ReactNode } from 'react'

export function Header({
  eyebrow='BUSINESS COGNITION',title,sub,action
}:{
  eyebrow?:string
  title:string
  sub:string
  action?:ReactNode
}){
  return <div className="page-head"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{sub}</p></div>{action}</div>
}

export function Empty({children}:{children:ReactNode}){
  return <div className="empty-state">{children}</div>
}

export function Pill({
  children,tone='neutral'
}:{children:ReactNode;tone?:string}){
  return <span className={`pill tone-${tone}`}>{children}</span>
}
