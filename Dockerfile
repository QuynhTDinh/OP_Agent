# Sử dụng base image Python chính thức ổn định
FROM python:3.11-slim

# Thiết lập thư mục làm việc trong container
WORKDIR /app

# Sao chép file requirements.txt
COPY requirements.txt .

# Cài đặt các thư viện phụ thuộc
RUN pip install --no-cache-dir -r requirements.txt

# Sao chép mã nguồn và cấu hình
COPY agent_op/ ./agent_op/
COPY playbooks/ ./playbooks/


# Tạo thư mục scratch cho dữ liệu tạm và mount volume
RUN mkdir -p scratch

# Mở cổng API
EXPOSE 8000

# Khởi chạy server FastAPI
CMD ["uvicorn", "agent_op.main:app", "--host", "0.0.0.0", "--port", "8000"]
