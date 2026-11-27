import { API_BASE, CLASS_LABELS, REVIEW_LABELS } from '../config/service'
import type {
  AnalysisResults, ErrorResponse, JobAnalysisSummary, JobHistory, JobHistoryItem, JobHistoryQuery,
  JobReviews, JobStatus, ReviewState, ReviewSummary, Scene, SceneReview,
} from './types'

const errorMessages: Record<string, string> = {
  invalid_request: '요청 정보를 확인해 주세요.',
  not_found: '요청한 작업 또는 파일을 찾을 수 없습니다.',
  results_not_ready: '아직 조회할 수 있는 분석 결과가 없습니다.',
  upload_too_large: '파일 크기가 200 MiB 제한을 초과했습니다.',
  unsupported_file_type: 'MP4 파일만 업로드할 수 있습니다.',
  empty_file: '빈 파일은 업로드할 수 없습니다.',
  invalid_video: '영상을 읽을 수 없습니다. 재생 가능한 MP4 파일을 선택해 주세요.',
  analysis_failed: '영상 분석 중 오류가 발생했습니다. 다른 영상으로 다시 시도해 주세요.',
  interrupted: '서버 종료로 분석이 중단됐습니다. 영상을 다시 업로드해 주세요.',
  shutting_down: '서버가 종료 중입니다. 연결을 확인한 뒤 다시 시도해 주세요.',
  review_data_invalid: '저장된 검토 데이터를 확인할 수 없습니다.',
  review_read_failed: '검토 데이터를 읽을 수 없습니다.',
  review_save_failed: '서버가 검토 결과를 저장하지 못했습니다.',
  internal_error: '서버 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.',
}

export class ApiRequestError extends Error {
  readonly kind: 'network' | 'http' | 'response'
  readonly status?: number

  constructor(message: string, kind: ApiRequestError['kind'], status?: number) {
    super(message)
    this.kind = kind
    this.status = status
  }
}

export function errorMessage(error: unknown): string {
  return error instanceof ApiRequestError ? error.message : '요청을 처리할 수 없습니다. 다시 시도해 주세요.'
}

export function apiErrorMessage(code: string): string | undefined {
  return Object.hasOwn(errorMessages, code) ? errorMessages[code] : undefined
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isErrorResponse(value: unknown): value is ErrorResponse {
  return isRecord(value) && isRecord(value.error)
    && typeof value.error.code === 'string' && typeof value.error.message === 'string'
}

function isNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function isJobId(value: unknown): value is string {
  return typeof value === 'string' && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value)
}

function isJobStatus(value: unknown): value is JobStatus {
  return isRecord(value) && isJobId(value.job_id)
    && (value.status === 'queued' || value.status === 'running' || value.status === 'completed' || value.status === 'failed')
    && typeof value.created_at === 'string'
    && (value.started_at === null || typeof value.started_at === 'string')
    && (value.finished_at === null || typeof value.finished_at === 'string')
    && (value.error === null || isErrorResponse(value))
}

function isCount(value: unknown): value is number {
  return isNumber(value) && Number.isSafeInteger(value) && value >= 0
}

function isAnalysisSummary(value: unknown): value is JobAnalysisSummary {
  return isRecord(value) && isCount(value.event_count) && isNumber(value.analysis_seconds) && value.analysis_seconds >= 0
    && isRecord(value.video) && isNumber(value.video.fps) && value.video.fps > 0
    && isCount(value.video.width) && value.video.width > 0 && isCount(value.video.height) && value.video.height > 0
    && isCount(value.video.frame_count)
    && (value.video.duration_sec === null || (isNumber(value.video.duration_sec) && value.video.duration_sec >= 0))
}

function isReviewSummary(value: unknown): value is ReviewSummary {
  return isRecord(value)
    && [value.unreviewed, value.suspected, value.false_positive, value.deferred, value.reviewed_count].every(isCount)
}

function isHistoryTimestamp(value: string): boolean {
  return /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)?$/.test(value)
    && Number.isFinite(Date.parse(value))
}

function isHistoryItem(value: unknown): value is JobHistoryItem {
  return isRecord(value) && isJobStatus(value)
    && isHistoryTimestamp(value.created_at)
    && (value.started_at === null || isHistoryTimestamp(value.started_at))
    && (value.finished_at === null || isHistoryTimestamp(value.finished_at))
    && (value.original_filename === null || (typeof value.original_filename === 'string' && value.original_filename.length > 0))
    && (value.file_size_bytes === null || isCount(value.file_size_bytes))
    && (value.analysis === null || isAnalysisSummary(value.analysis))
    && (value.reviews === null || isReviewSummary(value.reviews))
}

function isJobHistory(value: unknown, { limit, offset }: JobHistoryQuery): value is JobHistory {
  return isRecord(value) && value.limit === limit && value.offset === offset
    && isCount(value.total) && isCount(value.count)
    && value.count === Math.min(limit, Math.max(0, value.total - offset))
    && Array.isArray(value.items) && value.items.length === value.count && value.items.every(isHistoryItem)
    && new Set(value.items.map(item => item.job_id)).size === value.count
    && Array.isArray(value.warnings)
    && value.warnings.every(warning => isRecord(warning) && isJobId(warning.job_id) && isErrorResponse(warning))
}

export function apiUrl(path: string): string {
  return new URL(path, API_BASE).href
}

function isMediaPath(value: unknown): value is string {
  return typeof value === 'string' && value.startsWith('/api/')
    && new URL(value, API_BASE).origin === new URL(API_BASE).origin
}

