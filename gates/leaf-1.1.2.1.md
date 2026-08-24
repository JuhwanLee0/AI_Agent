# Gates: Leaf 1.1.2.1 Config & KeyPool Modernization
Scope: Remove legacy Gemini settings from scripts/sns/config.py and adapt to Groq/Cerebras.

- [x] G1: KeyPoolManager supports Groq keys and safe rate limit delay
  CHECK: PYTHONPATH=. python3 -c "from scripts.sns.config import KeyPoolManager, get_safe_delay; pool = KeyPoolManager(); print('DELAY:', get_safe_delay('worker') > 0)"
  EXPECT: DELAY: True
  EVIDENCE: DELAY: True
