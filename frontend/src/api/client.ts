import { API_BASE, CLASS_LABELS } from '../config/service'
import type { AnalysisResults, ErrorResponse, JobStatus, Scene } from './types'

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

function isJobStatus(value: unknown): value is JobStatus {
  return isRecord(value) && typeof value.job_id === 'string'
    && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value.job_id)
    && (value.status === 'queued' || value.status === 'running' || value.status === 'completed' || value.status === 'failed')
    && typeof value.created_at === 'string'
    && (value.started_at === null || typeof value.started_at === 'string')
    && (value.finished_at === null || typeof value.finished_at === 'string')
    && (value.error === null || isErrorResponse(value))
}

export function apiUrl(path: string): string {
  return new URL(path, API_BASE).href
}

function isMediaPath(value: unknown): value is string {
  return typeof value === 'string' && value.startsWith('/api/')
    && new URL(value, API_BASE).origin === new URL(API_BASE).origin
}

function isScene(value: unknown): value is Scene {
  return isRecord(value) && typeof value.event_id === 'string' && /^event_[0-9]{4,}$/.test(value.event_id)
    && typeof value.class_name === 'string' && Object.hasOwn(CLASS_LABELS, value.class_name)
    && [value.class_id, value.start_time_sec, value.last_detection_time_sec, value.representative_time_sec,
      value.representative_frame_index, value.max_confidence, value.detection_count, value.detected_frame_count].every(isNumber)
    && Array.isArray(value.representative_xyxy) && value.representative_xyxy.length === 4
    && value.representative_xyxy.every(isNumber) && isMediaPath(value.image_url)
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

export function getJob(jobId: string, signal: AbortSignal) {
  return request(`/api/jobs/${encodeURIComponent(jobId)}`, { signal, cache: 'no-store' }, 200,
    (value): value is JobStatus => isJobStatus(value) && value.job_id === jobId.toLowerCase())
}

export function getResults(jobId: string, signal: AbortSignal) {
  return request(`/api/jobs/${encodeURIComponent(jobId)}/results`, { signal, cache: 'no-store' }, 200,
    (value): value is AnalysisResults => isResults(value, jobId))
}
