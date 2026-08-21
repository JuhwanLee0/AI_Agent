# Global Skill: GSD (Get Shit Done) - Autonomous Situational Dispatch

## 1. GSD 개요 및 6대 상황별 디스패치 규칙
GSD는 다단계 프로젝트 기획, 단계별 실행, 검증, 디버깅을 체계적이고 자율적으로 완수하는 오케스트레이션 프레임워크입니다.
모든 에이전트는 복잡한 다단계 작업이나 프로젝트 변경 시 GSD 워크플로우에 따라 단계를 나누고 검증 루프를 거칩니다.

### 6대 상황별 GSD 액션
1. **신규 기획 / 계획 부재 (`gsd-new-project` / `gsd-map-codebase`)**:
   - `.planning/` 및 `ROADMAP.md`가 없거나 새로운 프로젝트일 때 전체 구조를 맵핑하고 마일스톤을 수립합니다.
2. **다음 단계 전진 (`gsd-next` / `gsd-progress`)**:
   - 이미 수립된 로드맵에서 다음 페이즈를 탐색하고 즉시 활성화합니다.
3. **페이즈 상세 계획 (`gsd-plan-phase` / `gsd-discuss-phase`)**:
   - 활성화된 페이즈를 얇은 수직 슬라이스(Vertical Slice, 1회 100~300줄) 단위의 실행 계획(`PLAN.md`)으로 구체화합니다.
4. **페이즈 실행 및 검증 (`gsd-execute-phase` / `gsd-verify-work`)**:
   - 계획된 순서대로 코드를 구현하고, UAT 및 인수 조건을 대조하여 증거 기반으로 검증합니다.
5. **경량 / 신속 작업 (`gsd-quick` / `gsd-fast`)**:
   - 단일 파일 수정, 사소한 버그 픽스 등 단순한 작업은 서브에이전트 오버헤드 없이 원자적 커밋과 상태 갱신만으로 즉시 처리합니다.
6. **체계적 디버깅 및 감사 (`gsd-debug` / `gsd-audit-fix`)**:
   - 에러 발생 시 5단계 디버깅 프로토콜(Reproduce ➔ Localize ➔ Reduce ➔ Fix ➔ Guard)을 적용하여 원인을 박멸합니다.

## 2. GSD 파일 체계 (`.planning/`)
- `.planning/ROADMAP.md`: 전체 마일스톤 및 페이즈 목록, 완료 상태
- `.planning/STATE.md`: 현재 활성 페이즈, 진행률, 블로커 및 최근 의사결정
- `.planning/phases/`: 페이즈별 상세 실행 계획(`PLAN.md`) 및 검증 보고서(`VERIFY.md`)
