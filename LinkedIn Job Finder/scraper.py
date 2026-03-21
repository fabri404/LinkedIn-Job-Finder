"""
scraper.py - Scraping de LinkedIn feed con Selenium.
Busca posts relevantes por keywords y los abre en pestañas nuevas.
"""

import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from config import LINKEDIN_USER, LINKEDIN_PASS


def create_driver() -> webdriver.Chrome:
    """Crea el driver de Chrome con opciones optimizadas para Linux."""
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    service = Service()
    driver = webdriver.Chrome(service=service, options=options)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


def login(driver: webdriver.Chrome) -> bool:
    """Inicia sesión en LinkedIn."""
    print("[*] Iniciando sesión en LinkedIn...")
    driver.get("https://www.linkedin.com/login")
    time.sleep(3)

    try:
        user_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "username"))
        )
        user_input.clear()
        user_input.send_keys(LINKEDIN_USER)

        pass_input = driver.find_element(By.ID, "password")
        pass_input.clear()
        pass_input.send_keys(LINKEDIN_PASS)

        submit_btn = driver.find_element(By.XPATH, '//button[@type="submit"]')
        submit_btn.click()
        time.sleep(5)

        if "checkpoint" in driver.current_url or "challenge" in driver.current_url:
            print("[!] LinkedIn pide verificación de seguridad.")
            print("    Completá el captcha/verificación en el navegador.")
            input("    Presioná ENTER cuando hayas terminado...")

        if "feed" in driver.current_url:
            print("[OK] Login exitoso.")
            return True
        else:
            print(f"[WARN] URL actual: {driver.current_url}")
            input("       Presioná ENTER si ya completaste la verificación...")
            return True

    except Exception as e:
        print(f"[ERROR] Falló el login: {e}")
        return False


def scroll_feed(driver: webdriver.Chrome, duration: int):
    """Hace scroll en el feed durante X segundos para cargar posts."""
    print(f"[*] Scrolleando feed por {duration} segundos...")
    end_time = time.time() + duration
    last_height = driver.execute_script("return document.body.scrollHeight")

    while time.time() < end_time:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            time.sleep(1)
        last_height = new_height

    print("[OK] Scroll completado.")


def collect_posts_via_js(driver: webdriver.Chrome) -> list[dict]:
    """
    Recolecta posts del feed usando JavaScript para máxima compatibilidad.
    LinkedIn cambia los selectores seguido, así que usamos múltiples estrategias.
    Retorna lista de dicts: {url, text}
    """
    print("[*] Recolectando posts del feed...")

    # Estrategia: JavaScript que recorre el DOM buscando posts con su texto y link
    posts_data = driver.execute_script("""
        const results = [];
        const seen = new Set();

        // Buscar todos los contenedores de posts posibles
        const selectors = [
            'div.feed-shared-update-v2',
            'div[data-urn*="activity"]',
            'div[data-id]',
            'article',
        ];

        let containers = [];
        for (const sel of selectors) {
            const found = document.querySelectorAll(sel);
            if (found.length > 0) {
                containers = found;
                break;
            }
        }

        // Si no encontramos containers específicos, buscar por estructura
        if (containers.length === 0) {
            containers = document.querySelectorAll('[class*="feed"] [class*="update"]');
        }

        containers.forEach(container => {
            // Obtener TODO el texto del container
            const text = container.innerText || '';
            if (text.length < 30) return;

            // Deduplicar por primeros 100 chars
            const key = text.substring(0, 100);
            if (seen.has(key)) return;
            seen.add(key);

            // Buscar URL del post
            let url = '';
            const links = container.querySelectorAll('a[href]');
            for (const a of links) {
                const href = a.href || '';
                if (href.includes('/feed/update/') || href.includes('/posts/')) {
                    url = href.split('?')[0];
                    break;
                }
            }

            // Si no hay link directo, buscar data-urn para construir URL
            if (!url) {
                const urn = container.getAttribute('data-urn') || 
                            container.getAttribute('data-id') || '';
                if (urn.includes('activity')) {
                    const activityId = urn.split(':').pop();
                    if (activityId) {
                        url = 'https://www.linkedin.com/feed/update/urn:li:activity:' + activityId;
                    }
                }
            }

            if (url) {
                results.push({url: url, text: text});
            }
        });

        return results;
    """)

    posts = posts_data if posts_data else []
    print(f"[OK] {len(posts)} posts recolectados.")

    # Debug: mostrar preview de los primeros 3 posts
    for i, p in enumerate(posts[:3]):
        preview = p["text"][:80].replace("\n", " ")
        print(f"  [preview {i+1}] {preview}...")

    return posts


