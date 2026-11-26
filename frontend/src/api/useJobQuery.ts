import { useEffect, useState } from 'react'

export function useJobQuery<T>(
  jobId: string,
  load: (id: string, signal: AbortSignal) => Promise<T>,
  shouldPoll?: (value: T) => boolean,
) {
  const [data, setData] = useState<T>()
  const [error, setError] = useState<unknown>()
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    let timer: number | undefined
    async function check() {
      try {
        const value = await load(jobId, controller.signal)
        if (controller.signal.aborted) return
        setData(value)
        // 조회가 완료된 시점부터 간격을 재고 종료 상태에서는 타이머를 만들지 않는다.
        if (shouldPoll?.(value)) timer = window.setTimeout(check, 1000)
      } catch (error) {
        if (!controller.signal.aborted) setError(error)
      }
    }
    void check()
    return () => {
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [jobId, load, shouldPoll, attempt])

  function retry() {
    setError(undefined)
    setAttempt(previous => previous + 1)
  }

  return { data, error, retry }
}
