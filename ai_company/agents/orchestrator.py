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
        try:
            # 1. 과거 대화 메시지 중 지나치게 긴 텍스트 자동 트리밍 (Groq 8000/30000 TPM 보호)
            pre_trimmed = []
            for i, m in enumerate(messages):
                role = str(m.get("role", "user")) if isinstance(m, dict) else str(getattr(m, "role", "user"))
                content = str(m.get("content", "")) if isinstance(m, dict) else str(getattr(m, "content", ""))
                # 직전 메시지가 아닌 이전 히스토리가 1800자를 초과하는 경우 압축
                if i < len(messages) - 1 and len(content) > 1800:
                    content = content[:1200] + "\n...(핵심 인수인계 외 중략)...\n" + content[-400:]
                pre_trimmed.append({"role": role, "content": content})

            if not self.enabled or not self._headroom or not pre_trimmed:
                return pre_trimmed
            res = self._headroom.compress(pre_trimmed)
            if hasattr(res, 'messages') and isinstance(res.messages, list) and len(res.messages) > 0:
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
            return pre_trimmed
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
        api_key_env: str = "GROQ_API_KEY",
        model_env: str = "MODEL_MANAGER",
        default_model: str = "groq/openai/gpt-oss-120b",
        avatar_name: str = "robot_face"
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
    # 경영진 (CEO - High IQ 120B / Qwen 27B)
    "CEO": AgentConfig("CEO", "최고경영자", "executive", "ceo_instruction.md", "GROQ_API_KEY_1", "MODEL_CEO", "groq/openai/gpt-oss-120b", "briefcase"),
    
    # 개발본부 (120B / 20B 고TPM 분산 아키텍처)
    "개발팀장": AgentConfig("개발팀장", "Technical Lead & Scrum Master", "dev", "dev_instruction.md", "GROQ_API_KEY_2", "MODEL_MANAGER", "groq/openai/gpt-oss-120b", "hammer_and_wrench"),
    "개발_사원A": AgentConfig("개발_사원A", "System Architect", "dev", "dev_instruction.md", "GROQ_API_KEY_2", "MODEL_MANAGER", "groq/openai/gpt-oss-120b", "building_construction"),
    "개발_사원B": AgentConfig("개발_사원B", "Backend & Data Engineer / Security", "dev", "dev_instruction.md", "GROQ_API_KEY_2", "MODEL_WORKER", "groq/openai/gpt-oss-20b", "shield"),
    "개발_사원C": AgentConfig("개발_사원C", "Frontend & UI / Payment UX", "dev", "dev_instruction.md", "GROQ_API_KEY_2", "MODEL_MANAGER", "groq/openai/gpt-oss-120b", "credit_card"),
    "개발_사원D": AgentConfig("개발_사원D", "QA & Penetration Engineer", "dev", "dev_instruction.md", "GROQ_API_KEY_2", "MODEL_WORKER", "groq/openai/gpt-oss-20b", "mag"),
    "개발_사원E": AgentConfig("개발_사원E", "DevOps & Infra Engineer", "dev", "dev_instruction.md", "GROQ_API_KEY_2", "MODEL_WORKER", "groq/openai/gpt-oss-20b", "cloud"),

    # 마케팅본부 (120B / 20B 초고속 카피라이팅)
    "마케팅팀장": AgentConfig("마케팅팀장", "Marketing Director", "marketing", "marketing_instruction.md", "GROQ_API_KEY_3", "MODEL_MANAGER", "groq/openai/gpt-oss-120b", "chart_with_upwards_trend"),
    "마케팅_사원A": AgentConfig("마케팅_사원A", "Trend & Material Analyst", "marketing", "marketing_instruction.md", "GROQ_API_KEY_3", "MODEL_WORKER", "groq/openai/gpt-oss-20b", "telescope"),
    "마케팅_사원B": AgentConfig("마케팅_사원B", "Content Architect (3막 8장)", "marketing", "marketing_instruction.md", "GROQ_API_KEY_3", "MODEL_WORKER", "groq/openai/gpt-oss-20b", "scroll"),
    "마케팅_사원C": AgentConfig("마케팅_사원C", "Detail Copywriter & CTA", "marketing", "marketing_instruction.md", "GROQ_API_KEY_3", "MODEL_WORKER", "groq/openai/gpt-oss-20b", "pen"),
    "마케팅_사원D": AgentConfig("마케팅_사원D", "Visual Prompt Engineer", "marketing", "marketing_instruction.md", "GROQ_API_KEY_3", "MODEL_WORKER", "groq/openai/gpt-oss-20b", "art"),

    # 미디어본부
    "미디어팀장": AgentConfig("미디어팀장", "Technical Director", "media", "media_instruction.md", "GROQ_API_KEY_3", "MODEL_MANAGER", "groq/openai/gpt-oss-120b", "movie_camera"),
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
[6-LAYER INTELLIGENCE COMPLIANCE]
당신은 모든 작업 시 6대 지능 엔진(Headroom, Claude-Mem, GSD, Graphify, Ponytail, unlazy) 원칙을 준수합니다.

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
        "CEO": ["executive_governance.md", "unlazy_discipline.md"],
        # 개발본부 (각 에이전트별 필수 스킬과 unlazy 안티-게으름 실행 규율 매핑)
        "개발팀장": ["team_lead_skills.md", "unlazy_discipline.md"],
        "개발_사원A": ["architect_skills.md", "unlazy_discipline.md"],
        "개발_사원B": ["backend_skills.md", "vibe_coding_security_checklist.md", "unlazy_discipline.md"],
        "개발_사원C": ["frontend_skills.md", "ui_ux_design_system.md", "unlazy_discipline.md"],
        "개발_사원D": ["qa_security_skills.md", "vibe_coding_security_checklist.md", "unlazy_discipline.md"],
        "개발_사원E": ["devops_infra_skills.md", "unlazy_discipline.md"],
        # 마케팅본부
        "마케팅팀장": ["marketing_psychology.md", "unlazy_discipline.md"],
        "마케팅_사원A": ["sns_viral_formula.md", "unlazy_discipline.md"],
        "마케팅_사원B": ["copywriting_mastery.md", "unlazy_discipline.md"],
        "마케팅_사원C": ["copywriting_mastery.md", "unlazy_discipline.md"],
        "마케팅_사원D": ["banner_design.md", "unlazy_discipline.md"],
        # 미디어본부
        "미디어팀장": ["story_craft.md", "unlazy_discipline.md"],
        "미디어_사원A": ["story_narrative_rules.md", "unlazy_discipline.md"],
        "미디어_사원B": ["story_craft.md", "unlazy_discipline.md"],
        "미디어_사원C": ["story_craft.md", "unlazy_discipline.md"],
        "미디어_사원D": ["story_narrative_rules.md", "unlazy_discipline.md"],
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

    def clean_llm_response(self, text: str) -> str:
        """
        Qwen 3.6 등의 <think>...</think> 추론 태그 스마트 정제
        - 불필요한 내부 생각 과정이 슬랙/결과물로 누출되는 현상 방지
        - 태그가 닫히지 않은 경우(토큰 한도 등)에도 최종 답변부만 스마트 추출
        """
        if not text:
            return ""
        
        if "<think>" in text:
            if "</think>" in text:
                cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
            else:
                # 닫는 태그가 없는 경우: 생각 과정 이후의 실제 답변 패턴 탐지
                match = re.search(r"(?:\n\n|\n)(?:Draft|최종|@|##|###|\*\*|\[TOOL:)([\s\S]*)", text)
                if match:
                    cleaned = match.group(0).strip()
                else:
                    # 생각 태그 뒷부분 요약 추출
                    cleaned = re.sub(r"^<think>[\s\S]*?(?=\n\n[^\n]+$)", "", text).strip()
                    if not cleaned:
                        cleaned = text.replace("<think>", "").strip()
            if cleaned:
                return cleaned

        return text.strip()

    def get_client_candidates(self, agent_name: str) -> List[Dict[str, Any]]:
        """에이전트 설정에 따라 Cerebras 및 Groq 듀얼 클라우드 후보 목록 추출 (어느 한쪽 키만 있어도 100% 자동 가동)"""
        config = AGENTS.get(agent_name)
        if not config:
            return []
            
        groq_keys = [
            k.strip() for k in [
                os.getenv("GROQ_API_KEY_1"),
                os.getenv("GROQ_API_KEY_2"),
                os.getenv("GROQ_API_KEY_3"),
                os.getenv("GROQ_API_KEY")
            ] if k and k.strip()
        ]
        cerebras_keys = [
            k.strip() for k in [
                os.getenv("CEREBRAS_API_KEY_1"),
                os.getenv("CEREBRAS_API_KEY_2"),
                os.getenv("CEREBRAS_API_KEY_3"),
                os.getenv("CEREBRAS_API_KEY")
            ] if k and k.strip()
        ]
        
        candidates = []
        
        # 1. Groq 클라우드 (초고속 실시간 추론 & 고TPM 모델 우선)
        if groq_keys:
            primary_groq_key = groq_keys[0]
            clean_model = config.model_name
            if clean_model.startswith("groq/"):
                clean_model = clean_model[5:]
            if clean_model.startswith("cerebras/"):
                clean_model = clean_model[9:]
            # 8,000 TPM 병목인 구형 Qwen 설정이 .env에 남아있더라도 자동으로 30,000+ TPM 고지능 모델로 자동 승격
            if clean_model == "qwen/qwen3.6-27b" or clean_model not in {"openai/gpt-oss-120b", "openai/gpt-oss-20b", "meta-llama/llama-3.3-70b-versatile", "meta-llama/llama-3.1-8b-instant"}:
                clean_model = "openai/gpt-oss-120b" if config.model_env in ["MODEL_CEO", "MODEL_MANAGER"] else "openai/gpt-oss-20b"
                
            candidates.append({
                "provider": "Groq",
                "base_url": "https://api.groq.com/openai/v1",
                "api_key": primary_groq_key,
                "model": clean_model
            })
            
            # 고TPM 서브 모델 및 다중 키 분산 폴백
            for g_key in groq_keys:
                candidates.append({
                    "provider": "Groq (120B)",
                    "base_url": "https://api.groq.com/openai/v1",
                    "api_key": g_key,
                    "model": "openai/gpt-oss-120b"
                })
                candidates.append({
                    "provider": "Groq (20B Fast)",
                    "base_url": "https://api.groq.com/openai/v1",
                    "api_key": g_key,
                    "model": "openai/gpt-oss-20b"
                })
                candidates.append({
                    "provider": "Groq (Llama 70B)",
                    "base_url": "https://api.groq.com/openai/v1",
                    "api_key": g_key,
                    "model": "meta-llama/llama-3.3-70b-versatile"
                })

        # 2. Cerebras 클라우드 (120B / Gemma 31B)
        if cerebras_keys:
            for c_key in cerebras_keys:
                candidates.append({
                    "provider": "Cerebras",
                    "base_url": "https://api.cerebras.ai/v1",
                    "api_key": c_key,
                    "model": "gpt-oss-120b"
                })
                candidates.append({
                    "provider": "Cerebras (Gemma)",
                    "base_url": "https://api.cerebras.ai/v1",
                    "api_key": c_key,
                    "model": "gemma-4-31b"
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
                
                # 프롬프트 크기 기반 동적 max_tokens 책정 (TPM 8000/30000 초과 방지)
                total_chars = sum(len(m.get("content", "")) for m in messages)
                current_max_tokens = 1200 if total_chars < 3000 else 800
                active_messages = list(messages)
                
                for cand in candidates:
                    try:
                        logger.info(f"Calling {cand['provider']} [{cand['model']}] for {agent_name} (max_tokens={current_max_tokens})...")
                        client = OpenAI(
                            api_key=cand["api_key"],
                            base_url=cand["base_url"],
                            timeout=35.0
                        )
                        completion = client.chat.completions.create(
                            model=cand["model"],
                            messages=active_messages,
                            temperature=0.7,
                            max_tokens=current_max_tokens,
                        )
                        if completion.choices and completion.choices[0].message.content:
                            raw_resp = completion.choices[0].message.content
                            return self.clean_llm_response(raw_resp)
                    except Exception as err:
                        err_msg = str(err)
                        last_error = err
                        logger.warning(f"[{cand['provider']} - {cand['model']}] failed for {agent_name}: {err_msg[:80]}... Switching next candidate.")
                        
                        # 413 (TPM 초과 / Request too large) 발생 시 컨텍스트 즉시 압축 및 max_tokens 하향
                        if "413" in err_msg or "rate_limit_exceeded" in err_msg or "Request too large" in err_msg:
                            logger.info(f"[Quota Shield] Auto-compressing messages for {agent_name} due to 413 TPM limit...")
                            current_max_tokens = 600
                            # 시스템 프롬프트(0번) + 최근 1개 메시지만 유지하여 극단적 다이어트
                            if len(active_messages) > 2:
                                active_messages = [active_messages[0], active_messages[-1]]
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
            output_text = self.clean_llm_response(output_text)

            # 2. Tool 실행 루프: 도구 결과 및 코드 블록 자동 감지 실행 (최대 3회)
            for _tool_iter in range(3):
                tool_output = self.parse_and_run_tools(output_text, agent_name=agent_name)
                if not tool_output:
                    break
                # 도구 결과를 포함하여 LLM 재호출
                full_messages.append({"role": "assistant", "content": str(output_text)})
                full_messages.append({"role": "user", "content": f"[도구 실행 결과]\n{tool_output}\n\n위 도구 실행 결과를 바탕으로 최종 인수인계 및 답변을 완성해 주세요."})
                output_text = _call_llm_with_fallback(full_messages)
                output_text = self.clean_llm_response(output_text)

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

            # 5. [Unlazy Finish Line Gate] 프론트엔드/개발팀장 완료 시 물리 파일(DESIGN.md, index.html, styles.css) 실존 100% 보장
            if agent_name in ("개발_사원C", "개발팀장", "개발_사원D", "개발_사원E"):
                user_msg = history[0]["content"] if history else ""
                self.ensure_project_artifacts(user_msg)

            return output_text
        except Exception as e:
            logger.error(f"LLM Call Error for {agent_name}: {e}")
            raise RuntimeError(f"{agent_name} 에이전트 LLM 호출 실패 - {e}") from e

    def ensure_project_artifacts(self, prompt: str = ""):
        """
        [Unlazy v2 Finish Line Gate]
        웹/앱 프로젝트 시 DESIGN.md 및 index.html, styles.css, app.js 물리 파일의 실존을 100% 보장
        (사원C 또는 LLM이 플레이스홀더만 남기고 중단하는 80% 조기종료 버그 원천 차단)
        """
        base_dir_state = self.tracker.state.get("current_project_dir", "")
        if not base_dir_state or not base_dir_state.startswith("projects/"):
            return

        project_root = os.path.dirname(BASE_DIR)
        target_path = os.path.join(project_root, base_dir_state)
        os.makedirs(target_path, exist_ok=True)
        os.makedirs(os.path.join(target_path, "css"), exist_ok=True)
        os.makedirs(os.path.join(target_path, "js"), exist_ok=True)

        slug = os.path.basename(base_dir_state)
        title = slug.replace("-", " ").title()
        p_lower = prompt.lower() if prompt else slug.lower()

        # 도메인별 미학 및 팔레트 판정 (교회/선교 vs SaaS vs 일반 커머스/포트폴리오)
        is_church = any(k in p_lower for k in ["교회", "church", "선교", "예배", "목사", "성경", "grace", "faith", "life"])
        is_saas = any(k in p_lower for k in ["saas", "대시보드", "ai", "자동화", "analytics", "bot", "dashboard"])

        if is_church:
            theme_name = "Modern Sacred Editorial"
            primary = "#92400E" # Warm Amber/Gold
            accent = "#B45309"
            bg = "#FAF8F5"      # Warm Paper
            text_color = "#1E293B" # Dark Slate
            font_heading = "Playfair Display"
            font_body = "Pretendard"
            hero_tagline = "은혜와 진리가 충만한 공동체"
            hero_sub = "함께 예배하고, 사랑으로 섬기며, 세상의 빛과 소금이 되는 교회입니다."
            nav_items = [("교회소개", "#about"), ("예배안내", "#worship"), ("말씀/찬양", "#sermons"), ("선교/사역", "#ministry"), ("오시는길", "#location"), ("온라인헌금", "#offering")]
        elif is_saas:
            theme_name = "Minimal SaaS Precision"
            primary = "#2563EB"
            accent = "#10B981"
            bg = "#09090B"
            text_color = "#F8FAFC"
            font_heading = "Syne"
            font_body = "Pretendard"
            hero_tagline = "차세대 AI 자동화 비즈니스 솔루션"
            hero_sub = "1인 기업부터 엔터프라이즈까지, 업무 효율을 10배 극대화하는 올인원 워크스페이스."
            nav_items = [("기능소개", "#features"), ("작동원리", "#how-it-works"), ("요금안내", "#pricing"), ("고객후기", "#reviews"), ("문의하기", "#contact"), ("무료체험", "#cta")]
        else:
            theme_name = "Clean Modern Editorial"
            primary = "#0F172A"
            accent = "#EA580C"
            bg = "#FDFBF7"
            text_color = "#18181B"
            font_heading = "Playfair Display"
            font_body = "Pretendard"
            hero_tagline = f"{title} — 새로운 경험의 시작"
            hero_sub = "직관적인 디자인과 완벽한 기능으로 당신의 목표를 현실로 만들어 드립니다."
            nav_items = [("소개", "#about"), ("서비스", "#services"), ("특장점", "#features"), ("고객센터", "#contact"), ("시작하기", "#cta")]

        # 1. DESIGN.md 보장
        des_path = os.path.join(target_path, "DESIGN.md")
        if not os.path.exists(des_path) or os.stat(des_path).st_size < 50:
            design_md_content = f"""# 🎨 DESIGN.md — {title}

## 1. 브랜드 아이덴티티 및 디자인 테마
- **디자인 미학**: `{theme_name}`
- **목표**: AI 티를 배제한 신뢰도 높은 프리미엄 인터페이스 구축

## 2. 컬러 팔레트 (Color System)
- **주조색 (Primary)**: `{primary}` (신뢰와 품격을 전달하는 메인 테마 색상)
- **강조색 (Accent)**: `{accent}` (CTA 및 주요 전환 포인트 강조)
- **배경색 (Background)**: `{bg}` (눈의 피로를 덜어주는 고대비 소프트 배경)
- **본문 텍스트 (Text)**: `{text_color}` (WCAG AA 기준 명도 대비 4.5:1 이상 준수)

## 3. 타이포그래피 (Typography)
- **제목용 글꼴 (Heading)**: `{font_heading}`, serif/sans-serif
- **본문용 글꼴 (Body)**: `{font_body}`, sans-serif (가독성 최우선 큐레이션)
- *(금기: Inter, Roboto, 시스템 기본 글꼴 남발 금지)*

## 4. AI 클리셰 5대 금지 규칙 준수
1. ❌ 보라색/인디고 AI 네온 그라데이션 금지 ➔ ✅ 명확한 1개 주조색(`{primary}`) 사용
2. ❌ 중첩 카드 지옥 금지 ➔ ✅ 1px 얇은 라인과 여백(Whitespace) 중심 플랫 구조
3. ❌ 저대비 회색 텍스트 금지 ➔ ✅ 4.5:1 이상 고대비 본문색 사용
4. ❌ 과도한 바운스/스프링 모션 금지 ➔ ✅ 150~200ms 절제된 ease-out 트랜지션
5. ❌ 기본 폰트 남발 금지 ➔ ✅ `{font_heading}` + `{font_body}` 페어링
"""
            with open(des_path, "w", encoding="utf-8") as f:
                f.write(design_md_content)
            logger.info(f"[Unlazy Guard] Auto-generated pristine DESIGN.md at {des_path}")

        # 2. index.html 보장
        html_path = os.path.join(target_path, "index.html")
        if not os.path.exists(html_path) or os.stat(html_path).st_size < 100:
            nav_links_html = "\n                ".join([f'<li><a href="{href}" class="nav-link">{label}</a></li>' for label, href in nav_items])
            
            if is_church:
                sections_html = f"""
    <!-- 예배 안내 섹션 -->
    <section id="worship" class="section worship-section">
        <div class="container">
            <div class="section-header">
                <span class="badge">WORSHIP SERVICE</span>
                <h2>예배 및 모임 안내</h2>
                <p>영과 진리로 드리는 거룩한 예배에 여러분을 초대합니다.</p>
            </div>
            <div class="grid grid-3">
                <div class="card">
                    <div class="card-icon">📖</div>
                    <h3>주일 대예배</h3>
                    <p class="time">매주 주일 오전 11:00</p>
                    <p class="desc">본당 3층 대예배실 (온라인 생중계 병행)</p>
                </div>
                <div class="card">
                    <div class="card-icon">🌅</div>
                    <h3>새벽 기도회</h3>
                    <p class="time">화 ~ 토 오전 05:30</p>
                    <p class="desc">소예배실 (하루를 기도로 여는 시간)</p>
                </div>
                <div class="card">
                    <div class="card-icon">🔥</div>
                    <h3>금요 성령집회</h3>
                    <p class="time">매주 금요일 오후 08:30</p>
                    <p class="desc">찬양과 말씀, 뜨거운 중보기도</p>
                </div>
            </div>
        </div>
    </section>

    <!-- 교회 소개 섹션 -->
    <section id="about" class="section about-section">
        <div class="container">
            <div class="grid grid-2">
                <div class="about-content">
                    <span class="badge">ABOUT US</span>
                    <h2>말씀 위에 굳건히 선 믿음의 공동체</h2>
                    <p>우리 교회는 오직 성경 말씀에 기초하여 하나님을 영화롭게 하고, 이웃에게 그리스도의 사랑을 실천하며 복음을 전파하는 공동체입니다.</p>
                    <ul class="check-list">
                        <li><span>✓</span> 말씀 중심의 바른 신앙과 제자 훈련</li>
                        <li><span>✓</span> 다음 세대를 세우는 교회 학교와 청년 공동체</li>
                        <li><span>✓</span> 지역 사회를 섬기고 땅끝까지 전하는 선교 사역</li>
                    </ul>
                </div>
                <div class="about-card-box">
                    <div class="highlight-card">
                        <h4>"너희는 세상의 빛이라"</h4>
                        <p class="verse">산 위에 있는 동네가 숨겨지지 못할 것이요 (마 5:14)</p>
                        <div class="pastor-info">
                            <strong>담임목사 및 교역자 일동</strong>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </section>

    <!-- 온라인 헌금 및 참여 -->
    <section id="offering" class="section offering-section">
        <div class="container text-center">
            <span class="badge">OFFERING & MISSION</span>
            <h2>온라인 헌금 및 사역 후원</h2>
            <p>하나님 나라의 확장과 선교를 위한 거룩한 동역에 감사드립니다.</p>
            <div class="account-card">
                <p class="bank-name">농협은행 (예금주: 대한예수교장로회 {title})</p>
                <p class="account-number">301-0000-0000-01</p>
                <button class="btn btn-secondary" onclick="navigator.clipboard.writeText('301-0000-0000-01'); alert('계좌번호가 복사되었습니다.');">계좌번호 복사</button>
            </div>
        </div>
    </section>
"""
            else:
                sections_html = f"""
    <!-- 서비스 핵심 기능 섹션 -->
    <section id="features" class="section">
        <div class="container">
            <div class="section-header">
                <span class="badge">FEATURES</span>
                <h2>핵심 기능 및 가치</h2>
                <p>복잡한 과정을 단 하나의 솔루션으로 완벽하게 해결합니다.</p>
            </div>
            <div class="grid grid-3">
                <div class="card">
                    <div class="card-icon">⚡</div>
                    <h3>초고속 실행</h3>
                    <p>불필요한 대기시간 없이 실시간으로 결과를 확인하고 적용합니다.</p>
                </div>
                <div class="card">
                    <div class="card-icon">🛡️</div>
                    <h3>철저한 보안</h3>
                    <p>엔드투엔드 암호화와 엄격한 인증 시스템으로 데이터를 보호합니다.</p>
                </div>
                <div class="card">
                    <div class="card-icon">📈</div>
                    <h3>수익 극대화</h3>
                    <p>직관적인 UI와 구매 동선으로 전환율을 극대화합니다.</p>
                </div>
            </div>
        </div>
    </section>
"""

            full_html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} — 공식 웹사이트</title>
    <!-- 구글 폰트 & 큐레이션 서체 로드 -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@500;700&family=Playfair+Display:wght@500;700&family=Plus+Jakarta+Sans:wght@400;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css">
    <link rel="stylesheet" href="css/styles.css">
</head>
<body>
    <!-- 상단 내비게이션 -->
    <header class="navbar">
        <div class="container nav-container">
            <a href="#" class="logo">{title}</a>
            <nav class="nav-menu">
                <ul class="nav-list">
                    {nav_links_html}
                </ul>
            </nav>
            <a href="#contact" class="btn btn-primary nav-cta">문의하기</a>
        </div>
    </header>

    <!-- 히어로 섹션 -->
    <section class="hero-section">
        <div class="container hero-container">
            <span class="hero-badge">WELCOME TO OUR COMMUNITY</span>
            <h1 class="hero-title">{hero_tagline}</h1>
            <p class="hero-sub">{hero_sub}</p>
            <div class="hero-actions">
                <a href="#about" class="btn btn-primary">자세히 보기</a>
                <a href="#worship" class="btn btn-outline">예배 안내</a>
            </div>
        </div>
    </section>

    {sections_html}

    <!-- 위치 및 문의 섹션 -->
    <section id="contact" class="section contact-section">
        <div class="container">
            <div class="section-header">
                <span class="badge">LOCATION & CONTACT</span>
                <h2>오시는 길 및 안내</h2>
                <p>언제나 열려있는 마음으로 여러분을 환영합니다.</p>
            </div>
            <div class="grid grid-2">
                <div class="info-card">
                    <h3>📍 주소 안내</h3>
                    <p class="info-text">서울특별시 강남구 테헤란로 123 ({title})</p>
                    <p class="info-sub">지하철 2호선 역삼역 4번 출구 도보 5분</p>
                    <div class="contact-details">
                        <p>📞 대표 전화: <strong>02-1234-5678</strong></p>
                        <p>✉️ 이메일: <strong>contact@{slug}.org</strong></p>
                    </div>
                </div>
                <div class="info-card">
                    <h3>✉️ 빠른 문의 / 기도 요청</h3>
                    <form class="contact-form" onsubmit="event.preventDefault(); alert('소중한 문의가 접수되었습니다. 담당 교역자가 연락드리겠습니다.');">
                        <input type="text" placeholder="성함" required class="form-input">
                        <input type="tel" placeholder="연락처" required class="form-input">
                        <textarea placeholder="문의 내용 또는 기도 제목을 입력해주세요" required class="form-textarea"></textarea>
                        <button type="submit" class="btn btn-primary btn-block">문의 제출하기</button>
                    </form>
                </div>
            </div>
        </div>
    </section>

    <!-- 푸터 -->
    <footer class="footer">
        <div class="container footer-container">
            <div class="footer-left">
                <p class="footer-logo">{title}</p>
                <p class="footer-desc">사랑과 섬김으로 세상을 변화시키는 따뜻한 공동체입니다.</p>
            </div>
            <div class="footer-right">
                <p class="copyright">© 2026 {title}. All rights reserved.</p>
                <p class="built-with">Crafted with Anti-Slop UI Standards</p>
            </div>
        </div>
    </footer>

    <script src="js/app.js"></script>
</body>
</html>"""
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(full_html)
            logger.info(f"[Unlazy Guard] Auto-generated production index.html at {html_path}")

        # 3. css/styles.css 보장
        css_path = os.path.join(target_path, "css", "styles.css")
        if not os.path.exists(css_path) or os.stat(css_path).st_size < 50:
            css_content = f"""/* DESIGN SYSTEM & STYLES — {title} */
:root {{
    --color-primary: {primary};
    --color-accent: {accent};
    --color-bg: {bg};
    --color-text: {text_color};
    --color-card-bg: #FFFFFF;
    --color-border: rgba(0, 0, 0, 0.08);
    --font-heading: '{font_heading}', 'Playfair Display', serif;
    --font-body: '{font_body}', 'Pretendard', -apple-system, sans-serif;
}}

* {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}}

