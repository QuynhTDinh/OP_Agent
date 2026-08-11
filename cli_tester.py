import asyncio
import logging
import sys
from pathlib import Path

from agent_op.config import Config
from agent_op.pipeline import run_navigator, execute_pipeline, get_session_state, set_session_state
from agent_op.planka_client import PlankaClient

# Configure basic logging to console for debug tracking
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout
)
# Silence SDK logs a bit for clean CLI interface
logging.getLogger("google.antigravity").setLevel(logging.WARNING)

async def run_cli_test():
    print("=" * 60)
    print("              AGENT OP - CLI INTERACTIVE TESTER")
    print("=" * 60)
    print("Hệ thống sẽ chạy ở chế độ MOCK Planka để không gọi API thật.")
    print("Bạn có thể chat để làm rõ ý định (Bước 0) hoặc truyền file.")
    print("Nhập 'exit' hoặc 'quit' để thoát.")
    print("-" * 60)

    # Set mock mode explicitly for testing
    Config.PLANKA_MOCK_MODE = True
    session_id = "cli-test-session-uuid-1234567890"
    set_session_state(session_id, "NAVIGATING")

    # Create dummy playbook for test matching
    Config.PLAYBOOKS_DIR.mkdir(parents=True, exist_ok=True)
    playbook_file = Config.PLAYBOOKS_DIR / "playbook.md"
    if not playbook_file.exists():
        playbook_content = """# Quy chuẩn Chi tiêu và Phê duyệt Doanh nghiệpFNX
1. Trần chi tiêu tiếp khách tối đa: 10.000.000 VNĐ / chuyến.
2. Yêu cầu hóa đơn: Mọi hóa đơn taxi phải ghi đầy đủ Mã số thuế công ty FNX.
3. Phê duyệt vượt hạn mức: Phải có văn bản phê duyệt trước từ CEO.
"""
        playbook_file.write_text(playbook_content, encoding="utf-8")
        print(f"Đã tạo file quy chuẩn Playbook mẫu tại: {playbook_file}")

    # Create dummy contract for scanning
    dummy_doc = Config.BASE_DIR / "scratch" / "contract_sample.txt"
    if not dummy_doc.exists():
        dummy_content = """HỒ SƠ THANH TOÁN CHI TIÊU Q2 - PHÒNG HR
- Khoản chi tiếp khách: Chi tiếp khách họp đối tác ngoại giao ngày 12/06. Số tiền: 15.000.000 VNĐ. Tọa độ chứng từ: [Trang 3, Mục 2.1].
- Chi phí di chuyển: taxi Mai Linh đưa đón đối tác. Số tiền: 250.000 VNĐ. Tọa độ chứng từ: [Trang 5, Hóa đơn số 194] (Không có thông tin Mã số thuế công ty).
"""
        dummy_doc.write_text(dummy_content, encoding="utf-8")
        print(f"Đã tạo file tài liệu mẫu cần duyệt tại: {dummy_doc}")

    print(f"Gợi ý file test của bạn: {dummy_doc}")
    print("-" * 60)

    while True:
        try:
            current_state = get_session_state(session_id)
            prompt_prefix = "[ĐANG PHÂN TÍCH] " if current_state == "PROCESSING" else ""
            user_input = input(f"\n{prompt_prefix}User: ").strip()
            
            if not user_input:
                continue
                
            if user_input.lower() in ("exit", "quit"):
                print("Tạm biệt!")
                break

            # Check if user mentioned files or paths
            attachment_paths = []
            if str(dummy_doc) in user_input or "contract_sample.txt" in user_input:
                attachment_paths.append(str(dummy_doc))
                print(f"-> Hệ thống tự động đính kèm file: {dummy_doc}")

            # 1. Gọi Navigator (Bước 0)
            res = await run_navigator(session_id, user_input, attachment_paths)
            print(f"\nOP_Navigator: {res['message']}")

            # 2. Bẻ ghi và kích hoạt pipeline
            if res["status"] == "processing":
                print("\n" + "=" * 40)
                print(">>> KÍCH HOẠT DÂY CHUYỀN 3 BƯỚC CHẠY NGẦM <<<")
                print("=" * 40)
                
                doc_path = str(dummy_doc)
                playbook_text = playbook_file.read_text(encoding="utf-8")
                
                print("-> Bước 1: OP_Scanner đang quét tài liệu...")
                print("-> Bước 2: OP_Builder đang ráp biểu mẫu đối chiếu quy chuẩn...")
                print("-> Bước 3: Đang tiến hành tranh biện chéo (OP_Challenger vs OP_Judge)...")
                
                # Thực thi pipeline
                card = await execute_pipeline(doc_path, playbook_text, session_id=session_id)
                
                print("\n" + "=" * 20 + " THẺ HÀNH ĐỘNG THÀNH PHẨM (ACTION CARD) " + "=" * 20)
                print(f"Tiêu đề: {card.title}")
                print(f"Kết luận: {card.summary}")
                print(f"Mức rủi ro: {card.risk_level}")
                print("\nCác phát hiện:")
                for f in card.findings:
                    print(f"  - {f}")
                print("\nTọa độ truy vết nguồn gốc (Poka-Yoke Verified):")
                for tag in card.traceability_tags:
                    print(f"  - {tag.point} -> {tag.coordinate}")
                print("\nKhuyến nghị:")
                for r in card.recommendations:
                    print(f"  - {r}")
                print(f"\nCần con người xem xét: {card.human_review_required}")
                print("-" * 60)
                
                # Gọi Planka Mock đẩy card
                planka = PlankaClient()
                await planka.push_action_card("list-cli-test", card)
                
        except KeyboardInterrupt:
            print("\nTạm biệt!")
            break
        except Exception as e:
            print(f"\nLỗi hệ thống: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_cli_test())