function isEventId(value: unknown): value is string {
  return typeof value === 'string' && /^event_[0-9]{4,}$/.test(value)
}

function isScene(value: unknown): value is Scene {
  return isRecord(value) && isEventId(value.event_id)
    && typeof value.class_name === 'string' && Object.hasOwn(CLASS_LABELS, value.class_name)
    && [value.class_id, value.start_time_sec, value.last_detection_time_sec, value.representative_time_sec,
      value.representative_frame_index, value.max_confidence, value.detection_count, value.detected_frame_count].every(isNumber)
    && Array.isArray(value.representative_xyxy) && value.representative_xyxy.length === 4
    && value.representative_xyxy.every(isNumber) && isMediaPath(value.image_url)
}

function isSceneReview(value: unknown): value is SceneReview {
  return isRecord(value) && isEventId(value.event_id)
    && typeof value.review === 'string' && Object.hasOwn(REVIEW_LABELS, value.review)
    && typeof value.updated_at === 'string' && Number.isFinite(Date.parse(value.updated_at))
}

function isJobReviews(value: unknown, jobId: string): value is JobReviews {
  if (!isRecord(value) || value.job_id !== jobId.toLowerCase()
    || !Array.isArray(value.reviews) || !value.reviews.every(isSceneReview)) return false
  return new Set(value.reviews.map(entry => entry.event_id)).size === value.reviews.length
}

function isResults(value: unknown, jobId: string): value is AnalysisResults {
  return isRecord(value) && value.job_id === jobId.toLowerCase() && value.status === 'completed'
    && isRecord(value.video) && [value.video.fps, value.video.width, value.video.height, value.video.frame_count].every(isNumber)
    && (value.video.duration_sec === null || isNumber(value.video.duration_sec)) && isMediaPath(value.video_url)
    && [value.extracted_frame_count, value.inferred_frame_count, value.detected_frame_count,
      value.detection_count, value.event_count, value.analysis_seconds].every(isNumber)
    && value.profile === 'mvp' && typeof value.model_sha256 === 'string'
    && isRecord(value.settings) && typeof value.timestamp_basis === 'string'
    && Array.isArray(value.events) && value.event_count === value.events.length && value.events.every(isScene)
}

function unexpectedResponse() {
  return new ApiRequestError('서버 응답을 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.', 'response')
}

async function request<T>(
  path: string,
  options: RequestInit,
  expectedStatus: number,
  isExpected: (value: unknown) => value is T,
): Promise<T> {
  const networkError = () => new ApiRequestError('분석 서버와 연결할 수 없습니다. 서버 연결을 확인해 주세요.', 'network')
  let response: Response
  try {
    response = await fetch(apiUrl(path), options)
  } catch (error) {
    if (options.signal?.aborted) throw error
    throw networkError()
  }

  let body: unknown
  try {
    body = await response.json()
  } catch (error) {
    if (options.signal?.aborted) throw error
    if (response.ok) throw error instanceof SyntaxError ? unexpectedResponse() : networkError()
  }
  if (!response.ok) {
    // 오류 계약의 코드를 사용해 화면에 표시할 문구를 선택한다.
    const message = isErrorResponse(body) ? apiErrorMessage(body.error.code) : undefined
    throw new ApiRequestError(message ?? `요청을 처리할 수 없습니다 (HTTP ${response.status}).`, 'http', response.status)
  }
  if (response.status !== expectedStatus || !isExpected(body)) throw unexpectedResponse()
  return body
}

export function checkHealth(signal: AbortSignal) {
  return request('/api/health', { signal, cache: 'no-store' }, 200,
    (value): value is { status: 'ok' } => isRecord(value) && value.status === 'ok')
}

export function uploadVideo(file: File, signal: AbortSignal) {
  const body = new FormData()
  body.append('file', file)
  return request('/api/jobs', { method: 'POST', body, signal }, 202, isJobStatus)
}

export function getJobHistory(query: JobHistoryQuery, signal: AbortSignal) {
  const params = new URLSearchParams({ limit: String(query.limit), offset: String(query.offset), sort: query.sort })
  if (query.status) params.set('status', query.status)
  if (query.search) params.set('search', query.search)
  return request(`/api/jobs?${params}`, { signal, cache: 'no-store' }, 200,
    (value): value is JobHistory => isJobHistory(value, query))
}

export function getJob(jobId: string, signal: AbortSignal) {
  return request(`/api/jobs/${encodeURIComponent(jobId)}`, { signal, cache: 'no-store' }, 200,
    (value): value is JobStatus => isJobStatus(value) && value.job_id === jobId.toLowerCase())
}

export function getResults(jobId: string, signal: AbortSignal) {
  return request(`/api/jobs/${encodeURIComponent(jobId)}/results`, { signal, cache: 'no-store' }, 200,
    (value): value is AnalysisResults => isResults(value, jobId))
}

export function getReviews(jobId: string, signal: AbortSignal) {
  return request(`/api/jobs/${encodeURIComponent(jobId)}/reviews`, { signal, cache: 'no-store' }, 200,
    (value): value is JobReviews => isJobReviews(value, jobId))
}

export function saveReview(jobId: string, eventId: string, review: ReviewState) {
  return request(`/api/jobs/${encodeURIComponent(jobId)}/reviews/${encodeURIComponent(eventId)}`,
    { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ review }) }, 200,
    (value): value is SceneReview => isSceneReview(value) && value.event_id === eventId && value.review === review)
}
