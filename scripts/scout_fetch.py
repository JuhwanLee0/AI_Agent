#!/usr/bin/env python3
"""
scripts/scout_fetch.py — 네트워크·쿼터·스냅샷 수집 담당

계약:
- 환경변수 YOUTUBE_API_KEY 사용 (코드 하드코딩 금지).
- 1) config.ref_channels를 yt-dlp flat 스캔으로 영상 id 수집 (쿼터 0 소모).
- 2) YouTube Data API videos.list로 50개씩 보강 (호출당 1유닛 소모).
     ★ search.list 호출 금지.
- 3) 롱폼(>180초) 영상의 vph 및 중앙값 계산. 표본 < min_baseline_sample 제외.
- 4) 배율(영상 vph / 기준선 vph) >= outlier_ratio_min 영상 추출.
- 5) 스냅샷 저장: _scout/snapshots/{YYYYMMDD-HHMMSS}.json
- 쿼터 보호: unit_budget 하드캡 초과나 403 에러 시 degraded=true 스냅샷 저장.
"""

import sys
import os
import json
import re
import urllib.request
import urllib.error
import urllib.parse
import subprocess
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

def parse_iso8601_duration(duration_str: str) -> int:
    """ISO 8601 duration (예: PT15M33S, PT1H2M10S, PT45S)을 초 단위 정수로 변환."""
    pattern = r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?'
    match = re.match(pattern, duration_str)
    if not match:
        return 0
    hours = int(match.group(1)) if match.group(1) else 0
    minutes = int(match.group(2)) if match.group(2) else 0
    seconds = int(match.group(3)) if match.group(3) else 0
    return hours * 3600 + minutes * 60 + seconds

def calculate_median(values: List[float]) -> float:
    """부동소수점 리스트의 중앙값(Median) 계산."""
    if not values:
        return 0.0
    sorted_v = sorted(values)
    n = len(sorted_v)
    mid = n // 2
    if n % 2 == 1:
        return sorted_v[mid]
    else:
        return (sorted_v[mid - 1] + sorted_v[mid]) / 2.0

def fetch_channel_video_ids_ytdlp(channel_id: str, scan_depth: int = 30) -> List[str]:
    """yt-dlp flat-playlist 모드로 채널의 최신 영상 ID 목록을 스캔한다 (API 쿼터 소모 0)."""
    # 채널 URL 형식 지원 (UC... ID)
    if channel_id.startswith("UC"):
        url = f"https://www.youtube.com/channel/{channel_id}/videos"
    elif channel_id.startswith("http"):
        url = channel_id
    else:
        url = f"https://www.youtube.com/@{channel_id}/videos"

    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--print", "id",
        "--playlist-end", str(scan_depth),
        url
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if res.returncode == 0:
            ids = [line.strip() for line in res.stdout.splitlines() if line.strip()]
            return ids
        else:
            sys.stderr.write(f"yt-dlp 스캔 경고 ({channel_id}): {res.stderr[:200]}\n")
            return []
    except Exception as e:
        sys.stderr.write(f"yt-dlp 실행 실패 ({channel_id}): {e}\n")
        return []

def call_youtube_videos_list(video_ids: List[str], api_key: str) -> Optional[Dict[str, Any]]:
    """YouTube Data API videos.list 호출 (50개당 1유닛 소모)."""
    if not video_ids:
        return {"items": []}
    
    ids_param = ",".join(video_ids)
    url = "https://www.googleapis.com/youtube/v3/videos?" + urllib.parse.urlencode({
        "part": "snippet,contentDetails,statistics",
        "id": ids_param,
        "key": api_key,
        "maxResults": 50
    })
    
    req = urllib.request.Request(url, headers={"User-Agent": "TopicScout/2.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"YouTube API HTTP 오류: {e.code} - {e.reason}\n")
        return None
    except Exception as e:
        sys.stderr.write(f"YouTube API 요청 실패: {e}\n")
        return None

def save_snapshot(snapshot: Dict[str, Any], output_dir: Path) -> Path:
    """스냅샷을 _scout/snapshots/{YYYYMMDD-HHMMSS}.json 파일로 저장."""
    output_dir.mkdir(parents=True, exist_ok=True)
    now_str = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    file_path = output_dir / f"{now_str}.json"
    
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False, sort_keys=True)
        
    latest_path = output_dir / "latest.json"
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False, sort_keys=True)
        
    return file_path

