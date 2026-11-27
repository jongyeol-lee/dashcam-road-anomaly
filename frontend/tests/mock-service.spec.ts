import { expect, test, type Page, type Route } from '@playwright/test'
import type {
  AnalysisResults, JobHistory, JobHistoryItem, JobHistoryWarning, JobState, ReviewState, Scene, SceneReview,
} from '../src/api/types'

const api = 'http://127.0.0.1:8000/api'
const jobsUrl = (url: URL) => url.origin + url.pathname === api + '/jobs'
const job = '10000000-2000-4000-8000-000000000001'
const otherJob = '10000000-2000-4000-8000-000000000002'
const jobPath = '/jobs/' + job
const resultPath = jobPath + '/results'
const timestamp = '2026-11-26T00:00:00Z'
const mp4 = (name: string, contents = 'mock MP4 upload') => ({
  name, mimeType: 'video/mp4', buffer: Buffer.from(contents),
})
const scenePng = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l2sAAAAASUVORK5CYII=', 'base64')

function json(route: Route, body: object, status = 200) {
  return route.fulfill({
    status, json: body,
    headers: {
      'access-control-allow-origin': '*', 'access-control-allow-methods': 'GET, PUT',
      'access-control-allow-headers': 'Content-Type', 'cache-control': 'no-store',
    },
  })
}

function status(id: string, phase: JobState, errorCode = 'analysis_failed') {
  return {
    job_id: id, status: phase, created_at: timestamp,
    started_at: phase === 'queued' ? null : timestamp,
    finished_at: phase === 'completed' || phase === 'failed' ? timestamp : null,
    error: phase === 'failed' ? { code: errorCode, message: '테스트 오류' } : null,
  }
}

function scene(index: number, code: Scene['class_name'], time: number, confidence: number): Scene {
  const id = 'event_' + String(index).padStart(4, '0')
  return {
    event_id: id, class_id: ['D00', 'D10', 'D20', 'D40'].indexOf(code), class_name: code,
    start_time_sec: time, last_detection_time_sec: time, representative_time_sec: time,
    representative_frame_index: time * 30, max_confidence: confidence, detection_count: 1,
    detected_frame_count: 1, representative_xyxy: [10, 10, 30, 40],
    image_url: '/api/jobs/' + job + '/scenes/' + id,
  }
}

const scenes = [scene(1, 'D00', 3, 0.3), scene(2, 'D40', 8, 0.8), scene(3, 'D00', 12, 0.6)]

function results(events = scenes, id = job): AnalysisResults {
  return {
    job_id: id, status: 'completed', video: { width: 1920, height: 1080, fps: 30, frame_count: 600, duration_sec: 20 },
    video_url: '/api/jobs/' + id + '/video', extracted_frame_count: 40, inferred_frame_count: 40,
    detected_frame_count: events.length, detection_count: events.length, event_count: events.length,
    analysis_seconds: 2, profile: 'mvp', model_sha256: '0'.repeat(64), settings: {},
    timestamp_basis: 'frame_index / fps', events,
  }
}

function hold() {
  let release!: () => void
  const pending = new Promise<void>(resolve => { release = resolve })
  return { pending, release }
}

async function mockReviews(page: Page, options: {
  initial?: Record<string, SceneReview[]>
  beforeGet?: (id: string) => Promise<boolean>
  beforeSave?: (id: string, entry: SceneReview) => Promise<boolean>
} = {}) {
  const stored = new Map(Object.entries(options.initial ?? {}))
  const gets: string[] = []
  const puts: SceneReview[] = []
  await page.route(api + '/jobs/*/reviews', async route => {
    const id = new URL(route.request().url()).pathname.split('/')[3]
    gets.push(id)
    if (await options.beforeGet?.(id) === false) {
      return json(route, { error: { code: 'review_data_invalid', message: '테스트 오류' } }, 500)
    }
    return json(route, { job_id: id, reviews: stored.get(id) ?? [] })
  })
  await page.route(api + '/jobs/*/reviews/*', async route => {
    if (route.request().method() === 'OPTIONS') return json(route, {})
    expect(route.request().method()).toBe('PUT')
    const [, , , id, , event_id] = new URL(route.request().url()).pathname.split('/')
    const { review } = route.request().postDataJSON() as { review: ReviewState }
    const entry = { event_id, review, updated_at: timestamp }
    puts.push(entry)
    if (await options.beforeSave?.(id, entry) === false) {
      return json(route, { error: { code: 'review_save_failed', message: '테스트 오류' } }, 500)
    }
    stored.set(id, [...(stored.get(id) ?? []).filter(item => item.event_id !== event_id), entry])
    return json(route, entry)
  })
  return { gets, puts }
}

const fileInput = (page: Page) => page.locator('input[type=file]')
const heading = (page: Page, name: string) => page.getByRole('heading', { name, exact: true })
const button = (page: Page, name: string) => page.getByRole('button', { name, exact: true })
const rows = (page: Page) => page.getByTestId('scene-row')
const positionLabel = (page: Page) => page.getByRole('status', { name: '표시 장면 중 현재 위치' })
const markers = (page: Page) => page.getByRole('group', { name: '의심 구간 위치' }).getByRole('button')
const markerFor = (page: Page, id: string) => markers(page).and(page.locator(`[data-event-ids~="${id}"]`))
const videoTime = (page: Page) => page.locator('video').evaluate((video: HTMLVideoElement) => video.currentTime)
const reviewRadio = (page: Page, name: string) => page.getByRole('radio', { name, exact: true })

async function mockVideoMetadata(page: Page) {
  // 미디어 메타데이터 도착 순서와 seek 요청만 제어한다. 실제 디코딩은 실영상 검증에서 확인한다.
  await page.addInitScript(() => {
    const times = new WeakMap<HTMLVideoElement, number>()
    Object.defineProperties(HTMLVideoElement.prototype, {
      readyState: { get(this: HTMLVideoElement) { return this.dataset.metadataLoaded ? 1 : 0 } },
      duration: { get(this: HTMLVideoElement) { return this.dataset.metadataLoaded ? 20 : NaN } },
      currentTime: {
        get(this: HTMLVideoElement) { return times.get(this) ?? 0 },
        set(this: HTMLVideoElement, seconds: number) { times.set(this, seconds) },
      },
    })
    document.addEventListener('error', event => {
      if (event.target instanceof HTMLVideoElement) event.stopImmediatePropagation()
    }, true)
  })
}

async function loadMockMetadata(page: Page) {
  await page.locator('video').evaluate((video: HTMLVideoElement) => {
    video.dataset.metadataLoaded = 'true'
    video.dispatchEvent(new Event('durationchange'))
    video.dispatchEvent(new Event('loadedmetadata'))
  })
}

async function setMockVideoTime(page: Page, seconds: number) {
  await page.locator('video').evaluate((video: HTMLVideoElement, time) => {
    video.currentTime = time
    video.dispatchEvent(new Event('timeupdate'))
  }, seconds)
}

test.beforeEach(async ({ page }) => {
  // 처리되지 않은 API 요청도 실제 FastAPI 포트로 보내지 않는다.
  await page.route(api + '/**', route => route.abort())
  await page.route(api + '/health', route => json(route, { status: 'ok' }))
  await mockHistory(page)
  await page.route(api + '/jobs/*/scenes/*', route => route.fulfill({ contentType: 'image/png', body: scenePng }))
  await mockReviews(page)
})

