import type { ClassCode, Scene } from '../../api/types'

export function formatTime(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds) || seconds < 0) return '시간 정보 없음'
  const whole = Math.floor(seconds)
  const minutes = Math.floor(whole / 60)
  const sec = String(whole % 60).padStart(2, '0')
  return minutes >= 60
    ? `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, '0')}:${sec}`
    : `${String(minutes).padStart(2, '0')}:${sec}`
}

export function timelinePosition(time: number, duration: number | null): number | null {
  // 메타데이터가 없거나 범위 밖이면 임의의 영상 길이·위치를 만들지 않는다.
  if (duration === null || !Number.isFinite(duration) || duration <= 0
    || !Number.isFinite(time) || time < 0 || time > duration) return null
  return time / duration * 100
}

export function visibleScenes(events: Scene[], filter: ClassCode | 'all', sort: 'time' | 'score', unreviewedOnly: boolean, reviews: Record<string, string>): Scene[] {
  return events.filter(event => (filter === 'all' || event.class_name === filter)
    && (!unreviewedOnly || !reviews[event.event_id] || reviews[event.event_id] === 'unreviewed'))
    .sort((a, b) => (sort === 'score' ? b.max_confidence - a.max_confidence : 0)
      || a.representative_time_sec - b.representative_time_sec || a.event_id.localeCompare(b.event_id))
}