def is_relevant(text: str, keywords: list[str], min_matches: int) -> bool:
    """Verifica si el texto del post contiene suficientes keywords."""
    text_lower = text.lower()
    matches = sum(1 for kw in keywords if kw in text_lower)
    return matches >= min_matches


def open_in_new_tab(driver: webdriver.Chrome, url: str):
    """Abre una URL en una nueva pestaña sin cerrar las anteriores."""
    driver.execute_script(f"window.open('{url}', '_blank');")
    time.sleep(0.5)


def analyze_if_job_posting(text: str) -> dict:
    """
    Analiza el contenido de un post para determinar si es una búsqueda laboral real
    o un post informativo/motivacional sobre empleo.

    Usa un sistema de puntuación con indicadores positivos (búsqueda real)
    e indicadores negativos (post informativo).

    Retorna: {is_job: bool, score: int, reasons: list[str]}
    """
    import re
    text_lower = text.lower()

    score = 0
    reasons = []

    # =====================================================
    # INDICADORES POSITIVOS — Señales de búsqueda real
    # =====================================================

    # Una empresa específica está contratando (peso alto)
    hiring_phrases = [
        "estamos buscando", "estamos en la búsqueda", "nos encontramos en búsqueda",
        "buscamos incorporar", "buscamos sumar", "sumate a", "sumate al equipo",
        "unite a", "unite al equipo", "se busca", "se requiere",
        "incorporar a nuestro equipo", "para nuestro equipo",
        "sumarse a nuestro equipo", "sumarse al equipo",
        "seguimos creciendo", "seguimos sumando",
        "we are looking for", "we're looking for", "we are hiring",
        "looking to hire", "join our team", "join us",
        "estamos buscando talento", "buscando talento",
    ]
    for phrase in hiring_phrases:
        if phrase in text_lower:
            score += 3
            reasons.append(f"+3 frase de contratación: '{phrase}'")
            break

    # Tiene sección de requisitos (peso alto)
    requirement_headers = [
        "requisitos", "requisitos excluyentes", "requisitos deseables",
        "requirements", "what we're looking for", "perfil buscado",
        "perfil ideal", "que buscamos", "qué buscamos", "lo que buscamos",
        "skills required", "must have", "nice to have",
        "conocimientos en", "experiencia en", "experiencia con",
    ]
    for header in requirement_headers:
        if header in text_lower:
            score += 3
            reasons.append(f"+3 sección de requisitos: '{header}'")
            break

    # Pide enviar CV, postularse, o contacto directo (peso alto)
    apply_phrases = [
        "enviá tu cv", "envia tu cv", "enviar cv", "enviar tu cv",
        "enviános tu cv", "envianos tu cv", "envíanos tu cv",
        "postulate", "postularse", "postularte",
        "aplicar a", "apply at", "apply to", "apply now",
        "send your cv", "send your resume", "envía tu currículum",
        "escribinos a", "contactanos a", "contactate a",
        "escríbeme por dm", "escribime por dm", "dejame tu contacto",
        "déjame tu contacto", "contacto en los comentarios",
        "escribime al", "escríbeme al",
        "mandá tu cv", "manda tu cv",
    ]
    for phrase in apply_phrases:
        if phrase in text_lower:
            score += 3
            reasons.append(f"+3 pide postulación: '{phrase}'")
            break

    # Tiene email de contacto (peso medio)
    emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
    real_emails = [e for e in emails if not any(
        d in e.lower() for d in ["linkedin.com", "facebook.com", "google.com", "example.com"]
    )]
    if real_emails:
        score += 2
        reasons.append(f"+2 email de contacto: {real_emails[0]}")

    # Lista múltiples posiciones abiertas (peso alto — patrón de empresas reales)
    position_indicators = [
        "posiciones abiertas", "vacantes disponibles", "búsquedas abiertas",
        "posiciones disponibles", "roles abiertos", "open positions",
        "oportunidades abiertas",
    ]
    for phrase in position_indicators:
        if phrase in text_lower:
            score += 3
            reasons.append(f"+3 lista de posiciones: '{phrase}'")
            break

    # Detectar múltiples títulos de puesto (patrón de multi-búsqueda)
    job_titles = [
        "desarrollador", "developer", "qa", "tester", "líder técnico",
        "tech lead", "analyst", "analista", "engineer", "ingeniero",
        "devops", "fullstack", "full stack", "frontend", "backend",
        "diseñador", "designer", "data", "scrum", "project manager",
        "capacitador", "arquitecto", "dba", "sysadmin", "cloud",
        "ssr", "sr", " jr", "junior", "trainee", "semi senior", "senior",
    ]
    title_matches = sum(1 for t in job_titles if t in text_lower)
    if title_matches >= 3:
        score += 2
        reasons.append(f"+2 múltiples puestos mencionados ({title_matches} títulos)")

    # Menciona convocatoria específica (peso medio)
    convocatoria_phrases = [
        "convocatoria", "búsqueda laboral", "busqueda laboral",
        "oportunidad laboral", "vacante", "puesto",
    ]
    for phrase in convocatoria_phrases:
        if phrase in text_lower:
            score += 2
            reasons.append(f"+2 convocatoria: '{phrase}'")
            break

    # Menciona modalidad de trabajo (peso medio)
    modality_phrases = [
        "modalidad híbrida", "modalidad remota", "modalidad presencial",
        "100% remoto", "remote position", "hybrid",
        "lunes a viernes", "jornada completa", "full time", "part time",
        "medio tiempo", "jornada parcial",
    ]
    if sum(1 for p in modality_phrases if p in text_lower):
        score += 2
        reasons.append("+2 modalidad de trabajo mencionada")

    # Describe responsabilidades o tareas (peso medio)
    task_phrases = [
        "vas a hacer", "qué vas a hacer", "responsabilidades",
        "tareas", "funciones", "tu rol", "your role",
        "what you'll do", "responsibilities", "day to day",
        "principales funciones",
    ]
    for phrase in task_phrases:
        if phrase in text_lower:
            score += 2
            reasons.append(f"+2 describe tareas: '{phrase}'")
            break

    # Menciona beneficios o sueldo (peso bajo)
    benefit_phrases = [
        "beneficios", "ofrecemos", "we offer", "sueldo", "salario",
        "remuneración", "prepaga", "obra social", "capacitación",
        "plan de carrera",
    ]
    for phrase in benefit_phrases:
        if phrase in text_lower:
            score += 1
            reasons.append(f"+1 menciona beneficios: '{phrase}'")
            break

    # =====================================================
    # INDICADORES NEGATIVOS — Señales de post informativo
    # =====================================================

    # Lista de plataformas/sitios (típico de posts informativos)
    platform_names = [
        "remotive", "flexjobs", "upwork", "workana", "remote ok",
        "freelancer.com", "fiverr", "toptal", "indeed", "glassdoor",
        "computrabajo", "zonajobs", "bumeran",
    ]
    platform_count = sum(1 for p in platform_names if p in text_lower)
    if platform_count >= 2:
        score -= 4
        reasons.append(f"-4 lista de plataformas ({platform_count} mencionadas)")

    # Muchos links externos — SOLO penalizar si NO es un listado de vacantes
    # Si el post lista posiciones con links de postulación, no penalizar
    url_count = len(re.findall(r'https?://\S+', text))
    has_position_list = any(p in text_lower for p in position_indicators)
    has_shorturl = "shorturl" in text_lower or "lnkd.in" in text_lower
    if url_count >= 3 and not has_position_list and not has_shorturl:
        score -= 3
        reasons.append(f"-3 muchos links externos ({url_count})")

    # Frases motivacionales / de engagement (típico de posts virales)
    engagement_phrases = [
        "si te resulta útil", "seguime", "hacé clic en seguir",
        "compartilo", "comparte esto", "dale like", "guardá este post",
        "te invito a seguir", "sígueme", "follow me",
        "¿cansado de", "dream team", "el mundo sea tu escritorio",
        "tip:", "tips para", "consejos para",
        "guarda este post", "save this post",
    ]
    engagement_count = sum(1 for p in engagement_phrases if p in text_lower)
    if engagement_count >= 1:
        score -= 2 * engagement_count
        reasons.append(f"-{2 * engagement_count} frases de engagement ({engagement_count})")

    # Pregunta retórica de contenido (no confundir con preguntas de oferta)
    rhetorical = [
        "¿dónde conseguir", "¿cómo conseguir", "¿querés saber",
        "¿sabías que", "¿te gustaría", "¿cansado de",
    ]
    for phrase in rhetorical:
        if phrase in text_lower:
            score -= 2
            reasons.append(f"-2 pregunta retórica: '{phrase}'")
            break

    # Exceso de emojis decorativos de lista (posts de contenido viral)
    list_emojis = ["◾", "◽", "▶️", "🔗", "💡"]
    emoji_count = sum(text.count(e) for e in list_emojis)
    if emoji_count >= 5:
        score -= 2
        reasons.append(f"-2 exceso de emojis decorativos ({emoji_count})")

    # =====================================================
    # DECISIÓN
    # =====================================================
    is_job = score >= 3

    return {
        "is_job": is_job,
        "score": score,
        "reasons": reasons,
    }


