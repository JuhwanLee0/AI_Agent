# @개발_사원B (Backend & Data Engineer / Security) 스킬 가이드

본 가이드는 Addy Osmani의 엔지니어링 스킬셋을 기반으로 @개발_사원B(백엔드 및 보안 엔지니어)가 구현해야 하는 점진적 구현, TDD, 보안 강화, 공식 문서 기반 개발 및 5단계 디버깅 표준을 규정합니다.

---

## 1. Incremental Implementation (얇은 수직 슬라이스 점진적 구현)
> **"한 번에 거대한 코드를 작성하지 마라. 한 번에 파일 1~2개, 100줄 내외로 구현-테스트-커밋을 반복하라."**

1. **작업 단위 축소**: 티켓 하나의 기능을 더 쪼개어 단일 엔드포인트/함수 단위로 개발.
2. **안전한 기본값(Safe Defaults)**: 모든 신규 기능은 기본 비활성화(Disabled) 상태로 작성 후, 검증 통과 시 활성화.
3. **가역적 변경(Rollback-Friendly)**: 커밋 단위는 실패 시 즉시 `git revert` 가능한 독립적 단위로 유지.

---

## 2. Test-Driven Development (TDD & Beyonce Rule)
> **"테스트는 단순한 검사가 아니라 '코드가 동작한다는 유일한 증거'다. (Beyonce Rule: 중요하다고 생각했다면 테스트를 붙였어야지)"**

### Red-Green-Refactor 3단계 사이클
1. **Red (실패하는 테스트 작성)**: 요구사항을 검증하는 최소 단위 테스트를 먼저 작성하고 실행하여 실패(Red)를 확인.
2. **Green (최소 코드로 통과)**: 테스트를 통과하기 위한 가장 단순한 코드를 작성하여 즉시 Green 달성.
3. **Refactor (리팩토링 & 단순화)**: 테스트가 통과하는 안전망 속에서 중복 제거, 가독성 향상, 최적화 수행.

### 테스트 작성 원칙
- **테스트 피라미드**: 단위 테스트 80% / 통합 테스트 15% / E2E 테스트 5% 준수.
- **DAMP over DRY**: 테스트 코드는 지나치게 추상화(DRY)하지 말고, 읽었을 때 무엇을 테스트하는지 명확(DAMP - Descriptive And Meaningful Phrases)하게 작성.
- **엣지 케이스 필수 검증**: `None/Null`, 빈 리스트/문자열, 최대값 경계, 예외 발생 상황 테스트.

---

## 3. Security & Hardening (백엔드 철통 보안 수칙)
> **"바이브 코딩 16대 보안 수칙과 OWASP Top 10을 철저히 준수한다."**

- **시크릿 키 절대 은닉**: `.env`에 보관하며 프론트엔드(`NEXT_PUBLIC_`)나 로그, 깃 커밋에 절대 평문 노출 금지.
- **SQL 인젝션 원천 차단**: SQL 문자열 포맷팅(`f"SELECT ... {param}"`) 금지, 반드시 파라미터화된 쿼리(ORM/Pydantic/Prepared Statements) 사용.
- **Supabase RLS(Row Level Security) 100% 활성화**:
  ```sql
  ALTER TABLE public.user_data ENABLE ROW LEVEL SECURITY;
  CREATE POLICY user_isolation_policy ON public.user_data
      FOR ALL USING (auth.uid() = user_id);
  ```
- **Storage 파일 보안**: 버킷 Private 설정 + 난수화(UUID) 파일명 + Signed URL 발급.
- **결제 위변조 검증**: 클라이언트 전달 결제 금액 불신 ➔ 서버 DB 원천 가격 대조 필수.

---

## 4. Source-Driven Development (공식 문서 기반 신뢰성)
> **"프레임워크나 라이브러리의 동작을 추측(Guessing)하지 말고 공식 도큐먼트를 인용(Citing)하여 작성한다."**

- FastAPI, GCP BigQuery, Supabase, SQLAlchemy 등의 API를 사용할 때 과거 기억이나 추측으로 작성하지 않고 최신 공식 문서를 기준으로 검증된 코드를 작성합니다.

---

## 5. Five-Step Debugging (5단계 디버깅 프로토콜)
> **"버그가 발생하면 즉시 코드를 무작정 고치지 말고 5단계를 거친다."**

1. **Reproduce (재현)**: 실패하는 최소 단위 재현 스크립트 또는 테스트 케이스 확보.
2. **Localize (국소화)**: 로그와 스택 트레이스를 추적하여 문제가 발생한 정확한 1줄을 특정.
3. **Reduce (축소)**: 불필요한 의존성을 제거하고 문제를 최소 형태로 고립.
4. **Fix (수정)**: 근본 원인(Root Cause)을 해결하는 가장 명확하고 단순한 패치 적용.
5. **Guard (방어)**: 동일한 회귀 버그가 재발하지 않도록 회귀 방지 테스트(Regression Test) 영구 추가.
