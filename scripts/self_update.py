"""
AI Company - Self Updater Script
Triggered by Slack command (/ai-update) to autonomously pull from Git and restart background daemon.
"""

import os
import sys
import subprocess
import time
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SelfUpdater")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def run_self_update():
    logger.info(f"Starting self-update in directory: {PROJECT_ROOT}")
    os.chdir(PROJECT_ROOT)

    # 1. 런타임 파일 충돌 방지: git stash & pull
    try:
        # 런타임에 변경될 수 있는 상태 파일들을 안전하게 임시 보관
        subprocess.run(["git", "stash", "--include-untracked"], capture_output=True, text=True, timeout=15)
        pull_res = subprocess.run(["git", "pull", "origin", "main"], capture_output=True, text=True, timeout=30)
        logger.info(f"Git Pull Output: {pull_res.stdout.strip()}")
        if pull_res.returncode != 0:
            # 강제 리셋 후 최신 main으로 맞춤 시도 (최후의 안전망)
            subprocess.run(["git", "fetch", "origin", "main"], capture_output=True, text=True, timeout=15)
            reset_res = subprocess.run(["git", "reset", "--hard", "origin/main"], capture_output=True, text=True, timeout=15)
            if reset_res.returncode != 0:
                logger.error(f"Git Pull & Reset Failed: {pull_res.stderr}")
                return False, f"Git Pull 실패: {pull_res.stderr.strip()}"
    except Exception as e:
        logger.error(f"Git pull error: {e}")
        return False, str(e)

    # 2. 최신 커밋 해시 및 메시지 추출
    try:
        log_res = subprocess.run(["git", "log", "-1", "--pretty=format:%h - %s"], capture_output=True, text=True, timeout=10)
        latest_commit = log_res.stdout.strip()
    except Exception:
        latest_commit = "최신 커밋 정보 확인 불가"

    restart_script = f"""
sleep 1
pkill -f "ai_company.main" || true
pkill -f "main.py" || true
cd "{PROJECT_ROOT}"
nohup python3 -u main.py > agent.log 2>&1 &
"""
    subprocess.Popen(["bash", "-c", restart_script], start_new_session=True)
    
    return True, latest_commit

if __name__ == "__main__":
    success, msg = run_self_update()
    print(f"Update Result: {success} -> {msg}")
