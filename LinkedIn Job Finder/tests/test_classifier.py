from classifier import check_location, check_seniority, evaluate_post, extract_emails, extract_role_title, extract_subject_hint, score_job_posting

KEYWORDS = ["desarrollador", "developer", "python", "qa", "backend", "full stack"]

EMBITALENT = (
    "Mariana Franco Recruiter 6 días Seguir ¡Buscamos Desarrollador/a Junior Python, "
    "Django y n8n! Buscamos experiencia práctica reciente con n8n, conocimientos de Python "
    "y Django 100 % remoto | Lunes a viernes Contrato según país de residencia. "
    "O envía tu CV a reclutamiento@embitalent.com #Vacante #Python"
)
BEYSERIN = (
    "¡Buscamos Analista Junior de IA / AI Trainee en Beyserin Consulting! Modalidad: "
    "Remoto (México) Requisitos clave: Programación (Python, Java) envía tu CV a "
    "ecampero@beyserinconsulting.com"
)
CUMPLO = (
    "¡Estamos buscando Desarrollador/a Full Stack! Asunción Centro | Presencial. "
    "Requisitos: Python, Node.js, React. Enviá tu CV a recursoshumanos.cumplo@gmail.com"
)
SENIOR = (
    "Estamos buscando un Backend Developer Senior. Requisitos: 6 años de experiencia "
    "en Python. 100% remoto Argentina. Enviá tu CV a talent@empresa.com"
)
JOB_SEEKER = (
    "¡Hola! Me encuentro en búsqueda de nuevas oportunidades laborales como "
    "desarrollador Python. Requisitos que cumplo... escribime a persona@gmail.com"
)
ADN = (
    "Buscamos talento para un importante cliente. Tenemos más de 720 búsquedas activas "
    "en IT | Comercial. Desarrollador backend y QA. Enviános tu CV a cv@adnrh.com.ar "
    "Por favor, no olvides indicar en el ASUNTO del mail la búsqueda que te interesó."
)


def test_evaluate_post_remote_python_with_email_is_accepted():
    verdict, posting = evaluate_post(EMBITALENT, KEYWORDS)
    assert verdict.accepted
    assert posting.emails == ("reclutamiento@embitalent.com",)
    assert posting.language == "es"
    assert posting.track == "backend"


def test_evaluate_post_remote_only_mexico_is_rejected():
    verdict, _ = evaluate_post(BEYSERIN, KEYWORDS)
    assert not verdict.accepted
    assert "ubicación" in verdict.reason


def test_evaluate_post_onsite_paraguay_is_rejected():
    verdict, _ = evaluate_post(CUMPLO, KEYWORDS)
    assert not verdict.accepted


def test_evaluate_post_senior_six_years_is_rejected():
    verdict, _ = evaluate_post(SENIOR, KEYWORDS)
    assert not verdict.accepted


def test_evaluate_post_job_seeker_is_rejected():
    verdict, _ = evaluate_post(JOB_SEEKER, KEYWORDS)
    assert not verdict.accepted


def test_evaluate_post_generic_subject_request_uses_role():
    verdict, posting = evaluate_post(ADN, KEYWORDS)
    assert verdict.accepted
    assert posting.subject_hint is None
    assert posting.asks_role_in_subject


def test_extract_subject_hint_quoted_subject_is_exact():
    hint, asks = extract_subject_hint('Enviá tu CV con el asunto "DEV-PY-2026" a rrhh@x.com')
    assert hint == "DEV-PY-2026"
    assert asks


def test_extract_emails_skips_own_and_blacklisted():
    text = "a@linkedin.com fabri404lopez@gmail.com rrhh@empresa.com.ar."
    assert extract_emails(text) == ("rrhh@empresa.com.ar",)


LOGISTICS = (
    "Recruiter IT | Talento 2 días Estamos buscando Coordinador/a de Transporte – Logística "
    "Terrestre. Requisitos: experiencia en logística. Presencial en Córdoba. "
    "Enviá tu CV a busquedasrrhh@brilog.com.ar"
)
LAWYER = (
    "Buscamos 🔴 Si eres Abogado/a, recién graduado/a o cuentas con hasta un año de "
    "experiencia. Requisitos: título de abogado. Remoto. Enviá tu CV a mercadeo@estudio.com"
)
HASHTAG_DEV = (
    "hashtag#hiring Buscamos Desarrollador/a Python para proyecto remoto en Argentina. "
    "Requisitos: Python y SQL. Enviá tu CV a rrhh@devs.com.ar"
)


def test_evaluate_post_logistics_role_from_it_recruiter_is_rejected():
    verdict, _ = evaluate_post(LOGISTICS, ["junior", "python", "desarrollador"])
    assert not verdict.accepted


def test_evaluate_post_lawyer_role_is_rejected():
    verdict, _ = evaluate_post(LAWYER, ["junior", "trainee"])
    assert not verdict.accepted


def test_evaluate_post_dev_role_after_hashtag_is_accepted():
    verdict, posting = evaluate_post(HASHTAG_DEV, KEYWORDS)
    assert verdict.accepted
    assert posting.track == "backend"


