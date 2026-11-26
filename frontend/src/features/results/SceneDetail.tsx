import type { Ref } from 'react'
import { ChevronLeft, ChevronRight, List } from 'lucide-react'
import type { ReviewState, Scene } from '../../api/types'
import { Button } from '../../components/ui'
import { CLASS_LABELS, REVIEW_LABELS } from '../../config/service'
import { ExpandableSceneImage } from './SceneImage'
import { formatSceneTime } from './helpers'
import type { ReviewChange } from './useJobReviews'

export function ReviewFeedback({ change, eventId, onRetry }: {
  change: ReviewChange
  eventId?: string
  onRetry: () => void
}) {
  const scene = eventId ? `${eventId} · ` : ''
  if (change.status === 'failed') return <div className="review-feedback">
    <p role="alert">{scene}저장 실패 · {REVIEW_LABELS[change.review]} · {change.message}</p>
    <Button type="button" variant="secondary" onClick={onRetry}>검토 저장 다시 시도</Button>
  </div>
  return <p className="review-feedback muted" role="status">
    {scene}{change.status === 'saving' ? '저장 중' : '저장 완료'} · {REVIEW_LABELS[change.review]}
  </p>
}

export function SceneDetail({
  event, imageSrc, example, headingRef, index, count, onNavigate, onReturnToList, review, change, onReview, onRetryImage,
}: {
  event: Scene
  imageSrc: string
  example: boolean
  headingRef: Ref<HTMLHeadingElement>
  index: number
  count: number
  onNavigate: (offset: number) => void
  onReturnToList: () => void
  review?: ReviewState
  change?: ReviewChange
  onReview: (review: ReviewState) => void
  onRetryImage: () => void
}) {
  const label = CLASS_LABELS[event.class_name]
  const time = formatSceneTime(event.representative_time_sec)
  const score = event.max_confidence.toFixed(2)
  return <section className="panel scene-detail" aria-labelledby="detail-heading" data-testid="scene-detail">
    <div className="panel-heading">
      <h2 id="detail-heading" ref={headingRef} tabIndex={-1}>선택한 대표 장면</h2>
      <Button type="button" variant="ghost" className="scene-list-return" onClick={onReturnToList}><List size={16} aria-hidden="true" />목록으로</Button>
      <span className="small muted scene-detail-id">{event.event_id}</span>
    </div>
    <div className="scene-navigation" role="group" aria-label="장면 탐색">
      <Button type="button" variant="secondary" disabled={index === 0} onClick={() => onNavigate(-1)}><ChevronLeft size={16} aria-hidden="true" />이전 장면</Button>
      <span role="status" aria-label="표시 장면 중 현재 위치" className="scene-navigation-position">{index + 1} / {count}</span>
      <Button type="button" variant="secondary" disabled={index === count - 1} onClick={() => onNavigate(1)}>다음 장면<ChevronRight size={16} aria-hidden="true" /></Button>
    </div>
    <div className="detail-body"><div className="detail-image">
      <ExpandableSceneImage key={event.event_id} src={imageSrc} alt={`${label} ${example ? '예시' : '대표'} 장면`}
        caption={`${label} · ${time} · AI 예측 점수 ${score}`} onRetry={onRetryImage} />
      {example && <span className="sample-tag">예시 이미지</span>}
    </div>
      <div className="detail-info"><div className="detail-title"><h3>{label}</h3><span className="code-label">{event.class_name}</span></div>
        <dl className="detail-metrics"><div><dt>구간 시작</dt><dd>{formatSceneTime(event.start_time_sec)}</dd></div><div><dt>마지막 탐지</dt><dd>{formatSceneTime(event.last_detection_time_sec)}</dd></div><div><dt>대표 시각</dt><dd>{time}</dd></div><div><dt>AI 예측 점수</dt><dd>{score} <span className="small muted">/ 1</span></dd></div><div><dt>탐지 박스</dt><dd>{event.detection_count}개</dd></div><div><dt>탐지 프레임</dt><dd>{event.detected_frame_count}장</dd></div></dl>
        <p className="score-note">AI 점수는 모델의 예측 점수이며, 파손 확률이나 위험 등급이 아닙니다.</p>
      </div></div>
    <div className="review-controls">
      <fieldset className="review-fieldset" disabled={review === undefined || change?.status === 'saving'}>
        <legend>이 장면을 어떻게 보셨나요?</legend>
        <div className="review-options">{Object.entries(REVIEW_LABELS).map(([value, label]) =>
          <label key={value} className={`review-option ${review === value ? 'checked' : ''}`}>
            <input type="radio" name={`review-${event.event_id}`} value={value} checked={review === value}
              onChange={() => onReview(value as ReviewState)} />{label}
          </label>)}</div>
      </fieldset>
      {change && <ReviewFeedback change={change} onRetry={() => onReview(change.review)} />}
    </div>
  </section>
}
