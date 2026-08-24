# Gates: Leaf 1.4.2.1 auto_tts 24kHz Mono Fallbacks
Scope: 24kHz mono resampling and language detection.

- [x] G1: detect_language function
  CHECK: PYTHONPATH=. python3 -c "from ai_company.tools.auto_tts import detect_language; print('LANG_KO:', detect_language('안녕하세요'), 'LANG_EN:', detect_language('Hello'))"
  EXPECT: LANG_KO: ko LANG_EN: en
  EVIDENCE: LANG_KO: ko LANG_EN: en
