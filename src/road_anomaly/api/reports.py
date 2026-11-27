import csv
from datetime import UTC, datetime, timedelta, timezone
from io import BytesIO, StringIO
from unicodedata import normalize

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .schemas import JobReport, REPORT_SETTING_FIELDS


# 프런트엔드의 CLASS_LABELS, REVIEW_LABELS와 동일한 화면 용어를 사용한다.
CLASS_LABELS = {"D00": "종방향 균열", "D10": "횡방향 균열", "D20": "거북등 균열", "D40": "포트홀"}
REVIEW_LABELS = {"unreviewed": "미검토", "suspected": "파손 의심", "false_positive": "오탐", "deferred": "판단 보류"}

CSV_COLUMNS = (
    "job_id", "original_filename", "created_at", "finished_at", "exported_at",
    "event_id", "class_id", "class_name", "class_label", "start_time_sec", "last_detection_time_sec",
    "representative_time_sec", "representative_frame_index", "max_confidence", "x1", "y1", "x2", "y2",
    "detection_count", "detected_frame_count", "review_state", "review_label", "review_updated_at",
    "model_sha256", "profile", *REPORT_SETTING_FIELDS,
)
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
KST = timezone(timedelta(hours=9))
DATE_COLUMNS = {"created_at", "finished_at", "exported_at", "review_updated_at"}
DECIMAL_COLUMNS = {"start_time_sec", "last_detection_time_sec", "representative_time_sec", "max_confidence",
                   "x1", "y1", "x2", "y2", *REPORT_SETTING_FIELDS[1:]}
XLSX_WIDTHS = {
    "job_id": 23, "original_filename": 34, **dict.fromkeys(DATE_COLUMNS, 30),
    "event_id": 16, "class_label": 18, "start_time_sec": 16, "last_detection_time_sec": 18,
    "representative_time_sec": 18, "representative_frame_index": 18, "max_confidence": 16,
    "detected_frame_count": 17, "review_state": 18, "review_label": 15, "model_sha256": 23,
    "max_event_duration_sec": 18,
}


def spreadsheet_text(value: str | None) -> str | None:
    """외부 입력 문자열에서 수식으로 해석될 수 있는 접두사를 이스케이프한다."""
    if value and (value.startswith(("\t", "\r", "\n")) or normalize("NFKC", value).lstrip().startswith(("=", "+", "-", "@"))):
        return "'" + value
    return value


def report_rows(report: JobReport):
    """CSV와 XLSX의 전체 장면을 같은 필드 순서로 구성한다."""
    results = report.results
    job = report.job.model_dump(mode="json")
    reviews = {entry.event_id: entry for entry in report.reviews.reviews}
    job_cells = (job["job_id"], job["original_filename"], job["created_at"], job["finished_at"],
                 report.exported_at.isoformat())
    model_cells = (results.model_sha256, results.profile, *(results.settings.get(key) for key in REPORT_SETTING_FIELDS))
    for scene in results.events:
        entry = reviews.get(scene.event_id)
        state = entry.review if entry else "unreviewed"
        yield (*job_cells, scene.event_id, scene.class_id, scene.class_name, CLASS_LABELS[scene.class_name],
               scene.start_time_sec, scene.last_detection_time_sec, scene.representative_time_sec,
               scene.representative_frame_index, scene.max_confidence, *scene.representative_xyxy,
               scene.detection_count, scene.detected_frame_count, state, REVIEW_LABELS[state],
               entry.updated_at.isoformat() if entry else None, *model_cells)


def report_csv(report: JobReport) -> bytes:
    with StringIO(newline="") as stream:
        # 텍스트 필드는 인용하고 분석 수치는 원래 값으로 기록한다.
        writer = csv.writer(stream, quoting=csv.QUOTE_NONNUMERIC)
        writer.writerow(CSV_COLUMNS)
        for job_id, original_filename, *fields in report_rows(report):
            writer.writerow((job_id, spreadsheet_text(original_filename), *fields))
        return stream.getvalue().encode("utf-8-sig")


def xlsx_date(value: str) -> datetime:
    date = datetime.fromisoformat(value)
    # 기존 작업에 시간대가 없으면 서버 저장 기준인 UTC로 해석한다.
    if date.tzinfo is None:
        date = date.replace(tzinfo=UTC)
    return date.astimezone(KST).replace(tzinfo=None)


def report_xlsx(report: JobReport) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "분석 결과"
    sheet.freeze_panes = "A2"
    sheet.sheet_format.defaultRowHeight = 21
    sheet.row_dimensions[1].height = 34
    sheet.append(CSV_COLUMNS)

    header_font = Font(name="맑은 고딕", size=10, bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="244C70")
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    body_font = Font(name="맑은 고딕", size=10, color="172C42")
    body_alignment = Alignment(vertical="center")
    for cell in sheet[1]:
        cell.font, cell.fill, cell.alignment = header_font, header_fill, header_alignment
        field = cell.value
        sheet.column_dimensions[cell.column_letter].width = XLSX_WIDTHS.get(field, 13)
        if field in DATE_COLUMNS:
            cell.comment = Comment("한국 표준시(KST, UTC+09:00)입니다. 원본 UTC 시각과 정밀도는 CSV에서 확인하세요.", "도로환경 AI 분석")

    for row_number, row in enumerate(report_rows(report), start=2):
        for column, (field, value) in enumerate(zip(CSV_COLUMNS, row, strict=True), start=1):
            cell = sheet.cell(row=row_number, column=column)
            cell.font, cell.alignment = body_font, body_alignment
            if field in DATE_COLUMNS:
                cell.value = xlsx_date(value) if value is not None else None
                cell.number_format = 'yyyy-mm-dd hh:mm:ss.000" KST"'
            else:
                cell.value = value
                if isinstance(value, str):
                    # 파일명 등의 문자열은 수식이나 오류 값으로 해석되지 않도록 명시한다.
                    cell.data_type = "s"
                elif field in DECIMAL_COLUMNS:
                    cell.number_format = "0.000###"

    sheet.auto_filter.ref = f"A1:{get_column_letter(len(CSV_COLUMNS))}{sheet.max_row}"
    with BytesIO() as stream:
        workbook.save(stream)
        return stream.getvalue()
