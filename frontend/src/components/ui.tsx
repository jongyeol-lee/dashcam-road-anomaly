import { AlertCircle, CircleCheck, FlaskConical, Route } from 'lucide-react'
import { Link } from 'react-router'
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
export function MissingJob() {
  return <main className="page narrow"><div className="panel"><EmptyState title="작업을 찾을 수 없습니다">
    <p>존재하지 않는 예시 작업이거나 새로고침으로 작업 정보가 초기화되었습니다.</p>
    <Link to="/" className="button button-primary">영상 선택 화면으로</Link>
  </EmptyState></div></main>
}
export function Layout({ children }: { children: ReactNode }) {
  return <>
    <a className="skip-link" href="#main-content">본문으로 이동</a>
    <header className="site-header"><div className="header-inner">
      <Link to="/" className="brand"><span className="brand-icon"><Route size={23} aria-hidden="true" /></span><span>{SERVICE_NAME}</span></Link>
      <span className="header-note">주행의 기록을, 도로를 살피는 시선으로</span><span className="badge">UI 미리보기</span>
    </div></header>
    <div className="demo-banner"><FlaskConical size={16} aria-hidden="true" /><span><strong>개발용 예시 모드</strong> · 실제 영상 업로드와 AI 분석은 연결 전입니다. 모든 결과와 처리 상태는 화면 검증용입니다.</span></div>
    <div id="main-content" tabIndex={-1}>{children}</div>
    <footer className="site-footer">{SERVICE_NAME}<span>AI가 제안하고, 사람이 확인합니다.</span></footer>
  </>
}
