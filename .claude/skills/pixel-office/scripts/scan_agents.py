"""agents 폴더 스캔 → 조직도(JSON).

프로젝트 `.claude/agents/*.md` + 유저 전역 `~/.claude/agents/*.md` 를 읽어
{name, description, source, zone, sprite} 목록을 만든다.

★관대한 파서가 요구사항이다 (설계 SoT §4.6):
공식 스펙상 필수 프론트매터는 `name`·`description` 둘뿐이고 `tools` 는 생략 가능하며
인라인 콤마와 YAML 리스트가 모두 유효하다. 실제로 같은 레포 안에서도 형식이 갈린다.
따라서 YAML 파싱에 실패해도, description 이 없어도 죽지 않고 폴백한다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# 역할 키워드 → 구역. 위에서부터 먼저 맞는 것을 쓴다(순서가 우선순위).
ZONE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("research", ("research", "scout", "search", "analy", "explor", "리서치", "조사", "분석")),
    ("server", ("deploy", "publish", "ops", "operator", "upload", "release", "배포", "발행", "운영")),
    ("meeting", ("review", "critic", "judge", "qa", "audit", "검수", "리뷰", "심사")),
    ("desk", ()),  # 기본값
]

SPRITES = ("cat_orange", "cat_grey", "cat_black", "cat_white", "cat_calico", "cat_tabby")

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
# YAML 파싱 실패 시 폴백용 — 값에 콜론이 들어가도 첫 콜론에서만 자른다
_KV_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$")
_H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)


def parse_frontmatter(text: str) -> dict[str, str]:
    """프론트매터에서 스칼라 키만 뽑는다. 리스트/블록 값은 무시한다.

    PyYAML 을 쓰지 않는다 — 표준 라이브러리만으로 돌게 해서 시청자 환경 의존을 없앤다.
    """
    m = _FM_RE.match(text)
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith((" ", "\t", "-")):
            continue  # 리스트 항목/중첩 값 — 스칼라가 아니므로 건너뛴다
        kv = _KV_RE.match(line)
        if not kv:
            continue
        key, val = kv.group(1).lower(), kv.group(2).strip()
        if val.startswith(("|", ">")):
            continue  # 블록 스칼라는 다루지 않는다
        out[key] = val.strip("'\"")
    return out


def pick_zone(name: str, description: str) -> str:
    blob = f"{name} {description}".lower()
    for zone, keys in ZONE_RULES:
        if not keys:
            return zone
        if any(k in blob for k in keys):
            return zone
    return "desk"


def scan_dir(d: Path, source: str) -> list[dict]:
    if not d.is_dir():
        return []
    found = []
    for f in sorted(d.glob("*.md")):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm = parse_frontmatter(text)
        name = fm.get("name") or f.stem
        desc = fm.get("description", "")
        if not desc:
            # 폴백 1: 본문 첫 h1 → 폴백 2: 파일명
            h1 = _H1_RE.search(text)
            desc = h1.group(1).strip() if h1 else f.stem
        found.append(
            {
                "name": name,
                "description": desc,
                "source": source,
                "file": str(f),
                "zone": pick_zone(name, desc),
            }
        )
    return found


def scan(project_root: Path, include_global: bool) -> list[dict]:
    agents = scan_dir(project_root / ".claude" / "agents", "project")
    if include_global:
        agents += scan_dir(Path.home() / ".claude" / "agents", "global")
    # 같은 이름이면 프로젝트 정의가 이긴다(Claude Code 의 해석 순서와 같게)
    seen: dict[str, dict] = {}
    for a in agents:
        if a["name"] not in seen or a["source"] == "project":
            seen[a["name"]] = a
    out = list(seen.values())
    for i, a in enumerate(out):
        a["sprite"] = SPRITES[i % len(SPRITES)]
        a["seat"] = i
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="agents 폴더를 스캔해 조직도를 만든다")
    p.add_argument("--root", default=".", help="프로젝트 루트 (기본: 현재 폴더)")
    p.add_argument("--global", dest="use_global", action="store_true", help="~/.claude/agents 도 포함")
    p.add_argument("--out", help="JSON 저장 경로 (없으면 표준출력)")
    p.add_argument("--preset", help="에이전트가 하나도 없을 때 쓸 프리셋 JSON")
    args = p.parse_args()

    agents = scan(Path(args.root).resolve(), args.use_global)

    if not agents and args.preset:
        preset = Path(args.preset)
        if preset.is_file():
            agents = json.loads(preset.read_text(encoding="utf-8"))
            print(f"에이전트를 못 찾아 프리셋을 씁니다: {preset}", file=sys.stderr)

    # ★손으로 고친 zone 을 보존한다.
    #   README·SKILL 은 "org.json 의 zone 을 직접 바꾸라"고 안내하는데, start.py 는 실행할 때마다
    #   스캔을 다시 돌린다. 덮어쓰면 사용자가 고친 자리가 매번 날아간다(2026-08-01 검수에서 발견).
    if args.out:
        prev_path = Path(args.out)
        if prev_path.is_file():
            try:
                prev = json.loads(prev_path.read_text(encoding="utf-8"))
                kept = {a["name"]: a.get("zone") for a in prev.get("agents", []) if a.get("zone")}
                auto = {a["name"]: pick_zone(a["name"], a["description"]) for a in agents}
                for a in agents:
                    # 사용자가 바꾼 값(= 자동 배정과 다른 값)만 되살린다
                    if a["name"] in kept and kept[a["name"]] != auto.get(a["name"]):
                        a["zone"] = kept[a["name"]]
                        a["zone_manual"] = True
            except (OSError, ValueError, KeyError):
                pass  # 이전 파일이 깨져 있으면 그냥 새로 쓴다

    payload = {"agents": agents, "count": len(agents)}
    text = json.dumps(payload, ensure_ascii=False, indent=2)

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")

    by_zone: dict[str, int] = {}
    for a in agents:
        by_zone[a["zone"]] = by_zone.get(a["zone"], 0) + 1
    print(f"직원 {len(agents)}명")
    for z, n in sorted(by_zone.items(), key=lambda kv: -kv[1]):
        print(f"  {z:9s} {n}명")
    if not args.out:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
