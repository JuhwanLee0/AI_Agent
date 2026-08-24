# Gates: Leaf 1.4.2.2 video_compositor SRT Sync
Scope: wrap_text_lines and subtitle generation.

- [x] G1: wrap_text_lines functionality
  CHECK: PYTHONPATH=. python3 -c "from ai_company.tools.video_compositor import wrap_text_lines; print('WRAP:', len(wrap_text_lines('긴 문장 분할 테스트입니다.', max_chars=10)) > 1)"
  EXPECT: WRAP: True
  EVIDENCE: WRAP: True
