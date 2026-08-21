import unittest
import sys
import json
import tempfile
from pathlib import Path

# scripts 디렉토리를 import 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from scout_rank import (
    clean_josa,
    is_anchor_token,
    tokenize_title,
    jaccard_similarity,
    is_strong_match,
    rank_outliers
)

class TestScoutRank(unittest.TestCase):
    def test_clean_josa(self):
        # 긴 조사부터 검사하여 '에서'가 '서'로 잘리지 않는지 확인
        self.assertEqual(clean_josa("서울에서"), "서울")
        self.assertEqual(clean_josa("집으로"), "집")
        self.assertEqual(clean_josa("처음부터"), "처음")
        self.assertEqual(clean_josa("끝까지"), "끝")
        self.assertEqual(clean_josa("어제보다"), "어제")
        self.assertEqual(clean_josa("철수가"), "철수")
        self.assertEqual(clean_josa("영희는"), "영희")
        self.assertEqual(clean_josa("사과를"), "사과")

    def test_tokenize_title_stopwords_and_length(self):
        title = "진짜 충격적인 이유! 2026년 부동산 폭락 총정리 및 긴급 속보"
        tokens = tokenize_title(title)
        
        # 불용어 제거 확인
        for stopword in ["진짜", "충격적", "이유", "총정리", "긴급", "속보"]:
            self.assertNotIn(stopword, tokens)
        
        # 핵심 토큰 추출 확인
        self.assertTrue(any("2026" in t for t in tokens))
        self.assertIn("부동산", tokens)
        self.assertIn("폭락", tokens)

    def test_anchor_token(self):
        self.assertFalse(is_anchor_token("ai"))
        self.assertTrue(is_anchor_token("gpt"))  # 3글자
        self.assertTrue(is_anchor_token("2026"))  # 숫자 포함
        self.assertTrue(is_anchor_token("부동산"))  # 3글자

    def test_jaccard_and_strong_match(self):
        tokens1 = {"부동산", "폭락", "2026"}
        tokens2 = {"부동산", "폭락", "전망"}
        tokens3 = {"주식", "투자", "단타"}
        
        sim12 = jaccard_similarity(tokens1, tokens2)
        self.assertEqual(sim12, 2 / 4)
        self.assertTrue(is_strong_match(tokens1, tokens2))
        
        sim13 = jaccard_similarity(tokens1, tokens3)
        self.assertEqual(sim13, 0.0)
        self.assertFalse(is_strong_match(tokens1, tokens3))

    def test_determinism_rank_outliers(self):
        snapshot_data = {
            "$schema_version": 2,
            "fetch_meta": {
                "timestamp": "2026-08-20T00:00:00Z",
                "unit_spent": 5,
                "unit_budget": 30,
                "degraded": False,
                "channel_count": 3
            },
            "ref_baselines": [
                {"channel_id": "UC_A", "channel_title": "채널A", "median_vph": 100.0, "sample_count": 10},
                {"channel_id": "UC_B", "channel_title": "채널B", "median_vph": 150.0, "sample_count": 12},
                {"channel_id": "UC_C", "channel_title": "채널C", "median_vph": 200.0, "sample_count": 15}
            ],
            "outliers": [
                {
                    "video_id": "vid_01",
                    "channel_id": "UC_A",
                    "channel_title": "채널A",
                    "title": "2026년 부동산 폭락 시나리오 총정리",
                    "views": 500000,
                    "vph": 1200.0,
                    "ratio": 12.0,
                    "age_days": 5.0
                },
                {
                    "video_id": "vid_02",
                    "channel_id": "UC_B",
                    "channel_title": "채널B",
                    "title": "부동산 폭락 현실화 2026 충격 경고",
                    "views": 420000,
                    "vph": 1500.0,
                    "ratio": 10.0,
                    "age_days": 7.0
                },
                {
                    "video_id": "vid_03",
                    "channel_id": "UC_C",
                    "channel_title": "채널C",
                    "title": "주식 초보 단타 매매 기법 강의",
                    "views": 100000,
                    "vph": 300.0,
                    "ratio": 3.0,
                    "age_days": 2.0
                }
            ]
        }
        
        config_data = {
          "$schema_version": 2,
          "unit_budget": 30,
          "dedup_threshold": 0.8,
          "evergreen_keywords": ["재테크"],
          "signals": {
            "packaging_min_video_views": 400000
          },
          "outlier": {
            "scan_depth": 30,
            "min_baseline_sample": 10,
            "outlier_ratio_min": 2.5,
            "outlier_strength_min": 8.0,
            "cross_channel_min": 2,
            "recency_days": 45,
            "freshness_days": 14,
            "cluster_threshold": 0.3
          },
          "portfolio": {
            "formats": [
              {"name": "설명형", "keywords": ["방법", "강의", "정리"]},
              {"name": "사례해부형", "keywords": ["폭락", "시나리오"]}
            ]
          },
          "policy": {
            "inauthentic_veto": [],
            "kr_defamation_veto": ["사기꾼"],
            "tragedy_adjacency_veto": ["참사"]
          }
        }
        
        with tempfile.NamedTemporaryFile("w+", delete=False) as f_ledger:
            ledger_path = Path(f_ledger.name)
            
        try:
            # 실행 1회
            res1 = rank_outliers(snapshot_data, config_data, ledger_path)
            json1 = json.dumps(res1, indent=2, ensure_ascii=False, sort_keys=True)
            
            # 실행 2회
            res2 = rank_outliers(snapshot_data, config_data, ledger_path)
            json2 = json.dumps(res2, indent=2, ensure_ascii=False, sort_keys=True)
            
            # 완벽한 바이트 일치성 검증 (결정론)
            self.assertEqual(json1, json2)
            
            # 후보 및 탈락 목록 검증
            self.assertEqual(len(res1["candidates"]), 1)
            cand = res1["candidates"][0]
            self.assertTrue(cand["signals_fired"]["outlier_strength"])
            self.assertTrue(cand["signals_fired"]["cross_channel"])
            self.assertTrue(cand["signals_fired"]["freshness"])
            self.assertTrue(cand["signals_fired"]["packaging_views"])
            self.assertEqual(cand["signal_agreement_count"], 4)
            self.assertEqual(cand["matched_format"], "사례해부형")
            self.assertEqual(cand["prior_confidence"], "high")
            
            # outlier_strength_min 미달 영상이 excluded에 있는지 검증
            self.assertEqual(len(res1["excluded"]), 1)
            exc = res1["excluded"][0]
            self.assertFalse(exc["signals_fired"]["outlier_strength"])
        finally:
            if ledger_path.exists():
                ledger_path.unlink()

    def test_degraded_snapshot_rejection(self):
        degraded_snap = {
            "$schema_version": 2,
            "fetch_meta": {
                "timestamp": "2026-08-20T00:00:00Z",
                "unit_spent": 30,
                "degraded": True
            },
            "ref_baselines": [],
            "outliers": []
        }
        config_data = {"$schema_version": 2}
        with self.assertRaises(SystemExit) as cm:
            rank_outliers(degraded_snap, config_data, Path("dummy_ledger.jsonl"))
        self.assertEqual(cm.exception.code, 2)

if __name__ == "__main__":
    unittest.main()
