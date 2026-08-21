import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.sns.queue_db import QueueDB
from scripts.sns.exporter import SNSExporter
from scripts.sns.tavily_scout import TavilyScout
from scripts.sns.jina_verifier import JinaVerifier

class TestSNSPipeline(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_queue.db"
        self.output_path = Path(self.temp_dir.name) / "output"
        self.db = QueueDB(self.db_path)
        self.exporter = SNSExporter(self.output_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_queue_lifecycle(self):
        # 1. Add draft
        item_id = self.db.add_draft(
            scheduled_date="2026-08-25",
            category="AI 생산성",
            topic="Claude Code 1인 기업 워크플로우",
            cover_title="개발 지식 없이 혼자 SaaS 만드는 법",
            slides=[
                {
                    "slide_num": 1,
                    "headline": "1. 기획부터 배포까지",
                    "content": "Claude Code를 활용하면 터미널에서 즉시 앱이 빌드됩니다.",
                    "whisk_prompt": "Minimalist 2D vector illustration of programmer at desk, clean flat style"
                },
                {
                    "slide_num": 2,
                    "headline": "2. 검증의 중요성",
                    "content": "Jina AI와 Tavily로 실시간 팩트체크를 거칩니다.",
                    "whisk_prompt": "Minimalist 2D vector illustration of digital shield and checkmarks"
                }
            ],
            thread_text="개발 몰라도 1인 창업 가능한 시대가 왔습니다.\n- 핵심 1\n- 핵심 2\n자세한 내용은 본문 참조.",
            core_claims=["Tavily 무료 한도는 월 1000회", "Jina Reader는 무료 이용 가능"],
            source_urls=["https://tavily.com", "https://jina.ai"],
        )
        self.assertIsInstance(item_id, int)

        # 2. Get item
        item = self.db.get_item(item_id)
        self.assertIsNotNone(item)
        self.assertEqual(item["status"], "DRAFT_SCHEDULED")
        self.assertEqual(len(item["slides"]), 2)
        self.assertEqual(len(item["core_claims"]), 2)

        # 3. Get items by date
        items = self.db.get_items_by_date("2026-08-25")
        self.assertEqual(len(items), 1)

        # 4. Update verification status
        self.db.update_verification_result(
            item_id=item_id,
            status="VERIFIED_READY",
            verification_log=json.dumps({"diff_summary": "검증 완료: 모든 사실 일치"}),
        )
        updated_item = self.db.get_item(item_id)
        self.assertEqual(updated_item["status"], "VERIFIED_READY")

    def test_export_pipeline(self):
        item_id = self.db.add_draft(
            scheduled_date="2026-08-25",
            category="AI 툴",
            topic="Whisk 이미지 자동화",
            cover_title="카드뉴스 이미지 1초만에 뽑는 비결",
            slides=[
                {
                    "slide_num": 1,
                    "headline": "Whisk 자동화",
                    "content": "Puppeteer로 일괄 생성",
                    "whisk_prompt": "Minimalist 2D illustration of artist studio"
                }
            ],
            thread_text="Whisk 이미지 자동화 스레드 본문",
            core_claims=["Whisk는 구글 랩스에서 제공"],
            source_urls=["https://labs.google/whisk"],
        )

        batch_dir = self.exporter.export_date_batch("2026-08-25", db=self.db)
        self.assertTrue(batch_dir.exists())
        self.assertTrue((batch_dir / "REPORT.md").exists())

        # Check subfolder files
        subdirs = [p for p in batch_dir.iterdir() if p.is_dir()]
        self.assertEqual(len(subdirs), 1)
        target_sub = subdirs[0]

        self.assertTrue((target_sub / "whisk_prompts.txt").exists())
        self.assertTrue((target_sub / "cardnews_slides.md").exists())
        self.assertTrue((target_sub / "threads_post.txt").exists())
        self.assertTrue((target_sub / "metadata.json").exists())

        prompts_content = (target_sub / "whisk_prompts.txt").read_text()
        self.assertIn("Minimalist 2D illustration of artist studio", prompts_content)

        slides_content = (target_sub / "cardnews_slides.md").read_text()
        self.assertIn("카드뉴스 이미지 1초만에 뽑는 비결", slides_content)

        threads_content = (target_sub / "threads_post.txt").read_text()
        self.assertIn("Whisk 이미지 자동화 스레드 본문", threads_content)

    def test_jina_verifier_auto_patch(self):
        verifier = JinaVerifier(gemini_api_key="mock_key")
        verifier.client = MagicMock()
        verifier.fetch_jina_search = MagicMock(return_value="Latest news: Price is now $25 instead of $20.")
        verifier.fetch_jina_reader = MagicMock(return_value="Official pricing page: $25/mo.")

        # Mock Gemini verification response
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "verdict": "AUTO_PATCHED",
            "diff_summary": "가격 변동 확인: $20 -> $25로 교정",
            "reason": "공식 페이지 가격 인상 반영",
            "patched_cover_title": "월 25달러로 누리는 AI 혁신",
            "patched_slides": [
                {
                    "slide_num": 1,
                    "headline": "가격 인상 안내",
                    "content": "월 25달러로 변경되었습니다.",
                    "whisk_prompt": "Minimalist 2D illustration"
                }
            ],
            "patched_thread_text": "최신 가격 정보: 월 25달러로 변경되었습니다."
        })
        verifier.client.models.generate_content.return_value = mock_response

        item_id = self.db.add_draft(
            scheduled_date="2026-08-25",
            category="가격 정보",
            topic="AI 툴 가격",
            cover_title="월 20달러 AI 툴",
            slides=[{"slide_num": 1, "headline": "구버전", "content": "20달러입니다.", "whisk_prompt": "prompt"}],
            thread_text="20달러 스레드",
            core_claims=["가격은 월 20달러"],
            source_urls=["https://example.com"],
        )

        res = verifier.verify_and_update_item(item_id, db=self.db)
        self.assertEqual(res["status"], "AUTO_PATCHED")
        self.assertIn("25", res["diff_summary"])

        patched_item = self.db.get_item(item_id)
        self.assertEqual(patched_item["status"], "AUTO_PATCHED")
        self.assertEqual(patched_item["cover_title"], "월 25달러로 누리는 AI 혁신")
        self.assertIn("25달러", patched_item["thread_text"])

    def test_key_pool_quota_shield(self):
        from scripts.sns.config import KeyPoolManager

        pool = KeyPoolManager()
        pool.daily_ceo_limit = 100
        pool.ceo_max_borrow_percent = 80
        pool.max_borrow_calls = 80  # 80% limit -> 20% reserved for CEO

        # 1. Initial key mapping
        with patch.dict("os.environ", {"GEMINI_API_KEY_1": "key_ceo", "GEMINI_API_KEY_2": "key_mgr", "GEMINI_API_KEY_3": "key_worker"}):
            k3, label3 = pool.get_initial_key("worker")
            self.assertEqual(label3, "Key 3 (실무사원)")

        # 2. Smart fallback borrow up to 80%
        with patch.dict("os.environ", {"GEMINI_API_KEY_1": "key_ceo", "GEMINI_API_KEY_2": "", "GEMINI_API_KEY_3": "key_worker"}):
            # Borrow 80 times
            for _ in range(80):
                fb_key, fb_label = pool.get_fallback_key("worker")
                self.assertEqual(fb_key, "key_ceo")

            # 81st attempt should be blocked to protect the remaining 20% for CEO
            fb_blocked, blocked_label = pool.get_fallback_key("worker")
            self.assertIsNone(fb_blocked)
            self.assertIn("20% 안전 비축분", blocked_label)

    def test_threads_publisher(self):
        from scripts.sns.threads_publisher import ThreadsPublisher

        # 1. Without API key -> Staging mode
        pub = ThreadsPublisher(user_id="", access_token="")
        self.assertFalse(pub.is_configured())
        res = pub.publish_post("테스트 스레드 본문입니다.")
        self.assertEqual(res["status"], "STAGED_READY")
        self.assertIn("입력하면", res["message"])

        # 2. Mock API call when configured
        pub_configured = ThreadsPublisher(user_id="user123", access_token="token_xyz")
        self.assertTrue(pub_configured.is_configured())
        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.side_effect = [
                {"id": "container_999"},  # Container creation
                {"id": "post_777"},       # Publish
            ]
            pub_res = pub_configured.publish_post("성공적인 스레드 글")
            self.assertTrue(pub_res["success"])
            self.assertEqual(pub_res["post_id"], "post_777")
            self.assertEqual(pub_res["status"], "PUBLISHED")

if __name__ == "__main__":
    unittest.main()
