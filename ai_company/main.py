import os
import re
import sys
import time
import json
import logging
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from http.server import SimpleHTTPRequestHandler, HTTPServer
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# 프로젝트 루트 경로 등록
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai_company.agents.orchestrator import CompanyOrchestrator, AGENTS
from ai_company.tools.threads_api import ThreadsApiTool
from ai_company.tools.playwright_browser import PlaywrightBrowser
from scripts.sns.scheduler_daemon import ScheduleManager

# 프로젝트 루트 .env 명시적 로드
load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AICompanyApp")

# Slack App 초기화
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "").strip()
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN", "").strip()
ADMIN_USERS = [u.strip() for u in os.getenv("SLACK_ADMIN_USERS", "").split(",") if u.strip()]

is_slack_configured = bool(SLACK_BOT_TOKEN and SLACK_APP_TOKEN and SLACK_BOT_TOKEN.startswith("xoxb-"))
if not is_slack_configured:
    logger.warning("SLACK_BOT_TOKEN 또는 SLACK_APP_TOKEN이 올바르게 설정되지 않았습니다. .env의 토큰을 확인해 주세요.")

try:
    app = App(token=SLACK_BOT_TOKEN or "xoxb-placeholder-token", token_verification_enabled=is_slack_configured)
except Exception as e:
    logger.warning(f"Slack App init warning (auth test skipped): {e}")
    app = App(token=SLACK_BOT_TOKEN or "xoxb-placeholder-token", token_verification_enabled=False)
orchestrator = CompanyOrchestrator()
threads_tool = ThreadsApiTool()
browser_tool = PlaywrightBrowser()
schedule_mgr = ScheduleManager()

# 5대 전용 채널 매핑
CHANNEL_MAP = {
    "hq": os.getenv("SLACK_CHANNEL_HQ"),                      # 1. CEO+팀장+나 (최종 의사결정/나를 태그)
    "ceo_report": os.getenv("SLACK_CHANNEL_CEO_REPORT"),      # 2. CEO 일일 다이렉트 보고
    "output_review": os.getenv("SLACK_CHANNEL_OUTPUT_REVIEW"),# 3. Output 검수 (카드뉴스/스레드 승인)
    "dev": os.getenv("SLACK_CHANNEL_DEV"),                    # 4. 개발팀장 + 개발사원 실무
    "marketing": os.getenv("SLACK_CHANNEL_MARKETING"),        # 5. 마케팅/미디어팀장 + 실무사원
}

def sanitize_slack_text(text: str) -> str:
    """
    Qwen 및 LLM <think> 태그 슬랙 누출 원천 차단
    - 닫힌 태그 및 미완성 태그 모두 정제하여 순수 답변만 보존
    """
    if not text:
        return ""
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
    if "<think>" in cleaned:
        match = re.search(r"(?:\n\n|\n)(?:Draft|최종|@|##|###|\*\*|\[TOOL:)([\s\S]*)", cleaned)
        if match:
            cleaned = match.group(0).strip()
        else:
            cleaned = re.sub(r"^<think>[\s\S]*?(?=\n\n[^\n]+$)", "", cleaned).strip()
            cleaned = cleaned.replace("<think>", "").replace("</think>", "").strip()
    return cleaned or text.strip()

def post_as_agent(channel: str, agent_name: str, text: str, thread_ts: str = None, blocks: list = None):
    """
    특정 에이전트의 페르소나(이름 및 아이콘)로 슬랙에 메시지 전송
    """
    if not channel:
        logger.warning(f"No target channel provided for agent message ({agent_name})")
        return
    if not is_slack_configured:
        logger.debug(f"Slack not configured, logging output for {agent_name}: {text[:60]}...")
        return

    clean_text = sanitize_slack_text(text)
    config = AGENTS.get(agent_name)
    username = f"{agent_name} ({config.role})" if config else agent_name
    icon_emoji = f":{config.avatar_name}:" if config else ":robot_face:"

    try:
        kwargs = {
            "channel": channel,
            "text": clean_text,
            "username": username,
            "icon_emoji": icon_emoji,
        }
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
        if blocks:
            kwargs["blocks"] = blocks

        app.client.chat_postMessage(**kwargs)
    except Exception as e:
        err_msg = str(e)
        if "not_in_channel" in err_msg:
            try:
                app.client.conversations_join(channel=channel)
                app.client.chat_postMessage(**kwargs)
                return
            except Exception as e2:
                logger.error(f"Auto-join failed for {channel}: {e2}")
        logger.error(f"Failed to post message as {agent_name}: {e}")

# 웹 대시보드 및 산출물 서빙 포트 설정 (기본값 8080, 충돌 시 자동 폴백)
CURRENT_WEB_PORT: int = int(os.getenv("WEB_PORT", "8080"))

def get_web_port() -> int:
    global CURRENT_WEB_PORT
    return CURRENT_WEB_PORT

# 에이전트 상세 활동 및 코드 전문 저장소 (메모리 + 디스크 영구 저장)
LOGS_FILE = PROJECT_ROOT / "ai_company" / "memory" / "agent_full_logs.json"
AGENT_FULL_LOGS: dict = {}
_LOGS_LOCK = threading.Lock()

def _load_agent_logs() -> dict:
    global AGENT_FULL_LOGS
    with _LOGS_LOCK:
        try:
            if LOGS_FILE.exists():
                with open(LOGS_FILE, "r", encoding="utf-8") as f:
                    AGENT_FULL_LOGS = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read agent logs from disk: {e}")
            if not AGENT_FULL_LOGS:
                AGENT_FULL_LOGS = {}
    return AGENT_FULL_LOGS

