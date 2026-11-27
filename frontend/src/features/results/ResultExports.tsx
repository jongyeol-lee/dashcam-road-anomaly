import { useState } from 'react'
import { Download, FileSpreadsheet, FileText } from 'lucide-react'
import { Link, useLocation } from 'react-router'
import { errorMessage, getJobExport } from '../../api/client'
import type { JobExportFormat } from '../../api/types'
import { Button } from '../../components/ui'

const exportOptions = [
  { format: 'csv', label: 'CSV', icon: Download },
  { format: 'xlsx', label: 'Excel', icon: FileSpreadsheet },
] as const

export function ResultExports({ jobId, eventCount, saving, failed }: {
  jobId: string; eventCount: number; saving: boolean; failed: boolean
}) {
  const { state } = useLocation()
  const [downloading, setDownloading] = useState<JobExportFormat>()
  const [error, setError] = useState<{ label: string; message: string }>()

  async function download(format: JobExportFormat, label: string) {
    if (saving || downloading) return
    setDownloading(format)
    setError(undefined)
    try {
      const blob = await getJobExport(jobId, format)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `road-anomaly-${jobId}.${format}`
      link.click()
      // 브라우저가 다운로드를 시작할 시간을 확보한 뒤 URL을 해제한다.
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (error) {
      setError({ label, message: errorMessage(error) })
    } finally {
      setDownloading(undefined)
    }
  }

  const reportLabel = <><FileText size={17} aria-hidden="true" />PDF 리포트 보기</>
  return <section className="panel result-exports" aria-label="분석 결과 내보내기">
    <div>
      <p className="small">화면 필터와 관계없이 전체 의심 장면 {eventCount.toLocaleString('ko-KR')}건을 내보냅니다.</p>
      <p className="muted small">CSV는 원본 수치 분석용, Excel은 검토용 표입니다.</p>
      {eventCount === 0 && <p className="muted small">CSV에는 열 제목만 포함됩니다. Excel에는 열 제목과 서식이 포함됩니다.</p>}
      {saving && <p className="muted small" role="status">검토 데이터 준비가 끝나면 내보낼 수 있습니다.</p>}
      {failed && <p className="muted small">저장에 실패한 변경이 있습니다. 리포트에는 마지막으로 저장된 검토 상태가 포함됩니다.</p>}
      {error && <p className="small report-error" role="alert">{error.label === 'CSV' ? 'CSV를' : 'Excel 파일을'} 다운로드하지 못했습니다. {error.message} {error.label} 버튼으로 다시 시도해 주세요.</p>}
    </div>
    <div className="button-row">
      {exportOptions.map(({ format, label, icon: Icon }) => <Button key={format} type="button" variant="secondary"
        onClick={() => void download(format, label)} disabled={saving || downloading !== undefined}>
        <Icon size={17} aria-hidden="true" />{downloading === format ? `${label} 준비 중` : `전체 장면 ${label} 다운로드`}
      </Button>)}
      {saving ? <Button type="button" variant="secondary" disabled>{reportLabel}</Button>
        : <Link to={`/jobs/${jobId}/report`} state={state} className="button button-secondary">{reportLabel}</Link>}
    </div>
  </section>
}
