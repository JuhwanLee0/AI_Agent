---
name: pixel-office
description: 내 .claude/agents/ 폴더를 읽어, 내 AI 직원들이 일하는 픽셀 사무실(CCTV 화면)을 자동으로 지어준다. 에이전트가 지금 누가 뭘 하는지·누가 승인을 기다리는지를 한 화면에서 본다. 트리거 — "내 픽셀 오피스 만들어줘", "AI 직원 대시보드", "에이전트 사무실 띄워줘", "누가 일하는지 보여줘", "/pixel-office".
---

# 픽셀 오피스

`.claude/agents/` 폴더가 이미 당신의 조직도다. 그걸 읽어서 사무실을 짓는다.

**외부 의존 0** — 표준 라이브러리 + 단일 HTML만 쓴다. 설치·API 키·추가 요금 없다.
**전부 로컬** — 폴더를 읽고 로컬 서버를 띄운다. 바깥으로 나가는 요청이 없다.

## 실행 5단계

`{ROOT}` = 프로젝트 루트, `{SK}` = `.claude/skills/pixel-office`

### 1 SCAN — 조직도 읽기

```bash
python {SK}/scripts/scan_agents.py --root {ROOT} --out .pixel-office/org.json --preset {SK}/presets/default-5.json
```

- 프로젝트 `.claude/agents/*.md` + (`--global` 주면) `~/.claude/agents/*.md` 를 읽는다.
- 필수 프론트매터는 `name`·`description` 둘뿐이고 형식은 파일마다 달라도 된다 — 파서가 관대하다.
  `description` 이 없으면 본문 첫 제목 → 파일명 순으로 폴백한다.
- 에이전트가 하나도 없으면 `--preset` 의 기본 5인으로 시작한다.
- **확인**: `직원 N명` 과 구역별 인원이 출력되면 정상.

### 2 MAP — 역할을 자리로

스캔이 이름·설명의 키워드로 구역을 자동 배정한다(`research`/`server`/`meeting`/`desk`).

⚠️ **자동 배정은 만능이 아니다.** 설명에 다른 구역 단어가 섞이면 엉뚱한 자리로 간다.
(실제 사례: `critic` 의 설명에 "리서치 팩"이 있어 리서치 코너로, `video-engineer` 는 "QA"가 걸려 회의실로 갔다.)

고치려면 `.pixel-office/org.json` 의 해당 `zone` 값을 직접 바꾼다. 그게 정상 사용법이다.

### 3 WIRE — 신호 연결 (기존 훅 보존)

```bash
python {SK}/scripts/wire_hooks.py --settings .claude/settings.local.json --check   # 먼저 미리보기
python {SK}/scripts/wire_hooks.py --settings .claude/settings.local.json           # 실제 배선
```

- **기존 훅을 덮어쓰지 않는다.** 같은 이벤트에 항목을 덧붙이고, 저장 전 `.bak` 을 남긴다.
- 되돌리기: `--remove`
- **확인**: `보존된 기존 훅: N개` 가 배선 전과 같아야 정상.

### 4 LAYOUT + 5 BOOT — 사무실 열기

```bash
python {SK}/scripts/serve.py --org .pixel-office/org.json --port 8791 --open
```

브라우저에 사무실이 뜬다. 인원수에 맞춰 자리가 배치된다.

**스모크 테스트** (되는지 눈으로 확인):

```bash
curl -X POST http://127.0.0.1:8791/demo -H "Content-Type: application/json" -d "{\"zone\":\"research\"}"
```

캐릭터 하나가 리서치 코너로 **걸어가면** 정상이다. 안 움직이면 §트러블슈팅.

## 화면 조작

- `c` 키 — CCTV 오버레이 강도 전환(진하게 ↔ 옅게). 촬영 시 도입부는 진하게, 화면을 읽어야 하는 구간은 옅게.

## 왜 신호를 세 겹으로 받나 ★

서브에이전트 전용 이벤트(`SubagentStart`/`SubagentStop`)는 **실사용에서 신뢰할 수 없다.**
보고된 사례에서 `SubagentStart` 가 370건 중 42% 미발화했고, 발화해도 `agent_type` 이 비거나
`agent_id` 가 없는 경우가 있다. 관련 이슈는 되돌릴 계획 없이 닫혔다.
([claude-code#27755](https://github.com/anthropics/claude-code/issues/27755) ·
[#29677](https://github.com/anthropics/claude-code/issues/29677) ·
[#33049](https://github.com/anthropics/claude-code/issues/33049))

그래서 `hook_push.py` 는 이렇게 받는다:

| 순위 | 경로 | 얻는 것 |
|---|---|---|
| 1 | `PreToolUse` 의 `tool_input.subagent_type` | **이름** — 가장 안정적인 소스 |
| 2 | `SubagentStart` / `SubagentStop` | 오면 갱신 |
| 3 | 무이벤트 타임아웃 | 종료 신호를 못 받은 직원 자동 퇴근 |

⚠️ `tool_name` 은 v2.1.63부터 `"Task"` → `"Agent"` 로 바뀌었다. 둘 다 받는다.
`"Task"` 만 비교하면 **에러도 없이 아무 일도 안 일어난다.**

## 트러블슈팅

| 증상 | 원인 | 조치 |
|---|---|---|
| 캐릭터가 아예 안 뜬다 | 서버 미기동 / 포트 충돌 | `serve.py` 로그 확인, `--port` 변경 |
| 스모크는 되는데 실제 작업에 반응이 없다 | 훅 미배선 또는 다른 settings 파일에 배선됨 | `wire_hooks.py --check` 로 배선 위치 확인 |
| 직원이 책상에 영원히 앉아 있다 | 종료 신호 미수신 | 자동 퇴근(기본 90초) 대기. `serve.py` 의 `IDLE_SEC` 조정 |
| 이름이 안 붙고 `main` 으로만 나온다 | 서브에이전트가 아니라 메인 세션 이벤트 | 정상. 서브에이전트를 띄우면 이름이 붙는다 |

## 못 하는 것 (솔직히)

이건 **감시 화면**이다. 에이전트를 막거나, 되돌리거나, 비용을 보여주지 않는다.
실행 전 검사도 안 된다. 보이는 것뿐이고, 그게 이 도구가 파는 전부다.

## 파일

```
{SK}/
  SKILL.md
  scripts/scan_agents.py   # 1 SCAN
  scripts/wire_hooks.py    # 3 WIRE (기존 훅 보존 머지 + 백업 + --remove)
  scripts/hook_push.py     # 훅 → 서버 (3중 폴백)
  scripts/serve.py         # 4·5 LAYOUT + BOOT (상태 보관·자동 퇴근)
  web/office.html          # 화면 (Canvas 2D + CCTV 오버레이)
  presets/default-5.json   # 에이전트 없는 사람용
```
