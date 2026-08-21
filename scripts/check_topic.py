#!/usr/bin/env python3
"""
scripts/check_topic.py — 4중 거부권 게이트 (통과/탈락 판정)

계약:
- 후보 토픽을 받아 4중 거부권(중복, 비진정성, 명예훼손, 참사 인접)을 검사한다.
- exit 0 = 통과 (Passed)
- exit 1 = 탈락 (Vetoed) - 탈락 사유를 JSON으로 출력.
- 점수가 아무리 높아도 거부권을 상쇄하지 못한다.
"""

import sys
import os
import json
import argparse
from pathlib import Path
from typing import List, Dict, Set, Any

# scout_rank의 토큰화 및 자카드 유사도 모듈 가져오기
from scout_rank import tokenize_title, jaccard_similarity, load_ledger_topics

import re

def is_veto_matched(word: str, text: str, tokens: Set[str]) -> bool:
    """단어 경계 또는 토큰 완전 일치를 검사하여 부분문자열 오탐(예: 참사->참사랑) 방지"""
    if not word:
        return False
    # 1. 토큰 단위 정확 일치
    if word in tokens:
        return True
    # 2. 정규식 단어 경계 일치 (한글/영문 경계)
    pattern = rf"(?<![가-힣a-zA-Z0-9]){re.escape(word)}(?![가-힣a-zA-Z0-9])"
    return bool(re.search(pattern, text))

def check_topic_gate(topic_text: str, config_data: Dict[str, Any], ledger_path: Path, candidate_data: Dict[str, Any] = None) -> Dict[str, Any]:
    veto_reasons = []
    
    # 1. 텍스트 통합 (주제명, 영상 제목들, 설명 등)
    full_text_list = [topic_text]
    if candidate_data:
        full_text_list.append(candidate_data.get("topic", ""))
        videos = candidate_data.get("outlier_summary", {}).get("videos", [])
        for v in videos:
            full_text_list.append(v.get("title", ""))
            
    combined_text = " ".join(full_text_list)
    topic_tokens = set(tokenize_title(combined_text))
    
    policy = config_data.get("policy", {})
    inauthentic_veto = policy.get("inauthentic_veto", [])
    kr_defamation_veto = policy.get("kr_defamation_veto", ["사기꾼", "범죄자", "횡령범"])
    tragedy_adjacency_veto = policy.get("tragedy_adjacency_veto", ["참사", "사망 사고", "압사", "유가족", "분향소"])
    
    # 거부권 1: 비진정성 (Inauthentic Veto)
    for word in inauthentic_veto:
        if is_veto_matched(word, combined_text, topic_tokens):
            veto_reasons.append(f"비진정성 거부권(inauthentic_veto) 발동: '{word}' 포함")
            
    # 거부권 2: 명예훼손 (KR Defamation Veto)
    for word in kr_defamation_veto:
        if is_veto_matched(word, combined_text, topic_tokens):
            veto_reasons.append(f"명예훼손 거부권(kr_defamation_veto) 발동: '{word}' 포함")
            
    # 거부권 3: 참사 인접 (Tragedy Adjacency Veto)
    for word in tragedy_adjacency_veto:
        if is_veto_matched(word, combined_text, topic_tokens):
            veto_reasons.append(f"참사 인접 거부권(tragedy_adjacency_veto) 발동: '{word}' 포함")
            
    # 거부권 4: 중복 (Dedup / Duplicate in Ledger)
    dedup_threshold = config_data.get("dedup_threshold", 0.8)
    ledger_topics = load_ledger_topics(ledger_path)
    for prev in ledger_topics:
        prev_topic = prev.get("topic", "")
        if prev_topic:
            prev_tokens = set(tokenize_title(prev_topic))
            sim = jaccard_similarity(topic_tokens, prev_tokens)
            if sim >= dedup_threshold:
                veto_reasons.append(f"기존 발행 주제 중복: '{prev_topic}' (토큰 유사도 {sim:.2f} >= {dedup_threshold})")
                break
                
    passed = (len(veto_reasons) == 0)
    
    return {
        "passed": passed,
        "topic": topic_text,
        "veto_count": len(veto_reasons),
        "veto_reasons": veto_reasons
    }

def main():
    parser = argparse.ArgumentParser(description="Check topic against 4-fold veto gate")
    parser.add_argument("--topic", type=str, help="검사할 주제 텍스트")
    parser.add_argument("--candidate-file", type=str, help="검사할 후보 JSON 파일 경로")
    parser.add_argument("--candidate-json", type=str, help="검사할 후보 JSON 문자열")
    parser.add_argument("--config", type=str, default="config/topic-scout.json", help="설정 파일 경로")
    parser.add_argument("--ledger", type=str, default="_scout/ledger.jsonl", help="성과 원장 파일 경로")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        sys.stderr.write(f"오류: 설정 파일을 찾을 수 없습니다: {config_path}\n")
        sys.exit(1)
        
    with open(config_path, "r", encoding="utf-8") as f:
        config_data = json.load(f)
        
    ledger_path = Path(args.ledger)

    topic_text = ""
    candidate_data = None

    if args.candidate_file:
        with open(args.candidate_file, "r", encoding="utf-8") as f:
            candidate_data = json.load(f)
            topic_text = candidate_data.get("topic", "")
    elif args.candidate_json:
        candidate_data = json.loads(args.candidate_json)
        topic_text = candidate_data.get("topic", "")
    elif args.topic:
        topic_text = args.topic
    else:
        # stdin에서 읽기 시도
        if not sys.stdin.isatty():
            stdin_content = sys.stdin.read().strip()
            if stdin_content:
                try:
                    candidate_data = json.loads(stdin_content)
                    topic_text = candidate_data.get("topic", "")
                except json.JSONDecodeError:
                    topic_text = stdin_content
        if not topic_text:
            sys.stderr.write("오류: 검사할 주제(--topic, --candidate-file, 또는 stdin)를 입력해주세요.\n")
            sys.exit(1)

    result = check_topic_gate(topic_text, config_data, ledger_path, candidate_data)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    if not result["passed"]:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()
