import os
import unittest
from ai_company.tools.video_compositor import wrap_text_lines, create_subtitles
from ai_company.tools.auto_tts import detect_language
from ai_company.tools.threads_api import ThreadsApiTool

class TestTools(unittest.TestCase):
    def test_wrap_text_lines(self):
        long_text = '이것은 매우 긴 문장으로 25자가 넘어가기 때문에 스마트하게 여러 줄로 분할되어야 합니다.'
        chunks = wrap_text_lines(long_text, max_chars=25)
        self.assertTrue(len(chunks) > 1)
        for c in chunks:
            self.assertTrue(len(c) <= 25)

    def test_detect_language(self):
        self.assertEqual(detect_language('안녕하세요'), 'ko')
        self.assertEqual(detect_language('Hello World'), 'en')

    def test_threads_api_staging_mode(self):
        tool = ThreadsApiTool()
        res = tool.publish_text('테스트 스레드 본문')
        if not tool.is_configured():
            self.assertEqual(res.get('status'), 'STAGED_READY')

if __name__ == '__main__':
    unittest.main()
