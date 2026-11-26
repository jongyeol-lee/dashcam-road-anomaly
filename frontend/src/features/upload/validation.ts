import { MAX_UPLOAD_BYTES } from '../../config/service'

export function validateFiles(files: ArrayLike<Pick<File, 'name' | 'size'>>): string | null {
  if (files.length !== 1) return 'MP4 파일을 한 개만 선택해 주세요.'
  const file = files[0]
  if (!/\.mp4$/i.test(file.name)) return 'MP4 형식의 파일만 선택할 수 있습니다.'
  if (file.size === 0) return '빈 파일은 사용할 수 없습니다. 다른 영상을 선택해 주세요.'
  if (file.size > MAX_UPLOAD_BYTES) return '파일 크기가 200 MiB(209,715,200바이트)를 초과합니다.'
  return null
}

export function formatFileSize(bytes: number): string {
  const kibibyte = 1024
  const mebibyte = kibibyte * 1024
  if (bytes < kibibyte) return `${bytes.toLocaleString('ko-KR')} B`
  const [divisor, unit] = bytes < mebibyte ? [kibibyte, 'KiB'] : [mebibyte, 'MiB']
  return `${(bytes / divisor).toLocaleString('ko-KR', { maximumFractionDigits: 2 })} ${unit}`
}
