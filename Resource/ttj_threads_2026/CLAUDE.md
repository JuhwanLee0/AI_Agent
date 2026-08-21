# Project Instructions

메인 코드 = run.js -> 수정사항 있을때마다 이 가이드 문서 최신화 하기. 
** 서브 에이전트 & 팀원의 작업도 모두 가이드 최신화 진행하기 **

---

# run.js 기능 가이드

이 문서는 `run.js`가 어떤 일을 하는지, 그리고 각 기능이 어떻게 동작하는지를 초보자도 이해할 수 있도록 정리한 가이드입니다.

> **한 줄 요약**: `run.js`는 Puppeteer로 크롬을 띄워 Threads에 자동 로그인하고, 탐색 피드에서 유저를 찾아 팔로우/좋아요/리포스트/AI 댓글을 자동으로 수행한 뒤, 원하면 새 게시글까지 올려주는 자동화 스크립트입니다.

## 전체 실행 흐름 (큰 그림)

```
main()
  ├─ validateAIConfig()            ← API 모드 사용 시 .env 키 검증
  ├─ findChromePath()              ← 설치된 크롬 찾기
  ├─ getUserCredentials()          ← 계정 정보 로드
  ├─ createBrowserProfileDir()     ← 유저별 브라우저 프로필 폴더 생성
  ├─ normalizeChromeProfileState() ← 크롬 비정상 종료 상태 정리 (충돌 경고 제거)
  ├─ initBrowser()                 ← 크롬 실행
  ├─ setupPage()                   ← 봇 탐지 우회 + 한국 환경 설정
  ├─ waitForManualLogin()          ← 사용자가 브라우저에서 직접 로그인할 때까지 대기
  ├─ ensureSession()               ← 닉네임 확인 및 저장
  ├─ runInteractions()             ← 피드 상호작용 (팔로우/좋아요/리포스트/댓글)
  │    └─ processFriendshipMode()
  │         └─ tryNextUser()       ← 재귀로 다음 유저 시도
  ├─ runPosting()                  ← 게시글 작성 (writePost=1일 때)
  ├─ handleShutdown()              ← 브라우저 종료 또는 대기
  └─ normalizeChromeProfileState() ← 종료 시 프로필 상태 재정리 (finally)
```

---

## 기능 1: 수동 로그인 감지 (사용자가 직접 로그인 → 닉네임 감지 후 진행)

이미 로그인된 상태면 그대로 진행하고, 아니면 사용자가 브라우저에서 직접 로그인할 때까지 3초마다 닉네임을 확인하며 대기합니다.

**시작 조건**: `main()` 호출 시 자동 실행 (필수 단계)
**데이터 흐름**:
`main()` → `waitForManualLogin()` → 쿠키로 `fetchSessionInfo()` → 닉네임 있으면 즉시 통과 / 없으면 "직접 로그인해주세요" 안내 → 3초마다 `fetchSessionInfo()` 폴링 → 닉네임 감지 시 통과 → `ensureSession()` → `saveNickName()` 저장

**관련 설정**: 없음 (자동 로그인 없음, 사용자가 브라우저에서 직접 로그인)
**관련 파일**: `lib/utils.js`의 `buildCookieString`, `fetchSessionInfo`, `saveNickName`

---

## 기능 2: 피드 상호작용 (팔로우 / 좋아요 / 리포스트 / AI 댓글)

탐색 피드에서 팔로우하지 않은 유저를 찾아 한 명씩 시도하면서, AI 안전성 검사를 통과한 유저에게만 팔로우/좋아요/리포스트/댓글을 수행합니다.

**시작 조건**: `useFollow`, `useLike`, `useRepost`, `commentMode` 중 하나라도 활성화
**데이터 흐름**:
`main()` → `runInteractions()` → `processFriendshipMode()` → 홈 이동 → `/search` 클릭 → `scrollDown()` 1회 → `scrapeThreadsFeed()`로 카드 목록 수집 (이미 팔로우한 유저 제외) → `tryNextUser()` 재귀 시작

`tryNextUser()` 내부:
1. `scrapeUserPosts()` → 해당 유저 최신 게시글 URL 가져오기
2. `analyzePostContent()` → 게시글 페이지 이동 → `scrapePostContentInPlace()`로 본문 추출 → `buildAnalysisForMode()`로 AI 안전성 검사 + 댓글 생성
3. AI가 `use:false` → 다음 유저로 재귀 호출
4. AI 통과 → `user.userUrl`(프로필 페이지)로 이동 → `followOnProfile()` (팔로우/맞팔로우) → `newPostUrl`(게시글 페이지)로 재이동 → `performPostActions()` (좋아요 → 리포스트 → 댓글)
5. `buildResultRecord()` → AI 응답 직후 `result.json` 저장

