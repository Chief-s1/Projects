import os, subprocess, sys
from database.database import init_db
from config import settings

if __name__=="__main__":
    init_db()
    backend=subprocess.Popen([sys.executable,"-m","uvicorn","backend.api:app","--host",settings.host,"--port",str(settings.websocket_port)])
    try:
        raise SystemExit(os.system(f'"{sys.executable}" -m streamlit run app.py --server.address {settings.host} --server.port {settings.port}'))
    finally:
        backend.terminate()
        try: backend.wait(timeout=5)
        except subprocess.TimeoutExpired: backend.kill()
