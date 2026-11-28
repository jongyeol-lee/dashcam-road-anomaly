import { Link, useLocation, useParams } from 'react-router'
import { Check, CircleAlert, FileVideo, LoaderCircle, Pause, Play, ScanLine } from 'lucide-react'
import { ApiRequestError, apiErrorMessage, errorMessage, getJob } from '../api/client'
import type { JobStatus } from '../api/types'
import { useJobQuery } from '../api/useJobQuery'
import { Button, HistoryBackLink, JobInfo, JobNotice, StatusBadge } from '../components/ui'
import { PHASE_LABELS, PHASE_MESSAGES, type AnalysisPhase } from '../config/service'
import { useSession } from '../mocks/SessionContext'

export function AnalysisPage() {
  const { jobId = '' } = useParams()
  const { state } = useLocation()
  const filename = typeof state?.filename === 'string' ? state.filename : undefined
  return <LiveAnalysis key={jobId} jobId={jobId} filename={filename} />
}

function isPending(job: JobStatus) {
  return job.status === 'queued' || job.status === 'running'
}

function LiveAnalysis({ jobId, filename }: { jobId: string; filename?: string }) {
  const { data: job, error, retry } = useJobQuery(jobId, getJob, isPending)
  if (error instanceof ApiRequestError && error.status === 404) {
    return <JobNotice title="작업을 찾을 수 없습니다"><p>{error.message}</p></JobNotice>
  }
  return <AnalysisView
    jobId={jobId}
    phase={job?.status}
    filename={job?.original_filename ?? filename}
    queryError={error === undefined ? undefined : errorMessage(error)}
    onRetry={retry}
    failure={job?.error ? apiErrorMessage(job.error.code) : undefined}
  />
}

export function ExampleAnalysisPage() {
  const { jobId = '' } = useParams()
  const { jobs, setPhase, toggleAuto } = useSession()
  const entry = Object.hasOwn(jobs, jobId) ? jobs[jobId] : undefined
  if (!entry) return <JobNotice title="예시 작업을 찾을 수 없습니다" />
  return <AnalysisView jobId={jobId} phase={entry.phase} failure={entry.job?.error?.message}
    example={{ auto: entry.auto, onPhase: phase => setPhase(jobId, phase), onToggle: () => toggleAuto(jobId) }} />
}

function AnalysisView({ jobId, phase, filename, queryError, onRetry, failure, example }: {
  jobId: string
  phase?: AnalysisPhase
  filename?: string
  queryError?: string
  onRetry?: () => void
  failure?: string
  example?: { auto: boolean; onPhase: (phase: AnalysisPhase) => void; onToggle: () => void }
}) {
  const { state } = useLocation()
  const stages: AnalysisPhase[] = example ? ['uploading', 'queued', 'running', 'completed'] : ['queued', 'running', 'completed']
  const currentIndex = phase ? stages.indexOf(phase) : -1
  const failed = phase === 'failed'
  const resultsPath = `${example ? '/examples' : ''}/jobs/${jobId}/results`
  return <main className="page narrow">
    <div className="page-heading">{example && <span className="eyebrow">예시 워크플로</span>}<h1>영상 분석 상태</h1><p className="muted">{example ? '처리 단계별 화면을 미리 확인하세요.' : '영상 분석이 완료되면 결과를 확인할 수 있습니다.'}</p></div>
    <section className="panel status-panel">
      <div className={`status-illustration ${failed || queryError ? 'is-error' : ''}`}>{failed || queryError ? <CircleAlert size={36} aria-hidden="true" /> : phase === 'completed' ? <Check size={36} aria-hidden="true" /> : <LoaderCircle className="animate-spin" size={36} aria-hidden="true" />}</div>
      <div role="status" aria-live="polite">
        {phase && <StatusBadge phase={phase} />}
        <h2>{queryError ? '작업 상태를 새로 확인하지 못했습니다.' : phase ? PHASE_MESSAGES[phase] : '작업 상태를 확인하고 있습니다.'}</h2>
        {example && <p className="muted">화면 확인용 예시 상태입니다.</p>}
        {queryError && phase && <p className="muted">위에는 마지막으로 받은 분석 상태를 표시합니다.</p>}
      </div>
      <div className="file-summary"><FileVideo size={20} aria-hidden="true" /><div><strong>{filename ?? (example ? '개발용 예시 영상' : '원본 영상')}</strong><JobInfo jobId={jobId} /></div></div>
      <ol className="stage-list" aria-label="분석 처리 단계">{stages.map((stage, index) => <li key={stage} className={phase === stage ? 'current' : currentIndex > index ? 'done' : ''} aria-current={phase === stage ? 'step' : undefined}><span>{currentIndex > index ? <Check size={16} aria-hidden="true" /> : index + 1}</span>{PHASE_LABELS[stage]}</li>)}</ol>
      {queryError && <p role="alert" className="error-message">{queryError}</p>}
      {failed && <p role="alert" className="error-message">{failure ?? '영상 분석에 실패했습니다. 영상을 다시 선택해 주세요.'}</p>}
      <div className="button-row justify-center">
        {queryError && <Button onClick={onRetry}>상태 다시 확인</Button>}
        {phase === 'completed' && <Link className="button button-primary" to={resultsPath} state={filename ? { ...state, filename } : state}><ScanLine size={18} aria-hidden="true" />결과 확인</Link>}
        <HistoryBackLink />
        <Link to="/" className="button button-secondary">{failed ? '다른 영상 선택' : '영상 선택 화면으로'}</Link>
      </div>
    </section>
    {example && <section className="demo-controls"><h2>화면 검증용 상태 전환</h2><p className="small muted">수동 선택 시 자동 전환을 멈춥니다.</p><div className="button-row"><label htmlFor="demo-phase">예시 상태</label><select id="demo-phase" value={phase} onChange={event => example.onPhase(event.target.value as AnalysisPhase)}>{Object.entries(PHASE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><Button variant="secondary" disabled={phase === 'completed' || failed} onClick={example.onToggle}>{example.auto ? <Pause size={16} aria-hidden="true" /> : <Play size={16} aria-hidden="true" />}{example.auto ? '자동 전환 멈춤' : '자동 전환 재생'}</Button></div></section>}
  </main>
}