### 2-1. 팔로우 (`followOnProfile`)
유저 프로필에서 "팔로잉" 상태인지 재확인 → "팔로우" 버튼 클릭 → "맞팔로우" 버튼 있으면 추가 클릭
**관련 설정**: `useFollow` (0/1)

### 2-2. 좋아요 (`clickLike`)
`svg[aria-label="좋아요"]` 버튼 클릭
**관련 설정**: `useLike` (0/1)

### 2-3. 리포스트 (`clickRepost`)
`aria-haspopup="dialog"` 버튼 클릭 → 팝업 메뉴에서 "리포스트" 항목 클릭
**관련 설정**: `useRepost` (0/1)

### 2-4. 댓글 (`postComment`)
답글 버튼 클릭 → `contenteditable` 입력창에 댓글 타이핑 → "게시" 버튼 클릭
**관련 설정**: `commentMode` (0: 없음, 1: 고정 댓글, 2: AI 생성), `FRIEND_COMMENT`

---

## 기능 3: AI 안전성 필터 (스팸 키워드 + AI 판단)

부적합한 게시글(만남 유도, 신청서, 폭력, 성인물 등)에는 댓글을 달지 않습니다. 1차로 키워드 필터, 2차로 설정된 AI가 판단합니다.

**시작 조건**: `commentMode !== 0`
**데이터 흐름**:
`analyzePostContent()` → `buildAnalysisForMode()` → `analyzeAndComment()` →
1. 빈 글이면 `use:false` 반환
2. `SPAM_KEYWORDS`에 포함된 단어 있으면 `use:false` 반환
3. `buildAnalysisPrompt()`로 AI용 프롬프트 생성
4. `callAI()` → `AI_MODE`에 따라 적절한 AI 호출 (Gemini CLI / Codex CLI / Claude CLI / Gemini API / GPT API). 실패 시 `SECOND_AI_MODE`로 자동 재시도 (`SECOND_AI_MODE=0`이면 재시도 없음).
   Claude CLI(`AI_MODE=3`)는 비대화형 `-p --output-format text` 모드로 실행되며, 프롬프트는 명령행 인자가 아니라 `stdin`으로 전달합니다. 특히 Windows에서 긴 프롬프트/따옴표가 포함된 인자 전달이 깨져 입력 없음으로 실패하는 문제를 피하기 위한 설정입니다. Claude 한도 초과가 감지되면 원문 전체 대신 짧은 경고 로그만 남기고 `SECOND_AI_MODE`로 재시도합니다.
5. `parseAnalysisResponse()` → 코드블록/일반 텍스트 안의 JSON 객체를 안전하게 추출
6. JSON 파싱 성공 시 `{use, country_lang, content}` 반환 + `cleanResponse()`로 이모지/마크다운 제거
7. JSON 파싱 실패나 AI 호출 실패 시 `use:false`로 안전하게 건너뜀

**관련 설정**:
- `commentMode` (0/1/2)
- `AI_MODE` (1~5, 사용할 AI 선택)
- `SECOND_AI_MODE` (AI_MODE 실패 시 시도할 AI, 0이면 재시도 없음)
- `GEMINI_MODEL` (AI_MODE=4일 때 사용할 Gemini 모델명)
- `GPT_MODEL` (AI_MODE=5일 때 사용할 GPT 모델명)
- `SPAM_KEYWORDS` (배열, 차단할 키워드)
- `.env`의 `GEMINI_API_KEY` (AI_MODE/SECOND_AI_MODE=4일 때 사용)
- `.env`의 `OPENAI_API_KEY` (AI_MODE/SECOND_AI_MODE=5일 때 사용)

---

## 기능 4: 재시도 로직 (부적합 게시글 → 다음 유저 자동 시도)

AI가 한 유저의 게시글을 거절하면, 그 유저를 건너뛰고 다음 유저의 게시글을 자동으로 시도합니다. 재귀 함수로 구현되어 있습니다.

**시작 조건**: `tryNextUser()`가 호출되었고 AI가 `use:false`를 반환했을 때
**데이터 흐름**:
`tryNextUser(users, idx=0)` →
- 게시글 없음 → `tryNextUser(users, idx+1)` 재귀
- AI 거절 (`use:false`) → `tryNextUser(users, idx+1)` 재귀
- AI 통과 → 액션 수행 + `result.json` 저장 후 종료
- 모든 유저 소진 시 → "적합한 게시글을 찾지 못했습니다" 출력 후 종료