body {{
    font-family: var(--font-body);
    background-color: var(--color-bg);
    color: var(--color-text);
    line-height: 1.7;
    font-size: 16px;
    -webkit-font-smoothing: antialiased;
}}

.container {{
    width: 100%;
    max-width: 1120px;
    margin: 0 auto;
    padding: 0 24px;
}}

/* Navbar */
.navbar {{
    position: sticky;
    top: 0;
    z-index: 100;
    background-color: rgba(253, 251, 247, 0.92);
    backdrop-filter: blur(10px);
    border-bottom: 1px solid var(--color-border);
    padding: 16px 0;
}}

.nav-container {{
    display: flex;
    align-items: center;
    justify-content: space-between;
}}

.logo {{
    font-family: var(--font-heading);
    font-size: 22px;
    font-weight: 700;
    color: var(--color-primary);
    text-decoration: none;
}}

.nav-list {{
    display: flex;
    list-style: none;
    gap: 28px;
}}

.nav-link {{
    color: var(--color-text);
    text-decoration: none;
    font-weight: 500;
    font-size: 15px;
    transition: color 0.2s ease;
}}

.nav-link:hover {{
    color: var(--color-accent);
}}

/* Buttons */
.btn {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 10px 22px;
    border-radius: 6px;
    font-size: 15px;
    font-weight: 600;
    text-decoration: none;
    cursor: pointer;
    transition: all 0.2s ease;
    border: 1px solid transparent;
}}

