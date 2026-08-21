import unittest
import sys
import json
import tempfile
from pathlib import Path

# scripts 디렉토리를 import 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from check_topic import check_topic_gate

class TestCheckTopic(unittest.TestCase):
    def test_check_topic_veto_rules(self):
        config_data = {
            "dedup_threshold": 0.8,
            "policy": {
                "inauthentic_veto": ["수익보장", "100% 확실"],
                "kr_defamation_veto": ["사기꾼", "범죄자"],
                "tragedy_adjacency_veto": ["참사", "사망 사고"]
            }
        }
        
        with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as f_ledger:
            ledger_path = Path(f_ledger.name)
            f_ledger.write(json.dumps({"topic": "2026년 부동산 시장 전망과 투자 전략"}) + "\n")
            f_ledger.flush()
            
        try:
            # 1. 정상 통과 케이스
            res_pass = check_topic_gate("초보자를 위한 연금 저축 펀드 가이드", config_data, ledger_path)
            self.assertTrue(res_pass["passed"])
            self.assertEqual(res_pass["veto_count"], 0)
            
            # 2. 비진정성 거부권 발동
            res_inauth = check_topic_gate("월 1000만원 수익보장 비법 공개", config_data, ledger_path)
            self.assertFalse(res_inauth["passed"])
            self.assertTrue(any("비진정성" in r for r in res_inauth["veto_reasons"]))
            
            # 3. 명예훼손 거부권 발동
            res_defam = check_topic_gate("유명 유튜버 사기꾼 폭로 영상", config_data, ledger_path)
            self.assertFalse(res_defam["passed"])
            self.assertTrue(any("명예훼손" in r for r in res_defam["veto_reasons"]))
            
            # 4. 참사 인접 거부권 발동
            res_trag = check_topic_gate("대형 참사 이후 대처 방안 분석", config_data, ledger_path)
            self.assertFalse(res_trag["passed"])
            self.assertTrue(any("참사" in r for r in res_trag["veto_reasons"]))
            
            # 5. 기존 발행 주제 중복 거부권 발동
            res_dup = check_topic_gate("2026년 부동산 시장 전망 투자 전략", config_data, ledger_path)
            self.assertFalse(res_dup["passed"])
            self.assertTrue(any("기존 발행 주제 중복" in r for r in res_dup["veto_reasons"]))
            
        finally:
            if ledger_path.exists():
                ledger_path.unlink()

if __name__ == "__main__":
    unittest.main()