test('파일 선택, 변경, 취소 및 브라우저 입력 검증', async ({ page }) => {
  let posts = 0
  await page.route(jobsUrl, route => {
    if (route.request().method() !== 'POST') return route.fallback()
    posts++
    return route.abort()
  })
  await page.goto('/')
  const submit = button(page, '분석 시작')
  await expect(submit).toBeDisabled()
  const choose = page.waitForEvent('filechooser')
  await button(page, 'MP4 파일 선택').click()
  await (await choose).setFiles(mp4('first.mp4'))
  await expect(page.getByText('first.mp4')).toBeVisible()
  await expect(page.getByText('파일 선택됨 · 15 B')).toBeVisible()
  await expect(page.getByText('MP4 · 최대 200 MiB')).toBeVisible()
  await expect(submit).toBeEnabled()

  const replace = page.waitForEvent('filechooser')
  await button(page, '파일 변경').click()
  await (await replace).setFiles(mp4('second.MP4', 'x'.repeat(1536)))
  await expect(page.getByText('second.MP4')).toBeVisible()
  await expect(page.getByText('파일 선택됨 · 1.5 KiB')).toBeVisible()
  await expect(page.getByText('first.mp4')).toHaveCount(0)
  await button(page, '선택 취소').click()
  await expect(submit).toBeDisabled()

  const alert = page.locator('#file-error')
  await fileInput(page).setInputFiles(mp4('invalid.mov'))
  await expect(alert).toContainText('MP4 형식의 파일만')
  await expect(submit).toBeDisabled()
  await fileInput(page).setInputFiles(mp4('empty.mp4', ''))
  await expect(alert).toContainText('빈 파일은 사용할 수 없습니다')
  await expect(submit).toBeDisabled()

  // 200 MiB를 할당하지 않고 File.size 경계와 실제 파일 선택 이벤트를 검증한다.
  const chooseSize = (size: number) => fileInput(page).evaluate((input, size) => {
    const fileField = input as HTMLInputElement
    const file = new File(['test'], 'large.mp4', { type: 'video/mp4' })
    Object.defineProperty(file, 'size', { value: size })
    const transfer = new DataTransfer()
    transfer.items.add(file)
    fileField.files = transfer.files
    fileField.dispatchEvent(new Event('change', { bubbles: true }))
  }, size)
  await chooseSize(209715200)
  await expect(page.getByText('파일 선택됨 · 200 MiB')).toBeVisible()
  await expect(submit).toBeEnabled()
  await chooseSize(209715201)
  await expect(alert).toContainText('파일 크기가 200 MiB')
  await expect(submit).toBeDisabled()
  expect(posts).toBe(0)
})

test('중복 업로드 차단, queued → running → completed, 완료 후 폴링 중단', async ({ page }) => {
  await page.clock.install()
  const pendingUpload = hold()
  let uploads = 0
  let postedBody = ''
  let polls = 0
  await page.route(jobsUrl, async route => {
    if (route.request().method() !== 'POST') return route.fallback()
    uploads++
    postedBody = route.request().postData() ?? ''
    await pendingUpload.pending
    await json(route, status(job, 'queued'), 202)
  })
  const phases = ['queued', 'running', 'completed'] as const
  await page.route(api + jobPath, route => json(route, status(job, phases[Math.min(polls++, 2)])))
  await page.goto('/')
  await fileInput(page).setInputFiles(mp4('input.mp4'))
  try {
    await button(page, '분석 시작').dblclick()
    await expect(button(page, '업로드 및 영상 확인 중')).toBeDisabled()
    await expect(button(page, '파일 변경')).toBeDisabled()
    await expect(button(page, '선택 취소')).toBeDisabled()
    await expect.poll(() => uploads).toBe(1)
    expect(postedBody).toContain('filename="input.mp4"')
  } finally {
    pendingUpload.release()
  }
  await expect(page).toHaveURL(jobPath)
  await expect(heading(page, '분석을 기다리고 있습니다.')).toBeVisible()
  await page.clock.runFor(1050)
  await expect(heading(page, 'AI가 영상에서 도로의 이상 징후를 찾고 있습니다.')).toBeVisible()
  await page.clock.runFor(1050)
  await expect(page.getByRole('link', { name: '결과 확인' })).toBeVisible()
  await page.clock.runFor(3500)
  expect(polls).toBe(3)
  expect(uploads).toBe(1)
})

test('실제·예시 단계가 항목 수에 맞는 같은 너비의 열로 영역을 채운다', async ({ page }) => {
  await page.route(api + jobPath, route => json(route, status(job, 'completed')))
  const examplePath = '/examples/jobs/00000000-0000-4000-8000-000000000001'
  for (const [path, count] of [[jobPath, 3], [examplePath, 4]] as const) {
    await page.goto(path)
    const stages = page.getByRole('list', { name: '분석 처리 단계' })
    await expect(stages.getByRole('listitem')).toHaveCount(count)
    for (const [width, height] of [[1440, 1024], [390, 844]]) {
      await page.setViewportSize({ width, height })
      const layout = await stages.evaluate(element => {
        const items = [...element.children].map(item => item.getBoundingClientRect())
        return {
          columns: getComputedStyle(element).gridTemplateColumns.split(/\s+/).length,
          remaining: element.getBoundingClientRect().right - items.at(-1)!.right,
          equalWidths: items.every(item => Math.abs(item.width - items[0].width) < 1),
          documentWidth: document.documentElement.scrollWidth,
        }
      })
      expect(layout.columns).toBe(count)
      expect(Math.abs(layout.remaining)).toBeLessThan(1)
      expect(layout.equalWidths).toBe(true)
      expect(layout.documentWidth).toBe(width)
    }
  }
})

test('실패 메시지와 실패 후 폴링 중단', async ({ page }) => {
  let polls = 0
  await page.clock.install()
  await page.route(api + jobPath, route => {
    polls++
    return json(route, status(job, 'failed', 'interrupted'))
  })
  await page.goto(jobPath)
  await expect(heading(page, '영상 분석에 실패했습니다.')).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('서버 종료로 분석이 중단됐습니다.')
  await expect(page.getByRole('link', { name: '결과 확인' })).toHaveCount(0)
  await page.clock.runFor(3500)
  expect(polls).toBe(1)
})

test('상태 네트워크 오류와 결과 HTTP 500 각각의 재시도', async ({ page }) => {
  let statuses = 0
  let reads = 0
  await page.route(api + jobPath, route => ++statuses === 1
    ? route.abort('connectionfailed') : json(route, status(job, 'completed')))
  await page.route(api + resultPath, route => ++reads === 1
    ? json(route, { error: { code: 'internal_error', message: '테스트에서 주입한 HTTP 응답' } }, 500)
    : json(route, results()))
  await page.goto(jobPath)
  await expect(page.getByRole('alert')).toContainText('분석 서버와 연결할 수 없습니다.')
  await button(page, '상태 다시 확인').click()
  await page.getByRole('link', { name: '결과 확인' }).click()
  await expect(page.getByRole('alert')).toContainText('서버 처리 중 오류가 발생했습니다.')
  await button(page, '결과 다시 불러오기').click()
  await expect(heading(page, '영상 분석 결과')).toBeVisible()
  expect([statuses, reads]).toEqual([2, 2])
})

test('페이지 이탈 시 예약된 상태 폴링을 정리한다', async ({ page }) => {
  await page.clock.install()
  let polls = 0
  await page.route(api + jobPath, route => { polls++; return json(route, status(job, 'running')) })
  await page.goto(jobPath)
  await expect(heading(page, 'AI가 영상에서 도로의 이상 징후를 찾고 있습니다.')).toBeVisible()
  await page.getByRole('link', { name: '영상 선택 화면으로' }).click()
  await expect(page).toHaveURL('/')
  // URL 갱신 뒤 새 화면의 효과까지 실행된 시점에서 폴링 시간을 진행한다.
  await expect(page.getByText('분석 서버 연결됨')).toBeVisible()
  await page.clock.runFor(3500)
  expect(polls).toBe(1)
})

test('페이지 이탈 시 진행 중인 상태 요청을 취소한다', async ({ page }) => {
  const pending = hold()
  await page.route(api + jobPath, async route => {
    await pending.pending
    await json(route, status(job, 'running')).catch(() => {})
  })
  try {
    const requested = page.waitForRequest(api + jobPath)
    await page.goto(jobPath)
    await requested
    const cancelled = page.waitForEvent('requestfailed', request => request.url() === api + jobPath)
    await page.getByRole('link', { name: '영상 선택 화면으로' }).click()
    await expect(page).toHaveURL('/')
    expect((await cancelled).failure()?.errorText).toContain('ERR_ABORTED')
  } finally {
    pending.release()
  }
})

