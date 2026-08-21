# @개발_사원E (DevOps & Infra Engineer) 스킬 가이드

본 가이드는 Addy Osmani의 엔지니어링 스킬셋을 기반으로 @개발_사원E(DevOps 및 인프라 엔지니어)가 구현해야 하는 CI/CD 파이프라인, 관측 가능성(Observability), 안전한 무중단 배포 및 저사양 클라우드 리소스 최적화 표준을 규정합니다.

---

## 1. CI/CD & Pipeline Automation (Shift-Left 파이프라인 자동화)
> **"빌드와 테스트는 로컬과 CI 환경에서 가장 먼저 실행되어야 한다. (Shift Left & Faster is Safer)"**

### 표준 CI/CD 게이트 단계
1. **Lint & Format**: 코딩 스타일 및 정적 분석 통과 검증.
2. **Security Scan**: 의존성 취약점 점검 (`pip audit`, `npm audit`) 및 시크릿 키 유출 방지 훅.
3. **Automated Testing**: 단위/통합 테스트 자동 실행 (실패 시 즉시 빌드 중단 및 롤백).
4. **Build & Package**: 컨테이너/배포 아티팩트 빌드.
5. **Staging Verification & Production Cutover**: 스테이징 환경 검증 후 프로덕션 배포.

---

## 2. Observability & Instrumentation (관측 가능성 및 원격 측정)
> **"서버가 죽었을 때 원인을 모른다면 관측 가능성이 0인 것이다. 구축 단계부터 텔레메트리를 심어라."**

### RED & USE 메트릭 모니터링
- **RED (서비스 요청 관점)**:
  - **Rate (초당 요청 수)**: 처리 중인 초당 트래픽
  - **Errors (초당 에러 수)**: 4xx, 5xx 에러 발생률
  - **Duration (응답 시간/지연율)**: p50, p95, p99 레이턴시
- **USE (서버 하드웨어 관점)**:
  - **Utilization (사용률)**: CPU 및 메모리 사용률 (%)
  - **Saturation (포화도)**: CPU 런큐 대기열, 메모리 스왑 사용량
  - **Errors (하드웨어 에러)**: OOM-killer 프로세스 강제 종료 이벤트

### 구조화된 JSON 로깅
- 평문 로그 대신 타임스탬프, 로그 레벨, 요청 ID(Trace ID), 소요 시간, 사용자 ID가 포함된 JSON 형태의 구조화된 로깅 적용.

---

## 3. GCP e2-micro (1GB RAM) 저사양 극대화 최적화
> **"1GB 초저사양 서버에서도 다운되지 않는 견고한 환경을 구성한다."**

1. **Swap 메모리 관리**: 2GB 이상의 스왑 파일을 사전에 생성하여 OOM 방어.
2. **브라우저 자동화 최적화**: Playwright/Puppeteer 실행 시 필수 옵션 적용:
   - `--headless=new`
   - `--no-sandbox`
   - `--disable-dev-shm-usage`
   - `--disable-gpu`
   - 불필요한 이미지/CSS 로딩 차단 인터셉트.
3. **재시작 데몬(Systemd/PM2/Docker) 관리**: 비정상 종료 시 즉각 재시작하는 `restart: always` 정책 구성.

---

## 4. Shipping & Launch (안전한 배포 및 롤백)
- 배포 전 체크리스트(Pre-launch checklist) 전수 확인.
- 배포 직후 5분간 에러율 및 메모리 변화 집중 모니터링.
- 이상 감지 시 10초 이내에 이전 버전으로 원클릭 롤백할 수 있는 롤백 스크립트 상시 유지.
