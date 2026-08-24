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
# 1. API Keys (Cerebras & Groq 듀얼 클라우드)
# ==============================================================================
CEREBRAS_API_KEY = (os.getenv("CEREBRAS_API_KEY_1") or os.getenv("CEREBRAS_API_KEY", "")).strip()
GROQ_API_KEY = (os.getenv("GROQ_API_KEY_1") or os.getenv("GROQ_API_KEY", "")).strip()

# ==============================================================================
# 2. 직급별 모델 설정 (Groq 27B / 120B / 20B 듀얼 클라우드)
# ==============================================================================
def normalize_model_name(model_str: str, default: str = "openai/gpt-oss-20b") -> str:
    if not model_str:
        return default
    if model_str.startswith("groq/"):
        return model_str.replace("groq/", "")
    if model_str.startswith("cerebras/"):
        return model_str.replace("cerebras/", "")
    return model_str

MODEL_CEO = os.getenv("MODEL_CEO", "groq/openai/gpt-oss-120b").strip()
MODEL_MANAGER = os.getenv("MODEL_MANAGER", "groq/openai/gpt-oss-120b").strip()
MODEL_WORKER = os.getenv("MODEL_WORKER", "groq/openai/gpt-oss-20b").strip()

# Fallback & Legacy Keys for backward compatibility
GEMINI_API_KEY_1 = os.getenv("GEMINI_API_KEY_1", "").strip()
GEMINI_API_KEY_2 = os.getenv("GEMINI_API_KEY_2", "").strip()
GEMINI_API_KEY_3 = os.getenv("GEMINI_API_KEY_3", "").strip()
DEFAULT_GEMINI_KEY = os.getenv("GEMINI_API_KEY", "").strip()

def get_role_model(role: str = "worker") -> str:
    """역할에 맞는 공식 AI 모델 버전 반환"""
    role = role.lower()
    if role in ("ceo", "executive"):
        return normalize_model_name(MODEL_CEO, "openai/gpt-oss-120b")
    elif role in ("manager", "lead", "팀장", "verifier", "dev", "개발사원", "개발_사원", "developer"):
        return normalize_model_name(MODEL_MANAGER, "openai/gpt-oss-120b")
    else:  # worker, 사원, scout, 마케팅, sns
        return normalize_model_name(MODEL_WORKER, "openai/gpt-oss-20b")

def get_gemini_model(role: str = "worker") -> str:
    """하위 호환용 모델 반환 함수"""
    return get_role_model(role)

AI_MODEL = get_role_model("worker")
GEMINI_MODEL = AI_MODEL


# ==============================================================================
# 3. ⏱️ Rate Limit (RPM / RPD) 속도 제어기 (429 방지 안전 딜레이)
# ==============================================================================
# Groq 30 RPM -> 요청 간 최소 2.0초 간격
# 복잡한 모델(27B/120B) -> 요청 간 최소 3.0초 간격
def get_safe_delay(role: str = "worker") -> float:
    model_name = get_role_model(role)
    if "20b" in model_name or "mini" in model_name or "lite" in model_name:
        return 1.5   # 30 RPM 초고속 안전 딜레이
    elif "120b" in model_name or "27b" in model_name or "3.6" in model_name:
        return 3.0   # 고성능 모델 안전 딜레이
    else:
        return 2.0

