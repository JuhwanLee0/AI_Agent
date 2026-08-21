import os
import unittest
from ai_company.agents.orchestrator import (
    CompanyOrchestrator,
    StatusTracker,
    ClaudeMemManager,
    GSDManager,
    PonytailAuditor,
    GraphifyEngine,
    AGENTS
)

class TestOrchestratorCore(unittest.TestCase):
    def setUp(self):
        self.orchestrator = CompanyOrchestrator()

    def test_agents_registry(self):
        self.assertIn('CEO', AGENTS)
        self.assertIn('개발팀장', AGENTS)
        self.assertIn('마케팅팀장', AGENTS)
        self.assertIn('미디어팀장', AGENTS)
        self.assertEqual(len(AGENTS), 17)

    def test_status_tracker(self):
        tracker = StatusTracker()
        tracker.update_agent('CEO', '진행중', '테스트 작업', progress=50)
        summary = tracker.get_summary()
        self.assertIn('CEO', summary)
        self.assertIn('50%', summary)

    def test_gsd_manager(self):
        gsd = GSDManager()
        ctx = gsd.get_gsd_context('개발팀장')
        self.assertIn('<gsd-context>', ctx)
        self.assertIn('ROADMAP', gsd.roadmap_file)

    def test_ponytail_auditor(self):
        ponytail = PonytailAuditor()
        ctx = ponytail.get_ponytail_context('dev')
        self.assertIn('YAGNI', ctx)
        self.assertIn('Less Code', ctx)

    def test_graphify_engine(self):
        graphify = GraphifyEngine()
        ctx = graphify.get_graph_context('dev', '개발_사원A')
        self.assertIn('<graphify-context>', ctx)
        self.assertIn('God Nodes', ctx)

    def test_system_prompt_generation(self):
        prompt = self.orchestrator.load_system_prompt('CEO')
        self.assertIn('최고경영자', prompt)
        self.assertIn('Claude-Mem', prompt)
        self.assertIn('GSD', prompt)

    def test_parse_next_agent(self):
        text = '작업을 완료했습니다. 다음 작업은 @개발팀장 님이 진행해주세요.'
        next_agent = self.orchestrator.parse_next_agent(text)
        self.assertEqual(next_agent, '개발팀장')

if __name__ == '__main__':
    unittest.main()