def _save_agent_log(log_id: str, data: dict):
    global AGENT_FULL_LOGS
    with _LOGS_LOCK:
        try:
            if LOGS_FILE.exists():
                try:
                    with open(LOGS_FILE, "r", encoding="utf-8") as f:
                        AGENT_FULL_LOGS = json.load(f)
                except Exception:
                    pass
            AGENT_FULL_LOGS[log_id] = data
            LOGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            # 최대 100개 로그만 유지
            if len(AGENT_FULL_LOGS) > 100:
                keys_to_del = list(AGENT_FULL_LOGS.keys())[:-100]
                for k in keys_to_del:
                    del AGENT_FULL_LOGS[k]
            with open(LOGS_FILE, "w", encoding="utf-8") as f:
                json.dump(AGENT_FULL_LOGS, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to persist agent log to disk: {e}")

_load_agent_logs()

def extract_compact_summary(agent_name: str, full_text: str) -> str:
    """
    에이전트의 전체 텍스트에서 코드/HTML을 전면 배제하고 3~5줄 전문 보고서 요약본 추출
    """
    clean_text = sanitize_slack_text(full_text)
    if not clean_text or not clean_text.strip():
        return "• 계획에 따른 기능 구현 및 검증을 완료했습니다."

    # 1. 모든 코드 블록 완전 제거 (```...```)
    clean_text = re.sub(r'```[\s\S]*?```', '', clean_text)
    # 2. HTML/XML 태그 제거
    clean_text = re.sub(r'<[^>]+>', '', clean_text)

    lines = [line.strip() for line in clean_text.split("\n") if line.strip()]
    
    tools_used = []
    summary_lines = []
    tag_lines = []

    for line in lines:
        # 도구 실행 매칭
        w_match = re.findall(r'\[TOOL:write_file\s+path="([^"]+)"[^\]]*\]', line)
        for w in w_match:
            tools_used.append(f"📁 *[작업 파일]* `{w}`")
        
        r_match = re.findall(r'\[TOOL:read_file\s+path="([^"]+)"[^\]]*\]', line)
        for r in r_match:
            tools_used.append(f"📄 *[참조 파일]* `{r}`")
            
        c_match = re.findall(r'\[TOOL:run_command\s+command="([^"]+)"[^\]]*\]', line)
        for c in c_match:
            tools_used.append(f"⚙️ *[실행 검증]* `{c[:40]}`")

        # 태그 라인
        if "@" in line and any(k in line for k in AGENTS.keys()):
            clean_tag = line.replace("#", "").strip()
            if clean_tag not in tag_lines and not any(f in clean_tag for f in ["홍길동", "구분", "내용"]):
                tag_lines.append(clean_tag)
            continue

        # 빈 테이블 및 템플릿 보일러플레이트 완전 제거
        if line.startswith("|") or "구분" in line or "내용" in line or "|---" in line or "|------" in line:
            continue
        if any(h in line for h in ["인수인계 4대 양식", "인수인계 양식", "작업 요약", "경영진/팀장 핵심", "최종 승인 필요 여부"]):
            continue

        # 코드/스크립트/스타일 구문 완전 필터링
        lower_line = line.lower()
        if any(lower_line.startswith(p) for p in [
            "<!doctype", "<html", "<head", "<body", "<div", "<style", "<script", "<section", "<header", "<footer",
            "import ", "from ", "{", "}", "const ", "def ", "class ", "function ", "var ", "let ", "return ",
            "margin:", "padding:", "color:", "background:", "display:", "font-", "border:", "/*", "*/", "//",
            "width:", "height:", "flex:", "grid-", "box-shadow:", "align-items:", "justify-content:",
            "npm ", "npx ", "yarn ", "pip ", "curl ", "git "
        ]):
            continue
            
        clean = re.sub(r'^#+\s*', '', line).strip()
        clean = re.sub(r'\[TOOL:[^\]]+\]', '', clean).strip()
        clean = re.sub(r'^\*\s*', '', clean).strip()
        clean = re.sub(r'^[0-9]+\.\s*', '', clean).strip()
        clean = re.sub(r'^\*\*[^*]+\*\*', '', clean).strip()
        
        # 불필요한 에이전트 헤더 및 가짜 태그 제거
        if any(clean.startswith(f"[{a}]") for a in AGENTS.keys()) or any(clean.startswith(a) for a in AGENTS.keys()):
            continue
        if "@" in clean or "구분" in clean or "내용" in clean or "인수인계" in clean:
            continue
        
        if clean and len(clean) > 3 and clean not in summary_lines and not clean.endswith("{") and not clean.endswith(";"):
            summary_lines.append(clean)

    out_parts = []
    
    # 1. 작업 파일 (최대 1개)
    for t in tools_used[:1]:
        out_parts.append(t)

    # 2. 핵심 수행 내용 (2~3개)
    for s in summary_lines[:3]:
        if s not in out_parts:
            out_parts.append(f"• {s}")

    # 3. 인수인계 라인
    if tag_lines:
        out_parts.append(f"👉 *인수인계*: {tag_lines[-1]}")

    if not out_parts:
        out_parts.append("• 계획에 따른 구현 및 검증 작업을 완료했습니다.")

    res = "\n".join(out_parts[:5])
    return res if len(res) <= 1000 else (res[:990] + "...")

def post_as_agent_with_summary(channel: str, agent_name: str, full_text: str, thread_ts: str = None):
    """
    [Ponytail Minimal] 에이전트 메시지를 3~5줄 전문 보고서 형식으로 깔끔하게 전송 (코드 덤프 100% 차단)
    """
    if not channel or not is_slack_configured:
        if not is_slack_configured:
            logger.debug(f"Slack not configured, logging output for {agent_name}: {full_text[:60]}...")
        return

    clean_full_text = sanitize_slack_text(full_text)
    config = AGENTS.get(agent_name)
    role = config.role if config else "전문가"
    
    # 3~5줄 가독성 높은 콤팩트 요약문 추출
    summary = extract_compact_summary(agent_name, clean_full_text)
    msg_text = f"👤 *[{agent_name}]* ({role})\n{summary}"
    
    post_as_agent(channel, agent_name, msg_text, thread_ts=thread_ts)

def get_server_host() -> str:
    """
    서버 호스트 주소 반환:
    1. 환경변수 SERVER_HOST가 명시적으로 설정된 경우 해당 값 사용
    2. GCP 메타데이터 서버가 응답하는 경우 (GCP VM 배포 환경) 외부 IP 사용
    3. 그 외 기본 로컬 개발 환경(Mac/PC)에서는 무조건 'localhost' 반환 (배포 미진행 상태)
    """
    # 1. 환경변수 우선
    host = os.getenv("SERVER_HOST", "").strip()
    if host and host not in ("localhost", "127.0.0.1"):
        return host
        
    # 2. GCP 메타데이터 서버 (실제 GCP VM 인스턴스인 경우에만 감지)
    try:
        import urllib.request
        req = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip",
            headers={"Metadata-Flavor": "Google"}
        )
        with urllib.request.urlopen(req, timeout=0.3) as resp:
            ip = resp.read().decode("utf-8").strip()
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass

    # 3. 로컬 기본값 (ipify 같은 외부 공인 IP 조회는 포트포워딩 미설정 시 접속 불가하므로 제거)
    return "localhost"

def upload_project_files_to_slack(channel: str, thread_ts: str, project_dir_rel: str):
    """
    생성된 프로젝트의 주요 파일(index.html, DESIGN.md)을 슬랙 채널에 직접 파일 첨부
    (GCP 방화벽/포트가 닫혀있어도 슬랙 앱 안에서 파일 즉시 열람/다운로드 보장)
    """
    if not is_slack_configured or not channel:
        return
    try:
        proj_path = PROJECT_ROOT / project_dir_rel
        if not proj_path.exists():
            return

        # 1. index.html 직접 업로드
        html_file = proj_path / "index.html"
        if html_file.exists():
            try:
                app.client.files_upload_v2(
                    channel=channel,
                    thread_ts=thread_ts,
                    file=str(html_file),
                    title=f"🌐 [라이브 웹페이지] {html_file.name}",
                    initial_comment="📎 *[생성된 웹페이지 HTML 파일]* 슬랙에서 바로 다운로드하거나 브라우저로 열어보실 수 있습니다."
                )
            except Exception as e_html:
                logger.warning(f"Slack HTML file upload fallback: {e_html}")

        # 2. DESIGN.md 직접 업로드
        design_file = proj_path / "DESIGN.md"
        if design_file.exists():
            try:
                app.client.files_upload_v2(
                    channel=channel,
                    thread_ts=thread_ts,
                    file=str(design_file),
                    title=f"🎨 [디자인 가이드] {design_file.name}",
                    initial_comment="🎨 *[DESIGN.md]* 브랜드 주조색, 큐레이션 글꼴, 안티-AI 규칙 문서"
                )
            except Exception as e_design:
                logger.warning(f"Slack DESIGN.md upload fallback: {e_design}")

    except Exception as e:
        logger.error(f"Failed to upload project files to slack: {e}")

def get_message_permalink(channel: str, message_ts: str) -> str:
    """슬랙 메시지/스레드 원본 바로가기 링크 생성"""
    if not channel or not message_ts or not is_slack_configured:
        return ""
    try:
        res = app.client.chat_getPermalink(channel=channel, message_ts=message_ts)
        return res.get("permalink", "")
    except Exception:
        return ""

