import os
import json
import logging
import urllib.parse
import requests
from typing import List, Dict, Any, Optional
from openai import OpenAI

from scripts.sns.config import JINA_API_KEY
from scripts.sns.queue_db import QueueDB

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("JinaVerifier")

class JinaVerifier:
    def __init__(self, jina_api_key: Optional[str] = None):
        self.jina_api_key = jina_api_key or JINA_API_KEY
        self._init_llm_candidates()

    def _init_llm_candidates(self):
        cerebras_key = (os.getenv("CEREBRAS_API_KEY_2") or os.getenv("CEREBRAS_API_KEY", "")).strip()
        groq_key = (os.getenv("GROQ_API_KEY_2") or os.getenv("GROQ_API_KEY", "")).strip()
        self.candidates = []
        
        if cerebras_key:
            self.candidates.append({
                "provider": "Cerebras",
                "base_url": "https://api.cerebras.ai/v1",
                "api_key": cerebras_key,
                "model": "qwen/qwen3.6-27b"
            })
        if groq_key:
            self.candidates.append({
                "provider": "Groq",
                "base_url": "https://api.groq.com/openai/v1",
                "api_key": groq_key,
                "model": "openai/gpt-oss-20b"
            })

    def _generate_with_fallback(self, prompt: str, temperature: float = 0.2) -> str:
        """
        Cerebras & Groq OpenAI 호환 LLM 호출 래퍼
        """
        if not self.candidates:
            self._init_llm_candidates()
        if not self.candidates:
            raise ValueError("CEREBRAS_API_KEY 또는 GROQ_API_KEY가 설정되지 않았습니다.")

        last_err = None
        for cand in self.candidates:
            try:
                client = OpenAI(
                    api_key=cand["api_key"],
                    base_url=cand["base_url"],
                    timeout=30.0
                )
                completion = client.chat.completions.create(
                    model=cand["model"],
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temperature,
                    response_format={"type": "json_object"}
                )
                if completion.choices and completion.choices[0].message.content:
                    return completion.choices[0].message.content
            except Exception as e:
                last_err = e
                logger.warning(f"[{cand['provider']}] JinaVerifier LLM 호출 실패: {e}. 다음 후보로 전환...")
                continue
                
        raise last_err or RuntimeError("모든 LLM 클라우드 후보 호출 실패")

    def fetch_jina_search(self, query: str) -> str:
        """Jina Search (https://s.jina.ai/) 실시간 웹 검색 마크다운 가져오기 (무료/API키 불필요)"""
        encoded_query = urllib.parse.quote(query)
        url = f"https://s.jina.ai/{encoded_query}"
        headers = {"Accept": "text/markdown"}
        if self.jina_api_key:
            headers["Authorization"] = f"Bearer {self.jina_api_key}"

        try:
            res = requests.get(url, headers=headers, timeout=25)
            res.raise_for_status()
            # Truncate if too long (first 8,000 chars is plenty of context)
            return res.text[:8000]
        except Exception as e:
            logger.warning(f"Jina Search 실패 ({query}): {e}")
            return ""

    def fetch_jina_reader(self, target_url: str) -> str:
        """Jina Reader (https://r.jina.ai/) 웹페이지 마크다운 변환"""
        if not target_url or not target_url.startswith("http"):
            return ""
        url = f"https://r.jina.ai/{target_url}"
        headers = {"Accept": "text/markdown"}
        if self.jina_api_key:
            headers["Authorization"] = f"Bearer {self.jina_api_key}"

        try:
            res = requests.get(url, headers=headers, timeout=25)
            res.raise_for_status()
            return res.text[:8000]
        except Exception as e:
            logger.warning(f"Jina Reader 실패 ({target_url}): {e}")
            return ""

    def verify_single_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        초안의 core_claims를 당일 Jina 검색/리더 결과와 대조하여
        - VERIFIED_READY (정상)
        - AUTO_PATCHED (경미한 변경 시 자동 수정 및 Diff 기록)
        - HOLD_ALERT (중대 취소/오보 시 보류) 판정
        """
        if not self.client:
            raise ValueError("Gemini Client가 초기화되지 않았습니다.")

        topic = item.get("topic", "")
        claims = item.get("core_claims", [])
        source_urls = item.get("source_urls", [])

        # 1. Jina 실시간 검색 수행
        search_query = f"{topic} latest update news"
        jina_search_content = self.fetch_jina_search(search_query)

        # 2. 1순위 소스 URL이 있으면 Reader로도 긁기
        jina_reader_content = ""
        if source_urls:
            jina_reader_content = self.fetch_jina_reader(source_urls[0])

        combined_live_web = f"=== [실시간 웹 검색 (s.jina.ai)] ===\n{jina_search_content}\n\n=== [원문 소스 확인 (r.jina.ai)] ===\n{jina_reader_content}"

        prompt = f"""
당신은 엄격한 팩트체크 및 최신성 검증 AI 감사관(Inspector)입니다.
발행 예정인 콘텐츠의 핵심 주장(Core Claims)을 오늘자 실시간 웹 데이터와 대조하여 정확성과 최신성을 검증하세요.