def test_check_seniority_english_year_range_is_rejected():
    from classifier import check_seniority
    assert not check_seniority("Data Migration Engineer | 8–12 Years | Remote").accepted
    assert not check_seniority("Backend developer with 5+ years of Python").accepted


def test_check_seniority_low_range_is_accepted():
    from classifier import check_seniority
    assert check_seniority("Buscamos dev con 2-4 años de experiencia").accepted


def test_detect_track_uses_requested_subject():
    from classifier import detect_track
    assert detect_track("texto", "talento para el equipo", "ANALISTA QA") == "qa"


def test_check_seniority_with_age_range_ignores_it():
    # Act
    verdict = check_seniority("Requerimientos: 1 año de experiencia. Edad: entre 20 y 45 años")

    # Assert
    assert verdict.accepted


def test_evaluate_post_logistics_supervisor_is_rejected():
    # Arrange
    text = (
        "Buscamos SUPERVISOR DE DESPACHO / Morón. Requisitos: experiencia en logística, "
        "manejo de sistemas, Excel y nociones de Python. Presencial. Enviá tu CV a cv@empresa.com.ar"
    )

    # Act
    verdict, posting = evaluate_post(text, KEYWORDS + ["sistemas"])

    # Assert
    assert not verdict.accepted
    assert posting is None


def test_check_location_with_clima_laboral_is_not_lima():
    assert check_location("Ofrecemos buen clima laboral. Presencial en Córdoba.").accepted


def test_check_location_with_india_only_is_rejected():
    verdict = check_location("Backend Python Developer, 3 years, onsite in Pune, India.")

    assert not verdict.accepted


def test_evaluate_post_risk_prevention_specialist_is_rejected():
    # Arrange
    text = (
        "🚀 ¡Nueva oportunidad | Risk Prevention Specialist! - AMBA ¿Te apasiona el análisis de datos? "
        "Requisitos: SQL y Python, 2 años de experiencia. Híbrido. Enviá tu CV a cv@consultora.com.ar"
    )

    # Act
    verdict, _ = evaluate_post(text, KEYWORDS)

    # Assert
    assert not verdict.accepted


def test_check_location_latam_list_without_argentina_is_rejected():
    text = "Vaga LATAM para candidatos residentes no #Brasil #Chile #Mexico #Peru. Fullstack Python. Remoto."

    assert not check_location(text).accepted


def test_check_location_latam_list_with_argentina_is_accepted():
    text = "Remoto LATAM: residentes en Argentina, Chile o Uruguay. Backend Python."

    assert check_location(text).accepted


def test_evaluate_post_months_old_is_rejected():
    # Arrange
    text = (
        "Número de publicación en el feed 38 Maria • Recruiter 5 meses • Estoy buscando un Backend "
        "Developer Python. Requisitos: 2 años. Remoto Argentina. Enviá tu CV a cv@acme.com.ar"
    )

    # Act
    verdict, _ = evaluate_post(text, KEYWORDS)

    # Assert
    assert verdict.reason == "publicado hace 5 meses"


def test_evaluate_post_days_old_is_not_rejected_by_age():
    text = (
        "Maria • Recruiter 2 días • Estamos buscando Desarrollador Python. Requisitos: 2 años. "
        "Remoto Argentina. Enviá tu CV a cv@acme.com.ar"
    )

    assert evaluate_post(text, KEYWORDS)[0].accepted


def test_evaluate_post_years_old_header_with_seguir_is_rejected():
    text = ("Paula • Tech Recruiter 2 años Seguir Hola comunidad, buscamos Desarrollador Python. "
            "Requisitos: 1 año. Remoto Argentina. Enviá tu CV a cv@acme.com.ar")

    assert evaluate_post(text, KEYWORDS)[0].reason == "publicado hace 2 años Seguir"


def test_evaluate_post_group_post_months_old_with_unirse_is_rejected():
    text = ("Entre QAs Victoria • 3er+ 4 meses Unirse Buscamos Desarrollador Python. "
            "Requisitos: 1 año. Remoto Argentina. Enviá tu CV a cv@acme.com.ar")

    assert evaluate_post(text, KEYWORDS)[0].reason == "publicado hace 4 meses Unirse"


def test_extract_role_title_uses_dev_line_when_buscamos_is_generic():
    text = ("En Accusys nos encontramos en la búsqueda del siguiente perfil para sumarse:\n"
            "📍 Desarrollador React Native Semi Senior\n📌 Experiencia en Expo.")

    assert extract_role_title(text) == "Desarrollador React Native Semi Senior"


def test_evaluate_post_mexican_recruiter_email_without_argentina_is_rejected():
    text = ("Buscamos desarrollador/a web para un proyecto de CRM. Requisitos: 2 años con APIs y bases de "
            "datos. Remoto. Enviá tu CV a contacto@ideaccion.com.mx")

    assert evaluate_post(text, KEYWORDS)[0].reason == "email de otro país (contacto@ideaccion.com.mx)"


