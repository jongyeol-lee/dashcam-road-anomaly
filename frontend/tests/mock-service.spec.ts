import { expect, test, type Page, type Route } from '@playwright/test'
import type { AnalysisResults, JobState, Scene } from '../src/api/types'

const api = 'http://127.0.0.1:8000/api'
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
    headers: { 'access-control-allow-origin': '*', 'cache-control': 'no-store' },
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

const fileInput = (page: Page) => page.locator('input[type=file]')
const heading = (page: Page, name: string) => page.getByRole('heading', { name, exact: true })
const button = (page: Page, name: string) => page.getByRole('button', { name, exact: true })
const rows = (page: Page) => page.getByTestId('scene-row')
const positionLabel = (page: Page) => page.getByRole('status', { name: '표시 장면 중 현재 위치' })
const markers = (page: Page) => page.getByRole('group', { name: '의심 구간 위치' }).getByRole('button')
const markerFor = (page: Page, id: string) => markers(page).and(page.locator(`[data-event-ids~="${id}"]`))
const videoTime = (page: Page) => page.locator('video').evaluate((video: HTMLVideoElement) => video.currentTime)

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
  await page.route(api + '/jobs/*/scenes/*', route => route.fulfill({ contentType: 'image/png', body: scenePng }))
})

test('파일 선택, 변경, 취소 및 브라우저 입력 검증', async ({ page }) => {
  let posts = 0
  await page.route(api + '/jobs', route => { posts++; return route.abort() })
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
  await page.route(api + '/jobs', async route => {
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
  await page.goto('/')
  await page.getByRole('link', { name: '예시 화면 보기' }).click()
  await expect(page).toHaveURL(/\/examples\/jobs\/[a-f0-9-]+\/results$/)
  await expect(page.getByText('개발용 예시 모드')).toBeVisible()
  await expect(rows(page)).toHaveCount(6)
  expect(queried).toEqual([])

  await page.goto(jobPath)
  await expect(heading(page, '영상 분석이 완료되었습니다.')).toBeVisible()
  await page.reload()
  await expect(heading(page, '영상 분석이 완료되었습니다.')).toBeVisible()
  await page.goto(resultPath)
  await expect(heading(page, '영상 분석 결과')).toBeVisible()
  await page.reload()
  await expect(rows(page)).toHaveCount(3)
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
  await page.getByRole('radio', { name: '오탐' }).check()
  await expect(page.getByTestId('review-count')).toHaveText('1 / 3')
  await page.getByRole('radio', { name: '미검토' }).check()
  await expect(page.getByTestId('review-count')).toHaveText('0 / 3')
  await page.getByRole('radio', { name: '판단 보류' }).check()
  await expect(page.getByTestId('review-count')).toHaveText('1 / 3')
  await page.getByRole('checkbox', { name: '미검토 장면만 보기' }).check()
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
