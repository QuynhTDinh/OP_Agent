import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional, Union
import asyncio

from google.antigravity import Agent, types, LocalAgentConfig
from google.antigravity.types import Document

from agent_op.config import Config
from agent_op.database import get_db
import time
from agent_op.schemas import ExtractionOutput, ReportDraft, CrossCritique, ActionCard, TraceabilityTag, ConsultingReport
from agent_op.agents import (
    get_navigator_config,
    get_scanner_config,
    get_builder_alpha_config,
    get_builder_beta_config,
    get_challenger_config,
    get_judge_config
)

logger = logging.getLogger("agent_op.pipeline")

# In-memory session store for tracking conversation state
# Maps session_id -> current status ("NAVIGATING", "PROCESSING", "COMPLETED")
session_states: Dict[str, str] = {}
session_results: Dict[str, Dict[str, Any]] = {}

# Semaphore to control parallel LLM pipeline tasks (Concurrency Guard)
pipeline_semaphore = asyncio.Semaphore(Config.MAX_CONCURRENT_LLM_TASKS)


def get_session_state(session_id: str) -> str:
    return session_states.get(session_id, "NAVIGATING")


def set_session_state(session_id: str, state: str):
    session_states[session_id] = state
    logger.info(f"Session {session_id} state updated to: {state}")


def get_session_result(session_id: str) -> Optional[Dict[str, Any]]:
    return session_results.get(session_id)


def set_session_result(session_id: str, result: Dict[str, Any]):
    session_results[session_id] = result


def clear_session_result(session_id: str):
    if session_id in session_results:
        del session_results[session_id]


def format_conversation_id(session_id: str) -> str:
    """Đảm bảo conversation_id có độ dài tối thiểu 32 ký tự bằng cách băm MD5 nếu cần."""
    import hashlib
    if len(session_id) < 32:
        return hashlib.md5(session_id.encode('utf-8')).hexdigest()
    return session_id


async def run_navigator(session_id: str, message: str, attachment_paths: List[str] = None) -> Dict[str, Any]:
    """
    Bước 0: OP_Navigator - Nhận tin nhắn và làm rõ yêu cầu.
    """
    history_text = ""
    chat_col = None
    
    # 1. LOAD HISTORY FROM MONGODB (WITH RISK MITIGATION)
    try:
        db = get_db()
        chat_col = db["chat_history"]
        cursor = chat_col.find({"session_id": session_id}).sort("timestamp", 1)
        history_msgs = await cursor.to_list(length=50)
        
        # Build sliding window memory (limit history context to 4000 characters)
        history_lines = []
        accumulated_len = 0
        for msg in reversed(history_msgs):
            line = f"{msg['role']}: {msg['text']}\n"
            if accumulated_len + len(line) <= 4000:
                history_lines.insert(0, line)
                accumulated_len += len(line)
            else:
                break
        history_text = "".join(history_lines)
    except Exception as e:
        logger.error(f"Error loading chat history from MongoDB: {e}")
        history_text = ""

    # 2. CONSTRUCT PROMPT WITH SYSTEM BOUNDARY
    prompt_content = ""
    if history_text:
        prompt_content += f"[LỊCH SỬ HỘI THOẠI GẦN NHẤT]\n{history_text}\n"
    prompt_content += f"[TIN NHẮN MỚI CỦA USER]\nUser: {message}\n"

    # Compile files if any
    chat_inputs = [prompt_content]
    if attachment_paths:
        for path in attachment_paths:
            if Path(path).exists():
                logger.info(f"Navigator loading attachment: {path}")
                chat_inputs.append(Document.from_file(path))

    # 3. CALL GEMINI MODEL (WITHOUT SQLITE PERSISTENCE TO GUARANTEE CONTEXT CAPPING)
    config = get_navigator_config()
    async with Agent(config) as agent:
        response = await agent.chat(chat_inputs)
        data = await response.structured_output()
        
    if not data:
        raw_text = await response.text()
        logger.error(f"Navigator failed JSON validation. Raw text: {raw_text}")
        return {"status": "error", "message": "Lỗi hệ thống phân loại ngữ cảnh."}
        
    decision = data.get("decision")
    display_message = data.get("message", "")
        
    # Check for routing signal
    if decision in ["FAST_TRACK", "DEEP_TRACK"]:
        metadata = {"track": decision}
        
        set_session_state(session_id, "PROCESSING")
        
        # Ẩn tin nhắn báo cáo tiến trình theo yêu cầu của user, chỉ để UI hiển thị loading
        display_message = ""
            
        # CLEAR HISTORY FOR COMPLETED NAVIGATING SESSION
        if chat_col is not None:
            try:
                await chat_col.delete_many({"session_id": session_id})
                logger.info(f"Cleared chat history in MongoDB for session: {session_id}")
            except Exception as e:
                logger.error(f"Error clearing chat history in MongoDB: {e}")

        return {
            "status": "processing",
            "session_id": session_id,
            "message": display_message,
            "metadata": metadata
        }
    else:
        # Tức là ASK_CLARIFY
        return {
            "status": "clarification_needed",
            "session_id": session_id,
            "message": display_message
        }
        
    # 4. SAVE NEW CHAT TURNS TO MONGODB (IF NOT TRIGGERING PIPELINE)
    if chat_col is not None:
        try:
            now = time.time()
            await chat_col.insert_many([
                {
                    "session_id": session_id,
                    "role": "User",
                    "text": message,
                    "timestamp": now
                },
                {
                    "session_id": session_id,
                    "role": "Trợ lý",
                    "text": response_text.strip(),
                    "timestamp": now + 0.1
                }
            ])
        except Exception as e:
            logger.error(f"Error saving chat turn to MongoDB: {e}")

    return {
        "status": "clarification_needed",
        "session_id": session_id,
        "message": response_text
    }


