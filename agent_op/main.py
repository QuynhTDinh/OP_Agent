import logging
from typing import List, Dict, Any, Optional
from pathlib import Path
import httpx
from fastapi import FastAPI, Header, HTTPException, BackgroundTasks, Query, UploadFile, File
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from agent_op.config import Config
from agent_op.pipeline import (
    run_navigator,
    execute_pipeline,
    get_session_state,
    set_session_state,
    get_session_result,
    set_session_result,
    clear_session_result
)
from agent_op.planka_client import PlankaClient
from agent_op.schemas import ActionCard

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("agent_op.main")

app = FastAPI(
    title="Agent OP Core Engine API",
    description="Hệ thống Trợ lý AI Đa tác tử (Multi-Agent) hỗ trợ FNX-OP",
    version="1.0.0"
)

# --- REQUEST/RESPONSE SCHEMAS ---

class UserSchema(BaseModel):
    id: str
    email: str
    name: str

class MessageSchema(BaseModel):
    text: str
    timestamp: int

class AttachmentSchema(BaseModel):
    id: str
    name: str
    url: str
    size: int
    mime_type: str

class WebhookChatRequest(BaseModel):
    session_id: str
    user: UserSchema
    message: MessageSchema
    attachments: List[AttachmentSchema] = []
    context: Dict[str, Any] = {}

class DirectPipelineRequest(BaseModel):
    document_url_or_path: str = Field(description="URL hoặc đường dẫn file tài liệu cần thẩm định.")
    playbook_text: str = Field(description="Quy định/Playbook nghiệp vụ để đối chiếu.")
    list_id: str = Field(description="List ID trong Planka để tạo Action Card.")
    session_id: Optional[str] = Field(default=None, description="Session ID hội thoại (nếu có).")

# --- HELPER FUNCTIONS ---

async def download_attachment(attachment: AttachmentSchema) -> Path:
    """Tải file đính kèm từ link URL của Planka về scratch directory."""
    # Nếu là đường dẫn cục bộ hiện có, trả về luôn (cho việc test)
    if Path(attachment.url).exists():
        return Path(attachment.url)
        
    dest = Config.SCRATCH_DIR / "downloads" / f"{attachment.id}_{attachment.name}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Đang tải file đính kèm từ: {attachment.url} về {dest}")
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(attachment.url)
            response.raise_for_status()
            dest.write_bytes(response.content)
            logger.info("Tải file đính kèm hoàn tất.")
            return dest
        except Exception as e:
            logger.error(f"Lỗi tải file đính kèm: {e}")
            raise HTTPException(status_code=400, detail=f"Không thể tải file đính kèm: {e}")


async def run_background_pipeline(session_id: str, doc_path: str, playbook_text: str, list_id: str):
    """Hàm chạy ngầm xử lý pipeline đa tác tử và lưu kết quả báo cáo."""
    try:
        # Chạy pipeline
        card = await execute_pipeline(str(doc_path), playbook_text, session_id=session_id)
        
        # Format kết quả báo cáo sang Markdown đẹp mắt
        findings_md = ""
        for i, tag in enumerate(card.traceability_tags, 1):
            findings_md += f"{i}. **{tag.point}** `{tag.coordinate}`\n"
        if not findings_md:
            findings_md = "Không phát hiện lỗi hoặc không tìm thấy bằng chứng đối chiếu."

        recs_md = ""
        for rec in card.recommendations:
            recs_md += f"- {rec}\n"
        if not recs_md:
            recs_md = "- Không có khuyến nghị thêm."

        audit_md = card.audit_trail if card.audit_trail else "Không có lịch sử tranh biện chéo."

        markdown_report = f"""### 📋 BÁO CÁO THẨM ĐỊNH TỰ ĐỘNG
*   **Tiêu đề:** {card.title}
*   **Kết luận:** {card.summary}
*   **Mức độ Rủi ro:** **{card.risk_level}**
*   **Cần con người xem xét:** {'Có ⚠️' if card.human_review_required else 'Không'}

---

#### 🔍 Chi tiết phát hiện & Tọa độ đối chiếu (Poka-Yoke)
{findings_md}

---

#### 💡 Khuyến nghị / Đề xuất hành động
{recs_md}

---

#### ⚔️ Biên bản tranh biện chéo (Audit Trail)
<details>
<summary>Xem chi tiết thảo luận giữa Challenger & Judge</summary>

{audit_md}
</details>
"""
        # Lưu kết quả
        set_session_result(session_id, {"result": markdown_report})
        # Cập nhật trạng thái thành COMPLETED để frontend biết để fetch
        set_session_state(session_id, "COMPLETED")
        
        # Vẫn gọi Planka push card để tương thích ngược nếu cần
        planka = PlankaClient()
        await planka.push_action_card(list_id, card)
        
        logger.info(f"Chạy ngầm hoàn thành. Đã lưu kết quả cho session {session_id}.")
    except Exception as e:
        logger.error(f"Lỗi khi chạy ngầm pipeline cho session {session_id}: {e}")
        # Reset về NAVIGATING nếu có lỗi để cho phép chat lại
        set_session_state(session_id, "NAVIGATING")


