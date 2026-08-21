"""AI Company 픽셀 오피스 원클릭 실행 스크립트.

실행:
    python pixel_office/scripts/start.py
    python start_office.py

옵션:
    --port      포트 지정 (기본 8791, 사용 중이면 다음 사용 가능한 포트 자동 검색)
    --wire      Claude Code / Antigravity 훅 자동 배선
    --no-open   브라우저 자동 열기 비활성화
"""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
PIXEL_OFFICE_DIR = SCRIPTS_DIR.parent
PROJECT_ROOT = PIXEL_OFFICE_DIR.parent


def find_free_port(start_port: int = 8791) -> int:
    for p in range(start_port, start_port + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return start_port


def main() -> int:
    ap = argparse.ArgumentParser(description="AI Company 픽셀 오피스 가동")
    ap.add_argument("--port", type=int, default=8791, help="시작 포트 번호 (기본: 8791)")
    ap.add_argument("--wire", action="store_true", help="Claude Code 훅 배선 연동")
    ap.add_argument("--no-open", action="store_true", help="브라우저 자동 실행 끄기")
    ap.add_argument("--global", dest="use_global", action="store_true", help="전역 에이전트 포함")
    args = ap.parse_args()

    py = sys.executable
    org_out = PROJECT_ROOT / ".pixel-office" / "org.json"

    print("=" * 60)
    print(" 🏢 AI Company 픽셀 오피스 (Pixel Office)")
    print("=" * 60)

    # 1. 조직도 스캔
    print("\n[1/3] 👥 16인 가상 기업 및 에이전트 조직도를 스캔합니다...")
    scan_cmd = [py, str(SCRIPTS_DIR / "scan_agents.py"), "--root", str(PROJECT_ROOT), "--out", str(org_out)]
    if args.use_global:
        scan_cmd.append("--global")
    
    r = subprocess.run(scan_cmd)
    if r.returncode != 0:
        print("❌ 스캔 중 오류가 발생했습니다.")
        return 1

    # 2. 훅 배선 (선택)
    if args.wire:
        print("\n[2/3] 🔌 훅 신호를 안전하게 배선합니다...")
        subprocess.run([py, str(SCRIPTS_DIR / "wire_hooks.py")])
    else:
        print("\n[2/3] ℹ️ 훅 배선은 건너뜁니다 (CLI 훅 연동 시 --wire 옵션 사용).")

    # 3. 포트 확인 및 서버 가동
    port = find_free_port(args.port)
    if port != args.port:
        print(f"\n⚠️ {args.port} 포트가 이미 사용 중이므로 {port} 포트로 자동 전환합니다.")

    print(f"\n[3/3] 🚀 픽셀 오피스 서버를 구동합니다!")
    print(f"👉 브라우저 주소: http://127.0.0.1:{port}/")
    print("👉 종료하려면 터미널에서 Ctrl+C를 누르세요.\n")

    serve_cmd = [py, str(SCRIPTS_DIR / "serve.py"), "--org", str(org_out), "--port", str(port)]
    if not args.no_open:
        serve_cmd.append("--open")

    return subprocess.run(serve_cmd).returncode


if __name__ == "__main__":
    raise SystemExit(main())
