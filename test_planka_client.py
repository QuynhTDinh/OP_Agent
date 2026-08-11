import unittest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from agent_op.planka_client import PlankaClient
from agent_op.schemas import ActionCard, TraceabilityTag

class TestPlankaClient(unittest.TestCase):
    def test_mock_mode_create_card(self):
        """Kiểm tra Planka Client ở chế độ MOCK_MODE=True"""
        client = PlankaClient()
        client.mock_mode = True

        async def run_test():
            card = ActionCard(
                title="Hợp đồng thử nghiệm",
                summary="Đồng ý duyệt",
                risk_level="MEDIUM",
                findings=["Không có vi phạm nghiêm trọng."],
                traceability_tags=[
                    TraceabilityTag(point="Không có vi phạm nghiêm trọng.", coordinate="[Trang 1]")
                ],
                recommendations=["Tiếp tục ký kết."],
                audit_trail="Challenger đồng ý.",
                human_review_required=False
            )
            
            card_id = await client.push_action_card("list-mock-123", card)
            self.assertEqual(card_id, "mock-card-uuid-9999")
            
        asyncio.run(run_test())

    @patch("httpx.AsyncClient.post")
    def test_real_mode_login_and_create_card(self, mock_post):
        """Kiểm tra Planka Client ở chế độ REAL (không mock) có thực hiện gọi API đúng cách"""
        client = PlankaClient()
        client.mock_mode = False

        # Giả lập phản hồi đăng nhập
        mock_response_login = MagicMock()
        mock_response_login.json.return_value = {"token": "jwt-abc-123"}
        mock_response_login.raise_for_status = MagicMock()

        # Giả lập phản hồi tạo card
        mock_response_card = MagicMock()
        mock_response_card.json.return_value = {"id": "real-card-uuid-456"}
        mock_response_card.raise_for_status = MagicMock()

        # Áp dụng mock cho các cuộc gọi post lần lượt
        mock_post.side_effect = [mock_response_login, mock_response_card, MagicMock(), MagicMock()]

        async def run_test():
            card = ActionCard(
                title="Hợp đồng thật",
                summary="Đồng ý duyệt",
                risk_level="LOW",
                findings=["Không vi phạm."],
                traceability_tags=[
                    TraceabilityTag(point="Không vi phạm.", coordinate="[Trang 2]")
                ],
                recommendations=["Tiếp tục."],
                audit_trail="",
                human_review_required=False
            )
            
            card_id = await client.push_action_card("list-real-456", card)
            self.assertEqual(card_id, "real-card-uuid-456")
            
            # Đảm bảo login được gọi đúng
            mock_post.assert_any_call(
                "https://operation.fnx.vn/api/access-tokens", 
                json={"email": client.email, "password": client.password}
            )

        asyncio.run(run_test())

if __name__ == "__main__":
    unittest.main()
