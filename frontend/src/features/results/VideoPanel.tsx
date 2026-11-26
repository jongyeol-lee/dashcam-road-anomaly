import { useEffect, useRef, useState } from 'react'
import { Film, VideoOff } from 'lucide-react'
import { Button } from '../../components/ui'

interface VideoProps {
  src: string
  seekRequest?: { seconds: number }
  onTimeChange: (seconds: number | null) => void
  onDurationChange: (seconds: number | null) => void
}

export function VideoPanel(props: VideoProps) {
  return <VideoContent key={props.src} {...props} />
}

function VideoContent({ src, seekRequest, onTimeChange, onDurationChange }: VideoProps) {
  const [failed, setFailed] = useState(false)
  const videoRef = useRef<HTMLVideoElement>(null)

  useEffect(() => {
    const video = videoRef.current
    if (!video || !seekRequest || !Number.isFinite(seekRequest.seconds) || seekRequest.seconds < 0) return
    const seconds = seekRequest.seconds
    const seek = () => {
      if (!Number.isFinite(video.duration) || video.duration <= 0) return
      video.currentTime = Math.min(seconds, video.duration)
      onTimeChange(video.currentTime)
    }
    if (video.readyState >= HTMLMediaElement.HAVE_METADATA) {
      seek()
    } else {
      // 새 선택이 들어오면 이전 메타데이터 리스너를 해제해 마지막 요청만 적용한다.
      video.addEventListener('loadedmetadata', seek, { once: true })
      return () => video.removeEventListener('loadedmetadata', seek)
    }
  }, [seekRequest, failed, onTimeChange])

  function handleError() {
    setFailed(true)
    onTimeChange(null)
    onDurationChange(null)
  }

  return <div className="video-stage">
    {src && !failed ? <video
      ref={videoRef}
      aria-label="원본 영상"
      src={src}
      controls
      preload="metadata"
      playsInline
      onDurationChange={event => {
        const { duration } = event.currentTarget
        onDurationChange(Number.isFinite(duration) && duration > 0 ? duration : null)
      }}
      onLoadedMetadata={event => onTimeChange(event.currentTarget.currentTime)}
      onTimeUpdate={event => onTimeChange(event.currentTarget.currentTime)}
      onError={handleError}
    /> : <div className="video-placeholder">
      {failed ? <VideoOff size={36} aria-hidden="true" /> : <Film size={36} aria-hidden="true" />}
      <strong role="status">{failed ? '영상을 재생할 수 없습니다' : '재생할 예시 영상이 없습니다'}</strong>
      <p>{failed ? '서버 연결과 브라우저의 영상 코덱 지원을 확인해 주세요.' : '아래에서 장면 선택과 검토 기능을 체험할 수 있습니다.'}</p>
      {failed && <Button type="button" variant="secondary" onClick={() => setFailed(false)}>영상 다시 불러오기</Button>}
    </div>}
  </div>
}
