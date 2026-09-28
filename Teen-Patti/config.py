from dataclasses import dataclass
import os
from dotenv import load_dotenv
load_dotenv()

@dataclass(frozen=True)
class Settings:
    host: str = os.getenv('HOST', '0.0.0.0')
    port: int = int(os.getenv('PORT', '8501'))
    websocket_port: int = int(os.getenv('WEBSOCKET_PORT', '8000'))
    database_url: str = os.getenv('DATABASE_URL', 'sqlite:///./teen_patti.db')
    secret_key: str = os.getenv('SECRET_KEY', 'change-me-in-production')
    max_players: int = int(os.getenv('MAX_PLAYERS', '15'))
    turn_seconds: int = int(os.getenv('TURN_SECONDS', '30'))
    disconnect_grace_seconds: int = int(os.getenv('DISCONNECT_GRACE_SECONDS', '60'))
    log_level: str = os.getenv('LOG_LEVEL', 'INFO')
    join_code_length: int = 4

settings = Settings()