def verify_tabs(driver: webdriver.Chrome, opened_urls: list[str]) -> list[str]:
    """
    Recorre cada pestaña abierta y analiza su contenido para determinar
    si es una búsqueda laboral real o un post informativo.
    Cierra las pestañas que no sean búsquedas reales.
    """
    feed_tab = driver.window_handles[0]
    verified_urls = []
    tabs_to_check = driver.window_handles[1:]

    print(f"\n[*] Analizando contenido de {len(tabs_to_check)} pestañas...")
    print(f"    (Determinando si son búsquedas laborales reales)\n")

    for i, tab in enumerate(tabs_to_check, 1):
        try:
            driver.switch_to.window(tab)
            time.sleep(2)

            # Obtener todo el texto de la página
            body_text = driver.execute_script(
                "return document.body ? document.body.innerText : '';"
            ) or ""

            url = opened_urls[i - 1] if i - 1 < len(opened_urls) else "?"

            # Analizar si es búsqueda laboral real
            analysis = analyze_if_job_posting(body_text)

            preview = body_text[:100].replace("\n", " ").strip()

            if analysis["is_job"]:
                print(f"  [BÚSQUEDA REAL] Pestaña {i} (score: {analysis['score']})")
                print(f"    Preview: {preview}...")
                for r in analysis["reasons"]:
                    print(f"      {r}")
                verified_urls.append(url)
            else:
                print(f"  [FALSO POSITIVO] Pestaña {i} (score: {analysis['score']})")
                print(f"    Preview: {preview}...")
                for r in analysis["reasons"]:
                    print(f"      {r}")
                driver.close()

        except Exception as e:
            print(f"  [ERROR] Pestaña {i}: {e}")

    # Volver al feed
    driver.switch_to.window(feed_tab)
    return verified_urls


