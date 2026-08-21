import os
import re
import sys
import time
import logging
import threading
from pathlib import Path
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

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AICompanyApp")

# Slack App 초기화
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")

if not SLACK_BOT_TOKEN or not SLACK_APP_TOKEN:
    logger.warning("SLACK_BOT_TOKEN 또는 SLACK_APP_TOKEN이 .env에 설정되지 않았습니다.")

app = App(token=SLACK_BOT_TOKEN)
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

def post_as_agent(channel: str, agent_name: str, text: str, thread_ts: str = None, blocks: list = None):
    """
    특정 에이전트의 페르소나(이름 및 아이콘)로 슬랙에 메시지 전송
    """
    if not channel:
        logger.warning(f"No target channel provided for agent message ({agent_name})")
        return

    config = AGENTS.get(agent_name)
    username = f"{agent_name} ({config.role})" if config else agent_name
    icon_emoji = f":{config.avatar_name}:" if config else ":robot_face:"

    try:
        kwargs = {
            "channel": channel,
            "text": text,
            "username": username,
            "icon_emoji": icon_emoji,
        }
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
        if blocks:
            kwargs["blocks"] = blocks

        app.client.chat_postMessage(**kwargs)
    except Exception as e:
        logger.error(f"Failed to post message as {agent_name}: {e}")

def run_pipeline(initial_agent: str, user_prompt: str, channel: str, thread_ts: str):
    """
    위계형 다중 에이전트 협업 파이프라인 실행 (instruction.md 태그 인수인계 준수)
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

    current_agent = initial_agent
    current_message = user_prompt
    history = [{"role": "user", "content": user_prompt}]
    max_hops = 10
    hop = 0

    orchestrator.tracker.state["current_project"] = user_prompt[:40] + "..."
    orchestrator.tracker.save()

    while current_agent and hop < max_hops:
        hop += 1
        logger.info(f"Step {hop}: Running Agent -> {current_agent}")
        
        # 상태 업데이트 (진행중)
        orchestrator.tracker.update_agent(
            agent_name=current_agent,
            status="진행중",
            task=current_message[:50] + "...",
            progress=int((hop / 6) * 100) if hop <= 6 else 95
        )

        # LLM 호출 및 도구 실행
        response = orchestrator.call_agent_llm(current_agent, history)
        
        # 슬랙에 에이전트 페르소나로 회신
        post_as_agent(channel, current_agent, response, thread_ts)

        # 상태 업데이트 (완료)
        orchestrator.tracker.update_agent(
            agent_name=current_agent,
            status="완료",
            task="인수인계 완료"
        )

        # 대화 히스토리 누적
        history.append({"role": "assistant", "content": f"[{current_agent}]: {response}"})

        # 다음 에이전트 태그 탐지 (@다음에이전트)
        next_agent = orchestrator.parse_next_agent(response)
        if next_agent and next_agent != current_agent:
            current_agent = next_agent
            current_message = response
            time.sleep(1) # 부드러운 스레드 연결을 위한 짧은 대기
        else:
            logger.info("Pipeline completed or no further agent tagged.")
            break

    orchestrator.tracker.state["progress_percent"] = 100
    orchestrator.tracker.state["active_agent"] = "None"
    orchestrator.tracker.save()


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
# 슬래시 커맨드 (Slash Commands)
# ----------------------------------------------------
@app.command("/status")
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
def handle_schedule_command(ack, respond, command):
    """
    /schedule : 현재 스케줄 확인
    /schedule set threads 09:00,18:30
    /schedule set youtube 20:00
    /schedule set buffer 3
    """
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


@app.command("/help")
def handle_help_command(ack, respond, command):
    ack()
    msg = """
🤖 *1인 AI 비즈니스 OS 슬랙 명령어 안내*
• `/status` : 전체 에이전트 상태, GSD 마일스톤, 콘텐츠 버퍼 현황 확인
• `/schedule` : 동적 발행 시간대 및 버퍼 수량 조회 및 실시간 변경
• `/instant` : 팩트 2차 재검증된 예비 스레드 1초 즉시 인출 및 승인 요청
• `/browse <URL>` : Playwright 브라우저로 웹페이지 내용 실시간 스크래핑
• `/threads <내용>` : Threads에 글 즉시 발행 또는 스테이징
• `@CEO` / `@개발팀장` / `@마케팅팀장` : 채널에서 에이전트 멘션 시 `instruction.md` 태그 협업 파이프라인 가동
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


def start_local_dashboard_server(port: int = 8080):
    """초경량 로컬 웹 대시보드 서버"""
    os.chdir(str(PROJECT_ROOT / "ai_company"))
    handler = SimpleHTTPRequestHandler
    try:
        httpd = HTTPServer(("0.0.0.0", port), handler)
        logger.info(f"Local Dashboard running at http://localhost:{port}/web/")
        httpd.serve_forever()
    except Exception as e:
        logger.warning(f"Could not start local web dashboard: {e}")


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
