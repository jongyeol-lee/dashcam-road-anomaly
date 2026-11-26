import { useRef, useState, type MouseEventHandler } from 'react'
import { ImageOff, Maximize2, X } from 'lucide-react'
import { Button } from '../../components/ui'

interface SceneImageProps {
  src: string
  alt: string
  compact?: boolean
  onRetry?: () => void
  onExpand?: MouseEventHandler<HTMLButtonElement>
}

export function SceneImage(props: SceneImageProps) {
  return <ImageContent key={props.src} {...props} />
}

function ImageContent({ src, alt, compact = false, onRetry, onExpand }: SceneImageProps) {
  const [failed, setFailed] = useState(false)
  if (failed) {
    return <div className={`image-fallback ${compact ? 'compact' : ''}`} role="status">
      <ImageOff size={compact ? 18 : 28} aria-hidden="true" />
      <span>{compact ? '이미지 없음' : '대표 이미지를 불러오지 못했습니다.'}</span>
      {!compact && <Button type="button" variant="secondary" onClick={() => { setFailed(false); onRetry?.() }}>이미지 다시 불러오기</Button>}
    </div>
  }
  return <>
    <img src={src} alt={alt} onError={() => setFailed(true)} className="scene-image" />
    {onExpand && <button type="button" className="scene-image-expand" aria-haspopup="dialog" onClick={onExpand}>
      <span><Maximize2 size={16} aria-hidden="true" />이미지 확대</span>
    </button>}
  </>
}

export function ExpandableSceneImage({ src, alt, caption, onRetry }: Pick<SceneImageProps, 'src' | 'alt' | 'onRetry'> & { caption: string }) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const openerRef = useRef<HTMLButtonElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  const viewportRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [originalSize, setOriginalSize] = useState(false)

  const openImage: MouseEventHandler<HTMLButtonElement> = event => {
    openerRef.current = event.currentTarget
    setOriginalSize(false)
    setOpen(true)
    // 기본 모달은 배경의 클릭과 포커스 이동을 막고 ESC 닫기를 제공한다.
    dialogRef.current?.showModal()
    closeRef.current?.focus({ preventScroll: true })
  }

  function closeImage() {
    setOpen(false)
    openerRef.current?.focus({ preventScroll: true })
  }

  function setImageSize(useOriginalSize: boolean) {
    viewportRef.current?.scrollTo(0, 0)
    setOriginalSize(useOriginalSize)
  }

  return <>
    <SceneImage src={src} alt={alt} onRetry={onRetry} onExpand={openImage} />
    <dialog ref={dialogRef} className={`scene-image-dialog${originalSize ? ' is-original' : ''}`}
      aria-labelledby="scene-image-title" aria-describedby="scene-image-caption" onClose={closeImage}>
      <div className="scene-image-dialog-header">
        <div><h2 id="scene-image-title">대표 이미지 확대</h2><p id="scene-image-caption">{caption}</p></div>
        <Button ref={closeRef} type="button" variant="ghost" onClick={() => dialogRef.current?.close()}><X size={19} aria-hidden="true" />닫기</Button>
      </div>
      {open && <>
        <div className="scene-image-size" role="group" aria-label="이미지 표시 크기">
          <Button type="button" variant="secondary" aria-pressed={!originalSize} onClick={() => setImageSize(false)}>화면에 맞춤</Button>
          <Button type="button" variant="secondary" aria-pressed={originalSize} onClick={() => setImageSize(true)}>원본 크기</Button>
        </div>
        <div ref={viewportRef} className="scene-image-viewport" tabIndex={0} role="region" aria-label="확대 이미지">
          <SceneImage src={src} alt={alt} onRetry={() => viewportRef.current?.focus({ preventScroll: true })} />
        </div>
      </>}
    </dialog>
  </>
}
