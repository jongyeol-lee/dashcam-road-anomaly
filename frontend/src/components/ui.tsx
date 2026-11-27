import { AlertCircle, ArrowLeft, CircleCheck, FlaskConical, Route } from 'lucide-react'
import { Link, NavLink, useLocation, useMatch } from 'react-router'
import type { ComponentPropsWithRef, ReactNode } from 'react'
import { PHASE_LABELS, SERVICE_NAME, type AnalysisPhase } from '../config/service'

export function Button({ variant = 'primary', className = '', children, ...props }: ComponentPropsWithRef<'button'> & { variant?: 'primary' | 'secondary' | 'ghost'; children: ReactNode }) {
  return <button className={`button button-${variant} ${className}`} {...props}>{children}</button>
}
export function StatusBadge({ phase }: { phase: AnalysisPhase }) {
  return <span className={`badge ${phase === 'completed' ? 'badge-success' : phase === 'failed' ? 'badge-error' : ''}`}>
    {phase === 'completed' && <CircleCheck size={14} aria-hidden="true" />}{PHASE_LABELS[phase]}</span>
}
export function JobInfo({ jobId }: { jobId: string }) {
  return <details className="job-id muted"><summary>작업 정보</summary><p>작업 ID · {jobId}</p></details>
}
export function EmptyState({ title, children }: { title: string; children: ReactNode }) {
  return <div className="empty-state"><AlertCircle size={28} aria-hidden="true" /><h2>{title}</h2>{children}</div>
}
export function HistoryBackLink() {
  const { state } = useLocation()
  const path = state?.historyPath
  if (typeof path !== 'string' || (path !== '/history' && !path.startsWith('/history?'))) return null
  return <Link to={path} className="button button-secondary"><ArrowLeft size={16} aria-hidden="true" />분석 이력으로</Link>
}

export function JobNotice({ title, children, backTo = '/', backLabel = '영상 선택 화면으로' }: {
  title: string
  children?: ReactNode
  backTo?: string
  backLabel?: string
}) {
  return <main className="page narrow"><div className="panel"><EmptyState title={title}>
    {children}
    <div className="button-row justify-center">
      <HistoryBackLink />
      <Link to={backTo} className="button button-secondary">{backLabel}</Link>
    </div>
  </EmptyState></div></main>
}
export function Layout({ children }: { children: ReactNode }) {
  const showDemo = useMatch('/examples/*')
  return <>
    <a className="skip-link" href="#main-content">본문으로 이동</a>
    <header className="site-header"><div className="header-inner">
      <Link to="/" className="brand"><span className="brand-icon"><Route size={23} aria-hidden="true" /></span><span>{SERVICE_NAME}</span></Link>
      {showDemo && <span className="badge">UI 미리보기</span>}
      <nav className="header-nav" aria-label="주 메뉴">
        <NavLink to="/" end>영상 분석</NavLink>
        <NavLink to="/history" end>분석 이력</NavLink>
      </nav>
      <span className="header-note">주행의 기록을, 도로를 살피는 시선으로</span>
    </div></header>
    {showDemo && <div className="demo-banner"><FlaskConical size={16} aria-hidden="true" /><span><strong>개발용 예시 모드</strong> · 화면 확인을 위한 예시 결과와 처리 상태입니다.</span></div>}
    <div id="main-content" tabIndex={-1}>{children}</div>
    <footer className="site-footer">{SERVICE_NAME}<span>AI가 제안하고, 사람이 확인합니다.</span></footer>
  </>
}
