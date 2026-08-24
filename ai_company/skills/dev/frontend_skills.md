# @개발_사원C (Frontend & UI/UX Design System Engineer) 스킬 가이드

본 가이드는 Addy Osmani의 엔지니어링 스킬셋을 기반으로 @개발_사원C(프론트엔드 및 디자인 시스템 엔지니어)가 구현해야 하는 컴포넌트 아키텍처, 성능 최적화, 웹 접근성(WCAG AA), 브라우저 런타임 검증 및 무결점 루프 표준을 규정합니다.

---

## 1. Frontend UI Engineering (컴포넌트 & 디자인 시스템 엔지니어링)
> **"UI는 단순한 마크업이 아니라 상태, 접근성, 반응형 레이아웃의 유기적 시스템이다."**

### 컴포넌트 아키텍처 원칙
1. **단일 책임 원칙 (SRP)**: 프레젠테이션 컴포넌트(UI 전용)와 컨테이너/훅(데이터/상태 관리)을 명확히 분리.
2. **WCAG 2.1 AA 접근성 준수**:
   - 모든 대화형 요소는 키보드 Tab 및 Enter/Space로 조작 가능해야 함 (`tabindex`, `onKeyDown`).
   - 텍스트 명도 대비(Contrast Ratio) 4.5:1 이상 유지 (대형 텍스트는 3:1).
   - 모든 이미지에 의미 있는 `alt` 텍스트 제공, 아이콘 버튼에 `aria-label` 필수 부여.
3. **반응형 모바일 우선 (Mobile-First)**: 모바일 뷰포트(375px)부터 시작하여 태블릿(768px), 데스크톱(1024px, 1440px)으로 확장.

---

## 2. Web Performance Optimization (Core Web Vitals 최적화)
> **"측정하기 전에 최적화하지 마라. Core Web Vitals 3대 지표를 엄격히 준수한다."**

### 핵심 성능 목표치
- **LCP (Largest Contentful Paint)**: < 2.5초 (이미지 `priority`/`fetchpriority="high"`, 웹폰트 `font-display: swap`)
- **INP (Interaction to Next Paint)**: < 200ms (메인 스레드 블로킹 방지, 디바운스/쓰로틀 적용)
- **CLS (Cumulative Layout Shift)**: < 0.1 (이미지/동영상에 명시적 `width`/`height` 또는 `aspect-ratio` 지정)

### 번들 최적화
- 동적 임포트(`import()`, `React.lazy`)를 통한 라우트별 코드 스플리팅.
- 무거운 외부 라이브러리(Moment.js 등) 지양, 가벼운 대안(Day.js 또는 Native Date) 채택.

---

## 3. Browser DevTools Runtime Verification (`browser-testing-with-devtools`)
> **"코드가 작성되었다고 끝난 것이 아니다. 브라우저 실제 런타임에서 증명해야 한다."**

- **Console 무결점**: 런타임 에러(Uncaught Exception), 경고(Warning), React Key 누락 경고가 콘솔에 0건이어야 함.
- **Network 워터폴 확인**: 실패한 HTTP 요청(4xx, 5xx)이 없으며 불필요한 중복 API 호출이 없는지 확인.
- **DOM 레이아웃 검사**: 오버플로우로 인한 가로 스크롤 버그(Layout Bleed) 방지.

---

## 4. Impeccable Detect & Anti-Slop 무결점 완결 루프
- `DESIGN.md`에 규정된 색상(3~5개), 폰트(2개), 레이아웃 및 시그니처 4칸 체크리스트 준수.
- UI 코드 구현 후 반드시 `npx --yes impeccable@latest detect <폴더>`를 실행하여 **0건(Clean)**이 나올 때까지 수정한 뒤 사원D(QA)에게 이관.

---

## 5. scrollcraft 스크롤 타임라인 & 인터랙티브 웹 검증 (`scrollcraft`)
> **"스크롤은 방문자의 타임라인이다. 프레임 단위 비디오 스크러빙과 헤드리스 캡처로 무결점을 검증한다."**

- **스크롤 타임라인 아키텍처**: 휠/터치 진행도에 연동된 비디오 스크러빙, 핀(Pin), 팬(Pan), 리빌(Reveal) 인터랙션 구현.
- **8대 문법 & 6대 지문 게이트**: 매 프로젝트마다 고유한 문법, 내비게이션, 히어로, 액트 형태, 클로즈, 시그니처 무브 적용.
- **스크롤 캡처 자가 검증**: `node <skill>/scripts/shoot.mjs` 기반으로 스크롤 전 구간을 캡처하여 데드 스크롤 0건, 불투명도 미달 방지, 프레임별 텍스트 명도 대비(4.5:1 이상) 검증 완료.

