import type { Scene } from '../../api/types'
import { CLASS_LABELS } from '../../config/service'
import { formatTime, timelinePosition } from './helpers'

export function Timeline({ events, duration, playbackTime, selectedId, onSelect, example }: {
  events: Scene[]
  duration: number | null
  playbackTime: number | null
  selectedId?: string
  onSelect: (id: string) => void
  example: boolean
}) {
  const validDuration = duration !== null && Number.isFinite(duration) && duration > 0
  const playhead = playbackTime !== null ? timelinePosition(playbackTime, duration) : null
  return <section className="timeline-panel" aria-labelledby="timeline-heading">
    <div className="section-title">
      <h2 id="timeline-heading">의심 구간 타임라인</h2>
      <span className="small muted">{playhead === null ? '대표 시각 기준' : `재생 위치 · ${formatTime(playbackTime)}`}</span>
    </div>
    {validDuration ? <><div className="timeline-track" role="group" aria-label="의심 구간 위치">
      {playhead !== null && <span className="timeline-playhead" style={{ left: `${playhead}%` }} aria-hidden="true" />}
      {events.map(event => {
      const position = timelinePosition(event.representative_time_sec, duration)
      return position === null ? null : <button key={event.event_id} style={{ left: `${position}%` }} className={`timeline-marker ${selectedId === event.event_id ? 'selected' : ''}`} aria-pressed={selectedId === event.event_id} aria-label={`${formatTime(event.representative_time_sec)} ${CLASS_LABELS[event.class_name]} 선택`} title={`${formatTime(event.representative_time_sec)} · ${CLASS_LABELS[event.class_name]}`} onClick={() => onSelect(event.event_id)}><span /></button>
    })}</div><div className="timeline-ends"><span>{formatTime(0)}</span><span>{formatTime(duration)}</span></div></> : <p className="small muted timeline-unavailable">영상 길이 정보가 없어 구간 위치를 표시할 수 없습니다. 목록에서 장면을 선택해 주세요.</p>}
    {validDuration && events.length > 0 && <p className="small muted">{example ? '표시를 누르면 대표 장면을 확인할 수 있습니다.' : '표시를 누르면 영상의 대표 시각으로 이동합니다.'}</p>}
  </section>
}
