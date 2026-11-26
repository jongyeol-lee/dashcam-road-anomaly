import type { Scene } from '../../api/types'
import { CLASS_LABELS } from '../../config/service'
import { formatTime, timelinePosition } from './helpers'

export function Timeline({ events, duration, selectedId, onSelect }: { events: Scene[]; duration: number | null; selectedId?: string; onSelect: (id: string) => void }) {
  const validDuration = duration !== null && Number.isFinite(duration) && duration > 0
  return <section className="timeline-panel" aria-labelledby="timeline-heading"><div className="section-title"><h2 id="timeline-heading">의심 구간 타임라인</h2><span className="small muted">대표 시각 기준</span></div>
    {validDuration ? <><div className="timeline-track" aria-label="의심 구간 위치">{events.map(event => {
      const position = timelinePosition(event.representative_time_sec, duration)
      return position === null ? null : <button key={event.event_id} style={{ left: `${position}%` }} className={`timeline-marker ${selectedId === event.event_id ? 'selected' : ''}`} aria-pressed={selectedId === event.event_id} aria-label={`${formatTime(event.representative_time_sec)} ${CLASS_LABELS[event.class_name]} 선택`} title={`${formatTime(event.representative_time_sec)} · ${CLASS_LABELS[event.class_name]}`} onClick={() => onSelect(event.event_id)}><span /></button>
    })}</div><div className="timeline-ends"><span>{formatTime(0)}</span><span>{formatTime(duration)}</span></div></> : <p className="small muted timeline-unavailable">영상 길이 정보가 없어 구간 위치를 표시할 수 없습니다. 목록에서 장면을 선택해 주세요.</p>}
    <p className="small muted">표시를 누르면 대표 장면이 선택됩니다. 현재 영상 재생 시점은 이동하지 않습니다.</p>
  </section>
}
