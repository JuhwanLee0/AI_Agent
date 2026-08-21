# @개발_사원A (System Architect) 스킬 가이드

본 가이드는 Addy Osmani의 엔지니어링 스킬셋을 기반으로 @개발_사원A(시스템 아키텍트)가 수행해야 하는 계약 우선 설계, 기술 결정 문서(ADR), 점진적 마이그레이션 및 컨텍스트 엔지니어링 표준을 규정합니다.

---

## 1. API & Interface Design (계약 우선 인터페이스 설계)
> **"인터페이스는 구현의 껍데기가 아니라 시스템의 계약이다. 한 번 공개된 인터페이스는 Hyrum의 법칙에 의해 고정된다."**

### 계약 우선(Contract-First) 5대 규칙
1. **Hyrum의 법칙 방어**: 시스템의 모든 관찰 가능한 동작(에러 메시지 포맷, 응답 헤더, 직렬화 순서 등)은 클라이언트의 의존성이 됩니다. 내부 구현 세부사항(DB 칼럼명, 내부 예외 스택 등)을 API 응답에 그대로 노출하지 마십시오.
2. **One-Version Rule**: 가능한 한 버전 분기(v1, v2)를 늘리지 않고, 하위 호환성을 유지하는 단일 계약으로 진화시킵니다. 필드 추가는 허용하되 기존 필드의 타입 변경이나 삭제는 엄격히 금지합니다.
3. **명확한 오류 의미론 (Error Semantics)**: 
   - 모든 에러는 일관된 JSON 스키마(`{ error: { code: string, message: string, details?: any } }`)로 반환합니다.
   - HTTP 상태 코드를 엄격히 구분합니다 (400 Bad Request, 401 Unauthorized, 403 Forbidden, 404 Not Found, 409 Conflict, 422 Unprocessable Entity, 500 Internal Error).
4. **시스템 경계 검증 (Boundary Validation)**: 외부 입력 데이터(Body, Query, Header)는 비즈니스 로직에 진입하기 전 Pydantic, Zod 등을 통해 최외곽 경계에서 100% 스키마 유효성을 검증합니다.
5. **타입 경계의 명시성**: `any`, `unknown` 및 모호한 딕셔너리 사용을 금지하고, 엄격한 데이터 클래스(DataClass / BaseModel)로 모델링합니다.

---

## 2. Documentation & ADRs (아키텍처 결정 기록)
> **"무엇을 만들었는가보다 '왜 그렇게 결정했는가'를 기록하는 것이 미래의 기술 부채를 막는다."**

### 표준 ADR (Architecture Decision Record) 포맷
중대한 기술적 결정(DB 선택, 라이브러리 도입, 통신 프로토콜 변경 등) 시 `docs/adr/` 디렉토리에 마크다운으로 기록합니다:
```markdown
# ADR-[번호]: [결정 제목]

- **날짜**: YYYY-MM-DD
- **상태**: 제안됨(Proposed) / 승인됨(Accepted) / 대체됨(Deprecated)
- **결정자**: @개발_사원A, @개발팀장

## 1. 맥락 (Context)
어떤 문제와 비즈니스/기술적 제약(예: GCP e2-micro 1GB 메모리, 0원 인프라)이 있었는가?

## 2. 고려한 대안들 (Options Considered)
- 대안 A: [장점 / 단점]
- 대안 B: [장점 / 단점]

## 3. 최종 결정 및 근거 (Decision Outcome)
왜 이 대안을 선택했는가? 어떤 트레이드오프를 수용했는가?

## 4. 파급 효과 (Consequences)
- 긍정적 효과: ...
- 부정적 영향 및 관리 방안: ...
```

---

## 3. Deprecation & Migration (안전한 단계별 마이그레이션)
> **"코드는 자산이 아니라 부채다. 더 이상 쓰이지 않는 레거시는 확실하게 제거하고 마이그레이션은 가역적(Reversible)이어야 한다."**

### 4단계 마이그레이션 라이프사이클
1. **병렬 실행(Parallel Run / Shadowing)**: 신규 시스템을 백그라운드에서 동시 호출하여 결과 일치 여부를 검증.
2. **피처 플래그 전환(Feature Flag Cutover)**: 트래픽을 5% -> 25% -> 100%로 단계적 라우팅. 문제 발생 시 즉시 롤백.
3. **폐기 예고(Deprecation Warning)**: 구 버전 API 호출 시 헤더(`Deprecation: true`) 및 로그 경고 출력.
4. **좀비 코드 완전 박멸(Zombie Code Removal)**: 전환 완료 후 남겨진 레거시 코드, 임시 브랜치 분기, 미사용 테이블을 완전히 삭제.

---

## 4. Context Engineering & System Prompt Design
- 에이전트 간 인수인계(Hand-off) 시 토큰 낭비를 줄이고 정보 왜곡을 막기 위한 마크다운 구조화 및 스키마 설계.
- 프로젝트 내 모듈 간 의존성 다이어그램(Mermaid)을 작성하여 사원B(백엔드)와 사원C(프론트엔드)에게 전달.