.btn-primary {{
    background-color: var(--color-primary);
    color: #FFFFFF;
}}

.btn-primary:hover {{
    opacity: 0.92;
    transform: translateY(-1px);
}}

.btn-outline {{
    background-color: transparent;
    color: var(--color-primary);
    border-color: var(--color-primary);
}}

.btn-outline:hover {{
    background-color: var(--color-primary);
    color: #FFFFFF;
}}

.btn-secondary {{
    background-color: #E2E8F0;
    color: #1E293B;
}}

.btn-block {{
    width: 100%;
}}

/* Hero Section */
.hero-section {{
    padding: 96px 0 80px;
    text-align: center;
    background: linear-gradient(180deg, rgba(245, 238, 227, 0.4) 0%, var(--color-bg) 100%);
    border-bottom: 1px solid var(--color-border);
}}

.hero-badge {{
    display: inline-block;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 2px;
    color: var(--color-accent);
    margin-bottom: 16px;
}}

.hero-title {{
    font-family: var(--font-heading);
    font-size: 44px;
    font-weight: 700;
    color: var(--color-primary);
    margin-bottom: 20px;
    line-height: 1.3;
}}

.hero-sub {{
    font-size: 18px;
    color: #475569;
    max-width: 680px;
    margin: 0 auto 32px;
}}

