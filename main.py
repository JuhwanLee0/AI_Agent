"""
1인 AI 비즈니스 OS - 통합 엔트리포인트 (Master Entry Point)

GCP 24시간 무중단 백그라운드 구동 명령어:
nohup python3 -u main.py > agent.log 2>&1 &
"""

import os
import sys
import threading
import time
import logging

# 1. 프로젝트 루트 및 모듈 경로 등록
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
AI_COMPANY_DIR = os.path.join(ROOT_DIR, "ai_company")

if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
if AI_COMPANY_DIR not in sys.path:
    sys.path.insert(0, AI_COMPANY_DIR)

from ai_company.main import (
    app,
    SLACK_APP_TOKEN,
    SLACK_BOT_TOKEN,
    SocketModeHandler,
    start_local_dashboard_server,
    dynamic_scheduler_loop
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AICompanyMaster")

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 1인 AI 비즈니스 OS 에이전트 시스템 가동")
    print(f"📍 프로젝트 루트: {ROOT_DIR}")
    print("🛡️ 지능 스택: Headroom + Claude-Mem + GSD + Graphify + Ponytail")
    print("⏱️ 기능: 동적 스케줄링 + 쿼터 안전 버퍼 풀 + Slack Socket Mode")
    print("=" * 60)

    # 1. 로컬 모니터링 웹 대시보드 기동 (포트 8080)
    threading.Thread(target=start_local_dashboard_server, daemon=True).start()

    # 2. 동적 스케줄러 & 쿼터 안전 버퍼 자동 보충 데몬 기동
    threading.Thread(target=dynamic_scheduler_loop, daemon=True).start()

    # 3. Slack Socket Mode 리스너 구동
    if SLACK_APP_TOKEN and SLACK_BOT_TOKEN:
        logger.info("Starting Slack Socket Mode Handler...")
        handler = SocketModeHandler(app, SLACK_APP_TOKEN)
        handler.start()
    else:
        logger.warning("SLACK_BOT_TOKEN 또는 SLACK_APP_TOKEN이 .env에 없습니다. 로컬 데몬 모드로 대기합니다.")
        while True:
            time.sleep(3600)
