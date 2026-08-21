"""AI Company 픽셀 오피스 로컬 서버 — 상태 보관, 양방향 REST API, 실시간 시뮬레이터.

- GET  /             → web/office.html (픽셀 사무실 웹앱)
- GET  /state        → 현재 사무실 상태(JSON, status.json 자동 통합)
- GET  /org          → 16인 조직도 및 부서 메타데이터
- POST /event        → 실시간 훅 및 오케스트레이터 이벤트 수신
- POST /demo         → 특정 에이전트/구역 데모
- POST /simulate     → 16인 가상 기업 전 부서 파이프라인 협업 시뮬레이션
- POST /dispatch     → UI에서 특정 에이전트로 직접 업무 지시
"""

from __future__ import annotations

import argparse
import json
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

IDLE_SEC = 240.0
LOUNGE_SEC = 50.0
MIN_DWELL_SEC = 8.0

ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = ROOT.parent
WEB = ROOT / "web"
STATUS_FILE = PROJECT_ROOT / "ai_company" / "status.json"

_lock = threading.Lock()
_org: dict = {"agents": [], "count": 0, "departments": []}
_workers: dict[str, dict] = {}
_boss = {"active": True, "ts": 0.0}
_log: list[dict] = []
_project_state = {
    "current_project": "AI 비즈니스 OS 및 프로젝트 런칭 파이프라인",
    "progress_percent": 65,
    "active_phase": "Phase 2: Full Automation Execution",
    "active_agent": "CEO"
}
_last_status_mtime = 0.0


def _seat_for(name: str) -> int:
    for a in _org.get("agents", []):
        if a["name"] == name:
            return a.get("seat", 0)
    return abs(hash(name)) % max(1, _org.get("count", 1) or 1)


def _home_zone(name: str) -> str:
    for a in _org.get("agents", []):
        if a["name"] == name:
            return a.get("zone", "desk")
    return "dev"


def _meta_for(name: str) -> dict:
    for a in _org.get("agents", []):
        if a["name"] == name:
            return a
    return {}


def check_status_file():
    """ai_company/status.json 파일의 변경 사항을 감지하여 실시간 동기화"""
    global _last_status_mtime, _project_state
    if not STATUS_FILE.is_file():
        return
    try:
        mtime = STATUS_FILE.stat().st_mtime
        if mtime > _last_status_mtime:
            _last_status_mtime = mtime
            data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
            with _lock:
                _project_state["current_project"] = data.get("current_project", _project_state["current_project"])
                _project_state["progress_percent"] = data.get("progress_percent", _project_state["progress_percent"])
                _project_state["active_phase"] = data.get("active_phase", _project_state["active_phase"])
                _project_state["active_agent"] = data.get("active_agent", _project_state["active_agent"])
                
                # 에이전트별 실시간 상태 반영
                agents_status = data.get("agents_status", {})
                now = time.time()
                for name, info in agents_status.items():
                    st = info.get("status", "대기")
                    task = info.get("last_task", "")
                    if st in ("진행중", "Working", "완료"):
                        meta = _meta_for(name)
                        zone = meta.get("zone", "dev") if st == "진행중" else "lounge"
                        w = _workers.setdefault(name, {})
                        w.update(
                            name=name,
                            seat=_seat_for(name),
                            zone=zone,
                            tool=task[:24] if task else "",
                            status=st,
                            task=task,
                            ts=now
                        )
                        w.setdefault("born", now)
    except Exception:
        pass


def apply_event(ev: dict) -> None:
    now = time.time()
    kind = ev.get("kind")
    with _lock:
        if kind == "boss_in":
            _boss.update(active=True, ts=now)
        elif kind == "boss_idle":
            _boss.update(active=False, ts=now)
        elif kind == "hire":
            wid = str(ev.get("id") or ev.get("name") or "?")
            name = str(ev.get("name") or wid)
            meta = _meta_for(name)
            w = _workers.setdefault(wid, {})
            w.update(
                name=name,
                seat=_seat_for(name),
                zone=ev.get("zone") or w.get("zone") or meta.get("zone") or _home_zone(name),
                tool=ev.get("tool", ""),
                task=ev.get("task", ""),
                department=meta.get("department", "dev"),
                ts=now,
                src=ev.get("src", "")
            )
            w.setdefault("born", now)
            w.pop("leave_at", None)
        elif kind == "leave":
            wid = str(ev.get("id") or "")
            w = _workers.get(wid)
            if w:
                born = w.get("born", now)
                if now - born < MIN_DWELL_SEC:
                    w["leave_at"] = born + MIN_DWELL_SEC
                else:
                    _workers.pop(wid, None)
        elif kind == "state":
            wid = str(ev.get("id") or ev.get("name") or "main")
            name = str(ev.get("name") or wid)
            meta = _meta_for(name)
            w = _workers.setdefault(wid, {})
            w.update(
                name=name,
                seat=w.get("seat", _seat_for(name)),
                zone=str(ev.get("zone") or meta.get("zone") or "dev"),
                tool=ev.get("tool", ""),
                task=ev.get("task", ""),
                department=meta.get("department", "dev"),
                ts=now
            )
        elif kind == "project_update":
            if "current_project" in ev:
                _project_state["current_project"] = ev["current_project"]
            if "progress_percent" in ev:
                _project_state["progress_percent"] = ev["progress_percent"]
            if "active_phase" in ev:
                _project_state["active_phase"] = ev["active_phase"]

        _log.append({"t": now, **{k: v for k, v in ev.items() if k != "kind"}, "kind": kind})
        del _log[:-50]


