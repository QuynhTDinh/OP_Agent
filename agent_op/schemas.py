from typing import List, Optional
from pydantic import BaseModel, Field

# --- STEP 1: Scanner Schemas ---
class FactItem(BaseModel):
    fact: str = Field(description="Mô tả sự kiện, con số hoặc điều khoản nguyên bản được trích xuất từ tài liệu.")
    coordinate: str = Field(description="Tọa độ chính xác của dữ kiện trong tài liệu gốc, ví dụ: [Trang 3, Mục 1.2] hoặc [Trang 5, Hóa đơn số 194].")

class ExtractionOutput(BaseModel):
    found: bool = Field(description="Đánh dấu True nếu tìm thấy dữ kiện liên quan trong tài liệu, False nếu không tìm thấy bất kỳ dữ kiện nào.")
    facts: List[FactItem] = Field(default=[], description="Danh sách các dữ kiện nguyên bản được trích xuất. Trả về danh sách rỗng nếu found=False.")

# --- STEP 2: Builder Schemas ---
class CompareItem(BaseModel):
    playbook_rule: str = Field(description="Nội dung quy định hoặc tiêu chuẩn được lấy làm hệ quy chiếu (từ Playbook hoặc tri thức nghiệp vụ).")
    extracted_fact: str = Field(description="Dữ kiện thực tế tương ứng được trích xuất từ tài liệu của người dùng.")
    status: str = Field(description="Trạng thái đối chiếu: COMPLIANT (Khớp/Tuân thủ), NON_COMPLIANT (Lệch/Vi phạm), WARNING (Cảnh báo), hoặc NOT_APPLICABLE (Không áp dụng).")
    analysis: str = Field(description="Phân tích chi tiết về điểm khớp hoặc lệch giữa dữ kiện thực tế và quy chuẩn đối chiếu.")
    coordinate: str = Field(description="Tọa độ nguồn của dữ kiện thực tế, ví dụ: [Trang 3, Mục 1.2]. Bắt buộc phải khớp với tọa độ từ Bước 1.")

class ReportDraft(BaseModel):
    title: str = Field(description="Tiêu đề của bản thảo báo cáo thẩm định.")
    summary: str = Field(description="Tóm tắt sơ bộ về kết quả đối chiếu tài liệu.")
    comparisons: List[CompareItem] = Field(description="Danh sách các hạng mục đối chiếu chi tiết so với quy chuẩn.")
    draft_conclusions: List[str] = Field(description="Các kết luận sơ bộ của Builder.")

# --- STEP 3A: Challenger (Red Team) Schemas ---
class CritiqueItem(BaseModel):
    target_comparison_index: int = Field(description="Chỉ số (index) của CompareItem trong bản thảo mà Challenger muốn phản biện (bắt đầu từ 0).")
    logic_gap: str = Field(description="Mô tả kẽ hở logic, điểm mù hoặc rủi ro pháp lý/nghiệp vụ ngầm mà Builder đã bỏ sót hoặc phân tích sai.")
    playbook_violation_risk: str = Field(description="Lý do cụ thể tại sao điểm này có nguy cơ vi phạm quy chuẩn Playbook.")
    severity: str = Field(description="Mức độ nghiêm trọng của lỗi được Challenger chỉ ra: LOW, MEDIUM, hoặc HIGH.")

class CritiqueList(BaseModel):
    critiques: List[CritiqueItem] = Field(description="Danh sách các điểm phản biện chi tiết đối với bản thảo.")
    overall_critique: str = Field(description="Nhận xét tổng quan của Challenger về chất lượng và độ tin cậy của bản thảo báo cáo.")

# --- STEP 3B: Judge Decision Schemas ---
class JudgeDecision(BaseModel):
    valid_critiques: List[str] = Field(description="Danh sách các điểm phản biện ĐÚNG của Challenger cần được Builder sửa chữa.")
    invalid_critiques: List[str] = Field(description="Danh sách các điểm phản biện VÔ LÝ hoặc ngoài phạm vi cần được bỏ qua.")
    builder_instructions: str = Field(description="Hướng dẫn chi tiết của Judge yêu cầu Builder phải sửa đổi bản thảo thế nào.")

# --- STEP 4: Action Card (Judge Final Output) Schemas ---
class TraceabilityTag(BaseModel):
    point: str = Field(description="Kết luận hoặc nhận định nghiệp vụ cụ thể.")
    coordinate: str = Field(description="Tọa độ nguồn tương ứng, ví dụ: [Trang 3, Mục 1.2]. Phải là tọa độ hợp lệ từ Bước 1.")

class ActionCard(BaseModel):
    title: str = Field(description="Tiêu đề Thẻ Hành Động chính thức.")
    summary: str = Field(description="Tóm tắt quyết định ngắn gọn, quyết đoán (ví dụ: Đồng ý duyệt, Từ chối, hoặc Yêu cầu bổ sung chứng từ).")
    risk_level: str = Field(description="Đánh giá mức độ rủi ro cuối cùng: INFO, LOW, MEDIUM, hoặc HIGH.")
    findings: List[str] = Field(description="Danh sách các phát hiện chính từ quá trình thẩm định tài liệu.")
    traceability_tags: List[TraceabilityTag] = Field(description="Danh sách tọa độ truy vết nguồn chứng minh cho từng phát hiện.")
    recommendations: List[str] = Field(description="Kiến nghị và đề xuất hành động tiếp theo cho người dùng.")
    audit_trail: str = Field(description="Ghi nhận tóm tắt diễn biến tranh biện giữa Challenger và Judge.")
    human_review_required: bool = Field(description="Đánh dấu True nếu xảy ra deadlock trong tranh biện (đạt tối đa 3 vòng mà chưa ngã ngũ) hoặc rủi ro ở mức HIGH.")
