import { BrowserRouter, Link, Route, Routes, useLocation } from 'react-router'
import { useEffect } from 'react'
import { Layout, EmptyState } from './components/ui'
import { SessionProvider } from './mocks/SessionProvider'
import { UploadPage } from './pages/UploadPage'
import { AnalysisPage } from './pages/AnalysisPage'
import { ResultsPage } from './pages/ResultsPage'

function RouteFocus() {
  const { pathname } = useLocation()
  useEffect(() => {
    document.getElementById('main-content')?.focus({ preventScroll: true })
    window.scrollTo(0, 0)
  }, [pathname])
  return null
}
export default function App() {
  return <BrowserRouter><SessionProvider><Layout><RouteFocus /><Routes>
    <Route path="/" element={<UploadPage />} />
    <Route path="/jobs/:jobId" element={<AnalysisPage />} />
    <Route path="/jobs/:jobId/results" element={<ResultsPage />} />
    <Route path="*" element={<main className="page"><EmptyState title="페이지를 찾을 수 없습니다"><Link to="/" className="button button-primary">처음으로</Link></EmptyState></main>} />
  </Routes></Layout></SessionProvider></BrowserRouter>
}