**관련 설정**: 없음 (`processFriendshipMode()`가 수집한 유저 수만큼 시도)

---

## 기능 5: 게시글 작성 (본문 + 주제 태그 + 이미지 첨부 + 답글)

상호작용이 끝난 후, 직접 새 게시글을 올립니다. 본문 입력, 주제 태그 추가, 이미지 업로드, 게시 후 답글 작성까지 자동화됩니다.

**시작 조건**: `writePost === 1`
**데이터 흐름**:
`runPosting()` →
1. `openComposeModal()` → 홈에서 "만들기" 버튼 클릭 → 작성 모달 대기
2. `setPostTopic(POST_TOPIC)` → "주제 추가" 입력창에 타이핑 → 자동완성 첫 옵션 클릭
3. `setPostBody(POST_BODY)` → 본문 입력 (URL 포함 시 OG 카드 로딩 대기)
4. `attachPostImage(POST_IMAGE)` → 파일 input에 이미지 업로드 (`uploadImage===1`일 때만)
5. `submitPostAndGetCode()` → "게시" 버튼 클릭 + `/api/v1/media/configure_text` 응답 가로채서 `media.code` 추출
6. 게시글 URL 생성 → 해당 페이지로 이동
7. `submitReply(POST_REPLY)` → 답글 버튼 클릭 → 답글 입력 (URL이면 OG 카드 대기) → 게시

**관련 설정**:
- `writePost` (0: 안 함, 1: 작성)
- `uploadImage` (0/1)
- `POST_BODY` (본문 텍스트)
- `POST_TOPIC` (주제 태그)
- `POST_IMAGE` (업로드할 이미지 경로)
- `POST_REPLY` (게시 후 달 답글, 빈 문자열이면 답글 건너뜀)

---

## 기능 6: 결과 저장 (result.json)

AI 댓글까지 정상 파싱된 유저의 정보와 분석 결과를 `result.json`에 저장합니다. 한 번 실행에 한 명의 유저만 저장됩니다.

**시작 조건**: `tryNextUser()`에서 AI 통과 시 자동 실행
**데이터 흐름**:
`tryNextUser()` → `buildAiResult()` → `buildResultRecord()` (유저 정보 + AI 결과 합산) → `fsPromises.writeFile('result.json', ...)`

**저장 형식 예시**:
```json
[
  {
    "userName": "...",
    "userUrl": "https://www.threads.net/@...",
    "postUrl": "https://www.threads.net/.../post/...",
    "postContent": "...",
    "ai_use": true,
    "ai_lang": "한국어",
    "ai_comment": "...",
    "ai_skip_reason": "",
    "ai_at": "2026-05-11T..."
  }
]
```

**관련 설정**: 없음 (`__dirname/result.json`에 저장)

---

## 기능 7: 브라우저 종료 모드 (수동/자동)

작업이 모두 끝난 뒤 브라우저를 사용자가 닫을 때까지 기다릴지, 자동으로 닫을지 결정합니다.

**시작 조건**: `main()` 마무리 단계에서 자동 실행
**데이터 흐름**:
`handleShutdown(browser)` →
- `RUN_MODE === 1` → `browser.on('disconnected')` 대기 (수동 종료)
- `RUN_MODE === 2` → `browser.close()` 즉시 종료

**관련 설정**: `RUN_MODE` (1: 수동 종료, 2: 자동 종료)

---

## 기능 8: 봇 탐지 우회 + 한국 환경 설정 (`setupPage`)

Threads가 자동화 도구를 탐지하지 못하도록 위장하고, 한국 사용자처럼 동작하도록 설정합니다.

**시작 조건**: 브라우저 시작 직후 자동 실행
**데이터 흐름**:
`setupPage(page)` →
1. `viewport` 설정 (화면 크기)
2. `navigator.webdriver` → `false`로 위장
3. `dialog` 이벤트 자동 수락 (beforeunload 알림창)
4. HTTP 헤더에 `Accept-Language: ko-KR` 등 추가
5. `geolocation` → 서울 좌표 (37.5665, 126.9780) 모킹
6. `emulateTimezone('Asia/Seoul')` → 한국 표준시

**관련 설정**: `HEADLESS_MODE` (false: 화면 표시, 'new': 헤드리스)

---

## 설정 변수 전체 정리

