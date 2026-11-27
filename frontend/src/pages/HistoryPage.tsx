import { useEffect, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, RotateCw, Search } from 'lucide-react'
import { useLocation, useSearchParams } from 'react-router'
import type { JobHistoryQuery, JobState } from '../api/types'
import { useJobHistory } from '../api/useJobHistory'
import { Button } from '../components/ui'
import { PHASE_LABELS } from '../config/service'
import { HistoryList, HistoryRequestStatus, HistoryWarnings } from '../features/history/HistoryList'

const PAGE_SIZE = 20
const SEARCH_LIMIT = 255
const jobStates: JobState[] = ['queued', 'running', 'completed', 'failed']

function limitSearch(value: string) {
  return Array.from(value).slice(0, SEARCH_LIMIT).join('')
}

function normalizeSearch(search: string) {
  return limitSearch(search.trim())
}

function getPage(value: string | null) {
  const page = Number(value)
  return value && /^\d+$/.test(value) && page >= 1 && Number.isSafeInteger((page - 1) * PAGE_SIZE) ? page : 1
}

export function HistoryPage() {
  const [params, setParams] = useSearchParams()
  const { pathname, search: urlSearch } = useLocation()
  const search = normalizeSearch(params.get('search') ?? '')
  const status = jobStates.find(state => state === params.get('status'))
  const sort = params.get('sort') === 'oldest' ? 'oldest' : 'newest'
  const page = getPage(params.get('page'))
  const [draft, setDraft] = useState({ committed: search, value: search })
  const listHeading = useRef<HTMLHeadingElement>(null)
  const query = { limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE, search, status, sort } satisfies JobHistoryQuery

  // 뒤로 가기에서 브라우저가 복원하는 입력값과 별개로 URL의 검색어를 적용한다.
  if (draft.committed !== search) setDraft({ committed: search, value: search })

  function update({
    nextSearch = search, nextStatus = status ?? '', nextSort = sort, nextPage = 1, replace = false,
  }: {
    nextSearch?: string; nextStatus?: JobState | ''; nextSort?: JobHistoryQuery['sort']; nextPage?: number; replace?: boolean
  }) {
    const next = new URLSearchParams()
    if (nextSearch) next.set('search', nextSearch)
    if (nextStatus) next.set('status', nextStatus)
    if (nextSort === 'oldest') next.set('sort', nextSort)
    if (nextPage > 1) next.set('page', String(nextPage))
    if (next.toString() !== params.toString()) setParams(next, { replace })
  }

  function reset() {
    setDraft({ committed: search, value: '' })
    update({ nextSearch: '', nextStatus: '', nextSort: 'newest' })
  }

  function changePage(nextPage: number, replace = false) {
    update({ nextPage, replace })
    if (!replace) listHeading.current?.focus()
  }

  return <main className="page history-page">
    <div className="page-heading history-page-heading">
      <h1>분석 이력</h1>
      <p className="muted">업로드한 영상의 분석 상태와 사용자 검토 현황을 확인하세요.</p>
    </div>
    <form className="panel history-filters" onSubmit={event => {
      event.preventDefault()
      const nextSearch = normalizeSearch(draft.value)
      setDraft({ committed: search, value: nextSearch })
      update({ nextSearch })
    }}>
      <div className="history-search">
        <label htmlFor="history-search">파일명 검색</label>
        <div className="history-search-input">
          <input id="history-search" type="search" value={draft.value} autoComplete="off" placeholder="원본 파일명 입력"
            onChange={event => setDraft({ committed: search, value: limitSearch(event.target.value) })} />
          <Button type="submit"><Search size={16} aria-hidden="true" />검색</Button>
        </div>
      </div>
      <div>
        <label htmlFor="history-status">분석 상태</label>
        <select id="history-status" value={status ?? ''} onChange={event => {
          update({ nextStatus: jobStates.find(state => state === event.target.value) ?? '' })
        }}>
          <option value="">전체 상태</option>
          {jobStates.map(state => <option key={state} value={state}>{PHASE_LABELS[state]}</option>)}
        </select>
      </div>
      <div>
        <label htmlFor="history-sort">정렬</label>
        <select id="history-sort" value={sort} onChange={event => update({ nextSort: event.target.value === 'oldest' ? 'oldest' : 'newest' })}>
          <option value="newest">최신순</option>
          <option value="oldest">오래된 순</option>
        </select>
      </div>
      <Button type="button" variant="secondary" onClick={reset}>조건 초기화</Button>
    </form>
    <section className="panel history-results" aria-labelledby="history-results-title">
      <h2 id="history-results-title" className="sr-only" tabIndex={-1} ref={listHeading}>분석 작업 목록</h2>
      <HistoryListing key={JSON.stringify(query)} query={query} page={page} historyPath={pathname + urlSearch}
        onPageChange={changePage} />
    </section>
  </main>
}

function HistoryListing({ query, page, historyPath, onPageChange }: {
  query: JobHistoryQuery; page: number; historyPath: string; onPageChange: (page: number, replace?: boolean) => void
}) {
  const { data, busy, error, refresh } = useJobHistory(query)
  const pageCount = Math.max(1, Math.ceil((data?.total ?? 0) / PAGE_SIZE))
  const recover = !!data && !busy && !error && page > pageCount

  useEffect(() => {
    if (recover) onPageChange(pageCount, true)
  }, [recover, pageCount, onPageChange])

  const hasFilters = !!(query.status || query.search)
  return <>
    <div className="history-list-bar">
      <div className="history-count small" role="status">
        {data && !recover && <>
          <strong>전체 일치 {data.total.toLocaleString('ko-KR')}건</strong>
          <span className="muted">{data.count > 0
            ? `${(data.offset + 1).toLocaleString('ko-KR')}–${(data.offset + data.count).toLocaleString('ko-KR')}건 표시`
            : '표시 0건'}</span>
        </>}
      </div>
      <Button type="button" variant="secondary" onClick={refresh} disabled={busy || recover}>
        <RotateCw size={15} aria-hidden="true" />새로고침
      </Button>
    </div>
    <HistoryRequestStatus busy={busy || recover} hasData={!!data} error={error} refresh={refresh} />
    {data && !recover && <>
      <HistoryWarnings warnings={data.warnings} />
      {data.count > 0 ? <HistoryList items={data.items} historyPath={historyPath} />
        : <p className="history-empty muted">{hasFilters ? '검색 조건에 맞는 분석 이력이 없습니다.'
          : data.warnings.length ? '표시할 분석 이력이 없습니다.' : '아직 분석 이력이 없습니다.'}</p>}
      {pageCount > 1 && <nav className="history-pagination" aria-label="이력 페이지 선택">
        <Button type="button" variant="secondary" disabled={page === 1} onClick={() => onPageChange(page - 1)}>
          <ChevronLeft size={16} aria-hidden="true" />이전 페이지
        </Button>
        <span className="small muted"><span aria-hidden="true">{page} / {pageCount}</span>
          <span className="sr-only">전체 {pageCount}페이지 중 {page}페이지</span>
        </span>
        <Button type="button" variant="secondary" disabled={page === pageCount} onClick={() => onPageChange(page + 1)}>
          다음 페이지<ChevronRight size={16} aria-hidden="true" />
        </Button>
      </nav>}
    </>}
  </>
}
