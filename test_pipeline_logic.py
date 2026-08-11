import unittest
from unittest.mock import AsyncMock, patch, MagicMock
import asyncio

from agent_op.pipeline import run_navigator, execute_pipeline, set_session_state, get_session_state
from agent_op.schemas import ExtractionOutput, FactItem, ReportDraft, CompareItem, CritiqueList, CritiqueItem, ActionCard, TraceabilityTag, JudgeDecision

class TestPipelineLogic(unittest.TestCase):

    @patch("agent_op.pipeline.Agent")
    async def async_test_navigator_routing_open_flow(self, mock_agent_class):
        """Kiểm tra Navigator bẻ ghi sang luồng mở / làm rõ tin nhắn"""
        mock_agent_instance = MagicMock()
        mock_agent_class.return_value.__aenter__.return_value = mock_agent_instance
        
        # Giả lập Navigator trả lời làm rõ thông thường
        mock_response = MagicMock()
        mock_response.text = AsyncMock(return_value="Xin chào, vui lòng cung cấp thêm thông tin.")
        mock_agent_instance.chat = AsyncMock(return_value=mock_response)

        set_session_state("session-1", "NAVIGATING")
        result = await run_navigator("session-1", "Hello")
        
        self.assertEqual(result["status"], "clarification_needed")
        self.assertEqual(result["message"], "Xin chào, vui lòng cung cấp thêm thông tin.")
        self.assertEqual(get_session_state("session-1"), "NAVIGATING")

    @patch("agent_op.pipeline.Agent")
    async def async_test_navigator_routing_start_pipeline(self, mock_agent_class):
        """Kiểm tra Navigator kích hoạt luồng đóng khi có tín hiệu [START_PIPELINE]"""
        mock_agent_instance = MagicMock()
        mock_agent_class.return_value.__aenter__.return_value = mock_agent_instance
        
        # Giả lập Navigator bắn tín hiệu bắt đầu pipeline
        mock_response = MagicMock()
        mock_response.text = AsyncMock(return_value="Thông tin đã đủ. Bắt đầu phân tích... [START_PIPELINE] {\"document\": \"report.pdf\"}")
        mock_agent_instance.chat = AsyncMock(return_value=mock_response)

        set_session_state("session-2", "NAVIGATING")
        result = await run_navigator("session-2", "Phân tích file báo cáo đi")
        
        self.assertEqual(result["status"], "processing")
        self.assertEqual(result["message"], "Thông tin đã đủ. Bắt đầu phân tích...")
        self.assertEqual(get_session_state("session-2"), "PROCESSING")

    @patch("agent_op.pipeline.run_scanner")
    @patch("agent_op.pipeline.run_builder")
    @patch("agent_op.pipeline.run_challenger")
    @patch("agent_op.pipeline.run_judge_decision")
    @patch("agent_op.pipeline.run_builder_update")
    @patch("agent_op.pipeline.run_judge_finalize")
    async def async_test_pipeline_debate_concludes_early(
        self, mock_finalize, mock_builder_update, mock_judge_decision, mock_challenger, mock_builder, mock_scanner
    ):
        """Kiểm tra luồng tranh biện kết thúc sớm khi Challenger không có ý kiến phản biện"""
        # 1. Scanner trả về 1 dữ kiện
        mock_scanner.return_value = ExtractionOutput(
            found=True,
            facts=[FactItem(fact="Chi tiếp khách 15tr", coordinate="[Trang 3]")]
        )
        # 2. Builder tạo nháp báo cáo
        mock_builder.return_value = ReportDraft(
            title="Nháp", summary="Tóm tắt", comparisons=[], draft_conclusions=[]
        )
        # 3. Challenger trả về danh sách phản biện RỖNG (chấp thuận)
        mock_challenger.return_value = CritiqueList(critiques=[], overall_critique="Mọi thứ đều ổn.")
        
        # 4. Final Action Card
        mock_finalize.return_value = ActionCard(
            title="Thẻ cuối",
            summary="Duyệt",
            risk_level="LOW",
            findings=["Chi tiếp khách 15tr"],
            traceability_tags=[TraceabilityTag(point="Chi tiếp khách 15tr", coordinate="[Trang 3]")],
            recommendations=[],
            audit_trail="",
            human_review_required=False
        )

        card = await execute_pipeline("mock_path.pdf", "mock playbook", session_id="session-3")
        
        self.assertEqual(card.risk_level, "LOW")
        self.assertFalse(card.human_review_required)
        # Challenger chỉ gọi đúng 1 lần rồi ngắt debate loop
        mock_challenger.assert_called_once()
        mock_judge_decision.assert_not_called()

    @patch("agent_op.pipeline.run_scanner")
    @patch("agent_op.pipeline.run_builder")
    @patch("agent_op.pipeline.run_challenger")
    @patch("agent_op.pipeline.run_judge_decision")
    @patch("agent_op.pipeline.run_builder_update")
    @patch("agent_op.pipeline.run_judge_finalize")
    async def async_test_pipeline_debate_deadlock(
        self, mock_finalize, mock_builder_update, mock_judge_decision, mock_challenger, mock_builder, mock_scanner
    ):
        """Kiểm tra luồng tranh biện đạt tối đa 3 vòng mà chưa ngã ngũ (deadlock)"""
        mock_scanner.return_value = ExtractionOutput(
            found=True,
            facts=[FactItem(fact="Khoản A", coordinate="[Trang 1]")]
        )
        mock_builder.return_value = ReportDraft(
            title="Nháp", summary="Tóm tắt", comparisons=[], draft_conclusions=[]
        )
        # Luôn trả về phản biện để bắt debate chạy hết 3 vòng
        mock_challenger.return_value = CritiqueList(
            critiques=[CritiqueItem(target_comparison_index=0, logic_gap="Chưa rõ", playbook_violation_risk="Có", severity="HIGH")],
            overall_critique="Cần sửa"
        )
        mock_judge_decision.return_value = JudgeDecision(
            valid_critiques=["Sửa đi"], invalid_critiques=[], builder_instructions="Cập nhật cột A"
        )
        mock_builder_update.return_value = ReportDraft(
            title="Nháp", summary="Tóm tắt", comparisons=[], draft_conclusions=[]
        )
        mock_finalize.return_value = ActionCard(
            title="Thẻ cuối",
            summary="Không thống nhất",
            risk_level="MEDIUM",
            findings=["Khoản A"],
            traceability_tags=[TraceabilityTag(point="Khoản A", coordinate="[Trang 1]")],
            recommendations=[],
            audit_trail="",
            human_review_required=False
        )

        card = await execute_pipeline("mock_path.pdf", "mock playbook", session_id="session-4")
        
        # Do debate đạt max 3 vòng (deadlock) nên human_review_required bắt buộc phải là True
        self.assertTrue(card.human_review_required)
        self.assertEqual(mock_challenger.call_count, 3)

    @patch("agent_op.pipeline.run_scanner")
    @patch("agent_op.pipeline.run_builder")
    @patch("agent_op.pipeline.run_challenger")
    @patch("agent_op.pipeline.run_judge_finalize")
    async def async_test_poka_yoke_coordinate_filtering(
        self, mock_finalize, mock_challenger, mock_builder, mock_scanner
    ):
        """Kiểm tra Poka-Yoke lọc bỏ các kết luận có tọa độ sai lệch không thuộc Bước 1"""
        # Bước 1 trích xuất tọa độ [Trang 2]
        mock_scanner.return_value = ExtractionOutput(
            found=True,
            facts=[FactItem(fact="Quy trình 1", coordinate="[Trang 2]")]
        )
        mock_builder.return_value = ReportDraft(
            title="Nháp", summary="Tóm tắt", comparisons=[], draft_conclusions=[]
        )
        mock_challenger.return_value = CritiqueList(critiques=[], overall_critique="OK")
        
        # Giả lập Judge trả về Action Card chứa 2 phát hiện:
        # Phát hiện 1: tọa độ [Trang 2] (Hợp lệ)
        # Phát hiện 2: tọa độ [Trang 99] (Ảo giác - Không tồn tại ở Bước 1)
        mock_finalize.return_value = ActionCard(
            title="Báo cáo",
            summary="Thẩm định",
            risk_level="LOW",
            findings=["Đúng quy chuẩn", "Ảo giác"],
            traceability_tags=[
                TraceabilityTag(point="Đúng quy chuẩn", coordinate="[Trang 2]"),
                TraceabilityTag(point="Ảo giác", coordinate="[Trang 99]")
            ],
            recommendations=[],
            audit_trail="",
            human_review_required=False
        )

        card = await execute_pipeline("mock_path.pdf", "mock playbook", session_id="session-5")
        
        # Poka-Yoke phải lọc bỏ phát hiện ảo giác [Trang 99]
        self.assertEqual(len(card.traceability_tags), 1)
        self.assertEqual(card.traceability_tags[0].coordinate, "[Trang 2]")
        self.assertEqual(card.findings, ["Đúng quy chuẩn"])

    # Wrapper to run async test cases
    def test_navigator_routing_open_flow(self):
        asyncio.run(self.async_test_navigator_routing_open_flow())

    def test_navigator_routing_start_pipeline(self):
        asyncio.run(self.async_test_navigator_routing_start_pipeline())

    def test_pipeline_debate_concludes_early(self):
        asyncio.run(self.async_test_pipeline_debate_concludes_early())

    def test_pipeline_debate_deadlock(self):
        asyncio.run(self.async_test_pipeline_debate_deadlock())

    def test_poka_yoke_coordinate_filtering(self):
        asyncio.run(self.async_test_poka_yoke_coordinate_filtering())


if __name__ == "__main__":
    unittest.main()
