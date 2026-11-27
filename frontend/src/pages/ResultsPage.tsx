import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router'
import { CheckCheck, FileVideo, ListFilter, Plus, ScanLine, CircleCheck, Info } from 'lucide-react'
import type { AnalysisResults, ClassCode, ReviewState } from '../api/types'
import { ApiRequestError, apiUrl, errorMessage, getResults } from '../api/client'
import { useJobQuery } from '../api/useJobQuery'
import { Button, EmptyState, HistoryBackLink, JobInfo, JobNotice, StatusBadge } from '../components/ui'
import { CLASS_LABELS, REVIEW_LABELS } from '../config/service'
import { useSession } from '../mocks/SessionContext'
import { ResultExports } from '../features/results/ResultExports'
import { ReviewFeedback, SceneDetail } from '../features/results/SceneDetail'
import { SceneImage } from '../features/results/SceneImage'
import { Timeline } from '../features/results/Timeline'
import { VideoPanel } from '../features/results/VideoPanel'
import { formatSceneTime, formatTime, visibleScenes } from '../features/results/helpers'
import { useJobReviews, type ReviewChange, type ReviewValues } from '../features/results/useJobReviews'

type SceneSelectionSource = 'list' | 'timeline' | 'navigation'

function selectedSceneRow(list: HTMLDivElement | null) {
  return list?.querySelector<HTMLButtonElement>('.scene-row[aria-pressed="true"]')
}

export function ResultsPage() {
  const { jobId = '' } = useParams()
  const { state } = useLocation()
  const filename = typeof state?.filename === 'string' ? state.filename : undefined
  return <LiveResults key={jobId} jobId={jobId} filename={filename} />
}

function LiveResults({ jobId, filename }: { jobId: string; filename?: string }) {
  const { data: result, error, retry } = useJobQuery(jobId, getResults)
  if (result) return <LiveReviewWorkspace result={result} filename={filename} />
  if (error instanceof ApiRequestError && error.status === 404) {
    return <JobNotice title="작업을 찾을 수 없습니다"><p>{error.message}</p></JobNotice>
  }
  const statusPath = `/jobs/${jobId}`
  if (error instanceof ApiRequestError && error.status === 409) {
    return <JobNotice title="아직 완료된 결과가 없습니다" backTo={statusPath} backLabel="분석 상태 확인" />
  }
  if (error !== undefined) {
    return <JobNotice title="결과를 불러오지 못했습니다" backTo={statusPath} backLabel="분석 상태 확인">
      <p role="alert">{errorMessage(error)}</p><Button onClick={retry}>결과 다시 불러오기</Button>
    </JobNotice>
  }
  return <main className="page narrow"><div className="panel status-panel" role="status">분석 결과를 불러오고 있습니다.</div></main>
}

function LiveReviewWorkspace({ result, filename }: { result: AnalysisResults; filename?: string }) {
  const { values, error, retry, changes, latestEventId, update } = useJobReviews(result.job_id)
  return <ResultsWorkspace result={result} filename={filename} jobReviews={values} onReview={update}
    reviewError={error === undefined ? undefined : errorMessage(error)} onRetryReviews={retry}
    reviewChanges={changes} latestReviewEventId={latestEventId} />
}

export function ExampleResultsPage() {
  const { jobId = '' } = useParams()
  const { jobs, reviews, setReview } = useSession()
  const entry = Object.hasOwn(jobs, jobId) ? jobs[jobId] : undefined
  if (!entry) return <JobNotice title="예시 작업을 찾을 수 없습니다" />
  if (entry.phase !== 'completed') {
    return <JobNotice title="아직 완료된 결과가 없습니다" backTo={`/examples/jobs/${jobId}`} backLabel="예시 분석 상태 확인" />
  }
  return <ResultsWorkspace key={jobId} result={entry.result} example jobReviews={reviews[jobId] ?? {}}
    onReview={(eventId, review) => setReview(jobId, eventId, review)} />
}

