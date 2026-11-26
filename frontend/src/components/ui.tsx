import { AlertCircle, CircleCheck, FlaskConical, Route } from 'lucide-react'
import { Link, useMatch } from 'react-router'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { PHASE_LABELS, SERVICE_NAME, type AnalysisPhase } from '../config/service'

export function Button({ variant = 'primary', className = '', children, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'ghost'; children: ReactNode }) {
  return <button className={`button button-${variant} ${className}`} {...props}>{children}</button>
}
export function StatusBadge({ phase }: { phase: AnalysisPhase }) {
  return <span className={`badge ${phase === 'completed' ? 'badge-success' : phase === 'failed' ? 'badge-error' : ''}`}>
    {phase === 'completed' && <CircleCheck size={14} aria-hidden="true" />}{PHASE_LABELS[phase]}</span>
}
export function EmptyState({ title, children }: { title: string; children: ReactNode }) {
  return <div className="empty-state"><AlertCircle size={28} aria-hidden="true" /><h2>{title}</h2>{children}</div>
}
export function JobNotice({ title, children, backTo = '/', backLabel = '영상 선택 화면으로' }: {
  title: string
  children?: ReactNode
  backTo?: string
  backLabel?: string
}) {
  return <main className="page narrow"><div className="panel"><EmptyState title={title}>
    {children}
    <Link to={backTo} className="button button-secondary">{backLabel}</Link>
  </EmptyState></div></main>
}
export function Layout({ children }: { children: ReactNode }) {
  const showDemo = useMatch('/examples/*')
  return <>
    <a className="skip-link" href="#main-content">본문으로 이동</a>
    <header className="site-header"><div className="header-inner">
      <Link to="/" className="brand"><span className="brand-icon"><Route size={23} aria-hidden="true" /></span><span>{SERVICE_NAME}</span></Link>
      <span className="header-note">주행의 기록을, 도로를 살피는 시선으로</span>{showDemo && <span className="badge">UI 미리보기</span>}
    </div></header>
    {showDemo && <div className="demo-banner"><FlaskConical size={16} aria-hidden="true" /><span><strong>개발용 예시 모드</strong> · 화면 확인을 위한 예시 결과와 처리 상태입니다.</span></div>}
    <div id="main-content" tabIndex={-1}>{children}</div>
    <footer className="site-footer">{SERVICE_NAME}<span>AI가 제안하고, 사람이 확인합니다.</span></footer>
  </>
}
