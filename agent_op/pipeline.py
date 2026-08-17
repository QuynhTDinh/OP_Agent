import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
import asyncio

from google.antigravity import Agent, types
from google.antigravity.types import Document

from agent_op.config import Config
from agent_op.database import get_db
import time
from agent_op.schemas import ExtractionOutput, ReportDraft, CritiqueList, JudgeDecision, ActionCard, TraceabilityTag
from agent_op.agents import (
    get_navigator_config,
    get_scanner_config,
    get_builder_config,
    get_challenger_config,
    get_judge_config,
    get_judge_decision_config
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
        response_text = await response.text()
        
    # Check for routing signal: [START_PIPELINE]
    if "[START_PIPELINE]" in response_text:
        # User has supplied enough info, extract JSON metadata if present
        metadata = {}
        try:
            start_index = response_text.find("[START_PIPELINE]") + len("[START_PIPELINE]")
            json_str = response_text[start_index:].strip()
            if json_str:
                metadata = json.loads(json_str)
        except Exception as e:
            logger.warning(f"Failed to parse Navigator trigger JSON: {e}")
            
        set_session_state(session_id, "PROCESSING")
        
        # Clean response message
        display_message = response_text.split("[START_PIPELINE]")[0].strip()
        if not display_message:
            display_message = "Đã nhận đủ thông tin. Hệ thống đang tiến hành kích hoạt Dây chuyền 4 bước..."
            
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
    return data


async def run_builder(facts_str: str, playbook_text: str) -> ReportDraft:
    """
    Bước 2: OP_Builder - Soạn thảo bản nháp báo cáo ban đầu
    """
    logger.info("Running OP_Builder")
    config = get_builder_config()
    
    prompt = (
        f"Playbook Quy định:\n{playbook_text}\n\n"
        f"Danh sách dữ kiện trích xuất từ Bước 1:\n{facts_str}\n\n"
        "Hãy ráp dữ liệu thực tế vào biểu mẫu quy chuẩn, so sánh đối chiếu và soạn thảo bản nháp báo cáo thẩm định."
    )
    
    async with Agent(config) as agent:
        response = await agent.chat(prompt)
        data = await response.structured_output()
        
    if not data:
        raise ValueError("OP_Builder failed to output valid structured data.")
    return data


async def run_builder_update(current_draft: ReportDraft, judge_instructions: str, playbook_text: str) -> ReportDraft:
    """
    Builder cập nhật lại bản thảo báo cáo dựa trên chỉ thị của Judge
    """
    logger.info("Running OP_Builder (Updating Draft)")
    config = get_builder_config()
    
    prompt = (
        f"Playbook Quy định:\n{playbook_text}\n\n"
        f"Bản thảo báo cáo hiện tại:\n{current_draft.model_dump_json()}\n\n"
        f"Chỉ thị sửa đổi của Judge:\n{judge_instructions}\n\n"
        "Hãy cập nhật và sửa đổi bản thảo báo cáo theo đúng chỉ thị trên. Đảm bảo giữ nguyên tọa độ nguồn chính xác."
    )
    
    async with Agent(config) as agent:
        response = await agent.chat(prompt)
        data = await response.structured_output()
        
    if not data:
        raise ValueError("OP_Builder failed to output valid updated draft.")
    return data


async def run_challenger(current_draft: ReportDraft, playbook_text: str) -> CritiqueList:
    """
    Bước 3A: OP_Challenger - Phản biện bản thảo báo cáo
    """
    logger.info("Running OP_Challenger")
    config = get_challenger_config()
    
    prompt = (
        f"Playbook Quy định:\n{playbook_text}\n\n"
        f"Bản thảo báo cáo hiện tại:\n{current_draft.model_dump_json()}\n\n"
        "Hãy tìm các kẽ hở logic, rủi ro pháp lý/nghiệp vụ chưa được giải quyết hoặc điểm mâu thuẫn trong bản thảo."
    )
    
    async with Agent(config) as agent:
        response = await agent.chat(prompt)
        data = await response.structured_output()
        
    if not data:
        raise ValueError("OP_Challenger failed to output valid structured data.")
    return data


async def run_judge_decision(current_draft: ReportDraft, critique: CritiqueList, playbook_text: str) -> JudgeDecision:
    """
    Bước 3B: OP_Judge - Đưa ra phán quyết hướng dẫn sửa đổi draft
    """
    logger.info("Running OP_Judge (Decision)")
    config = get_judge_decision_config()
    
    # Memory Scrubbing: Judge only gets draft, critique, and playbook excerpt context
    prompt = (
        f"Playbook Quy định:\n{playbook_text}\n\n"
        f"Bản thảo báo cáo hiện tại:\n{current_draft.model_dump_json()}\n\n"
        f"Danh sách phản biện của Challenger:\n{critique.model_dump_json()}\n\n"
        "Hãy đánh giá các phản biện của Challenger, quyết định những điểm nào đúng cần Builder sửa và điểm nào vô lý cần bỏ qua. Đưa ra hướng dẫn chi tiết."
    )
    
    async with Agent(config) as agent:
        response = await agent.chat(prompt)
        data = await response.structured_output()
        
    if not data:
        raise ValueError("OP_Judge failed to output valid decision.")
    return data


async def run_judge_finalize(final_draft: ReportDraft, audit_trail: List[str], playbook_text: str, deadlock: bool) -> ActionCard:
    """
    Judge chốt hạ và đóng gói Action Card kết quả cuối cùng
    """
    logger.info("Running OP_Judge (Finalizing Action Card)")
    config = get_judge_config()
    
    audit_trail_str = "\n".join(audit_trail)
    prompt = (
        f"Playbook Quy định:\n{playbook_text}\n\n"
        f"Bản thảo báo cáo cuối cùng đã sửa đổi:\n{final_draft.model_dump_json()}\n\n"
        f"Lịch sử tranh luận chéo (Audit Trail):\n{audit_trail_str}\n\n"
        f"Trạng thái Deadlock: {deadlock}\n\n"
        "Hãy đóng gói kết quả thành Thẻ Hành Động ActionCard. Nhớ đính kèm các tọa độ nguồn chính xác cho từng phát hiện."
    )
    
    async with Agent(config) as agent:
        response = await agent.chat(prompt)
        data = await response.structured_output()
        
    if not data:
        raise ValueError("OP_Judge failed to output final ActionCard.")
    return data


async def execute_pipeline(document_path: str, playbook_text: str, session_id: str = None) -> ActionCard:
    """
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
        
        # --- BƯỚC 2: LẮP RÁP (OP_Builder) ---
        current_draft = await run_builder(facts_str, playbook_text)
        
        # --- BƯỚC 3: KIỂM CHỨNG & TRANH BIỆN (Challenger vs Judge) ---
        audit_trail = []
        deadlock = False
        
        for turn in range(1, Config.MAX_DEBATE_TURNS + 1):
            logger.info(f"Debate Turn {turn}/{Config.MAX_DEBATE_TURNS}")
            
            # Challenger phản biện
            critique = await run_challenger(current_draft, playbook_text)
            if not critique.critiques:
                audit_trail.append(f"Vòng {turn}: Challenger không tìm thấy thêm điểm mù hay rủi ro logic nào. Bản thảo được thông qua.")
                break
                
            audit_trail.append(f"Vòng {turn} - Phản biện (OP_Challenger): {critique.overall_critique}")
            
            # Judge phân giải
            decision = await run_judge_decision(current_draft, critique, playbook_text)
            audit_trail.append(f"Vòng {turn} - Phán quyết (OP_Judge): {decision.builder_instructions}")
            
            # Builder cập nhật bản thảo dựa trên phán quyết của Judge
            current_draft = await run_builder_update(current_draft, decision.builder_instructions, playbook_text)
            
            if turn == Config.MAX_DEBATE_TURNS:
                logger.warning("Debate loop reached max turns (deadlock).")
                deadlock = True
                audit_trail.append("Cảnh báo: Cuộc tranh luận đạt giới hạn 3 vòng mà chưa ngã ngũ hoàn toàn. Kích hoạt cờ yêu cầu con người xem xét.")

        # --- BƯỚC 4: KẾT LUẬN & ĐỀ XUẤT ---
        action_card = await run_judge_finalize(current_draft, audit_trail, playbook_text, deadlock)
        
        # POKA-YOKE: Traceability Tagging check
        # Loại bỏ các findings và traceability_tags không có tọa độ trùng khớp với Bước 1
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
            
        # Đánh dấu cần duyệt thủ công nếu rủi ro HIGH hoặc deadlock
        if action_card.risk_level == "HIGH" or deadlock:
            action_card.human_review_required = True
            
        if session_id:
            # Reset trạng thái về NAVIGATING sau khi xử lý xong
            set_session_state(session_id, "NAVIGATING")
            
        logger.info(f"Pipeline completed successfully. Action Card title: {action_card.title}")
        return action_card