def test_evaluate_post_business_developer_is_rejected():
    text = ("En Herreros buscamos Desarrollador Negocios para importante empresa. Requisitos: 3 años "
            "en ventas B2B. Enviá tu CV a cv@hhk.com")

    assert not evaluate_post(text, KEYWORDS)[0].accepted


def test_evaluate_post_guayaquil_onsite_is_rejected():
    text = ("Buscamos Desarrollador/a Back-End .NET. Ubicación: Guayaquil. Modalidad: Presencial. "
            "Requisitos: 2 años. Enviá tu CV a talento@nexti.com")

    assert not evaluate_post(text, KEYWORDS)[0].accepted


def test_extract_emails_skips_accessibility_mailbox():
    assert extract_emails("Need an accommodation? Write to accessibility@proofpoint.com or jobs@acme.com") == (
        "jobs@acme.com",)


def test_evaluate_post_with_unicode_bold_senior_hybrid_caba_is_rejected():
    text = ("𝗡𝘂𝗲𝘃𝗮 𝗯𝘂́𝘀𝗾𝘂𝗲𝗱𝗮 | 𝗝𝗮𝘃𝗮 𝗗𝗲𝘃𝗲𝗹𝗼𝗽𝗲𝗿 𝗦𝗿. Estamos buscando un Java Developer. 📍 𝗖𝗔𝗕𝗔 | "
            "𝗠𝗼𝗱𝗮𝗹𝗶𝗱𝗮𝗱 𝗵𝗶́𝗯𝗿𝗶𝗱𝗮. Requisitos: Java. Enviá tu CV a cv@cfo.com")

    assert not evaluate_post(text, KEYWORDS)[0].accepted


def test_extract_subject_hint_with_quoted_options_takes_first():
    text = 'Enviá tu CV a empleos@kp.com con asunto: • "Desarrollador PHP" o • "Desarrollador Mobile"'

    assert extract_subject_hint(text) == ("Desarrollador PHP", True)


def test_score_job_posting_remote_and_email_without_hiring_signal_is_not_a_job():
    spam = ("Python Developers group • 8 h Benefits of Catapult UAV: remote areas, rapid deployment. "
            "Contact akingswellking@gmail.com")

    assert not score_job_posting(spam).is_job


def test_score_job_posting_en_la_busqueda_de_is_a_hiring_signal():
    post = "Nos encontramos en la búsqueda de un Desarrollador Python. Modalidad remoto. cv@consultora.com"

    assert score_job_posting(post).is_job


def test_check_location_foreign_flag_without_argentina_is_rejected():
    post = "¡BUSCAMOS DESARROLLADOR FULL STACK! 💻🇬🇹 Envía tu CV por WhatsApp: 3266-0665"

    assert not check_location(post).accepted


def test_check_location_english_level_flag_is_ignored():
    post = "Buscamos Desarrollador Python. Inglés intermedio 🇺🇸. Remoto."

    assert check_location(post).accepted


def test_check_location_mexican_state_is_rejected():
    post = "Vacante: Desarrollador Backend .NET. 📍 Santa Catarina, Nuevo León. Modalidad híbrida."

    assert not check_location(post).accepted


def test_score_job_posting_search_for_freelance_recruiters_is_not_a_job():
    post = ("¡En Zenta Group queremos conectar con reclutadores/as IT freelance! Estamos buscando reclutadores "
            "con base de perfiles: Desarrolladores Backend y Full Stack. Requisitos: experiencia. seleccion@zenta.com")

    assert not score_job_posting(post).is_job


def test_extract_emails_skips_courses_and_sales_mailboxes():
    assert extract_emails("cursos@conexion-hr.com ventas@x.com cv@x.com") == ("cv@x.com",)


def test_evaluate_post_indonesian_tester_post_is_rejected():
    text = ("Syahnia • Tech Recruiter 12 h Seguir We're Hiring: Manual QA Tester. Placement: Jakarta Barat (WFO). "
            "Requirements: 2 years in software testing. Send your CV to syahnia@achiera.id")

    verdict, _ = evaluate_post(text, KEYWORDS)

    assert not verdict.accepted


def test_evaluate_post_indian_qa_post_with_city_is_rejected():
    text = ("Komal • HR Executive 1 día Seguir Zorko is Hiring - QA Tester! Experience: 1+ Year. "
            "Location: Vesu, Surat. Full-Time. Send your CV to: hr@zorko.com")

    assert evaluate_post(text, KEYWORDS)[0].reason == "ubicación fuera de Argentina (surat)"


def test_evaluate_post_chilean_full_stack_post_is_rejected():
    text = ("Juan • Analista de Personas 1 h Seguir Nos encontramos en búsqueda de Desarrollador/a Full Stack "
            "(Odoo, Integraciones y BI). (Las Condes). Requisitos: 2 años. Enviar CV a rrhh@democorp.com")

    assert not evaluate_post(text, KEYWORDS)[0].accepted


def test_extract_emails_skips_referrals_mailbox():
    assert extract_emails("referidos@grupokelsoft.com referrals@acme.com rrhh@acme.com") == ("rrhh@acme.com",)