for (const suffix of ['', '/results']) {
  test('작업 ID 교체 시 이전 요청 취소 ' + (suffix ? '(결과)' : '(상태)'), async ({ page }) => {
    const pending = hold()
    const firstPath = jobPath + suffix
    const secondPath = '/jobs/' + otherJob + suffix
    await page.route(api + firstPath, async route => {
      await pending.pending
      await json(route, suffix ? results() : status(job, 'failed')).catch(() => {})
    })
    await page.route(api + secondPath, route => json(route,
      suffix ? results([], otherJob) : status(otherJob, 'completed')))
    try {
      const oldStarted = page.waitForRequest(api + firstPath)
      await page.goto(firstPath)
      await oldStarted
      const cancelled = page.waitForEvent('requestfailed', request => request.url() === api + firstPath)
      // 브라우저 히스토리 이동을 같은 문서에서 재현해 새로고침에 의한 취소와 구분한다.
      await page.evaluate(path => {
        history.pushState(null, '', path)
        dispatchEvent(new PopStateEvent('popstate'))
      }, secondPath)
      const request = await cancelled
      expect(request.failure()?.errorText).toContain('ERR_ABORTED')
      if (suffix) {
        await expect(heading(page, '의심 장면이 없습니다')).toBeVisible()
      } else {
        await expect(heading(page, '영상 분석이 완료되었습니다.')).toBeVisible()
      }
      await expect(page.getByText('작업 ID · ' + otherJob, { exact: true })).toBeHidden()
      await page.getByText('작업 정보', { exact: true }).click()
      await expect(page.getByText('작업 ID · ' + otherJob, { exact: true })).toBeVisible()
      pending.release()
      await expect(page.getByText('작업 ID · ' + job, { exact: true })).toHaveCount(0)
    } finally {
      pending.release()
    }
  })
}

test('예시와 실작업 URL 분리, 작업 URL 직접 접근과 새로고침', async ({ page }) => {
  const queried: string[] = []
  await page.route(api + '/jobs/**', route => {
    queried.push(new URL(route.request().url()).pathname)
    return route.request().url().endsWith('/results')
      ? json(route, results()) : json(route, status(job, 'completed'))
  })
  const { gets, puts } = await mockReviews(page)
  await page.goto('/')
  await page.getByRole('link', { name: '예시 화면 보기' }).click()
  await expect(page).toHaveURL(/\/examples\/jobs\/[a-f0-9-]+\/results$/)
  await expect(page.getByText('개발용 예시 모드')).toBeVisible()
  await expect(rows(page)).toHaveCount(6)
  await reviewRadio(page, '파손 의심').check()
  await expect(page.getByTestId('review-count')).toHaveText('1 / 6')
  await page.reload()
  await expect(reviewRadio(page, '미검토')).toBeChecked()
  expect(queried).toEqual([])
  expect(gets).toEqual([])
  expect(puts).toEqual([])

  await page.goto(jobPath)
  await expect(heading(page, '영상 분석이 완료되었습니다.')).toBeVisible()
  await page.reload()
  await expect(heading(page, '영상 분석이 완료되었습니다.')).toBeVisible()
  await page.goto(resultPath)
  await expect(heading(page, '영상 분석 결과')).toBeVisible()
  await page.reload()
  await expect(rows(page)).toHaveCount(3)
  await expect(reviewRadio(page, '미검토')).toBeChecked()
  await expect(page.getByText('개발용 예시 모드')).toHaveCount(0)
  expect(queried.filter(url => url === '/api' + jobPath)).toHaveLength(2)
  expect(queried.filter(url => url === '/api' + resultPath)).toHaveLength(2)
})

test('장면 선택, 클래스 필터, 시간·점수 정렬과 검토 개수', async ({ page }) => {
  await page.route(api + resultPath, route => json(route, results()))
  await page.goto(resultPath)
  await expect(rows(page)).toHaveCount(3)
  await expect(rows(page).first()).toHaveAttribute('data-event-id', 'event_0001')
  await page.getByLabel('정렬').selectOption('score')
  await expect(rows(page).first()).toHaveAttribute('data-event-id', 'event_0002')
  await rows(page).first().click()
  await expect(page.getByTestId('scene-detail')).toContainText('event_0002')
  await expect(rows(page).first()).toHaveAttribute('aria-pressed', 'true')
  await reviewRadio(page, '오탐').click()
  await expect(page.getByTestId('review-count')).toHaveText('1 / 3')
  await reviewRadio(page, '미검토').click()
  await expect(page.getByTestId('review-count')).toHaveText('0 / 3')
  await reviewRadio(page, '판단 보류').click()
  await expect(page.getByTestId('review-count')).toHaveText('1 / 3')
  await page.getByLabel('검토 상태').selectOption('unreviewed')
  await expect(rows(page)).toHaveCount(2)
  await page.getByLabel('탐지 종류').selectOption('D00')
  await expect(rows(page).first()).toHaveAttribute('data-event-id', 'event_0003')
  await page.getByLabel('정렬').selectOption('time')
  await expect(rows(page).first()).toHaveAttribute('data-event-id', 'event_0001')
  await page.getByLabel('탐지 종류').selectOption('D40')
  await expect(heading(page, '필터 결과가 없습니다')).toBeVisible()
  await expect(heading(page, '조건에 맞는 장면이 없습니다')).toBeVisible()
  await page.getByRole('complementary').getByRole('button', { name: '필터 초기화' }).click()
  await expect(rows(page)).toHaveCount(3)
})

test('검토 조회 지연과 실패 중 영상·장면을 열고 다시 조회해 서버 상태를 복원한다', async ({ page }) => {
  const firstGet = hold()
  let attempts = 0
  await mockReviews(page, {
    initial: { [job]: [{ event_id: 'event_0001', review: 'suspected', updated_at: timestamp }] },
    async beforeGet() {
      if (++attempts !== 1) return true
      await firstGet.pending
      return false
    },
  })
  await mockVideoMetadata(page)
  await page.route(api + resultPath, route => json(route, results()))
  await page.goto(resultPath)
  await expect(page.getByRole('status').filter({ hasText: '검토 결과를 불러오고 있습니다.' })).toBeVisible()
  await expect(reviewRadio(page, '미검토')).toBeDisabled()
  await expect(reviewRadio(page, '미검토')).not.toBeChecked()
  await expect(page.getByLabel('검토 상태')).toBeDisabled()
  await expect(page.getByTestId('review-count')).toHaveCount(0)
  await expect(rows(page).first()).not.toContainText('미검토')
  await loadMockMetadata(page)
  await rows(page).nth(1).click()
  await expect.poll(() => videoTime(page)).toBe(8)
  await expect(button(page, '이미지 확대')).toBeEnabled()
  firstGet.release()
  await expect(page.getByRole('alert').filter({ hasText: '검토 결과를 불러오지 못했습니다.' })).toBeVisible()
  await expect(reviewRadio(page, '미검토')).not.toBeChecked()
  await rows(page).first().click()
  await button(page, '검토 결과 다시 불러오기').click()
  await expect(reviewRadio(page, '파손 의심')).toBeChecked()
  await expect(page.getByTestId('review-count')).toHaveText('1 / 3')
  await expect.poll(() => videoTime(page)).toBe(3)
})

