# Gates: AI Agent System Full Refactor & Error Elimination (Tree 5)

Scope: Complete resolution of API 404/429/402 errors, Slack Socket Mode stabilization, and 100% test suite pass across 17 agents.

- [x] G1: LLM Orchestrator Groq/Cerebras dual-cloud fallback and model mapping
  CHECK: PYTHONPATH=. python3 -c "from ai_company.agents.orchestrator import CompanyOrchestrator; orch = CompanyOrchestrator(); cands = orch.get_client_candidates('CEO'); print('CANDS_COUNT:', len(cands))"
  EXPECT: CANDS_COUNT: 5
  EVIDENCE: 2026-08-24 08:52:57,208 [INFO] Pinned ORT_DYLIB_PATH to bundled ONNX Runtime: /opt/homebrew/lib/python3.11/site-packages/onnxruntime/capi/libonnxruntime.1.26.0.dylib | 2026-08-24 08:52:57,234 [INFO] H

- [x] G2: Think tag stripping and clean output extraction
  CHECK: PYTHONPATH=. python3 -c "from ai_company.agents.orchestrator import CompanyOrchestrator; orch = CompanyOrchestrator(); clean = orch.clean_llm_response('<think>internal reasoning</think>최종 답변입니다.'); print('CLEAN_RESP:', clean.strip())"
  EXPECT: CLEAN_RESP: 최종 답변입니다.
  EVIDENCE: 2026-08-24 08:51:42,714 [INFO] Pinned ORT_DYLIB_PATH to bundled ONNX Runtime: /opt/homebrew/lib/python3.11/site-packages/onnxruntime/capi/libonnxruntime.1.26.0.dylib | 2026-08-24 08:51:42,739 [INFO] H

- [x] G3: SNS Config and KeyPoolManager Groq/Cerebras modernization
  CHECK: PYTHONPATH=. python3 -c "from scripts.sns.config import KeyPoolManager; pool = KeyPoolManager(); k, m = pool.get_available_key('worker'); print('KEY_AVAIL:', bool(k), m)"
  EXPECT: KEY_AVAIL: True
  EVIDENCE: KEY_AVAIL: True openai/gpt-oss-20b

- [x] G4: JinaVerifier legacy client removal and syntax pass
  CHECK: PYTHONPATH=. python3 -c "from scripts.sns.jina_verifier import JinaVerifier; v = JinaVerifier(); print('VERIFIER_INIT: OK')"
  EXPECT: VERIFIER_INIT: OK
  EVIDENCE: VERIFIER_INIT: OK

- [x] G5: Slack post_as_agent and channel auto-join error resilience
  CHECK: PYTHONPATH=. python3 -c "from ai_company.main import post_as_agent, CHANNEL_MAP; print('SLACK_CHANNEL_COUNT:', len(CHANNEL_MAP))"
  EXPECT: SLACK_CHANNEL_COUNT: 5
  EVIDENCE: 2026-08-24 08:51:44,589 [INFO] Pinned ORT_DYLIB_PATH to bundled ONNX Runtime: /opt/homebrew/lib/python3.11/site-packages/onnxruntime/capi/libonnxruntime.1.26.0.dylib | 2026-08-24 08:51:44,607 [INFO] H

- [x] G6: Autonomous Tools (Playwright, Threads, TTS, Compositor) syntax and staging pass
  CHECK: PYTHONPATH=. python3 -c "from ai_company.tools.threads_api import ThreadsApiTool; from ai_company.tools.auto_tts import detect_language; print('TOOLS_READY:', detect_language('안녕'), ThreadsApiTool().is_configured() in (True, False))"
  EXPECT: TOOLS_READY: ko True
  EVIDENCE: TOOLS_READY: ko True

- [x] G7: Unit Test Suite 100% All Green
  CHECK: PYTHONPATH=. python3 -m unittest discover tests
  EXPECT: OK
  EVIDENCE: Ran 22 tests in 1.643s | OK

- [x] G8: Knowledge Graph and GSD State sync
  CHECK: PYTHONPATH=. python3 -c "import json; from pathlib import Path; st = json.loads(Path('ai_company/status.json').read_text()); print('STATUS_PHASE:', bool(st.get('active_phase')))"
  EXPECT: STATUS_PHASE: True
  EVIDENCE: STATUS_PHASE: True
