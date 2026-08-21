"""조직도 스캔 스크립트 — AI Company 16인 에이전트 & Claude Agents 통합 스캔.

1. ai_company/agents/orchestrator.py 의 AGENTS 설정 스캔
2. 프로젝트 .claude/agents/*.md 및 ~/.claude/agents/*.md 스캔
3. AGENTS.md 및 preset 폴백 지원
4. 사용자가 손으로 수정한 zone(자리) 값 자동 영구 보존
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# 부서/역할별 기본 구역 매핑 규칙 (우선순위 순)
ZONE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("ceo", ("ceo", "최고경영자", "executive")),
    ("server", ("deploy", "publish", "ops", "operator", "infra", "upload", "release", "배포", "발행", "운영", "인프라", "사원e", "사원d")),
    ("research", ("research", "scout", "search", "trend", "analy", "explor", "리서치", "조사", "분석", "트렌드")),
    ("meeting", ("review", "critic", "judge", "qa", "audit", "검수", "리뷰", "심사", "회의")),
    ("dev", ("dev", "architect", "backend", "frontend", "engineer", "개발", "아키텍트", "백엔드", "프론트")),
    ("marketing", ("market", "copy", "content", "story", "prompt", "마케팅", "카피", "콘텐츠", "스토리")),
    ("media", ("media", "audio", "video", "tts", "visual", "editor", "미디어", "오디오", "비디오", "영상", "편집")),
    ("desk", ()),
]

SPRITES = ("cat_orange", "cat_grey", "cat_black", "cat_white", "cat_calico", "cat_tabby")

AGENT_CUSTOM_META = {
    "CEO": {"tunic": "#1d2d44", "zone": "ceo", "dept_name": "경영진", "desc": "사업 총괄 의사결정, 비즈니스 전략 수립, 팀장단 지휘 및 최종 승인"},
    "개발팀장": {"tunic": "#0d5c75", "zone": "dev", "dept_name": "개발본부", "desc": "6블록 PRD 스펙 수립, WBS 수직 슬라이싱, DoD 검증 및 기술 총괄"},
    "개발_사원A": {"tunic": "#1b7a82", "zone": "dev", "dept_name": "개발본부", "desc": "시스템 아키텍처 & DB 설계, 계약 우선 API 명세, 기술 결정 문서(ADR) 작성"},
    "개발_사원B": {"tunic": "#1e6f5c", "zone": "dev", "dept_name": "개발본부", "desc": "파이썬 비즈니스 로직 & 백엔드 보안, TDD Red-Green-Refactor, API 및 DB"},
    "개발_사원C": {"tunic": "#289672", "zone": "dev", "dept_name": "개발본부", "desc": "탈-AI 티 UI/UX, DESIGN.md 원칙 준수, Emil Kowalski 마이크로 인터랙션 구현"},
    "개발_사원D": {"tunic": "#e07a5f", "zone": "meeting", "dept_name": "개발본부", "desc": "5개 축 코드 품질 리뷰(정확/가독/구조/보안/성능), 4대 모의 침투 및 테스트 검증"},
    "개발_사원E": {"tunic": "#3d5a80", "zone": "server", "dept_name": "개발본부", "desc": "CI/CD 자동화, 구조화 로깅 및 관측 가능성, GCP 1GB 저사양 최적화"},
    "마케팅팀장": {"tunic": "#c35a38", "zone": "marketing", "dept_name": "마케팅본부", "desc": "마이크로 SaaS 트래픽 전환 퍼널, 3막 8장 스토리텔링 기획 및 마케팅 총괄"},
    "마케팅_사원A": {"tunic": "#d97736", "zone": "research", "dept_name": "마케팅본부", "desc": "유튜브 이상치(Outlier) 주제 발굴, VPH 비율 분석 및 시장 트렌드 조사"},
    "마케팅_사원B": {"tunic": "#e28743", "zone": "marketing", "dept_name": "마케팅본부", "desc": "3막 8장 내러티브 설계, 숏폼/롱폼 스토리 아크 및 전환 트리거 구조화"},
    "마케팅_사원C": {"tunic": "#ba5a31", "zone": "marketing", "dept_name": "마케팅본부", "desc": "about-me.md / voice.md 기반 고유 보이스 카피라이팅 및 CTA 작성"},
    "마케팅_사원D": {"tunic": "#9a4a28", "zone": "marketing", "dept_name": "마케팅본부", "desc": "Banana Pro Director 2.0 및 6패널 캐릭터 시트 / 탈-AI 비주얼 기획"},
    "미디어팀장": {"tunic": "#5e3c88", "zone": "media", "dept_name": "미디어본부", "desc": "미디어 파이프라인 총괄, Cinema Worldbuilder Pro 2.0 영상 모션 및 품질 검수"},
    "미디어_사원A": {"tunic": "#754f9e", "zone": "media", "dept_name": "미디어본부", "desc": "Chatterbox-TTS 및 CosyVoice 기반 듀얼 엔진 고음질 음성 합성 및 오디오 싱크"},
    "미디어_사원B": {"tunic": "#885fa8", "zone": "media", "dept_name": "미디어본부", "desc": "헤드리스 브라우저 캡처, Seedance 2.0 시네마틱 비디오 생성 및 에셋 추출"},
    "미디어_사원C": {"tunic": "#6a4591", "zone": "media", "dept_name": "미디어본부", "desc": "영상 컷편집, 자막 싱크, BGM/SFX 믹싱 및 최종 숏폼/롱폼 인코딩"},
    "미디어_사원D": {"tunic": "#4d326f", "zone": "server", "dept_name": "미디어본부", "desc": "유튜브, 인스타그램, 틱톡 포맷 패키징 및 슬랙 알림 스테이징"}
}

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_KV_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$")
_H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)


def parse_frontmatter(text: str) -> dict[str, str]:
    m = _FM_RE.match(text)
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith((" ", "\t", "-")):
            continue
        kv = _KV_RE.match(line)
        if not kv:
            continue
        key, val = kv.group(1).lower(), kv.group(2).strip()
        if val.startswith(("|", ">")):
            continue
        out[key] = val.strip("'\"")
    return out


def pick_zone(name: str, description: str, department: str = "") -> str:
    if name.upper() == "CEO" or department == "executive":
        return "ceo"
    if name in AGENT_CUSTOM_META:
        return AGENT_CUSTOM_META[name]["zone"]
    blob = f"{name} {description} {department}".lower()
    for zone, keys in ZONE_RULES:
        if not keys:
            return zone
        if any(k in blob for k in keys):
            return zone
    return "dev" if department == "dev" else "desk"


def scan_orchestrator(root: Path) -> list[dict]:
    """ai_company/agents/orchestrator.py 또는 preset 에서 16인 에이전트 정보 추출"""
    orch_file = root / "ai_company" / "agents" / "orchestrator.py"
    if not orch_file.is_file():
        return []
    
    agents = []
    text = orch_file.read_text(encoding="utf-8", errors="replace")
    
    pattern = re.compile(
        r'["\'](?P<name>[^"\']+)["\']\s*:\s*AgentConfig\s*\(\s*'
        r'["\'](?P<cname>[^"\']+)["\']\s*,\s*'
        r'["\'](?P<role>[^"\']+)["\']\s*,\s*'
        r'["\'](?P<dept>[^"\']+)["\']\s*,\s*'
        r'["\'](?P<instruction>[^"\']+)["\']\s*,\s*'
        r'["\'](?P<key>[^"\']+)["\']\s*,\s*'
        r'["\'](?P<model_env>[^"\']+)["\']\s*,\s*'
        r'["\'](?P<default_model>[^"\']+)["\']\s*,\s*'
        r'["\'](?P<avatar>[^"\']+)["\']'
    )

    seat_idx = 0
    for match in pattern.finditer(text):
        m = match.groupdict()
        name = m["name"]
        dept = m["dept"]
        role = m["role"]
        instr_file = f"ai_company/instructions/{m['instruction']}"
        
        meta = AGENT_CUSTOM_META.get(name, {})
        zone = meta.get("zone", pick_zone(name, role, dept))
        tunic = meta.get("tunic", "#3f6fa8")
        desc = meta.get("desc", role)

        agents.append({
            "name": name,
            "role": role,
            "department": dept,
            "department_name": meta.get("dept_name", dept),
            "description": desc,
            "source": "ai_company",
            "file": instr_file,
            "zone": zone,
            "sprite": SPRITES[seat_idx % len(SPRITES)],
            "tunic": tunic,
            "seat": seat_idx,
            "model": m["default_model"],
            "avatar": m["avatar"]
        })
        seat_idx += 1

    return agents


def scan_claude_agents(d: Path, source: str) -> list[dict]:
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
            h1 = _H1_RE.search(text)
            desc = h1.group(1).strip() if h1 else f.stem
        found.append({
            "name": name,
            "role": desc,
            "department": "claude",
            "department_name": "Claude Agent",
            "description": desc,
            "source": source,
            "file": str(f),
            "zone": pick_zone(name, desc, "claude"),
            "model": "claude-3.7-sonnet"
        })
    return found


def scan_all(project_root: Path, include_global: bool, preset_path: Path | None) -> list[dict]:
    # 1. ai_company 오케스트레이터 파싱
    agents = scan_orchestrator(project_root)

    # 2. .claude/agents/*.md 스캔
    claude_agents = scan_claude_agents(project_root / ".claude" / "agents", "project")
    if include_global:
        claude_agents += scan_claude_agents(Path.home() / ".claude" / "agents", "global")

    # 3. 프리셋 폴백 (에이전트가 없을 경우)
    if not agents and preset_path and preset_path.is_file():
        try:
            agents = json.loads(preset_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    seen: dict[str, dict] = {}
    for a in agents:
        seen[a["name"]] = a

    for ca in claude_agents:
        if ca["name"] not in seen:
            ca["sprite"] = SPRITES[len(seen) % len(SPRITES)]
            ca["seat"] = len(seen)
            ca["tunic"] = "#2f8a6d"
            seen[ca["name"]] = ca

    out = list(seen.values())
    for i, a in enumerate(out):
        a.setdefault("seat", i)
        a.setdefault("sprite", SPRITES[i % len(SPRITES)])
        meta = AGENT_CUSTOM_META.get(a["name"], {})
        a.setdefault("tunic", meta.get("tunic", "#3f6fa8"))
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="AI Company & Claude 에이전트 조직도 스캔")
    p.add_argument("--root", default=".", help="프로젝트 루트")
    p.add_argument("--global", dest="use_global", action="store_true", help="~/.claude/agents 포함")
    p.add_argument("--out", default=".pixel-office/org.json", help="출력 org.json 경로")
    p.add_argument("--preset", default="pixel_office/presets/default-company.json", help="프리셋 JSON 경로")
    args = p.parse_args()

    root = Path(args.root).resolve()
    preset_file = Path(args.preset)
    if not preset_file.is_absolute():
        preset_file = root / preset_file

    agents = scan_all(root, args.use_global, preset_file)

    # 수동 zone 설정 보존
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = root / out_path

    if out_path.is_file():
        try:
            prev = json.loads(out_path.read_text(encoding="utf-8"))
            kept = {a["name"]: a.get("zone") for a in prev.get("agents", []) if a.get("zone")}
            for a in agents:
                if a["name"] in kept:
                    a["zone"] = kept[a["name"]]
                    a["zone_manual"] = True
        except Exception:
            pass

    payload = {
        "agents": agents,
        "count": len(agents),
        "departments": [
            {"id": "executive", "name": "경영진", "color": "#1d2d44"},
            {"id": "dev", "name": "개발본부", "color": "#1b7a82"},
            {"id": "marketing", "name": "마케팅본부", "color": "#c35a38"},
            {"id": "media", "name": "미디어본부", "color": "#5e3c88"}
        ]
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")

    by_zone: dict[str, int] = {}
    for a in agents:
        by_zone[a["zone"]] = by_zone.get(a["zone"], 0) + 1

    print(f"✨ 픽셀 오피스 조직도 생성 완료: 총 {len(agents)}명")
    for z, n in sorted(by_zone.items(), key=lambda kv: -kv[1]):
        print(f"  - 구역 [{z:9s}]: {n}명")
    print(f"📁 저장 위치: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
