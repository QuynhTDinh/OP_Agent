#!/bin/bash

# Dừng thực thi nếu có lỗi xảy ra
set -e

echo "===================================================="
echo "          AGENT OP CORE ENGINE - STARTUP SCRIPT"
echo "===================================================="

# 1. Kiểm tra môi trường ảo và cài đặt thư viện
if [ ! -d "venv" ]; then
    echo "Tạo môi trường ảo Python venv..."
    python3 -m venv venv
fi

echo "Kích hoạt môi trường ảo và cài đặt dependencies..."
source venv/bin/activate
pip install -r requirements.txt

# 2. Khởi tạo file .env nếu chưa có
if [ ! -f ".env" ]; then
    echo "Không tìm thấy file .env, khởi tạo từ .env.example..."
    cp .env.example .env
    echo "LƯU Ý: Vui lòng mở file .env và cập nhật GEMINI_API_KEY của bạn!"
fi

# 3. Chạy toàn bộ test suite để kiểm tra tính toàn vẹn
echo "Đang chạy test suite..."
python3 test_schemas.py
python3 test_pipeline_logic.py
python3 test_planka_client.py
python3 test_pipeline.py

echo "----------------------------------------------------"
echo "Chạy test thành công 100%! Chất lượng đạt chuẩn."
echo "----------------------------------------------------"

# 4. Gợi ý chạy server hoặc CLI tester
echo "Để chạy thử nghiệm tương tác trong terminal, gõ:"
echo "  python3 cli_tester.py"
echo ""
echo "Để chạy server API FastAPI, gõ:"
echo "  uvicorn agent_op.main:app --reload --port 8000"
echo "===================================================="