[콘텐츠 주제] {topic}
[표지 제목] {item.get('cover_title', '')}
[핵심 주장 목록 (Core Claims)]
{json.dumps(claims, ensure_ascii=False, indent=2)}

[현재 슬라이드 텍스트]
{json.dumps(item.get('slides', []), ensure_ascii=False, indent=2)}

[현재 스레드 본문]
{item.get('thread_text', '')}

[오늘자 실시간 웹 검증 데이터]
{combined_live_web}

[검증 및 판정 기준]
1. 판정 상태 (verdict):
   - 'VERIFIED_READY': 모든 핵심 주장이 오늘 날짜 기준으로 사실이며 변동 없음.
   - 'AUTO_PATCHED': 일부 수치, 가격, 날짜, 모델 버전 등의 경미한 변경이 확인되어, 슬라이드와 스레드 본문을 최신 팩트에 맞게 수정함.
   - 'HOLD_ALERT': 서비스 종료, 출시 취소, 중대한 오보, 논란 등으로 인해 발행이 부적절하거나 사람의 직접 판단이 필요한 경우.
2. diff_summary:
   - 무엇이 어떻게 달라졌는지 간결하게 한 줄로 요약 (예: "Tavily 무료 한도 1000회 유지 확인 / 슬라이드 3번 출시일 8월->9월로 교정").
3. 만약 AUTO_PATCHED인 경우:
   - patched_cover_title: 수정된 표지 제목 (수정 불필요 시 원본 유지)
   - patched_slides: 최신 정보가 반영된 슬라이드 배열
   - patched_thread_text: 최신 정보가 반영된 스레드 본문

반드시 아래 JSON 형식으로 응답하세요:
```json
{{
  "verdict": "VERIFIED_READY", 
  "diff_summary": "검증 완료: 모든 핵심 수치 및 정책 유효함",
  "reason": "상세 검증 사유...",
  "patched_cover_title": "{item.get('cover_title', '')}",
  "patched_slides": {json.dumps(item.get('slides', []), ensure_ascii=False)},
  "patched_thread_text": "{item.get('thread_text', '')}"
}}
```
"""
        response_text = self._generate_with_fallback(prompt, temperature=0.2)

        try:
            return json.loads(response_text)
        except Exception as e:
            logger.error(f"검증 결과 JSON 파싱 실패: {e}\n응답: {response_text}")
            raise

    def verify_and_update_item(self, item_id: int, db: Optional[QueueDB] = None) -> Dict[str, Any]:
        db = db or QueueDB()
        item = db.get_item(item_id)
        if not item:
            raise ValueError(f"ID {item_id} 항목을 찾을 수 없습니다.")

        logger.info(f"ID {item_id} 검증 시작: [{item.get('topic')}]")
        result = self.verify_single_item(item)
        verdict = result.get("verdict", "VERIFIED_READY")
        diff_summary = result.get("diff_summary", "")
        reason = result.get("reason", "")
        log_entry = json.dumps({"diff_summary": diff_summary, "reason": reason}, ensure_ascii=False)

        if verdict == "AUTO_PATCHED":
            db.update_verification_result(
                item_id=item_id,
                status="AUTO_PATCHED",
                verification_log=log_entry,
                slides=result.get("patched_slides"),
                thread_text=result.get("patched_thread_text"),
                cover_title=result.get("patched_cover_title"),
            )
            logger.info(f"ID {item_id} -> [AUTO_PATCHED] 스마트 패치 완료 ({diff_summary})")
        elif verdict == "HOLD_ALERT":
            db.update_verification_result(
                item_id=item_id,
                status="HOLD_ALERT",
                verification_log=log_entry,
            )
            logger.warning(f"ID {item_id} -> [HOLD_ALERT] 발행 보류 처리 ({reason})")
        else:
            db.update_verification_result(
                item_id=item_id,
                status="VERIFIED_READY",
                verification_log=log_entry,
            )
            logger.info(f"ID {item_id} -> [VERIFIED_READY] 팩트체크 통과")

        return {
            "item_id": item_id,
            "topic": item.get("topic"),
            "status": verdict,
            "diff_summary": diff_summary,
            "reason": reason,
        }

    def verify_date_batch(self, scheduled_date: str, db: Optional[QueueDB] = None) -> List[Dict[str, Any]]:
        db = db or QueueDB()
        items = db.get_items_by_date(scheduled_date)
        if not items:
            logger.info(f"[{scheduled_date}] 검증할 예약 콘텐츠가 없습니다.")
            return []

        logger.info(f"[{scheduled_date}] 총 {len(items)}개 콘텐츠 일괄 실시간 검증 시작...")
        results = []
        for idx, it in enumerate(items, 1):
            res = self.verify_and_update_item(it["id"], db)
            results.append(res)
            if idx < len(items):
                from scripts.sns.config import get_safe_delay
                import time
                delay = get_safe_delay("manager")
                logger.debug(f"[RateLimiter] 다음 검증 전 {delay}초 대기 중...")
                time.sleep(delay)

        return results
