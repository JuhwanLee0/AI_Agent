# Gates: Branch 1.4 Autonomous Tooling & Media Pipeline
Scope: Playwright, Threads, TTS, Video Compositor tools verification.

- [x] G1: Tools module readiness
  CHECK: PYTHONPATH=. python3 -c "from ai_company.tools.threads_api import ThreadsApiTool; from ai_company.tools.playwright_browser import PlaywrightBrowser; print('TOOLS_MOD_OK: True')"
  EXPECT: TOOLS_MOD_OK: True
  EVIDENCE: TOOLS_MOD_OK: True
