# React 프론트엔드 실행과 테스트

프로젝트 루트에서 로컬 Node.js를 PATH에 추가한 뒤 `frontend`에서 실행한다.

```powershell
$projectNode = (Resolve-Path 'outputs/frontend_tooling/node-v26.13.1-win-x64').Path
$env:PATH = "$projectNode;$env:PATH"
Set-Location frontend
npm.cmd run dev
```

개발 화면 `http://127.0.0.1:5173`은 FastAPI `http://127.0.0.1:8000`에 연결된다. 실제 영상 분석에는 프로젝트 전용 FastAPI 실행 명령을 사용한다. 업로드 화면의 예시는 API 없이 사용할 수 있다. [백엔드 실행 방법](../README.md#fastapi-로컬-백엔드)

```powershell
npm.cmd run typecheck -- --force
npm.cmd run lint
npm.cmd run build
npm.cmd test -- --workers=1
```

Playwright는 설치된 Microsoft Edge에서 프론트엔드 빌드를 사용한다. 실행 시 5177에서 Vite 미리보기를 띄우고 분석 API 호출은 브라우저에서 가로챈다. Mock 테스트에는 FastAPI, GPU와 원본 영상이 필요하지 않다. 실패 아티팩트는 `outputs/playwright/part6_3_1_mock/`에 저장된다. [실제 영상 통합 검증](../docs/experiments/part6_service_integration_validation.md)

결과 화면에서는 이미지 위의 `이미지 확대` 또는 Enter로 대표 장면을 열 수 있다. 타임라인의 숫자 마커는 가까운 장면을 펼치며, 개별 장면을 선택하면 영상이 해당 시점으로 이동한다. 이전·다음은 현재 표시 중인 목록을 따른다. 작은 화면에서는 장면을 선택한 뒤 상세의 `목록으로` 버튼으로 해당 목록 항목에 돌아간다. [검토 UX 검증](../docs/experiments/part6_review_ux_improvement.md)

실제 작업의 결과 화면에서 검토 상태를 선택하면 FastAPI에 저장된다. `저장 완료`를 확인한 뒤에는 새로고침하거나 서버를 다시 시작해도 같은 작업에서 복원된다. 저장이 실패하면 현재 저장값과 시도한 값이 표시되며 저장을 다시 시도할 수 있다. 전체 검토 집계에는 판단 보류가 포함된다. 검토 상태·탐지 종류·정렬을 바꾸면 목록과 타임라인이 함께 갱신된다. 예시 화면의 검토는 예시 세션에서 유지되며 새로고침하면 초기화된다. [검토 저장 검증](../docs/experiments/part6_review_persistence.md)

메인의 **최근 분석 이력**에서 최근 5건까지, 헤더의 **분석 이력** 또는 **전체 보기**에서 전체 작업을 확인할 수 있다. 파일명은 입력 후 Enter 또는 **검색**으로 조회한다. 상태와 정렬은 선택 즉시 적용한다. 검색·필터·정렬·현재 페이지는 `/history` URL에 저장한다. 상세 화면의 **분석 이력으로** 링크나 브라우저 뒤로 가기로 돌아오면 같은 조건으로 새로 조회한다. 목록의 **새로고침**은 현재 조건을 유지한다. [이력 화면 구현과 검증](../docs/experiments/part6_job_history_ui.md)

완료 작업의 결과 화면에는 **전체 장면 CSV 다운로드**, **전체 장면 Excel 다운로드**, **PDF 리포트 보기**가 표시된다. 모든 형식은 화면 필터와 관계없이 전체 장면과 마지막으로 저장된 검토 상태를 읽는다. 검토를 저장 중이면 마친 뒤 내보낼 수 있다. 저장이 실패한 경우 화면에서 다시 저장할 수 있으며, 그전에 내보내면 서버에 남아 있는 값이 포함된다. 정상 무탐지는 CSV에 열 제목을, Excel에 열 제목과 서식을 제공한다. [내보내기 열과 API 계약](../docs/api_contract.md#분석-리포트-내보내기)

원본 수치·UTC 시각을 분석하려면 CSV를 사용한다. CSV에는 열 너비를 저장할 수 없다. Excel에서 바로 확인하려면 `.xlsx`를 내려받는다. 날짜와 클래스명 열에 전용 너비를 적용했고, 날짜에는 KST를 표시한다. 긴 파일명·UUID·모델 해시의 전체 값은 셀을 선택해 수식 입력줄에서 볼 수 있다. [CSV 형식 설명](https://support.microsoft.com/en-us/excel/excel-formatting-and-features-that-are-not-transferred-to-other-file-formats)

리포트 화면(`/jobs/<job_id>/report`)에서 **최신 리포트 다시 불러오기**를 선택하면 검토를 다시 조회한다. 대표 JPEG를 모두 확인한 뒤 **PDF로 저장 / 인쇄**를 누르고, 브라우저 인쇄 창에서 **PDF로 저장**을 선택한다. 추가 설정에서 **머리글과 바닥글**을 해제하면 브라우저의 출력 날짜와 로컬 URL을 숨길 수 있다. 미리보기에 Liner 같은 브라우저 확장 버튼이 나타나면 해당 사이트에서 확장을 끄거나 확장이 없는 프로필에서 리포트를 다시 열어 출력한다. 대표 이미지에 차량번호, 얼굴, 위치정보가 포함될 수 있으므로 외부 공유 전 사용 권한과 비식별화 필요성을 확인한다. [출력 검증](../docs/experiments/part6_report_export.md)

## Vite 템플릿 참고

This template provides a minimal setup to get React working in Vite with HMR and some Oxlint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the Oxlint configuration

If you are developing a production application, we recommend enabling type-aware lint rules by installing `oxlint-tsgolint` and editing `.oxlintrc.json`:

```json
{
  "$schema": "./node_modules/oxlint/configuration_schema.json",
  "plugins": ["react", "typescript", "oxc"],
  "options": {
    "typeAware": true
  },
  "rules": {
    "react/rules-of-hooks": "error",
    "react/only-export-components": ["warn", { "allowConstantExport": true }]
  }
}
```

See the [Oxlint rules documentation](https://oxc.rs/docs/guide/usage/linter/rules) for the full list of rules and categories.
