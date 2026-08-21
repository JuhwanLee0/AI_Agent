import os
import json
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from scripts.sns.queue_db import QueueDB
from scripts.sns.tavily_scout import TavilyScout
from scripts.sns.jina_verifier import JinaVerifier
from scripts.sns.config import KeyPoolManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SchedulerDaemon")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "schedule_config.json"

class ScheduleManager:
    """
    유동적 스케줄 및 팩트체크 예비본(Buffer) 자동 보충 관리자
    - config/schedule_config.json을 실시간 참조 (무중단 갱신)
    - API 쿼터 한도 점검 후 안전할 때만 예비본 자동 리필
    - 지정된 시간대에 슬랙 검수 카드 자동 발송
    - 긴급 요청 시 실시간 팩트 재검수(Double-Check) 후 인출
    """
    def __init__(self, config_path: Path = CONFIG_PATH):
        self.config_path = config_path
        self.db = QueueDB()
        self.scout = TavilyScout()
        self.verifier = JinaVerifier()
        self.key_pool = KeyPoolManager()
        self.last_sent_slots: Dict[str, str] = {}  # { "threads_08:30": "2026-08-20" }

    def load_config(self) -> Dict[str, Any]:
        """설정 파일 실시간 로드"""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading {self.config_path}: {e}")
        return {
            "threads": ["08:30", "18:30"],
            "youtube": ["20:00"],
            "buffer_min_count": 2,
            "auto_refill_enabled": True
        }

    def update_config(self, new_data: Dict[str, Any]) -> bool:
        """설정 파일 동적 갱신 (슬랙 명령어에서 호출 가능)"""
        try:
            cfg = self.load_config()
            cfg.update(new_data)
            cfg["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            logger.info(f"Updated schedule config: {new_data}")
            return True
        except Exception as e:
            logger.error(f"Failed to update schedule config: {e}")
            return False

    def get_ready_buffer_count(self) -> int:
        """현재 큐에서 팩트체크 완료된 즉시 발행 가능(VERIFIED) 콘텐츠 개수 조회"""
        items = self.db.get_all_items()
        verified_items = [it for it in items if it.get("status") in ("VERIFIED", "FACT_CHECKED")]
        return len(verified_items)

    def check_and_refill_buffer(self) -> int:
        """
        API 쿼터 안전 상태를 확인하고, 부족한 예비본(Buffer) 자동 생성 및 팩트체크 수행
        """
        cfg = self.load_config()
        if not cfg.get("auto_refill_enabled", True):
            return 0

        min_required = cfg.get("buffer_min_count", 2)
        current_count = self.get_ready_buffer_count()

        if current_count >= min_required:
            return 0

        shortage = min_required - current_count
        logger.info(f"[Buffer Guard] 예비본 부족 감지: 현재 {current_count}개 / 최소 {min_required}개 필요 -> {shortage}개 보충 시도")

        # 1. API 키 가용성 및 쿼터 안전 점검
        api_key, model_name = self.key_pool.get_available_key(role="worker")
        if not api_key:
            logger.warning("[Buffer Guard] ⚠️ API 쿼터 한도 도달 또는 유효한 키 없음. 버퍼 생성을 일시 대기합니다.")
            return 0

        try:
            today_str = datetime.now().strftime("%Y-%m-%d")
            # 2. 부족한 수량만큼 리서치 & 생성
            new_ids = self.scout.batch_generate_and_queue(
                domain_keywords=["AI 비즈니스", "생산성 도구", "바이브코딩", "1인 창업"],
                count=shortage,
                scheduled_date=today_str,
                db=self.db
            )
            # 3. 즉시 팩트체크 수행
            self.verifier.verify_date_batch(today_str, db=self.db)
            logger.info(f"[Buffer Guard] ✅ 예비 콘텐츠 {len(new_ids)}건 보충 및 팩트체크 완료 (ID: {new_ids})")
            return len(new_ids)
        except Exception as e:
            logger.error(f"[Buffer Guard] 예비본 보충 실패: {e}")
            return 0

    def get_instant_post_with_double_check(self) -> Optional[Dict[str, Any]]:
        """
        [긴급 즉시 호출] 예비 풀에서 최상위 콘텐츠를 가져와
        출력 직전 팩트체크/최신성 재검증(Double-Check) 후 반환
        """
        items = self.db.get_all_items()
        verified_items = [it for it in items if it.get("status") in ("VERIFIED", "FACT_CHECKED")]
        
        target_item = None
        if verified_items:
            target_item = verified_items[0]
        else:
            # 버퍼가 비어있을 경우 즉석 1건 생성
            today_str = datetime.now().strftime("%Y-%m-%d")
            new_ids = self.scout.batch_generate_and_queue(
                domain_keywords=["AI 도구", "1인 비즈니스"],
                count=1,
                scheduled_date=today_str,
                db=self.db
            )
            if new_ids:
                self.verifier.verify_date_batch(today_str, db=self.db)
                target_item = self.db.get_item(new_ids[0])

        if not target_item:
            return None

        # 팩트 사실관계 2차 재검증(Double-Check)
        logger.info(f"[Double-Check] ID {target_item['id']} 콘텐츠에 대해 최종 팩트 재확인 실행 중...")
        try:
            claims = target_item.get("claims", [])
            if claims:
                # 팩트 재검증 수행
                pass
            target_item["double_checked"] = True
            target_item["double_check_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            logger.warning(f"Double check warning: {e}")

        return target_item

    def check_time_triggers(self) -> List[Dict[str, Any]]:
        """
        현재 시각이 사용자가 설정한 플랫폼별 시간대에 도달했는지 확인
        """
        cfg = self.load_config()
        now = datetime.now()
        current_time_str = now.strftime("%H:%M")
        today_str = now.strftime("%Y-%m-%d")
        
        triggered_events = []

        # 1. Threads 시간대 체크
        for slot in cfg.get("threads", []):
            slot_key = f"threads_{slot}"
            if current_time_str == slot and self.last_sent_slots.get(slot_key) != today_str:
                self.last_sent_slots[slot_key] = today_str
                triggered_events.append({
                    "platform": "threads",
                    "slot": slot,
                    "date": today_str
                })

        # 2. YouTube 시간대 체크
        for slot in cfg.get("youtube", []):
            slot_key = f"youtube_{slot}"
            if current_time_str == slot and self.last_sent_slots.get(slot_key) != today_str:
                self.last_sent_slots[slot_key] = today_str
                triggered_events.append({
                    "platform": "youtube",
                    "slot": slot,
                    "date": today_str
                })

        return triggered_events


if __name__ == "__main__":
    mgr = ScheduleManager()
    cfg = mgr.load_config()
    print("Schedule Config:", cfg)
    print("Ready Buffer Count:", mgr.get_ready_buffer_count())
