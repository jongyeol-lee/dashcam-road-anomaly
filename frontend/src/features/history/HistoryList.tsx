import { ArrowRight, CircleAlert, FileVideo, LoaderCircle } from 'lucide-react'
import { Link } from 'react-router'
import type { JobHistoryItem, JobHistoryWarning } from '../../api/types'
import { Button, JobInfo, StatusBadge } from '../../components/ui'
import { REVIEW_LABELS } from '../../config/service'
import { formatTime } from '../results/helpers'
import { formatFileSize } from '../upload/validation'

const dateFormat = new Intl.DateTimeFormat('ko-KR', {
  year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
  hourCycle: 'h23',
})
const reviewStates = ['suspected', 'false_positive', 'deferred'] as const
const detailLabels = {
  completed: '결과 확인', queued: '상태 확인', running: '상태 확인', failed: '실패 내용 확인',
}
const warningMessages: Record<string, string> = {
  job_data_unavailable: '일부 작업 정보를 읽을 수 없어 목록과 전체 건수에서 제외했습니다.',
  results_unavailable: '일부 작업의 분석 및 검토 요약을 확인할 수 없습니다.',
  review_data_invalid: '일부 작업의 검토 데이터가 올바르지 않아 검토 요약을 확인할 수 없습니다.',
  review_read_failed: '일부 작업의 검토 데이터를 읽을 수 없습니다.',
  upload_size_unavailable: '일부 작업의 파일 크기를 확인할 수 없습니다.',
}

export function HistoryWarnings({ warnings }: { warnings: JobHistoryWarning[] }) {
  if (!warnings.length) return null
  const messages = new Set(warnings.map(({ error }) => Object.hasOwn(warningMessages, error.code)
    ? warningMessages[error.code] : error.message))
  return <div className="history-warning" role="status">
    <CircleAlert size={18} aria-hidden="true" />
    <div><strong>일부 이력 확인 필요</strong>{[...messages].map(message => <p key={message}>{message}</p>)}</div>
  </div>
}

export function HistoryRequestStatus({ busy, hasData, error, refresh }: {
  busy: boolean; hasData: boolean; error?: string; refresh: () => void
}) {
  return <>
    <p className="history-loading muted small" role="status">{busy && <>
      <LoaderCircle size={16} className="animate-spin" aria-hidden="true" />
      {hasData ? '분석 이력을 다시 불러오고 있습니다.' : '분석 이력을 불러오고 있습니다.'}
    </>}</p>
    {error && <div className="history-error">
      <div role="alert"><strong>분석 이력을 불러오지 못했습니다.</strong><p>{error}</p>
        {hasData && <p>마지막으로 불러온 이력을 표시합니다.</p>}
      </div>
      <Button type="button" variant="secondary" onClick={refresh}>다시 시도</Button>
    </div>}
  </>
}

export function HistoryList({ items, historyPath }: {
  items: JobHistoryItem[]; historyPath?: string
}) {
  const full = historyPath !== undefined
  return <ul className={`history-list ${full ? 'history-list-full' : ''}`} aria-label={full ? '분석 작업 목록' : '최근 분석 작업 목록'}>
    {items.map(job => {
      const filename = job.original_filename ?? '파일명 미확인'
      const completed = job.status === 'completed'
      const { analysis, reviews } = job
      const path = `/jobs/${job.job_id}${completed ? '/results' : ''}`
      // 시간대가 없는 과거 데이터는 서버의 저장 기준인 UTC로 해석한다.
      const timestamp = /(?:Z|[+-]\d\d:\d\d)$/i.test(job.created_at) ? job.created_at : `${job.created_at}Z`
      const createdAt = dateFormat.format(new Date(timestamp))
      return <li className="history-row" key={job.job_id}>
        <div className="history-file">
          <span className="history-file-icon"><FileVideo size={19} aria-hidden="true" /></span>
          <div>
            <h3 className="filename">{filename}</h3>
            <p className="small muted"><time dateTime={timestamp}>{createdAt}</time></p>
            {full && <p className="small muted">{job.file_size_bytes === null ? '파일 크기 미확인' : formatFileSize(job.file_size_bytes)}</p>}
            <JobInfo jobId={job.job_id} />
          </div>
        </div>
        <div className="history-status"><StatusBadge phase={job.status} /></div>
        <div className="history-summary">
          {completed ? <>
            <p className={analysis ? undefined : 'muted'}>
              {analysis ? <><strong>의심 장면 {analysis.event_count.toLocaleString('ko-KR')}건</strong>
                {full && <span className="history-duration"> · 영상 {formatTime(analysis.video.duration_sec)}</span>}</> : '분석 요약 미확인'}
            </p>
            <p className="muted">{analysis && reviews
              ? <>검토한 장면 <strong>{reviews.reviewed_count.toLocaleString('ko-KR')} / {analysis.event_count.toLocaleString('ko-KR')}건</strong></>
              : '검토 요약 미확인'}</p>
            {full && reviews && <ul className="history-review-counts" aria-label="사용자 검토 요약">
              {reviewStates.map(state => <li key={state}>{REVIEW_LABELS[state]} <strong>{reviews[state].toLocaleString('ko-KR')}건</strong></li>)}
            </ul>}
          </> : <p className="muted">{job.status === 'failed' ? '검토할 분석 결과 없음' : '분석 후 장면 검토 가능'}</p>}
        </div>
        <Link to={path} state={{ filename: job.original_filename, historyPath: historyPath ?? '/history' }} className="button button-secondary history-detail">
          {detailLabels[job.status]}<span className="sr-only"> · {filename} · {createdAt}</span><ArrowRight size={15} aria-hidden="true" />
        </Link>
      </li>
    })}
  </ul>
}
