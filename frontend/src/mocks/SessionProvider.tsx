import { useEffect, useState, type ReactNode } from 'react'
import type { AnalysisPhase } from '../config/service'
import { DEMO_IDS, makeJob, makeResults, type DemoScenario } from './fixtures'
import { SessionContext, type DemoJob, type Session } from './SessionContext'

const nextPhase: Partial<Record<AnalysisPhase, AnalysisPhase>> = {
  uploading: 'queued', queued: 'running', running: 'completed',
}
function updatePhase(entry: DemoJob, phase: AnalysisPhase): DemoJob {
  return { ...entry, phase, job: phase === 'uploading' ? null : makeJob(entry.result.job_id, phase) }
}
function initialJobs(): Record<string, DemoJob> {
  return Object.fromEntries(Object.entries(DEMO_IDS).map(([scenario, id]) => [id, {
    phase: scenario === 'failed' ? 'failed' : 'completed', auto: false,
    job: makeJob(id, scenario === 'failed' ? 'failed' : 'completed'),
    result: makeResults(id, scenario as DemoScenario),
  }]))
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<Record<string, DemoJob>>(initialJobs)
  const [reviews, setReviews] = useState<Session['reviews']>({})

  useEffect(() => {
    const timers = Object.entries(jobs).filter(([, entry]) => entry.auto && nextPhase[entry.phase])
      .map(([id, entry]) => window.setTimeout(() => {
        const phase = nextPhase[entry.phase]!
        setJobs(previous => ({ ...previous, [id]: updatePhase(previous[id], phase) }))
      }, entry.phase === 'running' ? 2400 : 1600))
    return () => timers.forEach(window.clearTimeout)
  }, [jobs])

  const value: Session = {
    jobs, reviews,
    createExample(scenario, filename) {
      const id = crypto.randomUUID()
      const entry: DemoJob = {
        phase: 'uploading', job: null, auto: true, clientFilename: filename, result: makeResults(id, scenario),
      }
      setJobs(previous => ({ ...previous, [id]: entry }))
      return id
    },
    setPhase(id, phase) {
      setJobs(previous => previous[id] ? { ...previous, [id]: { ...updatePhase(previous[id], phase), auto: false } } : previous)
    },
    toggleAuto(id) {
      setJobs(previous => previous[id] ? { ...previous, [id]: { ...previous[id], auto: !previous[id].auto } } : previous)
    },
    setReview(id, eventId, review) {
      if (!jobs[id]?.result.events.some(event => event.event_id === eventId)) return
      setReviews(previous => ({ ...previous, [id]: { ...previous[id], [eventId]: review } }))
    },
  }
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}
