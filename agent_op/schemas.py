from typing import List, Optional
from pydantic import BaseModel, Field

# --- BƯỚC 0: Navigator Schema ---
class NavigatorDecision(BaseModel):
    decision: str = Field(description="Quyết định định tuyến. BẮT BUỘC chọn 1 trong 3: 'ASK_CLARIFY' (Hỏi thêm để làm rõ), 'FAST_TRACK' (Tra cứu đơn giản, kiến thức phổ quát, yêu cầu cơ bản), 'DEEP_TRACK' (Thẩm định rủi ro, đối chiếu tài liệu, yêu cầu phức tạp cần tranh luận).")
    message: str = Field(description="Câu trả lời phản hồi lại cho người dùng.")
    
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

# --- STEP 3: Challenger (Red Team) Schemas ---
class ComparisonPoint(BaseModel):
    point_of_contention: str = Field(description="Vấn đề đang được tranh luận hoặc so sánh giữa Draft A và Draft B.")
    alpha_flaw: str = Field(description="Điểm yếu hoặc lỗ hổng logic của Bản nháp Alpha trong vấn đề này.")
    beta_flaw: str = Field(description="Điểm yếu hoặc rủi ro của Bản nháp Beta trong vấn đề này.")
    challenger_verdict: str = Field(description="Nhận định của Challenger: Draft nào xử lý tốt hơn, hoặc cả 2 đều sai ở đâu.")
    severity: str = Field(description="Mức độ nghiêm trọng của vấn đề này: LOW, MEDIUM, HIGH.")

class CrossCritique(BaseModel):
    comparisons: List[ComparisonPoint] = Field(description="Danh sách so sánh chi tiết các lỗ hổng của 2 bản nháp.")
    overall_recommendation: str = Field(description="Khuyến nghị tổng quan của Challenger dành cho Judge về việc nên lấy ý nào của Alpha, ý nào của Beta.")

# --- STEP 4: Action Card (Judge Final Output) Schemas ---
class TraceabilityTag(BaseModel):
    point: str = Field(description="Kết luận hoặc nhận định nghiệp vụ cụ thể.")
    coordinate: str = Field(description="Tọa độ nguồn tương ứng, ví dụ: [Trang 3, Mục 1.2]. Phải là tọa độ hợp lệ từ Bước 1.")

class ActionCard(BaseModel):
    audit_trail: str = Field(description="PHASE 1 (Tư duy nội bộ): Ghi nhận tóm tắt diễn biến tranh biện giữa Challenger và Judge. Đưa ra quyết định chốt hạ xem sẽ sử dụng ý nào, bỏ ý nào.")
    title: str = Field(description="PHASE 2: Tiêu đề Thẻ Hành Động chính thức.")
    summary: str = Field(description="PHASE 2: Tóm tắt quyết định hoặc mở bài câu trả lời ngắn gọn (1-2 câu).")
    risk_level: str = Field(description="Đánh giá mức độ rủi ro cuối cùng: INFO, LOW, MEDIUM, hoặc HIGH.")
    findings: List[str] = Field(description="PHASE 3 (Câu trả lời cho user): Danh sách các phát hiện chính (đối với thẩm định) hoặc các luận điểm, ví dụ giải thích chi tiết, trình bày tự nhiên như ChatGPT (đối với tra cứu).")
    traceability_tags: List[TraceabilityTag] = Field(description="Danh sách tọa độ truy vết nguồn chứng minh cho từng phát hiện.")
    recommendations: List[str] = Field(description="PHASE 3: Kiến nghị và đề xuất hành động thực tiễn cho người dùng.")
    human_review_required: bool = Field(description="Đánh dấu True nếu xảy ra deadlock trong tranh biện hoặc rủi ro ở mức HIGH.")

class ConsultingReport(BaseModel):
    title: str = Field(description="Tiêu đề báo cáo phân tích")
    deep_analysis: str = Field(description="PHẦN PHÂN TÍCH CHÍNH: Viết 3-5 đoạn văn phân tích thật dài, sâu sắc, lập luận chặt chẽ nguyên nhân hệ quả. Tuyệt đối không dùng gạch đầu dòng ngắn.")
    recommendations: List[str] = Field(description="ĐỀ XUẤT CHIẾN LƯỢC: Viết thành các gạch đầu dòng, rất ngắn gọn, súc tích (1-2 câu mỗi ý).")
