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

    # 1. git pull 실행
    try:
        pull_res = subprocess.run(["git", "pull", "origin", "main"], capture_output=True, text=True, timeout=30)
        logger.info(f"Git Pull Output: {pull_res.stdout.strip()}")
        if pull_res.returncode != 0:
            logger.error(f"Git Pull Failed: {pull_res.stderr}")
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

    # 3. 백그라운드 재부팅 스크립트 비동기 실행
    restart_script = f"""
sleep 1
pkill -f main.py
cd {PROJECT_ROOT}
nohup python3 -u main.py > agent.log 2>&1 &
"""
    subprocess.Popen(["bash", "-c", restart_script], start_new_session=True)
    
    return True, latest_commit

if __name__ == "__main__":
    success, msg = run_self_update()
    print(f"Update Result: {success} -> {msg}")