async def run_scanner(document_path: str) -> ExtractionOutput:
    """
    Bước 1: OP_Scanner - Trích xuất các dữ kiện nguyên bản kèm tọa độ
    """
    logger.info(f"Running OP_Scanner on {document_path}")
    config = get_scanner_config()
    
    async with Agent(config) as agent:
        doc = Document.from_file(document_path)
        prompt = "Hãy quét tài liệu đính kèm và trích xuất tất cả các sự kiện (facts), số liệu hoặc điều khoản nguyên bản kèm tọa độ."
        response = await agent.chat([prompt, doc])
        data = await response.structured_output()
        
    if not data:
        raise ValueError("OP_Scanner failed to output valid structured data.")
    return ExtractionOutput(**data)


async def run_builders_parallel(facts_str: str, playbook_text: Optional[str] = None) -> Tuple[ReportDraft, ReportDraft]:
    """
    Bước 2: OP_Builder (Fork) - Gọi 2 tiến trình Alpha và Beta chạy song song.
    """
    logger.info("Running OP_Builder (Alpha & Beta in Parallel)")
    config_alpha = get_builder_alpha_config()
    config_beta = get_builder_beta_config()
    
    if playbook_text:
        prompt = (
            f"Playbook Quy định:\n{playbook_text}\n\n"
            f"Danh sách dữ kiện trích xuất từ Bước 1:\n{facts_str}\n\n"
            "Hãy ráp dữ liệu thực tế vào biểu mẫu quy chuẩn, phân tích chi tiết và soạn thảo bản nháp báo cáo."
        )
    else:
        prompt = (
            f"Danh sách dữ kiện từ Bước 1:\n{facts_str}\n\n"
            "Hãy sử dụng tri thức mở của bạn để soạn thảo câu trả lời cho người dùng."
        )
    
    async def run_agent(config: LocalAgentConfig) -> ReportDraft:
        async with Agent(config) as agent:
            response = await agent.chat(prompt)
            data = await response.structured_output()
        if not data:
            raw_text = await response.text()
            logger.error(f"Builder failed JSON validation. Raw text: {raw_text}")
            raise ValueError("Builder failed to output valid data.")
        return ReportDraft(**data)

    draft_a, draft_b = await asyncio.gather(
        run_agent(config_alpha),
        run_agent(config_beta)
    )
    return draft_a, draft_b


async def run_challenger(draft_a: ReportDraft, draft_b: ReportDraft, playbook_text: Optional[str] = None) -> CrossCritique:
    """
    Bước 3: OP_Challenger (Debate) - Phản biện chéo 2 bản nháp
    """
    logger.info("Running OP_Challenger (Cross-Critique)")
    config = get_challenger_config()
    
    prompt = (
        f"Playbook (nếu có):\n{playbook_text if playbook_text else 'Không có'}\n\n"
        f"Bản nháp A (Alpha - Thiên về An toàn):\n{draft_a.model_dump_json()}\n\n"
        f"Bản nháp B (Beta - Thiên về Linh hoạt):\n{draft_b.model_dump_json()}\n\n"
        "Hãy so sánh, đối chiếu và vạch trần lỗ hổng logic/rủi ro của cả 2 bản nháp."
    )
    
    async with Agent(config) as agent:
        response = await agent.chat(prompt)
        data = await response.structured_output()
        
    if not data:
        raise ValueError("OP_Challenger failed to output valid CrossCritique.")
    return CrossCritique(**data)