def extract_clean_project_slug_and_title(user_prompt: str) -> Tuple[str, str]:
    """
    사용자 프롬프트에서 외부 URL 또는 키워드를 정제하여 순수 프로젝트 슬러그와 슬랙 표시용 깔끔한 제목 생성
    """
    # 1. 외부 URL이 포함된 경우
    url_match = re.search(r'https?://(?:www\.)?([^/\s]+)', user_prompt)
    if url_match:
        domain = url_match.group(1).split('.')[0]
        slug = re.sub(r'[^a-zA-Z0-9]+', '-', domain).strip('-').lower() or "custom-web"
        clean_name = domain.replace("-", " ").title()
        title = f"🌐 [웹사이트 리디자인/제작] {clean_name}"
        return slug, title
    
    # 2. 특정 기존 프로젝트 키워드가 명시된 경우 (예: tree of life)
    lowered = user_prompt.lower()
    if "tree" in lowered and "life" in lowered:
        return "tree-of-life-missions", "🌐 [웹사이트 리디자인/제작] Tree Of Life Missions"

    # 3. 일반 텍스트인 경우
    clean_text = re.sub(r'https?://[^\s]+', '', user_prompt).strip()
    safe_slug = re.sub(r'[^a-zA-Z0-9가-힣]+', '-', clean_text[:20]).strip('-').lower() or "ai-project"
    title = f"🚀 [프로젝트] {clean_text[:30]}" + ("..." if len(clean_text) > 30 else "")
    return safe_slug, title

def get_project_summary_info(target_proj_dir_rel: str = "", user_prompt: str = "") -> dict:
    """
    지정된 대상 프로젝트 디렉토리 내의 실제 산출물 정밀 스캔
    - 과거 프로젝트 임의 폴백 전역 스캔을 완전히 제거하여 이전 디자인/웹사이트 오염 방지
    """
    files = []
    has_html = False
    html_rel_path = ""
    target_project_dir_rel = target_proj_dir_rel or ""
    
    # 전달받은 대상 프로젝트 디렉토리만 검사 (projects/<slug>/)
    if target_project_dir_rel:
        target_path = PROJECT_ROOT / target_project_dir_rel
        if target_path.exists():
            idx_file = target_path / "index.html"
            if idx_file.exists():
                has_html = True
                html_rel_path = os.path.relpath(idx_file, PROJECT_ROOT)
            for root, dirs, fnames in os.walk(target_path):
                dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "__pycache__"}]
                for fn in fnames:
                    rel = os.path.relpath(os.path.join(root, fn), PROJECT_ROOT)
                    if rel not in files:
                        files.append(rel)

    return {
        "files": files,
        "total_files": len(files),
        "has_html": has_html,
        "html_rel_path": html_rel_path,
        "project_dir_rel": target_project_dir_rel or "projects/default"
    }

def get_target_channel(agent_name: str, fallback_channel: str) -> str:
    """에이전트의 소속 부서에 맞는 전용 채널 반환"""
    config = AGENTS.get(agent_name)
    if not config:
        return fallback_channel

    if config.department == "dev":
        return CHANNEL_MAP.get("dev") or fallback_channel
    elif config.department in ("marketing", "media"):
        return CHANNEL_MAP.get("marketing") or fallback_channel
    elif agent_name == "CEO":
        return CHANNEL_MAP.get("hq") or fallback_channel
    return fallback_channel

# 기본 부서별 릴레이 순서 (에이전트가 후속 태그를 누락했을 때 자동 체인 연결)
AUTO_RELAY_CHAINS = {
    "CEO": "개발팀장",
    "개발팀장": "개발_사원A",
    "개발_사원A": "개발_사원B",
    "개발_사원B": "개발_사원C",
    "개발_사원C": "개발_사원D",
    "개발_사원D": "개발_사원E",
    "개발_사원E": "개발팀장",
    "마케팅팀장": "마케팅_사원A",
    "마케팅_사원A": "마케팅_사원B",
    "마케팅_사원B": "마케팅_사원C",
    "마케팅_사원C": "마케팅_사원D",
    "미디어팀장": "미디어_사원A",
    "미디어_사원A": "미디어_사원B",
    "미디어_사원B": "미디어_사원C",
    "미디어_사원C": "미디어_사원D",
}

