import type { ClassCode, ReviewState } from '../api/types'

export const SERVICE_NAME = '도로환경 AI 분석'
export const API_BASE = 'http://127.0.0.1:8000'
export const MAX_UPLOAD_BYTES = 209715200
export const CLASS_LABELS: Record<ClassCode, string> = {
  D00: '종방향 균열', D10: '횡방향 균열', D20: '거북등 균열', D40: '포트홀',
}
export const REVIEW_LABELS: Record<ReviewState, string> = {
  unreviewed: '미검토', suspected: '파손 의심', false_positive: '오탐', deferred: '판단 보류',
}
export type AnalysisPhase = 'uploading' | 'queued' | 'running' | 'completed' | 'failed'
export const PHASE_LABELS: Record<AnalysisPhase, string> = {
  uploading: '업로드 확인', queued: '분석 대기', running: 'AI 분석 중', completed: '분석 완료', failed: '분석 실패',
}
export const PHASE_MESSAGES: Record<AnalysisPhase, string> = {
  uploading: '영상을 업로드하고 유효성을 확인하고 있습니다.',
  queued: '분석을 기다리고 있습니다.',
  running: 'AI가 영상에서 도로의 이상 징후를 찾고 있습니다.',
  completed: '영상 분석이 완료되었습니다.',
  failed: '영상 분석에 실패했습니다.',
}