def snapshot() -> dict:
    check_status_file()
    now = time.time()
    permanent_names = {a["name"] for a in _org.get("agents", [])}

    with _lock:
        # 예약 퇴장
        for wid in [k for k, w in _workers.items() if w.get("leave_at") and now >= w["leave_at"]]:
            _workers.pop(wid, None)
        
        # 자동 퇴근 — 임시 서브에이전트만 퇴근시키고 기본 직원은 책상에 상주
        for wid in list(_workers.keys()):
            w = _workers[wid]
            quiet = now - w.get("ts", now)
            if wid not in permanent_names and quiet > IDLE_SEC:
                _workers.pop(wid, None)

        # 기본 직원이 빠져있으면 복구
        for a in _org.get("agents", []):
            name = a["name"]
            if name not in _workers:
                _workers[name] = {
                    "name": name,
                    "seat": a.get("seat", 0),
                    "zone": a.get("zone", "dev"),
                    "tool": "대기",
                    "task": a.get("description", ""),
                    "department": a.get("department", "dev"),
                    "ts": now,
                    "born": now
                }

        out = []
        for wid, w in _workers.items():
            quiet = now - w.get("ts", now)
            zone = w.get("zone", "dev")
            idle = quiet > LOUNGE_SEC and zone not in ("waiting", "error")
            meta = _meta_for(w.get("name", wid))
            out.append({
                "id": wid,
                "name": w.get("name", wid),
                "role": meta.get("role", ""),
                "department": meta.get("department", "dev"),
                "tunic": meta.get("tunic", "#1b7a82"),
                "zone": zone,
                "seat": w.get("seat", 0),
                "tool": w.get("tool", ""),
                "task": w.get("task", ""),
                "idle": idle,
                "quiet": round(quiet, 1)
            })

        return {
            "workers": sorted(out, key=lambda x: x["seat"]),
            "boss": dict(_boss),
            "project": dict(_project_state),
            "org_count": _org.get("count", len(_org.get("agents", []))),
            "log": _log[-10:],
            "now": now
        }