# --- ENDPOINTS ---

@app.get("/", response_class=HTMLResponse)
def read_root():
    """Trả về trang UI giả lập tương tác đẹp mắt."""
    static_file = Path(__file__).resolve().parent / "static" / "index.html"
    if static_file.exists():
        return static_file.read_text(encoding="utf-8")
    return """
    <html>
        <head><title>Agent OP Core Engine</title></head>
        <body style="font-family: sans-serif; text-align: center; padding-top: 50px;">
            <h1>Agent OP Core Engine is running</h1>
            <p>UI File not found. Please create agent_op/static/index.html.</p>
        </body>
    </html>
    """


@app.get("/api/health")
def health_check():
    return {
        "status": "healthy",
        "app": "Agent OP Core Engine",
        "mock_mode": Config.PLANKA_MOCK_MODE
    }


@app.get("/api/session-status")
def get_status(session_id: str = Query(...)):
    """Lấy trạng thái và kết quả phân tích của session."""
    state = get_session_state(session_id)
    result = get_session_result(session_id)
    
    # Nếu trạng thái là COMPLETED, sau khi frontend lấy xong kết quả, ta reset về NAVIGATING để user có thể tiếp tục tương tác
    if state == "COMPLETED":
        set_session_state(session_id, "NAVIGATING")
        clear_session_result(session_id)
            
    return {
        "status": "success",
        "session_id": session_id,
        "state": state,
        "result": result.get("result") if result else None
    }




@app.get("/api/playbook")
def get_playbook():
    """Lấy nội dung playbook.md hiện tại."""
    playbook_file = Config.PLAYBOOKS_DIR / "playbook.md"
    if playbook_file.exists():
        return {"content": playbook_file.read_text(encoding="utf-8")}
    return {"content": ""}


@app.post("/api/playbook")
def save_playbook(data: dict):
    """Lưu nội dung playbook.md."""
    playbook_file = Config.PLAYBOOKS_DIR / "playbook.md"
    Config.PLAYBOOKS_DIR.mkdir(parents=True, exist_ok=True)
    content = data.get("content", "")
    playbook_file.write_text(content, encoding="utf-8")
    return {"status": "saved"}


@app.post("/api/upload-file")
async def upload_file(file: UploadFile = File(...)):
    """Upload tài liệu và lưu tạm tại scratch/uploads/ để test."""
    dest = Config.SCRATCH_DIR / "uploads" / file.filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    
    content = await file.read()
    dest.write_bytes(content)
    
    logger.info(f"Đã upload file test cục bộ: {dest}")
    return {
        "id": f"file-{file.filename}",
        "name": file.filename,
        "url": str(dest), # Truyền luôn path cục bộ
        "size": len(content),
        "mime_type": file.content_type or "application/octet-stream"
    }