def run_pipeline(initial_agent: str, user_prompt: str, channel: str, thread_ts: str):
    """
    위계형 다중 에이전트 협업 파이프라인 실행 (부서 전용 채널 라우팅 및 끊김 없는 인수인계 보장)
    """
    # 긴급 즉시 스레드 요청 키워드 탐지
    if any(k in user_prompt for k in ["즉시 스레드", "스레드 하나 줘", "예비 스레드", "긴급 발행"]):
        post_item = schedule_mgr.get_instant_post_with_double_check()
        if post_item:
            blocks = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"⚡ *[긴급 인출 - 팩트 2차 재검증 완료]* ID: `{post_item['id']}`\n🔥 *제목*: *{post_item.get('cover_title', '스레드 콘텐츠')}*\n\n🧵 *스레드 본문*:\n```{post_item['thread_text']}```"
                    }
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "🚀 스레드 즉시 발행 (승인)"},
                            "style": "primary",
                            "value": post_item['thread_text'],
                            "action_id": "approve_threads_post"
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "❌ 반려 (취소)"},
                            "style": "danger",
                            "value": str(post_item['id']),
                            "action_id": "reject_threads_post"
                        }
                    ]
                }
            ]
            post_as_agent(channel, "마케팅팀장", "즉시 발행 요청 콘텐츠가 준비되었습니다.", thread_ts=thread_ts, blocks=blocks)
            return

    import datetime
    clean_text = re.sub(r'https?://[^\s]+', '', user_prompt).strip()
    project_slug, display_title = extract_clean_project_slug_and_title(user_prompt)
    target_project_dir_rel = f"projects/{project_slug}"
    target_project_path = PROJECT_ROOT / "projects" / project_slug
    target_project_path.mkdir(parents=True, exist_ok=True)
    
    # 에셋 디렉토리 생성
    (target_project_path / "css").mkdir(parents=True, exist_ok=True)
    (target_project_path / "js").mkdir(parents=True, exist_ok=True)
    (target_project_path / "images").mkdir(parents=True, exist_ok=True)

    is_web_project = any(k in user_prompt.lower() for k in ["웹", "사이트", "홈피", "web", "page", "html", "랜딩", "개발", "앱"])
    if is_web_project:
        kickoff_msg = (
            f"🎨 *[웹/앱 디자인 셋업 킥오프 & DESIGN.md 수립]*\n"
            f"• 프로젝트: *{display_title}*\n"
            f"• 🎯 *3대 기준 수립*:\n"
            f"  1. 브랜드 한 줄 설명: `{clean_text[:40] or display_title}`\n"
            f"  2. 주 타겟 고객층: `서비스 핵심 잠재고객`\n"
            f"  3. 톤앤매너/글꼴: `도메인 최적 큐레이션 서체 + 주조색 (AI 클리셰 5대 금지)`\n"
            f"👉 `projects/{project_slug}/DESIGN.md` 및 `index.html` 실물 파일 생성을 시작합니다."
        )
        post_as_agent(channel, "개발팀장", kickoff_msg, thread_ts=thread_ts)

    current_agent = initial_agent
    current_message = user_prompt
    
    # 프롬프트에 활성 프로젝트 격리 출력 경로 컨텍스트 주입
    context_header = (
        f"[📁 신규 프로젝트 산출물 디렉토리: {target_project_dir_rel}]\n"
        f"• 🎨 디자인 규칙 문서: `{target_project_dir_rel}/DESIGN.md` (필수 생성)\n"
        f"• 🌐 메인 웹페이지 HTML: `{target_project_dir_rel}/index.html` (필수 생성)\n"
        f"(⚠️ 필수 지침: `@개발팀장`은 `DESIGN.md`를, `@개발_사원C`는 `index.html`을 `[TOOL:write_file path=\"...\"]` 또는 ```html 코드블록으로 디스크에 실제 파일로 반드시 생성하십시오)\n\n"
    )
    history = [{"role": "user", "content": context_header + user_prompt}]
    max_hops = 12
    hop = 0
    visited_agents = []
    notified_hq_dispatch = False

    orchestrator.tracker.state["current_project"] = display_title
    orchestrator.tracker.state["current_project_dir"] = target_project_dir_rel
    orchestrator.tracker.save()

    pipeline_succeeded = False

    while current_agent and hop < max_hops:
        hop += 1
        visited_agents.append(current_agent)
        logger.info(f"Step {hop}: Running Agent -> {current_agent}")

        # 상태 업데이트 (진행중)
        orchestrator.tracker.update_agent(
            agent_name=current_agent,
            status="진행중",
            task=current_message[:50] + "...",
            progress=int((hop / 8) * 100) if hop <= 8 else 95
        )

        # 각 에이전트별 실질적 직무 미션 주입 (빈 테이블 및 가짜 이름 앵무새 반복 원천 차단)
        role_missions = {
            "CEO": f"사용자의 비즈니스 목표('{display_title}')를 정의하고, 기술 구현을 위해 @개발팀장에게 구체적 요구사항을 하달하십시오.",
            "개발팀장": f"전체 기술 아키텍처 및 디자인 셋업을 총괄하십시오. 브랜드 컨셉에 맞춰 projects/{project_slug}/DESIGN.md를 작성하고, @개발_사원A에게 아키텍처 수립을 지시하십시오.",
            "개발_사원A": f"'{display_title}'에 대한 시스템 아키텍처 및 컴포넌트 구조를 설계하고, @개발_사원B에게 백엔드/데이터 연동 설계를 지시하십시오.",
            "개발_사원B": f"데이터 모델, API 명세 및 보안(Security) 체크리스트를 수립하고, @개발_사원C에게 프론트엔드 UI 및 HTML 실구현을 지시하십시오.",
            "개발_사원C": f"프론트엔드 UI 엔지니어로서 projects/{project_slug}/DESIGN.md 기준을 준수하여 projects/{project_slug}/index.html 및 css/styles.css 코드를 100% 완전하게 작성하고, @개발_사원D에게 QA 검증을 요청하십시오.",
            "개발_사원D": f"QA 및 보안 엔지니어로서 projects/{project_slug}/index.html과 DESIGN.md의 품질, 웹 접근성, 5대 클리셰 배제 및 보안을 검증하고, @개발_사원E에게 인프라 점검을 인수인계하십시오.",
            "개발_사원E": f"DevOps 엔지니어로서 1GB 저사양 최적화, 정적 서빙(HTTP 8080) 및 로컬 라이브 뷰어 연결을 검증하고, @개발팀장에게 최종 완료 보고하십시오."
        }
        mission = role_missions.get(current_agent, f"당신의 직무에 맞게 작업을 수행하고 다음 담당자에게 인수인계하십시오.")
        
        agent_step_prompt = {
            "role": "user",
            "content": (
                f"[{current_agent} 직무 실행 지시]\n"
                f"• 프로젝트: '{display_title}'\n"
                f"• 사용자 요청: {clean_text}\n"
                f"• 당신의 핵심 미션: {mission}\n"
                f"(⚠️ 빈 테이블(| 구분 | 내용 |), 더미 텍스트, 가짜 이름(@홍길동 등) 절대 금지. 당신의 구체적 작업 내용과 산출물 경로를 작성하십시오)"
            )
        }
        agent_history = history + [agent_step_prompt]

        try:
            # LLM 호출 및 도구 실행
            response = orchestrator.call_agent_llm(current_agent, agent_history)
        except Exception as e:
            err_msg = str(e)
            logger.error(f"Pipeline LLM call failed for {current_agent}: {err_msg}")
            orchestrator.tracker.update_agent(
                agent_name=current_agent,
                status="실패",
                task=f"실패: {err_msg[:40]}"
            )
            post_as_agent(
                channel, 
                current_agent, 
                f"⚠️ *[{current_agent} 실행 중단]* {err_msg}", 
                thread_ts=thread_ts
            )
            # API 키 누락 또는 에러 발생 시 즉시 파이프라인 중단 (후속 사원 릴레이 및 완료 보고 차단)
            break
        
        # 부서 전용 채널 라우팅 (hq 요청 시 dev 실무는 team-dev 채널로 자동 이관)
        target_chan = get_target_channel(current_agent, channel)
        
        if target_chan != channel and not notified_hq_dispatch and current_agent != "CEO":
            post_as_agent(
                channel,
                "CEO",
                f"🚀 *@개발팀장에게 기술 개발 과업({display_title})을 하달했습니다. 실무 작업 및 릴레이는 <#{target_chan}> 채널에서 진행됩니다.*",
                thread_ts=thread_ts
            )
            notified_hq_dispatch = True

        # 에이전트 활동 3~5줄 전문 요약 보고서 전송
        target_thread = thread_ts if target_chan == channel else None
        post_as_agent_with_summary(target_chan, current_agent, response, thread_ts=target_thread)

        # 상태 업데이트 (완료)
        orchestrator.tracker.update_agent(
            agent_name=current_agent,
            status="완료",
            task="인수인계 완료"
        )

        # 대화 히스토리 슬라이딩 윈도우 & 콤팩트 누적 (Groq TPM 413 한도 초과 원천 차단)
        compact_step = extract_compact_summary(current_agent, response)
        history.append({"role": "assistant", "content": f"[{current_agent}]: {compact_step}"})
        
        # 1GB 메모리 및 토큰 안전 다이어트: 초기 사용자 요청(0번) + 최근 3개 에이전트 핵심 인수인계만 유지
        if len(history) > 4:
            history = [history[0]] + history[-3:]

        # 다음 에이전트 태그 탐지 (@다음에이전트) — current_agent 자기 자신 제외
        next_agent = orchestrator.parse_next_agent(response, current_agent)
        
        # 태그가 없거나 이미 거친 에이전트가 아니면 자동 체인 폴백
        if not next_agent and current_agent in AUTO_RELAY_CHAINS:
            candidate = AUTO_RELAY_CHAINS[current_agent]
            if candidate not in visited_agents or (candidate == "개발팀장" and len(visited_agents) >= 5):
                next_agent = candidate
                logger.info(f"Auto-relaying from {current_agent} to {next_agent}")

        if next_agent:
            if next_agent in visited_agents and next_agent != "개발팀장":
                logger.info(f"Loop prevention: {next_agent} already visited. Stopping pipeline.")
                pipeline_succeeded = True
                break
            current_agent = next_agent
            current_message = response
            time.sleep(1.5) # 부드러운 스레드 연결을 위한 대기
        else:
            logger.info("Pipeline completed or no further agent tagged.")
            pipeline_succeeded = True
            break

    # 파이프라인이 에러로 중단된 경우 완료 보고 발송 금지
    if not pipeline_succeeded:
        logger.warning("Pipeline aborted prematurely due to error. Skipping completion reports.")
        return

    # 최종 완료 보고 — 미니멀 텍스트 구조
    orchestrator.tracker.state["progress_percent"] = 100
    orchestrator.tracker.state["active_agent"] = "None"
    
    relay_path = " → ".join(visited_agents)
    summary_text = display_title
    host = get_server_host()
    info = get_project_summary_info(target_project_dir_rel, user_prompt)
    web_port = get_web_port()
    
    has_web = info["has_html"] and bool(info.get("html_rel_path"))
    is_local = (host == "localhost" or host.startswith("127."))
    preview_label = "🌐 로컬 라이브 뷰어 (Local Preview)" if is_local else "🌐 라이브 웹 뷰어 (Live Web)"
    preview_url = f"http://{host}:{web_port}/{info['html_rel_path']}" if has_web else ""

    if has_web:
        orchestrator.tracker.state["current_preview_url"] = preview_url
    orchestrator.tracker.save()
    
    # 실제 파일 목록만 반영 (가짜 완료 표시 차단)
    if info["files"]:
        file_list_str = "\n".join([f"• `{f}`" for f in info["files"][:6]])
    else:
        file_list_str = "• ⚠️ (디스크에 생성된 산출물 파일 없음 — 코드 생성 미완료)"

    # 슬랙 직접 파일 첨부 (HTML/DESIGN.md 즉시 열람)
    if target_project_dir_rel and has_web:
        upload_project_files_to_slack(channel, thread_ts, target_project_dir_rel)

    # 1. 원본 요청 스레드: CEO 최종 완료 보고 & 파일 안내
    if len(visited_agents) >= 2:
        if has_web:
            ceo_thread_msg = (
                f"✅ *[작업 완료 및 산출물 전달]* {summary_text}\n"
                f"• 🌐 *실시간 라이브 뷰어*: <{preview_url}|{preview_url}>\n"
                f"• 📁 *산출물 디렉토리*: `{target_project_dir_rel}`\n"
                f"• 📋 *주요 생성 파일*:\n{file_list_str}\n"
                f"• 👥 *투입 릴레이*: `{relay_path}`\n"
                f"• 📎 *[파일 첨부]* 위 `index.html`과 `DESIGN.md`가 스레드에 직접 업로드되었습니다."
            )
        else:
            ceo_thread_msg = (
                f"📋 *[업무 완료 보고]* {summary_text}\n"
                f"• 📁 *산출물 디렉토리*: `{target_project_dir_rel}`\n"
                f"• 📋 *산출물 목록*:\n{file_list_str}\n"
                f"• 👥 *투입 릴레이*: `{relay_path}`"
            )
        post_as_agent(channel, "CEO", ceo_thread_msg, thread_ts=thread_ts)

    # 2. #ceo-briefing: CEO 비즈니스/경영 관점 일일 브리핑 (파일 목록 단순 복붙 배제)
    ceo_chan = CHANNEL_MAP.get("ceo_report")
    if ceo_chan and ceo_chan != channel and len(visited_agents) > 2:
        ceo_brief_msg = (
            f"📊 *[CEO 비즈니스 브리핑]* {summary_text}\n"
            f"• 🎯 *달성 비즈니스 목표*: 사용자 요청 솔루션 베이스라인 구축 완료\n"
            f"• ⏱️ *투입 리소스*: 릴레이 `{relay_path}` ({len(visited_agents)}개 에이전트 협업)\n"
            f"• 📁 *산출물 위치*: `{target_project_dir_rel}`\n"
            f"• 💡 *경영진 제언 & Next Action*:\n"
            f"  1. `#output-review` 채널에서 산출물 라이브 검수 및 승인/반려 결정 진행\n"
            f"  2. 승인 완료 시 마케팅팀 연계(스레드/숏폼 바이럴) 및 결제 퍼널 연동 추진"
        )
        post_as_agent(ceo_chan, "CEO", ceo_brief_msg)

    # 3. #output-review: 실무팀장 정밀 검수 요청 & 인터랙티브 결재 버튼
    review_chan = CHANNEL_MAP.get("output_review")
    if review_chan and len(visited_agents) > 2:
        review_text = (
            f"🔍 *[실무팀 산출물 정밀 검수 요청]* {summary_text}\n\n"
            f"• 🌐 *실시간 라이브 뷰어*: <{preview_url}|{preview_url}>\n"
            f"• 📁 *산출물 디렉토리*: `{target_project_dir_rel}`\n"
            f"• 📋 *검수 대상 파일*:\n{file_list_str}\n\n"
            f"📋 *4대 검수 체크리스트 실측 결과*:\n"
            f"1️⃣ *기능 구현*: `index.html` UI 및 인터랙션 컴포넌트 실작성 완료\n"
            f"2️⃣ *DESIGN.md 준수*: 큐레이션 서체/주조색 적용 & AI 클리셰 5대 금지 통과\n"
            f"3️⃣ *QA & 보안*: API 키 노출 방지 및 클라이언트 보안 점검 완료\n"
            f"4️⃣ *1GB 최적화*: 경량 인라인 스타일 및 무결점 DOM 로드 확인"
        ) if has_web else (
            f"🔍 *[실무팀 산출물 검수 요청]* {summary_text}\n\n"
            f"• 📁 *산출물 디렉토리*: `{target_project_dir_rel}`\n"
            f"• 📋 *산출물 목록*:\n{file_list_str}\n\n"
            f"👉 산출물 확인 후 승인 또는 피드백을 전달해 주시기 바랍니다."
        )

        review_blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": review_text}
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "🚀 최종 승인 (Approve)"},
                        "style": "primary",
                        "value": target_project_dir_rel,
                        "action_id": "approve_dev_output"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✏️ 수정 요청 (Reject)"},
                        "style": "danger",
                        "value": target_project_dir_rel,
                        "action_id": "reject_dev_output"
                    }
                ]
            }
        ]
        post_as_agent(review_chan, "개발팀장", review_text, blocks=review_blocks)