.hero-actions {{
    display: flex;
    gap: 16px;
    justify-content: center;
}}

/* Sections & Grids */
.section {{
    padding: 80px 0;
}}

.section-header {{
    text-align: center;
    margin-bottom: 48px;
}}

.badge {{
    display: inline-block;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 1.5px;
    color: var(--color-accent);
    margin-bottom: 8px;
}}

.section-header h2 {{
    font-family: var(--font-heading);
    font-size: 32px;
    color: var(--color-primary);
    margin-bottom: 12px;
}}

.section-header p {{
    color: #64748B;
    font-size: 16px;
}}

.grid {{
    display: grid;
    gap: 28px;
}}

.grid-2 {{
    grid-template-columns: repeat(2, 1fr);
}}

.grid-3 {{
    grid-template-columns: repeat(3, 1fr);
}}

.card {{
    background: var(--color-card-bg);
    border: 1px solid var(--color-border);
    border-radius: 8px;
    padding: 32px 24px;
    text-align: center;
    transition: transform 0.2s ease, box-shadow 0.2s ease;
}}

.card:hover {{
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(0,0,0,0.04);
}}

.card-icon {{
    font-size: 32px;
    margin-bottom: 16px;
}}

.card h3 {{
    font-size: 20px;
    color: var(--color-primary);
    margin-bottom: 8px;
}}

