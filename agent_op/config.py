import os
from pathlib import Path
from dotenv import load_dotenv

# Load environmental variables from .env file
load_dotenv()

class Config:
    # API Keys
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

    # Planka (FNX-OP) Integration Config
    PLANKA_API_URL = os.getenv("PLANKA_API_URL", "https://operation.fnx.vn")
    PLANKA_EMAIL = os.getenv("PLANKA_EMAIL", "bot-agent@fnx.vn")
    PLANKA_PASSWORD = os.getenv("PLANKA_PASSWORD", "securepassword")
    PLANKA_MOCK_MODE = os.getenv("PLANKA_MOCK_MODE", "True").lower() == "true"
    
    # Webhook security
    WEBHOOK_SECRET_TOKEN = os.getenv("WEBHOOK_SECRET_TOKEN", "fnx-op-secret-token-2026")

    # LLM Models mapping (Gemini Strategy)
    MODEL_NAVIGATOR = os.getenv("MODEL_NAVIGATOR", None)
    MODEL_SCANNER = os.getenv("MODEL_SCANNER", None)
    MODEL_BUILDER = os.getenv("MODEL_BUILDER", None)
    MODEL_CHALLENGER = os.getenv("MODEL_CHALLENGER", None)
    MODEL_JUDGE = os.getenv("MODEL_JUDGE", None)

    # Concurrency and logic caps (Poka-Yoke)
    MAX_CONCURRENT_LLM_TASKS = int(os.getenv("MAX_CONCURRENT_LLM_TASKS", "5"))
    MAX_CLARIFICATION_TURNS = int(os.getenv("MAX_CLARIFICATION_TURNS", "3"))
    MAX_DEBATE_TURNS = int(os.getenv("MAX_DEBATE_TURNS", "3"))

    # Workspace directories
    BASE_DIR = Path(__file__).resolve().parent.parent
    PLAYBOOKS_DIR = BASE_DIR / "playbooks"
    SCRATCH_DIR = BASE_DIR / "scratch"

    @classmethod
    def init_dirs(cls):
        """Ensure directories exist."""
        cls.PLAYBOOKS_DIR.mkdir(parents=True, exist_ok=True)
        cls.SCRATCH_DIR.mkdir(parents=True, exist_ok=True)

# Initialize paths on import
Config.init_dirs()
