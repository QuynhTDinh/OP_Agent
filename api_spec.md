# Tài Liệu Đặc Tả API Tích Hợp: OP_Agent x FNX-OP

Tài liệu này cung cấp đầy đủ đặc tả kỹ thuật và payload mẫu của các API mà hệ thống **OP_Agent** cung cấp để đội ngũ phát triển **FNX-OP** thực hiện tích hợp.

---

## 1. Thông Tin Chung (General Info)
*   **Base URL (Cục bộ):** `http://localhost:8000`
*   **Base URL (Production/Staging):** Cấu hình theo IP/Domain deploy thực tế (ví dụ: `http://10.0.x.x:8000` hoặc `https://op-agent.fnx.vn`).
*   **Swagger UI (Tài liệu tương tác):** `http://localhost:8000/docs`
*   **Phương thức Xác thực (Authentication):**
    *   Mọi request gửi từ FNX-OP sang OP_Agent bắt buộc phải đính kèm Header:
        ```http
        Authorization: Bearer fnx-op-secret-token-2026
        ```
    *   *(Lưu ý: Token này có thể tùy chỉnh trong file `.env` qua khóa `WEBHOOK_SECRET_TOKEN`)*.

---

## 2. API Chi Tiết (Endpoints Spec)

### 2.1 Webhook Tiếp Nhận Hội Thoại (POST /api/webhook/chat)
Được gọi bởi Backend FNX-OP mỗi khi người dùng chat hoặc tải file lên trong Widget Chat.

*   **Endpoint:** `/api/webhook/chat`
*   **Method:** `POST`
*   **Headers:**
    ```http
    Content-Type: application/json
    Authorization: Bearer <WEBHOOK_SECRET_TOKEN>
    ```

#### Request Payload (JSON):
```json
{
  "session_id": "session-simplified-chat-widget-2026",
  "user": {
    "id": "user-12345",
    "email": "quynhdt@fnx.vn",
    "name": "Đinh Thị Thúy Quỳnh"
  },
  "message": {
    "text": "Hãy thẩm định tài liệu này giúp mình",
    "timestamp": 1786438242
  },
  "attachments": [
    {
      "id": "file-uuid-abc-123",
      "name": "contract_sample.txt",
      "url": "/Users/quynhdinh/Documents/OP Agent/scratch/contract_sample.txt",
      "size": 1024,
      "mime_type": "text/plain"
    }
  ],
  "context": {
    "list_id": "column-action-cards"
  }
}
```

#### Các phản hồi mẫu từ OP_Agent:

##### Trường hợp A: Cần thêm thông tin/file (Luồng Navigator hỏi làm rõ)
*   **HTTP Status:** `200 OK`
*   **Response Body:**
    ```json
    {
      "status": "clarification_needed",
      "session_id": "session-simplified-chat-widget-2026",
      "message": "Để thực hiện quy trình Thẩm định & Đối chiếu tài liệu, tôi cần có đầy đủ 2 thông tin sau: 1. Tài liệu cần thẩm định (file đính kèm), 2. Quy chiếu playbook. Vui lòng đính kèm file và cung cấp thêm thông tin!"
    }
    ```

##### Trường hợp B: Đủ thông tin, kích hoạt chạy ngầm (Luồng Heavy Pipeline)
*   **HTTP Status:** `200 OK`
*   **Response Body:**
    ```json
    {
      "status": "processing",
      "session_id": "session-simplified-chat-widget-2026",
      "message": "Đã nhận đủ thông tin. Hệ thống đang kích hoạt dây chuyền tác tử xử lý (Scanner ➔ Builder ➔ Challenger ➔ Judge). Vui lòng đợi trong giây lát, kết quả thẩm định sẽ được trả về trực tiếp tại ô chat này."
    }
    ```

##### Trường hợp C: Chat làm rõ thông thường (Luồng Mở)
*   **HTTP Status:** `200 OK`
*   **Response Body:**
    ```json
    {
      "status": "success",
      "session_id": "session-simplified-chat-widget-2026",
      "message": "Quy định về hạn mức chi tiêu tiếp khách của công ty hiện tại là tối đa 10.000.000 VNĐ cho mỗi sự kiện."
    }
    ```

---

### 2.2 Polling Trạng Thái Chạy Ngầm (GET /api/session-status)
Giao diện Widget Chat của FNX-OP gọi định kỳ (2 giây/lần) sau khi nhận được phản hồi `"status": "processing"` từ webhook chat.

*   **Endpoint:** `/api/session-status`
*   **Method:** `GET`
*   **Query Parameters:**
    *   `session_id` (string, bắt buộc): ID phiên chat cần kiểm tra.

#### Phản hồi mẫu (Khi vẫn đang xử lý):
*   **HTTP Status:** `200 OK`
*   **Response Body:**
    ```json
    {
      "status": "success",
      "session_id": "session-simplified-chat-widget-2026",
      "state": "PROCESSING",
      "result": null
    }
    ```

#### Phản hồi mẫu (Khi hoàn thành thẩm định):
*   **HTTP Status:** `200 OK`
*   **Response Body:**
    ```json
    {
      "status": "success",
      "session_id": "session-simplified-chat-widget-2026",
      "state": "COMPLETED",
      "result": "### 📋 BÁO CÁO THẨM ĐỊNH TỰ ĐỘNG\n*   **Tiêu đề:** Thẩm định hợp đồng dịch vụ\n*   **Kết luận:** Từ chối\n*   **Mức độ Rủi ro:** **HIGH**\n...\n"
    }
    ```
    *(Lưu ý: Sau lượt gọi trả về `COMPLETED` này, hệ thống sẽ tự động dọn dẹp kết quả khỏi RAM và chuyển trạng thái về `NAVIGATING` để nhận yêu cầu mới).*
