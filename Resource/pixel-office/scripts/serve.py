"""픽셀 오피스 로컬 서버 — 상태 보관 + 화면 서빙.

표준 라이브러리만 쓴다(시청자 환경 의존 0). 외부 패키지 설치 없음.

- GET  /            → web/office.html
- GET  /state       → 현재 사무실 상태(JSON). 화면이 주기적으로 폴링한다.
- GET  /org         → 조직도(스캔 결과)
- POST /event       → 훅이 보내는 이벤트 수신
- POST /demo        → 스모크 테스트용 가짜 이벤트 1발

★자동 퇴근: 종료 신호를 못 받은 직원은 IDLE_SEC 뒤 자리에서 사라진다.
  (설계 SoT §4.4-b — Stop 이벤트가 안 오는 사례가 보고돼 있어서, 이게 없으면
   유령 직원이 책상에 영원히 앉아 있다.)
"""

from __future__ import annotations

import argparse
import json
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

IDLE_SEC = 180.0  # 이 시간 동안 아무 이벤트 없으면 자동 퇴근
# ⚠️ 라운지 판정을 짧게 잡으면 안 된다. 오래 걸리는 툴(웹 검색·긴 빌드) 하나만 써도
#    이벤트가 그동안 안 오는데, 그걸 "논다"로 그리면 화면이 거짓말을 한다.
LOUNGE_SEC = 45.0
# ★최소 체류 시간. 몇 초 만에 끝나는 서브에이전트는 입장하자마자 퇴장해서
#   사람 눈에 안 보인다(실측: Explore 에이전트가 화면에 스쳐 지나감).
#   퇴장 신호가 와도 이 시간까지는 자리를 지키게 해서 "봤다"가 되게 한다.
MIN_DWELL_SEC = 8.0

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

_lock = threading.Lock()
_org: dict = {"agents": [], "count": 0}
_workers: dict[str, dict] = {}  # id -> {name, zone, tool, seat, ts}
_boss = {"active": False, "ts": 0.0}
_log: list[dict] = []  # 최근 이벤트 (화면 하단 티커용)


def _seat_for(name: str) -> int:
    for a in _org.get("agents", []):
        if a["name"] == name:
            return a.get("seat", 0)
    return abs(hash(name)) % max(1, _org.get("count", 1) or 1)


def _home_zone(name: str) -> str:
    for a in _org.get("agents", []):
        if a["name"] == name:
            return a.get("zone", "desk")
    return "desk"


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
            src = ev.get("src", "")
            # ★화해: 1순위(pre_agent)로 이미 들어온 같은 이름의 미결합 직원이 있으면
            #   2순위(subagent_start)가 새 사람을 만들지 않고 그 직원에 id 를 묶는다.
            #   안 하면 에이전트 하나가 화면에 둘로 보인다.
            if src == "subagent_start" and wid not in _workers:
                cand = [
                    k for k, w0 in _workers.items()
                    if w0.get("name") == name and w0.get("src") == "pre_agent" and not w0.get("bound")
                ]
                if cand:
                    old = cand[0]
                    w0 = _workers.pop(old)
                    w0["bound"] = True
                    _workers[wid] = w0
            w = _workers.setdefault(wid, {})
            w.update(
                name=name,
                seat=_seat_for(name),
                zone=w.get("zone") or _home_zone(name),
                ts=now,
                src=ev.get("src", ""),
            )
            w.setdefault("born", now)
            w.pop("leave_at", None)  # 다시 들어왔으면 예약 퇴장 취소
        elif kind == "leave":
            wid = str(ev.get("id") or "")
            w = _workers.get(wid)
            if w:
                # 최소 체류 시간을 못 채웠으면 바로 지우지 않고 예약 퇴장으로 돌린다
                born = w.get("born", now)
                if now - born < MIN_DWELL_SEC:
                    w["leave_at"] = born + MIN_DWELL_SEC
                else:
                    _workers.pop(wid, None)
        elif kind == "state":
            wid = str(ev.get("id") or "main")
            name = str(ev.get("name") or wid)
            w = _workers.setdefault(wid, {})
            w.update(
                name=name,
                seat=w.get("seat", _seat_for(name)),
                zone=str(ev.get("zone") or "desk"),
                tool=ev.get("tool", ""),
                ts=now,
            )
        _log.append({"t": now, **{k: v for k, v in ev.items() if k != "kind"}, "kind": kind})
        del _log[:-40]


def snapshot() -> dict:
    now = time.time()
    with _lock:
        # 예약 퇴장 — 최소 체류 시간을 채웠으면 이제 내보낸다
        for wid in [k for k, w in _workers.items()
                    if w.get("leave_at") and now >= w["leave_at"]]:
            _workers.pop(wid, None)
        # 자동 퇴근 — Stop 을 못 받은 직원 정리
        for wid in [k for k, w in _workers.items() if now - w.get("ts", now) > IDLE_SEC]:
            _workers.pop(wid, None)
        out = []
        for wid, w in _workers.items():
            quiet = now - w.get("ts", now)
            zone = w.get("zone", "desk")
            # ⚠️ 유휴라고 라운지로 '옮기지' 않는다. 27명이 좁은 라운지에 겹쳐 서는
            #    그림이 되고, 의미상으로도 그 직원은 자기 일을 하다 멈춘 것이지
            #    쉬러 간 게 아니다. 자리는 그대로 두고 idle 플래그만 준다.
            idle = quiet > LOUNGE_SEC and zone not in ("waiting", "error")
            out.append(
                {
                    "id": wid,
                    "name": w.get("name", wid),
                    "zone": zone,
                    "seat": w.get("seat", 0),
                    "tool": w.get("tool", ""),
                    "idle": idle,
                    "quiet": round(quiet, 1),
                }
            )
        return {
            "workers": sorted(out, key=lambda x: x["seat"]),
            "boss": dict(_boss),
            "org_count": _org.get("count", 0),
            "log": _log[-8:],
            "now": now,
        }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 콘솔을 조용히 (촬영 화면 보호)
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj) -> None:
        self._send(200, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):  # noqa: N802
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

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            payload = {}
        if self.path.startswith("/demo"):
            agents = _org.get("agents", [])
            name = payload.get("name") or (agents[0]["name"] if agents else "researcher")
            apply_event({"kind": "hire", "id": name, "name": name, "src": "demo"})
            apply_event({"kind": "state", "id": name, "name": name, "zone": payload.get("zone", "research"), "tool": "Grep"})
            return self._json({"ok": True, "name": name})
        apply_event(payload)
        return self._json({"ok": True})


def main() -> int:
    p = argparse.ArgumentParser(description="픽셀 오피스 서버")
    p.add_argument("--org", default=".pixel-office/org.json", help="조직도 JSON 경로")
    p.add_argument("--port", type=int, default=8791)
    p.add_argument("--open", action="store_true", help="브라우저 자동 열기")
    args = p.parse_args()

    global _org
    org_path = Path(args.org)
    if org_path.is_file():
        _org = json.loads(org_path.read_text(encoding="utf-8"))
    print(f"조직도 {_org.get('count', 0)}명 로드")

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"사무실 열림 → {url}")
    if args.open:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n사무실 닫음")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
