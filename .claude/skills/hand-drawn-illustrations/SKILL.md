---
name: hand-drawn-illustrations
description: 아티클, 블로그, 뉴스레터, 노션, 기획서 등에 들어갈 감각적인 16:9 미니멀 손그림(Hand-drawn) 에디토리얼 일러스트 및 개념 다이어그램 프롬프트를 한국어와 영어로 생성하는 스킬입니다. 사용자가 "손그림 그려줘", "손그림 일러스트 만들어줘", "아티클 다이어그램 손그림", "에디토리얼 일러스트", "/hand-drawn", "/illustration" 등을 요청할 때 사용하세요.
---

# 감성 손그림 에디토리얼 일러스트 스킬 (Hand-Drawn Illustrations)

복잡한 개념과 방법론을 **직관적이고 따뜻한 16:9 미니멀 손그림(Hand-drawn) 스타일**로 시각화하는 전문 프롬프트 생성 스킬입니다.

---

## 🎨 스타일 DNA (Visual Core)

1. **캔버스 & 구도**: **16:9 가로 비율**, 순백색 또는 미색(#FAFAFA)의 넉넉한 여백(Whitespace).
2. **라인 워크**: 굵고 자연스러운 검은색 잉크 펜 손그림 라인 (Loose, organic hand-drawn black ink lines).
3. **미니멀 컬러 액센트**: 불필요한 그라데이션 없이 **레드(#FF4D4D), 오렌지(#FF9F1C), 블루(#2EC4B6)** 3가지 포인트 색상만 제한적으로 사용.
4. **텍스트 & 라벨**: 손글씨 느낌의 한국어 또는 영어 라벨 (단어 1~3개로 극도로 절제).
5. **분위기**: 복잡한 3D나 인위적인 'AI 티'를 완전히 배제한, 잡지나 에세이 책에 들어가는 세련된 에디토리얼 드로잉.

---

## 🚀 4단계 제작 워크플로우

```
[1. 핵심 개념 추출] ➔ [2. 시각적 메타포 매핑] ➔ [3. 구도 & 라벨링] ➔ [4. 프롬프트 출력]
```

### 1단계: 핵심 개념 추출 (Cognitive Anchor)
- 전달하려는 복잡한 비즈니스, 기술, 일상 개념 중 **'단 하나의 핵심 메시지'**를 정의합니다.

### 2단계: 시각적 메타포 매핑 (Metaphor Selection)
- 추상적인 생각을 직관적인 물리적 사물로 비유합니다:
  - 예: *정보 축적 ➔ 우물(Well)* / *아이디어 정제 ➔ 압축기(Press)* / *신뢰 구축 ➔ 다리(Bridge)* / *협업 인수인계 ➔ 이어달리기 바통(Baton)*

### 3단계: 구도 및 언어 선택 (Composition & Language)
- 사용자가 원하는 언어(**한국어 또는 영어**)에 맞게 라벨 텍스트를 구성합니다.
- `references/composition-patterns.md`에서 적합한 구도(대비, 파이프라인, 루프, 계층 등)를 선택합니다.

### 4단계: 표준 프롬프트 생성 (Prompt Output)
- Midjourney, DALL-E 3, Google Whisk 등 모든 이미지 생성 AI에서 100% 동일한 손그림 화풍을 재현하는 영문 프롬프트를 조립합니다.

---

## 📌 프롬프트 표준 출력 포맷

```markdown
### 🎨 [손그림 일러스트 기획]
- **핵심 개념**: [시각화할 주제]
- **선택된 메타포 & 구도**: [비유 요소 및 화면 배치]
- **라벨 언어**: [한국어 / English]

---

### 📝 생성 프롬프트 (Copy & Paste)

**[English Prompt for AI]**
A minimalist 16:9 editorial hand-drawn illustration with ample clean white background. In the center, [메타포 중심 피사체 및 인물 행동 묘사]. Loose organic black ink pen line drawing with subtle pops of accent colors (coral red, warm orange, and soft cobalt blue). Minimal hand-written text annotations in Korean/English reading "[라벨1]", "[라벨2]". Clean conceptual diagram style, sophisticated book illustration aesthetic, 16:9 aspect ratio, zero AI gradient slop.

---

### 💡 한글 해석 및 연출 팁
- [프롬프트 한국어 번역 및 이미지 생성 시 주의사항 설명]
```

---

## 📚 참조 문서
- `references/style-dna.md` : 상세 색상 코드, 선 굵기, 여백 규칙
- `references/composition-patterns.md` : 6대 구도 패턴 라이브러리
- `references/prompt-template.md` : AI 모델별(Whisk, Midjourney, DALL-E) 최적화 템플릿
- `references/qa-checklist.md` : 손그림 퀄리티 검수 체크리스트