async def run_judge_synthesis(draft_a: ReportDraft, draft_b: ReportDraft, critique: CrossCritique, playbook_text: Optional[str] = None) -> Union[ActionCard, ConsultingReport]:
    """
    Bước 4: OP_Judge (Join & Synthesize) - Chủ tọa chốt đáp án
    """
    logger.info("Running OP_Judge (Synthesis)")
    config = get_judge_config()
    
    if playbook_text:
        task_instruction = "Hãy đóng vai Chủ tọa, dung hòa các điểm đúng, loại bỏ điểm sai, tuân thủ 3 Tiêu chuẩn Phán quyết (Ưu tiên an toàn, Khách quan, Giải thích lý do) và viết ra Action Card cuối cùng đánh giá rủi ro."
    else:
        task_instruction = (
            "ĐÂY LÀ YÊU CẦU PHÂN TÍCH CHUYÊN SÂU. Đóng vai trò là Chuyên gia Tư vấn Cấp cao, bạn hãy tổng hợp lập luận từ các bên để viết báo cáo cho người dùng theo các quy định NGHIÊM NGẶT sau:\n"
            "1. TIÊU CHUẨN PHÁN QUYẾT (Cập nhật): Đánh giá rủi ro (An toàn) và Giải pháp (Linh hoạt) một cách công bằng. Nếu rủi ro ở mức nghiêm trọng (vi phạm luật pháp/đạo đức), ưu tiên An toàn. Nếu rủi ro có thể kiểm soát, hãy ưu tiên đưa ra Giải pháp thực tiễn.\n"
            "2. TẬP TRUNG PHÂN TÍCH (Trường deep_analysis): Trình bày phân tích theo cấu trúc mạch lạc, chia thành các đề mục nhỏ (Tiêu đề in đậm) đại diện cho từng khía cạnh vấn đề. Sử dụng câu văn gãy gọn, diễn đạt nhân quả rõ ràng. ĐƯỢC PHÉP dùng gạch đầu dòng hoặc danh sách để làm nổi bật các luận điểm chính, kết hợp với các đoạn văn ngắn giải thích bối cảnh. Tuyệt đối tránh lối viết lê thê, lý thuyết vĩ mô.\n"
            "3. ĐỀ XUẤT NGẮN GỌN (Trường recommendations): Đưa ra 3-5 hành động cụ thể, trực diện (Actionable insights). Mỗi đề xuất không quá 2 câu, tập trung vào việc \"Nên làm gì tiếp theo?\".\n"
            "4. VĂN PHONG: Chuyên nghiệp, hiện đại, mang tính xây dựng. Tuyệt đối không nhắc đến các quy trình nội bộ (OP, Alpha, Beta, Challenger, Draft, Playbook) trong câu trả lời."
        )

    prompt = (
        f"Playbook (Hiến pháp tối cao):\n{playbook_text if playbook_text else 'Không có'}\n\n"
        f"Bản nháp A:\n{draft_a.model_dump_json()}\n\n"
        f"Bản nháp B:\n{draft_b.model_dump_json()}\n\n"
        f"Biên bản phản biện chéo:\n{critique.model_dump_json()}\n\n"
        f"Nhiệm vụ của bạn:\n{task_instruction}"
    )
    
    # Configure structured output dynamically based on playbook_text
    config.response_schema = ActionCard if playbook_text else ConsultingReport

    async with Agent(config) as agent:
        response = await agent.chat(prompt)
        data = await response.structured_output()
        
    if not data:
        raise ValueError("OP_Judge failed to output final Report.")
    
    return ActionCard(**data) if playbook_text else ConsultingReport(**data)

