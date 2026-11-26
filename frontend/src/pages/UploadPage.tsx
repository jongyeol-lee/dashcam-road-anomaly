import { useState, useRef } from 'react'
import { Link, useNavigate } from 'react-router'
import { Upload, ScanLine, ListChecks, ShieldCheck, Film, Check, FlaskConical, FileVideo, X } from 'lucide-react'
import { Button } from '../components/ui'
import { validateFiles, formatFileSize } from '../features/upload/validation'
import { useSession } from '../mocks/SessionContext'
import { DEMO_IDS, type DemoScenario } from '../mocks/fixtures'

export function UploadPage() {
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const [showExample, setShowExample] = useState(false)
  const [scenario, setScenario] = useState<DemoScenario>('standard')
  const fileInput = useRef<HTMLInputElement>(null)
  const dragDepth = useRef(0)
  const { createExample } = useSession()
  const navigate = useNavigate()

  function selectFiles(files: ArrayLike<File>) {
    const problem = validateFiles(files)
    setError(problem)
    setFile(problem ? null : files[0])
    setShowExample(false)
  }

  return <main className="page upload-page">
    <section className="intro"><span className="eyebrow"><ScanLine size={16} aria-hidden="true" />블랙박스 영상 검토 워크스페이스</span><h1>일상 속 주행 영상에서<br />도로의 이상 징후를 발견하세요.</h1><p>블랙박스 영상을 분석하여 확인이 필요한 도로 균열과<br className="desktop-break" /> 포트홀 의심 장면을 찾아드립니다.</p></section>
    <section className="panel upload-panel" aria-labelledby="upload-heading"><div className="panel-heading"><h2 id="upload-heading">주행 영상 선택</h2><span className="small muted">MP4 · 최대 200 MiB</span></div>
      <div className={`drop-zone ${dragging ? 'dragging' : ''} ${file ? 'has-file' : ''}`}
        onDragEnter={event => { event.preventDefault(); dragDepth.current += 1; setDragging(true) }}
        onDragOver={event => event.preventDefault()}
        onDragLeave={event => { event.preventDefault(); dragDepth.current -= 1; if (dragDepth.current <= 0) setDragging(false) }}
        onDrop={event => { event.preventDefault(); dragDepth.current = 0; setDragging(false); selectFiles(event.dataTransfer.files) }}>
        <span className="upload-symbol">{file ? <FileVideo size={30} aria-hidden="true" /> : <Upload size={30} aria-hidden="true" />}</span>
        {file ? <><h3 className="filename">{file.name}</h3><p><Check size={15} aria-hidden="true" /> 파일 선택됨 · {formatFileSize(file.size)} · 미전송</p></> : <><h3>여기에 영상을 놓아주세요</h3><p>또는 파일을 선택해 시작할 수 있어요.</p></>}
        <input ref={fileInput} id="video-file" className="sr-only" type="file" accept=".mp4,video/mp4" aria-label="MP4 영상 선택" aria-describedby="file-help file-error"
          onChange={event => { if (event.target.files?.length) selectFiles(event.target.files); event.target.value = '' }} />
        <div className="button-row"><Button type="button" variant="secondary" onClick={() => fileInput.current?.click()}>{file ? '파일 변경' : 'MP4 파일 선택'}</Button>{file && <Button type="button" variant="ghost" onClick={() => { setFile(null); setError(null); setShowExample(false) }}><X size={16} aria-hidden="true" />선택 취소</Button>}</div>
        <p className="small muted" id="file-help">파일 1개 · 최대 209,715,200바이트</p>
      </div>
      <div id="file-error" role="alert">{error && <p className="error-message">{error}</p>}</div>
      <div className="upload-bottom"><p className="small muted">파일 형식·크기만 확인합니다.<br />실제 영상 유효성은 연결 후 서버에서 검증합니다.</p><Button disabled={!file} onClick={() => setShowExample(true)}><ScanLine size={18} aria-hidden="true" />분석 시작</Button></div>
      {showExample && <div className="inline-notice" role="status"><strong>실제 분석은 다음 단계에서 연결됩니다.</strong><p>선택한 영상은 전송하지 않습니다. 별도의 예시 영상과 상태로 화면 흐름을 체험할 수 있습니다.</p><Button onClick={() => navigate(`/jobs/${createExample('standard', file?.name)}`)}><FlaskConical size={16} aria-hidden="true" />예시 상태 체험</Button></div>}
    </section>
    <section className="how-it-works" aria-label="서비스 이용 과정">
      {[{ Icon: Upload, title: '영상 업로드', text: '운행을 마친 뒤 녹화된 MP4를 선택하세요.' }, { Icon: ScanLine, title: 'AI 분석', text: '균열과 포트홀의 의심 구간을 모아봅니다.' }, { Icon: ListChecks, title: '의심 장면 확인', text: '대표 장면과 영상 시각으로 직접 검토하세요.' }].map(({ Icon, title, text }) => <div className="process-step" key={title}><Icon size={23} aria-hidden="true" /><div><h3>{title}</h3><p>{text}</p></div></div>)}
    </section>
    <div className="safety-note"><ShieldCheck size={20} aria-hidden="true" /><p>운행 종료 후 녹화 영상을 사용해 주세요. AI 분석 결과는 사용자 확인 대상이며, 파손이나 위험을 확정하지 않습니다.</p></div>
    <section className="example-launcher" aria-labelledby="example-title"><div><h2 id="example-title"><Film size={19} aria-hidden="true" />먼저 예시로 둘러보세요</h2><p className="small muted">실제 영상을 선택하지 않아도 화면을 확인할 수 있습니다.</p></div>
      <div className="button-row"><label className="sr-only" htmlFor="example-scenario">예시 화면 선택</label><select id="example-scenario" value={scenario} onChange={event => setScenario(event.target.value as DemoScenario)}>
        <option value="standard">의심 장면 6개</option><option value="empty">의심 장면 없음</option><option value="failed">분석 실패</option><option value="media-error">이미지·영상 오류</option><option value="unknown-duration">영상 길이 없음</option><option value="zero-duration">영상 길이 0초</option></select>
        <Link className="button button-secondary" to={`/jobs/${DEMO_IDS[scenario]}${scenario === 'failed' ? '' : '/results'}`}>예시 화면 보기</Link></div>
    </section>
  </main>
}
