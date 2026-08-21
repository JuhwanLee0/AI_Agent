# 🌿 Tree Of Life Global Missions - Design System Specification (DESIGN.md)

## 1. 브랜드 컨셉 & 미학 (Brand & Aesthetic)
- **브랜드 한 줄 설명**: 전 세계 소외된 지역에 성경과 하나님의 사랑을 전하는 비영리 글로벌 선교 공동체
- **주 고객층(방문자)**: 글로벌 후원자, 선교 지망생, 자원봉사자, 교회 및 기부 파트너
- **디자인 미학(Aesthetic)**: **에디토리얼(Editorial) + 웜 미니멀(Warm Minimal)**
  - 고감도 출판물처럼 정돈된 여백(Whitespace), 우아한 `Newsreader` 세리프 타이포그래피, 대지와 숲을 닮은 따뜻한 딥 파인 & 번트 테라코타 컬러 팔레트를 사용하여 깊은 신뢰성과 헌신을 전달합니다.

---

## 2. 컬러 팔레트 (Color Palette & Rationale)

| 명칭 | Hex 코드 | 선정 이유 |
| :--- | :--- | :--- |
| **주조색 (Primary / Deep Forest)** | `#173426` | 생명나무(Tree of Life)의 굳건한 생명력과 영원성, 진중한 신뢰감을 상징 |
| **배경색 (Paper / Warm Ivory)** | `#FAF8F5` | 순백색(`#FFFFFF`)의 인위적이고 차가운 느낌을 없애고 책과 편지 같은 따뜻한 종이 질감 연출 |
| **본문 글자색 (Deep Ink Charcoal)** | `#141715` | 배경 대비가 확실한 잉크 차콜 톤으로 WCAG AAA 수준의 최고 등급 가독성 보장 |
| **강조색 (Accent / Deep Brick Terracotta)** | `#9E441B` | 흙과 온기를 담은 딥 테라코타 브라운 (WCAG AA 5.2:1 고대비 만족)으로 기부(Give) 및 주요 액션 집중 |
| **보조 테두리색 (Subtle Border)** | `#E2DDD4` | 과도한 그림자 대신 정갈하고 얇은 선(1px)으로 섹션과 요소를 깔끔하게 분리 |

---

## 3. 타이포그래피 (Typography)
- **제목용 글꼴 (Headings)**: **`Newsreader`** & **`Cinzel`** (Google Fonts)
  - 에디토리얼 고유의 우아함과 클래식한 품격을 가진 큐레이션 세리프 글꼴 (*Inter, Roboto, Fraunces 등 흔한 AI 글꼴 배제*).
- **본문용 글꼴 (Body & UI)**: **`Outfit`** & **`DM Sans`** (Google Fonts)
  - 명료한 가독성과 안정적인 자간을 지닌 현대적 산세리프 글꼴 (*Plus Jakarta Sans, Roboto 배제*).

---

## 4. 절대 쓰지 말아야 할 시각 요소 3가지 (Anti-Slop Clichés)
1. ❌ **보라~파랑 네온/AI 그래디언트**: 인위적이고 가벼운 AI 템플릿 느낌을 완전히 배제합니다.
2. ❌ **카드 안에 카드, 또 카드 (중첩 카드 지옥)**: 깊은 그림자와 겹겹이 쌓인 박스 대신, 넉넉한 여백(Whitespace)과 미니멀한 1px 라인으로 정돈된 플랫 구조를 사용합니다.
3. ❌ **과도한 바운스/이미지 확대 트랜지션**: 튀는 줌/바운스 애니메이션 대신 짧고 절제된 페이드인만 적용합니다.

---

## 5. UI 시그니처 (Signature Elements)
- **시그니처 1**: 잡지 스타일의 대형 숫자 인덱스 (`01 / 02 / 03`) 및 엠비언트 테두리
- **시그니처 2**: 갤러리 사진 호버 시 부드러운 에디토리얼 캡션 오버레이 & 풀스크린 라이트박스
- **시그니처 3**: 관리자 모드 즉시 전환 및 직관적인 드래그 앤 드롭 사진 업로더