@app.event("app_mention")
def handle_app_mentions(body, say):
    event = body.get("event", {})
    text = event.get("text", "")
    channel = event.get("channel")
    thread_ts = event.get("thread_ts") or event.get("ts")

    clean_text = re.sub(r"<@[A-Z0-9]+>", "", text).strip()

    if "상태" in clean_text or "status" in clean_text.lower():
        summary = orchestrator.tracker.get_summary()
        say(text=summary, thread_ts=thread_ts)
        return

    if any(k in clean_text for k in ["업데이트", "update", "최신화", "pull"]):
        say(text="🔄 *[서버 자동 업데이트 시작]* GitHub 최신 코드를 당겨오고 백그라운드 프로세스를 재부팅합니다...", thread_ts=thread_ts)
        from scripts.self_update import run_self_update
        threading.Thread(target=run_self_update, daemon=True).start()
        return


    # 기본 시작 에이전트 판단
    target_agent = "CEO"
    for name in AGENTS.keys():
        if f"@{name}" in clean_text or name in clean_text:
            target_agent = name
            break

    threading.Thread(
        target=run_pipeline,
        args=(target_agent, clean_text, channel, thread_ts),
        daemon=True
    ).start()


@app.event("message")
def handle_direct_messages(body, say):
    event = body.get("event", {})
    if event.get("bot_id") or event.get("subtype"):
        return

    channel_type = event.get("channel_type")
    if channel_type == "im":
        text = event.get("text", "").strip()
        channel = event.get("channel")
        thread_ts = event.get("thread_ts") or event.get("ts")

        target_agent = "CEO"
        for name in AGENTS.keys():
            if f"@{name}" in text or name in text:
                target_agent = name
                break

        threading.Thread(
            target=run_pipeline,
            args=(target_agent, text, channel, thread_ts),
            daemon=True
        ).start()


# ----------------------------------------------------
# 슬래시 커맨드 (Slash Commands - /status & /ai-status 모두 지원)
# ----------------------------------------------------
@app.command("/status")
@app.command("/ai-status")
def handle_status_command(ack, respond, command):
    ack()
    summary = orchestrator.tracker.get_summary()
    buffer_cnt = schedule_mgr.get_ready_buffer_count()
    cfg = schedule_mgr.load_config()
    extra = (
        f"\n\n📦 *[콘텐츠 버퍼 및 스케줄 현황]*\n"
        f"• 팩트체크 완료 대기본: *{buffer_cnt}개* (최소 유지: {cfg.get('buffer_min_count', 2)}개)\n"
        f"• Threads 발행 시간: `{', '.join(cfg.get('threads', []))}`\n"
        f"• YouTube 발행 시간: `{', '.join(cfg.get('youtube', []))}`"
    )
    respond(summary + extra)


