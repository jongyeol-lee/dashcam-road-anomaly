import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { Scene } from '../../api/types'
import { CLASS_LABELS } from '../../config/service'
import { formatSceneTime, formatTime, timelinePosition } from './helpers'

const markerWidth = 38
const markerGap = 4

interface MarkerGroup {
  events: Scene[]
  start: number
  end: number
}

function groupMarkers(events: Scene[], duration: number | null, trackWidth: number) {
  if (trackWidth <= 0) return []
  const markers = events.flatMap(event => {
    const position = timelinePosition(event.representative_time_sec, duration)
    return position === null ? [] : [{ event, x: position * trackWidth / 100 }]
  }).sort((a, b) => a.x - b.x || a.event.event_id.localeCompare(b.event.event_id))

  const groups: MarkerGroup[] = []
  for (const { event, x } of markers) {
    const previous = groups.at(-1)
    // 인접 버튼 경계가 가까운 장면을 같은 그룹에 넣으면 그룹 사이에는 최소 간격이 남는다.
    if (previous && x - previous.end < markerWidth + markerGap) {
      previous.events.push(event)
      previous.end = x
    } else {
      groups.push({ events: [event], start: x, end: x })
    }
  }
  return groups
}

function sceneLabel(event: Scene) {
  return `${formatSceneTime(event.representative_time_sec)} · ${CLASS_LABELS[event.class_name]}`
}

export function Timeline({ events, duration, playbackTime, selectedId, onSelect, example }: {
  events: Scene[]
  duration: number | null
  playbackTime: number | null
  selectedId?: string
  onSelect: (id: string) => void
  example: boolean
}) {
  const trackRef = useRef<HTMLDivElement>(null)
  const groupRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const [trackWidth, setTrackWidth] = useState(0)
  const [opened, setOpened] = useState<{ key: string; events: Scene[] } | null>(null)
  const validDuration = duration !== null && Number.isFinite(duration) && duration > 0
  const playhead = playbackTime !== null ? timelinePosition(playbackTime, duration) : null
  const groups = useMemo(() => groupMarkers(events, duration, trackWidth), [events, duration, trackWidth])
  const openGroup = opened?.events === events ? groups.find(group => group.events.length > 1 && group.events[0].event_id === opened.key) : undefined

  useLayoutEffect(() => {
    const track = trackRef.current
    if (!validDuration || !track) return
    let width = track.getBoundingClientRect().width
    setTrackWidth(width)
    const resize = new ResizeObserver(() => {
      const nextWidth = track.getBoundingClientRect().width
      if (nextWidth === width) return
      width = nextWidth
      if (groupRef.current?.contains(document.activeElement)) track.focus({ preventScroll: true })
      setOpened(null)
      setTrackWidth(width)
    })
    resize.observe(track)
    return () => resize.disconnect()
  }, [validDuration])

  useLayoutEffect(() => {
    if (!openGroup) return
    const option = groupRef.current?.querySelector<HTMLButtonElement>('button[aria-pressed="true"]')
      ?? groupRef.current?.querySelector<HTMLButtonElement>('button')
    option?.focus({ preventScroll: true })
    option?.scrollIntoView({ block: 'nearest' })
  }, [openGroup])

  function closeGroup(restoreFocus: boolean) {
    if (restoreFocus) triggerRef.current?.focus({ preventScroll: true })
    setOpened(null)
  }

  return <section className="timeline-panel" aria-labelledby="timeline-heading" onKeyDown={event => {
    if (event.key === 'Escape' && openGroup) {
      event.preventDefault()
      closeGroup(true)
    }
  }}>
    <div className="section-title">
      <h2 id="timeline-heading">의심 구간 타임라인</h2>
      <span className="small muted">{playhead === null ? '대표 시각 기준' : `재생 위치 · ${formatTime(playbackTime)}`}</span>
    </div>
    {validDuration ? <><div ref={trackRef} className="timeline-track" role="group" aria-label="의심 구간 위치" tabIndex={-1}>
      {playhead !== null && <span className="timeline-playhead" style={{ left: `${playhead}%` }} aria-hidden="true" />}
      {groups.map(group => {
        const first = group.events[0]
        const grouped = group.events.length > 1
        const expanded = openGroup === group
        const selected = group.events.some(event => event.event_id === selectedId)
        const label = grouped ? `${formatSceneTime(first.representative_time_sec)} 근처 장면 ${group.events.length}개${selected ? ' · 선택한 장면 포함' : ''}` : `${sceneLabel(first)} 선택`
        return <button type="button" key={first.event_id} ref={expanded ? triggerRef : undefined}
          style={{ left: `${100 * (group.start + group.end) / (2 * trackWidth)}%`, width: markerWidth }}
          className={`timeline-marker${selected ? ' selected' : ''}`} aria-pressed={grouped ? undefined : selected}
          aria-expanded={grouped ? expanded : undefined} aria-controls={expanded ? 'timeline-group-scenes' : undefined}
          aria-label={label} title={label} data-event-ids={group.events.map(event => event.event_id).join(' ')}
          onClick={() => {
            if (!grouped) {
              closeGroup(false)
              onSelect(first.event_id)
            } else if (expanded) {
              closeGroup(true)
            } else {
              setOpened({ key: first.event_id, events })
            }
          }}>
          {grouped ? <span className="timeline-marker-count" aria-hidden="true">{group.events.length}</span>
            : <span className="timeline-marker-dot" aria-hidden="true" />}
        </button>
      })}
    </div><div className="timeline-ends"><span>{formatTime(0)}</span><span>{formatTime(duration)}</span></div></> : <p className="small muted timeline-unavailable">영상 길이 정보가 없어 구간 위치를 표시할 수 없습니다. 목록에서 장면을 선택해 주세요.</p>}
    {openGroup && <div ref={groupRef} id="timeline-group-scenes" className="timeline-group-scenes" role="group" aria-label="모아 표시한 의심 장면">
      {openGroup.events.map(event => <button type="button" key={event.event_id} data-event-id={event.event_id}
        aria-pressed={event.event_id === selectedId} onClick={() => { closeGroup(true); onSelect(event.event_id) }}>
        <span>{sceneLabel(event)}</span><small>{event.event_id}</small>
      </button>)}
    </div>}
    {validDuration && events.length > 0 && <p className="small muted">{example ? '마커에서 대표 장면을 선택하세요.' : '장면을 선택하면 해당 시각으로 이동합니다.'}</p>}
  </section>
}