# ==============================================================================
# 4. 🛡️ KeyPoolManager (스마트 폴백 및 CEO 20% 쿼터 보호 방어선)
# ==============================================================================
class KeyPoolManager:
    """
    Groq/Cerebras 및 다중 키 한도를 고려하여
    실무사원이 한도 초과 시 CEO 키를 최대 80%까지만 스마트 차용하고
    CEO 고유 업무를 위한 20%는 무조건 보존하는 매니저
    """
    def __init__(self):
        self.borrowed_from_ceo_count = 0
        self.enable_ceo_fallback = os.getenv("ENABLE_CEO_KEY_FALLBACK", "true").lower() in ("true", "1", "yes")
        self.ceo_max_borrow_percent = int(os.getenv("CEO_KEY_MAX_BORROW_PERCENT", "80"))
        self.daily_ceo_limit = int(os.getenv("DAILY_GROQ_LIMIT", os.getenv("DAILY_CEO_KEY_LIMIT", "100")))
        self.max_borrow_calls = max(1, int(self.daily_ceo_limit * (self.ceo_max_borrow_percent / 100.0)))

    def get_initial_key(self, role: str = "worker") -> Tuple[str, str]:
        role = role.lower()
        if role in ("ceo", "executive"):
            key = (
                os.environ.get("GROQ_API_KEY_1") or os.environ.get("CEREBRAS_API_KEY_1") or
                os.environ.get("GEMINI_API_KEY_1", GEMINI_API_KEY_1) or
                os.environ.get("GROQ_API_KEY", GROQ_API_KEY) or os.environ.get("GEMINI_API_KEY", DEFAULT_GEMINI_KEY)
            )
            return (key or "").strip(), "Key 1 (CEO)"
        elif role in ("manager", "lead", "팀장", "verifier", "dev", "개발사원", "개발_사원", "developer"):
            key = (
                os.environ.get("GROQ_API_KEY_2") or os.environ.get("CEREBRAS_API_KEY_2") or
                os.environ.get("GEMINI_API_KEY_2", GEMINI_API_KEY_2) or
                os.environ.get("GROQ_API_KEY", GROQ_API_KEY) or os.environ.get("GEMINI_API_KEY", DEFAULT_GEMINI_KEY)
            )
            return (key or "").strip(), "Key 2 (팀장/개발)"
        else:
            key = (
                os.environ.get("GROQ_API_KEY_3") or os.environ.get("CEREBRAS_API_KEY_3") or
                os.environ.get("GEMINI_API_KEY_3", GEMINI_API_KEY_3) or
                os.environ.get("GROQ_API_KEY", GROQ_API_KEY) or os.environ.get("GEMINI_API_KEY", DEFAULT_GEMINI_KEY)
            )
            return (key or "").strip(), "Key 3 (실무사원)"

    def get_fallback_key(self, role: str = "worker") -> Tuple[Optional[str], str]:
        """Key 3 한도 도달 시 CEO Key 1 스마트 차용 (20% 예비분 보존 검사)"""
        if not self.enable_ceo_fallback:
            logger.warning("[Quota Shield] CEO 키 폴백이 비활성화되어 있습니다.")
            return None, "폴백 비활성화"

        # 1. 1차 폴백: 팀장/개발 키(Key 2) 여유 시도
        team_key = (
            os.environ.get("GROQ_API_KEY_2") or os.environ.get("CEREBRAS_API_KEY_2") or
            os.environ.get("GEMINI_API_KEY_2", GEMINI_API_KEY_2)
        )
        worker_key = (
            os.environ.get("GROQ_API_KEY_3") or os.environ.get("CEREBRAS_API_KEY_3") or
            os.environ.get("GEMINI_API_KEY_3", GEMINI_API_KEY_3)
        )
        if team_key and team_key != worker_key:
            logger.info("[Quota Shield] Key 3 한도 초과 -> Key 2(팀장/개발)로 1차 폴백 전환")
            return team_key.strip(), "Key 2 (팀장/개발 1차 폴백)"

        # 2. 2차 폴백: CEO 키(Key 1) 스마트 차용
        ceo_key = (
            os.environ.get("GROQ_API_KEY_1") or os.environ.get("CEREBRAS_API_KEY_1") or
            os.environ.get("GEMINI_API_KEY_1", GEMINI_API_KEY_1) or
            os.environ.get("GROQ_API_KEY", GROQ_API_KEY) or os.environ.get("GEMINI_API_KEY", DEFAULT_GEMINI_KEY)
        )
        if not ceo_key:
            return None, "사용 가능한 CEO 키 없음"

        ceo_key = ceo_key.strip()
        if self.borrowed_from_ceo_count < self.max_borrow_calls:
            self.borrowed_from_ceo_count += 1
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

    def get_available_key(self, role: str = "worker") -> Tuple[Optional[str], str]:
        key, _ = self.get_initial_key(role)
        if not key:
            key, _ = self.get_fallback_key(role)
        model_name = get_role_model(role)
        return key, model_name

# 글로벌 인스턴스
key_pool = KeyPoolManager()

def get_role_key(role: str = "worker") -> str:
    key, _ = key_pool.get_initial_key(role)
    return key or ""

def get_gemini_key(role: str = "worker") -> str:
    return get_role_key(role)

# 하위 호환용 기본 키
GEMINI_API_KEY = get_role_key("worker")

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
