"""
config.py - Carga de configuración desde .env y keywords.txt
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# LinkedIn
LINKEDIN_USER = os.getenv("LINKEDIN_USER", "")
LINKEDIN_PASS = os.getenv("LINKEDIN_PASS", "")

# Archivos de proyecto
BASE_DIR = Path(__file__).parent
KEYWORDS_FILE = BASE_DIR / "keywords.txt"
SEEN_POSTS_FILE = BASE_DIR / "seen_posts.txt"

# Scraper settings
MIN_KEYWORDS_MATCH = 1


def load_keywords() -> list[str]:
    if not KEYWORDS_FILE.exists():
        print("[ERROR] No se encontró keywords.txt")
        return []
    with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
        return [line.strip().lower() for line in f if line.strip()]


def load_seen_posts() -> set[str]:
    if not SEEN_POSTS_FILE.exists():
        return set()
    with open(SEEN_POSTS_FILE, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def save_seen_post(url: str):
    with open(SEEN_POSTS_FILE, "a", encoding="utf-8") as f:
        f.write(url + "\n")


def validate_config() -> bool:
    errors = []
    if not LINKEDIN_USER:
        errors.append("LINKEDIN_USER no configurado en .env")
    if not LINKEDIN_PASS:
        errors.append("LINKEDIN_PASS no configurado en .env")
    if errors:
        print("\n[ERROR] Configuración incompleta:")
        for e in errors:
            print(f"  - {e}")
        return False
    return True