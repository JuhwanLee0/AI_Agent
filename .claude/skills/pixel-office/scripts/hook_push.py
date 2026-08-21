"""훅 이벤트 → 오피스 서버로 상태 전송.

Claude Code 훅이 stdin 으로 JSON 페이로드를 준다. 그걸 읽어 상태를 정하고
로컬 오피스 서버에 POST 한다. 실패해도 **절대 죽지 않는다** — 이 스크립트가
에러를 내면 사용자의 Claude Code 세션이 방해받는다.

★3중 폴백이 이 파일의 존재 이유다 (설계 SoT §4.4-b).
서브에이전트 전용 이벤트(SubagentStart/Stop)는 실사용에서 신뢰할 수 없다
(보고 사례 370건 중 42% 미발화, agent_type 공란). 그래서:

  1순위  PreToolUse(tool_name == "Agent") 의 tool_input.subagent_type 에서 이름 확보
  2순위  SubagentStart/SubagentStop 이 오면 그걸로 갱신
  3순위  둘 다 없으면 서버가 JSONL 트랜스크립트로 복원 (serve.py 담당)

그리고 종료 신호를 못 받은 직원은 서버가 일정 시간 뒤 자동 퇴근시킨다.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_URL = os.environ.get("PIXEL_OFFICE_URL", "http://127.0.0.1:8791")
TIMEOUT = 1.0  # 훅은 세션을 막으면 안 된다. 짧게 끊는다.

# 툴 이름 → 구역. 어느 자리로 걸어갈지.
TOOL_ZONE = {
    "Read": "desk",
    "Write": "desk",
    "Edit": "desk",
    "NotebookEdit": "desk",
    "Grep": "research",
    "Glob": "research",
    "WebSearch": "research",
    "WebFetch": "research",
    "Task": "meeting",
    "Agent": "meeting",
}


def zone_for_tool(tool_name: str, tool_input: dict) -> str:
    if tool_name == "Bash":
        cmd = str(tool_input.get("command", ""))
        if any(k in cmd for k in ("git push", "git commit", "deploy", "rsync", "scp")):
            return "server"
        return "desk"
    return TOOL_ZONE.get(tool_name, "desk")


def build_event(payload: dict) -> dict | None:
    """훅 페이로드 → 서버가 이해하는 이벤트. 보낼 게 없으면 None."""
    ev = payload.get("hook_event_name", "")
    # 서브에이전트 안에서 발화한 툴 훅이면 그 직원 것으로 귀속된다
    agent_id = payload.get("agent_id") or ""
    agent_type = payload.get("agent_type") or ""

    if ev == "SessionStart":
        return {"kind": "boss_in", "session": payload.get("session_id", "")}

    if ev == "Stop":
        return {"kind": "boss_idle", "session": payload.get("session_id", "")}

    if ev == "SubagentStart":
        # agent_type 이 비어 오는 사례가 보고돼 있다 — 비면 버리고 1순위 경로에 맡긴다
        if not agent_type:
            return None
        return {"kind": "hire", "id": agent_id or agent_type, "name": agent_type, "src": "subagent_start"}

    if ev == "SubagentStop":
        if not (agent_id or agent_type):
            return None
        return {"kind": "leave", "id": agent_id or agent_type, "src": "subagent_stop"}

    if ev == "PermissionRequest":
        return {"kind": "state", "id": agent_id or "main", "zone": "waiting", "name": agent_type}

    if ev in ("PreToolUse", "PostToolUse"):
        tool = payload.get("tool_name", "")
        tinput = payload.get("tool_input") or {}

        # ★1순위 경로: 서브에이전트를 띄우는 순간. 여기서 이름을 먼저 챙긴다.
        #   v2.1.63 부터 tool_name 이 "Task" → "Agent" 로 바뀌었으므로 둘 다 받는다.
        if tool in ("Task", "Agent"):
            sub = tinput.get("subagent_type") or ""
            if not sub:
                return None
            # ★id 는 tool_use_id 여야 한다. subagent_type 을 id 로 쓰면
            #   같은 종류를 여러 개 동시에 띄웠을 때 전부 한 사람으로 합쳐진다
            #   (실측: Explore 6개 병렬 → 캐릭터 1명). 하필 병렬일 때 틀린다.
            uid = payload.get("tool_use_id") or f"{sub}:{payload.get('session_id','')}"
            if ev == "PreToolUse":
                return {"kind": "hire", "id": uid, "name": sub, "src": "pre_agent"}
            return {"kind": "leave", "id": uid, "src": "post_agent"}

        if ev != "PreToolUse":
            return None
        return {
            "kind": "state",
            "id": agent_id or agent_type or "main",
            "name": agent_type,
            "zone": zone_for_tool(tool, tinput),
            "tool": tool,
        }

    return None


def post(url: str, event: dict) -> None:
    data = json.dumps(event).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/event", data=data, headers={"Content-Type": "application/json"}
    )
    urllib.request.urlopen(req, timeout=TIMEOUT).read()


def main() -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0  # 페이로드가 깨져도 세션을 막지 않는다

    try:
        event = build_event(payload)
        if event:
            post(DEFAULT_URL, event)
    except (urllib.error.URLError, OSError, TimeoutError):
        pass  # 오피스가 안 떠 있어도 정상 — 조용히 넘어간다
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
