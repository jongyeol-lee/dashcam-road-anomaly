import { BrowserRouter, Link, Outlet, Route, Routes, useLocation } from 'react-router'
import { useEffect } from 'react'
import { Layout, EmptyState } from './components/ui'
import { SessionProvider } from './mocks/SessionProvider'
import { UploadPage } from './pages/UploadPage'
import { HistoryPage } from './pages/HistoryPage'
import { ReportPage } from './pages/ReportPage'
import { AnalysisPage, ExampleAnalysisPage } from './pages/AnalysisPage'
import { ExampleResultsPage, ResultsPage } from './pages/ResultsPage'

function RouteFocus() {
  const { pathname } = useLocation()
  useEffect(() => {
    document.getElementById('main-content')?.focus({ preventScroll: true })
    window.scrollTo(0, 0)
  }, [pathname])
  return null
}
export default function App() {
  return <BrowserRouter><Layout><RouteFocus /><Routes>
    <Route path="/" element={<UploadPage />} />
    <Route path="/history" element={<HistoryPage />} />
    <Route path="/jobs/:jobId" element={<AnalysisPage />} />
    <Route path="/jobs/:jobId/results" element={<ResultsPage />} />
    <Route path="/jobs/:jobId/report" element={<ReportPage />} />
    <Route path="/examples" element={<SessionProvider><Outlet /></SessionProvider>}>
      <Route path="jobs/:jobId" element={<ExampleAnalysisPage />} />
      <Route path="jobs/:jobId/results" element={<ExampleResultsPage />} />
    </Route>
    <Route path="*" element={<main className="page"><EmptyState title="페이지를 찾을 수 없습니다"><Link to="/" className="button button-primary">처음으로</Link></EmptyState></main>} />
  </Routes></Layout></BrowserRouter>
}
