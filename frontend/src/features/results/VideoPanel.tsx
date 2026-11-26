import { useState } from 'react'
import { Film, VideoOff } from 'lucide-react'

export function VideoPanel({ src }: { src: string }) {
  return <VideoContent key={src} src={src} />
}
function VideoContent({ src }: { src: string }) {
  const [failed, setFailed] = useState(false)
  return <div className="video-stage">
    {src && !failed ? <video aria-label="원본 영상" src={src} controls preload="metadata" playsInline onError={() => setFailed(true)} /> : <div className="video-placeholder" role="status">
      {failed ? <VideoOff size={36} aria-hidden="true" /> : <Film size={36} aria-hidden="true" />}
      <strong>{failed ? '영상을 재생할 수 없습니다' : '원본 영상 연결 전'}</strong>
      <p>{failed ? '영상 주소 또는 브라우저의 코덱 지원을 확인해 주세요.' : '재생 가능한 예시 미디어가 없습니다.'}<br />장면 선택과 검토 기능은 아래에서 체험할 수 있습니다.</p>
      <span className="video-note">개발용 예시 · 실제 영상 재생·시점 이동은 후속 검증</span>
    </div>}
  </div>
}
