import { Link, useParams } from 'react-router'
import { Check, CircleAlert, FileVideo, LoaderCircle, Pause, Play, ScanLine } from 'lucide-react'
import { Button, MissingJob, StatusBadge } from '../components/ui'
import { PHASE_LABELS, PHASE_MESSAGES, type AnalysisPhase } from '../config/service'
import { useSession } from '../mocks/SessionContext'

export function AnalysisPage() {
  const { jobId = '' } = useParams()
  const { jobs, setPhase, toggleAuto } = useSession()
  const entry = jobs[jobId]
  if (!entry) return <MissingJob />
  const phase = entry.phase
  const active = phase !== 'completed' && phase !== 'failed'
  const stages = ['uploading', 'queued', 'running', 'completed'] as const
  const currentIndex = stages.findIndex(stage => stage === phase)
  return <main className="page narrow">
    <div className="page-heading"><span className="eyebrow">예시 워크플로</span><h1>영상 분석 상태</h1><p className="muted">처리 단계별 화면을 미리 확인하세요.</p></div>
    <section className="panel status-panel">
      <div className={`status-illustration ${phase === 'failed' ? 'is-error' : ''}`}>{active ? <LoaderCircle className="animate-spin" size={36} aria-hidden="true" /> : phase === 'completed' ? <Check size={36} aria-hidden="true" /> : <CircleAlert size={36} aria-hidden="true" />}</div>
      <div role="status" aria-live="polite"><StatusBadge phase={phase} /><h2>{PHASE_MESSAGES[phase]}</h2><p className="muted">위 문구는 예시 상태입니다. 실제 업로드·AI 처리는 수행하지 않습니다.</p></div>
      <div className="file-summary"><FileVideo size={20} aria-hidden="true" /><div><strong>{entry.clientFilename ?? '개발용 예시 영상'}</strong>{entry.clientFilename && <p className="small muted">로컬에서 선택한 파일명 · 미전송 · 예시 결과와 무관</p>}<p className="small muted job-id">작업 ID · {jobId}</p></div></div>
      <ol className="stage-list" aria-label="예시 처리 단계">{stages.map((stage, index) => <li key={stage} className={phase === stage ? 'current' : currentIndex > index ? 'done' : ''} aria-current={phase === stage ? 'step' : undefined}><span>{currentIndex > index ? <Check size={16} aria-hidden="true" /> : index + 1}</span>{PHASE_LABELS[stage]}</li>)}</ol>
      {phase === 'failed' && <div role="alert" className="error-message"><strong>{entry.job?.error?.message}</strong><p>다른 파일을 선택해 다시 시도할 수 있습니다. 현재는 예시 상태만 체험할 수 있습니다.</p></div>}
      <div className="button-row justify-center">{phase === 'completed' && <Link className="button button-primary" to={`/jobs/${jobId}/results`}><ScanLine size={18} aria-hidden="true" />결과 확인</Link>}<Link to="/" className="button button-secondary">{phase === 'failed' ? '다른 영상 선택' : '영상 선택 화면으로'}</Link></div>
    </section>
    <section className="demo-controls"><h2>화면 검증용 상태 전환</h2><p className="small muted">실제 처리 상태와 무관합니다. 수동 선택 시 자동 전환을 멈춥니다.</p><div className="button-row"><label htmlFor="demo-phase">예시 상태</label><select id="demo-phase" value={phase} onChange={event => setPhase(jobId, event.target.value as AnalysisPhase)}>{Object.entries(PHASE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><Button variant="secondary" disabled={!active} onClick={() => toggleAuto(jobId)}>{entry.auto ? <Pause size={16} aria-hidden="true" /> : <Play size={16} aria-hidden="true" />}{entry.auto ? '자동 전환 멈춤' : '자동 전환 재생'}</Button></div></section>
  </main>
}
