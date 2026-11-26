// schemas.py의 응답 모델을 기준으로 유지한다. 분석 결과와 사용자 검토는 별도 API로 조회한다.
export type JobState = 'queued' | 'running' | 'completed' | 'failed'
export type ClassCode = 'D00' | 'D10' | 'D20' | 'D40'
export type ReviewState = 'unreviewed' | 'suspected' | 'false_positive' | 'deferred'
export interface SceneReview {
  event_id: string
  review: ReviewState
  updated_at: string
}
export interface JobReviews {
  job_id: string
  reviews: SceneReview[]
}
export interface ApiError { code: string; message: string }
export interface ErrorResponse { error: ApiError }
export interface JobStatus {
  job_id: string
  status: JobState
  created_at: string
  started_at: string | null
  finished_at: string | null
  error: ApiError | null
}
export interface VideoInfo {
  fps: number
  width: number
  height: number
  frame_count: number
  duration_sec: number | null
}
export interface Scene {
  event_id: string
  class_id: number
  class_name: ClassCode
  start_time_sec: number
  last_detection_time_sec: number
  representative_time_sec: number
  representative_frame_index: number
  representative_xyxy: [number, number, number, number]
  max_confidence: number
  detection_count: number
  detected_frame_count: number
  image_url: string
}
export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue }
export interface AnalysisResults {
  job_id: string
  status: 'completed'
  video: VideoInfo
  video_url: string
  extracted_frame_count: number
  inferred_frame_count: number
  detected_frame_count: number
  detection_count: number
  event_count: number
  analysis_seconds: number
  profile: 'mvp'
  model_sha256: string
  settings: { [key: string]: JsonValue }
  timestamp_basis: string
  events: Scene[]
}
