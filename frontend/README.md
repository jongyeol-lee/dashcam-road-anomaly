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
