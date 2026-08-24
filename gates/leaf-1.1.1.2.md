# Gates: Leaf 1.1.1.2 Think Tag Stripper & Tool Parser
Scope: Strip <think> tags from Qwen 3.6 responses and parse [TOOL:...] parameters robustly.

- [x] G1: Think tag stripper functions properly
  CHECK: PYTHONPATH=. python3 -c "from ai_company.agents.orchestrator import CompanyOrchestrator; orch = CompanyOrchestrator(); print(orch.clean_llm_response('<think>deep thought</think>Actual Output'))"
  EXPECT: Actual Output
  EVIDENCE: 2026-08-24 08:53:03,378 [INFO] Pinned ORT_DYLIB_PATH to bundled ONNX Runtime: /opt/homebrew/lib/python3.11/site-packages/onnxruntime/capi/libonnxruntime.1.26.0.dylib | 2026-08-24 08:53:03,415 [INFO] H
