import type { AnalysisResults, JobStatus, Scene } from '../api/types'

export type DemoScenario = 'standard' | 'empty' | 'failed' | 'media-error' | 'unknown-duration' | 'zero-duration'
export const DEMO_IDS: Record<DemoScenario, string> = {
  standard: '00000000-0000-4000-8000-000000000001',
  empty: '00000000-0000-4000-8000-000000000002',
  failed: '00000000-0000-4000-8000-000000000003',
  'media-error': '00000000-0000-4000-8000-000000000004',
  'unknown-duration': '00000000-0000-4000-8000-000000000005',
  'zero-duration': '00000000-0000-4000-8000-000000000006',
}

function exampleImage(code: string, index: number): string {
  const marks: Record<string, string> = {
    D00: '<path d="M340 290l-8 30 16 17-6 26 10 35"/>',
    D10: '<path d="M270 340l40-7 30 15 34-8 45 8"/>',
    D20: '<path d="M310 315l40-10 25 23-11 32-40 10-24-28 10-27m40-10l-5 34-21 31m21-31l30-11m-30 11l19 21m-19-21l-45 3"/>',
    D40: '<ellipse cx="333" cy="351" rx="44" ry="18" fill="#263644"/>',
  }
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 450"><rect width="800" height="450" fill="#dce8ee"/><path d="M0 174l100-48 120 30 150-40 170 39 130-39 130 57v80H0" fill="#8fa597"/><path d="M0 213l294-32h212l294 32v237H0" fill="#b1baac"/><path d="M294 181L55 450h690L506 181" fill="#677784"/><path d="M294 181L55 450M506 181l239 269" stroke="#e6ebed" stroke-width="5"/><path d="M400 205v20m0 20v35m0 28v63m0 30v49" stroke="#eef2eb" stroke-width="5"/><g stroke="#263644" stroke-width="4" fill="none" stroke-linejoin="round">${marks[code]}</g><rect x="24" y="22" width="255" height="35" rx="5" fill="#172c42"/><text x="38" y="46" fill="white" font-size="19" font-family="sans-serif">SYNTHETIC SAMPLE · ${String(index).padStart(2, '0')}</text><rect x="24" y="395" width="100" height="30" rx="4" fill="#172c42"/><text x="37" y="416" fill="white" font-size="16" font-family="sans-serif">${code}</text></svg>`
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}

export function makeResults(jobId: string, scenario: DemoScenario): AnalysisResults {
  const definitions = [
    ['D00', 6, 0.91, 9, 6], ['D40', 14, 0.87, 5, 4], ['D20', 25, 0.94, 12, 6],
    ['D10', 34, 0.64, 4, 2], ['D00', 43, 0.72, 6, 4], ['D40', 53, 0.83, 7, 4],
  ] as const
  const events: Scene[] = scenario === 'empty' ? [] : definitions.map(([code, time, score, boxes, frames], index) => ({
    event_id: `event_${String(index + 1).padStart(4, '0')}`,
    class_id: ['D00', 'D10', 'D20', 'D40'].indexOf(code), class_name: code,
    start_time_sec: time - 1, last_detection_time_sec: time + 1.5,
    representative_time_sec: time, representative_frame_index: time * 30,
    representative_xyxy: [270, 290, 420, 400], max_confidence: score,
    detection_count: boxes, detected_frame_count: frames,
    image_url: scenario === 'media-error' ? '/__mock_missing_image__.svg' : exampleImage(code, index + 1),
  }))
  return {
    job_id: jobId, status: 'completed',
    video: { fps: 30, width: 800, height: 450, frame_count: scenario === 'zero-duration' ? 0 : 1800,
      duration_sec: scenario === 'unknown-duration' ? null : scenario === 'zero-duration' ? 0 : 60 },
    // 정상 예시는 재생 가능한 미디어가 없어 명시적인 플레이스홀더를 쓴다.
    video_url: scenario === 'media-error' ? '/__mock_missing_video__.mp4' : '',
    extracted_frame_count: 121, inferred_frame_count: 121,
    detected_frame_count: events.reduce((sum, event) => sum + event.detected_frame_count, 0),
    detection_count: events.reduce((sum, event) => sum + event.detection_count, 0),
    event_count: events.length, analysis_seconds: 8.4, profile: 'mvp', model_sha256: '0'.repeat(64),
    settings: { interval_sec: 0.5, max_gap_sec: 1.5, max_event_duration_sec: 5, imgsz: 1280,
      iou: 0.7, rect: false, max_det: 300, batch: 1, quantize: false, classes: null,
      agnostic_nms: false, augment: false, tile: false, nms: true, conf: 0.05, device: 'cuda:0' },
    timestamp_basis: 'frame_index / fps', events,
  }
}

export function makeJob(jobId: string, status: JobStatus['status']): JobStatus {
  return {
    job_id: jobId, status, created_at: '2026-11-25T00:00:00Z',
    started_at: status === 'queued' ? null : '2026-11-25T00:00:01Z',
    finished_at: status === 'completed' || status === 'failed' ? '2026-11-25T00:00:10Z' : null,
    error: status === 'failed' ? { code: 'analysis_failed', message: '개발용 실패 예시입니다. 실제 영상 처리는 수행하지 않았습니다.' } : null,
  }
}