def scrape_and_open(keywords: list[str], min_matches: int, seen_posts: set[str], scroll_duration: int) -> list[str]:
    """
    Pipeline completo:
    Login → F5 → Scroll → Recolectar con JS → Filtrar por keywords →
    Abrir matches en pestañas → Verificar pestañas → Cerrar falsos positivos.

    Retorna lista de URLs abiertas.
    """
    driver = create_driver()
    opened_urls = []

    try:
        if not login(driver):
            print("[ERROR] No se pudo iniciar sesión. Abortando.")
            return []

        # Refrescar el feed para obtener publicaciones frescas
        print("[*] Refrescando el feed (F5)...")
        driver.get("https://www.linkedin.com/feed/")
        time.sleep(3)
        driver.refresh()
        time.sleep(4)

        # Expandir todos los "ver más" antes de scrollear
        print("[*] Expandiendo posts truncados...")
        driver.execute_script("""
            document.querySelectorAll('button').forEach(btn => {
                const text = (btn.innerText || '').toLowerCase();
                if (text.includes('ver más') || text.includes('see more') || text.includes('…más')) {
                    try { btn.click(); } catch(e) {}
                }
            });
        """)
        time.sleep(1)

        # Scroll por el tiempo indicado
        scroll_feed(driver, scroll_duration)

        # Expandir de nuevo después del scroll (nuevos posts cargados)
        driver.execute_script("""
            document.querySelectorAll('button').forEach(btn => {
                const text = (btn.innerText || '').toLowerCase();
                if (text.includes('ver más') || text.includes('see more') || text.includes('…más')) {
                    try { btn.click(); } catch(e) {}
                }
            });
        """)
        time.sleep(1)

        # Recolectar posts via JavaScript
        posts = collect_posts_via_js(driver)

        # Filtrar ya vistos
        new_posts = [p for p in posts if p["url"] not in seen_posts]
        seen_posts.update(p["url"] for p in new_posts)
        print(f"[*] {len(new_posts)} posts nuevos para analizar.")

        # Analizar relevancia y abrir en pestañas
        print(f"\n{'='*50}")
        print(f"  ANALIZANDO {len(new_posts)} POSTS")
        print(f"  Keywords: {', '.join(keywords)}")
        print(f"  Match mínimo: {min_matches} keyword(s)")
        print(f"{'='*50}")

        matches = 0
        for post in new_posts:
            text = post["text"]

            if is_relevant(text, keywords, min_matches):
                matches += 1
                preview = text[:120].replace("\n", " ")
                print(f"\n  [MATCH #{matches}] {preview}...")
                open_in_new_tab(driver, post["url"])
                opened_urls.append(post["url"])

        print(f"\n{'='*50}")
        print(f"  PRIMER FILTRO: {matches} publicaciones con keyword")
        print(f"  (de {len(new_posts)} posts analizados)")
        print(f"{'='*50}")

        # Segundo filtro: verificar que sean búsquedas laborales reales
        if matches > 0:
            verified_urls = verify_tabs(driver, opened_urls)
            opened_urls = verified_urls

            remaining = len(driver.window_handles) - 1  # -1 por el feed
            print(f"\n{'='*50}")
            print(f"  RESULTADO FINAL: {remaining} búsquedas laborales verificadas")
            print(f"  (se cerraron {matches - remaining} falsos positivos)")
            print(f"{'='*50}")

            if remaining > 0:
                print(f"\n  Quedan {remaining} pestañas con búsquedas reales.")
                print("  Revisalas tranquilo en el navegador.")
                input("\n  Presioná ENTER cuando hayas terminado de revisar...")
            else:
                print("\n  Todas las pestañas resultaron ser falsos positivos.")
                input("\n  Presioná ENTER para cerrar...")
        else:
            print("\n  No se encontraron publicaciones relevantes esta vez.")
            print("  Tip: revisá keywords.txt y asegurate que MIN_KEYWORDS_MATCH=1 en config.py")
            input("\n  Presioná ENTER para cerrar...")

    except KeyboardInterrupt:
        print("\n[!] Interrumpido por el usuario.")

    except Exception as e:
        print(f"\n[ERROR] Error durante el scraping: {e}")

    finally:
        driver.quit()
        print("[*] Navegador cerrado.")

    return opened_urls