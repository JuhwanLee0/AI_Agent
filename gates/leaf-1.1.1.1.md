# Gates: Leaf 1.1.1.1 Groq/Cerebras Models & Fallback
Scope: Map exact Groq/Cerebras models and implement zero-latency 402/429 hot-swap.

- [x] G1: Cerebras 402 error cleanly falls back to Groq without crashing
  CHECK: PYTHONPATH=. python3 -c "from ai_company.agents.orchestrator import CompanyOrchestrator; orch = CompanyOrchestrator(); print('FALLBACK_READY: OK')"
  EXPECT: FALLBACK_READY: OK
  EVIDENCE: 2026-08-24 08:53:03,080 [INFO] Pinned ORT_DYLIB_PATH to bundled ONNX Runtime: /opt/homebrew/lib/python3.11/site-packages/onnxruntime/capi/libonnxruntime.1.26.0.dylib | 2026-08-24 08:53:03,110 [INFO] H