test('같은 장면의 연속 입력을 잠그고 여러 장면 저장 및 실패 재시도를 처리한다', async ({ page }) => {
  const firstSave = hold()
  let failFirst = true
  const { puts } = await mockReviews(page, {
    async beforeSave(_, entry) {
      if (entry.event_id !== 'event_0001' || !failFirst) return true
      await firstSave.pending
      failFirst = false
      return false
    },
  })
  await mockVideoMetadata(page)
  await page.route(api + resultPath, route => json(route, results()))
  await page.goto(resultPath)
  await loadMockMetadata(page)
  await setMockVideoTime(page, 7)
  await reviewRadio(page, '파손 의심').click()
  const detail = page.getByTestId('scene-detail')
  await expect(detail.getByText('저장 중 · 파손 의심')).toBeVisible()
  await expect(reviewRadio(page, '오탐')).toBeDisabled()
  await expect(reviewRadio(page, '미검토')).toBeChecked()
  await expect(page.getByTestId('review-count')).toHaveText('0 / 3')
  await reviewRadio(page, '오탐').press('Space')
  expect(puts).toHaveLength(1)
  expect(await videoTime(page)).toBe(7)

  await rows(page).nth(1).click()
  await reviewRadio(page, '판단 보류').click()
  await expect(detail.getByText('저장 완료 · 판단 보류')).toBeVisible()
  firstSave.release()
  await expect(page.getByRole('alert').filter({ hasText: 'event_0001 · 저장 실패 · 파손 의심' })).toBeVisible()
  await expect(reviewRadio(page, '판단 보류')).toBeChecked()
  await expect(page.getByTestId('review-count')).toHaveText('1 / 3')
  await rows(page).first().click()
  await setMockVideoTime(page, 7)
  await expect(reviewRadio(page, '미검토')).toBeChecked()
  await expect(detail.getByRole('alert')).toContainText('저장 실패 · 파손 의심')
  await detail.getByRole('button', { name: '검토 저장 다시 시도' }).click()
  await expect(detail.getByText('저장 완료 · 파손 의심')).toBeVisible()
  await expect(reviewRadio(page, '파손 의심')).toBeChecked()
  await expect(page.getByTestId('review-count')).toHaveText('2 / 3')
  expect(await videoTime(page)).toBe(7)
  expect(puts.map(entry => entry.review)).toEqual(['suspected', 'deferred', 'suspected'])
})

test('검토 상태별 목록·타임라인·장면 탐색과 전체 집계를 함께 유지한다', async ({ page }) => {
  const events = [...scenes, scene(4, 'D00', 16, 0.95), scene(5, 'D20', 19, 0.4)]
  const values: ReviewState[] = ['suspected', 'false_positive', 'suspected', 'deferred']
  await mockReviews(page, {
    initial: { [job]: values.map((review, index) => ({ review, event_id: events[index].event_id, updated_at: timestamp })) },
  })
  await mockVideoMetadata(page)
  await page.route(api + resultPath, route => json(route, results(events)))
  await page.goto(resultPath)
  await loadMockMetadata(page)
  await setMockVideoTime(page, 6)
  const filter = page.getByLabel('검토 상태')
  await expect(page.getByTestId('review-count')).toHaveText('4 / 5')
  const totals = page.getByLabel('전체 장면의 검토 현황')
  await expect(totals.locator('div')).toHaveText(['미검토1개', '파손 의심2개', '오탐1개', '판단 보류1개'])
  for (const [state, id] of [['unreviewed', 'event_0005'], ['false_positive', 'event_0002'], ['deferred', 'event_0004']]) {
    await filter.selectOption(state)
    await expect(rows(page)).toHaveCount(1)
    await expect(rows(page).first()).toHaveAttribute('data-event-id', id)
    await expect(markerFor(page, id)).toHaveAttribute('aria-pressed', 'true')
    expect(await videoTime(page)).toBe(6)
  }
  await filter.selectOption('suspected')
  await page.getByLabel('탐지 종류').selectOption('D00')
  await page.getByLabel('정렬').selectOption('score')
  await expect(rows(page)).toHaveCount(2)
  await expect(markers(page)).toHaveCount(2)
  await expect(page.getByText('표시 중 2개')).toBeVisible()
  await expect(page.getByTestId('review-count')).toHaveText('4 / 5')
  expect(await videoTime(page)).toBe(6)
  await button(page, '이전 장면').click()
  await expect(markerFor(page, 'event_0003')).toHaveAttribute('aria-pressed', 'true')
  await button(page, '다음 장면').click()
  await expect(markerFor(page, 'event_0001')).toHaveAttribute('aria-pressed', 'true')
  await expect.poll(() => videoTime(page)).toBe(3)
  await reviewRadio(page, '미검토').click()
  await expect(page.getByText(/event_0001 · 저장 완료 · 미검토/)).toBeVisible()
  await expect(rows(page)).toHaveCount(1)
  await expect(markerFor(page, 'event_0003')).toHaveAttribute('aria-pressed', 'true')
  await expect(button(page, '다음 장면')).toBeDisabled()
  await expect(page.getByTestId('review-count')).toHaveText('3 / 5')
  expect(await videoTime(page)).toBe(3)
})

test('저장 중 페이지 이탈 후 재접속과 새로고침에서 작업별 상태를 복원한다', async ({ page }) => {
  const saving = hold()
  const { gets, puts } = await mockReviews(page, { async beforeSave() { await saving.pending; return true } })
  await page.route(api + '/jobs/*/results', route => json(route, results(scenes, new URL(route.request().url()).pathname.split('/')[3])))
  await page.goto(resultPath)
  await reviewRadio(page, '파손 의심').click()
  await expect(page.getByText('저장 중 · 파손 의심')).toBeVisible()
  await page.getByRole('link', { name: '새 영상 분석' }).click()
  await expect(heading(page, '영상 분석 결과')).toHaveCount(0)
  await page.goBack()
  await expect(page).toHaveURL(resultPath)
  await expect(page.getByText('검토 결과를 불러오고 있습니다.')).toBeVisible()
  await expect(reviewRadio(page, '미검토')).not.toBeChecked()
  expect(gets).toEqual([job])
  saving.release()
  await expect(reviewRadio(page, '파손 의심')).toBeChecked()
  expect(gets).toEqual([job, job])
  expect(puts).toHaveLength(1)
  await page.reload()
  await expect(reviewRadio(page, '파손 의심')).toBeChecked()
  await page.goto(`/jobs/${otherJob}/results`)
  await expect(reviewRadio(page, '미검토')).toBeChecked()
  await expect(page.getByTestId('review-count')).toHaveText('0 / 3')
  await page.goto(resultPath)
  await expect(reviewRadio(page, '파손 의심')).toBeChecked()
})

test('의심 구간이 없는 응답 표시', async ({ page }) => {
  await page.route(api + resultPath, route => json(route, results([])))
  await page.goto(resultPath)
  await expect(heading(page, '표시할 대표 장면이 없습니다')).toBeVisible()
  await expect(heading(page, '의심 장면이 없습니다')).toBeVisible()
  await expect(page.getByTestId('review-count')).toHaveText('0 / 0')
  await expect(rows(page)).toHaveCount(0)
  await expect(markers(page)).toHaveCount(0)
  await expect(positionLabel(page)).toHaveCount(0)
})

test('대표 이미지 로딩 실패 후 다시 불러오기', async ({ page }) => {
  let fail = true
  const fixture = scenes[0]
  await page.route(api + resultPath, route => json(route, results([fixture])))
  await page.route('http://127.0.0.1:8000' + fixture.image_url, route => fail
    ? route.fulfill({ status: 503 }) : route.fulfill({ contentType: 'image/png', body: scenePng }))
  await page.goto(resultPath)
  const detail = page.getByTestId('scene-detail')
  await expect(detail.getByText('대표 이미지를 불러오지 못했습니다.')).toBeVisible()
  fail = false
  await detail.getByRole('button', { name: '이미지 다시 불러오기' }).click()
  const image = detail.getByRole('img', { name: '종방향 균열 대표 장면' })
  await expect.poll(() => image.evaluate(element => (element as HTMLImageElement).naturalWidth)).toBeGreaterThan(0)
  await expect(detail.getByText('대표 이미지를 불러오지 못했습니다.')).toHaveCount(0)
})

