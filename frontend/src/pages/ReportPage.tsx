import { useState, type ReactNode } from 'react'
import { ArrowLeft, ImageOff, Printer, RefreshCw, ShieldAlert } from 'lucide-react'
import { Link, useLocation, useParams } from 'react-router'
import { apiUrl, errorMessage, getJobReport } from '../api/client'
import type { JobReport, ReviewState } from '../api/types'
import { useJobQuery } from '../api/useJobQuery'
import { Button } from '../components/ui'
import { CLASS_LABELS, REVIEW_LABELS, SERVICE_NAME } from '../config/service'
import { formatSceneTime } from '../features/results/helpers'
import { waitForPendingReviews } from '../features/results/useJobReviews'

const dateFormat = new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeStyle: 'long' })
const numberFormat = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 3 })
const formatNumber = (value: number) => numberFormat.format(value)
const reviewStates = Object.keys(REVIEW_LABELS) as ReviewState[]

async function loadReport(jobId: string, signal: AbortSignal) {
  await waitForPendingReviews(jobId, signal)
  return getJobReport(jobId, signal)
}

function ReportTime({ value }: { value: string | null }) {
  if (value === null) return '시각 미확인'
  // 시간대 없는 과거 작업 시각은 기존 서버 저장 기준인 UTC로 해석한다.
  const timestamp = /(?:Z|[+-]\d\d:\d\d)$/i.test(value) ? value : `${value}Z`
  return <time dateTime={timestamp}>{dateFormat.format(new Date(timestamp))}</time>
}

export function ReportPage() {
  const { jobId = '' } = useParams()
  const [revision, setRevision] = useState(0)
  return <ReportSnapshot key={`${jobId}/${revision}`} jobId={jobId} refresh={() => setRevision(value => value + 1)} />
}

function ReportSnapshot({ jobId, refresh }: { jobId: string; refresh: () => void }) {
  const { state } = useLocation()
  const { data, error } = useJobQuery(jobId, loadReport)
  const returnLink = <Link to={`/jobs/${jobId}/results`} state={data
    ? { filename: data.job.original_filename, historyPath: state?.historyPath } : state} className="button button-secondary">
    <ArrowLeft size={17} aria-hidden="true" />결과 화면으로 돌아가기
  </Link>
  if (data) return <ReportContents report={data} refresh={refresh} returnLink={returnLink} />
  return <main className="page report-page" data-print-ready="false">
    <div className="report-controls button-row">{returnLink}</div>
    <section className="panel report-section report-screen-status">
      <h1>영상 분석 리포트</h1>
      {error === undefined ? <p role="status">리포트를 불러오고 있습니다.</p> : <>
        <div role="alert"><strong>리포트를 불러오지 못했습니다.</strong><p>{errorMessage(error)}</p></div>
        <Button type="button" variant="secondary" onClick={refresh}>리포트 다시 불러오기</Button>
      </>}
    </section>
    <p className="report-print-blocked">인쇄할 수 있는 리포트가 없습니다. 화면에서 조회 및 이미지 상태를 확인해 주세요.</p>
  </main>
}

type ReportImage = { status: 'loading' | 'loaded' | 'failed'; attempt: number }

