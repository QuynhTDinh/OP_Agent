import logging
from typing import Dict, Any, Optional
from motor.motor_asyncio import AsyncIOMotorClient
from agent_op.config import Config

logger = logging.getLogger("agent_op.database")

# Client will be initialized lazily to avoid connection failures on startup
_mongo_client: Optional[AsyncIOMotorClient] = None

def get_db():
    global _mongo_client
    if _mongo_client is None:
        logger.info(f"Connecting to MongoDB at {Config.MONGO_URI}...")
        # Configure timeout to 3 seconds to fail fast if DB is down
        _mongo_client = AsyncIOMotorClient(Config.MONGO_URI, serverSelectionTimeoutMS=3000)
    return _mongo_client[Config.MONGO_DB_NAME]

async def check_db_health() -> bool:
    """Kiểm tra kết nối tới MongoDB."""
    try:
        db = get_db()
        # The ping command is cheap and checks if the server is responsive
        await db.command("ping")
        logger.info("Connected to MongoDB successfully!")
        return True
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        return False

async def save_audit_report(session_id: str, report_data: Dict[str, Any]):
    """Lưu hoặc cập nhật báo cáo thẩm định cho session."""
    try:
        db = get_db()
        collection = db["audit_reports"]
        await collection.update_one(
            {"session_id": session_id},
            {"$set": {
                "session_id": session_id,
                "result": report_data.get("result"),
                "timestamp": report_data.get("timestamp")
            }},
            upsert=True
        )
        logger.info(f"Audit report saved to MongoDB for session: {session_id}")
    except Exception as e:
        logger.error(f"Error saving audit report to MongoDB: {e}")

async def get_audit_report(session_id: str) -> Optional[Dict[str, Any]]:
    """Lấy báo cáo thẩm định của session."""
    try:
        db = get_db()
        collection = db["audit_reports"]
        doc = await collection.find_one({"session_id": session_id})
        return doc
    except Exception as e:
        logger.error(f"Error getting audit report from MongoDB: {e}")
        return None

async def clear_audit_report(session_id: str):
    """Xóa báo cáo thẩm định của session (sau khi đã đọc)."""
    try:
        db = get_db()
        collection = db["audit_reports"]
        await collection.delete_one({"session_id": session_id})
        logger.info(f"Audit report cleared from MongoDB for session: {session_id}")
    except Exception as e:
        logger.error(f"Error clearing audit report from MongoDB: {e}")
