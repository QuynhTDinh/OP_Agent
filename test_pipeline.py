import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

# Mock the environment variable before importing main
import os
os.environ["GEMINI_API_KEY"] = "mock-key-for-testing"
os.environ["PLANKA_MOCK_MODE"] = "True"

from agent_op.main import app
from agent_op.config import Config
from agent_op.schemas import ActionCard, TraceabilityTag

class TestPipelineE2E(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.secret_token = Config.WEBHOOK_SECRET_TOKEN
        
        # Tạo file tạm phục vụ test E2E
        self.test_dir = Path("./scratch")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.test_file = self.test_dir / "contract_sample.txt"
        self.test_file.write_text("Dummy content for testing", encoding="utf-8")

        # Mock database storage using a local dictionary
        self.mock_db_reports = {}
        
        async def mock_save(session_id, report_data):
            self.mock_db_reports[session_id] = report_data
            
        async def mock_get(session_id):
            return self.mock_db_reports.get(session_id)
            
        async def mock_clear(session_id):
            if session_id in self.mock_db_reports:
                del self.mock_db_reports[session_id]
                
        async def mock_health():
            return True

        # Start patchers for DB helpers
        self.patcher_save = patch("agent_op.main.save_audit_report", new=mock_save)
        self.patcher_get = patch("agent_op.main.get_audit_report", new=mock_get)
        self.patcher_clear = patch("agent_op.main.clear_audit_report", new=mock_clear)
        self.patcher_health = patch("agent_op.main.check_db_health", new=mock_health)
        
        self.patcher_save.start()
        self.patcher_get.start()
        self.patcher_clear.start()
        self.patcher_health.start()

    def tearDown(self):
        # Stop patchers
        self.patcher_save.stop()
        self.patcher_get.stop()
        self.patcher_clear.stop()
        self.patcher_health.stop()


    def test_health_check(self):
        """Kiểm tra health check endpoint /api/health"""
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["app"], "Agent OP Core Engine")

    def test_webhook_chat_unauthorized(self):
        """Kiểm tra webhook chat báo lỗi 401 khi thiếu/sai token"""
        payload = {
            "session_id": "session-test-e2e",
            "user": {"id": "1", "email": "a@a.com", "name": "User"},
            "message": {"text": "Hello", "timestamp": 12345}
        }
        response = self.client.post("/api/webhook/chat", json=payload)
        self.assertEqual(response.status_code, 401)

    @patch("agent_op.main.run_navigator")
    def test_webhook_chat_authorized_clarification(self, mock_run_navigator):
        """Kiểm tra webhook chat thành công khi có token và trả về thông tin làm rõ"""
        mock_run_navigator.return_value = {
            "status": "clarification_needed",
            "session_id": "session-test-e2e",
            "message": "Vui lòng cung cấp thêm playbook."
        }

        payload = {
            "session_id": "session-test-e2e",
            "user": {"id": "1", "email": "a@a.com", "name": "User"},
            "message": {"text": "Phân tích file báo cáo này nhé", "timestamp": 12345}
        }
        headers = {"Authorization": f"Bearer {self.secret_token}"}
        
        response = self.client.post("/api/webhook/chat", json=payload, headers=headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "clarification_needed")
        self.assertEqual(data["message"], "Vui lòng cung cấp thêm playbook.")

    @patch("agent_op.main.run_navigator")
    @patch("agent_op.main.execute_pipeline")
    def test_webhook_chat_starts_background_pipeline(self, mock_execute_pipeline, mock_run_navigator):
        """Kiểm tra webhook kích hoạt chạy ngầm pipeline khi navigator trả về status=processing"""
        # Giả lập Navigator báo đủ thông tin
        mock_run_navigator.return_value = {
            "status": "processing",
            "session_id": "session-test-e2e-2",
            "message": "Đã đủ thông tin. Bắt đầu chạy...",
            "metadata": {"document": "dummy_contract.txt"}
        }

        # Giả lập pipeline trả về ActionCard
        mock_execute_pipeline.return_value = ActionCard(
            title="Báo cáo",
            summary="Duyệt",
            risk_level="LOW",
            findings=["Hợp lệ"],
            traceability_tags=[TraceabilityTag(point="Hợp lệ", coordinate="[Trang 1]")],
            recommendations=[],
            audit_trail="",
            human_review_required=False
        )

        payload = {
            "session_id": "session-test-e2e-2",
            "user": {"id": "1", "email": "a@a.com", "name": "User"},
            "message": {"text": "Phân tích đi", "timestamp": 12345},
            "attachments": [
                {
                    "id": "file-1",
                    "name": "dummy_contract.txt",
                    "url": "./scratch/contract_sample.txt",  # Sử dụng file có sẵn
                    "size": 100,
                    "mime_type": "text/plain"
                }
            ]
        }
        headers = {"Authorization": f"Bearer {self.secret_token}"}
        
        # TestClient sẽ thực thi các BackgroundTasks một cách đồng bộ trong cuộc gọi post này
        response = self.client.post("/api/webhook/chat", json=payload, headers=headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "processing")

        # Truy vấn status lần đầu (phải trả về COMPLETED và có kết quả)
        status_res = self.client.get("/api/session-status?session_id=session-test-e2e-2")
        self.assertEqual(status_res.status_code, 200)
        status_data = status_res.json()
        self.assertEqual(status_data["state"], "COMPLETED")
        self.assertIn("BÁO CÁO THẨM ĐỊNH TỰ ĐỘNG", status_data["result"])

        # Truy vấn status lần hai (phải tự động reset về NAVIGATING và xóa kết quả)
        status_res2 = self.client.get("/api/session-status?session_id=session-test-e2e-2")
        self.assertEqual(status_res2.status_code, 200)
        status_data2 = status_res2.json()
        self.assertEqual(status_data2["state"], "NAVIGATING")
        self.assertIsNone(status_data2["result"])


    @patch("agent_op.main.execute_pipeline")
    def test_execute_direct_pipeline_success(self, mock_execute_pipeline):
        """Kiểm tra gọi trực tiếp API execute-pipeline bằng Swagger/Direct Call"""
        mock_execute_pipeline.return_value = ActionCard(
            title="Báo cáo trực tiếp",
            summary="Từ chối",
            risk_level="HIGH",
            findings=["Lỗi nghiêm trọng"],
            traceability_tags=[TraceabilityTag(point="Lỗi nghiêm trọng", coordinate="[Trang 2]")],
            recommendations=[],
            audit_trail="",
            human_review_required=True
        )

        payload = {
            "document_url_or_path": "./scratch/contract_sample.txt",
            "playbook_text": "Quy tắc 1",
            "list_id": "list-123"
        }
        
        response = self.client.post("/api/execute-pipeline", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["card_id"], "mongodb-saved-uuid")
        self.assertEqual(data["action_card"]["risk_level"], "HIGH")


if __name__ == "__main__":
    unittest.main()
