import logging
import httpx
from typing import Dict, Any, Optional

from agent_op.config import Config
from agent_op.schemas import ActionCard

logger = logging.getLogger("agent_op.planka")

class PlankaClient:
    def __init__(self):
        self.base_url = Config.PLANKA_API_URL.rstrip('/')
        self.email = Config.PLANKA_EMAIL
        self.password = Config.PLANKA_PASSWORD
        self.mock_mode = Config.PLANKA_MOCK_MODE
        self._token: Optional[str] = None

    async def get_token(self) -> str:
        """Đăng nhập Planka và lấy JWT Token (hoặc trả về cached token)."""
        if self._token:
            return self._token

        if self.mock_mode:
            logger.info("Planka Mock Mode: Đăng nhập giả lập thành công.")
            self._token = "mock-jwt-token-123456789"
            return self._token

        url = f"{self.base_url}/api/access-tokens"
        payload = {
            "email": self.email,
            "password": self.password
        }
        
        logger.info(f"Đang kết nối tới Planka tại {url}...")
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                self._token = data.get("token")
                if not self._token:
                    # In some older Planka setups it could be inside 'item' or different key
                    self._token = data.get("item", {}).get("token")
                
                if not self._token:
                    raise ValueError(f"Không tìm thấy trường token trong phản hồi từ Planka: {data}")
                
                logger.info("Đăng nhập Planka thành công, đã nhận JWT Token.")
                return self._token
            except Exception as e:
                logger.error(f"Lỗi đăng nhập Planka: {e}")
                raise

    async def create_card(self, list_id: str, name: str, description: str) -> Dict[str, Any]:
        """Tạo thẻ công việc (Card) mới trong Planka."""
        if self.mock_mode:
            logger.info(f"Planka Mock Mode [CREATE_CARD]: listId={list_id}, name={name}")
            logger.info(f"Description:\n{description}")
            return {"id": "mock-card-uuid-9999", "name": name, "listId": list_id}

        token = await self.get_token()
        url = f"{self.base_url}/api/cards"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        payload = {
            "listId": list_id,
            "name": name,
            "description": description
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                card_data = response.json()
                logger.info(f"Tạo Card thành công trên Planka. Card ID: {card_data.get('id')}")
                return card_data
            except Exception as e:
                logger.error(f"Lỗi tạo Card trên Planka: {e}")
                raise

    async def add_label_to_card(self, card_id: str, label_id: str) -> bool:
        """Gán nhãn rủi ro màu sắc cho Card."""
        if self.mock_mode:
            logger.info(f"Planka Mock Mode [ADD_LABEL]: cardId={card_id}, labelId={label_id}")
            return True

        token = await self.get_token()
        url = f"{self.base_url}/api/cards/{card_id}/labels"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        payload = {
            "labelId": label_id
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                logger.info(f"Đã gán nhãn {label_id} cho Card {card_id}")
                return True
            except Exception as e:
                logger.error(f"Lỗi gán nhãn cho Card trên Planka: {e}")
                # Không làm sập quy trình chính nếu chỉ lỗi gán nhãn
                return False

    async def add_comment_to_card(self, card_id: str, text: str) -> bool:
        """Thêm bình luận (Comment) lưu lịch sử tranh luận vào Card."""
        if self.mock_mode:
            logger.info(f"Planka Mock Mode [ADD_COMMENT]: cardId={card_id}")
            logger.info(f"Comment Text:\n{text}")
            return True

        token = await self.get_token()
        url = f"{self.base_url}/api/cards/{card_id}/comments"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        payload = {
            "text": text
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                logger.info(f"Đã đăng bình luận tranh biện cho Card {card_id}")
                return True
            except Exception as e:
                logger.error(f"Lỗi thêm bình luận cho Card trên Planka: {e}")
                return False

    async def push_action_card(self, list_id: str, card: ActionCard) -> Optional[str]:
        """
        Đẩy toàn bộ Action Card kết quả lên Planka gồm: tạo card, gán nhãn rủi ro, 
        và lưu vết tranh biện dưới dạng bình luận.
        """
        try:
            # 1. Tạo Card
            description_lines = [
                "### TÓM TẮT QUYẾT ĐỊNH",
                card.summary,
                "",
                "### ĐÁNH GIÁ RỦI RO",
                f"* **Mức độ:** {card.risk_level}",
                "",
                "### BẰNG CHỨNG TRUY VẾT (TRACEABILITY TAGS)"
            ]
            
            for i, tag in enumerate(card.traceability_tags, 1):
                description_lines.append(f"{i}. {tag.point} `{tag.coordinate}`")
                
            description_lines.extend([
                "",
                "### KIẾN NGHỊ & ĐỀ XUẤT"
            ])
            for rec in card.recommendations:
                description_lines.append(f"- {rec}")
                
            description_text = "\n".join(description_lines)
            
            card_res = await self.create_card(list_id, card.title, description_text)
            card_id = card_res.get("id")
            
            if not card_id:
                return None

            # 2. Gán Nhãn rủi ro (Giả lập nhãn nếu chạy Mock, hoặc lấy nhãn tương ứng)
            # Trong thực tế, label_id sẽ được tra cứu hoặc lấy từ biến môi trường
            label_map = {
                "HIGH": "label-red-risk-uuid",
                "MEDIUM": "label-yellow-risk-uuid",
                "LOW": "label-green-risk-uuid",
                "INFO": "label-gray-risk-uuid"
            }
            label_id = label_map.get(card.risk_level, "label-gray-risk-uuid")
            await self.add_label_to_card(card_id, label_id)

            # 3. Đẩy bình luận lịch sử tranh biện chéo
            if card.audit_trail:
                await self.add_comment_to_card(card_id, f"#### Lịch sử Tranh biện Chéo (Audit Trail):\n{card.audit_trail}")

            return card_id
        except Exception as e:
            logger.error(f"Không thể đẩy Action Card lên Planka: {e}")
            return None