function ReportContents({ report, refresh, returnLink }: {
  report: JobReport; refresh: () => void; returnLink: ReactNode
}) {
  const { job, results, reviews, review_summary: summary } = report
  const [images, setImages] = useState<Record<string, ReportImage>>({})
  const imageStates = results.events.map(event => images[event.event_id]?.status)
  const failedCount = imageStates.filter(status => status === 'failed').length
  const ready = imageStates.every(status => status === 'loaded')
  const reviewById = new Map(reviews.reviews.map(entry => [entry.event_id, entry.review]))
  const classCounts = { D00: 0, D10: 0, D20: 0, D40: 0 }
  for (const event of results.events) classCounts[event.class_name]++

  function imageSettled(eventId: string, attempt: number, status: 'loaded' | 'failed') {
    setImages(previous => ({ ...previous, [eventId]: { attempt, status } }))
  }

  function retryImages() {
    setImages(previous => Object.fromEntries(Object.entries(previous).map(([id, image]) => [id,
      image.status === 'failed' ? { status: 'loading', attempt: image.attempt + 1 } : image,
    ])))
  }

  return <main className="page report-page" data-print-ready={ready}>
    <div className="report-controls button-row">
      {returnLink}
      <Button type="button" variant="secondary" onClick={refresh}><RefreshCw size={16} aria-hidden="true" />최신 리포트 다시 불러오기</Button>
      <Button type="button" disabled={!ready} onClick={() => window.print()}><Printer size={18} aria-hidden="true" />PDF로 저장 / 인쇄</Button>
    </div>
    <aside className="panel report-notice" aria-label="인쇄 및 공유 안내">
      <ShieldAlert size={20} aria-hidden="true" />
      <div>
        <p>이 리포트는 조회 시점의 저장 상태를 담습니다. 최근에 저장한 검토는 리포트를 다시 불러오면 반영됩니다.</p>
        <p>브라우저 인쇄 창에서 <strong>PDF로 저장</strong>을 선택하고, 추가 설정에서 <strong>머리글과 바닥글</strong>을 해제하세요.</p>
        <p>대표 이미지에 차량번호, 얼굴, 위치정보가 포함될 수 있습니다. 외부 공유 전 사용 권한과 비식별화 필요성을 확인하세요.</p>
        {failedCount > 0 ? <div className="report-image-alert">
          <p role="alert">대표 이미지 {failedCount}개를 불러오지 못했습니다. 다시 불러온 뒤 인쇄할 수 있습니다.</p>
          <Button type="button" variant="secondary" onClick={retryImages}>대표 이미지 다시 불러오기</Button>
        </div> : !ready && <p role="status">인쇄에 필요한 대표 이미지를 불러오고 있습니다.</p>}
      </div>
    </aside>
    <p className="report-print-blocked">인쇄 준비가 필요합니다. 화면에서 모든 대표 이미지가 표시된 뒤 다시 시도해 주세요.</p>
    <div className="report-document">
      <header className="panel report-section report-title">
        <p className="report-service">{SERVICE_NAME}</p>
        <h1>영상 분석 리포트</h1>
        <dl className="report-metadata">
          <div className="report-file report-filename"><dt>원본 파일명</dt><dd>{job.original_filename ?? '파일명 미확인'}</dd></div>
          <div className="report-file"><dt>작업 ID</dt><dd>{job.job_id}</dd></div>
          <div><dt>분석 시작 시각</dt><dd><ReportTime value={job.started_at} /></dd></div>
          <div><dt>분석 완료 시각</dt><dd><ReportTime value={job.finished_at} /></dd></div>
          <div><dt>리포트 조회 시각</dt><dd><ReportTime value={report.exported_at} /></dd></div>
          <div><dt>영상 길이</dt><dd>{results.video.duration_sec === null ? '시간 정보 없음' : formatSceneTime(results.video.duration_sec)}</dd></div>
          <div><dt>해상도 및 프레임 속도</dt><dd>{results.video.width} × {results.video.height} · {formatNumber(results.video.fps)} FPS</dd></div>
        </dl>
      </header>
      <section className="panel report-section" aria-labelledby="report-analysis">
        <h2 id="report-analysis">AI 분석 요약</h2>
        <dl className="report-metrics">
          <div><dt>분석 프레임</dt><dd>{formatNumber(results.inferred_frame_count)}장</dd></div>
          <div><dt>탐지 박스</dt><dd>{formatNumber(results.detection_count)}개</dd></div>
          <div><dt>전체 의심 장면</dt><dd>{formatNumber(results.event_count)}건</dd></div>
          <div><dt>AI 영상 분석 소요 시간</dt><dd>{formatNumber(results.analysis_seconds)}초</dd></div>
        </dl>
        <h3>클래스별 의심 장면</h3>
        <dl className="report-metrics report-class-counts">
          {Object.keys(classCounts).map(key => {
            const code = key as keyof typeof classCounts
            return <div key={code}><dt>{CLASS_LABELS[code]} ({code})</dt><dd>{formatNumber(classCounts[code])}건</dd></div>
          })}
        </dl>
      </section>
      <section className="panel report-section" aria-labelledby="report-reviews">
        <h2 id="report-reviews">사용자 검토 요약</h2>
        <p className="report-reviewed-count">검토한 장면 <strong>{formatNumber(summary.reviewed_count)} / {formatNumber(results.event_count)}건</strong></p>
        <dl className="report-metrics">
          {reviewStates.map(state => <div key={state}><dt>{REVIEW_LABELS[state]}</dt><dd>{formatNumber(summary[state])}건</dd></div>)}
        </dl>
      </section>
      <section className="report-scenes" aria-labelledby="report-scenes-heading">
        <h2 id="report-scenes-heading">장면별 상세 기록</h2>
        {!results.events.length && <p className="panel report-section">AI가 검토할 의심 장면을 찾지 못했습니다. 전체 의심 장면 0건입니다.</p>}
        {results.events.map(event => {
          const image = images[event.event_id]
          const attempt = image?.attempt ?? 0
          const src = new URL(apiUrl(event.image_url))
          if (attempt) src.searchParams.set('retry', `${report.exported_at}/${attempt}`)
          const review = reviewById.get(event.event_id) ?? 'unreviewed'
          return <article className="panel report-scene" key={event.event_id} aria-labelledby={`report-${event.event_id}`}>
            <div className="report-scene-image">
              {image?.status === 'failed' ? <p><ImageOff size={22} aria-hidden="true" />대표 이미지 없음</p>
                : <img key={attempt} src={src.href} alt={`${event.event_id} 대표 장면`}
                    onLoad={() => imageSettled(event.event_id, attempt, 'loaded')}
                    onError={() => imageSettled(event.event_id, attempt, 'failed')} />}
            </div>
            <div className="report-scene-info">
              <h3 id={`report-${event.event_id}`}>{event.event_id}</h3>
              <dl className="report-metadata">
                <div><dt>대표 영상 시각</dt><dd>{formatSceneTime(event.representative_time_sec)}</dd></div>
                <div><dt>대표 프레임 번호</dt><dd>{formatNumber(event.representative_frame_index)}</dd></div>
                <div><dt>AI 예측 클래스</dt><dd>{CLASS_LABELS[event.class_name]} ({event.class_name})</dd></div>
                <div><dt>AI 예측 점수</dt><dd>{event.max_confidence.toFixed(2)}</dd></div>
                <div><dt>사용자 검토 상태</dt><dd><span className={`review-tag review-${review}`}>{REVIEW_LABELS[review]}</span></dd></div>
              </dl>
            </div>
          </article>
        })}
      </section>
      <section className="panel report-section" aria-labelledby="report-limitations">
        <h2 id="report-limitations">분석 한계 및 활용 안내</h2>
        <ul>
          <li>의심 장면 수는 검토 대상 구간의 수입니다. 실제 파손 개수는 현장 확인이 필요합니다.</li>
          <li>AI 예측 점수는 모델의 탐지 점수입니다. 파손 여부와 위험도는 별도 판단이 필요합니다.</li>
          <li>사용자 검토는 별도의 정답 검증을 거치지 않은 의견일 수 있습니다.</li>
          <li>이 리포트는 영상 검토 기록입니다. 공식 도로 안전 진단 또는 신고 자료로 사용할 수 없습니다.</li>
        </ul>
      </section>
    </div>
  </main>
}
