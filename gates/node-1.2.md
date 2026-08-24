# Gates: Branch 1.2 Slack Socket Mode & Daemon Lifecycle
Scope: Slack post_as_agent, file upload fallback, run_pipeline error isolation, and daemon stability.

- [x] G1: Slack channel mapping and helper sanity
  CHECK: PYTHONPATH=. python3 -c "from ai_company.main import CHANNEL_MAP, extract_compact_summary; print('SUMMARY:', len(extract_compact_summary('CEO', 'test summary')) > 0)"
  EXPECT: SUMMARY: True
  EVIDENCE: 2026-08-24 08:53:15,871 [INFO] Pinned ORT_DYLIB_PATH to bundled ONNX Runtime: /opt/homebrew/lib/python3.11/site-packages/onnxruntime/capi/libonnxruntime.1.26.0.dylib | 2026-08-24 08:53:15,885 [INFO] H