@app.post("/api/webhook/chat")
async def webhook_chat(
    request: WebhookChatRequest,
    background_tasks: BackgroundTasks,
    authorization: Optional[str] = Header(None)
):
    """
    Webhook tiếp nhận tin nhắn từ widget chat của FNX-OP.
    """
    # Xác thực Webhook Secret Token
    expected_auth = f"Bearer {Config.WEBHOOK_SECRET_TOKEN}"
    if authorization != expected_auth:
        logger.warning("Xác thực Webhook thất bại: Token không hợp lệ.")
        raise HTTPException(status_code=401, detail="Unauthorized")

    session_id = request.session_id
    current_state = get_session_state(session_id)

    # 1. LOCK STATE: Nếu đang xử lý phân tích nền, chặn lại ngay để tiết kiệm LLM quota
    if current_state == "PROCESSING":
        logger.info(f"Session {session_id} đang bận xử lý pipeline nền. Từ chối chat.")
        return {
            "status": "processing",
            "session_id": session_id,
            "message": "Hệ thống đang tiến hành thẩm định tài liệu của bạn. Vui lòng đợi trong giây lát, kết quả sẽ được cập nhật lên bảng công việc ngay khi hoàn tất!"
        }

    # Tải các file đính kèm nếu có
    downloaded_paths = []
    if request.attachments:
        for att in request.attachments:
            path = await download_attachment(att)
            downloaded_paths.append(str(path))

    # 2. FAST CHAT LAYER: Gọi OP_Navigator xử lý nhanh
    try:
        navigator_res = await run_navigator(session_id, request.message.text, downloaded_paths)
    except Exception as e:
        logger.error(f"Lỗi khi chạy Navigator: {e}")
        return {
            "status": "error",
            "session_id": session_id,
            "message": f"Lỗi hệ thống: {str(e)}. (LƯU Ý: Vui lòng kiểm tra xem bạn đã cấu hình đúng GEMINI_API_KEY trong file .env chưa)."
        }

    # 3. KÍCH HOẠT PIPELINE NỀN: Nếu Navigator bẻ ghi báo đủ thông tin
    if navigator_res["status"] == "processing":
        # Xác định list_id trên Planka để đẩy thẻ Action Card
        list_id = request.context.get("list_id", "default-list-id-from-webhook")
        
        # Lấy nội dung playbook. Mặc định đọc playbook.md hoặc dùng playbook cấu hình
        playbook_text = "Thẩm định theo quy chuẩn hoạt động công ty."
        playbook_file = Config.PLAYBOOKS_DIR / "playbook.md"
        if playbook_file.exists():
            playbook_text = playbook_file.read_text(encoding="utf-8")

        # Xác định đường dẫn tài liệu cần thẩm định (file vừa tải hoặc được truyền)
        doc_path = downloaded_paths[0] if downloaded_paths else ""
        if not doc_path and "document" in navigator_res.get("metadata", {}):
            doc_path = navigator_res["metadata"]["document"]

        if not doc_path:
            # Nếu Navigator báo đủ nhưng thực tế không có file, quay lại làm rõ
            set_session_state(session_id, "NAVIGATING")
            return {
                "status": "clarification_needed",
                "session_id": session_id,
                "message": "Không tìm thấy file tài liệu đính kèm để thẩm định. Vui lòng đính kèm file tài liệu cần thẩm định."
            }

        # Đẩy công việc nặng vào hàng đợi chạy ngầm (FastAPI Background Tasks)
        background_tasks.add_task(
            run_background_pipeline, 
            session_id, 
            doc_path, 
            playbook_text, 
            list_id
        )
        
    return navigator_res


@app.post("/api/execute-pipeline")
async def execute_direct_pipeline(
    request: DirectPipelineRequest,
    background: bool = Query(False, description="Chạy ngầm dưới dạng background task nếu set là True.")
):
    """
    Endpoint gọi trực tiếp dây chuyền thẩm định, phục vụ việc kiểm thử qua Swagger UI.
    """
    # Tải file từ URL nếu có, hoặc dùng path cục bộ
    if request.document_url_or_path.startswith("http"):
        # Giả lập tải file đính kèm
        mock_attachment = AttachmentSchema(
            id="temp-file-id",
            name="downloaded_file.pdf",
            url=request.document_url_or_path,
            size=0,
            mime_type="application/pdf"
        )
        dest_path = await download_attachment(mock_attachment)
        document_path = str(dest_path)
    else:
        document_path = request.document_url_or_path
        if not Path(document_path).exists():
            raise HTTPException(status_code=404, detail=f"Không tìm thấy file cục bộ tại: {document_path}")

    # Chạy ngầm
    if background:
        session_id = request.session_id or "direct-api-session-uuid"
        set_session_state(session_id, "PROCESSING")
        # Đẩy background task
        import asyncio
        asyncio.create_task(run_background_pipeline(session_id, document_path, request.playbook_text, request.list_id))
        return {
            "status": "processing",
            "message": "Đã tiếp nhận yêu cầu chạy ngầm. Thẻ Action Card sẽ được đẩy lên Planka."
        }

    # Chạy đồng bộ trực tiếp (tiện cho việc xem JSON trả về ở Swagger)
    try:
        card = await execute_pipeline(document_path, request.playbook_text, session_id=request.session_id)
        # Đẩy lên Planka
        planka = PlankaClient()
        card_id = await planka.push_action_card(request.list_id, card)
        
        return {
            "status": "success",
            "card_id": card_id,
            "action_card": card
        }
    except Exception as e:
        logger.error(f"Lỗi thực thi pipeline đồng bộ: {e}")
        raise HTTPException(status_code=500, detail=str(e))
