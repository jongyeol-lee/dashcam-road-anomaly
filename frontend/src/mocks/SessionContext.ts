import { createContext, useContext } from 'react'
import type { AnalysisResults, JobStatus } from '../api/types'
import type { AnalysisPhase, ReviewState } from '../config/service'
import type { DemoScenario } from './fixtures'

export interface DemoJob {
  phase: AnalysisPhase
  job: JobStatus | null
  auto: boolean
  result: AnalysisResults
  clientFilename?: string
}
export interface Session {
  jobs: Record<string, DemoJob>
  reviews: Record<string, Record<string, ReviewState>>
  createExample: (scenario: DemoScenario, filename?: string) => string
  setPhase: (jobId: string, phase: AnalysisPhase) => void
  toggleAuto: (jobId: string) => void
  setReview: (jobId: string, eventId: string, review: ReviewState) => void
}
export const SessionContext = createContext<Session | null>(null)
export function useSession(): Session {
  const session = useContext(SessionContext)
  if (!session) throw new Error('SessionProvider가 필요합니다.')
  return session
}
