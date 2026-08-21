"""settings.json 에 픽셀 오피스 훅을 배선한다 — 기존 훅을 보존하는 머지.

★이 파일의 존재 이유: 남의 설정을 덮어쓰지 않는 것.
따라하기 튜토리얼에서 사용자의 기존 훅을 날리면 그 순간 신뢰를 잃는다.
그래서 ①먼저 백업하고 ②같은 이벤트의 기존 항목 옆에 붙이고 ③중복이면 건너뛴다.

사용:
  python wire_hooks.py --settings .claude/settings.local.json --check   # 미리보기만
  python wire_hooks.py --settings .claude/settings.local.json           # 실제 배선
  python wire_hooks.py --settings .claude/settings.local.json --remove  # 되돌리기
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

MARK = "pixel-office"  # 우리 항목을 식별하는 표식 — 되돌릴 때 이걸로 찾는다

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
    p = argparse.ArgumentParser(description="픽셀 오피스 훅 배선 (기존 훅 보존)")
    p.add_argument("--settings", required=True)
    p.add_argument("--python", default=sys.executable)
    p.add_argument("--script", default=str(Path(__file__).with_name("hook_push.py")))
    p.add_argument("--check", action="store_true", help="바꾸지 않고 결과만 보여준다")
    p.add_argument("--remove", action="store_true", help="우리 훅만 걷어낸다")
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
    print(f"[{action}] 이벤트별 항목 수 (기존 → 이후)")
    for ev in sorted(set(before) | set(after)):
        b, a = before.get(ev, 0), after.get(ev, 0)
        flag = "  ←" if a != b else ""
        print(f"  {ev:20s} {b} → {a}{flag}")

    kept_others = sum(
        1
        for ev in hooks
        for e in hooks[ev] or []
        for h in e.get("hooks", []) or []
        if h.get("_source") != MARK
    )
    print(f"보존된 기존 훅: {kept_others}개")

    if args.check:
        print("\n--check 이므로 파일을 바꾸지 않았습니다.")
        return 0

    if sp.is_file():
        bak = sp.with_suffix(sp.suffix + ".bak")
        shutil.copy2(sp, bak)
        print(f"백업: {bak}")
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장: {sp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