| 변수명 | 위치 | 기본값 | 설명 |
|--------|------|--------|------|
| `RUN_MODE` | 실행 제어 | `1` | 1: 사용자가 브라우저 닫을 때까지 대기, 2: 작업 후 자동 종료 |
| `HEADLESS_MODE` | 실행 제어 | `false` | false: 브라우저 창 표시, `'new'`: 화면 없이 백그라운드 실행 |
| `useFollow` | 상호작용 | `1` | 0: 팔로우 안 함, 1: 팔로우함 |
| `useLike` | 상호작용 | `1` | 0: 좋아요 안 함, 1: 좋아요함 |
| `useRepost` | 상호작용 | `1` | 0: 리포스트 안 함, 1: 리포스트함 |
| `commentMode` | 상호작용 | `2` | 0: 댓글 안 달기, 1: `FRIEND_COMMENT` 고정 댓글, 2: AI 댓글 |
| `AI_MODE` | 상호작용 | `1` | 1: Gemini CLI, 2: Codex CLI, 3: Claude CLI, 4: Gemini API, 5: GPT API |
| `SECOND_AI_MODE` | 상호작용 | `2` | AI_MODE 실패 시 폴백 (0: 재시도 안 함, 1~5: 동일한 모드 번호) |
| `GEMINI_MODEL` | 상호작용 | `'gemini-2.5-flash'` | `AI_MODE=4`일 때 사용할 Gemini 모델명 |
| `GPT_MODEL` | 상호작용 | `'gpt-4o-mini'` | `AI_MODE=5`일 때 사용할 GPT 모델명 |
| `FRIEND_COMMENT` | 상호작용 | `'좋아요 눌렀어!'` | `commentMode=1`일 때 사용할 고정 댓글 |
| `SPAM_KEYWORDS` | AI 필터 | `['성인', '19금']` | 게시글에 포함되면 즉시 차단할 키워드 배열 |
| `writePost` | 글쓰기 | `1` | 0: 글 안 씀, 1: 상호작용 후 글 작성 |
| `uploadImage` | 글쓰기 | `1` | 0: 이미지 없음, 1: `POST_IMAGE` 첨부 |
| `POST_BODY` | 글쓰기 | `'안녕하세요!'` | 게시글 본문 |
| `POST_TOPIC` | 글쓰기 | `'맥북'` | 게시글 주제 태그 |
| `POST_IMAGE` | 글쓰기 | `src/imgs/1.jpg` | 업로드할 이미지 파일 경로 |
| `POST_REPLY` | 글쓰기 | `'https://ttj.kr -> 요기!!'` | 게시 직후 자기 글에 다는 답글 (빈 문자열이면 건너뜀) |

### 환경 변수 (`.env`)

| 변수명 | 설명 |
|--------|------|
| `GEMINI_API_KEY` | `AI_MODE=4` (Gemini API) 사용 시 필요한 키 |
| `OPENAI_API_KEY` | `AI_MODE=5` (GPT API) 사용 시 필요한 키 |
| `NICK_NAME` | 로그인 후 저장되는 자기 닉네임 (피드에서 자기 자신 제외용) |

### 자동 감지 항목

| 항목 | 동작 |
|------|------|
| 크롬 실행 경로 | `findChromePath()`가 macOS/Windows/Linux 표준 경로 자동 탐지 |
| 브라우저 프로필 | `browser_profile/{id}_browser_profile/` 폴더 자동 생성 |
| 크롬 확장 프로그램 | `extensions/` 폴더 내 하위 디렉토리 자동 로드 |

---

## 실행 시나리오 예시

### 시나리오 A: 좋아요+팔로우만 하고 끝내기
```js
useFollow = 1;
useLike = 1;
useRepost = 0;
commentMode = 0;     // AI 분석도 건너뜀
writePost = 0;
```

### 시나리오 B: AI 댓글 + 새 글 작성까지 풀 자동화
```js
useFollow = 1;
useLike = 1;
useRepost = 1;
commentMode = 2;     // AI 댓글 (AI_MODE로 어떤 AI 사용할지 선택)
AI_MODE = 1;         // 1: Gemini CLI, 2: Codex CLI, 3: Claude CLI, 4: Gemini API, 5: GPT API
writePost = 1;
uploadImage = 1;
```

### 시나리오 C: 글만 올리기 (피드 상호작용 없음)
```js
useFollow = 0;
useLike = 0;
useRepost = 0;
commentMode = 0;     // 모두 0이면 runInteractions에서 스킵
writePost = 1;
```