.card .time {{
    font-weight: 700;
    color: var(--color-accent);
    margin-bottom: 8px;
}}

.card .desc {{
    font-size: 14px;
    color: #64748B;
}}

/* About Section */
.about-section {{
    background-color: #F8F5EE;
    border-top: 1px solid var(--color-border);
    border-bottom: 1px solid var(--color-border);
}}

.check-list {{
    list-style: none;
    margin-top: 20px;
}}

.check-list li {{
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 12px;
    font-weight: 500;
}}

.check-list span {{
    color: var(--color-accent);
    font-weight: 700;
}}

.highlight-card {{
    background: #FFFFFF;
    border: 1px solid var(--color-border);
    border-left: 4px solid var(--color-accent);
    padding: 36px;
    border-radius: 8px;
}}

.highlight-card h4 {{
    font-family: var(--font-heading);
    font-size: 24px;
    color: var(--color-primary);
    margin-bottom: 12px;
}}

.highlight-card .verse {{
    font-style: italic;
    color: #64748B;
    margin-bottom: 24px;
}}

/* Offering Section */
.account-card {{
    background: #FFFFFF;
    border: 1px solid var(--color-border);
    max-width: 520px;
    margin: 32px auto 0;
    padding: 32px;
    border-radius: 8px;
}}

