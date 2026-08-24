# Plan: AI Agent System Full Refactor & Error Elimination (Tree 5)

Depth: tree 5   Mode: orchestrated
Budget note: Complete zero-defect refactor across LLM providers, Slack Socket Mode, SNS pipeline, and 17 agents.

## Contract

Decided BEFORE fan-out:
- Interfaces:
  - CompanyOrchestrator.call_agent_llm(agent_name, conversation_history) -> returns clean str without <think> tags
  - KeyPoolManager.get_available_key(role) -> returns (api_key, model_name)
  - post_as_agent(channel, agent_name, text, thread_ts, blocks) -> thread-safe slack dispatch with auto-join
  - ThreadsApiTool.publish_text(text, reply_to_id) -> returns {"success": bool, "status": str, ...}
- Data ownership:
  - Branch 1.1: ai_company/agents/orchestrator.py, scripts/sns/config.py, scripts/sns/jina_verifier.py, scripts/sns/tavily_scout.py
  - Branch 1.2: ai_company/main.py, main.py
  - Branch 1.3: ai_company/instructions/*, ai_company/skills/*, ai_company/memory/*
  - Branch 1.4: ai_company/tools/*
  - Branch 1.5: tests/*, GATES.md
- Naming and conventions: Python 3.11 type hints, UTF-8 encoding, zero-defect test-driven validation.

## Tree

- 1 Root: AI Agent System Full Refactor & Error Elimination
  - 1.1 Branch: LLM Cloud Engine & Quota Shield ......... gates/node-1.1.md
    - 1.1.1 Sub-branch: Orchestrator LLM Engine
      - 1.1.1.1 Leaf: Groq/Cerebras Models & Fallback ... gates/leaf-1.1.1.1.md
        Owns: ai_company/agents/orchestrator.py
        Needs: -
        Tier: smart
      - 1.1.1.2 Leaf: Think Tag Stripper & Tool Parser .. gates/leaf-1.1.1.2.md
        Owns: ai_company/agents/orchestrator.py
        Needs: 1.1.1.1
        Tier: smart
    - 1.1.2 Sub-branch: SNS Pipeline LLM & Legacy Cleanup
      - 1.1.2.1 Leaf: Config & KeyPool Modernization .... gates/leaf-1.1.2.1.md
        Owns: scripts/sns/config.py
        Needs: -
        Tier: fast
      - 1.1.2.2 Leaf: JinaVerifier & TavilyScout Fixes .. gates/leaf-1.1.2.2.md
        Owns: scripts/sns/jina_verifier.py, scripts/sns/tavily_scout.py
        Needs: 1.1.2.1
        Tier: fast
  - 1.2 Branch: Slack Socket Mode & Daemon Lifecycle ..... gates/node-1.2.md
    - 1.2.1 Sub-branch: Slack Messaging & Channel Safety
      - 1.2.1.1 Leaf: post_as_agent & Channel Auto-Join . gates/leaf-1.2.1.1.md
        Owns: ai_company/main.py
        Needs: 1.1.1.1
        Tier: smart
      - 1.2.1.2 Leaf: upload_project_files Fallback ..... gates/leaf-1.2.1.2.md
        Owns: ai_company/main.py
        Needs: 1.2.1.1
        Tier: fast
    - 1.2.2 Sub-branch: Async Pipeline & Master Entrypoint
      - 1.2.2.1 Leaf: run_pipeline Error Isolation ...... gates/leaf-1.2.2.1.md
        Owns: ai_company/main.py
        Needs: 1.2.1.1
        Tier: smart
      - 1.2.2.2 Leaf: Master main.py Daemon Defense ..... gates/leaf-1.2.2.2.md
        Owns: main.py
        Needs: 1.2.2.1
        Tier: fast
  - 1.3 Branch: 17-Agent Instruction & 5-Layer Stack ..... gates/node-1.3.md
    - 1.3.1 Sub-branch: Instruction & Prompt Optimization
      - 1.3.1.1 Leaf: Instruction Path Normalization .... gates/leaf-1.3.1.1.md
        Owns: ai_company/instructions/instruction.md
        Needs: -
        Tier: fast
      - 1.3.1.2 Leaf: 5-Layer Intelligence Compliance .. gates/leaf-1.3.1.2.md
        Owns: ai_company/instructions/ceo_instruction.md, ai_company/instructions/dev_instruction.md, ai_company/instructions/marketing_instruction.md, ai_company/instructions/media_instruction.md
        Needs: 1.3.1.1
        Tier: smart
    - 1.3.2 Sub-branch: Memory & Graph Persistence
      - 1.3.2.1 Leaf: State & Memory Integrity .......... gates/leaf-1.3.2.1.md
        Owns: ai_company/memory/agent_memory.json, .planning/STATE.md, .planning/graphs/graph.json
        Needs: 1.3.1.2
        Tier: fast
  - 1.4 Branch: Autonomous Tooling & Media Pipeline ...... gates/node-1.4.md
    - 1.4.1 Sub-branch: Browser & SNS Tools
      - 1.4.1.1 Leaf: PlaywrightBrowser Memory Safety ... gates/leaf-1.4.1.1.md
        Owns: ai_company/tools/playwright_browser.py
        Needs: -
        Tier: smart
      - 1.4.1.2 Leaf: ThreadsApiTool 500-char Chaining .. gates/leaf-1.4.1.2.md
        Owns: ai_company/tools/threads_api.py
        Needs: -
        Tier: fast
    - 1.4.2 Sub-branch: TTS & Video Compositor
      - 1.4.2.1 Leaf: auto_tts 24kHz Mono Fallbacks ..... gates/leaf-1.4.2.1.md
        Owns: ai_company/tools/auto_tts.py
        Needs: -
        Tier: fast
      - 1.4.2.2 Leaf: video_compositor SRT Sync ......... gates/leaf-1.4.2.2.md
        Owns: ai_company/tools/video_compositor.py
        Needs: 1.4.2.1
        Tier: fast
  - 1.5 Branch: Testing, Verification & Ledger Proof ..... gates/node-1.5.md
    - 1.5.1 Sub-branch: Unit Test Suite 100% Pass
      - 1.5.1.1 Leaf: SNS Pipeline Unit Tests ........... gates/leaf-1.5.1.1.md
        Owns: tests/test_sns_pipeline.py
        Needs: 1.1.2.1, 1.1.2.2
        Tier: smart
      - 1.5.1.2 Leaf: Core Orchestrator & Tool Tests .... gates/leaf-1.5.1.2.md
        Owns: tests/test_orchestrator.py, tests/test_tools.py, tests/test_check_topic.py, tests/test_scout_rank.py
        Needs: 1.1.1.1, 1.4.1.1
        Tier: smart
    - 1.5.2 Sub-branch: E2E Simulation & Ledger Finalization
      - 1.5.2.1 Leaf: E2E Pipeline & Slack Auth Proof ... gates/leaf-1.5.2.1.md
        Owns: GATES.md
        Needs: 1.5.1.1, 1.5.1.2
        Tier: smart
      - 1.5.2.2 Leaf: Unlazy Gate-Check Ledger Proof .... gates/leaf-1.5.2.2.md
        Owns: GATES.md
        Needs: 1.5.2.1
        Tier: fast

## Dispatch schedule

- Wave 1: 1.1.1.1, 1.1.2.1, 1.3.1.1, 1.4.1.1, 1.4.1.2, 1.4.2.1
- Wave 2: 1.1.1.2, 1.1.2.2, 1.2.1.1, 1.3.1.2, 1.4.2.2
- Wave 3: 1.2.1.2, 1.2.2.1, 1.3.2.1, 1.5.1.1, 1.5.1.2
- Wave 4: 1.2.2.2, 1.5.2.1
- Wave 5: 1.5.2.2 (Final gate check)

## Status log

- 2026-08-23T20:33:00Z plan written, contract fixed, dispatching Tree 5 waves