def run_pipeline_simulation():
    """16인 가상 기업 전 부서 풀사이클 시뮬레이션 백그라운드 스레드"""
    steps = [
        ("CEO", "ceo", "최고경영자", "신규 마이크로 SaaS 프로젝트 비전 선포 및 지시", 10),
        ("개발팀장", "dev", "PRD 기획", "6블록 PRD 작성 및 WBS 작업 분할", 20),
        ("개발_사원A", "dev", "아키텍처", "시스템 구조 설계 & Supabase 스키마 정의", 30),
        ("개발_사원B", "dev", "TDD 코딩", "백엔드 핵심 결제 및 인증 로직 구현", 45),
        ("개발_사원C", "dev", "UI/UX", "Emil 마이크로 인터랙션 & 디자인 시스템 적용", 55),
        ("개발_사원D", "meeting", "QA/보안", "5개 축 무결점 코드 리뷰 및 모의 침투", 65),
        ("개발_사원E", "server", "배포", "CI/CD 자동 빌드 및 저사양 최적화", 70),
        ("마케팅팀장", "marketing", "전략", "3막 8장 전환 퍼널 및 카피라이팅 기획", 75),
        ("마케팅_사원A", "research", "트렌드", "유튜브 이상치 데이터 및 키워드 발굴", 80),
        ("마케팅_사원C", "marketing", "카피라이팅", "고유 말투 반영 스레드 & 릴스 대본 작성", 85),
        ("마케팅_사원D", "marketing", "비주얼", "Banana Pro 6패널 카드뉴스 프롬프트 생성", 90),
        ("미디어팀장", "media", "영상기획", "Cinema Worldbuilder 2.0 시네마틱 모션 설계", 92),
        ("미디어_사원A", "media", "오디오TTS", "Chatterbox-TTS 듀얼 보이스 음성 합성", 94),
        ("미디어_사원C", "media", "영상편집", "자막 싱크 및 숏폼 영상 최종 마스터링", 96),
        ("미디어_사원D", "server", "발행준비", "플랫폼 스테이징 및 슬랙 보고 채널 연동", 98),
        ("CEO", "waiting", "최종결재", "@User 최종 승인 요청 및 릴리스 승인", 100),
    ]

    apply_event({
        "kind": "project_update",
        "current_project": "🚀 마이크로 SaaS 1인 런칭 파이프라인 (Live)",
        "progress_percent": 5,
        "active_phase": "Phase: Real-time Multi-Agent Collaboration"
    })

    for name, zone, tool, task, prog in steps:
        apply_event({
            "kind": "hire",
            "id": name,
            "name": name,
            "zone": zone,
            "tool": tool,
            "task": task,
            "src": "simulation"
        })
        apply_event({
            "kind": "project_update",
            "progress_percent": prog,
            "active_phase": f"Active: {name} ({tool})"
        })
        time.sleep(2.5)

    time.sleep(3.0)
    apply_event({
        "kind": "project_update",
        "current_project": "✅ 마이크로 SaaS 프로젝트 릴리스 완료",
        "progress_percent": 100,
        "active_phase": "All Tasks Completed Successfully"
    })


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj) -> None:
        self._send(200, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/state"):
            return self._json(snapshot())
        if self.path.startswith("/org"):
            return self._json(_org)
        
        name = "office.html" if self.path in ("/", "") else self.path.lstrip("/").split("?")[0]
        f = WEB / name
        if not f.is_file() or WEB not in f.resolve().parents:
            return self._send(404, b"not found", "text/plain")
        ctype = "text/html; charset=utf-8" if f.suffix == ".html" else "application/octet-stream"
        return self._send(200, f.read_bytes(), ctype)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            payload = {}

        if self.path.startswith("/simulate"):
            t = threading.Thread(target=run_pipeline_simulation, daemon=True)
            t.start()
            return self._json({"ok": True, "message": "Simulation started"})

        if self.path.startswith("/demo"):
            agents = _org.get("agents", [])
            name = payload.get("name") or (agents[0]["name"] if agents else "CEO")
            zone = payload.get("zone", "dev")
            tool = payload.get("tool", "Task")
            task = payload.get("task", "실시간 작업 수행 중")
            apply_event({"kind": "hire", "id": name, "name": name, "src": "demo"})
            apply_event({"kind": "state", "id": name, "name": name, "zone": zone, "tool": tool, "task": task})
            return self._json({"ok": True, "name": name, "zone": zone})

        if self.path.startswith("/dispatch"):
            name = payload.get("name", "CEO")
            task = payload.get("task", "지시된 신규 업무")
            meta = _meta_for(name)
            zone = payload.get("zone") or meta.get("zone", "dev")
            apply_event({
                "kind": "hire",
                "id": name,
                "name": name,
                "zone": zone,
                "tool": "DirectDispatch",
                "task": task,
                "src": "dispatch"
            })
            return self._json({"ok": True, "name": name, "task": task})

        apply_event(payload)
        return self._json({"ok": True})


def init_default_staff():
    """서버 시작 시 기본 16인 전원 사무실에 활성화 배치"""
    now = time.time()
    for a in _org.get("agents", []):
        name = a["name"]
        _workers[name] = {
            "name": name,
            "seat": a.get("seat", 0),
            "zone": a.get("zone", "dev"),
            "tool": "대기",
            "task": a.get("description", ""),
            "department": a.get("department", "dev"),
            "ts": now,
            "born": now
        }


def main() -> int:
    p = argparse.ArgumentParser(description="AI Company 픽셀 오피스 서버")
    p.add_argument("--org", default=".pixel-office/org.json", help="조직도 JSON 경로")
    p.add_argument("--port", type=int, default=8791)
    p.add_argument("--open", action="store_true", help="브라우저 자동 열기")
    args = p.parse_args()

    global _org
    org_path = Path(args.org)
    if not org_path.is_absolute():
        org_path = PROJECT_ROOT / org_path

    if org_path.is_file():
        _org = json.loads(org_path.read_text(encoding="utf-8"))
    
    print(f"👥 가상 기업 조직도 {_org.get('count', 0)}명 로드 완료")
    init_default_staff()

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"🏢 AI Company 픽셀 오피스 가동 중 → {url}")
    print("   [단축키] c : CCTV 레트로 CRT 필터 전환 | 클릭 : 직원 정보 카드")
    if args.open:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n사무실 종료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
