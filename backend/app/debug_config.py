import requests
import os
from app.config import settings

def debug_config():
    print(f"DEBUG_GLOBAL_PASSWORD: {settings.GLOBAL_PASSWORD}")
    print(f"ENV_GLOBAL_PASSWORD: {os.environ.get('GLOBAL_PASSWORD')}")

if __name__ == "__main__":
    debug_config()
