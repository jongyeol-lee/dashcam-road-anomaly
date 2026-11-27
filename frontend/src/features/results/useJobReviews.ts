import { useMemo, useState } from 'react'
import { errorMessage, getReviews, saveReview } from '../../api/client'
import type { ReviewState, SceneReview } from '../../api/types'
import { useJobQuery } from '../../api/useJobQuery'

export type ReviewValues = Partial<Record<string, ReviewState>>
export type ReviewChange =
  | { status: 'saving' | 'saved'; review: ReviewState }
  | { status: 'failed'; review: ReviewState; message: string }

const pendingSaves = new Map<string, Promise<SceneReview>>()

export async function waitForPendingReviews(jobId: string, signal: AbortSignal) {
  // 같은 작업에 다시 들어오면 이전 화면에서 시작한 저장이 끝난 뒤 조회한다.
  const saves = [...pendingSaves].filter(([key]) => key.startsWith(`${jobId.toLowerCase()}/`)).map(([, save]) => save)
  await Promise.allSettled(saves)
  signal.throwIfAborted()
}

async function loadReviews(jobId: string, signal: AbortSignal) {
  await waitForPendingReviews(jobId, signal)
  return getReviews(jobId, signal)
}

export function useJobReviews(jobId: string) {
  const { data, error, retry } = useJobQuery(jobId, loadReviews)
  const [saved, setSaved] = useState<ReviewValues>({})
  const [changes, setChanges] = useState<Partial<Record<string, ReviewChange>>>({})
  const [latestEventId, setLatestEventId] = useState<string>()
  const values = useMemo(() => data && {
    ...Object.fromEntries(data.reviews.map(entry => [entry.event_id, entry.review])),
    ...saved,
  }, [data, saved])

  async function update(eventId: string, review: ReviewState) {
    const key = `${jobId}/${eventId}`
    if (!data || pendingSaves.has(key)) return
    const save = saveReview(jobId, eventId, review)
    pendingSaves.set(key, save)
    setLatestEventId(eventId)
    setChanges(previous => ({ ...previous, [eventId]: { status: 'saving', review } }))
    try {
      const entry = await save
      setSaved(previous => ({ ...previous, [eventId]: entry.review }))
      setChanges(previous => ({ ...previous, [eventId]: { status: 'saved', review: entry.review } }))
    } catch (error) {
      setChanges(previous => ({ ...previous, [eventId]: { status: 'failed', review, message: errorMessage(error) } }))
    } finally {
      pendingSaves.delete(key)
    }
  }

  return { values, error, retry, changes, latestEventId, update }
}