async def execute_fast_track(query: str, session_id: str = None) -> str:
    """
    Luồng Fast Track: Chỉ sử dụng 1 Agent để trả lời nhanh.
    Trả về raw markdown string thay vì ActionCard JSON.
    """
    logger.info("Running FAST TRACK (Single Agent QA)")
    config = LocalAgentConfig(
        model="gemini-2.5-flash",
        system_instructions="Bạn là OP_Expert, một chuyên gia AI (như ChatGPT). Trả lời CÂU HỎI của người dùng một cách trực tiếp, tự nhiên, và hữu ích. Sử dụng định dạng Markdown.",
        temperature=0.7,
        api_key=Config.GEMINI_API_KEY if Config.GEMINI_API_KEY else None
    )
    
    prompt = f"Câu hỏi của tôi là: {query}"
    
    async with Agent(config) as agent:
        response = await agent.chat(prompt)
        text = await response.text()
        
    if not text:
        return "Xin lỗi, OP_Expert không thể đưa ra câu trả lời lúc này."
    return text

async def execute_pipeline(document_path: str, playbook_text: Optional[str] = None, session_id: str = None) -> Union[ActionCard, ConsultingReport]:
    """
    Chạy toàn bộ luồng 4 tác tử.
    Dây chuyền 3 bước khép kín (Scanner -> Builder -> Challenger/Judge -> Final Action Card)
    Được kiểm soát bởi Semaphore để tránh quá tải đồng thời.
    """
    async with pipeline_semaphore:
        logger.info(f"Pipeline started for document: {document_path}")
        
        # --- BƯỚC 1: TRÍCH XẤT (OP_Scanner) ---
        extraction_result = await run_scanner(document_path)
        
        if not extraction_result.found or not extraction_result.facts:
            logger.info("OP_Scanner found no relevant facts in the document.")
            return ActionCard(
                title="Báo cáo Thẩm định - Không Tìm Thấy Dữ Liệu",
                summary="Hủy quy trình thẩm định.",
                risk_level="INFO",
                findings=["Không tìm thấy dữ kiện hoặc số liệu nào liên quan trong tài liệu."],
                traceability_tags=[],
                recommendations=["Vui lòng kiểm tra lại tính hợp lệ và nội dung của tài liệu tải lên."],
                audit_trail="Scanner trả về Null. Quy trình dừng tại Bước 1.",
                human_review_required=False
            )
            
        # Biến đổi facts thành chuỗi văn bản cho Builder dễ đọc
        facts_list = [f"- Dữ kiện: {item.fact} (Tọa độ: {item.coordinate})" for item in extraction_result.facts]
        facts_str = "\n".join(facts_list)
        valid_coordinates = {item.coordinate for item in extraction_result.facts}
        # --- BƯỚC 2: LẮP RÁP ĐA CHIỀU (OP_Builder Fork) ---
        draft_a, draft_b = await run_builders_parallel(facts_str, playbook_text)
        
        # --- BƯỚC 3: TRANH BIỆN CHÉO (OP_Challenger) ---
        critique = await run_challenger(draft_a, draft_b, playbook_text)
        
        # --- BƯỚC 4: TỔNG HỢP & PHÁN QUYẾT (OP_Judge Join) ---
        action_card = await run_judge_synthesis(draft_a, draft_b, critique, playbook_text)
        
        # POKA-YOKE: Traceability Tagging check
        # Loại bỏ các findings và traceability_tags không có tọa độ trùng khớp với Bước 1
        if playbook_text:
            filtered_findings = []
            filtered_tags = []
            
            for tag in action_card.traceability_tags:
                # Chuẩn hóa tọa độ để so khớp
                clean_coordinate = tag.coordinate.strip()
                if clean_coordinate in valid_coordinates:
                    filtered_tags.append(tag)
                    # Tìm finding tương ứng
                    filtered_findings.append(tag.point)
                else:
                    logger.warning(f"Poka-Yoke: Loại bỏ kết luận không có tọa độ trích xuất hợp lệ: {tag.point} ({tag.coordinate})")
            
            # Cập nhật lại các trường dữ liệu của Action Card sau khi lọc
            if filtered_tags:
                action_card.traceability_tags = filtered_tags
                action_card.findings = filtered_findings
            else:
                # Nếu tất cả tọa độ bị loại bỏ (hallucination), ghi nhận lỗi
                logger.error("Poka-Yoke Warning: Mọi tọa độ trong ActionCard đều không hợp lệ.")
                action_card.findings = ["Phát hiện lỗi ảo giác (Hallucination) từ mô hình: Các kết luận thiếu bằng chứng tọa độ trích xuất."]
                action_card.traceability_tags = []
                action_card.human_review_required = True
                
            if action_card.risk_level == "HIGH":
                action_card.human_review_required = True

        logger.info(f"Pipeline completed successfully. Action Card title: {action_card.title}")
        return action_card
