"""AI Company & Claude 훅 이벤트 → 픽셀 오피스 서버 상태 전송.

3중 폴백 신호 수신:
1순위: PreToolUse(tool_name == "Agent"|"Task") 의 tool_input.subagent_type 에서 이름 확보
2순위: SubagentStart / SubagentStop 갱신
3순위: status.json 및 타임아웃 자동 퇴근 처리
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_URL = os.environ.get("PIXEL_OFFICE_URL", "http://127.0.0.1:8791")
TIMEOUT = 1.0

TOOL_ZONE = {
    "Read": "dev",
    "Write": "dev",
    "Edit": "dev",
    "NotebookEdit": "dev",
    "Grep": "research",
    "Glob": "research",
    "WebSearch": "research",
    "WebFetch": "research",
    "Task": "meeting",
    "Agent": "meeting",
    "chatterbox-tts": "media",
    "cosyvoice": "media",
    "seedance": "media",
}


def zone_for_tool(tool_name: str, tool_input: dict) -> str:
    if tool_name == "Bash":
        cmd = str(tool_input.get("command", ""))
        if any(k in cmd for k in ("git push", "git commit", "deploy", "rsync", "scp", "docker")):
            return "server"
        if any(k in cmd for k in ("chatterbox", "cosyvoice", "ffmpeg", "yt-dlp")):
            return "media"
        return "dev"
    return TOOL_ZONE.get(tool_name, "dev")


def build_event(payload: dict) -> dict | None:
    ev = payload.get("hook_event_name", "")
    agent_id = payload.get("agent_id") or ""
    agent_type = payload.get("agent_type") or ""

    if ev == "SessionStart":
        return {"kind": "boss_in", "session": payload.get("session_id", "")}

    if ev == "Stop":
        return {"kind": "boss_idle", "session": payload.get("session_id", "")}

    if ev == "SubagentStart":
        if not agent_type:
            return None
        return {"kind": "hire", "id": agent_id or agent_type, "name": agent_type, "src": "subagent_start"}

    if ev == "SubagentStop":
        if not (agent_id or agent_type):
            return None
        return {"kind": "leave", "id": agent_id or agent_type, "src": "subagent_stop"}

    if ev == "PermissionRequest":
        return {"kind": "state", "id": agent_id or "CEO", "name": agent_type or "CEO", "zone": "waiting"}

    if ev in ("PreToolUse", "PostToolUse"):
        tool = payload.get("tool_name", "")
        tinput = payload.get("tool_input") or {}

        if tool in ("Task", "Agent"):
            sub = tinput.get("subagent_type") or ""
            if not sub:
                return None
            uid = payload.get("tool_use_id") or f"{sub}:{payload.get('session_id','')}"
            if ev == "PreToolUse":
                return {"kind": "hire", "id": uid, "name": sub, "src": "pre_agent", "zone": "meeting"}
            return {"kind": "leave", "id": uid, "src": "post_agent"}

        if ev != "PreToolUse":
            return None
        return {
            "kind": "state",
            "id": agent_id or agent_type or "main",
            "name": agent_type or "main",
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
        return 0

    try:
        event = build_event(payload)
        if event:
            post(DEFAULT_URL, event)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
