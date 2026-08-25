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

    # 1. 깃 최신화 (안전한 fetch & reset --hard)
    try:
        subprocess.run(["git", "fetch", "origin", "main"], capture_output=True, text=True, timeout=20)
        reset_res = subprocess.run(["git", "reset", "--hard", "origin/main"], capture_output=True, text=True, timeout=20)
        logger.info(f"Git Reset Output: {reset_res.stdout.strip()}")
        if reset_res.returncode != 0:
            logger.error(f"Git Reset Failed: {reset_res.stderr}")
            return False, f"Git Reset 실패: {reset_res.stderr.strip()}"
    except Exception as e:
        logger.error(f"Git pull error: {e}")
        return False, str(e)

    # 2. 최신 커밋 해시 및 메시지 추출
    try:
        log_res = subprocess.run(["git", "log", "-1", "--pretty=format:%h - %s"], capture_output=True, text=True, timeout=10)
        latest_commit = log_res.stdout.strip()
    except Exception:
        latest_commit = "최신 커밋 정보 확인 불가"

    py_exec = sys.executable or "python3"
    restart_script = f"""
sleep 2
pkill -9 -f "ai_company.main" || true
pkill -9 -f "python3 -u main.py" || true
pkill -9 -f "main.py" || true
cd "{PROJECT_ROOT}"
nohup {py_exec} -u main.py > agent.log 2>&1 &
"""
    subprocess.Popen(["bash", "-c", restart_script], start_new_session=True)
    
    return True, latest_commit

if __name__ == "__main__":
    success, msg = run_self_update()
    print(f"Update Result: {success} -> {msg}")
