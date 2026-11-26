import type { Scene } from '../../api/types'
import { CLASS_LABELS, REVIEW_LABELS, type ReviewState } from '../../config/service'
import { SceneImage } from './SceneImage'
import { formatTime } from './helpers'

export function SceneDetail({ event, imageSrc, example, review, onReview, onRetryImage }: {
  event: Scene
  imageSrc: string
  example: boolean
  review: ReviewState
  onReview: (review: ReviewState) => void
  onRetryImage: () => void
}) {
  return <section className="panel scene-detail" aria-labelledby="detail-heading" data-testid="scene-detail">
    <div className="panel-heading"><h2 id="detail-heading">선택한 대표 장면</h2><span className="small muted">{event.event_id}</span></div>
    <div className="detail-body"><div className="detail-image">
      <SceneImage src={imageSrc} alt={`${CLASS_LABELS[event.class_name]} ${example ? '예시' : '대표'} 장면`} onRetry={onRetryImage} />
      {example && <span className="sample-tag">예시 이미지</span>}
    </div>
      <div className="detail-info"><div className="detail-title"><h3>{CLASS_LABELS[event.class_name]}</h3><span className="code-label">{event.class_name}</span></div>
        <dl className="detail-metrics"><div><dt>구간 시작</dt><dd>{formatTime(event.start_time_sec)}</dd></div><div><dt>마지막 탐지</dt><dd>{formatTime(event.last_detection_time_sec)}</dd></div><div><dt>대표 시각</dt><dd>{formatTime(event.representative_time_sec)}</dd></div><div><dt>AI 예측 점수</dt><dd>{event.max_confidence.toFixed(2)} <span className="small muted">/ 1</span></dd></div><div><dt>탐지 박스</dt><dd>{event.detection_count}개</dd></div><div><dt>탐지 프레임</dt><dd>{event.detected_frame_count}장</dd></div></dl>
        <p className="score-note">AI 점수는 모델의 예측 점수이며, 파손 확률이나 위험 등급이 아닙니다.</p>
      </div></div>
    <fieldset className="review-fieldset"><legend>이 장면을 어떻게 보셨나요?</legend><div className="review-options">{Object.entries(REVIEW_LABELS).map(([value, label]) => <label key={value} className={`review-option ${review === value ? 'checked' : ''}`}><input type="radio" name={`review-${event.event_id}`} value={value} checked={review === value} onChange={() => onReview(value as ReviewState)} />{label}</label>)}</div></fieldset>
  </section>
}