def main():
    parser = argparse.ArgumentParser(description="Fetch YouTube Outlier Snapshot")
    parser.add_argument("--config", type=str, default="config/topic-scout.json", help="설정 파일 경로")
    parser.add_argument("--self-channel-id", type=str, help="내 채널 ID (UC...)")
    parser.add_argument("--output-dir", type=str, default="_scout/snapshots", help="스냅샷 저장 디렉토리")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        sys.stderr.write(f"오류: 설정 파일을 찾을 수 없습니다: {config_path}\n")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    unit_budget = config.get("unit_budget", 30)
    outlier_cfg = config.get("outlier", {})
    scan_depth = outlier_cfg.get("scan_depth", 30)
    min_baseline_sample = outlier_cfg.get("min_baseline_sample", 10)
    outlier_ratio_min = outlier_cfg.get("outlier_ratio_min", 2.5)
    recency_days = outlier_cfg.get("recency_days", 45)
    
    ref_channels = config.get("ref_channels", [])
    output_dir = Path(args.output_dir)

    # API 키 확인
    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        sys.stderr.write("경고: YOUTUBE_API_KEY 환경변수가 설정되지 않았습니다. Degraded 스냅샷을 생성합니다.\n")
        degraded_snap = {
            "$schema_version": 2,
            "fetch_meta": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "unit_spent": 0,
                "unit_budget": unit_budget,
                "degraded": True,
                "error": "YOUTUBE_API_KEY 환경변수 미설정",
                "channel_count": len(ref_channels),
                "videos_fetched": 0
            },
            "ref_baselines": [],
            "outliers": []
        }
        saved_file = save_snapshot(degraded_snap, output_dir)
        print(f"Degraded 스냅샷 저장됨: {saved_file}")
        sys.exit(0)

    if not ref_channels:
        sys.stderr.write("알림: config/topic-scout.json에 ref_channels가 비어 있습니다.\n")
        empty_snap = {
            "$schema_version": 2,
            "fetch_meta": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "unit_spent": 0,
                "unit_budget": unit_budget,
                "degraded": False,
                "channel_count": 0,
                "videos_fetched": 0
            },
            "ref_baselines": [],
            "outliers": []
        }
        saved_file = save_snapshot(empty_snap, output_dir)
        print(f"빈 스냅샷 저장됨: {saved_file}")
        sys.exit(0)

    unit_spent = 0
    now_utc = datetime.now(timezone.utc)
    
    channel_video_records: Dict[str, List[Dict[str, Any]]] = {}
    channel_titles: Dict[str, str] = {}
    
    # 1) yt-dlp flat 스캔
    for ch in ref_channels:
        ch_id = ch if isinstance(ch, str) else ch.get("id", "")
        if not ch_id:
            continue
        v_ids = fetch_channel_video_ids_ytdlp(ch_id, scan_depth=scan_depth)
        
        # 2) YouTube Data API videos.list (50개씩 청크)
        ch_videos = []
        for i in range(0, len(v_ids), 50):
            if unit_spent >= unit_budget:
                sys.stderr.write(f"경고: unit_budget ({unit_budget}유닛) 소진. 조기 중단.\n")
                break
                
            chunk = v_ids[i:i+50]
            unit_spent += 1
            api_res = call_youtube_videos_list(chunk, api_key)
            if not api_res:
                # 403 등의 에러 발생 시 Degraded 플래그 처리
                sys.stderr.write("API 호출 실패로 Degraded 스냅샷으로 전환합니다.\n")
                degraded_snap = {
                    "$schema_version": 2,
                    "fetch_meta": {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "unit_spent": unit_spent,
                        "unit_budget": unit_budget,
                        "degraded": True,
                        "error": "YouTube API 403 or Error",
                        "channel_count": len(ref_channels),
                        "videos_fetched": 0
                    },
                    "ref_baselines": [],
                    "outliers": []
                }
                save_snapshot(degraded_snap, output_dir)
                sys.exit(0)
                
            items = api_res.get("items", [])
            for item in items:
                v_id = item.get("id", "")
                snippet = item.get("snippet", {})
                content = item.get("contentDetails", {})
                stats = item.get("statistics", {})
                
                title = snippet.get("title", "")
                published_at_str = snippet.get("publishedAt", "")
                duration_str = content.get("duration", "PT0S")
                duration_sec = parse_iso8601_duration(duration_str)
                views = int(stats.get("viewCount", 0))
                ch_title = snippet.get("channelTitle", "")
                channel_titles[ch_id] = ch_title
                
                # 경과 시간 계산
                try:
                    pub_dt = datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
                    elapsed_hours = max((now_utc - pub_dt).total_seconds() / 3600.0, 1.0)
                    age_days = (now_utc - pub_dt).total_seconds() / 86400.0
                except Exception:
                    elapsed_hours = 24.0
                    age_days = 1.0
                    
                vph = views / elapsed_hours
                
                ch_videos.append({
                    "video_id": v_id,
                    "channel_id": ch_id,
                    "channel_title": ch_title,
                    "title": title,
                    "published_at": published_at_str,
                    "duration_seconds": duration_sec,
                    "views": views,
                    "vph": vph,
                    "age_days": age_days,
                    "is_longform": (duration_sec > 180)
                })
        channel_video_records[ch_id] = ch_videos

    # 3) 채널별 롱폼 기준선 vph 계산
    ref_baselines = []
    channel_baselines = {}
    for ch_id, videos in channel_video_records.items():
        longform_vphs = [v["vph"] for v in videos if v["is_longform"]]
        sample_count = len(longform_vphs)
        if sample_count < min_baseline_sample:
            # 표본 부족 채널은 판정에서 제외
            continue
        median_vph = calculate_median(longform_vphs)
        channel_baselines[ch_id] = median_vph
        ref_baselines.append({
            "channel_id": ch_id,
            "channel_title": channel_titles.get(ch_id, ch_id),
            "sample_count": sample_count,
            "median_vph": round(median_vph, 2)
        })

    # 4) 아웃라이어 영상 필터링
    outliers = []
    for ch_id, videos in channel_video_records.items():
        if ch_id not in channel_baselines:
            continue
        base_vph = channel_baselines[ch_id]
        if base_vph <= 0:
            continue
            
        for v in videos:
            if not v["is_longform"]:
                continue
            if v["age_days"] > recency_days:
                continue
            ratio = v["vph"] / base_vph
            if ratio >= outlier_ratio_min:
                outliers.append({
                    "video_id": v["video_id"],
                    "channel_id": v["channel_id"],
                    "channel_title": v["channel_title"],
                    "title": v["title"],
                    "published_at": v["published_at"],
                    "duration_seconds": v["duration_seconds"],
                    "views": v["views"],
                    "vph": round(v["vph"], 2),
                    "baseline_vph": round(base_vph, 2),
                    "ratio": round(ratio, 2),
                    "age_days": round(v["age_days"], 1)
                })

    # 5) 스냅샷 생성 및 저장
    snapshot = {
        "$schema_version": 2,
        "fetch_meta": {
            "timestamp": now_utc.isoformat(),
            "unit_spent": unit_spent,
            "unit_budget": unit_budget,
            "degraded": False,
            "channel_count": len(ref_baselines),
            "videos_fetched": sum(len(v) for v in channel_video_records.values())
        },
        "ref_baselines": ref_baselines,
        "outliers": outliers
    }

    saved_path = save_snapshot(snapshot, output_dir)
    print(f"스냅샷 수집 완료: {saved_path} (아웃라이어 {len(outliers)}개 발견, 쿼터 소모 {unit_spent}/{unit_budget})")

if __name__ == "__main__":
    main()
