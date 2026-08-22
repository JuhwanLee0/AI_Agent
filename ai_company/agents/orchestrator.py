import os
import re
import json
import time
import logging
import threading
import subprocess
from typing import Dict, Any, List, Optional, Tuple
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Orchestrator")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTRUCTIONS_DIR = os.path.join(BASE_DIR, "instructions")
SKILLS_DIR = os.path.join(BASE_DIR, "skills")
STATUS_FILE = os.path.join(BASE_DIR, "status.json")
MEMORY_DIR = os.path.join(BASE_DIR, "memory")
PLANNING_DIR = os.path.join(BASE_DIR, ".planning")
GRAPHS_DIR = os.path.join(PLANNING_DIR, "graphs")
PHASES_DIR = os.path.join(PLANNING_DIR, "phases")

os.makedirs(MEMORY_DIR, exist_ok=True)
os.makedirs(PLANNING_DIR, exist_ok=True)
os.makedirs(GRAPHS_DIR, exist_ok=True)
os.makedirs(PHASES_DIR, exist_ok=True)


# ----------------------------------------------------
# 1. Headroom-AI Token Optimization Integration
# ----------------------------------------------------
class HeadroomOptimizer:
    """
    Headroom-AI Token Optimizer:
    - Minimizes LLM spend and token bloat across system prompts and message history.
    """
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._headroom = None
        if self.enabled:
            try:
                import headroom
                self._headroom = headroom
                logger.info("Headroom-AI optimizer successfully initialized.")
            except ImportError:
                logger.warning("headroom-ai is not installed in current Python environment. Proceeding with raw context.")

    def optimize_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """대화 메시지 리스트에 대해 토큰 압축 및 최적화 수행"""
        if not self.enabled or not self._headroom or not messages:
            return messages
        try:
            res = self._headroom.compress(messages)
            if hasattr(res, 'messages') and isinstance(res.messages, list):
                clean_res = []
                for m in res.messages:
                    if isinstance(m, dict) and "role" in m and "content" in m:
                        clean_res.append({"role": str(m["role"]), "content": str(m["content"])})
                    elif hasattr(m, "role") and hasattr(m, "content"):
                        clean_res.append({"role": str(m.role), "content": str(m.content)})
                if clean_res:
                    saved = getattr(res, 'tokens_saved', 0)
                    if saved > 0:
                        logger.info(f"[Headroom-AI] Optimized context: saved {saved} tokens.")
                    return clean_res
            return messages
        except Exception as e:
            logger.debug(f"[Headroom-AI] Message optimization pass-through: {e}")
            return messages

    def optimize_text(self, text: str) -> str:
        """단일 텍스트 문자열에 대한 헤드룸 최적화"""
        if not self.enabled or not self._headroom or not text:
            return text
        try:
            msg_format = [{"role": "system", "content": text}]
            res = self._headroom.compress(msg_format)
            if hasattr(res, 'messages') and isinstance(res.messages, list) and len(res.messages) > 0:
                saved = getattr(res, 'tokens_saved', 0)
                if saved > 0:
                    logger.info(f"[Headroom-AI] Optimized system prompt: saved {saved} tokens.")
                return res.messages[0].get("content", text)
            return text
        except Exception as e:
            logger.debug(f"[Headroom-AI] Text optimization pass-through: {e}")
            return text


