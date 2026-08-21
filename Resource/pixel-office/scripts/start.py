"""픽셀 오피스 한 방에 켜기 — 스캔 → 사무실 열기.

처음 쓰는 사람이 명령어 다섯 개를 순서대로 치게 하면 안 된다. 이 파일 하나로 끝난다.

    python .claude/skills/pixel-office/scripts/start.py

옵션:
    --wire      신호 연결(훅 배선)까지 같이 한다. 기본은 안 한다(남의 설정을 함부로 안 건드림)
    --global    ~/.claude/agents 의 에이전트도 같이 읽는다
    --port      포트 지정 (기본 8791, 이미 쓰는 중이면 자동으로 다음 번호를 찾는다)
"""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
from pathlib import Path

SK = Path(__file__).resolve().parent          # scripts/
ROOT = SK.parent                              # 스킬 폴더


def free_port(start: int) -> int:
    """이미 쓰는 포트면 다음 번호를 찾는다.

    이게 없으면 남이 쓰는 포트에 붙어 엉뚱한 화면이 뜬다(실제로 겪음).
    """
    for p in range(start, start + 40):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return start


def main() -> int:
    ap = argparse.ArgumentParser(description="픽셀 오피스 켜기")
    ap.add_argument("--root", default=".", help="프로젝트 루트 (기본: 현재 폴더)")
    ap.add_argument("--port", type=int, default=8791)
    ap.add_argument("--wire", action="store_true", help="신호 연결(훅 배선)까지 수행")
    ap.add_argument("--global", dest="use_global", action="store_true")
    ap.add_argument("--settings", default=".claude/settings.local.json")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    out = root / ".pixel-office" / "org.json"
    py = sys.executable

    print("=" * 52)
    print(" 픽셀 오피스")
    print("=" * 52)

    # 1) 조직도 읽기
    print("\n[1/3] 에이전트 폴더를 읽습니다…")
    cmd = [py, str(SK / "scan_agents.py"), "--root", str(root),
           "--out", str(out), "--preset", str(ROOT / "presets" / "default-5.json")]
    if args.use_global:
        cmd.append("--global")
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print("  스캔에 실패했습니다. --root 경로를 확인하세요.")
        return 1

    # 2) 신호 연결 (선택)
    if args.wire:
        print("\n[2/3] 신호를 연결합니다 (기존 설정은 보존)…")
        subprocess.run([py, str(SK / "wire_hooks.py"), "--settings", str(root / args.settings)])
    else:
        print("\n[2/3] 신호 연결은 건너뜁니다.")
        print("      실제 작업이 화면에 뜨게 하려면 --wire 를 붙여 다시 실행하세요.")
        print("      (기존 설정은 덮어쓰지 않고, 바꾸기 전에 백업을 뜹니다)")

    # 3) 사무실 열기
    port = free_port(args.port)
    if port != args.port:
        print(f"\n  ⚠️ {args.port} 번은 다른 프로그램이 쓰고 있어 {port} 번으로 엽니다.")
    print(f"\n[3/3] 사무실을 엽니다 → http://127.0.0.1:{port}/")
    print("      (끄려면 이 창에서 Ctrl+C)\n")
    return subprocess.run(
        [py, str(SK / "serve.py"), "--org", str(out), "--port", str(port), "--open"]
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