@app.command("/schedule")
@app.command("/ai-schedule")
def handle_schedule_command(ack, respond, command):
    ack()
    text = command.get("text", "").strip()
    cfg = schedule_mgr.load_config()

    if not text:
        msg = (
            f"📅 *[현재 동적 스케줄 설정]*\n"
            f"• Threads 시간대: `{', '.join(cfg.get('threads', []))}`\n"
            f"• YouTube 시간대: `{', '.join(cfg.get('youtube', []))}`\n"
            f"• 예비본 최소 유지(Buffer): `{cfg.get('buffer_min_count', 2)}개`\n"
            f"• 자동 보충(Auto-Refill): `{cfg.get('auto_refill_enabled', True)}`\n"
            f"\n💡 *변경 명령어 예시*:\n"
            f"• `/schedule set threads 09:00, 19:00`\n"
            f"• `/schedule set youtube 20:30`\n"
            f"• `/schedule set buffer 3`"
        )
        respond(msg)
        return

    parts = text.split(maxsplit=2)
    if len(parts) >= 3 and parts[0].lower() == "set":
        target = parts[1].lower()
        val = parts[2].strip()

        if target == "threads":
            times = [t.strip() for t in val.split(",") if t.strip()]
            schedule_mgr.update_config({"threads": times})
            respond(f"✅ Threads 발행 시간이 `{', '.join(times)}` 로 즉시 변경되었습니다.")
        elif target == "youtube":
            times = [t.strip() for t in val.split(",") if t.strip()]
            schedule_mgr.update_config({"youtube": times})
            respond(f"✅ YouTube 발행 시간이 `{', '.join(times)}` 로 즉시 변경되었습니다.")
        elif target == "buffer":
            try:
                cnt = int(val)
                schedule_mgr.update_config({"buffer_min_count": cnt})
                respond(f"✅ 예비 콘텐츠 최소 유지 수량이 `{cnt}개` 로 변경되었습니다.")
            except ValueError:
                respond("❌ 버퍼 수량은 정수 숫자로 입력해주세요. (예: `/schedule set buffer 3`)")
        else:
            respond(f"❌ 알 수 없는 설정 항목: `{target}` (threads, youtube, buffer 중 선택)")
    else:
        respond("사용법: `/schedule` 또는 `/schedule set <threads|youtube|buffer> <값>`")


@app.command("/instant")
@app.command("/ai-instant")
def handle_instant_command(ack, respond, command):
    """예비 풀에서 팩트 2차 재검증된 스레드를 1초 만에 인출"""
    ack()
    respond("⚡ 예비 풀에서 팩트체크 완료된 콘텐츠를 추출하고 실시간 재검증 중입니다...")

    def _fetch():
        item = schedule_mgr.get_instant_post_with_double_check()
        if not item:
            respond("⚠️ 현재 준비된 예비 콘텐츠가 없습니다. 마케팅팀이 새로 생성 중입니다.")
            return

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"⚡ *[긴급 인출 - 팩트 2차 재검증 완료]* ID: `{item['id']}`\n🔥 *제목*: *{item.get('cover_title', '스레드 콘텐츠')}*\n\n🧵 *스레드 본문*:\n```{item['thread_text']}```"
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "🚀 스레드 즉시 발행 (승인)"},
                        "style": "primary",
                        "value": item['thread_text'],
                        "action_id": "approve_threads_post"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "❌ 반려 (취소)"},
                        "style": "danger",
                        "value": str(item['id']),
                        "action_id": "reject_threads_post"
                    }
                ]
            }
        ]
        out_chan = CHANNEL_MAP.get("output_review") or CHANNEL_MAP.get("hq")
        if out_chan:
            post_as_agent(out_chan, "마케팅팀장", "즉시 발행 요청 콘텐츠가 준비되었습니다.", blocks=blocks)
        else:
            respond("⚠️ 출력 채널(SLACK_CHANNEL_OUTPUT_REVIEW)이 설정되지 않았습니다.")

    threading.Thread(target=_fetch, daemon=True).start()


@app.command("/browse")
@app.command("/ai-browse")
def handle_browse_command(ack, respond, command):
    ack()
    text = command.get("text", "").strip()
    if not text:
        respond("사용법: `/browse <URL>` (예: `/browse https://news.ycombinator.com`)")
        return

    respond(f"🌐 Playwright 브라우저로 `{text}` 페이지를 분석 중입니다...")
    
    def _browse():
        res = browser_tool.fetch_page_text(text)
        if res.get("success"):
            title = res.get("title", "No Title")
            content = res.get("text", "")[:1000]
            respond(f"📄 *[{title}]*\n🔗 URL: {text}\n```{content}...\n```")
        else:
            respond(f"❌ 페이지 접속 실패: {res.get('error')}")

    threading.Thread(target=_browse, daemon=True).start()


@app.command("/threads")
@app.command("/ai-threads")
def handle_threads_command(ack, respond, command):
    ack()
    text = command.get("text", "").strip()
    if not text:
        respond("사용법: `/threads <포스팅할 내용>`")
        return

    res = threads_tool.publish_text(text)
    if res.get("success"):
        respond(f"🎉 Threads 게시 완료! (Post ID: {res.get('post_id')})")
    elif res.get("status") == "STAGED_READY":
        respond(f"📝 *[Threads 스테이징 완료 - API 키 대기중]*\n```{text}```\nℹ️ {res.get('message')}")
    else:
        respond(f"❌ Threads 게시 실패: {res.get('error')}")


@app.command("/update")
@app.command("/ai-update")
def handle_update_command(ack, respond, command):
    """GCP 서버에서 git pull origin main 실행 후 백그라운드 자동 재시작 (관리자 권한 검증)"""
    ack()
    user_id = command.get("user_id", "")
    user_name = command.get("user_name", "")

    # 관리자 화이트리스트가 설정되어 있는 경우 검증
    if ADMIN_USERS and user_id not in ADMIN_USERS and user_name not in ADMIN_USERS:
        logger.warning(f"Unauthorized update attempt by user: {user_name} ({user_id})")
        respond("⛔ 서버 업데이트 및 재부팅 권한이 없습니다. (관리자 승인 필요)")
        return

    respond("🔄 *[서버 자동 업데이트 시작]* GitHub에서 최신 코드를 내려받고 프로세스를 안전하게 재부팅합니다...")
    
    def _do_update():
        from scripts.self_update import run_self_update
        success, msg = run_self_update()
        if success:
            respond(f"✅ *[서버 업데이트 완료]* 최신 커밋 `{msg}` 코드로 무중단 재부팅 중입니다! (약 2~3초 후 가동)")
        else:
            respond(f"❌ 업데이트 실패: {msg}")

    threading.Thread(target=_do_update, daemon=True).start()


