"""settings.json 에 픽셀 오피스 훅을 안전하게 배선 (기존 훅 보존).

사용:
  python pixel_office/scripts/wire_hooks.py --settings .claude/settings.local.json --check
  python pixel_office/scripts/wire_hooks.py --settings .claude/settings.local.json
  python pixel_office/scripts/wire_hooks.py --settings .claude/settings.local.json --remove
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

MARK = "pixel-office"
EVENTS = ("SessionStart", "PreToolUse", "PostToolUse", "PermissionRequest", "SubagentStart", "SubagentStop", "Stop")


def hook_entry(py: str, script: str) -> dict:
    return {
        "matcher": "*",
        "hooks": [{"type": "command", "command": f'"{py}" "{script}"', "_source": MARK}],
    }


def already_wired(entries: list, script: str) -> bool:
    for e in entries or []:
        for h in e.get("hooks", []) or []:
            if h.get("_source") == MARK or script in str(h.get("command", "")):
                return True
    return False


def main() -> int:
    p = argparse.ArgumentParser(description="픽셀 오피스 훅 배선")
    p.add_argument("--settings", default=".claude/settings.local.json")
    p.add_argument("--python", default=sys.executable)
    p.add_argument("--script", default=str(Path(__file__).with_name("hook_push.py")))
    p.add_argument("--check", action="store_true")
    p.add_argument("--remove", action="store_true")
    args = p.parse_args()

    sp = Path(args.settings)
    data = json.loads(sp.read_text(encoding="utf-8")) if sp.is_file() else {}
    hooks = data.setdefault("hooks", {})

    before = {k: len(v or []) for k, v in hooks.items()}

    if args.remove:
        for ev in list(hooks.keys()):
            kept = []
            for e in hooks[ev] or []:
                inner = [h for h in e.get("hooks", []) if h.get("_source") != MARK]
                if inner:
                    kept.append({**e, "hooks": inner})
            hooks[ev] = kept
        action = "제거"
    else:
        for ev in EVENTS:
            entries = hooks.setdefault(ev, [])
            if already_wired(entries, args.script):
                continue
            entries.append(hook_entry(args.python, args.script))
        action = "배선"

    after = {k: len(v or []) for k, v in hooks.items()}
    print(f"[{action}] 이벤트별 훅 등록 현황:")
    for ev in sorted(set(before) | set(after)):
        b, a = before.get(ev, 0), after.get(ev, 0)
        flag = "  ←" if a != b else ""
        print(f"  {ev:20s} {b} → {a}{flag}")

    if args.check:
        print("\n--check 모드로 파일을 변경하지 않았습니다.")
        return 0

    if sp.is_file():
        bak = sp.with_suffix(sp.suffix + ".bak")
        shutil.copy2(sp, bak)
        print(f"백업 완료: {bak}")
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장 완료: {sp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