# ----------------------------------------------------
# 2. Claude-Mem Persistent Memory Integration
# ----------------------------------------------------
class ClaudeMemManager:
    """
    claude-mem persistent memory bridge:
    - Queries past session observations, rules, and project learnings.
    - Saves key hand-off summaries and decisions to persistent memory (agent_memory.json).
    """
    def __init__(self, memory_file: str = os.path.join(MEMORY_DIR, "agent_memory.json")):
        self.memory_file = memory_file
        self._io_lock = threading.Lock()
        self.local_memories: Dict[str, List[Dict[str, str]]] = self._load_local_memory()

    def _load_local_memory(self) -> Dict[str, List[Dict[str, str]]]:
        if os.path.exists(self.memory_file):
            try:
                with open(self.memory_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading local memory: {e}")
        return {"global": [], "CEO": [], "dev": [], "marketing": [], "media": [], "business": []}

    def _save_local_memory(self):
        with self._io_lock:
            try:
                with open(self.memory_file, "w", encoding="utf-8") as f:
                    json.dump(self.local_memories, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"Error saving local memory: {e}")

    def query_claude_mem(self, query: str) -> str:
        """claude-mem CLI를 통한 세션 메모리 검색"""
        try:
            cmd = ["npx", "--yes", "claude-mem", "search", query]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception as e:
            logger.debug(f"claude-mem CLI search skipped: {e}")
        return ""

    def get_memory_context(self, department: str, agent_name: str) -> str:
        """에이전트에게 주입할 장기 기억 컨텍스트 추출 (초경량 압축)"""
        memories = []
        
        # 1. Global & Department memory (최근 2개만 유지하여 토큰 절감)
        if "global" in self.local_memories:
            for item in self.local_memories["global"][-2:]:
                memories.append(f"- [전사]: {item.get('text', '')}")
        
        if department in self.local_memories:
            for item in self.local_memories[department][-2:]:
                memories.append(f"- [{department}]: {item.get('text', '')}")

        if not memories:
            memories.append("- 축적된 이전 세션 특이사항 없음.")

        return "<claude-mem-context>\n" + "\n".join(memories) + "\n</claude-mem-context>"

    def synthesize_decision_with_groq(self, agent_name: str, full_text: str) -> str:
        """Groq API(llama-3.3-70b / gpt-oss-20b)를 활용하여 긴 활동에서 1~2줄 핵심 결정/학습 기억 자동 추출"""
        groq_key = (os.getenv("GROQ_API_KEY_1") or os.getenv("GROQ_API_KEY_2") or os.getenv("GROQ_API_KEY", "")).strip()
        if not groq_key or len(full_text) < 100:
            return full_text[:200].replace("\n", " ")
        try:
            from openai import OpenAI
            client = OpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1", timeout=8.0)
            res = client.chat.completions.create(
                model="openai/gpt-oss-20b",
                messages=[
                    {"role": "system", "content": "You are a concise memory compressor. Extract exactly 1-2 Korean sentences summarizing the key decisions, architectural rules, or deliverables from this agent output. Output only the summarized text without preamble."},
                    {"role": "user", "content": full_text[:3000]}
                ],
                max_tokens=200,
                temperature=0.3
            )
            if res.choices and res.choices[0].message.content:
                return res.choices[0].message.content.strip()
        except Exception as e:
            logger.debug(f"[claude-mem] Groq memory synthesis fallback: {e}")
        return full_text[:200].replace("\n", " ")

    def record_decision(self, department: str, agent_name: str, observation: str):
        """새로운 결정사항/피드백을 장기 기억에 저장 (Groq 지능형 요약 지원)"""
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 긴 텍스트인 경우 Groq API로 1~2문장 핵심 기억 합성
        if len(observation) > 150:
            observation = self.synthesize_decision_with_groq(agent_name, observation)
            
        entry = {"agent": agent_name, "text": observation, "time": timestamp}
        
        if department not in self.local_memories:
            self.local_memories[department] = []
        self.local_memories[department].append(entry)
        self._save_local_memory()
        logger.info(f"[claude-mem] Recorded Groq-synthesized memory for {agent_name} ({department})")


# ----------------------------------------------------
# 3. GSD (Get Shit Done) Workflow & Phase Manager
# ----------------------------------------------------
class GSDManager:
    """
    GSD (Get Shit Done) Autonomous Situational Dispatch & Phase Manager:
    - Maintains .planning/ROADMAP.md and .planning/STATE.md.
    - Routes multi-step tasks into thin vertical slices (100~300 lines).
    - Injects active milestone and phase contracts into agent contexts.
    """
    def __init__(self, planning_dir: str = PLANNING_DIR):
        self.planning_dir = planning_dir
        self.roadmap_file = os.path.join(self.planning_dir, "ROADMAP.md")
        self.state_file = os.path.join(self.planning_dir, "STATE.md")
        self._ensure_planning_files()

    def _ensure_planning_files(self):
        if not os.path.exists(self.roadmap_file):
            default_roadmap = """# 🗺️ Project Roadmap & Phase Tracking

## Active Milestone: v1.0 AI Company Business Engine

- [x] Phase 0: System Architecture & 16-Agent Persona Setup
- [ ] Phase 1: Core Automation Pipeline (GSD + Graphify + Ponytail Engine)
- [ ] Phase 2: Dual-Engine TTS & Media Rendering Integration
- [ ] Phase 3: Anti-Slop UI/UX Landing & Monetization Payment Gateway
- [ ] Phase 4: Production Deployment & 1GB Swap Optimization
"""
            try:
                with open(self.roadmap_file, "w", encoding="utf-8") as f:
                    f.write(default_roadmap)
            except Exception as e:
                logger.error(f"Failed to create default ROADMAP.md: {e}")

        if not os.path.exists(self.state_file):
            default_state = """# 🧭 GSD Active State

- **Current Milestone**: v1.0 AI Company Business Engine
- **Active Phase**: Phase 1: Core Automation Pipeline
- **Phase Status**: In-Progress
- **Current Mode**: Autonomous Dispatch
- **Recent Decision**: 5대 지능 스택(Headroom, Claude-Mem, GSD, Graphify, Ponytail) 완전 통합
"""
            try:
                with open(self.state_file, "w", encoding="utf-8") as f:
                    f.write(default_state)
            except Exception as e:
                logger.error(f"Failed to create default STATE.md: {e}")

    def get_gsd_state(self) -> str:
        """현재 GSD 실행 상태 읽기"""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except Exception as e:
                logger.error(f"Error reading STATE.md: {e}")
        return "GSD Active State: Initializing"

    def get_gsd_context(self, agent_name: str) -> str:
        """에이전트 프롬프트에 주입할 GSD 컨텍스트 생성"""
        state_content = self.get_gsd_state()
        return f"""<gsd-context>
# GSD (Get Shit Done) Autonomous Situational Context
{state_content}
- **Dispatch Guidance**:
  - 다단계 작업 시 수평 분할 금지, 1회 100~300줄 얇은 수직 슬라이스(Vertical Slice)로 실행.
  - 경량 작업: `gsd-quick` 모드로 즉시 실행 후 상태 갱신.
  - 버그/에러: 5단계 디버깅 프로토콜(`gsd-debug`) 준수.
</gsd-context>"""

    def update_phase_state(self, active_phase: str, phase_status: str, decision: Optional[str] = None):
        """페이즈 상태 갱신 및 STATE.md 저장"""
        state_text = f"""# 🧭 GSD Active State

- **Current Milestone**: v1.0 AI Company Business Engine
- **Active Phase**: {active_phase}
- **Phase Status**: {phase_status}
- **Current Mode**: Autonomous Dispatch
"""
        if decision:
            state_text += f"- **Recent Decision**: {decision}\n"
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                f.write(state_text)
            logger.info(f"[GSD] Updated STATE.md: {active_phase} -> {phase_status}")
        except Exception as e:
            logger.error(f"Error updating STATE.md: {e}")


# ----------------------------------------------------
# 4. Graphify Codebase & Architecture Knowledge Graph
# ----------------------------------------------------
class GraphifyEngine:
    """
    Graphify Codebase Knowledge Graph & Module Relations:
    - Maps codebase files, dependencies, god nodes, and call flows.
    - Stores persistent graph representation in .planning/graphs/graph.json.
    - Injects structural module relationships into Architect, Backend, QA, and Team Lead prompts.
    """
    def __init__(self, graphs_dir: str = GRAPHS_DIR):
        self.graphs_dir = graphs_dir
        self.graph_file = os.path.join(self.graphs_dir, "graph.json")
        self.graph_data: Dict[str, Any] = self._load_or_build_graph()

    def _load_or_build_graph(self) -> Dict[str, Any]:
        if os.path.exists(self.graph_file):
            try:
                with open(self.graph_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading graph.json: {e}")
        return self.build_graph()

    def build_graph(self) -> Dict[str, Any]:
        """코드베이스 및 지침서 디렉토리를 스캔하여 지식 그래프 구축"""
        nodes = []
        edges = []

        # 1. 파일 및 모듈 스캔
        for root, _, files in os.walk(BASE_DIR):
            if any(p in root for p in [".git", "__pycache__", ".venv", "scratch", "output"]):
                continue
            for file in files:
                if file.endswith((".py", ".md", ".json", ".html", ".js")):
                    rel_path = os.path.relpath(os.path.join(root, file), BASE_DIR)
                    file_type = "module" if file.endswith(".py") else "doc" if file.endswith(".md") else "config"
                    nodes.append({
                        "id": rel_path,
                        "type": file_type,
                        "size": os.path.getsize(os.path.join(root, file))
                    })

        # 2. 핵심 관계(Edges) 및 God Nodes 정의
        god_nodes = ["agents/orchestrator.py", "instructions/instruction.md", "main.py"]
        
        # 기본 의존성 엣지 추가
        edges.append({"source": "main.py", "target": "agents/orchestrator.py", "relation": "imports"})
        edges.append({"source": "agents/orchestrator.py", "target": "instructions/instruction.md", "relation": "enforces"})
        edges.append({"source": "agents/orchestrator.py", "target": "instructions/ceo_instruction.md", "relation": "loads"})
        edges.append({"source": "agents/orchestrator.py", "target": "instructions/dev_instruction.md", "relation": "loads"})
        edges.append({"source": "agents/orchestrator.py", "target": "instructions/marketing_instruction.md", "relation": "loads"})
        edges.append({"source": "agents/orchestrator.py", "target": "instructions/media_instruction.md", "relation": "loads"})
        edges.append({"source": "agents/orchestrator.py", "target": ".planning/STATE.md", "relation": "syncs_state"})
        edges.append({"source": "agents/orchestrator.py", "target": "memory/agent_memory.json", "relation": "reads_writes_memory"})

        graph = {
            "version": "2.0",
            "total_nodes": len(nodes),
            "god_nodes": god_nodes,
            "nodes": nodes,
            "edges": edges
        }

        try:
            with open(self.graph_file, "w", encoding="utf-8") as f:
                json.dump(graph, f, ensure_ascii=False, indent=2)
            logger.info(f"[Graphify] Built knowledge graph with {len(nodes)} nodes, {len(edges)} edges.")
        except Exception as e:
            logger.error(f"Error saving graph.json: {e}")

        return graph

    def get_graph_context(self, department: str, agent_name: str) -> str:
        """에이전트에게 주입할 Graphify 아키텍처 의존성 컨텍스트 생성"""
        god_nodes_str = ", ".join(self.graph_data.get("god_nodes", []))
        total_nodes = self.graph_data.get("total_nodes", 0)
        
        return f"""<graphify-context>
# Graphify Codebase Knowledge Graph & Module Relations
- **Total Mapped Nodes**: {total_nodes} files/modules
- **God Nodes (High Connectivity Hubs)**: {god_nodes_str}
- **Architectural Rules**:
  - God Node 수정 시 연결된 하위 모듈의 인터페이스 호환성 사전 검증.
  - 순환 참조(Circular Dependency) 엄격 금지, 단방향 계층 흐름 유지.
</graphify-context>"""


# ----------------------------------------------------
# 5. Ponytail Minimalist & Pragmatic Engineering (YAGNI)
# ----------------------------------------------------
class PonytailAuditor:
    """
    Ponytail Minimalist & Pragmatic Engineering (YAGNI):
    - Blocks over-engineering, code bloat, and unnecessary dependencies.
    - Enforces 500-line module budget and standard libraries priority.
    - Scoreboard metrics: Less Code, Less Cost, More Speed.
    """
    def __init__(self):
        self.max_line_budget = 500

    def get_ponytail_context(self, department: str) -> str:
        """에이전트 프롬프트에 주입할 Ponytail 실용주의 규칙 생성"""
        return f"""<ponytail-context>
# Ponytail Minimalist & Pragmatic Engineering (YAGNI)
- **Core Mantra**: "Less Code, Less Cost, More Speed"
- **YAGNI 원칙**: 현재 요구되지 않는 미래 기능을 추측하여 과도하게 설계(Over-engineering)하지 마십시오.
- **표준 라이브러리 우선**: 불필요한 무거운 외부 패키지 대신 내장 모듈을 최우선 활용.
- **모듈 예산**: 단일 모듈은 {self.max_line_budget}줄 이하를 유지하며 불필요한 추상화 레이어를 배제.
</ponytail-context>"""

    def audit_code_lines(self, file_path: str) -> Dict[str, Any]:
        """단일 파일의 라인 수 및 복잡도 감사"""
        if not os.path.exists(file_path):
            return {"status": "error", "message": "File not found"}
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        count = len(lines)
        is_over = count > self.max_line_budget
        return {
            "file": file_path,
            "lines": count,
            "line_budget": self.max_line_budget,
            "is_over_budget": is_over,
            "verdict": "⚠️ Refactor Required (>500 lines)" if is_over else "✅ Clean & Lean"
        }


# ----------------------------------------------------
# 6. Agent Configuration & Registry
# ----------------------------------------------------
class AgentConfig:
    def __init__(
        self,
        name: str,
        role: str,
        department: str,
        instruction_file: str,
        api_key_env: str,
        model_env: str = "MODEL_MANAGER",
        default_model: str = "groq/qwen/qwen3.6-27b",
        avatar_name: str = "robot"
    ):
        self.name = name
        self.role = role
        self.department = department
        self.instruction_file = instruction_file
        self.api_key_env = api_key_env
        self.model_env = model_env
        self.default_model = default_model
        self.avatar_name = avatar_name

    @property
    def model_name(self) -> str:
        raw = os.getenv(self.model_env, self.default_model).strip()
        return raw or self.default_model

    def get_provider_and_model(self) -> Tuple[str, str]:
        """모델명에 따라 cerebras / groq 프로바이더 및 실제 모델 ID 분리"""
        full_model = self.model_name
        if full_model.startswith("cerebras/"):
            return "cerebras", full_model.replace("cerebras/", "")
        elif full_model.startswith("groq/"):
            return "groq", full_model.replace("groq/", "")
        elif any(k in full_model.lower() for k in ["gemma", "production"]):
            return "cerebras", full_model
        elif any(k in full_model.lower() for k in ["qwen", "compound", "prompt-guard"]):
            return "groq", full_model
        else:
            return "cerebras", full_model

    @property
    def api_key(self) -> str:
        provider, _ = self.get_provider_and_model()
        if provider == "cerebras":
            if self.model_env == "MODEL_CEO" or self.role == "최고경영자":
                key = os.getenv("CEREBRAS_API_KEY_1") or os.getenv("CEREBRAS_API_KEY")
            elif self.department == "dev" or self.model_env == "MODEL_MANAGER" or "팀장" in self.name:
                key = os.getenv("CEREBRAS_API_KEY_2") or os.getenv("CEREBRAS_API_KEY")
            else:
                key = os.getenv("CEREBRAS_API_KEY_3") or os.getenv("CEREBRAS_API_KEY")
            return (key or os.getenv("CEREBRAS_API_KEY", "")).strip()
        else:  # groq
            if self.model_env == "MODEL_CEO" or self.role == "최고경영자":
                key = os.getenv("GROQ_API_KEY_1") or os.getenv("GROQ_API_KEY")
            elif self.department == "dev" or self.model_env == "MODEL_MANAGER" or "팀장" in self.name:
                key = os.getenv("GROQ_API_KEY_2") or os.getenv("GROQ_API_KEY")
            else:
                key = os.getenv("GROQ_API_KEY_3") or os.getenv("GROQ_API_KEY")
            return (key or os.getenv("GROQ_API_KEY", "")).strip()


AGENTS: Dict[str, AgentConfig] = {
    # 경영진 (CEO - Qwen 27B)
    "CEO": AgentConfig("CEO", "최고경영자", "executive", "ceo_instruction.md", "GROQ_API_KEY_1", "MODEL_CEO", "groq/qwen/qwen3.6-27b", "briefcase"),
    
    # 개발본부 (Qwen 27B 풀스택 코딩)
    "개발팀장": AgentConfig("개발팀장", "Technical Lead & Scrum Master", "dev", "dev_instruction.md", "GROQ_API_KEY_2", "MODEL_MANAGER", "groq/qwen/qwen3.6-27b", "hammer_and_wrench"),
    "개발_사원A": AgentConfig("개발_사원A", "System Architect", "dev", "dev_instruction.md", "GROQ_API_KEY_2", "MODEL_MANAGER", "groq/qwen/qwen3.6-27b", "building_construction"),
    "개발_사원B": AgentConfig("개발_사원B", "Backend & Data Engineer / Security", "dev", "dev_instruction.md", "GROQ_API_KEY_2", "MODEL_MANAGER", "groq/qwen/qwen3.6-27b", "shield"),
    "개발_사원C": AgentConfig("개발_사원C", "Frontend & UI / Payment UX", "dev", "dev_instruction.md", "GROQ_API_KEY_2", "MODEL_MANAGER", "groq/qwen/qwen3.6-27b", "credit_card"),
    "개발_사원D": AgentConfig("개발_사원D", "QA & Penetration Engineer", "dev", "dev_instruction.md", "GROQ_API_KEY_2", "MODEL_MANAGER", "groq/qwen/qwen3.6-27b", "mag"),
    "개발_사원E": AgentConfig("개발_사원E", "DevOps & Infra Engineer", "dev", "dev_instruction.md", "GROQ_API_KEY_2", "MODEL_MANAGER", "groq/qwen/qwen3.6-27b", "cloud"),

    # 마케팅본부 (20B 초고속 카피라이팅)
    "마케팅팀장": AgentConfig("마케팅팀장", "Marketing Director", "marketing", "marketing_instruction.md", "GROQ_API_KEY_3", "MODEL_MANAGER", "groq/qwen/qwen3.6-27b", "chart_with_upwards_trend"),
    "마케팅_사원A": AgentConfig("마케팅_사원A", "Trend & Material Analyst", "marketing", "marketing_instruction.md", "GROQ_API_KEY_3", "MODEL_WORKER", "groq/openai/gpt-oss-20b", "telescope"),
    "마케팅_사원B": AgentConfig("마케팅_사원B", "Content Architect (3막 8장)", "marketing", "marketing_instruction.md", "GROQ_API_KEY_3", "MODEL_WORKER", "groq/openai/gpt-oss-20b", "scroll"),
    "마케팅_사원C": AgentConfig("마케팅_사원C", "Detail Copywriter & CTA", "marketing", "marketing_instruction.md", "GROQ_API_KEY_3", "MODEL_WORKER", "groq/openai/gpt-oss-20b", "pen"),
    "마케팅_사원D": AgentConfig("마케팅_사원D", "Visual Prompt Engineer", "marketing", "marketing_instruction.md", "GROQ_API_KEY_3", "MODEL_WORKER", "groq/openai/gpt-oss-20b", "art"),

    # 미디어본부
    "미디어팀장": AgentConfig("미디어팀장", "Technical Director", "media", "media_instruction.md", "GROQ_API_KEY_3", "MODEL_MANAGER", "groq/qwen/qwen3.6-27b", "movie_camera"),
    "미디어_사원A": AgentConfig("미디어_사원A", "Dual-Engine Audio Specialist", "media", "media_instruction.md", "GROQ_API_KEY_3", "MODEL_WORKER", "groq/openai/gpt-oss-20b", "sound"),
    "미디어_사원B": AgentConfig("미디어_사원B", "Visual & Browser Automation Specialist", "media", "media_instruction.md", "GROQ_API_KEY_3", "MODEL_WORKER", "groq/openai/gpt-oss-20b", "globe_with_meridians"),
    "미디어_사원C": AgentConfig("미디어_사원C", "Compositor & Video Editor", "media", "media_instruction.md", "GROQ_API_KEY_3", "MODEL_WORKER", "groq/openai/gpt-oss-20b", "clapper"),
    "미디어_사원D": AgentConfig("미디어_사원D", "Platform Staging & Slack Messenger", "media", "media_instruction.md", "GROQ_API_KEY_3", "MODEL_WORKER", "groq/openai/gpt-oss-20b", "package"),
}



# ----------------------------------------------------
# 7. Status Tracking
# ----------------------------------------------------
class StatusTracker:
    _io_lock = threading.Lock()

    def __init__(self, filepath: str = STATUS_FILE):
        self.filepath = filepath
        self.state: Dict[str, Any] = {
            "current_project": "대기 중",
            "active_agent": "None",
            "progress_percent": 0,
            "active_phase": "Phase 1: Core Automation Pipeline",
            "intelligence_stack": ["Headroom-AI", "Claude-Mem", "GSD", "Graphify", "Ponytail"],
            "agents_status": {name: {"status": "대기", "last_task": "-", "updated_at": ""} for name in AGENTS}
        }
        self.load()

    def load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    self.state = json.load(f)
            except Exception as e:
                logger.error(f"Error loading status file: {e}")

    def save(self):
        with self._io_lock:
            try:
                with open(self.filepath, "w", encoding="utf-8") as f:
                    json.dump(self.state, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"Error saving status file: {e}")

    def update_agent(self, agent_name: str, status: str, task: str, progress: Optional[int] = None):
        import datetime
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if agent_name in self.state["agents_status"]:
            self.state["agents_status"][agent_name] = {
                "status": status,
                "last_task": task,
                "updated_at": now
            }
        self.state["active_agent"] = agent_name
        if progress is not None:
            self.state["progress_percent"] = progress
        self.save()

        # 픽셀 오피스 실시간 이벤트 푸시 (Non-blocking)
        try:
            import urllib.request
            ev = {
                "kind": "state",
                "id": agent_name,
                "name": agent_name,
                "task": task,
                "tool": status,
                "zone": "dev" if status == "진행중" else "lounge"
            }
            req = urllib.request.Request(
                "http://127.0.0.1:8791/event",
                data=json.dumps(ev).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            urllib.request.urlopen(req, timeout=0.2).read()
        except Exception:
            pass

    def get_summary(self) -> str:
        lines = [
            f"*프로젝트:* {self.state.get('current_project', '-')}",
            f"*활성 페이즈 (GSD):* {self.state.get('active_phase', 'Phase 1')}",
            f"*현재 진행 에이전트:* {self.state.get('active_agent', '-')}",
            f"*전체 진행률:* {self.state.get('progress_percent', 0)}%",
            f"*적용 지능 엔진:* {', '.join(self.state.get('intelligence_stack', []))}",
            "",
            "*부서 및 에이전트별 현황:*"
        ]
        for name, data in self.state.get("agents_status", {}).items():
            status_text = data.get("status", "대기")
            task_text = data.get("last_task", "-")
            lines.append(f"• *{name}*: [{status_text}] {task_text}")
        return "\n".join(lines)


# ----------------------------------------------------
# 8. Core Company Orchestrator
# ----------------------------------------------------
class CompanyOrchestrator:
    """
    Unified AI Company Orchestrator with 5-Layer Intelligence Stack:
    1. Headroom-AI: Context compression & token savings.
    2. Claude-Mem: Long-term memory & cross-session learning.
    3. GSD: Situational dispatch & thin vertical slicing.
    4. Graphify: Knowledge graph & architectural relationship check.
    5. Ponytail: Minimalist & Pragmatic Engineering (YAGNI) guardrails.
    """
    def __init__(self):
        self.tracker = StatusTracker()
        self.headroom = HeadroomOptimizer(enabled=True)
        self.claude_mem = ClaudeMemManager()
        self.gsd = GSDManager()
        self.graphify = GraphifyEngine()
        self.ponytail = PonytailAuditor()

    def extract_role_instruction(self, instruction_path: str, agent_name: str, department: str) -> str:
        """직무 지침서에서 해당 에이전트의 전용 역할 섹션만 스마트 추출 (토큰 다이어트)"""
        if not os.path.exists(instruction_path):
            return ""
        try:
            with open(instruction_path, "r", encoding="utf-8") as f:
                full_text = f.read()
            
            if department == "executive" or agent_name == "CEO":
                return full_text[:1000].strip()

            # 해당 에이전트(@이름)의 헤더부터 다음 헤더 또는 인수인계 섹션 전까지 정확히 분리 추출
            pattern = rf"(###\s*\d*\.?\s*@{re.escape(agent_name)}[\s\S]*?)(?=###\s*\d*\.?\s*@|##\s*인수인계|\Z)"
            match = re.search(pattern, full_text)
            if match:
                return match.group(1).strip()[:1000]
            
            return full_text[:800].strip()
        except Exception as e:
            logger.debug(f"Role instruction extraction fallback: {e}")
            return ""

    def load_system_prompt(self, agent_name: str) -> str:
        config = AGENTS.get(agent_name)
        if not config:
            raise ValueError(f"Unknown agent: {agent_name}")

        # [1. 전사 공통 핵심 지침 (경량화)]
        common_handoff = (
            "- **인수인계 4대 양식**: @다음담당자 태그 + 작업 요약 + 경영진 주의사항 + 구체적 액션 아이템\n"
            "- **산출물 격리**: `projects/<프로젝트명>/` 또는 `output/<프로젝트명>/` 에 저장\n"
            "- **절대 금기**: 서버 내부 절대 경로(`/home/...`) 단독 표기 금지, 미배포 로컬 미리보기 링크(`http://localhost:8080/projects/<slug>/index.html`) 및 파일 목록 필수 제공\n"
            "- **도구 실행**: 실제 파일 생성 시 `[TOOL:write_file path=\"...\" content=\"...\"]` 반드시 사용"
        )

        # [2. 해당 에이전트 전용 직무 지침 추출]
        inst_path = os.path.join(INSTRUCTIONS_DIR, config.instruction_file)
        agent_instruction = self.extract_role_instruction(inst_path, agent_name, config.department)

        # [3. 장기 기억 컨텍스트]
        mem_context = self.claude_mem.get_memory_context(config.department, agent_name)

        # [4. GSD 활성 상태 & Ponytail 규율]
        gsd_context = self.gsd.get_gsd_context(agent_name)
        ponytail_context = self.ponytail.get_ponytail_context(config.department)

        # [5. 에이전트 맞춤형 핵심 스킬 로드]
        skills_text = self._load_skills(config.department, agent_name)

        raw_prompt = f"""
[5-LAYER INTELLIGENCE COMPLIANCE]
당신은 모든 작업 시 5대 지능 엔진(Headroom, Claude-Mem, GSD, Graphify, Ponytail) 원칙을 준수합니다.

[1. 전사 공통 규칙]
{common_handoff}

[2. 당신의 직무 지침: {config.name} ({config.role})]
{agent_instruction}

[3. 장기 기억 & GSD 상태]
{mem_context}
{gsd_context}
{ponytail_context}

{skills_text}

[출력 형식]
답변 시 항상 `@다음담당자` 태그와 함께 작업 요약, 산출물 경로, 후속 액션 아이템을 명확하게 작성하십시오.
"""
        optimized_prompt = self.headroom.optimize_text(raw_prompt)
        return optimized_prompt.strip()

    AGENT_SKILL_MAPPING: Dict[str, List[str]] = {
        # 경영진 & 비즈니스
        "CEO": ["executive_governance.md"],
        # 개발본부 (각 에이전트별 필수 스킬만 1~2개로 압축 매핑)
        "개발팀장": ["team_lead_skills.md"],
        "개발_사원A": ["architect_skills.md"],
        "개발_사원B": ["backend_skills.md", "vibe_coding_security_checklist.md"],
        "개발_사원C": ["frontend_skills.md", "ui_ux_design_system.md"],
        "개발_사원D": ["qa_security_skills.md", "vibe_coding_security_checklist.md"],
        "개발_사원E": ["devops_infra_skills.md"],
        # 마케팅본부
        "마케팅팀장": ["marketing_psychology.md"],
        "마케팅_사원A": ["sns_viral_formula.md"],
        "마케팅_사원B": ["copywriting_mastery.md"],
        "마케팅_사원C": ["copywriting_mastery.md"],
        "마케팅_사원D": ["banner_design.md"],
        # 미디어본부
        "미디어팀장": ["story_craft.md"],
        "미디어_사원A": ["story_narrative_rules.md"],
        "미디어_사원B": ["story_craft.md"],
        "미디어_사원C": ["story_craft.md"],
        "미디어_사원D": ["story_narrative_rules.md"],
    }

    def _load_skills(self, department: str, agent_name: str) -> str:
        skills = []
        dept_dir = os.path.join(SKILLS_DIR, department)
        global_dir = os.path.join(SKILLS_DIR, "global")
        
        target_files = self.AGENT_SKILL_MAPPING.get(agent_name, [])
        for fname in target_files:
            fpath = os.path.join(dept_dir, fname)
            if not os.path.exists(fpath):
                fpath = os.path.join(global_dir, fname)
            if os.path.exists(fpath):
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        content = f.read()
                        clean_content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
                        skills.append(f"### [{fname}]\n{clean_content[:700].strip()}")
                except Exception as e:
                    logger.debug(f"Skill load error ({fname}): {e}")

        if not skills:
            return ""
        return "## [핵심 실행 스킬]\n" + "\n\n".join(skills)

    def parse_next_agent(self, response_text: str, current_agent: str = "") -> Optional[str]:
        """발화자(current_agent) 제외, 한국어 호환 @태그 탐지"""
        for agent_name in AGENTS.keys():
            if agent_name == current_agent:
                continue
            # \b 한국어 실패 대비: @이름 뒤에 공백/구두점/줄바꿈/문장끝
            pattern = rf"@{re.escape(agent_name)}(?=[\s,.\n!?:;]|$)"
            if re.search(pattern, response_text):
                return agent_name
        return None

    def get_client_candidates(self, agent_name: str) -> List[Dict[str, Any]]:
        """에이전트 설정에 따라 Groq 클라우드 후보 목록 추출 (검증된 가용 모델만 사용)"""
        config = AGENTS.get(agent_name)
        if not config:
            return []
            
        provider, model_id = config.get_provider_and_model()
        groq_key = (os.getenv("GROQ_API_KEY_1") or os.getenv("GROQ_API_KEY_2") or os.getenv("GROQ_API_KEY_3") or os.getenv("GROQ_API_KEY", "")).strip()
        cerebras_key = (os.getenv("CEREBRAS_API_KEY_1") or os.getenv("CEREBRAS_API_KEY_2") or os.getenv("CEREBRAS_API_KEY_3") or os.getenv("CEREBRAS_API_KEY", "")).strip()
        
        # 가용 모델 화이트리스트 (이 목록에 없는 모델은 절대 호출하지 않음)
        ALLOWED_MODELS = {
            "groq/compound", "meta-llama/llama-prompt-guard-2-86m",
            "openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b",
        }
        
        # .env에서 읽은 model_id에서 provider 접두사 제거 (groq/qwen/... → qwen/...)
        clean_model = model_id
        if clean_model.startswith("groq/"):
            clean_model = clean_model[5:]
        if clean_model.startswith("cerebras/"):
            clean_model = clean_model[9:]
        
        # 화이트리스트에 없으면 역할에 따라 안전한 기본 모델 사용
        if clean_model not in ALLOWED_MODELS:
            if config.model_env in ["MODEL_CEO", "MODEL_MANAGER"]:
                clean_model = "qwen/qwen3.6-27b"
            else:
                clean_model = "openai/gpt-oss-20b"
        
        candidates = []
        
        # 1순위: Groq (검증된 주력)
        if groq_key:
            candidates.append({
                "provider": "Groq",
                "base_url": "https://api.groq.com/openai/v1",
                "api_key": groq_key,
                "model": clean_model
            })
        
        # 2순위: Groq 서브 모델 (1순위 실패 시 자동 전환)
        if groq_key:
            sub_model = "openai/gpt-oss-20b" if clean_model != "openai/gpt-oss-20b" else "qwen/qwen3.6-27b"
            candidates.append({
                "provider": "Groq",
                "base_url": "https://api.groq.com/openai/v1",
                "api_key": groq_key,
                "model": sub_model
            })
            
        return candidates

    def call_agent_llm(self, agent_name: str, conversation_history: List[Dict[str, str]]) -> str:
        config = AGENTS.get(agent_name)
        if not config:
            raise ValueError(f"Unknown agent '{agent_name}'")

        system_prompt = self.load_system_prompt(agent_name)
        candidates = self.get_client_candidates(agent_name)

        if not candidates:
            raise RuntimeError(
                f"현재 .env 파일에 CEREBRAS_API_KEY 또는 GROQ_API_KEY가 입력되지 않았습니다. .env에 발급받으신 AI 키를 입력해 주십시오."
            )

        try:
            # 1. Headroom-AI 대화 기록 최적화
            optimized_history = self.headroom.optimize_messages(conversation_history)

            def _call_llm_with_fallback(messages: List[Dict[str, str]]) -> str:
                from openai import OpenAI
                last_error = None
                
                for cand in candidates:
                    try:
                        logger.info(f"Calling {cand['provider']} [{cand['model']}] for {agent_name}...")
                        client = OpenAI(
                            api_key=cand["api_key"],
                            base_url=cand["base_url"],
                            timeout=45.0
                        )
                        completion = client.chat.completions.create(
                            model=cand["model"],
                            messages=messages,
                            temperature=0.7,
                            max_tokens=1200,
                        )
                        if completion.choices and completion.choices[0].message.content:
                            return completion.choices[0].message.content
                    except Exception as err:
                        err_msg = str(err)
                        last_error = err
                        logger.warning(f"[{cand['provider']}] call failed for {agent_name}: {err_msg[:80]}... Auto-switching next fallback.")
                        time.sleep(1.0)
                        continue

                raise last_error or Exception("All Cerebras & Groq API candidates exhausted.")

            # LLM 메시지 조립 및 엄격한 딕셔너리 포맷 정제
            raw_messages = [
                {"role": "system", "content": system_prompt},
                *optimized_history
            ]
            full_messages: List[Dict[str, str]] = []
            for m in raw_messages:
                if isinstance(m, dict) and "role" in m and "content" in m:
                    full_messages.append({"role": str(m["role"]), "content": str(m["content"])})
                elif hasattr(m, "role") and hasattr(m, "content"):
                    full_messages.append({"role": str(m.role), "content": str(m.content)})

            output_text = _call_llm_with_fallback(full_messages)

            # 2. Tool 실행 루프: 도구 결과를 LLM에 재전달 (최대 3회)
            for _tool_iter in range(3):
                tool_output = self.parse_and_run_tools(output_text)
                if not tool_output:
                    break
                # 도구 결과를 포함하여 LLM 재호출
                full_messages.append({"role": "assistant", "content": str(output_text)})
                full_messages.append({"role": "user", "content": f"[도구 실행 결과]\n{tool_output}\n\n위 도구 실행 결과를 바탕으로 답변을 완성해 주세요."})
                output_text = _call_llm_with_fallback(full_messages)

            # 3. Claude-Mem: 중요 결정사항 자동 기록
            if "결과 요약" in output_text or "완료" in output_text or "인수인계" in output_text:
                summary_snippet = output_text[:200].replace("\n", " ")
                self.claude_mem.record_decision(config.department, agent_name, summary_snippet)

            # 4. GSD & Graphify 상태 동기화
            if "페이즈" in output_text or "Phase" in output_text or "마일스톤" in output_text:
                self.gsd.update_phase_state(
                    active_phase=self.tracker.state.get("active_phase", "Phase 1: Core Automation Pipeline"),
                    phase_status="In-Progress",
                    decision=f"{agent_name} 작업 이관 완료"
                )

            return output_text
        except Exception as e:
            logger.error(f"LLM Call Error for {agent_name}: {e}")
            raise RuntimeError(f"{agent_name} 에이전트 LLM 호출 실패 - {e}") from e

    def execute_tool(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """
        기능별 도구 실행 디스패처 (Playwright, Threads, TTS 등)
        """
        logger.info(f"[Orchestrator] Executing tool '{tool_name}' with args: {kwargs}")
        
        if tool_name in ("playwright_browse", "browse_url", "web_fetch"):
            try:
                from ai_company.tools.playwright_browser import PlaywrightBrowser
            except ImportError:
                from tools.playwright_browser import PlaywrightBrowser
            url = kwargs.get("url", "")
            if not url:
                return {"success": False, "error": "URL이 지정되지 않았습니다."}
            browser = PlaywrightBrowser()
            return browser.fetch_page_text(url)

        elif tool_name in ("playwright_screenshot", "screenshot"):
            try:
                from ai_company.tools.playwright_browser import PlaywrightBrowser
            except ImportError:
                from tools.playwright_browser import PlaywrightBrowser
            url = kwargs.get("url", "")
            base_dir = self.tracker.state.get("current_project_dir", "output")
            default_path = os.path.join(base_dir, "images", "screenshot.png")
            out_path = kwargs.get("output_path", default_path)
            browser = PlaywrightBrowser()
            return browser.take_screenshot(url, output_path=out_path)

        elif tool_name in ("playwright_search", "web_search"):
            try:
                from ai_company.tools.playwright_browser import PlaywrightBrowser
            except ImportError:
                from tools.playwright_browser import PlaywrightBrowser
            query = kwargs.get("query", "")
            browser = PlaywrightBrowser()
            return {"results": browser.search_duckduckgo(query)}

        elif tool_name in ("tts_generate", "auto_tts"):
            try:
                from ai_company.tools.auto_tts import process_script
            except ImportError:
                from tools.auto_tts import process_script
            script_path = kwargs.get("script_path", "")
            base_dir = self.tracker.state.get("current_project_dir", "output")
            out_wav = kwargs.get("output_wav", os.path.join(base_dir, "audio", "narration.wav"))
            if not os.path.exists(script_path):
                return {"success": False, "error": f"대본 파일 없음: {script_path}"}
            process_script(script_path, out_wav)
            return {"success": True, "output_wav": out_wav}

        elif tool_name in ("video_render", "render_video"):
            try:
                from ai_company.tools.video_compositor import render_video
            except ImportError:
                from tools.video_compositor import render_video
            base_dir = self.tracker.state.get("current_project_dir", "output")
            audio = kwargs.get("audio", os.path.join(base_dir, "audio", "narration.wav"))
            images = kwargs.get("images", os.path.join(base_dir, "images"))
            script = kwargs.get("script", os.path.join(base_dir, "script.txt"))
            output_mp4 = kwargs.get("output", os.path.join(base_dir, "final_video.mp4"))
            ratio = kwargs.get("ratio", "16:9")
            success = render_video(audio, images, script, output_mp4, ratio)
            return {"success": success, "output_mp4": output_mp4}

        elif tool_name in ("threads_publish", "threads_post"):
            try:
                from ai_company.tools.threads_api import ThreadsApiTool
            except ImportError:
                from tools.threads_api import ThreadsApiTool
            text = kwargs.get("text", "")
            img = kwargs.get("image_url")
            threads = ThreadsApiTool()
            if img:
                return threads.publish_image(text, img)
            return threads.publish_text(text)

        elif tool_name == "status_summary":
            return {"summary": self.tracker.get_summary()}

        # --- 개발용 도구 4종 (Smart Fallback & Ponytail) ---
        elif tool_name == "write_file":
            path, content = kwargs.get("path", ""), kwargs.get("content", "")
            project_root = os.path.dirname(BASE_DIR)
            
            # 경로가 단순 파일명인 경우 현재 활성 프로젝트 디렉토리에 배치
            base_dir_state = self.tracker.state.get("current_project_dir", "")
            if "/" not in path and "\\" not in path and base_dir_state:
                path = os.path.join(base_dir_state, path)
            elif not path.startswith("projects/") and not path.startswith("output/") and base_dir_state:
                path = os.path.join(base_dir_state, path)
                
            abs_path = os.path.normpath(os.path.join(project_root, path))
            if not abs_path.startswith(project_root):
                return {"success": False, "error": "경로 탈출 금지"}
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info(f"[Tool:write_file] Successfully wrote {len(content)} chars to {path}")
            return {"success": True, "path": path, "size": len(content)}

        elif tool_name == "read_file":
            path = kwargs.get("path", "").strip()
            project_root = os.path.dirname(BASE_DIR)
            
            # 1. 직접 지정된 절대/상대 경로 검사
            target_file = None
            candidate_paths = [
                os.path.normpath(os.path.join(project_root, path)),
                os.path.normpath(os.path.join(BASE_DIR, path)),
            ]
            
            base_dir_state = self.tracker.state.get("current_project_dir", "")
            if base_dir_state:
                candidate_paths.append(os.path.normpath(os.path.join(project_root, base_dir_state, path)))
                candidate_paths.append(os.path.normpath(os.path.join(project_root, "projects", base_dir_state.replace("output/", ""), path)))
            
            for cp in candidate_paths:
                if os.path.exists(cp) and os.path.isfile(cp):
                    target_file = cp
                    break
                    
            # 2. 스마트 퍼지 탐색: 파일명만으로 projects/ 및 output/ 하위 재귀 검색
            if not target_file:
                target_filename = os.path.basename(path)
                search_roots = [os.path.join(project_root, "projects"), os.path.join(project_root, "output"), BASE_DIR]
                matched_files = []
                for sroot in search_roots:
                    if os.path.exists(sroot):
                        for root, _, fnames in os.walk(sroot):
                            if target_filename in fnames:
                                matched_files.append(os.path.join(root, target_filename))
                if matched_files:
                    # 가장 최근 수정된 파일 선택
                    matched_files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
                    target_file = matched_files[0]
                    logger.info(f"[Tool:read_file] Smart resolved '{path}' -> '{target_file}'")

            if not target_file or not os.path.exists(target_file):
                # 주변 파일 목록 힌트 제공
                available = []
                for sdir in ["projects", "output"]:
                    sp = os.path.join(project_root, sdir)
                    if os.path.exists(sp):
                        for r, _, fns in os.walk(sp):
                            for fn in fns:
                                if fn.endswith((".md", ".html", ".js", ".css", ".py", ".json")):
                                    available.append(os.path.relpath(os.path.join(r, fn), project_root))
                return {
                    "success": False,
                    "error": f"파일을 찾을 수 없습니다: {path}",
                    "hint_available_files": available[:10]
                }

            with open(target_file, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
                rel = os.path.relpath(target_file, project_root)
                return {
                    "success": True,
                    "resolved_path": rel,
                    "content": content[:8000]
                }

        elif tool_name == "list_files":
            path = kwargs.get("path", ".")
            project_root = os.path.dirname(BASE_DIR)
            abs_path = os.path.normpath(os.path.join(project_root, path))
            files = []
            skip = {".git", "__pycache__", "node_modules", ".venv"}
            for root, dirs, fnames in os.walk(abs_path):
                dirs[:] = [d for d in dirs if d not in skip]
                for fn in fnames:
                    files.append(os.path.relpath(os.path.join(root, fn), project_root))
                if len(files) > 100:
                    break
            return {"success": True, "files": files[:100]}

        elif tool_name == "run_command":
            cmd = kwargs.get("command", "")
            blocked = ["rm -rf", "sudo", "mkfs", "dd if=", "shutdown"]
            if any(b in cmd for b in blocked):
                return {"success": False, "error": "차단된 명령어"}
            project_root = os.path.dirname(BASE_DIR)
            try:
                result = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True,
                    timeout=30, cwd=project_root
                )
                return {"success": True, "stdout": result.stdout[:3000], "stderr": result.stderr[:1000]}
            except subprocess.TimeoutExpired:
                return {"success": False, "error": "30초 타임아웃"}

        return {"success": False, "error": f"지원하지 않는 도구: {tool_name}"}

    def parse_and_run_tools(self, text: str) -> Optional[str]:
        """
        텍스트 내의 `[TOOL:tool_name key=val ...]` 형식 태그 탐지 및 자동 실행
        """
        tool_matches = re.findall(r"\[TOOL:([a-zA-Z0-9_-]+)\s*(.*?)\]", text)
        if not tool_matches:
            return None

        results = []
        for tool_name, arg_str in tool_matches:
            try:
                # key="value" or key='value' or key=value 안전 파싱
                clean_args = {}
                for m in re.finditer(r'(\w+)=(?:"([^"]*)"|\'([^\']*)\'|(\S+))', arg_str):
                    k = m.group(1)
                    v = m.group(2) if m.group(2) is not None else (m.group(3) if m.group(3) is not None else m.group(4))
                    clean_args[k] = v or ""
                
                res = self.execute_tool(tool_name, **clean_args)
                results.append(f"• `{tool_name}`: ```{json.dumps(res, ensure_ascii=False, indent=2)}```")
            except Exception as tool_err:
                logger.error(f"Tool {tool_name} error: {tool_err}")
                results.append(f"• `{tool_name}` 실행 실패: {tool_err}")

        return "\n".join(results)

