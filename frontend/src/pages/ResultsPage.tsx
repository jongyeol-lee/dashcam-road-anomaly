import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { CheckCheck, FileVideo, ListFilter, Plus, ScanLine, CircleCheck, Info } from 'lucide-react'
import type { AnalysisResults, ClassCode } from '../api/types'
import { Button, EmptyState, MissingJob, StatusBadge } from '../components/ui'
import { CLASS_LABELS, REVIEW_LABELS } from '../config/service'
import { useSession } from '../mocks/SessionContext'
import { SceneDetail } from '../features/results/SceneDetail'
import { SceneImage } from '../features/results/SceneImage'
import { Timeline } from '../features/results/Timeline'
import { VideoPanel } from '../features/results/VideoPanel'
import { formatTime, visibleScenes } from '../features/results/helpers'

export function ResultsPage() {
  const { jobId = '' } = useParams()
  const { jobs } = useSession()
  const entry = jobs[jobId]
  if (!entry) return <MissingJob />
  if (entry.phase !== 'completed') return <main className="page narrow"><div className="panel"><EmptyState title="아직 완료된 결과가 없습니다"><p>현재 예시 작업의 상태를 먼저 확인해 주세요.</p><Link className="button button-primary" to={`/jobs/${jobId}`}>분석 상태 확인</Link></EmptyState></div></main>
  return <ResultsWorkspace key={jobId} result={entry.result} />
}

