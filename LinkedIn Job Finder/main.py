#!/usr/bin/env python3
"""
main.py - LinkedIn Job Finder
Escanea el feed de LinkedIn, detecta publicaciones de empleo
y las abre en pestañas nuevas para que las revises.

Uso:
    python main.py
"""

from datetime import datetime

from config import (
    load_keywords,
    load_seen_posts,
    save_seen_post,
    validate_config,
    MIN_KEYWORDS_MATCH,
)
from scraper import scrape_and_open


def print_banner():
    print("""
╔══════════════════════════════════════════════════╗
║         LinkedIn Job Finder v2.0                 ║
║         by Adriel Fabricio López                 ║
╚══════════════════════════════════════════════════╝
    """)


def main():
    print_banner()

    # 1. Validar configuración
    print("[1/3] Validando configuración...")
    if not validate_config():
        return
    print("[OK] Configuración válida.\n")

    # 2. Cargar keywords y posts ya vistos
    print("[2/3] Cargando keywords y registro de posts...")
    keywords = load_keywords()
    seen_posts = load_seen_posts()
    print(f"  Keywords cargadas: {len(keywords)}")
    print(f"  Posts ya vistos: {len(seen_posts)}\n")

    # 3. Pedir tiempo de scroll
    while True:
        try:
            seg = input("[3/4] ¿Cuántos segundos querés scrollear el feed? (ej: 30, 60, 120): ").strip()
            scroll_duration = int(seg)
            if scroll_duration < 5:
                print("  Mínimo 5 segundos.")
                continue
            break
        except ValueError:
            print("  Ingresá un número válido.")

    # 4. Scraping + abrir pestañas
    print(f"\n[4/4] Iniciando scraping de LinkedIn ({scroll_duration}s de scroll)...")
    print("  (Esto abre Chrome. No lo cierres hasta que termine.)\n")
    opened_urls = scrape_and_open(keywords, MIN_KEYWORDS_MATCH, seen_posts, scroll_duration)

    # Guardar posts abiertos para no repetir
    for url in opened_urls:
        save_seen_post(url)

    # Resumen
    print(f"\n  RESUMEN - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Publicaciones relevantes encontradas: {len(opened_urls)}")
    if opened_urls:
        print(f"\n  URLs abiertas:")
        for i, url in enumerate(opened_urls, 1):
            print(f"    {i}. {url}")
    print()


if __name__ == "__main__":
    main()