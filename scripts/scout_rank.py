#!/usr/bin/env python3
"""
scripts/scout_rank.py — 순수 함수 랭커 (네트워크 금지)

계약:
- 네트워크 호출을 절대 하지 않는 순수 함수 파이썬 스크립트.
- 동일한 입력에 대해 항상 바이트 단위로 동일한 출력을 보장한다 (결정론적).
- degraded 스냅샷이거나 schema_version != 2이면 exit 2로 거부한다.
"""

import sys
import os
import json
import re
import math
import argparse
from pathlib import Path
from typing import List, Dict, Set, Any, Tuple

# 긴 조사부터 역순으로 제거 (단어가 잘못 잘리는 것 방지: '에서' -> '서' 방지)
JOSA_PATTERNS = [
    '에서', '으로', '부터', '까지', '보다',
    '이', '가', '은', '는', '을', '를', '의', '에', '로', '와', '과', '도', '만'
]

# 불용어 목록
STOPWORDS = {
    '진짜', '이유', '정체', '충격', '결국', '지금', '현재', '오늘', '왜',
    '그리고', '그런데', '하지만', '합니다', '입니다', '됩니다', '했다', '한다', '하는',
    '그', '이', '저', '것', '수', '때',
    '속보', '긴급', '영상', '총정리', '근황', '상황', '소식', '발표', '공개', '충격적'
}

def clean_josa(token: str) -> str:
    """단어 끝에 붙은 조사를 긴 것부터 검사하여 제거한다."""
    for josa in JOSA_PATTERNS:
        if token.endswith(josa) and len(token) > len(josa):
            token = token[:-len(josa)]
            break
    return token

def is_anchor_token(token: str) -> bool:
    """앵커 토큰: 숫자를 포함하거나 3글자 이상인 토큰 (고유명사 근사)."""
    if any(ch.isdigit() for ch in token):
        return True
    return len(token) >= 3

def tokenize_title(title: str) -> List[str]:
    """
    제목 토큰화:
    1. 정규식으로 한글/영문/숫자 덩어리를 추출.
    2. 조사를 뒤에서 벗겨냄 (긴 것부터).
    3. 불용어를 제거.
    4. 숫자가 아닌 한 글자는 버림.
    """
    raw_tokens = re.findall(r'[가-힣a-zA-Z0-9]+', title.lower())
    tokens: List[str] = []
    
    for raw in raw_tokens:
        tok = clean_josa(raw)
        if not tok:
            continue
        if tok in STOPWORDS:
            continue
        if len(tok) == 1 and not tok.isdigit():
            continue
        tokens.append(tok)
        
    return sorted(list(set(tokens)))

def jaccard_similarity(tokens_a: Set[str], tokens_b: Set[str]) -> float:
    """자카드 유사도 계산."""
    union = tokens_a | tokens_b
    if not union:
        return 0.0
    intersection = tokens_a & tokens_b
    return len(intersection) / len(union)

def is_strong_match(tokens_a: Set[str], tokens_b: Set[str]) -> bool:
    """
    강매칭 조건:
    공유 토큰이 2개 이상이고, 그중 앵커 토큰이 1개 이상일 것.
    """
    intersection = tokens_a & tokens_b
    if len(intersection) < 2:
        return False
    return any(is_anchor_token(t) for t in intersection)