test('대표 이미지 확대 크기, 모달 오류 복구와 ESC 포커스 복원', async ({ page }) => {
  await mockVideoMetadata(page)
  await page.route(api + resultPath, route => json(route, results()))
  await page.goto(resultPath)
  await loadMockMetadata(page)
  await setMockVideoTime(page, 6)
  const expand = button(page, '이미지 확대')
  await expand.focus()
  await expand.press('Enter')
  const modal = page.getByRole('dialog', { name: '대표 이미지 확대' })
  const original = button(page, '원본 크기')
  const fit = button(page, '화면에 맞춤')
  const image = modal.getByRole('img')
  await expect(button(page, '닫기')).toBeFocused()
  await expect(fit).toHaveAttribute('aria-pressed', 'true')
  await expect(modal.getByText('AI 예측 점수 0.30', { exact: false })).toBeVisible()
  await expect.poll(() => image.evaluate(img => (img as HTMLImageElement).naturalWidth)).toBeGreaterThan(0)
  expect(await image.getAttribute('src')).toBe(await page.locator('.detail-image > img').getAttribute('src'))
  await expect(modal).toBeVisible()
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).overflow)).toBe('hidden')
  const backgroundScroll = await page.evaluate(() => window.scrollY)
  await page.mouse.move(2, 2)
  await page.mouse.wheel(0, 600)
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
  expect(await page.evaluate(() => window.scrollY)).toBe(backgroundScroll)
  await page.keyboard.press('Tab')
  await expect(fit).toBeFocused()
  await original.click()
  await expect(original).toHaveAttribute('aria-pressed', 'true')
  expect(await image.evaluate(element => {
    const img = element as HTMLImageElement
    return img.width === img.naturalWidth && img.height === img.naturalHeight
  })).toBe(true)

  // 실제 깨진 브라우저 이미지 응답을 확대본에만 주입한다.
  await image.evaluate(element => { (element as HTMLImageElement).src = 'data:image/jpeg,broken' })
  await expect(modal.getByText('대표 이미지를 불러오지 못했습니다.')).toBeVisible()
  await modal.getByRole('button', { name: '이미지 다시 불러오기' }).click()
  await expect.poll(() => image.evaluate(img => (img as HTMLImageElement).naturalWidth)).toBeGreaterThan(0)
  await page.keyboard.press('Escape')
  await expect(modal).toHaveCount(0)
  await expect(expand).toBeFocused()
  expect(await page.evaluate(() => window.scrollY)).toBe(backgroundScroll)
  expect(await videoTime(page)).toBe(6)
})

const denseScenes = [scene(1, 'D00', 3, 0.3), scene(2, 'D00', 3, 0.8),
  scene(3, 'D40', 3.5, 0.6), scene(4, 'D20', 5, 0.4), scene(5, 'D10', 16, 0.7)]

test('밀집 마커의 같은 시각 장면을 키보드로 개별 선택하고 화면 크기에 따라 다시 묶는다', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1024 })
  await mockVideoMetadata(page)
  await page.route(api + resultPath, route => json(route, results(denseScenes)))
  await page.goto(resultPath)
  await loadMockMetadata(page)
  await setMockVideoTime(page, 9)
  const group = markerFor(page, 'event_0002')
  const options = page.getByRole('group', { name: '모아 표시한 의심 장면' })
  await expect(markers(page)).toHaveCount(3)
  await expect(group).toHaveAttribute('aria-expanded', 'false')
  await expect(group).toHaveAccessibleName(/3개.*선택한 장면 포함/)
  await group.focus()
  await group.press('Enter')
  await expect(options.getByRole('button', { name: /event_0001/ })).toBeFocused()
  await expect(options.getByRole('button', { name: /00:03\.5 · 포트홀/ })).toBeVisible()
  expect(await videoTime(page)).toBe(9)
  await page.keyboard.press('Escape')
  await expect(group).toBeFocused()
  await group.press('Enter')
  await page.keyboard.press('Tab')
  await expect(options.getByRole('button', { name: /event_0002/ })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(rows(page).nth(1)).toHaveAttribute('aria-pressed', 'true')
  await expect.poll(() => videoTime(page)).toBe(3)
  await expect(group).toBeFocused()
  await group.press('Enter')
  await options.getByRole('button', { name: /event_0001/ }).click()
  await expect(rows(page).first()).toHaveAttribute('aria-pressed', 'true')
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(markers(page)).toHaveCount(2)
  await expect(group).toHaveAccessibleName(/4개/)
  await page.getByLabel('탐지 종류').selectOption('D00')
  await expect(markers(page)).toHaveCount(1)
  await expect(group).toHaveAccessibleName(/2개/)
  await expect(group).toHaveAttribute('data-event-ids', 'event_0001 event_0002')
})

test('이전·다음과 필터·정렬, 메타데이터 전 최신 seek 및 같은 장면 재선택', async ({ page }) => {
  await mockVideoMetadata(page)
  await page.route(api + resultPath, route => json(route, results()))
  await page.goto(resultPath)
  const previous = button(page, '이전 장면')
  const next = button(page, '다음 장면')
  await expect(previous).toBeDisabled()
  await expect(positionLabel(page)).toHaveText('1 / 3')
  await next.click()
  await next.click()
  await expect(positionLabel(page)).toHaveText('3 / 3')
  await expect(next).toBeDisabled()
  expect(await videoTime(page)).toBe(0)
  await loadMockMetadata(page)
  await expect.poll(() => videoTime(page)).toBe(12)
  await expect(markerFor(page, 'event_0003')).toHaveAttribute('aria-pressed', 'true')
  await expect(rows(page).last()).toHaveAttribute('aria-pressed', 'true')

  await setMockVideoTime(page, 7)
  await rows(page).last().click()
  await expect.poll(() => videoTime(page)).toBe(12)
  await setMockVideoTime(page, 7)
  await page.getByLabel('정렬').selectOption('score')
  await expect(positionLabel(page)).toHaveText('2 / 3')
  expect(await videoTime(page)).toBe(7)
  await next.click()
  await expect(next).toBeDisabled()
  await expect.poll(() => videoTime(page)).toBe(3)
  await previous.click()
  await expect.poll(() => videoTime(page)).toBe(12)
  await setMockVideoTime(page, 7)
  await page.getByLabel('탐지 종류').selectOption('D40')
  await expect(positionLabel(page)).toHaveText('1 / 1')
  await expect(previous).toBeDisabled()
  await expect(next).toBeDisabled()
  await expect(markers(page)).toHaveCount(1)
  await expect(markerFor(page, 'event_0002')).toHaveAttribute('aria-pressed', 'true')
  await page.getByLabel('탐지 종류').selectOption('D20')
  await expect(positionLabel(page)).toHaveCount(0)
  await expect(markers(page)).toHaveCount(0)
  await expect(heading(page, '조건에 맞는 장면이 없습니다')).toBeVisible()
  await page.getByRole('complementary').getByRole('button', { name: '필터 초기화' }).click()
  await expect(page.getByLabel('정렬')).toHaveValue('score')
  await expect(positionLabel(page)).toHaveText('2 / 3')
  await expect(rows(page).nth(1)).toHaveAttribute('aria-pressed', 'true')
  expect(await videoTime(page)).toBe(7)
})

test('타임라인과 이전 장면 선택 시 필요한 경우에만 데스크톱 목록 내부를 스크롤한다', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1024 })
  const events = Array.from({ length: 12 }, (_, index) => scene(index + 1, 'D00', index * 1.6, 0.6))
  await page.route(api + resultPath, route => json(route, results(events)))
  await page.goto(resultPath)
  const list = page.getByRole('group', { name: '의심 장면 목록' })
  const listTop = () => list.evaluate(element => element.scrollTop)
  const scrollY = () => page.evaluate(() => window.scrollY)
  await markerFor(page, 'event_0012').scrollIntoViewIfNeeded()
  const yBefore = await scrollY()
  expect(await listTop()).toBe(0)
  await markerFor(page, 'event_0012').click()
  await expect(rows(page).last()).toHaveAttribute('aria-pressed', 'true')
  const yInList = await listTop()
  expect(yInList).toBeGreaterThan(0)
  expect(await scrollY()).toBe(yBefore)
  expect(await rows(page).last().evaluate(row => {
    const list = row.parentElement!.getBoundingClientRect()
    const bounds = row.getBoundingClientRect()
    return bounds.top >= list.top && bounds.bottom <= list.bottom
  })).toBe(true)
  await button(page, '이전 장면').click()
  await expect(rows(page).nth(10)).toHaveAttribute('aria-pressed', 'true')
  expect(await listTop()).toBe(yInList)
})