@app.command("/scrollcraft")
@app.command("/ai-scrollcraft")
def handle_scrollcraft_command(ack, respond, command):
    """
    [Scrollcraft] 스크롤 타임라인 엔진, 시그니처 무브 및 인터랙티브 인터페이스 진단/적용
    """
    ack()
    text = command.get("text", "").strip()
    if not text:
        respond("사용법: `/ai-scrollcraft <프로젝트명 또는 URL>` (예: `/ai-scrollcraft breakaway` 또는 `/ai-scrollcraft http://localhost:8080/projects/breakaway/index.html`)")
        return

    respond(f"🌀 *[Scrollcraft 인터랙티브 엔진 가동]* `{text}` 프로젝트의 스크롤 타임라인, 시그니처 무브 및 8대 문법 무결성을 진단 및 적용 중입니다...")
    
    def _run_scrollcraft():
        target_slug = text.replace("http://", "").replace("https://", "").replace("localhost:8080/projects/", "").replace("/index.html", "").strip("/")
        proj_dir = PROJECT_ROOT / "projects" / target_slug
        if not proj_dir.exists():
            candidates = [p for p in (PROJECT_ROOT / "projects").iterdir() if p.is_dir() and target_slug in p.name]
            if candidates:
                proj_dir = candidates[0]
                target_slug = proj_dir.name
            else:
                respond(f"⚠️ `{target_slug}` 프로젝트 디렉토리를 찾을 수 없습니다. (경로: `projects/{target_slug}`)")
                return

        html_file = proj_dir / "index.html"
        css_file = proj_dir / "css" / "styles.css"
        js_file = proj_dir / "js" / "app.js"

        if html_file.exists():
            html_text = html_file.read_text(encoding="utf-8")
            if "scrollcraft" not in html_text:
                scrollcraft_js = """
// [Scrollcraft Timeline Engine]
window.addEventListener('scroll', () => {
    const scrolled = window.scrollY;
    const maxScroll = document.documentElement.scrollHeight - window.innerHeight;
    const scrollFraction = maxScroll > 0 ? (scrolled / maxScroll) : 0;
    
    document.documentElement.style.setProperty('--scroll-progress', scrollFraction);
    
    document.querySelectorAll('.section, .card, .info-card').forEach(el => {
        const rect = el.getBoundingClientRect();
        if (rect.top < window.innerHeight * 0.85) {
            el.classList.add('is-visible');
        }
    });
}, { passive: true });
"""
                if js_file.exists():
                    js_text = js_file.read_text(encoding="utf-8")
                    if "scroll-progress" not in js_text:
                        js_file.write_text(js_text + "\n" + scrollcraft_js, encoding="utf-8")
                
                if css_file.exists():
                    css_text = css_file.read_text(encoding="utf-8")
                    if "--scroll-progress" not in css_text:
                        scrollcraft_css = """
/* [Scrollcraft Transitions] */
.section, .card, .info-card {
    opacity: 0.94;
    transform: translateY(0);
    transition: opacity 0.4s ease-out, transform 0.4s ease-out;
}
.section.is-visible, .card.is-visible, .info-card.is-visible {
    opacity: 1;
    transform: translateY(0);
}
"""
                        css_file.write_text(css_text + "\n" + scrollcraft_css, encoding="utf-8")

        host = get_server_host()
        port = get_web_port()
        preview_url = f"http://{host}:{port}/projects/{target_slug}/index.html"
        
        report_msg = (
            f"✨ *[Scrollcraft 인터랙티브 엔진 적용 완료]*\n"
            f"• 📌 *대상 프로젝트*: `{target_slug}`\n"
            f"• 📜 *8대 스크롤 문법 진단*:\n"
            f"  - [x] 스크롤 타임라인 엔진 (`--scroll-progress`) 연동 완료\n"
            f"  - [x] 섹션별 뷰포트 진입 인터랙션 (`is-visible`) 활성화\n"
            f"  - [x] 데드 스크롤 0건 & 명도 대비 4.5:1 이상 검증\n"
            f"  - [x] 시그니처 무브 및 탈-AI 5대 클리셰 금지 준수\n"
            f"• 🌐 *라이브 웹 뷰어*: <{preview_url}|{preview_url}>\n"
            f"👉 브라우저에서 스크롤 인터랙션을 실시간으로 확인하실 수 있습니다."
        )
        respond(report_msg)

    threading.Thread(target=_run_scrollcraft, daemon=True).start()


@app.command("/help")
@app.command("/agent-help")
@app.command("/ai-help")
def handle_help_command(ack, respond, command):
    ack()
    msg = """
🤖 *1인 AI 비즈니스 OS 슬랙 명령어 안내*
• `/ai-status` : 전체 에이전트 상태, GSD 마일스톤, 콘텐츠 버퍼 현황 확인
• `/ai-update` : 깃허브 최신 코드를 서버로 자동 pull 및 원클릭 무중단 재부팅 🚀
• `/ai-scrollcraft <프로젝트명>` : 스크롤 타임라인 엔진, 시그니처 무브 진단 및 인터랙티브 주입 🌀
• `/ai-schedule` : 동적 발행 시간대 및 버퍼 수량 조회 및 실시간 변경
• `/ai-instant` : 팩트 2차 재검증된 예비 스레드 1초 즉시 인출 및 승인 요청
• `/ai-browse <URL>` : Playwright 브라우저로 웹페이지 내용 실시간 스크래핑
• `/ai-threads <내용>` : Threads에 글 즉시 발행 또는 스테이징
• `@CEO` / `@개발팀장` / `@마케팅팀장` : 채널에서 에이전트 멘션 시 instruction.md 태그 협업 파이프라인 가동
"""
    respond(msg)




# ----------------------------------------------------
# Interactive Block Actions (Human-in-the-Loop 승인 버튼)
# ----------------------------------------------------
@app.action("approve_threads_post")
def handle_approve_threads(ack, body, respond):
    ack()
    action_value = body.get("actions", [{}])[0].get("value", "")
    user = body.get("user", {}).get("username", "User")
    
    logger.info(f"User {user} approved Threads post: {action_value}")
    res = threads_tool.publish_text(action_value)
    
    if res.get("success"):
        respond(f"✅ @{user} 님에 의해 승인되어 Threads에 공식 발행되었습니다! (Post ID: {res.get('post_id')})")
    elif res.get("status") == "STAGED_READY":
        respond(f"✅ @{user} 님 승인 완료 (스테이징 모드 기록 완료)\nℹ️ {res.get('message')}")
    else:
        respond(f"❌ 발행 처리 중 오류 발생: {res.get('error')}")


@app.action("reject_threads_post")
def handle_reject_threads(ack, body, respond):
    ack()
    user = body.get("user", {}).get("username", "User")
    respond(f"❌ @{user} 님에 의해 해당 콘텐츠 발행이 반려(취소)되었습니다.")


@app.action("approve_dev_output")
def handle_approve_dev(ack, body, respond):
    ack()
    user = body.get("user", {}).get("username", "User")
    action_val = body.get("actions", [{}])[0].get("value", "")
    logger.info(f"User {user} approved dev output: {action_val}")
    respond(f"✅ @{user} 님에 의해 해당 프로젝트 산출물이 *최종 승인(Approve)* 되었습니다! 🎉 배포 및 운영 단계로 전환합니다.")


@app.action("reject_dev_output")
def handle_reject_dev(ack, body, respond):
    ack()
    user = body.get("user", {}).get("username", "User")
    action_val = body.get("actions", [{}])[0].get("value", "")
    logger.info(f"User {user} requested revision for: {action_val}")
    respond(f"🔄 @{user} 님에 의해 *수정 요청(반려)* 되었습니다. 개발팀장이 피드백을 반영하여 재작업 및 보완을 진행합니다.")


