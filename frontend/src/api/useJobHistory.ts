import { useEffect, useState } from 'react'
import { errorMessage, getJobHistory } from './client'
import type { JobHistory, JobHistoryQuery } from './types'

// 목록 조건이 바뀔 때는 호출 화면에서 컴포넌트를 다시 마운트한다.
export function useJobHistory({ limit, offset, sort, status, search }: JobHistoryQuery) {
  const [attempt, setAttempt] = useState(0)
  const [response, setResponse] = useState<{ attempt: number; data?: JobHistory; error?: string }>()

  useEffect(() => {
    const controller = new AbortController()
    void getJobHistory({ limit, offset, sort, status, search }, controller.signal)
      .then(data => {
        if (!controller.signal.aborted) setResponse({ attempt, data })
      })
      .catch(error => {
        if (controller.signal.aborted) return
        // 같은 조건에서 다시 불러오다 실패하면 마지막 성공 목록을 유지한다.
        setResponse(previous => ({ attempt, data: previous?.data, error: errorMessage(error) }))
      })
    return () => controller.abort()
  }, [attempt, limit, offset, sort, status, search])

  const busy = response?.attempt !== attempt
  return {
    data: response?.data,
    error: busy ? undefined : response?.error,
    busy,
    refresh: () => setAttempt(previous => previous + 1),
  }
}