function ResultsWorkspace({ result }: { result: AnalysisResults }) {
  const { reviews, setReview } = useSession()
  const [selectedId, setSelectedId] = useState(result.events[0]?.event_id)
  const [filter, setFilter] = useState<ClassCode | 'all'>('all')
  const [sort, setSort] = useState<'time' | 'score'>('time')
  const [unreviewedOnly, setUnreviewedOnly] = useState(false)
  const jobReviews = reviews[result.job_id] ?? {}
  const visible = visibleScenes(result.events, filter, sort, unreviewedOnly, jobReviews)
  const selected = visible.find(event => event.event_id === selectedId) ?? visible[0]
  const reviewedCount = result.events.filter(event => jobReviews[event.event_id] && jobReviews[event.event_id] !== 'unreviewed').length

  function resetFilters() { setFilter('all'); setUnreviewedOnly(false) }

  return <main className="page results-page"><div className="result-heading"><div><div className="title-row"><h1>영상 분석 결과</h1><StatusBadge phase="completed" /></div><p className="video-meta"><FileVideo size={16} aria-hidden="true" /><strong>개발용 예시 영상</strong><span>· {formatTime(result.video.duration_sec)}</span><span>· {result.video.width} × {result.video.height} · {result.video.fps} fps</span></p><p className="small muted job-id">작업 ID · {result.job_id}</p></div><Link to="/" className="button button-primary"><Plus size={18} aria-hidden="true" />새 영상 분석</Link></div>
    <section className="summary-strip" aria-label="예시 분석 요약">{[
      ['분석 프레임', `${result.inferred_frame_count.toLocaleString()}장`, `추출 ${result.extracted_frame_count}장 중 추론한 프레임`],
      ['탐지 박스', `${result.detection_count.toLocaleString()}개`, '반복 탐지를 포함한 박스 수'],
      ['의심 구간', `${result.event_count}개`, '시간 기준으로 모은 검토 단위'],
      ['AI 영상 분석 시간', `${result.analysis_seconds.toLocaleString()}초`, '업로드·대기 제외 · 예시 수치'],
    ].map(([label, value, help]) => <div className="summary-item" key={label}><span>{label}</span><strong>{value}</strong><small>{help}</small></div>)}</section>
    <p className="summary-caption"><Info size={15} aria-hidden="true" />박스·구간 수는 실제 파손 개수가 아닙니다. 아래 수치·장면은 모두 UI 확인을 위한 예시입니다.</p>
    <div className="workspace-grid"><div className="workspace-main"><section className="panel video-panel"><div className="panel-heading"><h2><FilmIcon />원본 영상</h2><span className="small muted">영상 미연결</span></div><VideoPanel src={result.video_url} /><Timeline events={visible} duration={result.video.duration_sec} selectedId={selected?.event_id} onSelect={setSelectedId} /></section>
      {selected ? <SceneDetail event={selected} review={jobReviews[selected.event_id] ?? 'unreviewed'} onReview={review => setReview(result.job_id, selected.event_id, review)} /> : <section className="panel"><EmptyState title={result.events.length === 0 ? '표시할 대표 장면이 없습니다' : '조건에 맞는 장면이 없습니다'}><p>{result.events.length === 0 ? '의심 구간이 없는 예시입니다. 실제 도로의 안전을 보장하는 의미는 아닙니다.' : '필터를 변경하면 다른 의심 장면을 확인할 수 있습니다.'}</p>{result.events.length > 0 && <Button variant="secondary" onClick={resetFilters}>필터 초기화</Button>}</EmptyState></section>}
    </div><aside className="panel scene-sidebar" aria-labelledby="scene-list-heading"><div className="scene-list-heading"><div className="section-title"><h2 id="scene-list-heading">의심 장면 <span className="count-pill">{result.event_count}</span></h2><ListFilter size={18} aria-hidden="true" /></div><p className="small muted">장면을 선택하고 검토 상태를 남겨주세요.</p><div className="review-progress" role="status" aria-live="polite"><span><CheckCheck size={16} aria-hidden="true" />검토 완료</span><strong data-testid="review-count">{reviewedCount} / {result.event_count}</strong></div>
      <div className="list-controls"><label htmlFor="class-filter">탐지 종류<select id="class-filter" value={filter} onChange={event => setFilter(event.target.value as ClassCode | 'all')}><option value="all">전체 종류</option>{Object.entries(CLASS_LABELS).map(([code, label]) => <option value={code} key={code}>{label}</option>)}</select></label><label htmlFor="scene-sort">정렬<select id="scene-sort" value={sort} onChange={event => setSort(event.target.value as 'time' | 'score')}><option value="time">시간순</option><option value="score">AI 예측 점수 높은 순</option></select></label></div><label className="checkbox-label"><input type="checkbox" checked={unreviewedOnly} onChange={event => setUnreviewedOnly(event.target.checked)} />미검토 장면만 보기</label>
      <div className="list-result-count" role="status">표시 중 {visible.length}개<span>판단 보류도 검토에 포함</span></div></div>
      <div className="scene-list" role="group" aria-label="의심 장면 목록" tabIndex={0}>{visible.length > 0 ? visible.map(event => { const review = jobReviews[event.event_id] ?? 'unreviewed'; return <button key={event.event_id} className={`scene-row ${selected?.event_id === event.event_id ? 'is-selected' : ''}`} aria-pressed={selected?.event_id === event.event_id} aria-label={`${CLASS_LABELS[event.class_name]} ${formatTime(event.representative_time_sec)} ${REVIEW_LABELS[review]}`} onClick={() => setSelectedId(event.event_id)} data-testid="scene-row" data-event-id={event.event_id}>
        <span className="scene-thumbnail"><SceneImage src={event.image_url} alt="개발용 예시 이미지" compact /></span><span className="scene-row-content"><span className="row-title">{CLASS_LABELS[event.class_name]}<span className="row-time">{formatTime(event.representative_time_sec)}</span></span><span className="row-code">{event.class_name} · AI {event.max_confidence.toFixed(2)}</span><span className={`review-tag review-${review}`}>{review !== 'unreviewed' && <CircleCheck size={12} aria-hidden="true" />}{REVIEW_LABELS[review]}</span></span>
      </button> }) : <EmptyState title={result.events.length === 0 ? '의심 장면이 없습니다' : '필터 결과가 없습니다'}><p>{result.events.length === 0 ? '의심 구간이 없는 개발용 예시입니다.' : '다른 종류나 검토 상태로 찾아보세요.'}</p>{result.events.length > 0 && <Button variant="secondary" onClick={resetFilters}>필터 초기화</Button>}</EmptyState>}</div>
      <p className="review-storage-note">검토 상태는 이 페이지 세션에만 유지됩니다. 새로고침·페이지 종료 시 초기화될 수 있으며 서버에 저장되지 않습니다.</p>
    </aside></div>
  </main>
}
function FilmIcon() { return <ScanLine size={17} aria-hidden="true" /> }
