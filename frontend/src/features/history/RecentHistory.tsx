import { ArrowRight, History } from 'lucide-react'
import { Link } from 'react-router'
import { useJobHistory } from '../../api/useJobHistory'
import { HistoryList, HistoryRequestStatus, HistoryWarnings } from './HistoryList'

export function RecentHistory() {
  const { data, busy, error, refresh } = useJobHistory({ limit: 5, offset: 0, sort: 'newest' })
  return <section className="panel recent-history" aria-labelledby="recent-history-title">
    <div className="panel-heading">
      <h2 id="recent-history-title"><History size={19} aria-hidden="true" />최근 분석 이력</h2>
      <Link to="/history" className="button button-ghost">전체 보기<ArrowRight size={16} aria-hidden="true" /></Link>
    </div>
    <HistoryRequestStatus busy={busy} hasData={!!data} error={error} refresh={refresh} />
    {data && <>
      <HistoryWarnings warnings={data.warnings} />
      {data.count > 0 ? <HistoryList items={data.items} />
        : <p className="history-empty muted">{data.warnings.length ? '표시할 분석 이력이 없습니다.' : '아직 분석 이력이 없습니다.'}</p>}
    </>}
  </section>
}