test('영상 길이 미확인일 때 타임라인 안내와 목록·장면 탐색을 제공한다', async ({ page }) => {
  const result = results()
  result.video.duration_sec = null
  await page.route(api + resultPath, route => json(route, result))
  await page.goto(resultPath)
  await expect(page.getByText('영상 길이 정보가 없어 구간 위치를 표시할 수 없습니다.', { exact: false })).toBeVisible()
  await expect(markers(page)).toHaveCount(0)
  await button(page, '다음 장면').click()
  await expect(positionLabel(page)).toHaveText('2 / 3')
  await expect(rows(page).nth(1)).toHaveAttribute('aria-pressed', 'true')
})

test.describe('터치 뷰포트', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true })

  test('목록에서 상세 이동과 복귀, 밀집 장면 선택 및 확대 닫기', async ({ page }) => {
    await mockVideoMetadata(page)
    await page.route(api + resultPath, route => json(route, results(denseScenes)))
    await page.goto(resultPath)
    await loadMockMetadata(page)
    const selectedHeading = heading(page, '선택한 대표 장면')
    await rows(page).last().tap()
    await expect(selectedHeading).toBeFocused()
    await expect(selectedHeading).toBeInViewport()
    await expect(positionLabel(page)).toHaveText('5 / 5')
    await button(page, '이전 장면').tap()
    await expect(positionLabel(page)).toHaveText('4 / 5')
    await expect.poll(() => videoTime(page)).toBe(5)
    await button(page, '목록으로').tap()
    await expect(rows(page).nth(3)).toBeFocused()
    await expect(rows(page).nth(3)).toBeInViewport()

    await markerFor(page, 'event_0003').tap()
    expect(await videoTime(page)).toBe(5)
    await page.getByRole('group', { name: '모아 표시한 의심 장면' }).getByRole('button', { name: /00:03\.5 · 포트홀/ }).tap()
    await expect(selectedHeading).toBeInViewport()
    await expect(selectedHeading).toBeFocused()
    await expect.poll(() => videoTime(page)).toBe(3.5)
    await button(page, '이미지 확대').tap()
    await expect(page.getByRole('dialog')).toBeInViewport()
    await button(page, '닫기').tap()
    await expect(button(page, '이미지 확대')).toBeFocused()
    expect(await videoTime(page)).toBe(3.5)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
  })
})

function historyItem(
  index: number, phase: JobState = 'completed', name: string | null = `DashCam-${index}.mp4`,
): JobHistoryItem {
  return {
    ...status(index === 1 ? job : `10000000-2000-4000-8000-${String(index).padStart(12, '0')}`, phase),
    created_at: new Date(Date.UTC(2026, 10, 26, 0, 0, index)).toISOString(),
    original_filename: name,
    file_size_bytes: 2 * 1024 * 1024,
    analysis: phase === 'completed' ? { video: results().video, event_count: 3, analysis_seconds: 2 } : null,
    reviews: phase === 'completed' ? { unreviewed: 3, suspected: 0, false_positive: 0, deferred: 0, reviewed_count: 0 } : null,
  }
}

function historyResponse(params: URLSearchParams, items: JobHistoryItem[], warnings: JobHistoryWarning[] = []): JobHistory {
  const search = (params.get('search') ?? '').toLowerCase()
  const phase = params.get('status')
  const matches = items.filter(item => (!phase || item.status === phase)
    && (!search || item.original_filename?.toLowerCase().includes(search)))
  const direction = params.get('sort') === 'oldest' ? 1 : -1
  matches.sort((a, b) => direction * (Date.parse(a.created_at) - Date.parse(b.created_at) || a.job_id.localeCompare(b.job_id)))
  const limit = Number(params.get('limit'))
  const offset = Number(params.get('offset'))
  const pageItems = matches.slice(offset, offset + limit)
  return { items: pageItems, total: matches.length, count: pageItems.length, limit, offset, warnings }
}

async function mockHistory(
  page: Page,
  read: (route: Route, params: URLSearchParams) => Promise<void> = (route, params) => json(route, historyResponse(params, [])),
) {
  await page.route(jobsUrl, route => route.request().method() === 'GET'
    ? read(route, new URL(route.request().url()).searchParams) : route.fallback())
}

const historyRows = (page: Page, list = '분석 작업 목록') =>
  page.getByRole('list', { name: list, exact: true }).locator('li.history-row')
const historyBack = (page: Page) => page.getByRole('link', { name: '분석 이력으로', exact: true })
const historySearch = (page: Page) => page.getByRole('searchbox', { name: '파일명 검색' })
const nextHistoryPage = (page: Page) => button(page, '다음 페이지')