.bank-name {{
    font-weight: 600;
    color: #475569;
    margin-bottom: 8px;
}}

.account-number {{
    font-size: 24px;
    font-weight: 700;
    letter-spacing: 1px;
    color: var(--color-primary);
    margin-bottom: 20px;
}}

/* Form */
.info-card {{
    background: #FFFFFF;
    border: 1px solid var(--color-border);
    padding: 32px;
    border-radius: 8px;
}}

.form-input, .form-textarea {{
    width: 100%;
    padding: 12px 16px;
    border: 1px solid var(--color-border);
    border-radius: 6px;
    margin-bottom: 12px;
    font-family: inherit;
    font-size: 14px;
}}

.form-textarea {{
    min-height: 100px;
    resize: vertical;
}}

/* Footer */
.footer {{
    background-color: #1E293B;
    color: #94A3B8;
    padding: 48px 0;
    font-size: 14px;
}}

.footer-container {{
    display: flex;
    justify-content: space-between;
    align-items: center;
}}

.footer-logo {{
    font-family: var(--font-heading);
    font-size: 20px;
    color: #FFFFFF;
    font-weight: 700;
    margin-bottom: 6px;
}}

@media (max-width: 768px) {{
    .grid-2, .grid-3 {{
        grid-template-columns: 1fr;
    }}
    .hero-title {{
        font-size: 32px;
    }}
    .nav-list {{
        display: none;
    }}
    .footer-container {{
        flex-direction: column;
        gap: 20px;
        text-align: center;
    }}
}}
"""
            with open(css_path, "w", encoding="utf-8") as f:
                f.write(css_content)
            logger.info(f"[Unlazy Guard] Auto-generated styles.css at {css_path}")

        # 4. js/app.js 보장
        js_path = os.path.join(target_path, "js", "app.js")
        if not os.path.exists(js_path) or os.stat(js_path).st_size < 20:
            js_content = """// Interactive scripts
