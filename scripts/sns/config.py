import os
import logging
import time
from pathlib import Path
from typing import Optional, Tuple
from dotenv import load_dotenv

logger = logging.getLogger("KeyPool")

# Search and load .env files
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
env_candidates = [
    PROJECT_ROOT / ".env",
    PROJECT_ROOT / "ai_company" / ".env",
]

for env_path in env_candidates:
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False)

# ==============================================================================
# 1. API Keys (1, 2, 3 분할 및 역할별 할당)
# ==============================================================================
GEMINI_API_KEY_1 = os.getenv("GEMINI_API_KEY_1", "").strip()  # 기본: CEO 전용
GEMINI_API_KEY_2 = os.getenv("GEMINI_API_KEY_2", "").strip()  # 기본: 팀장 & 개발직원 전용
GEMINI_API_KEY_3 = os.getenv("GEMINI_API_KEY_3", "").strip()  # 기본: 마케팅 & SNS 실무사원 전용

# 폴백 공통 키
DEFAULT_GEMINI_KEY = (
    os.getenv("GEMINI_API_KEY")
    or os.getenv("GOOGLE_API_KEY", "")
).strip()

# ==============================================================================
# 2. 직급별 Gemini 모델 버전 설정 (3.6 / 3.5-lite 지원 및 공식 API 명칭 자동 매핑)
# ==============================================================================
MODEL_CEO = os.getenv("MODEL_CEO", "3.6").strip()
MODEL_MANAGER = os.getenv("MODEL_MANAGER", "3.6").strip()
MODEL_WORKER = os.getenv("MODEL_WORKER", "3.6").strip()

def normalize_model_name(raw_name: str, fallback: str = "gemini-2.5-flash") -> str:
    """
    사용자 친화적 버전 표기(3.6, 3.5 등)를 Google Gemini 공식 API 엔드포인트명으로 자동 변환
    - '3.6' / '3.6 flash' / '3.7' -> 'gemini-2.5-flash' (최신 고성능 Flash - 카피라이팅/Whisk 프롬프트 최적)
    - '3.5-lite' / '3.5 lite'     -> 'gemini-2.0-flash-lite' (초경량 초고속 Flash-Lite)
    - '3.5' / '3.5 flash'          -> 'gemini-2.0-flash' (표준 고속 Flash)
    """
    raw = (raw_name or "").strip().lower()
    if not raw:
        return fallback
    if raw in ("3.5-lite", "3.5 lite", "3.5_lite", "lite", "gemini-3.5-lite", "gemini-2.0-flash-lite", "flash-lite"):
        return "gemini-2.0-flash-lite"
    elif raw in ("3.6", "3.6 flash", "3.6-flash", "3.7", "3.7 flash", "gemini-3.6", "gemini-3.6-flash", "gemini-2.5-flash"):
        return "gemini-2.5-flash"
    elif raw in ("3.5", "3.5 flash", "3.5-flash", "gemini-3.5", "gemini-3.5-flash", "gemini-2.0-flash"):
        return "gemini-2.0-flash"
    elif not raw.startswith("gemini-"):
        return f"gemini-{raw}"
    return raw

def get_gemini_model(role: str = "worker") -> str:
    """역할에 맞는 공식 Gemini 모델 버전 반환"""
    role = role.lower()
    if role in ("ceo", "executive"):
        return normalize_model_name(MODEL_CEO, "gemini-2.5-flash")
    elif role in ("manager", "lead", "팀장", "verifier", "dev", "개발사원", "개발_사원", "developer"):
        return normalize_model_name(MODEL_MANAGER, "gemini-2.5-flash")
    else:  # worker, 사원, scout, 마케팅, sns
        return normalize_model_name(MODEL_WORKER, "gemini-2.5-flash")

GEMINI_MODEL = get_gemini_model("worker")

# ==============================================================================
# 3. ⏱️ Rate Limit (RPM / RPD) 속도 제어기 (429 방지 안전 딜레이)
# ==============================================================================
# 3.6/3.7:    RPM 5  -> 요청 간 최소 12.5초 간격
# 3.5-lite:   RPM 30 -> 요청 간 최소 2.5초 간격
# 3.5-flash:  RPM 15 -> 요청 간 최소 4.5초 간격
def get_safe_delay(role: str = "worker") -> float:
    model_name = get_gemini_model(role)
    if "lite" in model_name:
        return 2.5   # 30 RPM 초고속 안전 딜레이
    elif "2.5" in model_name or "3.6" in model_name or "3.7" in model_name:
        return 12.5  # 5 RPM 안전 딜레이
    else:
        return 4.5   # 15 RPM 안전 딜레이

