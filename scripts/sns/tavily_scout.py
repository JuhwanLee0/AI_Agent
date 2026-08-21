import os
import json
import logging
import requests
from typing import List, Dict, Any, Optional
from openai import OpenAI

from scripts.sns.config import TAVILY_API_KEY
from scripts.sns.queue_db import QueueDB

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("TavilyScout")

class TavilyScout:
    def __init__(self, tavily_api_key: Optional[str] = None):
        self.tavily_api_key = tavily_api_key or TAVILY_API_KEY
        self._init_llm_candidates()

    def _init_llm_candidates(self):
        cerebras_key = (os.getenv("CEREBRAS_API_KEY_3") or os.getenv("CEREBRAS_API_KEY", "")).strip()
        groq_key = (os.getenv("GROQ_API_KEY_3") or os.getenv("GROQ_API_KEY", "")).strip()
        self.candidates = []
        
        if cerebras_key:
            self.candidates.append({
                "provider": "Cerebras",
                "base_url": "https://api.cerebras.ai/v1",
                "api_key": cerebras_key,
                "model": "gemma-4-31b"
            })
        if groq_key:
            self.candidates.append({
                "provider": "Groq",
                "base_url": "https://api.groq.com/openai/v1",
                "api_key": groq_key,
                "model": "openai/gpt-oss-20b"
            })

    def _generate_with_fallback(self, prompt: str, temperature: float = 0.5) -> str:
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
                logger.warning(f"[{cand['provider']}] TavilyScout LLM 호출 실패: {e}. 다음 후보로 전환...")
                continue
                
        raise last_err or RuntimeError("모든 LLM 클라우드 후보 호출 실패")

    def search_tavily(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        """Tavily Search API 호출 (월 1,000회 무료 티어 활용)"""
        if not self.tavily_api_key:
            raise ValueError("TAVILY_API_KEY가 설정되지 않았습니다. .env 파일에 TAVILY_API_KEY를 입력해 주세요.")

        url = "https://api.tavily.com/search"
        payload = {
            "api_key": self.tavily_api_key,
            "query": query,
            "search_depth": "basic",
            "include_answer": True,
            "max_results": max_results,
        }
        
        response = requests.post(url, json=payload, timeout=20)
        response.raise_for_status()
        return response.json()

    def expand_topics(self, domain_keywords: List[str], count: int) -> List[Dict[str, str]]:
        """
        도메인 키워드를 바탕으로 이상한 마케팅의 '표본 이론(대중성+호기심 후킹)'에 부합하는
        고도달 콘텐츠 주제 N개를 발굴합니다.
        """
        prompt = f"""
당신은 인스타그램과 스레드에서 100만 조회수를 만드는 탑티어 SNS 마케팅 디렉터입니다.
다음 도메인/관심사를 기반으로 대중의 공감과 호기심을 극대화하는 매력적인 콘텐츠 주제 {count}개를 선정하세요.

[관심 도메인]
{', '.join(domain_keywords)}

[핵심 기획 원칙 (이상한 마케팅 표본 이론 & 탈-AI 티)]
1. 좁은 전문용어로 시작하지 마세요 (예: '쿠버네티스 세팅법' X -> '개발자 연봉 2배 올린 치트키 도구' O).
2. '나만 알고 싶은 꿀팁/비결', '업무 시간 3시간 단축', '돈 버는 실전 기술', '놓치면 손해인 최신 트렌드' 등 실질적 이득을 제시하세요.
3. 각 주제별로 Tavily 검색 엔진에 넣을 정밀 검색 쿼리(영문 또는 한글)를 함께 지정하세요.

반드시 아래 JSON 포맷으로만 응답하세요:
```json
[
  {{
    "category": "AI 도구",
    "topic": "Claude Code로 1인 SaaS 3일만에 출시하는 법",
    "search_query": "Claude Code workflow solo business 2026"
  }}
]
```
"""
        response_text = self._generate_with_fallback(prompt, temperature=0.7)
        try:
            return json.loads(response_text)
        except Exception as e:
            logger.error(f"주제 확장 JSON 파싱 실패: {e}\n응답: {response_text}")
            raise

    def generate_single_draft(self, category: str, topic: str, search_query: str) -> Dict[str, Any]:
        """
        Tavily 검색 결과를 기반으로 온트리(Onktree) 1단계(Head) 완전체 패키지 초안 생성
        - 표지 후킹 카피
        - 5~7개 슬라이드 텍스트
        - Google Whisk용 영문 이미지 프롬프트 (1.png ~ n.png 톤앤매너 일치)
        - 스레드(Threads) 전용 텍스트
        - 팩트체크용 core_claims 리스트
        """
        logger.info(f"Tavily 검색 수행: '{search_query}' (주제: {topic})")
        search_res = self.search_tavily(search_query)
        
        answer_summary = search_res.get("answer", "")
        results = search_res.get("results", [])
        context_snippets = []
        source_urls = []
        for r in results:
            context_snippets.append(f"- 제목: {r.get('title')}\n  내용: {r.get('content')}\n  URL: {r.get('url')}")
            if r.get("url"):
                source_urls.append(r.get("url"))

        search_context_text = "\n\n".join(context_snippets)

        prompt = f"""
당신은 온트리(Onktree)의 '탈(脫)-AI 티' 콘텐츠 기획 디렉터입니다.
아래 조사된 최신 사실 자료를 기반으로 인스타그램 카드뉴스 및 스레드(Threads) 콘텐츠 초안을 기획하세요.

[카테고리] {category}
[주제] {topic}
[Tavily 검색 요약] {answer_summary}
[수집된 사실 자료]
{search_context_text}

[작성 가이드라인]
1. 표지 후킹 카피 (cover_title):
   - 대중의 시선을 사로잡는 강력한 카피 (수치, 호기심, 손실회피, 꿀팁 강조).
2. 슬라이드 (slides, 5~7장):
   - slide_num: 1부터 순차
   - headline: 각 장의 핵심 헤드라인
   - content: 사람이 읽기 편한 간결하고 명확한 문장 (AI 클리셰 표현 금지)
   - whisk_prompt: Google Labs Whisk 및 AI 이미지 생성용 영문 프롬프트.
     * 모든 슬라이드가 동일한 일러스트/사진 톤앤매너(예: "Minimalist flat 2D vector style, vibrant color accents, clean studio lighting, high resolution")를 유지하도록 작성하세요.
3. 스레드 본문 (thread_text):
   - 이미지 없이 순수 텍스트만으로 스레드에서 높은 반응을 이끌어내는 글.
   - 첫 줄 강렬한 후킹 -> 3~4개의 글머리 요약 -> 실행 팁 -> 댓글 유도 질문.
4. 핵심 사실 검증 목록 (core_claims):
   - 이 글에서 주장하는 수치, 출시일, 가격, 핵심 사실 등 팩트체크가 필요한 핵심 문장 3~5개를 명확히 추출하세요 (예: "Tavily 무료 티어는 월 1,000회", "Jina Reader는 무료 이용 가능").

반드시 아래 JSON 형식으로 응답하세요:
```json
{{
  "cover_title": "...",
  "slides": [
    {{
      "slide_num": 1,
      "headline": "...",
      "content": "...",
      "whisk_prompt": "Minimalist 2D vector illustration of ... in clean modern style, high resolution, no text"
    }}
  ],
  "thread_text": "...",
  "core_claims": [
    "사실 1...",
    "사실 2..."
  ]
}}
```
"""
        response_text = self._generate_with_fallback(prompt, temperature=0.5)

        try:
            data = json.loads(response_text)
            data["category"] = category
            data["topic"] = topic
            data["source_urls"] = source_urls[:5]
            return data
        except Exception as e:
            logger.error(f"초안 생성 JSON 파싱 실패: {e}\n응답: {response_text}")
            raise

    def batch_generate_and_queue(
        self,
        domain_keywords: List[str],
        count: int,
        scheduled_date: str,
        db: Optional[QueueDB] = None,
    ) -> List[int]:
        """주제 확장 -> Tavily 검색 & 초안 작성 -> SQLite 큐 적재 일괄 실행"""
        db = db or QueueDB()
        logger.info(f"[{scheduled_date}] {count}개 콘텐츠 주제 발굴 시작...")
        topics = self.expand_topics(domain_keywords, count)

        created_ids = []
        for idx, t in enumerate(topics, 1):
            logger.info(f"[{idx}/{len(topics)}] 초안 기획 중: {t.get('topic')}")
            try:
                draft = self.generate_single_draft(
                    category=t.get("category", "일반"),
                    topic=t.get("topic", ""),
                    search_query=t.get("search_query", t.get("topic", "")),
                )
                item_id = db.add_draft(
                    scheduled_date=scheduled_date,
                    category=draft["category"],
                    topic=draft["topic"],
                    cover_title=draft["cover_title"],
                    slides=draft["slides"],
                    thread_text=draft["thread_text"],
                    core_claims=draft["core_claims"],
                    source_urls=draft["source_urls"],
                )
                created_ids.append(item_id)
                logger.info(f"큐 적재 완료 (ID: {item_id})")
                
                # RPM 한도(15 RPM / 5 RPM) 방어 안전 딜레이
                if idx < len(topics):
                    from scripts.sns.config import get_safe_delay
                    import time
                    delay = get_safe_delay("worker")
                    logger.debug(f"[RateLimiter] 다음 생성 전 {delay}초 대기 중...")
                    time.sleep(delay)
            except Exception as e:
                logger.error(f"초안 생성 실패 ({t.get('topic')}): {e}")

        logger.info(f"총 {len(created_ids)}개 초안이 {scheduled_date} 일정으로 큐에 적재되었습니다.")
        return created_ids
