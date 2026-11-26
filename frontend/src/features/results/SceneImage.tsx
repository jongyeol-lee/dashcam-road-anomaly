import { useState } from 'react'
import { ImageOff } from 'lucide-react'
import { Button } from '../../components/ui'

interface SceneImageProps {
  src: string
  alt: string
  compact?: boolean
  onRetry?: () => void
}

export function SceneImage(props: SceneImageProps) {
  return <ImageContent key={props.src} {...props} />
}

function ImageContent({ src, alt, compact = false, onRetry }: SceneImageProps) {
  const [failed, setFailed] = useState(false)
  if (failed) {
    return <div className={`image-fallback ${compact ? 'compact' : ''}`} role="status">
      <ImageOff size={compact ? 18 : 28} aria-hidden="true" />
      <span>{compact ? '이미지 없음' : '대표 이미지를 불러오지 못했습니다.'}</span>
      {!compact && <Button variant="secondary" onClick={() => { setFailed(false); onRetry?.() }}>이미지 다시 불러오기</Button>}
    </div>
  }
  return <img src={src} alt={alt} onError={() => setFailed(true)} className="scene-image" />
}