document.addEventListener('DOMContentLoaded', () => {
    // Smooth scrolling for anchor links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                target.scrollIntoView({
                    behavior: 'smooth'
                });
            }
        });
    });
});
"""
            with open(js_path, "w", encoding="utf-8") as f:
                f.write(js_content)
            logger.info(f"[Unlazy Guard] Auto-generated app.js at {js_path}")

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

    def parse_and_run_tools(self, text: str, agent_name: str = "") -> Optional[str]:
        """
        텍스트 내의 `[TOOL:tool_name key=val ...]` 형식 태그 탐지 및 자동 실행
        - 멀티라인 및 따옴표 충돌 없는 안전한 write_file 파싱
        - [Auto-Fallback] LLM이 [TOOL:...] 태그를 누락하고 마크다운 코드블록(```html, # DESIGN.md 등)으로 출력했을 때도 물리 파일 자동 생성 보장
        """
        if not text:
            return None

        results = []
        project_root = os.path.dirname(BASE_DIR)
        base_dir_state = self.tracker.state.get("current_project_dir", "")
        
        # 1. 명시적 [TOOL:tool_name ...] 태그 파싱
        tool_matches = re.findall(r"\[TOOL:([a-zA-Z0-9_-]+)\s*([\s\S]*?)\]", text)
        for tool_name, arg_str in tool_matches:
            try:
                clean_args = {}
                if tool_name == "write_file":
                    # path 추출
                    p_match = re.search(r'path=["\']?([^"\'\s]+)["\']?', arg_str)
                    if p_match:
                        clean_args["path"] = p_match.group(1)
                    
                    # content 추출 (내부 따옴표 충돌 방지: content= 시작점 이후 전체 캡처)
                    c_match = re.search(r'content=["\']([\s\S]*)["\']\s*$', arg_str)
                    if not c_match:
                        c_match = re.search(r'content=["\']([\s\S]*)$', arg_str)
                    if c_match:
                        clean_args["content"] = c_match.group(1).rstrip('"]')
                    else:
                        c_match_raw = re.search(r'content=([\s\S]*)', arg_str)
                        if c_match_raw:
                            clean_args["content"] = c_match_raw.group(1).strip()
                else:
                    for m in re.finditer(r'(\w+)=(?:"([\s\S]*?)"|\'([\s\S]*?)\'|(\S+))', arg_str):
                        k = m.group(1)
                        v = m.group(2) if m.group(2) is not None else (m.group(3) if m.group(3) is not None else m.group(4))
                        clean_args[k] = v or ""
                
                res = self.execute_tool(tool_name, **clean_args)
                results.append(f"• `{tool_name}`: ```{json.dumps(res, ensure_ascii=False, indent=2)}```")
            except Exception as tool_err:
                logger.error(f"Tool {tool_name} error: {tool_err}")
                results.append(f"• `{tool_name}` 실행 실패: {tool_err}")

        # 2. [Auto-Fallback] 마크다운 코드 블록 자동 추출 & 물리 파일 저장 (LLM이 도구 태그 누락 시 안전망)
        if base_dir_state:
            target_proj_path = os.path.join(project_root, base_dir_state)

            # (1) HTML 코드 블록 감지 -> index.html 자동 생성
            html_block = re.search(r"```html\s*([\s\S]*?)```", text, re.IGNORECASE)
            if html_block:
                html_content = html_block.group(1).strip()
            else:
                html_raw = re.search(r"(<!DOCTYPE html>[\s\S]*?</html>)", text, re.IGNORECASE)
                html_content = html_raw.group(1).strip() if html_raw else ""

            if html_content and ("<html" in html_content.lower() or "<body" in html_content.lower() or "<!doctype" in html_content.lower()):
                idx_path = os.path.join(target_proj_path, "index.html")
                if not os.path.exists(idx_path) or os.path.getsize(idx_path) < 50:
                    os.makedirs(target_proj_path, exist_ok=True)
                    with open(idx_path, "w", encoding="utf-8") as f:
                        f.write(html_content)
                    logger.info(f"[Auto-Fallback] Extracted HTML code block to {idx_path} ({len(html_content)} bytes)")
                    results.append(f"• `[Auto-Save]` HTML 코드 블록을 `{base_dir_state}/index.html` 에 자동 저장 완료 ({len(html_content)} bytes)")

            # (2) DESIGN.md 마크다운 블록 감지 -> DESIGN.md 자동 생성
            if "# DESIGN" in text or "## 1. 디자인" in text or "## DESIGN" in text or "### 1. 주조색" in text or "DESIGN.md" in text:
                design_block = re.search(r"```(?:markdown|md)?\s*(#\s*DESIGN[\s\S]*?)```", text, re.IGNORECASE)
                if design_block:
                    design_content = design_block.group(1).strip()
                else:
                    design_match = re.search(r"(#+\s*(?:DESIGN|디자인\s*가이드|Design\s*System)[\s\S]*?)(?=(?:```|@|\Z))", text, re.IGNORECASE)
                    design_content = design_match.group(1).strip() if design_match else ""
                
                if design_content and len(design_content) > 50:
                    des_path = os.path.join(target_proj_path, "DESIGN.md")
                    if not os.path.exists(des_path) or os.path.getsize(des_path) < 50:
                        os.makedirs(target_proj_path, exist_ok=True)
                        with open(des_path, "w", encoding="utf-8") as f:
                            f.write(design_content)
                        logger.info(f"[Auto-Fallback] Extracted DESIGN.md to {des_path} ({len(design_content)} bytes)")
                        results.append(f"• `[Auto-Save]` 디자인 가이드를 `{base_dir_state}/DESIGN.md` 에 자동 저장 완료 ({len(design_content)} bytes)")

            # (3) CSS 코드 블록 감지 -> css/styles.css 자동 생성
            css_block = re.search(r"```css\s*([\s\S]*?)```", text, re.IGNORECASE)
            if css_block:
                css_content = css_block.group(1).strip()
                if len(css_content) > 30:
                    css_dir = os.path.join(target_proj_path, "css")
                    os.makedirs(css_dir, exist_ok=True)
                    css_path = os.path.join(css_dir, "styles.css")
                    if not os.path.exists(css_path) or os.path.getsize(css_path) < 30:
                        with open(css_path, "w", encoding="utf-8") as f:
                            f.write(css_content)
                        logger.info(f"[Auto-Fallback] Extracted CSS code block to {css_path}")
                        results.append(f"• `[Auto-Save]` CSS 스타일을 `{base_dir_state}/css/styles.css` 에 자동 저장 완료")

        return "\n".join(results) if results else None

