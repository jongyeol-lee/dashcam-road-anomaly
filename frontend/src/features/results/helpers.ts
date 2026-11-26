import type { ClassCode, ReviewState, Scene } from '../../api/types'
import type { ReviewValues } from './useJobReviews'

export function formatTime(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds) || seconds < 0) return '시간 정보 없음'
  const whole = Math.floor(seconds)
  const minutes = Math.floor(whole / 60)
  const sec = String(whole % 60).padStart(2, '0')
  return minutes >= 60
    ? `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, '0')}:${sec}`
    : `${String(minutes).padStart(2, '0')}:${sec}`
}

export function formatSceneTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return formatTime(seconds)
  const milliseconds = Math.round(seconds * 1000)
  const whole = formatTime(Math.floor(milliseconds / 1000))
  const fraction = String(milliseconds % 1000).padStart(3, '0').replace(/0+$/, '')
  return fraction ? `${whole}.${fraction}` : whole
}

export function timelinePosition(time: number, duration: number | null): number | null {
  // 메타데이터가 없거나 범위 밖이면 임의의 영상 길이·위치를 만들지 않는다.
  if (duration === null || !Number.isFinite(duration) || duration <= 0
    || !Number.isFinite(time) || time < 0 || time > duration) return null
  return time / duration * 100
}

export function visibleScenes(
  events: Scene[], filter: ClassCode | 'all', sort: 'time' | 'score', reviewFilter: ReviewState | 'all', reviews?: ReviewValues,
): Scene[] {
  return events.filter(event => (filter === 'all' || event.class_name === filter)
    && (reviewFilter === 'all' || (reviews !== undefined && (reviews[event.event_id] ?? 'unreviewed') === reviewFilter)))
    .sort((a, b) => (sort === 'score' ? b.max_confidence - a.max_confidence : 0)
      || a.representative_time_sec - b.representative_time_sec || a.event_id.localeCompare(b.event_id))
}