def load_ledger_topics(ledger_path: Path) -> List[Dict[str, Any]]:
    """_scout/ledger.jsonl 파일에서 이미 다룬 주제들을 로드한다."""
    topics = []
    if ledger_path.exists():
        with open(ledger_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        topics.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    return topics

def classify_portfolio_format(tokens: Set[str], formats: List[Dict[str, Any]]) -> str:
    """토큰을 기반으로 설정된 포맷(설명형, 사례해부형 등)을 라우팅한다."""
    for fmt in formats:
        name = fmt.get("name", "")
        keywords = set(fmt.get("keywords", []))
        if tokens & keywords:
            return name
    return "none"

def rank_outliers(snapshot_data: Dict[str, Any], config_data: Dict[str, Any], ledger_path: Path) -> Dict[str, Any]:
    """스냅샷과 설정을 받아 결정론적으로 아웃라이어 토픽을 클러스터링하고 랭킹을 산출한다."""
    # 1. 스키마 버전 및 Degraded 검사
    schema_version = snapshot_data.get("$schema_version")
    fetch_meta = snapshot_data.get("fetch_meta", {})
    if schema_version != 2 or fetch_meta.get("degraded", False):
        sys.stderr.write("쿼터 소진 또는 스키마 불일치 — 랭킹 거부\n")
        sys.exit(2)
        
    outliers = snapshot_data.get("outliers", [])
    if not outliers:
        return {
            "candidates": [],
            "excluded": [],
            "deduped": []
        }
        
    # 설정값 추출
    outlier_cfg = config_data.get("outlier", {})
    cluster_threshold = outlier_cfg.get("cluster_threshold", 0.3)
    outlier_strength_min = outlier_cfg.get("outlier_strength_min", 8.0)
    cross_channel_min = outlier_cfg.get("cross_channel_min", 2)
    freshness_days = outlier_cfg.get("freshness_days", 14)
    
    signals_cfg = config_data.get("signals", {})
    packaging_min_video_views = signals_cfg.get("packaging_min_video_views", 400000)
    
    evergreen_keywords = set(config_data.get("evergreen_keywords", []))
    formats = config_data.get("portfolio", {}).get("formats", [])
    dedup_threshold = config_data.get("dedup_threshold", 0.8)
    
    # 2. 영상 정렬 (결정론적 처리를 위해 video_id 기준 선행 정렬)
    sorted_outliers = sorted(outliers, key=lambda v: str(v.get("video_id", "")))
    
    # 각 영상의 토큰 세트 미리 계산
    video_tokens_map = {}
    for v in sorted_outliers:
        v_id = v.get("video_id", "")
        title = v.get("title", "")
        tokens = tokenize_title(title)
        video_tokens_map[v_id] = set(tokens)
        
    # 3. 클러스터링 (Connected Components / Union-Find)
    n = len(sorted_outliers)
    parent = list(range(n))
    
    def find(i: int) -> int:
        path = []
        while parent[i] != i:
            path.append(i)
            i = parent[i]
        for node in path:
            parent[node] = i
        return i
        
    def union(i: int, j: int) -> None:
        root_i = find(i)
        root_j = find(j)
        if root_i != root_j:
            # 결정론적 순서: 작은 인덱스를 부모로
            if root_i < root_j:
                parent[root_j] = root_i
            else:
                parent[root_i] = root_j

    # 강매칭 또는 자카드 유사도 기준 연결
    for i in range(n):
        v_i = sorted_outliers[i]
        tokens_i = video_tokens_map[v_i.get("video_id", "")]
        for j in range(i + 1, n):
            v_j = sorted_outliers[j]
            tokens_j = video_tokens_map[v_j.get("video_id", "")]
            
            sim = jaccard_similarity(tokens_i, tokens_j)
            strong = is_strong_match(tokens_i, tokens_j)
            
            if sim >= cluster_threshold or strong:
                union(i, j)
                
    # 클러스터 그룹핑
    clusters_dict: Dict[int, List[Dict[str, Any]]] = {}
    for i in range(n):
        root = find(i)
        if root not in clusters_dict:
            clusters_dict[root] = []
        clusters_dict[root].append(sorted_outliers[i])
        
    # 4. 클러스터별 신호 판정 및 특징 추출
    clusters_list = []
    for root, group in sorted(clusters_dict.items(), key=lambda x: x[0]):
        # 클러스터 내 모든 토큰 수집
        all_cluster_tokens: Set[str] = set()
        channel_ids: Set[str] = set()
        max_ratio = 0.0
        max_vph = 0.0
        max_views = 0
        min_age_days = float('inf')
        
        # 영상 리스트도 결정론적으로 정렬 (video_id)
        sorted_group = sorted(group, key=lambda v: str(v.get("video_id", "")))
        
        for v in sorted_group:
            v_id = v.get("video_id", "")
            all_cluster_tokens |= video_tokens_map[v_id]
            ch_id = v.get("channel_id", "")
            if ch_id:
                channel_ids.add(ch_id)
            ratio = float(v.get("ratio", 0.0))
            if ratio > max_ratio:
                max_ratio = ratio
            vph = float(v.get("vph", 0.0))
            if vph > max_vph:
                max_vph = vph
            views = int(v.get("views", 0))
            if views > max_views:
                max_views = views
            age = float(v.get("age_days", 0.0))
            if age < min_age_days:
                min_age_days = age
                
        # 강매칭된 채널 수 계산 (서로 다른 채널 간 강매칭 여부)
        cross_channel_count = len(channel_ids)
        if len(sorted_group) >= 2 and len(channel_ids) >= 2:
            # 적어도 한 쌍의 서로 다른 채널 영상 간 강매칭 확인
            has_cross_strong = False
            for idx1 in range(len(sorted_group)):
                for idx2 in range(idx1 + 1, len(sorted_group)):
                    v1 = sorted_group[idx1]
                    v2 = sorted_group[idx2]
                    if v1.get("channel_id") != v2.get("channel_id"):
                        if is_strong_match(video_tokens_map[v1["video_id"]], video_tokens_map[v2["video_id"]]):
                            has_cross_strong = True
                            break
                if has_cross_strong:
                    break
            if not has_cross_strong and len(sorted_group) > 1:
                # 자카드 유사도로만 묶이고 강매칭이 없으면 cross_channel 카운트 완화 고려하지 않고 엄격 체크
                pass

        # 신호 4종 계산
        sig_outlier_strength = (max_ratio >= outlier_strength_min)
        sig_cross_channel = (cross_channel_count >= cross_channel_min)
        sig_freshness = bool(all_cluster_tokens & evergreen_keywords) or (min_age_days <= freshness_days)
        sig_packaging_views = (max_views >= packaging_min_video_views)
        
        signals_fired = {
            "outlier_strength": sig_outlier_strength,
            "cross_channel": sig_cross_channel,
            "freshness": sig_freshness,
            "packaging_views": sig_packaging_views
        }
        
        agreement_count = sum(1 for v in signals_fired.values() if v)
        
        # 클러스터 대표 토픽명 생성 (가장 긴 앵커 토큰 및 빈도 높은 토큰 조합)
        # 재현성을 위해 정렬된 토큰 목록 사용
        sorted_tokens = sorted(list(all_cluster_tokens), key=lambda t: (-len(t), t))
        representative_topic = " ".join(sorted_tokens[:3]) if sorted_tokens else "주제 미정"
        
        prior_confidence = "thin" if len(sorted_group) == 1 else "high"
        matched_format = classify_portfolio_format(all_cluster_tokens, formats)
        
        cluster_info = {
            "topic": representative_topic,
            "tokens": sorted(list(all_cluster_tokens)),
            "matched_format": matched_format,
            "signals_fired": signals_fired,
            "signal_agreement_count": agreement_count,
            "outlier_summary": {
                "max_ratio": round(max_ratio, 2),
                "channels": sorted(list(channel_ids)),
                "channel_count": len(channel_ids),
                "sample_count": len(sorted_group),
                "freshest_age_days": round(min_age_days if min_age_days != float('inf') else 0.0, 1),
                "max_vph": round(max_vph, 2),
                "max_views": max_views,
                "videos": [
                    {
                        "video_id": v.get("video_id", ""),
                        "title": v.get("title", ""),
                        "channel_title": v.get("channel_title", ""),
                        "ratio": round(float(v.get("ratio", 0.0)), 2),
                        "vph": round(float(v.get("vph", 0.0)), 2),
                        "views": int(v.get("views", 0)),
                        "age_days": round(float(v.get("age_days", 0.0)), 1)
                    } for v in sorted_group
                ]
            },
            "prior_confidence": prior_confidence
        }
        clusters_list.append(cluster_info)
        
    # 5. 채택 규칙 검사
    # outlier_strength == False 면 탈락 (필수 신호)
    # 그리고 4종 중 true가 2개 이상이어야 후보(candidate)
    raw_candidates = []
    excluded = []
    
    for c in clusters_list:
        if not c["signals_fired"]["outlier_strength"]:
            c["exclusion_reason"] = "필수 신호(outlier_strength) 미충족"
            excluded.append(c)
        elif c["signal_agreement_count"] < 2:
            c["exclusion_reason"] = f"신호 합의 부족 ({c['signal_agreement_count']}/4 < 2)"
            excluded.append(c)
        else:
            raw_candidates.append(c)
            
    # 6. 정렬 (결정론 3단):
    # 1) signal_agreement_count 내림차순
    # 2) max_vph 내림차순
    # 3) topic 이름 오름차순
    sorted_candidates = sorted(
        raw_candidates,
        key=lambda x: (
            -x["signal_agreement_count"],
            -x["outlier_summary"]["max_vph"],
            x["topic"]
        )
    )
    
    # 7. 중복 제거 (ledger 대조)
    ledger_topics = load_ledger_topics(ledger_path)
    ledger_token_sets = []
    for item in ledger_topics:
        t_title = item.get("topic", "")
        if t_title:
            ledger_token_sets.append(set(tokenize_title(t_title)))
            
    final_candidates = []
    deduped = []
    
    for cand in sorted_candidates:
        cand_tokens = set(cand["tokens"])
        is_dup = False
        dup_reason = ""
        
        for prev_tokens in ledger_token_sets:
            sim = jaccard_similarity(cand_tokens, prev_tokens)
            if sim >= dedup_threshold:
                is_dup = True
                dup_reason = f"성과 원장 기존 주제와 토큰 유사도 {sim:.2f} >= {dedup_threshold}"
                break
                
        if is_dup:
            cand_copy = dict(cand)
            cand_copy["dedup_reason"] = dup_reason
            deduped.append(cand_copy)
        else:
            final_candidates.append(cand)
            
    # excluded 목록도 결정론적 정렬
    sorted_excluded = sorted(
        excluded,
        key=lambda x: (
            -x["signal_agreement_count"],
            -x["outlier_summary"]["max_vph"],
            x["topic"]
        )
    )
    
    # deduped 목록도 결정론적 정렬
    sorted_deduped = sorted(
        deduped,
        key=lambda x: (
            -x["signal_agreement_count"],
            -x["outlier_summary"]["max_vph"],
            x["topic"]
        )
    )

    return {
        "candidates": final_candidates,
        "excluded": sorted_excluded,
        "deduped": sorted_deduped
    }

def main():
    parser = argparse.ArgumentParser(description="YouTube Topic Scout Ranker (Pure Function)")
    parser.add_argument("--snapshot", type=str, help="스냅샷 JSON 파일 경로")
    parser.add_argument("--config", type=str, default="config/topic-scout.json", help="설정 JSON 파일 경로")
    parser.add_argument("--ledger", type=str, default="_scout/ledger.jsonl", help="성과 원장 파일 경로")
    parser.add_argument("--output", type=str, help="결과 JSON 출력 파일 경로 (미지정 시 stdout)")
    args = parser.parse_args()

    # 1. 스냅샷 파일 찾기
    snapshot_path = None
    if args.snapshot:
        snapshot_path = Path(args.snapshot)
    else:
        snapshots_dir = Path("_scout/snapshots")
        if snapshots_dir.exists():
            files = sorted(snapshots_dir.glob("*.json"))
            if files:
                snapshot_path = files[-1]
                
    if not snapshot_path or not snapshot_path.exists():
        sys.stderr.write("오류: 분석할 스냅샷 파일을 찾을 수 없습니다.\n")
        sys.exit(1)

    # 2. 파일 로드
    try:
        with open(snapshot_path, "r", encoding="utf-8") as f:
            snapshot_data = json.load(f)
    except Exception as e:
        sys.stderr.write(f"오류: 스냅샷 파일 파싱 실패: {e}\n")
        sys.exit(2)

    config_path = Path(args.config)
    if not config_path.exists():
        sys.stderr.write(f"오류: 설정 파일을 찾을 수 없습니다: {config_path}\n")
        sys.exit(1)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)
    except Exception as e:
        sys.stderr.write(f"오류: 설정 파일 파싱 실패: {e}\n")
        sys.exit(1)

    ledger_path = Path(args.ledger)

    # 3. 순수 함수 랭킹 실행
    result = rank_outliers(snapshot_data, config_data, ledger_path)

    # 4. 결정론적 JSON 출력 (indent=2, sort_keys=True, utf-8)
    output_str = json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_str + "\n")
    else:
        print(output_str)

if __name__ == "__main__":
    main()