# ==============================================================================
# 4. 🛡️ KeyPoolManager (스마트 폴백 및 CEO 20% 쿼터 보호 방어선)
# ==============================================================================
class KeyPoolManager:
    """
    3.6 모델(RPD 20) 및 3.5-lite 모델(RPD 1500)의 한도를 고려하여
    실무사원이 한도 초과 시 CEO 키를 최대 80%까지만 스마트 차용하고
    CEO 고유 업무를 위한 20%는 무조건 보존하는 매니저
    """
    def __init__(self):
        self.borrowed_from_ceo_count = 0
        self.enable_ceo_fallback = os.getenv("ENABLE_CEO_KEY_FALLBACK", "true").lower() in ("true", "1", "yes")
        self.ceo_max_borrow_percent = int(os.getenv("CEO_KEY_MAX_BORROW_PERCENT", "80"))
        # RPD 20 기준: 20 * 0.8 = 16회 대여, 4회(20%)는 CEO 전용 보존
        self.daily_ceo_limit = int(os.getenv("DAILY_CEO_KEY_LIMIT", "20"))
        self.max_borrow_calls = max(1, int(self.daily_ceo_limit * (self.ceo_max_borrow_percent / 100.0)))

    def get_initial_key(self, role: str = "worker") -> Tuple[str, str]:
        role = role.lower()
        if role in ("ceo", "executive"):
            key = os.environ.get("GEMINI_API_KEY_1", GEMINI_API_KEY_1) or os.environ.get("GEMINI_API_KEY_CEO", "").strip() or os.environ.get("GEMINI_API_KEY", DEFAULT_GEMINI_KEY)
            return key, "Key 1 (CEO)"
        elif role in ("manager", "lead", "팀장", "verifier", "dev", "개발사원", "개발_사원", "developer"):
            key = os.environ.get("GEMINI_API_KEY_2", GEMINI_API_KEY_2) or os.environ.get("GEMINI_API_KEY_DEV", "").strip() or os.environ.get("GEMINI_API_KEY_MARKETING", "").strip() or os.environ.get("GEMINI_API_KEY", DEFAULT_GEMINI_KEY)
            return key, "Key 2 (팀장/개발)"
        else:
            key = os.environ.get("GEMINI_API_KEY_3", GEMINI_API_KEY_3) or os.environ.get("GEMINI_API_KEY_MEDIA", "").strip() or os.environ.get("GEMINI_API_KEY", DEFAULT_GEMINI_KEY)
            return key, "Key 3 (실무사원)"

    def get_fallback_key(self, role: str = "worker") -> Tuple[Optional[str], str]:
        """Key 3 한도 도달 시 CEO Key 1 스마트 차용 (20% 예비분 보존 검사)"""
        if not self.enable_ceo_fallback:
            logger.warning("[Quota Shield] CEO 키 폴백이 비활성화되어 있습니다.")
            return None, "폴백 비활성화"

        # 1. 1차 폴백: 팀장/개발 키(Key 2) 여유 시도
        team_key = (os.environ.get("GEMINI_API_KEY_2", GEMINI_API_KEY_2) or os.environ.get("GEMINI_API_KEY_DEV", "")).strip()
        worker_key = (os.environ.get("GEMINI_API_KEY_3", GEMINI_API_KEY_3) or os.environ.get("GEMINI_API_KEY_MEDIA", "")).strip()
        if team_key and team_key != worker_key:
            logger.info("[Quota Shield] Key 3 한도 초과 -> Key 2(팀장/개발)로 1차 폴백 전환")
            return team_key, "Key 2 (팀장/개발 1차 폴백)"

        # 2. 2차 폴백: CEO 키(Key 1) 스마트 차용
        ceo_key = (os.environ.get("GEMINI_API_KEY_1", GEMINI_API_KEY_1) or os.environ.get("GEMINI_API_KEY_CEO", "") or os.environ.get("GEMINI_API_KEY", DEFAULT_GEMINI_KEY)).strip()
        if not ceo_key:
            return None, "사용 가능한 CEO 키 없음"

        if self.borrowed_from_ceo_count < self.max_borrow_calls:
            self.borrowed_from_ceo_count += 1
            remaining_borrow = self.max_borrow_calls - self.borrowed_from_ceo_count
            logger.warning(
                f"[Quota Shield] 🚨 Key 3 한도 초과! CEO Key(Key 1) 스마트 차용 승인 "
                f"(차용 누적: {self.borrowed_from_ceo_count}/{self.max_borrow_calls}회, CEO 20% 안전 비축분 보존 중)"
            )
            return ceo_key, "Key 1 (CEO 스마트 차용 - 20% 보존)"
        else:
            logger.error(
                f"[Quota Shield] 🛑 CEO 키의 안전 차용 한도({self.ceo_max_borrow_percent}%, {self.max_borrow_calls}회)에 도달했습니다. "
                "CEO의 정상 업무 보장을 위해 추가 차용을 차단합니다 (20% 비축분 보호)."
            )
            return None, "CEO 20% 안전 비축분 보호로 차용 차단"

# 글로벌 인스턴스
key_pool = KeyPoolManager()

def get_gemini_key(role: str = "worker") -> str:
    key, _ = key_pool.get_initial_key(role)
    return key

# 하위 호환용 기본 키
GEMINI_API_KEY = get_gemini_key("worker")

# Tavily & Jina
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()
JINA_API_KEY = os.getenv("JINA_API_KEY", "").strip()

# Meta Threads API
THREADS_USER_ID = os.getenv("THREADS_USER_ID", "").strip()
THREADS_ACCESS_TOKEN = os.getenv("THREADS_ACCESS_TOKEN", "").strip()

# 기본 일일 생성 수량 (안전 웜업 기본 3개)
DEFAULT_DAILY_CONTENT_COUNT = int(os.getenv("DEFAULT_DAILY_CONTENT_COUNT", "3"))

# ==============================================================================
# 5. 디렉토리 설정
# ==============================================================================
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_DB_PATH = DATA_DIR / "sns_queue.db"

OUTPUT_DIR = PROJECT_ROOT / "output" / "sns"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