function ResultsWorkspace({
  result, filename, example = false, jobReviews, onReview, reviewError, onRetryReviews, reviewChanges, latestReviewEventId,
}: {
  result: AnalysisResults
  filename?: string
  example?: boolean
  jobReviews?: ReviewValues
  onReview: (eventId: string, review: ReviewState) => void
  reviewError?: string
  onRetryReviews?: () => void
  reviewChanges?: Partial<Record<string, ReviewChange>>
  latestReviewEventId?: string
}) {
  const [selection, setSelection] = useState<{ id?: string; source?: SceneSelectionSource }>({
    id: result.events[0]?.event_id,
  })
  const [filter, setFilter] = useState<ClassCode | 'all'>('all')
  const [sort, setSort] = useState<'time' | 'score'>('time')
  const [reviewFilter, setReviewFilter] = useState<ReviewState | 'all'>('all')
  const [seekRequest, setSeekRequest] = useState<{ seconds: number }>()
  const [playbackTime, setPlaybackTime] = useState<number | null>(null)
  const [playbackDuration, setPlaybackDuration] = useState<number | null>(null)
  const [imageRetries, setImageRetries] = useState<Record<string, number>>({})
  const listRef = useRef<HTMLDivElement>(null)
  const detailHeadingRef = useRef<HTMLHeadingElement>(null)
  const visible = useMemo(() => visibleScenes(result.events, filter, sort, reviewFilter, jobReviews),
    [result.events, filter, sort, reviewFilter, jobReviews])
  const selectedIndex = Math.max(0, visible.findIndex(event => event.event_id === selection.id))
  const selected = visible[selectedIndex]
  const counts = useMemo(() => {
    if (!jobReviews) return
    const totals = { unreviewed: 0, suspected: 0, false_positive: 0, deferred: 0 }
    for (const { event_id } of result.events) totals[jobReviews[event_id] ?? 'unreviewed']++
    return totals
  }, [jobReviews, result.events])
  const videoSource = example ? result.video_url : apiUrl(result.video_url)
  const imageSource = (path: string) => example ? path : apiUrl(path)

  useLayoutEffect(() => {
    if (!selection.source) return
    if (window.matchMedia('(max-width: 1023px)').matches) {
      if (selection.source !== 'navigation') {
        detailHeadingRef.current?.focus({ preventScroll: true })
        detailHeadingRef.current?.scrollIntoView({ block: 'start' })
      }
    } else if (selection.source !== 'list') {
      const list = listRef.current
      const row = selectedSceneRow(list)
      if (!list || !row) return
      // 전체 페이지는 건드리지 않고 목록에서 잘린 부분만 드러낸다.
      const listTop = list.getBoundingClientRect().top + list.clientTop
      const listBottom = listTop + list.clientHeight
      const bounds = row.getBoundingClientRect()
      if (bounds.top < listTop) list.scrollTop -= Math.ceil(listTop - bounds.top)
      else if (bounds.bottom > listBottom) list.scrollTop += Math.ceil(bounds.bottom - listBottom)
    }
  }, [selection])

  function selectScene(id: string, source: SceneSelectionSource) {
    const event = visible.find(scene => scene.event_id === id)
    if (!event) return
    setSelection({ id, source })
    if (!example) setSeekRequest({ seconds: event.representative_time_sec })
  }

  function navigateScene(offset: number) {
    const target = visible[selectedIndex + offset]
    if (target) selectScene(target.event_id, 'navigation')
  }

  function returnToSceneList() {
    const row = selectedSceneRow(listRef.current)
    row?.focus({ preventScroll: true })
    row?.scrollIntoView({ block: 'nearest' })
  }

  function retryThumbnail(id: string) {
    setImageRetries(previous => ({ ...previous, [id]: (previous[id] ?? 0) + 1 }))
  }

  function resetFilters() { setFilter('all'); setReviewFilter('all') }

  return <main className="page results-page">
    <div className="result-heading">
      <div>
        <div className="title-row"><h1>영상 분석 결과</h1><StatusBadge phase="completed" /></div>
        <p className="video-meta"><FileVideo size={16} aria-hidden="true" />
          <strong>{filename ?? (example ? '개발용 예시 영상' : '원본 영상')}</strong>
          <span>· {formatTime(result.video.duration_sec)}</span><span>· {result.video.width} × {result.video.height} · {result.video.fps} fps</span>
        </p>
        <JobInfo jobId={result.job_id} />
      </div>
      <div className="button-row result-heading-actions">
        <HistoryBackLink />
        <Link to="/" className="button button-primary"><Plus size={18} aria-hidden="true" />새 영상 분석</Link>
      </div>
    </div>
    <section className="summary-strip" aria-label="분석 요약">{[
      ['분석 프레임', `${result.inferred_frame_count.toLocaleString()}장`, `추출 ${result.extracted_frame_count}장 중 추론한 프레임`],
      ['탐지 박스', `${result.detection_count.toLocaleString()}개`, '반복 탐지를 포함한 박스 수'],
      ['의심 구간', `${result.event_count}개`, '시간 기준으로 모은 검토 단위'],
      ['AI 영상 분석 시간', `${result.analysis_seconds.toLocaleString()}초`, '업로드·대기 제외'],
    ].map(([label, value, help]) => <div className="summary-item" key={label}><span>{label}</span><strong>{value}</strong><small>{help}</small></div>)}</section>
    <p className="summary-caption"><Info size={15} aria-hidden="true" />박스·구간 수는 실제 파손 개수가 아닙니다.{example && ' 이 화면의 수치와 장면은 예시입니다.'}</p>
    {!example && <ResultExports jobId={result.job_id} eventCount={result.event_count}
      saving={(!jobReviews && !reviewError) || Object.values(reviewChanges ?? {}).some(change => change?.status === 'saving')}
      failed={Object.values(reviewChanges ?? {}).some(change => change?.status === 'failed')} />}
    <div className="workspace-grid"><div className="workspace-main">
      <section className="panel video-panel">
        <div className="panel-heading"><h2><ScanLine size={17} aria-hidden="true" />원본 영상</h2></div>
        <VideoPanel src={videoSource} seekRequest={seekRequest} onTimeChange={setPlaybackTime} onDurationChange={setPlaybackDuration} />
        <Timeline events={visible} duration={playbackDuration ?? result.video.duration_sec} playbackTime={playbackTime}
          selectedId={selected?.event_id} onSelect={id => selectScene(id, 'timeline')} example={example} />
      </section>
      {selected ? <SceneDetail event={selected} imageSrc={imageSource(selected.image_url)} example={example}
        headingRef={detailHeadingRef} index={selectedIndex} count={visible.length}
        onNavigate={navigateScene} onReturnToList={returnToSceneList}
        review={jobReviews && (jobReviews[selected.event_id] ?? 'unreviewed')} change={reviewChanges?.[selected.event_id]}
        onReview={review => onReview(selected.event_id, review)}
        onRetryImage={() => retryThumbnail(selected.event_id)} />
        : <section className="panel"><EmptyState title={result.events.length === 0 ? '표시할 대표 장면이 없습니다' : '조건에 맞는 장면이 없습니다'}>
          <p>{result.events.length === 0 ? 'AI가 검토할 의심 구간을 찾지 못했습니다.' : '필터를 변경하면 다른 의심 장면을 확인할 수 있습니다.'}</p>
          {result.events.length > 0 && <Button variant="secondary" onClick={resetFilters}>필터 초기화</Button>}
        </EmptyState></section>}
    </div><aside className="panel scene-sidebar" aria-labelledby="scene-list-heading"><div className="scene-list-heading">
      <div className="section-title"><h2 id="scene-list-heading">의심 장면 <span className="count-pill">{result.event_count}</span></h2><ListFilter size={18} aria-hidden="true" /></div>
      {counts ? <>
        <div className="review-progress" role="status"><span><CheckCheck size={16} aria-hidden="true" />검토한 장면</span>
          <strong data-testid="review-count">{result.event_count - counts.unreviewed} / {result.event_count}</strong></div>
        <dl className="review-totals" aria-label="전체 장면의 검토 현황">
          {(Object.keys(REVIEW_LABELS) as ReviewState[]).map(value =>
            <div key={value}><dt>{REVIEW_LABELS[value]}</dt><dd>{counts[value]}개</dd></div>)}
        </dl>
      </> : reviewError ? <div className="review-progress">
        <p role="alert">검토 결과를 불러오지 못했습니다. {reviewError}</p>
        <Button type="button" variant="secondary" onClick={onRetryReviews}>검토 결과 다시 불러오기</Button>
      </div> : <p className="review-progress" role="status">검토 결과를 불러오고 있습니다.</p>}
      <div className="list-controls">
        <label htmlFor="class-filter">탐지 종류<select id="class-filter" value={filter} onChange={event => setFilter(event.target.value as ClassCode | 'all')}><option value="all">전체 종류</option>{Object.entries(CLASS_LABELS).map(([code, label]) => <option value={code} key={code}>{label}</option>)}</select></label>
        <label htmlFor="scene-sort">정렬<select id="scene-sort" value={sort} onChange={event => setSort(event.target.value as 'time' | 'score')}><option value="time">시간순</option><option value="score">AI 점수 높은 순</option></select></label>
        <label className="review-filter" htmlFor="review-filter">검토 상태
          <select id="review-filter" value={reviewFilter} disabled={!jobReviews} onChange={event => setReviewFilter(event.target.value as ReviewState | 'all')}>
            <option value="all">전체 검토 상태</option>
            {Object.entries(REVIEW_LABELS).map(([value, label]) => <option value={value} key={value}>{label}</option>)}
          </select>
        </label>
      </div>
      <div className="list-result-count" role="status">표시 중 {visible.length}개</div>
      {Object.entries(reviewChanges ?? {}).map(([eventId, change]) =>
        change && eventId !== selected?.event_id && (change.status !== 'saved' || eventId === latestReviewEventId)
          ? <ReviewFeedback key={eventId} eventId={eventId} change={change} onRetry={() => onReview(eventId, change.review)} />
          : null)}
    </div>
      <div ref={listRef} className="scene-list" role="group" aria-label="의심 장면 목록" tabIndex={0}>{visible.length > 0 ? visible.map(event => {
        const review = jobReviews && (jobReviews[event.event_id] ?? 'unreviewed')
        const isSelected = selected?.event_id === event.event_id
        return <button key={event.event_id} className={`scene-row ${isSelected ? 'is-selected' : ''}`}
          aria-pressed={isSelected} aria-label={`${CLASS_LABELS[event.class_name]} ${formatSceneTime(event.representative_time_sec)}${review ? ` ${REVIEW_LABELS[review]}` : ''}`}
          onClick={() => selectScene(event.event_id, 'list')} data-testid="scene-row" data-event-id={event.event_id}>
          <span className="scene-thumbnail"><SceneImage key={imageRetries[event.event_id]} src={imageSource(event.image_url)} alt="" compact /></span>
          <span className="scene-row-content">
            <span className="row-title">{CLASS_LABELS[event.class_name]}<span className="row-time">{formatSceneTime(event.representative_time_sec)}</span></span>
            <span className="row-code">{event.class_name} · AI {event.max_confidence.toFixed(2)}</span>
            {review && <span className={`review-tag review-${review}`}>{review !== 'unreviewed' && <CircleCheck size={12} aria-hidden="true" />}{REVIEW_LABELS[review]}</span>}
          </span>
        </button>
      }) : <EmptyState title={result.events.length === 0 ? '의심 장면이 없습니다' : '필터 결과가 없습니다'}>
        {result.events.length > 0 && <><p>다른 종류나 검토 상태로 찾아보세요.</p><Button variant="secondary" onClick={resetFilters}>필터 초기화</Button></>}
      </EmptyState>}</div>
      {example && <p className="review-storage-note">예시 검토 상태는 새로고침하면 초기화됩니다.</p>}
    </aside></div>
  </main>
}