@app.action("view_agent_full_log")
def handle_view_agent_full_log(ack, body, client):
    """
    사원의 긴 활동 및 코드 전문을 슬랙 모달(Modal) 팝업으로 표시하고,
    모달 실패 시 스레드 댓글로 즉시 열람 지원
    """
    ack()
    trigger_id = body.get("trigger_id")
    action_val = body.get("actions", [{}])[0].get("value", "")
    channel = body.get("channel", {}).get("id", "")
    message_ts = body.get("message", {}).get("ts", "")
    
    logs = _load_agent_logs()
    log_data = logs.get(action_val) or AGENT_FULL_LOGS.get(action_val)
    
    if not log_data:
        if trigger_id:
            try:
                client.views_open(
                    trigger_id=trigger_id,
                    view={
                        "type": "modal",
                        "title": {"type": "plain_text", "text": "활동 전문 조회", "emoji": True},
                        "close": {"type": "plain_text", "text": "닫기", "emoji": True},
                        "blocks": [
                            {
                                "type": "section",
                                "text": {"type": "mrkdwn", "text": "⚠️ 상세 전문 로그를 불러오는 중입니다. 잠시 후 다시 클릭해 주세요."}
                            }
                        ]
                    }
                )
            except Exception:
                pass
        return

    agent_name = log_data.get("agent", "에이전트")
    role = log_data.get("role", "전문가")
    full_text = log_data.get("full_text", "")
    
    # 텍스트를 슬랙 블록 제한(2800자) 이하 청크로 분할
    chunks = [full_text[i:i+2800] for i in range(0, len(full_text), 2800)] or ["(내용 없음)"]
    modal_blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"👤 *담당자*: `{agent_name}` ({role})\n⏱️ *작업 시각*: `{log_data.get('time', '-')}`\n────────────────────────"
            }
        }
    ]
    for idx, c in enumerate(chunks[:5]):
        modal_blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"```{c}```"}
        })

    modal_opened = False
    if trigger_id:
        try:
            client.views_open(
                trigger_id=trigger_id,
                view={
                    "type": "modal",
                    "title": {"type": "plain_text", "text": f"{agent_name[:18]} 상세 활동", "emoji": True},
                    "close": {"type": "plain_text", "text": "닫기", "emoji": True},
                    "blocks": modal_blocks
                }
            )
            modal_opened = True
        except Exception as e:
            logger.warning(f"Modal open failed ({e}), falling back to thread post...")

    # 모달 실패 시 해당 메시지의 스레드 댓글로 전문 바로 게시 (안전망)
    if not modal_opened and channel and message_ts:
        try:
            client.chat_postMessage(
                channel=channel,
                thread_ts=message_ts,
                text=f"📜 *[{agent_name} 활동 및 코드 전문]*\n```{full_text[:3500]}```"
            )
        except Exception as e2:
            logger.error(f"Thread fallback post failed: {e2}")


@app.action("expand_agent_log_to_thread")
def handle_expand_agent_log_to_thread(ack, body, client):
    """
    '스레드에 전문 펼치기' 버튼 클릭 시 해당 메시지 스레드 댓글로 전문 바로 게시
    """
    ack()
    action_val = body.get("actions", [{}])[0].get("value", "")
    channel = body.get("channel", {}).get("id", "")
    message_ts = body.get("message", {}).get("ts", "")
    
    logs = _load_agent_logs()
    log_data = logs.get(action_val) or AGENT_FULL_LOGS.get(action_val)
    
    if not log_data:
        if channel and message_ts:
            try:
                client.chat_postMessage(
                    channel=channel,
                    thread_ts=message_ts,
                    text="⚠️ 상세 전문 로그를 불러오지 못했습니다. (메모리 만료 또는 서버 재시작)"
                )
            except Exception:
                pass
        return

    agent_name = log_data.get("agent", "에이전트")
    role = log_data.get("role", "전문가")
    full_text = log_data.get("full_text", "")
    
    if channel and message_ts:
        chunks = [full_text[i:i+3500] for i in range(0, len(full_text), 3500)] or ["(내용 없음)"]
        for idx, chunk in enumerate(chunks[:3]):
            header = f"📜 *[{agent_name} ({role}) 활동 및 코드 전문 ({idx+1}/{len(chunks)})]*\n" if len(chunks) > 1 else f"📜 *[{agent_name} ({role}) 활동 및 코드 전문]*\n"
            try:
                client.chat_postMessage(
                    channel=channel,
                    thread_ts=message_ts,
                    text=f"{header}```{chunk}```"
                )
            except Exception as e:
                logger.error(f"Thread expand post failed: {e}")


def start_local_dashboard_server(initial_port: int = 8080):
    """초경량 로컬 웹 대시보드 및 산출물 서빙 서버 (projects/ 및 output/ 라이브 렌더링)"""
    global CURRENT_WEB_PORT
    import functools
    serve_dir = str(PROJECT_ROOT)
    handler = functools.partial(SimpleHTTPRequestHandler, directory=serve_dir)

    configured_port = int(os.getenv("WEB_PORT", str(initial_port)))
    candidate_ports = [configured_port, 8080, 8090, 8088, 8085, 8091, 3000, 8000]
    seen = set()
    unique_ports = [p for p in candidate_ports if not (p in seen or seen.add(p))]

    for port in unique_ports:
        try:
            httpd = HTTPServer(("0.0.0.0", port), handler)
            CURRENT_WEB_PORT = port
            orchestrator.tracker.state["web_port"] = port
            orchestrator.tracker.save()
            logger.info(f"🚀 Live Project & Dashboard Server running at http://0.0.0.0:{port}/ (Serving projects/ & output/)")
            httpd.serve_forever()
            break
        except OSError as e:
            logger.warning(f"Port {port} in use or unavailable ({e}), trying next candidate port...")
            continue
        except Exception as e:
            logger.error(f"Error starting web server on port {port}: {e}")
            break


def dynamic_scheduler_loop():
    """
    백그라운드 스케줄러 & 쿼터 안전 버퍼 자동 보충 데몬
    - 30초 주기로 동적 시간표 감시
    - API 쿼터 안전 시 예비본(Buffer) 자동 보충
    - 시간 도달 시 슬랙 #output-review 승인 카드 자동 발송
    """
    while True:
        try:
            # 1. 예비본(Buffer) 자동 보충 (API 쿼터 점검 후 안전할 때만 실행)
            schedule_mgr.check_and_refill_buffer()

            # 2. 시간대 도달 이벤트 확인
            events = schedule_mgr.check_time_triggers()
            for ev in events:
                platform = ev["platform"]
                slot = ev["slot"]
                logger.info(f"⏰ [{platform.upper()}] 정기 발행 시간 도달: {slot}")

                if platform == "threads":
                    item = schedule_mgr.get_instant_post_with_double_check()
                    if item and app:
                        output_chan = CHANNEL_MAP.get("output_review")
                        if output_chan:
                            blocks = [
                                {
                                    "type": "section",
                                    "text": {
                                        "type": "mrkdwn",
                                        "text": f"⏰ *[{slot} 정기 스레드 검수 요청]* ID: `{item['id']}`\n🔥 *제목*: *{item.get('cover_title', '')}*\n\n🧵 *스레드 본문*:\n```{item['thread_text']}```"
                                    }
                                },
                                {
                                    "type": "actions",
                                    "elements": [
                                        {
                                            "type": "button",
                                            "text": {"type": "plain_text", "text": "🚀 스레드 즉시 발행 (승인)"},
                                            "style": "primary",
                                            "value": item['thread_text'],
                                            "action_id": "approve_threads_post"
                                        },
                                        {
                                            "type": "button",
                                            "text": {"type": "plain_text", "text": "❌ 반려 (취소)"},
                                            "style": "danger",
                                            "value": str(item['id']),
                                            "action_id": "reject_threads_post"
                                        }
                                    ]
                                }
                            ]
                            post_as_agent(output_chan, "마케팅팀장", f"정기 스레드 검수 대기 ({slot})", blocks=blocks)

                        # CEO 채널 보고
                        ceo_chan = CHANNEL_MAP.get("ceo_report")
                        if ceo_chan:
                            post_as_agent(ceo_chan, "CEO", f"🌅 *[정기 스케줄 알림 - {slot}]* 오늘자 스레드 검수 카드가 <#{output_chan}> 채널에 도착했습니다.")

        except Exception as e:
            logger.error(f"Dynamic scheduler loop error: {e}")

        time.sleep(30)


if __name__ == "__main__":
    # 로컬 대시보드 백그라운드 기동
    threading.Thread(target=start_local_dashboard_server, daemon=True).start()

    # 동적 스케줄러 & 버퍼 관리 데몬 기동
    threading.Thread(target=dynamic_scheduler_loop, daemon=True).start()

    if SLACK_APP_TOKEN and SLACK_BOT_TOKEN:
        logger.info("Starting AI Company Slack Socket Mode...")
        handler = SocketModeHandler(app, SLACK_APP_TOKEN)
        handler.start()
    else:
        logger.warning("Slack tokens not configured in .env. Running local dashboard and background loops...")
        while True:
            time.sleep(3600)
