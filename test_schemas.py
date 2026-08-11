import unittest
from pydantic import ValidationError
from agent_op.schemas import FactItem, ExtractionOutput, CompareItem, ReportDraft, CritiqueItem, CritiqueList, ActionCard, TraceabilityTag

class TestSchemas(unittest.TestCase):
    def test_fact_item_validation_success(self):
        """Kiểm tra validation thành công với FactItem hợp lệ"""
        data = {
            "fact": "Khoản chi tiếp khách 15.000.000 VNĐ.",
            "coordinate": "[Trang 3, Mục 2.1]"
        }
        item = FactItem(**data)
        self.assertEqual(item.fact, data["fact"])
        self.assertEqual(item.coordinate, data["coordinate"])

    def test_extraction_output_validation_success(self):
        """Kiểm tra validation thành công với ExtractionOutput"""
        data = {
            "found": True,
            "facts": [
                {"fact": "Dữ kiện 1", "coordinate": "[Trang 1]"},
                {"fact": "Dữ kiện 2", "coordinate": "[Trang 2]"}
            ]
        }
        output = ExtractionOutput(**data)
        self.assertTrue(output.found)
        self.assertEqual(len(output.facts), 2)
        self.assertEqual(output.facts[0].fact, "Dữ kiện 1")

    def test_extraction_output_validation_missing_fields(self):
        """Kiểm tra validation thất bại khi thiếu trường bắt buộc (found)"""
        data = {
            "facts": []
        }
        with self.assertRaises(ValidationError):
            # Thiếu field 'found' bắt buộc
            ExtractionOutput(**data)

    def test_compare_item_validation_success(self):
        """Kiểm tra CompareItem"""
        data = {
            "playbook_rule": "Hạn mức taxi tối đa 200.000 VNĐ/chuyến.",
            "extracted_fact": "Chi phí chuyến đi taxi là 250.000 VNĐ.",
            "status": "NON_COMPLIANT",
            "analysis": "Chi phí vượt quá hạn mức quy định 50.000 VNĐ.",
            "coordinate": "[Trang 5, Hóa đơn số 194]"
        }
        item = CompareItem(**data)
        self.assertEqual(item.status, "NON_COMPLIANT")

    def test_action_card_validation_success(self):
        """Kiểm tra ActionCard thành công"""
        data = {
            "title": "[Action Card] Thẩm Định Chi Tiêu Q2",
            "summary": "Từ chối phê duyệt thanh toán vượt hạn mức.",
            "risk_level": "HIGH",
            "findings": ["Chi tiếp khách 15tr vượt trần 10tr."],
            "traceability_tags": [
                {"point": "Chi tiếp khách 15tr vượt trần 10tr.", "coordinate": "[Trang 3, Mục 2.1]"}
            ],
            "recommendations": ["Yêu cầu HR hoàn trả phần vượt hạn mức."],
            "audit_trail": "Challenger vs Judge debate completed.",
            "human_review_required": True
        }
        card = ActionCard(**data)
        self.assertEqual(card.risk_level, "HIGH")
        self.assertEqual(card.traceability_tags[0].coordinate, "[Trang 3, Mục 2.1]")

if __name__ == "__main__":
    unittest.main()