test.describe('분석 이력', () => {
  test.use({ timezoneId: 'Asia/Seoul' })

  test('메인에 최신 다섯 건을 표시하고 전체 이력과 활성 메뉴로 연결한다', async ({ page }) => {
    const items = Array.from({ length: 7 }, (_, index) => historyItem(index + 1))
    const queries: Record<string, string>[] = []
    await mockHistory(page, (route, params) => {
      queries.push(Object.fromEntries(params))
      return json(route, historyResponse(params, items))
    })
    await page.goto('/')
    const menu = page.getByRole('navigation', { name: '주 메뉴' })
    await expect(menu.getByRole('link', { name: '영상 분석' })).toHaveAttribute('aria-current', 'page')
    const recent = historyRows(page, '최근 분석 작업 목록')
    await expect(recent).toHaveCount(5)
    await expect(recent.first()).toContainText('DashCam-7.mp4')
    await expect(recent.last()).toContainText('DashCam-3.mp4')
    await expect(recent.first()).toContainText('검토한 장면 0 / 3건')
    await expect(recent.first().locator('time')).toHaveText(/09:00:07/)
    expect(queries).toEqual([{ limit: '5', offset: '0', sort: 'newest' }])
    await page.getByRole('link', { name: '전체 보기' }).click()
    await expect(page).toHaveURL(/\/history$/)
    await expect(menu.getByRole('link', { name: '분석 이력' })).toHaveAttribute('aria-current', 'page')
    await expect(historyRows(page)).toHaveCount(7)
    expect(queries.at(-1)).toEqual({ limit: '20', offset: '0', sort: 'newest' })
  })

  test('같은 파일명의 상태별 작업에 들어가고 조건을 유지한 목록으로 돌아온다', async ({ page }) => {
    const phases = ['completed', 'queued', 'running', 'failed'] as const
    const items = phases.map((phase, index) => historyItem(index + 1, phase, '같은 파일명.mp4'))
    await mockHistory(page, (route, params) => json(route, historyResponse(params, items)))
    await page.route(api + resultPath, route => json(route, results()))
    for (const item of items) {
      await page.route(api + '/jobs/' + item.job_id, route => json(route, status(item.job_id, item.status)))
    }
    await page.goto('/history?sort=oldest')
    for (const [index, item] of items.entries()) {
      const row = historyRows(page).nth(index)
      await expect(row.locator('time')).toHaveText(new RegExp(`09:00:0${index + 1}`))
      const details = row.getByRole('link')
      await details.click()
      const completed = item.status === 'completed'
      await expect(page).toHaveURL(new RegExp(`/jobs/${item.job_id}${completed ? '/results' : ''}$`))
      await expect(heading(page, completed ? '영상 분석 결과' : '영상 분석 상태')).toBeVisible()
      await expect(page.getByText('같은 파일명.mp4', { exact: true })).toBeVisible()
      if (item.status === 'failed') await expect(page.getByRole('alert')).toContainText('영상 분석 중 오류')
      await historyBack(page).click()
      await expect(page).toHaveURL(/\/history\?sort=oldest$/)
    }
    await page.goto(resultPath)
    await expect(page.getByText('원본 영상', { exact: true }).first()).toBeVisible()
    await expect(historyBack(page)).toHaveCount(0)
  })

  test('파일명 제출·상태·정렬·페이지를 URL에 저장하고 뒤로 가기와 새로고침에서 복원한다', async ({ page }) => {
    const items = Array.from({ length: 45 }, (_, index) =>
      historyItem(index + 1, index < 25 ? 'completed' : 'failed', `DashCam 한글 &+ ${index + 1}.mp4`))
    const requests: Record<string, string>[] = []
    await mockHistory(page, (route, params) => {
      requests.push(Object.fromEntries(params))
      return json(route, historyResponse(params, items))
    })
    await page.goto('/history')
    await expect(historyRows(page)).toHaveCount(20)
    await nextHistoryPage(page).click()
    await expect(page.getByText('21–40건 표시')).toBeVisible()
    expect(requests.at(-1)?.offset).toBe('20')

    const search = historySearch(page)
    await search.fill('  dashcam 한글 &+  ')
    expect(requests).toHaveLength(2)
    await search.press('Enter')
    await expect(page.getByText('1–20건 표시')).toBeVisible()
    expect(requests.at(-1)).toMatchObject({ offset: '0', search: 'dashcam 한글 &+' })
    await nextHistoryPage(page).click()
    await expect(page.getByText('21–40건 표시')).toBeVisible()
    await page.getByLabel('분석 상태', { exact: true }).selectOption('completed')
    await expect(page.getByText('전체 일치 25건')).toBeVisible()
    expect(requests.at(-1)).toMatchObject({ offset: '0', status: 'completed' })

    await nextHistoryPage(page).click()
    await expect(page.getByText('21–25건 표시')).toBeVisible()
    await page.getByLabel('정렬', { exact: true }).selectOption('oldest')
    await expect(historyRows(page).first()).toContainText('DashCam 한글 &+ 1.mp4')
    expect(requests.at(-1)).toMatchObject({ offset: '0', sort: 'oldest' })
    await nextHistoryPage(page).click()
    await expect(historyRows(page).first()).toContainText('DashCam 한글 &+ 21.mp4')
    const restoredUrl = page.url()
    await button(page, '조건 초기화').click()
    await expect(page).toHaveURL(/\/history$/)
    await expect(search).toHaveValue('')
    await page.goBack()
    await expect(page).toHaveURL(restoredUrl)
    await expect(search).toHaveValue('dashcam 한글 &+')
    await expect(page.getByLabel('분석 상태', { exact: true })).toHaveValue('completed')
    await expect(page.getByLabel('정렬', { exact: true })).toHaveValue('oldest')
    await page.reload()
    await expect(page.getByText('21–25건 표시')).toBeVisible()
    await expect(historyRows(page)).toHaveCount(5)
    await button(page, '이전 페이지').click()
    await expect(page.getByText('1–20건 표시')).toBeVisible()
    await expect(button(page, '이전 페이지')).toBeDisabled()
  })

  test('새로고침으로 마지막 페이지가 사라지면 유효한 마지막 페이지로 복귀한다', async ({ page }) => {
    let items = Array.from({ length: 41 }, (_, index) => historyItem(index + 1))
    const offsets: string[] = []
    await mockHistory(page, (route, params) => {
      offsets.push(params.get('offset')!)
      return json(route, historyResponse(params, items))
    })
    await page.goto('/history?page=3')
    await expect(page.getByText('41–41건 표시')).toBeVisible()
    items = items.slice(0, 24)
    await button(page, '새로고침').click()
    await expect(page).toHaveURL(/\/history\?page=2$/)
    await expect(page.getByText('21–24건 표시')).toBeVisible()
    await expect(nextHistoryPage(page)).toBeDisabled()
    expect(offsets).toEqual(['40', '40', '20'])
  })

  test('전체 빈 이력과 조건에 맞는 결과가 없는 상태를 구분한다', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByText('아직 분석 이력이 없습니다.', { exact: true })).toBeVisible()
    await page.getByRole('link', { name: '전체 보기' }).click()
    await expect(page.getByText('아직 분석 이력이 없습니다.', { exact: true })).toBeVisible()
    await expect(page.getByText('전체 일치 0건')).toBeVisible()
    await expect(page.getByText('표시 0건')).toBeVisible()
    await historySearch(page).fill('일치하지 않는 이름')
    await button(page, '검색').click()
    await expect(page.getByText('검색 조건에 맞는 분석 이력이 없습니다.')).toBeVisible()
    await expect(page.getByText('아직 분석 이력이 없습니다.')).toHaveCount(0)
  })

  test('연결 실패, HTTP 오류, 잘못된 응답을 구분하고 재시도할 수 있다', async ({ page }) => {
    let reads = 0
    const refreshing = hold()
    await mockHistory(page, async (route, params) => {
      if (++reads === 1) return route.abort()
      if (reads === 2) return json(route, {}, 503)
      if (reads === 3) return json(route, { ...historyResponse(params, [historyItem(1)]), count: 2 })
      if (reads === 5) {
        await refreshing.pending
        return json(route, {}, 502)
      }
      return json(route, historyResponse(params, [historyItem(1)]))
    })
    await page.goto('/history')
    const alert = page.getByRole('alert')
    const retry = button(page, '다시 시도')
    await expect(alert).toContainText('분석 서버와 연결할 수 없습니다')
    await retry.click()
    await expect(alert).toContainText('HTTP 503')
    await retry.click()
    await expect(alert).toContainText('서버 응답을 확인할 수 없습니다')
    await retry.click()
    await expect(historyRows(page)).toHaveCount(1)
    try {
      await button(page, '새로고침').click()
      await expect(button(page, '새로고침')).toBeDisabled()
      await expect(page.getByText('분석 이력을 다시 불러오고 있습니다.')).toBeVisible()
      await expect(historyRows(page)).toHaveCount(1)
    } finally {
      refreshing.release()
    }
    await expect(alert).toContainText('HTTP 502')
    await expect(alert).toContainText('마지막으로 불러온 이력을 표시합니다.')
    await expect(historyRows(page)).toHaveCount(1)
    await retry.click()
    await expect(alert).toHaveCount(0)
  })

  test('이전 조건의 느린 요청을 취소하고 페이지 이탈 때 최근 이력 요청도 정리한다', async ({ page }) => {
    const delayed = hold()
    const slowHistory = (url: string) => jobsUrl(new URL(url)) && !new URL(url).searchParams.has('search')
    await mockHistory(page, async (route, params) => {
      if (!params.has('search')) await delayed.pending
      return json(route, historyResponse(params, [historyItem(1, 'completed', 'Old.mp4'), historyItem(2, 'completed', 'New.mp4')]))
        .catch(error => { if (params.has('search')) throw error })
    })
    try {
      const started = page.waitForRequest(request => slowHistory(request.url()))
      await page.goto('/history')
      await started
      await expect(page.getByText('분석 이력을 불러오고 있습니다.')).toBeVisible()
      const cancelled = page.waitForEvent('requestfailed', req => slowHistory(req.url()))
      await historySearch(page).fill('New')
      await button(page, '검색').click()
      expect((await cancelled).failure()?.errorText).toContain('ERR_ABORTED')
      await expect(historyRows(page)).toHaveCount(1)
      await expect(historyRows(page).first()).toContainText('New.mp4')

      const homeStarted = page.waitForRequest(req => new URL(req.url()).searchParams.get('limit') === '5')
      await page.getByRole('link', { name: '영상 분석', exact: true }).click()
      await homeStarted
      const homeCancelled = page.waitForEvent('requestfailed', req => new URL(req.url()).searchParams.get('limit') === '5')
      await page.getByRole('link', { name: '전체 보기' }).click()
      expect((await homeCancelled).failure()?.errorText).toContain('ERR_ABORTED')
    } finally {
      delayed.release()
    }
  })

  test('정상 무탐지 0건과 null 요약·미완료·부분 경고를 구분한다', async ({ page }) => {
    const zero = historyItem(1, 'completed', '무탐지.mp4')
    zero.analysis = { ...zero.analysis!, event_count: 0, video: { ...zero.analysis!.video, duration_sec: 0 } }
    zero.reviews = { ...zero.reviews!, unreviewed: 0 }
    const unavailable = { ...historyItem(2, 'completed', null), analysis: null, reviews: null, file_size_bytes: null }
    const invalidReview = { ...historyItem(3, 'completed', '검토 미확인.mp4'), reviews: null }
    const reviewed = historyItem(4, 'completed', '검토 완료.mp4')
    reviewed.reviews = { unreviewed: 0, suspected: 1, false_positive: 1, deferred: 1, reviewed_count: 3 }
    const items = [zero, unavailable, invalidReview, reviewed, historyItem(5, 'running', '진행 중.mp4')]
    const warnings = [
      [otherJob, 'results_unavailable'], [otherJob, 'upload_size_unavailable'],
      [invalidReview.job_id, 'review_data_invalid'], [invalidReview.job_id, 'review_read_failed'],
      [historyItem(6).job_id, 'job_data_unavailable'],
    ].map(([job_id, code]) => ({ job_id, error: { code, message: '테스트 경고' } }))
    await mockHistory(page, (route, params) => json(route, historyResponse(params, items, warnings)))
    await page.goto('/history')
    await expect(page.getByText('전체 일치 5건')).toBeVisible()
    const row = (name: string) => historyRows(page).filter({ has: heading(page, name) })
    await expect(row('무탐지.mp4')).toContainText('의심 장면 0건')
    await expect(row('무탐지.mp4')).toContainText('영상 00:00')
    await expect(row('무탐지.mp4')).toContainText('검토한 장면 0 / 0건')
    await expect(row('파일명 미확인')).toContainText('분석 요약 미확인')
    await expect(row('파일명 미확인')).toContainText('파일 크기 미확인')
    await expect(row('파일명 미확인')).not.toContainText('0건')
    await expect(row('검토 미확인.mp4')).toContainText('의심 장면 3건')
    await expect(row('검토 미확인.mp4')).toContainText('검토 요약 미확인')
    await expect(row('검토 완료.mp4')).toContainText('판단 보류 1건')
    await expect(row('검토 완료.mp4')).toContainText('검토한 장면 3 / 3건')
    await expect(row('진행 중.mp4')).toContainText('분석 후 장면 검토 가능')
    await expect(page.getByText('일부 이력 확인 필요')).toBeVisible()
    await expect(page.getByText('일부 작업 정보를 읽을 수 없어 목록과 전체 건수에서 제외했습니다.')).toBeVisible()
    await expect(page.getByText('일부 작업의 분석 및 검토 요약을 확인할 수 없습니다.')).toBeVisible()
    await expect(page.getByText('일부 작업의 검토 데이터가 올바르지 않아 검토 요약을 확인할 수 없습니다.')).toBeVisible()
    await expect(page.getByText('일부 작업의 검토 데이터를 읽을 수 없습니다.')).toBeVisible()
    await expect(page.getByText('일부 작업의 파일 크기를 확인할 수 없습니다.')).toBeVisible()
  })

  test('두 번째 페이지에서 검토를 저장한 뒤 목록에 재진입하면 요약이 갱신된다', async ({ page }) => {
    const target = historyItem(1)
    const items = [target, ...Array.from({ length: 20 }, (_, index) => historyItem(index + 2))]
    await mockReviews(page, {
      async beforeSave() {
        target.reviews = { unreviewed: 2, suspected: 0, false_positive: 0, deferred: 1, reviewed_count: 1 }
        return true
      },
    })
    await page.route(api + resultPath, route => json(route, results()))
    await mockHistory(page, (route, params) => json(route, historyResponse(params, items)))
    await page.goto('/history?search=dashcam&status=completed&page=2')
    const originalUrl = page.url()
    const row = historyRows(page).first()
    await expect(row).toContainText('검토한 장면 0 / 3건')
    await row.getByRole('link', { name: /결과 확인/ }).click()
    await reviewRadio(page, '판단 보류').click()
    await expect(page.getByTestId('review-count')).toHaveText('1 / 3')
    await expect(page.getByText('저장 완료 · 판단 보류')).toBeVisible()
    await historyBack(page).click()
    await expect(page).toHaveURL(originalUrl)
    await expect(row).toContainText('검토한 장면 1 / 3건')
    await expect(row).toContainText('판단 보류 1건')
  })

  test('모바일에서 긴 한글·영문 파일명을 줄바꿈하고 입력과 메뉴의 키보드 사용을 지원한다', async ({ page }) => {
    const names = ['긴파일명'.repeat(40) + '.mp4', 'LongRunName'.repeat(18) + '.mp4']
    await mockHistory(page, (route, params) => json(route, historyResponse(params, names.map((name, index) => historyItem(index + 1, 'completed', name)))))
    await page.setViewportSize({ width: 320, height: 740 })
    await page.goto('/')
    await expect(historyRows(page, '최근 분석 작업 목록')).toHaveCount(2)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(320)
    await page.getByRole('link', { name: '전체 보기' }).click()
    for (const name of names) await expect(heading(page, name)).toBeVisible()
    const search = historySearch(page)
    await search.focus()
    await page.keyboard.press('Tab')
    await expect(button(page, '검색')).toBeFocused()
    expect(await button(page, '검색').evaluate(element => getComputedStyle(element).outlineStyle)).toBe('solid')
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(320)
    await page.setViewportSize({ width: 390, height: 844 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
  })

  test('예시를 실행해도 실제 이력에는 작업이 추가되지 않는다', async ({ page }) => {
    const reads: string[] = []
    await mockHistory(page, (route, params) => {
      reads.push(params.get('limit')!)
      return json(route, historyResponse(params, [historyItem(1, 'completed', '실제 목록 작업.mp4')]))
    })
    await page.goto('/')
    await expect(historyRows(page, '최근 분석 작업 목록')).toHaveCount(1)
    await page.getByRole('link', { name: '예시 화면 보기' }).click()
    await expect(page).toHaveURL(/\/examples\//)
    await expect(page.getByText('개발용 예시 모드')).toBeVisible()
    expect(reads).toEqual(['5'])
    await page.getByRole('link', { name: '분석 이력', exact: true }).click()
    await expect(historyRows(page)).toHaveCount(1)
    await expect(historyRows(page).first()).toContainText('실제 목록 작업.mp4')
    expect(reads).toEqual(['5', '20'])
  })

  test('최근 이력 연결 실패와 무관하게 파일을 선택하고 POST 업로드한다', async ({ page }) => {
    let uploads = 0
    await mockHistory(page, route => route.abort())
    await page.route(jobsUrl, route => {
      if (route.request().method() !== 'POST') return route.fallback()
      uploads++
      return json(route, status(job, 'queued'), 202)
    })
    await page.route(api + jobPath, route => json(route, status(job, 'queued')))
    await page.goto('/')
    await expect(page.getByText('분석 이력을 불러오지 못했습니다.')).toBeVisible()
    await fileInput(page).setInputFiles(mp4('독립 업로드.mp4'))
    await expect(button(page, '분석 시작')).toBeEnabled()
    await button(page, '분석 시작').click()
    await expect(page.getByText('독립 업로드.mp4', { exact: true })).toBeVisible()
    await expect(page).toHaveURL(new RegExp(jobPath + '$'))
    expect(uploads).toBe(1)
  })
})
