# -*- coding: utf-8 -*-
from __future__ import annotations

import html
import json
import math
import sys
import hashlib
import secrets
from datetime import datetime
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import streamlit as st
import streamlit.components.v1 as components

from core import (
    AntennaParams,
    FabricationDefects,
    WAVEGUIDES,
    auto_select_waveguide,
    calculate_all,
    defect_effect_table,
    fmt,
    generate_recommendations,
    normalized_design,
    waveguide_names,
)

try:
    from fpdf import FPDF
    PDF_AVAILABLE = True
except Exception:
    FPDF = None
    PDF_AVAILABLE = False

APP_TITLE = "Antenne cornet HPEM - bande S"
st.set_page_config(page_title=APP_TITLE, page_icon=":satellite_antenna:", layout="wide")

AUTH_DB_FILE = APP_DIR / "data" / "users_local.json"


# Comptes de demonstration. Pour un deploiement public, utiliser une solution
# d'authentification externe ou streamlit-authenticator avec mots de passe haches.
USER_DATABASE = {
    "admin": {
        "password": "admin123",
        "name": "Administrateur",
        "role": "Admin",
        "theme": "Mode complet",
        "email": "admin@local",
        "avatar": "🛡️",
    },
    "yesmine": {
        "password": "antenne123",
        "name": "Yesmine",
        "role": "Etudiant(e)",
        "theme": "Mode projet",
        "email": "yesmine@local",
        "avatar": "🎓",
    },
    "invite": {
        "password": "invite",
        "name": "Invite",
        "role": "Lecture seule",
        "theme": "Mode demonstration",
        "email": "invite@local",
        "avatar": "👁️",
    },
}


def hash_password(password: str, salt: str | None = None) -> dict:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return {"salt": salt, "password_hash": digest}


def verify_password(user: dict, password: str) -> bool:
    if "password_hash" in user and "salt" in user:
        digest = hashlib.sha256((user["salt"] + password).encode("utf-8")).hexdigest()
        return secrets.compare_digest(digest, user["password_hash"])
    return secrets.compare_digest(str(user.get("password", "")), password)


def load_custom_users() -> dict:
    try:
        if AUTH_DB_FILE.exists():
            return json.loads(AUTH_DB_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {}


def save_custom_users(users: dict) -> None:
    AUTH_DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    AUTH_DB_FILE.write_text(json.dumps(users, indent=2, ensure_ascii=True), encoding="utf-8")


def all_users() -> dict:
    users = {k: dict(v) for k, v in USER_DATABASE.items()}
    users.update(load_custom_users())
    return users


def upsert_user(username: str, password: str, name: str, role: str = "Etudiant(e)", theme: str = "Mode projet", email: str = "", avatar: str = "👤") -> None:
    custom = load_custom_users()
    data = hash_password(password)
    data.update({"name": name, "role": role, "theme": theme, "email": email, "avatar": avatar})
    custom[username] = data
    save_custom_users(custom)


def record_auth_event(event: str, username: str, status: str) -> None:
    if "auth_events" not in st.session_state:
        st.session_state.auth_events = []
    st.session_state.auth_events.append({
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "event": event,
        "username": username,
        "status": status,
    })
    st.session_state.auth_events = st.session_state.auth_events[-25:]


def _format_cell(value) -> str:
    if isinstance(value, float):
        return fmt(value, 3)
    return str(value)


def show_table(rows: list[dict]) -> None:
    if not rows:
        st.write("Aucune donnee a afficher.")
        return
    headers = list(rows[0].keys())
    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in rows:
        lines.append("| " + " | ".join(_format_cell(row.get(h, "")) for h in headers) + " |")
    st.markdown("\n".join(lines))


def init_state() -> None:
    if "params" not in st.session_state:
        st.session_state.params = AntennaParams()
    if "defects" not in st.session_state:
        st.session_state.defects = FabricationDefects()
    if "norm_gain_dbi" not in st.session_state:
        st.session_state.norm_gain_dbi = 15.8
    if "norm_ratio_ab" not in st.session_state:
        st.session_state.norm_ratio_ab = 1.5
    if "norm_eta" not in st.session_state:
        st.session_state.norm_eta = 0.50
    if "guide_hint" not in st.session_state:
        st.session_state.guide_hint = ""
    if "report_meta" not in st.session_state:
        st.session_state.report_meta = {
            "university": "Nom de l'universite",
            "faculty": "Faculte / Institut",
            "department": "Departement / Laboratoire",
            "author": "Nom de l'etudiant(e)",
            "supervisor": "Encadrant",
            "year": "2025",
            "document_title": "Etude, prediction et optimisation d'une antenne cornet HPEM en bande S",
            "subtitle": "Rapport automatique de synthese et de validation",
        }
    if "university_logo_bytes" not in st.session_state:
        st.session_state.university_logo_bytes = None
    if "university_logo_name" not in st.session_state:
        st.session_state.university_logo_name = ""
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if "user" not in st.session_state:
        st.session_state.user = None
    if "login_attempts" not in st.session_state:
        st.session_state.login_attempts = 0
    if "auth_events" not in st.session_state:
        st.session_state.auth_events = []
    if "project_info" not in st.session_state:
        st.session_state.project_info = {
            "project_id": "HPEM-S-001",
            "prototype_name": "Cornet HPEM bande S",
            "operator": "Yesmine",
            "lab": "Laboratoire RF / HPEM",
            "objective": "Prediction, analyse des defauts et optimisation de l'antenne cornet",
        }
    if "session_notes" not in st.session_state:
        st.session_state.session_notes = ""
    if "snapshots" not in st.session_state:
        st.session_state.snapshots = []
    if "prototype_photos" not in st.session_state:
        st.session_state.prototype_photos = {}
    if "inspection_notes" not in st.session_state:
        st.session_state.inspection_notes = {
            "etat_surface": "Surface interne a inspecter visuellement.",
            "transition": "Verifier la continuite guide-cornet.",
            "soudures": "Relever les zones soudees et les irregularites.",
            "ouverture": "Verifier les aretes et l'equerrage de l'ouverture.",
        }


def login_card_html() -> str:
    return """
    <div style='padding:30px;border-radius:24px;background:linear-gradient(135deg,#0f172a,#1d4ed8 55%,#14b8a6);color:white;margin-bottom:18px;box-shadow:0 18px 45px rgba(15,23,42,.22)'>
      <div style='display:flex;align-items:center;justify-content:space-between;gap:18px;flex-wrap:wrap'>
        <div>
          <div style='font-size:34px;font-weight:900;margin-bottom:8px'>Antenne cornet HPEM - Bande S</div>
          <div style='font-size:16px;opacity:.94;max-width:900px'>Plateforme avec identifiants, espace projet, dashboard complet, optimisation, visualisations E/H et rapport automatique.</div>
        </div>
        <div style='background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.25);border-radius:18px;padding:14px 18px;min-width:230px'>
          <div style='font-size:12px;text-transform:uppercase;opacity:.8;letter-spacing:.08em'>Acces securise</div>
          <div style='font-size:24px;font-weight:800'>ID + mot de passe</div>
          <div style='font-size:12px;opacity:.85'>Profils, roles, session et journal</div>
        </div>
      </div>
      <div style='display:flex;gap:12px;margin-top:20px;flex-wrap:wrap'>
        <span style='background:rgba(255,255,255,.14);padding:8px 12px;border-radius:999px'>Authentification locale</span>
        <span style='background:rgba(255,255,255,.14);padding:8px 12px;border-radius:999px'>Creation de compte</span>
        <span style='background:rgba(255,255,255,.14);padding:8px 12px;border-radius:999px'>Changement de mot de passe</span>
        <span style='background:rgba(255,255,255,.14);padding:8px 12px;border-radius:999px'>Badges et alertes</span>
        <span style='background:rgba(255,255,255,.14);padding:8px 12px;border-radius:999px'>Exports PDF / Word</span>
      </div>
    </div>
    """



def show_login_page() -> None:
    components.html(login_card_html(), height=230)
    tab_login, tab_create = st.tabs(["Connexion", "Creer un compte"])

    with tab_login:
        c1, c2 = st.columns([1, 1.35])
        with c1:
            with st.form("login_form", clear_on_submit=False):
                username = st.text_input("Identifiant", value="", placeholder="Entrer votre identifiant")
                password = st.text_input("Mot de passe", type="password", value="", placeholder="Entrer votre mot de passe")
                submitted = st.form_submit_button("Se connecter")
            if submitted:
                username_clean = username.strip().lower()
                user = all_users().get(username_clean)
                if user and verify_password(user, password):
                    st.session_state.authenticated = True
                    st.session_state.user = {"username": username_clean, **user}
                    st.session_state.login_attempts = 0
                    record_auth_event("login", username_clean, "success")
                    st.success("Connexion reussie.")
                    st.rerun()
                else:
                    st.session_state.login_attempts += 1
                    record_auth_event("login", username_clean, "failed")
                    st.error("Identifiant ou mot de passe incorrect.")
        with c2:
            st.markdown("""
            **Acces securise a l'application**
            - connecte-toi avec ton identifiant et ton mot de passe ;
            - les identifiants ne sont pas affiches publiquement ;
            - chaque session peut etre associee a un utilisateur et a un projet ;
            - les rapports et journaux gardent une meilleure tracabilite.
            """)
            st.info("Veuillez utiliser les identifiants fournis par l'administrateur, ou creer un nouveau compte local.")
            if st.session_state.login_attempts >= 3:
                st.warning("Plusieurs tentatives echouees. Verifie l'identifiant et le mot de passe ou cree un compte local.")

    with tab_create:
        st.subheader("Creer un nouveau compte local")
        st.caption("Le compte cree est enregistre localement dans le dossier de l'application. Choisis un identifiant simple, sans espace.")
        c1, c2 = st.columns(2)
        new_username = c1.text_input("Nouvel identifiant", value="", placeholder="exemple : mon_compte")
        new_name = c2.text_input("Nom affiche", value="", placeholder="Nom et prenom")
        new_email = c1.text_input("Email / contact", value="", placeholder="exemple@email.com")
        new_role = c2.selectbox("Role", ["Etudiant(e)", "Admin", "Lecture seule"], index=0)
        new_theme = c1.selectbox("Mode", ["Mode projet", "Mode complet", "Mode demonstration"], index=0)
        new_avatar = c2.selectbox("Avatar", ["👤", "🎓", "📡", "🛠️", "🧪", "🛡️"], index=1)
        pw1 = c1.text_input("Mot de passe", type="password", value="")
        pw2 = c2.text_input("Confirmer le mot de passe", type="password", value="")

        create_clicked = st.button("Creer le compte et me connecter")
        if create_clicked:
            u = new_username.strip().lower()
            allowed = all(ch.isalnum() or ch in "._-" for ch in u)
            if not u or not pw1 or not new_name.strip():
                st.error("Identifiant, nom et mot de passe sont obligatoires.")
            elif not allowed:
                st.error("L'identifiant doit contenir seulement des lettres, chiffres, point, tiret ou underscore.")
            elif u in all_users():
                st.error("Cet identifiant existe deja. Choisis un autre identifiant.")
            elif pw1 != pw2:
                st.error("Les mots de passe ne correspondent pas.")
            elif len(pw1) < 6:
                st.error("Mot de passe trop court : au moins 6 caracteres.")
            else:
                try:
                    upsert_user(u, pw1, new_name.strip(), new_role, new_theme, new_email.strip(), new_avatar)
                    new_user = all_users().get(u, {})
                    st.session_state.authenticated = True
                    st.session_state.user = {"username": u, **new_user}
                    st.session_state.login_attempts = 0
                    record_auth_event("create_user", u, "success")
                    record_auth_event("login", u, "success")
                    st.success(f"Compte cree et connexion reussie : {u}.")
                    st.rerun()
                except Exception as exc:
                    record_auth_event("create_user", u, "failed")
                    st.error("Impossible de creer le compte local.")
                    st.code(str(exc))

def current_user() -> dict:
    return st.session_state.user or {"username": "", "name": "", "role": "", "theme": "", "avatar": "👤", "email": ""}


def user_header_html(results: dict) -> str:
    user = current_user()
    project = st.session_state.project_info
    hp = results["fabricated"]["hpem"]
    return f"""
    <div style='border:1px solid #dbe3ef;border-radius:18px;padding:18px 20px;background:#fbfcff;margin-bottom:12px'>
      <div style='display:flex;justify-content:space-between;gap:18px;flex-wrap:wrap'>
        <div>
          <div style='font-size:13px;color:#64748b'>Utilisateur connecte</div>
          <div style='font-size:22px;font-weight:800;color:#0f172a'>{html.escape(user.get('name',''))} <span style='font-size:13px;color:#2563eb'>({html.escape(user.get('role',''))})</span></div>
          <div style='font-size:13px;color:#64748b'>Mode : {html.escape(user.get('theme',''))}</div>
        </div>
        <div>
          <div style='font-size:13px;color:#64748b'>Projet</div>
          <div style='font-size:20px;font-weight:800;color:#0f172a'>{html.escape(project.get('prototype_name',''))}</div>
          <div style='font-size:13px;color:#64748b'>ID : {html.escape(project.get('project_id',''))} · Operateur : {html.escape(project.get('operator',''))}</div>
        </div>
        <div>
          <div style='font-size:13px;color:#64748b'>Etat rapide</div>
          <div style='font-size:20px;font-weight:800;color:#0f172a'>Score HPEM {hp['score_hpem']:.0f}%</div>
          <div style='font-size:13px;color:#64748b'>Risque : {html.escape(hp['breakdown_risk'])}</div>
        </div>
      </div>
    </div>
    """



def user_badges(results: dict) -> list[str]:
    badges = []
    hp = results["fabricated"]["hpem"]
    fab = results["fabricated"]
    th = results["theoretical"]
    if hp["score_hpem"] >= 85:
        badges.append("🏅 Tenue HPEM forte")
    elif hp["score_hpem"] >= 70:
        badges.append("🟡 Tenue HPEM acceptable")
    else:
        badges.append("🔴 Correction HPEM requise")
    if fab["penalties"]["s11_db"] <= -18:
        badges.append("📶 Bonne adaptation")
    if fab["gain_dbi"] >= th["gain_dbi"] - 1.0:
        badges.append("📈 Gain proche theorique")
    if fab["penalties"]["total_loss_db"] <= 1.0:
        badges.append("🛠️ Fabrication propre")
    return badges


def account_status_html(results: dict) -> str:
    user = current_user()
    badges = user_badges(results)
    badge_html = "".join([f"<span style='display:inline-block;background:#eef6ff;border:1px solid #bfdbfe;color:#1e3a8a;border-radius:999px;padding:7px 10px;margin:4px;font-size:12px'>{html.escape(b)}</span>" for b in badges])
    return f"""
    <div style='border:1px solid #d8dee9;border-radius:18px;padding:16px;background:#fbfcff;margin-bottom:12px'>
      <div style='display:flex;align-items:center;gap:14px;justify-content:space-between;flex-wrap:wrap'>
        <div style='display:flex;align-items:center;gap:12px'>
          <div style='font-size:40px'>{html.escape(user.get('avatar','👤'))}</div>
          <div>
            <div style='font-size:22px;font-weight:800;color:#0f172a'>{html.escape(user.get('name',''))}</div>
            <div style='font-size:13px;color:#64748b'>ID : {html.escape(user.get('username',''))} - Role : {html.escape(user.get('role',''))} - {html.escape(user.get('email',''))}</div>
          </div>
        </div>
        <div>{badge_html}</div>
      </div>
    </div>
    """


def alert_center_html(results: dict) -> str:
    th = results["theoretical"]
    fab = results["fabricated"]
    hp = fab["hpem"]
    alerts = []
    if th["mode_status"] != "TE10 dominant valide":
        alerts.append(("Mode", "Verifier la bande et le guide d'onde."))
    if fab["penalties"]["s11_db"] > -15:
        alerts.append(("Adaptation", "S11 a ameliorer, verifier transition et alignement."))
    if hp["score_hpem"] < 75:
        alerts.append(("HPEM", "Risque HPEM notable, soigner surfaces et aretes."))
    if fab["penalties"]["total_loss_db"] > 1.5:
        alerts.append(("Fabrication", "Les pertes de fabrication sont significatives."))
    if not alerts:
        alerts.append(("OK", "Aucune alerte majeure dans le modele parametrique."))
    cards = "".join([f"<div style='padding:10px;border-radius:12px;background:#fff7ed;border:1px solid #fed7aa;margin-bottom:8px'><b>{html.escape(t)}</b><br><span style='color:#475569;font-size:13px'>{html.escape(m)}</span></div>" for t,m in alerts])
    return f"<div style='border:1px solid #d8dee9;border-radius:16px;padding:14px;background:#fbfcfe'><div style='font-size:17px;font-weight:800;margin-bottom:10px'>Centre d\'alertes</div>{cards}</div>"



def make_session_snapshot(results: dict) -> dict:
    return {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user": current_user().get("username", ""),
        "project": dict(st.session_state.project_info),
        "params": dict(results["params"]),
        "defects": dict(results["defects"]),
        "gain_fabricated_dbi": round(results["fabricated"]["gain_dbi"], 3),
        "s11_fabricated_db": round(results["fabricated"]["penalties"]["s11_db"], 3),
        "score_hpem": round(results["fabricated"]["hpem"]["score_hpem"], 2),
        "notes": st.session_state.session_notes,
    }


def page_project_space(results: dict) -> None:
    st.title("Espace projet")
    st.write("Cette page ajoute une dimension professionnelle : identification, informations projet, notes de session et sauvegarde de configurations.")

    st.subheader("Informations projet")
    p = st.session_state.project_info
    c1, c2 = st.columns(2)
    p["project_id"] = c1.text_input("ID projet", value=p.get("project_id", ""))
    p["prototype_name"] = c2.text_input("Nom du prototype", value=p.get("prototype_name", ""))
    p["operator"] = c1.text_input("Operateur / utilisateur", value=p.get("operator", ""))
    p["lab"] = c2.text_input("Laboratoire", value=p.get("lab", ""))
    p["objective"] = st.text_area("Objectif", value=p.get("objective", ""), height=90)
    st.session_state.project_info = p

    st.subheader("Notes de session")
    st.session_state.session_notes = st.text_area("Observations, remarques de fabrication, hypotheses", value=st.session_state.session_notes, height=140)

    c1, c2 = st.columns(2)
    if c1.button("Sauvegarder un instantane de la configuration"):
        st.session_state.snapshots.append(make_session_snapshot(results))
        st.success("Instantane sauvegarde dans la session.")
    export_data = {
        "current_snapshot": make_session_snapshot(results),
        "snapshots": st.session_state.snapshots,
    }
    c2.download_button("Exporter le journal projet JSON", data=json.dumps(export_data, indent=2, ensure_ascii=True), file_name="journal_projet_antenne_hpem.json", mime="application/json")

    st.subheader("Historique de session")
    if st.session_state.snapshots:
        rows = []
        for i, snap in enumerate(st.session_state.snapshots, start=1):
            rows.append({"N": i, "Date": snap["date"], "Gain dBi": snap["gain_fabricated_dbi"], "S11 dB": snap["s11_fabricated_db"], "Score HPEM": snap["score_hpem"]})
        show_table(rows)
    else:
        st.info("Aucun instantane sauvegarde pour le moment.")



def page_account(results: dict) -> None:
    st.title("Compte utilisateur")
    components.html(account_status_html(results), height=145)
    user = current_user()

    tab_profile, tab_password, tab_activity = st.tabs(["Profil", "Mot de passe", "Activite"])

    with tab_profile:
        st.subheader("Informations du profil")
        c1, c2 = st.columns(2)
        name = c1.text_input("Nom affiche", value=user.get("name", ""))
        email = c2.text_input("Email / contact", value=user.get("email", ""))
        avatar = c1.selectbox("Avatar", ["👤", "🎓", "📡", "🛠️", "🧪", "🛡️"], index=0)
        theme = c2.selectbox("Mode d'utilisation", ["Mode projet", "Mode complet", "Mode demonstration"], index=0)
        if st.button("Mettre a jour le profil"):
            username = user.get("username", "")
            users = all_users()
            base = dict(users.get(username, {}))
            # Preserve old password if the account is not already custom.
            if "password_hash" not in base:
                old_pw = base.get("password", "antenne123")
                base.update(hash_password(old_pw))
                base.pop("password", None)
            base.update({"name": name, "email": email, "avatar": avatar, "theme": theme, "role": base.get("role", user.get("role", "Etudiant(e)"))})
            custom = load_custom_users()
            custom[username] = base
            save_custom_users(custom)
            st.session_state.user = {"username": username, **base}
            record_auth_event("update_profile", username, "success")
            st.success("Profil mis a jour.")
            st.rerun()

        st.subheader("Badges automatiques")
        for badge in user_badges(results):
            st.info(badge)

    with tab_password:
        st.subheader("Changer le mot de passe")
        old_pw = st.text_input("Ancien mot de passe", type="password")
        new_pw1 = st.text_input("Nouveau mot de passe", type="password")
        new_pw2 = st.text_input("Confirmer le nouveau mot de passe", type="password")
        if st.button("Changer le mot de passe"):
            username = user.get("username", "")
            users = all_users()
            current = dict(users.get(username, {}))
            if not verify_password(current, old_pw):
                st.error("Ancien mot de passe incorrect.")
                record_auth_event("change_password", username, "failed")
            elif new_pw1 != new_pw2:
                st.error("Les nouveaux mots de passe ne correspondent pas.")
            elif len(new_pw1) < 6:
                st.error("Mot de passe trop court : minimum 6 caracteres.")
            else:
                new_data = hash_password(new_pw1)
                current.pop("password", None)
                current.update(new_data)
                current.setdefault("name", user.get("name", username))
                current.setdefault("role", user.get("role", "Etudiant(e)"))
                current.setdefault("theme", user.get("theme", "Mode projet"))
                current.setdefault("email", user.get("email", ""))
                current.setdefault("avatar", user.get("avatar", "👤"))
                custom = load_custom_users()
                custom[username] = current
                save_custom_users(custom)
                st.session_state.user = {"username": username, **current}
                record_auth_event("change_password", username, "success")
                st.success("Mot de passe modifie.")

    with tab_activity:
        st.subheader("Journal d'activite")
        if st.session_state.auth_events:
            show_table(st.session_state.auth_events[::-1])
        else:
            st.info("Aucune activite enregistree.")
        st.download_button("Exporter le journal de connexion", data=json.dumps(st.session_state.auth_events, indent=2, ensure_ascii=True), file_name="journal_connexion.json", mime="application/json")



def page_admin_panel(results: dict) -> None:
    st.title("Administration")
    user = current_user()
    if user.get("role") != "Admin":
        st.warning("Cette page est reservee au role Admin dans cette demonstration.")
        return
    st.subheader("Comptes utilisateurs")
    rows = [{"Identifiant": k, "Nom": v.get("name", ""), "Role": v.get("role", ""), "Mode": v.get("theme", ""), "Email": v.get("email", "")} for k, v in all_users().items()]
    show_table(rows)
    st.subheader("Etat technique")
    st.json({
        "streamlit_page": APP_TITLE,
        "project": st.session_state.project_info,
        "snapshots_count": len(st.session_state.snapshots),
        "pdf_available": PDF_AVAILABLE,
        "custom_users_file": str(AUTH_DB_FILE),
        "custom_users_count": len(load_custom_users()),
    })
    st.info("Pour un vrai deploiement, utiliser une authentification serveur avec HTTPS et une base de donnees securisee. Les mots de passe des comptes crees localement sont haches.")

def get_results() -> dict:
    return calculate_all(st.session_state.params, st.session_state.defects)


def comparison_rows(results: dict) -> list[dict]:
    rows = []
    for row in results["comparison"]:
        rows.append(
            {
                "Cas": row["Cas"],
                "Gain dBi": round(row["Gain dBi"], 2),
                "S11 dB": round(row["S11 dB"], 1),
                "Score HPEM %": round(row["Score HPEM %"], 0),
            }
        )
    return rows


def get_report_meta() -> dict:
    default = {
        "university": "Nom de l'universite",
        "faculty": "Faculte / Institut",
        "department": "Departement / Laboratoire",
        "author": "Nom de l'etudiant(e)",
        "supervisor": "Encadrant",
        "year": "2025",
        "document_title": "Etude, prediction et optimisation d'une antenne cornet HPEM en bande S",
        "subtitle": "Rapport automatique de synthese et de validation",
    }
    meta = dict(default)
    if "report_meta" in st.session_state and isinstance(st.session_state.report_meta, dict):
        meta.update(st.session_state.report_meta)
    return meta


def final_summary_rows(results: dict) -> list[dict]:
    th = results["theoretical"]
    fab = results["fabricated"]
    corr = results["corrected"]
    return [
        {"Indicateur": "Gain (dBi)", "Theorique": round(th["gain_dbi"], 2), "Fabrique": round(fab["gain_dbi"], 2), "Corrige": round(corr["gain_dbi"], 2)},
        {"Indicateur": "S11 (dB)", "Theorique": round(th["base_s11_db"], 1), "Fabrique": round(fab["penalties"]["s11_db"], 1), "Corrige": round(corr["penalties"]["s11_db"], 1)},
        {"Indicateur": "Score HPEM (%)", "Theorique": round(results["comparison"][0]["Score HPEM %"], 0), "Fabrique": round(results["comparison"][1]["Score HPEM %"], 0), "Corrige": round(results["comparison"][2]["Score HPEM %"], 0)},
        {"Indicateur": "HPBW H (deg)", "Theorique": round(th["hpbw_h_deg"], 1), "Fabrique": round(th["hpbw_h_deg"] * (1 + fab["penalties"]["total_loss_db"] / 12.0), 1), "Corrige": round(th["hpbw_h_deg"] * (1 + corr["penalties"]["total_loss_db"] / 14.0), 1)},
        {"Indicateur": "HPBW E (deg)", "Theorique": round(th["hpbw_e_deg"], 1), "Fabrique": round(th["hpbw_e_deg"] * (1 + fab["penalties"]["total_loss_db"] / 12.0), 1), "Corrige": round(th["hpbw_e_deg"] * (1 + corr["penalties"]["total_loss_db"] / 14.0), 1)},
    ]


def figure_exports(results: dict) -> list[tuple[str, str]]:
    p = st.session_state.params
    return [
        ("schema_cornet_2d.svg", horn_2d_svg(p)),
        ("schema_cornet_3d.svg", horn_3d_svg(p)),
        ("diagramme_radiation_synthetique.svg", radiation_pattern_svg(results["theoretical"]["hpbw_h_deg"], results["theoretical"]["hpbw_e_deg"], results["theoretical"]["directivity_dbi"])),
        ("diagramme_radiation_db_plan_H.svg", radiation_db_comparison_svg(results, "H")),
        ("diagramme_radiation_db_plan_E.svg", radiation_db_comparison_svg(results, "E")),
        ("lobe_principal_3d.svg", radiation_3d_lobe_svg(results["theoretical"]["hpbw_h_deg"], results["theoretical"]["hpbw_e_deg"], results["theoretical"]["gain_dbi"])),
        ("champ_E_guide.svg", guide_efield_svg(p)),
        ("champ_H_guide.svg", guide_hfield_svg(p)),
        ("champ_EH_cornet.svg", horn_efield_hfield_svg(p, results)),
        ("carte_efield.svg", efield_heatmap_svg(p)),
        ("carte_hfield.svg", hfield_heatmap_svg(p)),
        ("carte_ouverture.svg", aperture_heatmap_svg(p, results)),
        ("carte_cornet_style_cst.svg", cst_like_horn_map_svg(p, results)),
        ("graphe_comparaison.svg", comparison_chart_svg(results)),
    ]


def make_word_figures_zip(results: dict) -> bytes:
    mem = BytesIO()
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as zf:
        figs = figure_exports(results)
        for fname, svg in figs:
            zf.writestr(fname, svg)
        note = [
            "Pack de figures SVG pretes a inserer dans Word.",
            "Conseil: utiliser Insertion > Images dans Word pour importer les SVG.",
            "Les SVG restent nets apres redimensionnement.",
            "",
            "Fichiers inclus :",
        ]
        for fname, _ in figs:
            note.append("- " + fname)
        zf.writestr("README_figures.txt", "\n".join(note))
    return mem.getvalue()


def make_report(results: dict) -> str:
    p = results["params"]
    d = results["defects"]
    th = results["theoretical"]
    fab = results["fabricated"]
    hp = fab["hpem"]
    pen = fab["penalties"]

    lines = []
    lines.append("# Rapport automatique - antenne cornet HPEM bande S")
    lines.append("")
    lines.append("## Resume")
    lines.append(
        "Dans le but de renforcer l'analyse experimentale, un outil web parametrique a ete propose afin d'estimer l'influence des parametres geometriques et des defauts de fabrication sur les performances de l'antenne cornet. Cet outil permet d'etablir un lien direct entre la conception, la fabrication reelle et la validation electromagnetique, notamment dans un contexte HPEM ou les discontinuites de surface peuvent fortement influencer la tenue en puissance."
    )
    lines.append("")
    lines.append("## Parametres d'entree")
    lines.append(f"- Frequence centrale: {fmt(p['f_center_ghz'], 3)} GHz")
    lines.append(f"- Bande: {fmt(p['f_min_ghz'], 3)} - {fmt(p['f_max_ghz'], 3)} GHz")
    lines.append(f"- Type de guide: {p['guide_type']}")
    lines.append(f"- Longueur du cornet: {fmt(p['horn_length_mm'], 1)} mm")
    lines.append(f"- Ouverture: {fmt(p['aperture_width_mm'], 1)} x {fmt(p['aperture_height_mm'], 1)} mm")
    lines.append(f"- Epaisseur aluminium: {fmt(p['aluminum_thickness_mm'], 2)} mm")
    lines.append(f"- Rugosite interne: {fmt(d['roughness_um'], 2)} um")
    lines.append(f"- Tolerance de fabrication: +/- {fmt(d['tolerance_mm'], 2)} mm")
    lines.append(f"- Nombre de soudures: {fmt(d['weld_count'], 0)}")
    lines.append(f"- Desalignement guide-cornet: {fmt(d['alignment_error_mm'], 2)} mm")
    lines.append("")
    lines.append("## Resultats RF")
    lines.append(f"- Longueur d'onde: {fmt(th['wavelength_mm'], 2)} mm")
    lines.append(f"- Frequence de coupure TE10: {fmt(th['fc_te10_ghz'], 3)} GHz")
    lines.append(f"- Premier mode superieur: {fmt(th['upper_mode_ghz'], 3)} GHz")
    lines.append(f"- Etat modal: {th['mode_status']}")
    lines.append(f"- Directivite: {fmt(th['directivity_dbi'], 2)} dBi")
    lines.append(f"- Gain theorique: {fmt(th['gain_dbi'], 2)} dBi")
    lines.append(f"- Gain fabrique estime: {fmt(fab['gain_dbi'], 2)} dBi")
    lines.append(f"- Ouverture efficace: {fmt(th['effective_aperture_m2'], 4)} m2")
    lines.append(f"- HPBW plan H: {fmt(th['hpbw_h_deg'], 1)} deg")
    lines.append(f"- HPBW plan E: {fmt(th['hpbw_e_deg'], 1)} deg")
    lines.append(f"- S11 theorique estime: {fmt(th['base_s11_db'], 1)} dB")
    lines.append(f"- S11 fabrique estime: {fmt(pen['s11_db'], 1)} dB")
    lines.append("")
    lines.append("## Impact des defauts")
    lines.append(f"- Pertes par rugosite: {fmt(pen['roughness_loss_db'], 2)} dB")
    lines.append(f"- Pertes par soudures: {fmt(pen['weld_loss_db'], 2)} dB")
    lines.append(f"- Pertes par erreurs dimensionnelles: {fmt(pen['dimensional_loss_db'], 2)} dB")
    lines.append(f"- Pertes par desalignement: {fmt(pen['alignment_loss_db'], 2)} dB")
    lines.append(f"- Pertes par oxydation: {fmt(pen['oxidation_loss_db'], 2)} dB")
    lines.append(f"- Pertes par mastic: {fmt(pen['mastic_loss_db'], 2)} dB")
    lines.append(f"- Pertes totales: {fmt(pen['total_loss_db'], 2)} dB")
    lines.append(f"- Decalage frequentiel indicatif: {fmt(pen['estimated_frequency_shift_mhz'], 1)} MHz")
    lines.append("")
    lines.append("## Comparaison")
    lines.append("| Cas | Gain | S11 | Score HPEM |")
    lines.append("|---|---:|---:|---:|")
    for row in results["comparison"]:
        lines.append(f"| {row['Cas']} | {fmt(row['Gain dBi'], 2)} dBi | {fmt(row['S11 dB'], 1)} dB | {fmt(row['Score HPEM %'], 0)} % |")
    lines.append("")
    lines.append("## Analyse HPEM")
    lines.append(f"- Facteur de concentration du champ: {fmt(hp['concentration_factor'], 2)}")
    lines.append(f"- Champ crete a la gorge: {fmt(hp['e_peak_throat_kv_per_m'], 0)} kV/m")
    lines.append(f"- Champ crete a l'ouverture: {fmt(hp['e_peak_aperture_kv_per_m'], 0)} kV/m")
    lines.append(f"- Marge simplifiee vis-a-vis du claquage air: {fmt(hp['breakdown_margin_air'], 2)}")
    lines.append(f"- Risque de decharge: {hp['breakdown_risk']}")
    lines.append("- Zones critiques: " + ", ".join(hp["critical_zones"]))
    lines.append("")
    lines.append("## Recommandations automatiques")
    for rec in generate_recommendations(results):
        lines.append(f"- {rec}")
    lines.append("")
    lines.append("## Validation experimentale recommandee")
    lines.append("- Mesurer le S11 sur toute la bande avec un VNA calibre.")
    lines.append("- Mesurer le gain et relever les diagrammes de rayonnement dans les plans H et E.")
    lines.append("- Comparer les etats theorique, fabrique et corrige apres finition.")
    lines.append("")
    lines.append("## Analyse avancee et aide a la decision")
    scores = prototype_scores(results)
    lines.append(f"- Score global du prototype: {fmt(scores['score_global'],0)} % ({score_interpretation(scores['score_global'])})")
    lines.append(f"- Score RF: {fmt(scores['score_rf'],0)} %")
    lines.append(f"- Score HPEM: {fmt(scores['score_hpem'],0)} %")
    lines.append(f"- Score fabrication: {fmt(scores['score_fabrication'],0)} %")
    lines.append(f"- Indice de confiance du modele: {fmt(scores['confidence'],0)} %")
    lines.append("")
    lines.append("### Defauts prioritaires")
    for row in defect_ranking_rows(results)[:4]:
        lines.append(f"- Priorite {row['Priorite']}: {row['Defaut']} - impact {row['Impact']} - action: {row['Action recommandee']}")
    lines.append("")
    lines.append("### Conclusion automatique")
    lines.append(intelligent_conclusion(results))
    lines.append("")
    lines.append("## Remarque de validite")
    lines.append(
        "Ces resultats sont des estimations parametriques. Ils doivent etre completes par une mesure VNA du S11, une mesure de gain ou une simulation EM 3D pour valider le prototype final."
    )
    lines.append("")
    return "\n".join(lines)



def make_academic_pdf_report(results: dict) -> bytes | None:
    if not PDF_AVAILABLE:
        return None

    meta = get_report_meta()
    p = results["params"]
    th = results["theoretical"]
    fab = results["fabricated"]
    corr = results["corrected"]
    hp = fab["hpem"]
    pen = fab["penalties"]
    summary_rows = final_summary_rows(results)

    def clean(value) -> str:
        txt = str(value)
        replacements = {
            "η": "eta", "λ": "lambda", "≈": "~", "–": "-", "—": "-",
            "’": "'", "“": '"', "”": '"', "°": " deg", "²": "2", "³": "3",
        }
        for old, new in replacements.items():
            txt = txt.replace(old, new)
        return txt.encode("latin-1", "replace").decode("latin-1")

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    left_margin = 15
    usable_w = 180
    pdf.set_left_margin(left_margin)
    pdf.set_right_margin(15)

    logo_path = None
    if st.session_state.get("university_logo_bytes"):
        suffix = Path(st.session_state.get("university_logo_name") or "logo.png").suffix or ".png"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(st.session_state["university_logo_bytes"])
        tmp.flush()
        tmp.close()
        logo_path = tmp.name

    def reset_x() -> None:
        try:
            pdf.set_x(left_margin)
        except Exception:
            pass

    def mc(txt: str, h: float = 5.4, align: str = "L", size: int = 10, style: str = "") -> None:
        reset_x()
        pdf.set_font("Helvetica", style, size)
        pdf.multi_cell(usable_w, h, clean(txt), align=align)
        reset_x()

    def heading(title: str, fill=(230, 238, 250)) -> None:
        pdf.ln(2)
        pdf.set_fill_color(*fill)
        pdf.set_text_color(17, 24, 39)
        reset_x()
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(usable_w, 8, clean(title), border=0, ln=1, fill=True)
        reset_x()
        pdf.set_text_color(0, 0, 0)
        pdf.ln(1)

    def paragraph(txt: str) -> None:
        mc(txt, h=5.2, align="J", size=10)
        pdf.ln(0.6)

    def bullet(txt: str) -> None:
        mc("- " + txt, h=5.0, size=10)

    def table(headers: list[str], rows: list[list[str]], widths: list[float], font_size: float = 8.6) -> None:
        total = max(sum(widths), 1)
        widths2 = [w * usable_w / total for w in widths]
        row_h = 7
        reset_x()
        pdf.set_font("Helvetica", "B", font_size)
        pdf.set_fill_color(219, 234, 254)
        for htxt, w in zip(headers, widths2):
            pdf.cell(w, row_h, clean(htxt)[:42], border=1, fill=True)
        pdf.ln(row_h)
        pdf.set_font("Helvetica", "", font_size)
        for row in rows:
            reset_x()
            for val, w in zip(row, widths2):
                txt = clean(val)
                max_chars = max(10, int(w * 1.65))
                if len(txt) > max_chars:
                    txt = txt[: max_chars - 3] + "..."
                pdf.cell(w, row_h, txt, border=1)
            pdf.ln(row_h)
        pdf.ln(2)

    def metric_box(x, y, w, title, value, color):
        pdf.set_draw_color(209, 213, 219)
        pdf.set_fill_color(248, 250, 252)
        pdf.rect(x, y, w, 22, "DF")
        pdf.set_text_color(*color)
        pdf.set_font("Helvetica", "B", 11)
        pdf.text(x + 3, y + 8, clean(value)[:22])
        pdf.set_text_color(71, 85, 105)
        pdf.set_font("Helvetica", "", 8)
        pdf.text(x + 3, y + 16, clean(title)[:26])
        pdf.set_text_color(0, 0, 0)

    def footer() -> None:
        # Use absolute text placement instead of width=0 cells.
        # Consecutive cells at the bottom can trigger an automatic page break in fpdf2,
        # which created blank pages after each real page.
        current_y = pdf.get_y()
        pdf.set_text_color(100, 116, 139)
        pdf.set_font("Helvetica", "I", 8)
        footer_y = 288
        pdf.text(left_margin, footer_y, clean(f"{meta['university']} - {meta['year']}")[:70])
        pdf.text(176, footer_y, clean(f"Page {pdf.page_no()}"))
        pdf.set_text_color(0, 0, 0)
        pdf.set_y(current_y)

    pdf.add_page()
    pdf.set_fill_color(9, 31, 62)
    pdf.rect(0, 0, 210, 297, "F")
    pdf.set_fill_color(255, 255, 255)
    pdf.rect(16, 18, 178, 261, "F")
    pdf.set_fill_color(30, 64, 175)
    pdf.rect(16, 18, 178, 28, "F")
    if logo_path:
        try:
            pdf.image(logo_path, x=24, y=56, w=28)
        except Exception:
            pass
    pdf.set_text_color(255, 255, 255)
    pdf.set_xy(22, 26)
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(166, 7, clean(meta["university"]), 0, 1, "C")
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(166, 7, clean(meta["faculty"]), 0, 1, "C")
    pdf.cell(166, 6, clean(meta["department"]), 0, 1, "C")
    pdf.set_text_color(17, 24, 39)
    pdf.set_xy(24, 96)
    pdf.set_font("Helvetica", "B", 21)
    pdf.multi_cell(162, 11, clean(meta["document_title"]), 0, "C")
    pdf.ln(5)
    pdf.set_font("Helvetica", "", 12)
    pdf.multi_cell(162, 7, clean(meta["subtitle"]), 0, "C")
    pdf.ln(12)
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(70, 8, clean("Realise par :"), 0, 0)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, clean(meta["author"]), 0, 1)
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(70, 8, clean("Encadrement :"), 0, 0)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, clean(meta["supervisor"]), 0, 1)
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(70, 8, clean("Annee universitaire :"), 0, 0)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, clean(meta["year"]), 0, 1)
    pdf.ln(16)
    pdf.set_draw_color(30, 64, 175)
    pdf.line(32, 205, 178, 205)
    pdf.set_y(214)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(162, 6, clean("Application web parametrique de prediction, d'analyse et d'aide a l'optimisation d'une antenne cornet HPEM en bande S. Ce document relie dimensions, defauts de fabrication, performances RF et recommandations d'amelioration."), 0, "C")
    footer()

    pdf.add_page()
    pdf.set_y(18)
    mc("Rapport de synthese", h=8, size=17, style="B")
    pdf.set_draw_color(203, 213, 225)
    pdf.line(15, 28, 195, 28)
    metric_box(15, 36, 42, "Guide", p["guide_type"], (30, 64, 175))
    metric_box(61, 36, 42, "Gain fabrique", f"{fab['gain_dbi']:.2f} dBi", (5, 150, 105))
    metric_box(107, 36, 42, "S11", f"{pen['s11_db']:.1f} dB", (245, 158, 11))
    metric_box(153, 36, 42, "Score HPEM", f"{hp['score_hpem']:.0f} %", (220, 38, 38))
    pdf.set_y(64)
    heading("1. Resume executif")
    paragraph("Ce rapport presente une synthese parametrique des performances d'une antenne cornet HPEM en bande S. Il relie les dimensions geometriques, les defauts de fabrication et les consequences electromagnetiques attendues, en fournissant des recommandations d'optimisation et de validation experimentale.")
    heading("2. Parametres d'entree")
    table(["Parametre", "Valeur"], [
        ["Frequence centrale", f"{p['f_center_ghz']:.3f} GHz"],
        ["Bande de frequence", f"{p['f_min_ghz']:.3f} - {p['f_max_ghz']:.3f} GHz"],
        ["Guide d'onde", p['guide_type']],
        ["Longueur L", f"{p['horn_length_mm']:.1f} mm"],
        ["Ouverture A x B", f"{p['aperture_width_mm']:.1f} x {p['aperture_height_mm']:.1f} mm"],
        ["Epaisseur aluminium", f"{p['aluminum_thickness_mm']:.2f} mm"],
        ["Puissance crete HPEM", f"{p['peak_power_mw']:.2f} MW"],
    ], [72, 105])
    heading("3. Resultats RF")
    table(["Grandeur", "Valeur"], [
        ["Longueur d'onde", f"{th['wavelength_mm']:.2f} mm"],
        ["Frequence de coupure TE10", f"{th['fc_te10_ghz']:.3f} GHz"],
        ["Premier mode superieur", f"{th['upper_mode_ghz']:.3f} GHz"],
        ["Etat modal", th['mode_status']],
        ["Directivite", f"{th['directivity_dbi']:.2f} dBi"],
        ["Gain theorique", f"{th['gain_dbi']:.2f} dBi"],
        ["Gain fabrique", f"{fab['gain_dbi']:.2f} dBi"],
        ["Gain corrige", f"{corr['gain_dbi']:.2f} dBi"],
        ["S11 theorique", f"{th['base_s11_db']:.1f} dB"],
        ["S11 fabrique", f"{pen['s11_db']:.1f} dB"],
    ], [72, 105])
    footer()

    pdf.add_page()
    heading("4. Defauts de fabrication et impact")
    table(["Defaut", "Impact estime"], [
        ["Rugosite", f"{pen['roughness_loss_db']:.2f} dB"],
        ["Soudures", f"{pen['weld_loss_db']:.2f} dB"],
        ["Erreur dimensionnelle", f"{pen['dimensional_loss_db']:.2f} dB"],
        ["Desalignement", f"{pen['alignment_loss_db']:.2f} dB"],
        ["Oxydation", f"{pen['oxidation_loss_db']:.2f} dB"],
        ["Mastic", f"{pen['mastic_loss_db']:.2f} dB"],
        ["Pertes totales", f"{pen['total_loss_db']:.2f} dB"],
    ], [72, 105])
    heading("5. Analyse HPEM")
    bullet(f"Score HPEM estime : {hp['score_hpem']:.0f} %")
    bullet(f"Risque de decharge : {hp['breakdown_risk']}")
    bullet(f"Champ crete a la gorge : {hp['e_peak_throat_kv_per_m']:.0f} kV/m")
    bullet(f"Champ crete a l'ouverture : {hp['e_peak_aperture_kv_per_m']:.0f} kV/m")
    bullet(f"Marge simplifiee vis-a-vis du claquage : {hp['breakdown_margin_air']:.2f}")
    bullet("Zones critiques : " + ", ".join(hp['critical_zones']))
    heading("6. Tableau recapitulatif final")
    table(["Indicateur", "Theorique", "Fabrique", "Corrige"], [[str(r['Indicateur']), str(r['Theorique']), str(r['Fabrique']), str(r['Corrige'])] for r in summary_rows], [58, 40, 40, 40], font_size=8.2)
    footer()

    pdf.add_page()
    heading("7. Analyse avancee")
    sc = prototype_scores(results)
    table(["Indicateur", "Valeur"], [
        ["Score global", f"{sc['score_global']:.0f} %"],
        ["Score RF", f"{sc['score_rf']:.0f} %"],
        ["Score HPEM", f"{sc['score_hpem']:.0f} %"],
        ["Score fabrication", f"{sc['score_fabrication']:.0f} %"],
        ["Confiance modele", f"{sc['confidence']:.0f} %"],
        ["Interpretation", score_interpretation(sc['score_global'])],
    ], [80, 95])
    heading("8. Defauts prioritaires")
    table(["Priorite", "Defaut", "Impact", "Action"], [[str(r['Priorite']), r['Defaut'], r['Impact'], r['Action recommandee']] for r in defect_ranking_rows(results)[:4]], [25, 45, 30, 78], font_size=7.6)
    heading("9. Matrice de risque HPEM")
    table(["Zone", "Risque", "Cause", "Action"], [[r['Zone'], r['Risque'], r['Cause'], r['Action']] for r in hpem_risk_matrix_rows(results)[:4]], [40, 28, 55, 55], font_size=7.4)
    footer()

    pdf.add_page()
    heading("10. Recommandations automatiques")
    for rec in generate_recommendations(results):
        bullet(rec)
    heading("11. Validation experimentale recommandee")
    bullet("Mesurer le S11 sur toute la bande avec un VNA calibre.")
    bullet("Mesurer le gain et relever les diagrammes de rayonnement dans les plans H et E.")
    bullet("Comparer les etats theorique, fabrique et corrige apres finition.")
    heading("12. Conclusion")
    paragraph(memory_text_block(results))
    heading("13. Note de validite")
    paragraph("Les figures et diagrammes integres dans l'application sont des representations parametriques et qualitatives. Ils sont adaptes a la presentation, a la comparaison et a la redaction d'un rapport universitaire, mais la validation finale doit etre confirmee par simulation EM 3D et par mesures experimentales.")
    footer()

    out = pdf.output(dest="S")
    if isinstance(out, bytearray):
        return bytes(out)
    if isinstance(out, bytes):
        return out
    if isinstance(out, str):
        return out.encode("latin-1", "replace")
    return None

def make_pdf_report(results: dict) -> bytes | None:
    if not PDF_AVAILABLE:
        return None

    p = results["params"]
    th = results["theoretical"]
    fab = results["fabricated"]
    corr = results["corrected"]
    hp = fab["hpem"]
    sweep = frequency_response_data(results, n=31)

    def safe(txt: str) -> str:
        return str(txt).encode("latin-1", "replace").decode("latin-1")

    def section(pdf, title: str) -> None:
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(30, 64, 175)
        pdf.multi_cell(0, 7, safe(title), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", size=10)

    def bullet(pdf, txt: str) -> None:
        pdf.set_font("Helvetica", size=10)
        pdf.multi_cell(0, 5.2, safe("- " + txt), new_x="LMARGIN", new_y="NEXT")

    def draw_metric_box(pdf, x, y, w, h, title, value, color):
        pdf.set_draw_color(210, 220, 235)
        pdf.set_fill_color(248, 250, 252)
        pdf.rect(x, y, w, h, "DF")
        pdf.set_text_color(*color)
        pdf.set_font("Helvetica", "B", 12)
        pdf.text(x + 4, y + 8, safe(value))
        pdf.set_text_color(70, 80, 100)
        pdf.set_font("Helvetica", size=8)
        pdf.text(x + 4, y + 15, safe(title))
        pdf.set_text_color(0, 0, 0)

    def draw_comparison(pdf, x, y):
        rows = results["comparison"]
        colors = [(37, 99, 235), (5, 150, 105), (245, 158, 11)]
        groups = [
            ("Gain dBi", [r["Gain dBi"] for r in rows], max([r["Gain dBi"] for r in rows] + [1])),
            ("|S11| dB", [abs(r["S11 dB"]) for r in rows], max([abs(r["S11 dB"]) for r in rows] + [1])),
            ("Score %", [r["Score HPEM %"] for r in rows], 100.0),
        ]
        pdf.set_font("Helvetica", "B", 11)
        pdf.text(x, y, safe("Comparaison theorique / fabrique / corrige"))
        base = y + 48
        for gi, (name, vals, vmax) in enumerate(groups):
            gx = x + gi * 60
            pdf.set_font("Helvetica", size=8)
            pdf.text(gx + 10, base + 6, safe(name))
            for i, val in enumerate(vals):
                bh = 38 * max(0, min(1, val / max(vmax, 1e-9)))
                bx = gx + 7 + i * 9
                by = base - bh
                pdf.set_fill_color(*colors[i])
                pdf.rect(bx, by, 6, bh, "F")
                pdf.set_font("Helvetica", size=6)
                pdf.text(bx - 1, by - 2, safe(f"{val:.1f}"))
        pdf.set_font("Helvetica", size=7)
        for i, row in enumerate(rows):
            pdf.set_fill_color(*colors[i])
            pdf.rect(x + i * 42, base + 13, 4, 4, "F")
            pdf.text(x + i * 42 + 6, base + 17, safe(row["Cas"]))

    def draw_curve(pdf, x, y, w, h, title, xs, series):
        pdf.set_font("Helvetica", "B", 10)
        pdf.text(x, y, safe(title))
        y += 5
        all_y = [v for _, vals, _ in series for v in vals]
        ymin, ymax = min(all_y), max(all_y)
        pad = max((ymax - ymin) * 0.12, 0.5)
        ymin -= pad
        ymax += pad
        xmin, xmax = min(xs), max(xs)
        pdf.set_draw_color(150, 160, 175)
        pdf.rect(x, y, w, h)
        pdf.set_font("Helvetica", size=6)
        for k in range(4):
            yy = y + h * k / 3
            pdf.set_draw_color(225, 230, 238)
            pdf.line(x, yy, x + w, yy)
        for name, vals, color in series:
            pdf.set_draw_color(*color)
            last = None
            for xv, yv in zip(xs, vals):
                px = x + (xv - xmin) / max(xmax - xmin, 1e-9) * w
                py = y + (ymax - yv) / max(ymax - ymin, 1e-9) * h
                if last:
                    pdf.line(last[0], last[1], px, py)
                last = (px, py)
        ly = y + h + 5
        for i, (name, _, color) in enumerate(series):
            pdf.set_fill_color(*color)
            pdf.rect(x + i * 45, ly, 4, 4, "F")
            pdf.text(x + i * 45 + 6, ly + 4, safe(name))

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=13)

    # Cover page
    pdf.add_page()
    pdf.set_fill_color(30, 64, 175)
    pdf.rect(0, 0, 210, 48, "F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_xy(14, 13)
    pdf.multi_cell(180, 10, safe("Application web parametrique\nAntenne cornet HPEM - bande S"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=11)
    pdf.set_xy(14, 36)
    pdf.cell(0, 7, safe("Rapport automatique / validation electromagnetique"))
    pdf.set_text_color(0, 0, 0)
    pdf.set_y(62)
    pdf.set_font("Helvetica", size=11)
    intro = (
        "Ce rapport presente les resultats calcules par l'application: dimensionnement, validation du guide, "
        "performances RF, impact des defauts de fabrication, analyse HPEM et recommandations d'amelioration."
    )
    pdf.multi_cell(0, 6, safe(intro), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    draw_metric_box(pdf, 14, 92, 43, 22, "Guide", p["guide_type"], (30, 64, 175))
    draw_metric_box(pdf, 62, 92, 43, 22, "Gain fabrique", f"{fab['gain_dbi']:.2f} dBi", (5, 150, 105))
    draw_metric_box(pdf, 110, 92, 43, 22, "S11", f"{fab['penalties']['s11_db']:.1f} dB", (245, 158, 11))
    draw_metric_box(pdf, 158, 92, 38, 22, "Score HPEM", f"{hp['score_hpem']:.0f} %", (220, 38, 38))
    pdf.set_y(125)
    section(pdf, "Texte de synthese automatique")
    pdf.multi_cell(0, 5.5, safe(
        "Dans le but de renforcer l'analyse experimentale, un outil web parametrique a ete propose afin "
        "d'estimer l'influence des parametres geometriques et des defauts de fabrication sur les performances "
        "de l'antenne cornet. Cet outil permet d'etablir un lien direct entre la conception, la fabrication "
        "reelle et la validation electromagnetique, notamment dans un contexte HPEM ou les discontinuites "
        "de surface peuvent fortement influencer la tenue en puissance."
    ), new_x="LMARGIN", new_y="NEXT")

    # Results page
    pdf.add_page()
    section(pdf, "1. Parametres et validation modale")
    bullet(pdf, f"Frequence centrale: {p['f_center_ghz']:.3f} GHz ; bande: {p['f_min_ghz']:.3f}-{p['f_max_ghz']:.3f} GHz")
    bullet(pdf, f"Guide: {p['guide_type']} ; coupure TE10: {th['fc_te10_ghz']:.3f} GHz ; premier mode superieur: {th['upper_mode_ghz']:.3f} GHz")
    bullet(pdf, f"Ouverture: {p['aperture_width_mm']:.1f} x {p['aperture_height_mm']:.1f} mm ; longueur: {p['horn_length_mm']:.1f} mm")
    bullet(pdf, f"Etat modal: {th['mode_status']}")
    section(pdf, "2. Resultats RF et HPEM")
    bullet(pdf, f"Directivite: {th['directivity_dbi']:.2f} dBi")
    bullet(pdf, f"Gain theorique: {th['gain_dbi']:.2f} dBi ; gain fabrique: {fab['gain_dbi']:.2f} dBi ; gain corrige: {corr['gain_dbi']:.2f} dBi")
    bullet(pdf, f"S11 theorique: {th['base_s11_db']:.1f} dB ; S11 fabrique: {fab['penalties']['s11_db']:.1f} dB")
    bullet(pdf, f"Champ crete gorge: {hp['e_peak_throat_kv_per_m']:.0f} kV/m ; marge air: {hp['breakdown_margin_air']:.2f}")
    draw_comparison(pdf, 15, 118)

    # Curves page
    pdf.add_page()
    section(pdf, "3. Courbes parametriques sur la bande")
    xs = sweep["f"]
    draw_curve(pdf, 15, 35, 180, 55, "Gain en fonction de la frequence", xs, [
        ("Theorique", sweep["gain_theorique"], (37, 99, 235)),
        ("Fabrique", sweep["gain_fabrique"], (5, 150, 105)),
        ("Corrige", sweep["gain_corrige"], (245, 158, 11)),
    ])
    draw_curve(pdf, 15, 115, 180, 55, "S11 estime en fonction de la frequence", xs, [
        ("Theorique", sweep["s11_theorique"], (37, 99, 235)),
        ("Fabrique", sweep["s11_fabrique"], (5, 150, 105)),
        ("Corrige", sweep["s11_corrige"], (245, 158, 11)),
    ])
    draw_curve(pdf, 15, 195, 180, 55, "Score HPEM en fonction de la frequence", xs, [
        ("Fabrique", sweep["score_fabrique"], (5, 150, 105)),
        ("Corrige", sweep["score_corrige"], (245, 158, 11)),
    ])

    # Recommendations page
    pdf.add_page()
    section(pdf, "4. Recommandations automatiques")
    for rec in generate_recommendations(results):
        bullet(pdf, rec)
    section(pdf, "5. Limite du modele")
    pdf.multi_cell(0, 5.5, safe(
        "Les cartes E/H et les courbes sont des estimations analytiques et parametriques. Elles aident a structurer "
        "l'analyse et a identifier les zones critiques, mais elles ne remplacent pas une simulation EM 3D "
        "complete ni les mesures experimentales VNA et HPEM."
    ), new_x="LMARGIN", new_y="NEXT")

    out = pdf.output(dest="S")
    if isinstance(out, bytearray):
        return bytes(out)
    if isinstance(out, bytes):
        return out
    if isinstance(out, str):
        return out.encode("latin-1", "replace")
    return None

def simple_bar(label: str, value: float, max_value: float, suffix: str = "") -> None:
    ratio = 0.0 if max_value <= 0 else max(0.0, min(1.0, value / max_value))
    st.markdown(
        f"**{html.escape(label)}** — {fmt(value, 2)}{suffix}<div style='background:#e6eaf0;border-radius:8px;height:14px;overflow:hidden'><div style='width:{ratio*100:.1f}%;background:#356ae6;height:14px'></div></div>",
        unsafe_allow_html=True,
    )


def horn_2d_svg(params: AntennaParams) -> str:
    guide = WAVEGUIDES[params.guide_type]
    throat_h = 36
    mouth_h = max(90, int(140 * params.aperture_height_mm / max(params.aperture_width_mm, 1)))
    x0, x1, x2 = 30, 110, 390
    ymid = 125
    throat_top = ymid - throat_h / 2
    throat_bottom = ymid + throat_h / 2
    mouth_top = ymid - mouth_h / 2
    mouth_bottom = ymid + mouth_h / 2
    return f"""
    <svg viewBox='0 0 480 260' width='100%' height='260' xmlns='http://www.w3.org/2000/svg'>
      <defs>
        <marker id='arrow' markerWidth='8' markerHeight='8' refX='4' refY='4' orient='auto'>
          <path d='M0,0 L8,4 L0,8 z' fill='#1f2937'/>
        </marker>
      </defs>
      <rect x='10' y='10' width='460' height='240' rx='12' fill='#fafbfc' stroke='#d9dee7'/>
      <rect x='{x0}' y='{throat_top}' width='{x1-x0}' height='{throat_h}' fill='#dbeafe' stroke='#1d4ed8' stroke-width='2'/>
      <polygon points='{x1},{throat_top} {x2},{mouth_top} {x2},{mouth_bottom} {x1},{throat_bottom}' fill='#dcfce7' stroke='#15803d' stroke-width='2'/>
      <line x1='{x0}' y1='{throat_top-18}' x2='{x1}' y2='{throat_top-18}' stroke='#1f2937' stroke-width='1.5' marker-start='url(#arrow)' marker-end='url(#arrow)'/>
      <text x='{(x0+x1)/2}' y='{throat_top-24}' text-anchor='middle' font-size='14'>a = {guide.a_mm:.1f} mm</text>
      <line x1='{x2+18}' y1='{mouth_top}' x2='{x2+18}' y2='{mouth_bottom}' stroke='#1f2937' stroke-width='1.5' marker-start='url(#arrow)' marker-end='url(#arrow)'/>
      <text x='{x2+28}' y='{ymid}' font-size='14'>B = {params.aperture_height_mm:.1f} mm</text>
      <line x1='{x1}' y1='{mouth_bottom+28}' x2='{x2}' y2='{mouth_bottom+28}' stroke='#1f2937' stroke-width='1.5' marker-start='url(#arrow)' marker-end='url(#arrow)'/>
      <text x='{(x1+x2)/2}' y='{mouth_bottom+20}' text-anchor='middle' font-size='14'>L = {params.horn_length_mm:.1f} mm</text>
      <line x1='{x2-110}' y1='{mouth_top-20}' x2='{x2}' y2='{mouth_top-20}' stroke='#1f2937' stroke-width='1.5' marker-start='url(#arrow)' marker-end='url(#arrow)'/>
      <text x='{x2-55}' y='{mouth_top-26}' text-anchor='middle' font-size='14'>A = {params.aperture_width_mm:.1f} mm</text>
      <text x='24' y='35' font-size='16' font-weight='bold'>Vue 2D - cornet pyramidal</text>
      <text x='24' y='55' font-size='13' fill='#475569'>Guide {guide.name} de la gorge vers l'ouverture</text>
    </svg>
    """


def horn_3d_svg(params: AntennaParams) -> str:
    guide = WAVEGUIDES[params.guide_type]
    scale = 0.35
    throat_w = max(40, guide.a_mm * scale)
    throat_h = max(24, guide.b_mm * scale)
    mouth_w = max(130, params.aperture_width_mm * scale)
    mouth_h = max(90, params.aperture_height_mm * scale)
    x1, y1 = 90, 90
    x2, y2 = 290, 55
    dx, dy = 42, 28
    return f"""
    <svg viewBox='0 0 480 280' width='100%' height='280' xmlns='http://www.w3.org/2000/svg'>
      <rect x='10' y='10' width='460' height='260' rx='12' fill='#fbfcfe' stroke='#d9dee7'/>
      <polygon points='{x1},{y1} {x1+throat_w},{y1} {x2+mouth_w},{y2} {x2},{y2}' fill='#e0f2fe' stroke='#0f766e' stroke-width='2'/>
      <polygon points='{x1+throat_w},{y1} {x1+throat_w+dx},{y1+dy} {x2+mouth_w+dx},{y2+dy} {x2+mouth_w},{y2}' fill='#bae6fd' stroke='#0f766e' stroke-width='2'/>
      <polygon points='{x1},{y1} {x1+dx},{y1+dy} {x1+throat_w+dx},{y1+dy} {x1+throat_w},{y1}' fill='#cffafe' stroke='#0f766e' stroke-width='2'/>
      <polygon points='{x1},{y1+throat_h} {x1+throat_w},{y1+throat_h} {x2+mouth_w},{y2+mouth_h} {x2},{y2+mouth_h}' fill='#dcfce7' stroke='#15803d' stroke-width='2'/>
      <polygon points='{x1+throat_w},{y1+throat_h} {x1+throat_w+dx},{y1+throat_h+dy} {x2+mouth_w+dx},{y2+mouth_h+dy} {x2+mouth_w},{y2+mouth_h}' fill='#bbf7d0' stroke='#15803d' stroke-width='2'/>
      <polygon points='{x1},{y1+throat_h} {x1+dx},{y1+throat_h+dy} {x1+throat_w+dx},{y1+throat_h+dy} {x1+throat_w},{y1+throat_h}' fill='#dcfce7' stroke='#15803d' stroke-width='2'/>
      <rect x='{x1}' y='{y1}' width='{throat_w}' height='{throat_h}' fill='none' stroke='#1d4ed8' stroke-width='2'/>
      <rect x='{x2}' y='{y2}' width='{mouth_w}' height='{mouth_h}' fill='none' stroke='#15803d' stroke-width='2'/>
      <text x='24' y='35' font-size='16' font-weight='bold'>Vue pseudo-3D du cornet</text>
      <text x='24' y='55' font-size='13' fill='#475569'>Projection simplifiee pour visualiser la transition guide - ouverture</text>
      <text x='24' y='240' font-size='14'>Guide {guide.name}</text>
      <text x='24' y='258' font-size='14'>a x b = {guide.a_mm:.1f} x {guide.b_mm:.1f} mm</text>
      <text x='260' y='240' font-size='14'>Ouverture A x B = {params.aperture_width_mm:.1f} x {params.aperture_height_mm:.1f} mm</text>
      <text x='260' y='258' font-size='14'>Longueur L = {params.horn_length_mm:.1f} mm</text>
    </svg>
    """


def beam_cartesian_svg(hpbw_deg: float, title: str, color: str) -> str:
    width = 460
    height = 250
    left = 45
    right = width - 20
    top = 20
    bottom = height - 40
    mid_y = bottom
    xs = []
    sigma = max(hpbw_deg / 2.355, 1.0)
    for i in range(0, 401):
        angle = -90 + 180 * i / 400
        amp = math.exp(-0.5 * (angle / sigma) ** 2)
        x = left + (right - left) * i / 400
        y = bottom - 180 * amp
        xs.append(f"{x:.1f},{y:.1f}")
    poly = " ".join(xs)
    hw = (right - left) * hpbw_deg / 180 / 2
    return f"""
    <svg viewBox='0 0 {width} {height}' width='100%' height='{height}' xmlns='http://www.w3.org/2000/svg'>
      <rect x='1' y='1' width='{width-2}' height='{height-2}' rx='12' fill='#fbfcfe' stroke='#d9dee7'/>
      <line x1='{left}' y1='{bottom}' x2='{right}' y2='{bottom}' stroke='#64748b' stroke-width='1.2'/>
      <line x1='{(left+right)/2}' y1='{top}' x2='{(left+right)/2}' y2='{bottom}' stroke='#cbd5e1' stroke-width='1.2'/>
      <line x1='{left}' y1='{bottom-90}' x2='{right}' y2='{bottom-90}' stroke='#e2e8f0' stroke-width='1'/>
      <line x1='{left}' y1='{bottom-180}' x2='{right}' y2='{bottom-180}' stroke='#e2e8f0' stroke-width='1'/>
      <polyline points='{poly}' fill='none' stroke='{color}' stroke-width='3'/>
      <line x1='{(left+right)/2 - hw:.1f}' y1='{bottom-90}' x2='{(left+right)/2 + hw:.1f}' y2='{bottom-90}' stroke='#111827' stroke-width='2'/>
      <text x='20' y='25' font-size='16' font-weight='bold'>{html.escape(title)}</text>
      <text x='20' y='45' font-size='13' fill='#475569'>HPBW ≈ {hpbw_deg:.1f}° ; niveau -3 dB</text>
      <text x='{left}' y='{bottom+18}' font-size='12' fill='#64748b'>-90°</text>
      <text x='{(left+right)/2 - 10}' y='{bottom+18}' font-size='12' fill='#64748b'>0°</text>
      <text x='{right-25}' y='{bottom+18}' font-size='12' fill='#64748b'>+90°</text>
      <text x='8' y='{bottom-175}' font-size='12' fill='#64748b'>0 dB</text>
      <text x='4' y='{bottom-85}' font-size='12' fill='#64748b'>-3 dB</text>
      <text x='4' y='{bottom-2}' font-size='12' fill='#64748b'>-∞</text>
    </svg>
    """


def beam_polar_svg(hpbw_deg: float, title: str, color: str) -> str:
    cx, cy = 170, 170
    rmax = 120
    pts = []
    sigma = max(hpbw_deg / 2.355, 1.0)
    for i in range(181):
        ang = -90 + i
        amp = math.exp(-0.5 * (ang / sigma) ** 2)
        r = amp * rmax
        x = cx + r * math.sin(math.radians(ang))
        y = cy - r * math.cos(math.radians(ang))
        pts.append(f"{x:.1f},{y:.1f}")
    path = " ".join(pts)
    return f"""
    <svg viewBox='0 0 360 260' width='100%' height='260' xmlns='http://www.w3.org/2000/svg'>
      <rect x='1' y='1' width='358' height='258' rx='12' fill='#fbfcfe' stroke='#d9dee7'/>
      <circle cx='{cx}' cy='{cy}' r='40' fill='none' stroke='#e2e8f0'/>
      <circle cx='{cx}' cy='{cy}' r='80' fill='none' stroke='#e2e8f0'/>
      <circle cx='{cx}' cy='{cy}' r='{rmax}' fill='none' stroke='#cbd5e1'/>
      <line x1='{cx}' y1='{cy-rmax}' x2='{cx}' y2='{cy}' stroke='#64748b'/>
      <line x1='{cx-rmax}' y1='{cy}' x2='{cx+rmax}' y2='{cy}' stroke='#64748b'/>
      <polyline points='{path}' fill='none' stroke='{color}' stroke-width='3'/>
      <text x='18' y='24' font-size='16' font-weight='bold'>{html.escape(title)}</text>
      <text x='18' y='44' font-size='13' fill='#475569'>Representation polaire approximative</text>
      <text x='{cx-10}' y='{cy-rmax-8}' font-size='12'>0°</text>
      <text x='{cx+rmax+6}' y='{cy+4}' font-size='12'>+90°</text>
      <text x='{cx-rmax-24}' y='{cy+4}' font-size='12'>-90°</text>
      <text x='{cx+rmax-12}' y='{cy-rmax+15}' font-size='12'>HPBW ~ {hpbw_deg:.1f}°</text>
    </svg>
    """


def radiation_pattern_svg(hpbw_h_deg: float, hpbw_e_deg: float, directivity_dbi: float) -> str:
    width, height = 760, 340
    cx1, cy = 190, 195
    cx2 = 560
    rmax = 120

    def curve_points(hpbw_deg: float, cx: float) -> str:
        sigma = max(hpbw_deg / 2.355, 1.0)
        pts = []
        for i in range(361):
            ang = -180 + i
            a = abs(((ang + 180) % 360) - 180)
            if a > 90:
                amp = 0.07 * math.exp(-0.5 * ((180 - a) / max(sigma*0.9, 1.0)) ** 2)
            else:
                amp = math.exp(-0.5 * (a / sigma) ** 2)
            r = max(8.0, amp * rmax)
            x = cx + r * math.sin(math.radians(ang))
            y = cy - r * math.cos(math.radians(ang))
            pts.append(f"{x:.1f},{y:.1f}")
        return " ".join(pts)

    p1 = curve_points(hpbw_h_deg, cx1)
    p2 = curve_points(hpbw_e_deg, cx2)

    def polar_grid(cx: float) -> str:
        items = [
            f"<circle cx='{cx}' cy='{cy}' r='30' fill='none' stroke='#e2e8f0'/>",
            f"<circle cx='{cx}' cy='{cy}' r='60' fill='none' stroke='#e2e8f0'/>",
            f"<circle cx='{cx}' cy='{cy}' r='90' fill='none' stroke='#e2e8f0'/>",
            f"<circle cx='{cx}' cy='{cy}' r='{rmax}' fill='none' stroke='#cbd5e1'/>",
            f"<line x1='{cx-rmax}' y1='{cy}' x2='{cx+rmax}' y2='{cy}' stroke='#94a3b8' stroke-width='1'/>",
            f"<line x1='{cx}' y1='{cy-rmax}' x2='{cx}' y2='{cy+rmax}' stroke='#94a3b8' stroke-width='1'/>",
            f"<text x='{cx-10}' y='{cy-rmax-8}' font-size='12'>0°</text>",
            f"<text x='{cx+rmax+6}' y='{cy+4}' font-size='12'>90°</text>",
            f"<text x='{cx-12}' y='{cy+rmax+18}' font-size='12'>180°</text>",
            f"<text x='{cx-rmax-28}' y='{cy+4}' font-size='12'>-90°</text>",
        ]
        return ''.join(items)

    return f"""
    <svg viewBox='0 0 {width} {height}' width='100%' height='{height}' xmlns='http://www.w3.org/2000/svg'>
      <rect x='1' y='1' width='{width-2}' height='{height-2}' rx='12' fill='#fbfcfe' stroke='#d9dee7'/>
      <text x='20' y='26' font-size='18' font-weight='bold'>Diagramme de rayonnement synthétique</text>
      <text x='20' y='48' font-size='13' fill='#475569'>Représentation polaire simplifiée des lobes principaux dans les plans H et E</text>
      {polar_grid(cx1)}
      {polar_grid(cx2)}
      <polyline points='{p1}' fill='rgba(37,99,235,0.08)' stroke='#2563eb' stroke-width='3'/>
      <polyline points='{p2}' fill='rgba(5,150,105,0.08)' stroke='#059669' stroke-width='3'/>
      <text x='{cx1-45}' y='34' font-size='15' font-weight='bold'>Plan H</text>
      <text x='{cx2-45}' y='34' font-size='15' font-weight='bold'>Plan E</text>
      <text x='{cx1-64}' y='314' font-size='12'>HPBW H ≈ {hpbw_h_deg:.1f}°</text>
      <text x='{cx2-64}' y='314' font-size='12'>HPBW E ≈ {hpbw_e_deg:.1f}°</text>
      <text x='20' y='318' font-size='12' fill='#475569'>Directivité estimée : {directivity_dbi:.2f} dBi</text>
      <rect x='560' y='20' width='14' height='14' fill='#059669' rx='2'/><text x='580' y='32' font-size='12'>Plan E</text>
      <rect x='470' y='20' width='14' height='14' fill='#2563eb' rx='2'/><text x='490' y='32' font-size='12'>Plan H</text>
    </svg>
    """



def _pattern_db_series(hpbw_deg: float, angles: list[float], broadening: float = 0.0, sidelobe_level_db: float = -17.0) -> list[float]:
    sigma = max((hpbw_deg * (1.0 + broadening)) / 2.355, 1.0)
    out = []
    for ang in angles:
        main = math.exp(-0.5 * (ang / sigma) ** 2)
        sl_amp = 10 ** (sidelobe_level_db / 20.0)
        side = 0.0
        for c, w, scale in [(-46, 10, 1.0), (46, 10, 1.0), (-72, 8, 0.55), (72, 8, 0.55)]:
            side += sl_amp * scale * math.exp(-0.5 * ((ang - c) / w) ** 2)
        back = 0.045 * math.exp(-0.5 * ((abs(ang) - 90) / 10.0) ** 2)
        amp = max(main + side + back, 1e-5)
        db = 20.0 * math.log10(amp)
        out.append(max(-40.0, min(0.0, db)))
    return out


def radiation_db_comparison_svg(results: dict, plane: str = "H") -> str:
    th = results["theoretical"]
    fab = results["fabricated"]
    cor = results["corrected"]
    hpbw_key = "hpbw_h_deg" if plane.upper() == "H" else "hpbw_e_deg"
    base = th[hpbw_key]
    fab_broad = max(0.02, fab["penalties"]["total_loss_db"] / 4.0)
    cor_broad = max(0.01, cor["penalties"]["total_loss_db"] / 5.0)
    angles = [-90 + 180*i/240 for i in range(241)]
    series = [
        ("Theorique", _pattern_db_series(base, angles, 0.0, -18.5), "#2563eb"),
        ("Fabrique", _pattern_db_series(base * (1.0 + 0.18*fab_broad), angles, fab_broad, -14.5), "#f59e0b"),
        ("Corrige", _pattern_db_series(base * (1.0 + 0.10*cor_broad), angles, cor_broad, -16.5), "#059669"),
    ]

    width, height = 760, 290
    left, right, top, bottom = 54, 736, 26, 246

    def path(vals: list[float]) -> str:
        pts = []
        for i, val in enumerate(vals):
            x = left + (right-left) * i / (len(vals)-1)
            y = top + (0 - val) / 40.0 * (bottom-top)
            pts.append(f"{x:.1f},{y:.1f}")
        return " ".join(pts)

    grid = []
    for db in [0, -3, -10, -20, -30, -40]:
        y = top + (0 - db) / 40.0 * (bottom-top)
        grid.append(f"<line x1='{left}' y1='{y:.1f}' x2='{right}' y2='{y:.1f}' stroke='#e2e8f0' stroke-width='1'/><text x='8' y='{y+4:.1f}' font-size='12' fill='#64748b'>{db} dB</text>")
    for a in [-90, -60, -30, 0, 30, 60, 90]:
        x = left + (a + 90) / 180.0 * (right-left)
        grid.append(f"<line x1='{x:.1f}' y1='{top}' x2='{x:.1f}' y2='{bottom}' stroke='#eef2f7' stroke-width='1'/><text x='{x-12:.1f}' y='{bottom+18}' font-size='12' fill='#64748b'>{a}°</text>")

    legends = []
    lx = 445
    for i, (name, vals, color) in enumerate(series):
        legends.append(f"<rect x='{lx}' y='{22 + i*18}' width='14' height='14' fill='{color}' rx='2'/><text x='{lx+22}' y='{34 + i*18}' font-size='12'>{name}</text>")

    paths = []
    for name, vals, color in series:
        paths.append(f"<polyline points='{path(vals)}' fill='none' stroke='{color}' stroke-width='2.8'/>")

    return f"""
    <svg viewBox='0 0 {width} {height}' width='100%' height='{height}' xmlns='http://www.w3.org/2000/svg'>
      <rect x='1' y='1' width='{width-2}' height='{height-2}' rx='12' fill='#fbfcfe' stroke='#d9dee7'/>
      <text x='20' y='24' font-size='18' font-weight='bold'>Diagramme de rayonnement normalisé - plan {plane.upper()}</text>
      <text x='20' y='44' font-size='13' fill='#475569'>Comparaison théorique / fabriqué / corrigé en dB normalisés</text>
      {''.join(grid)}
      <line x1='{left}' y1='{bottom}' x2='{right}' y2='{bottom}' stroke='#64748b' stroke-width='1.2'/>
      <line x1='{left}' y1='{top}' x2='{left}' y2='{bottom}' stroke='#64748b' stroke-width='1.2'/>
      {''.join(paths)}
      {''.join(legends)}
      <text x='{(left+right)/2 - 56}' y='{height-12}' font-size='12' fill='#64748b'>Angle d'observation</text>
    </svg>
    """


def radiation_3d_lobe_svg(hpbw_h_deg: float, hpbw_e_deg: float, gain_dbi: float) -> str:
    width, height = 760, 360
    cx, cy = 380, 195
    scale = 112
    pts = []
    for i in range(361):
        t = math.radians(i)
        a = (1.0 + 0.45 * math.cos(t))
        x = cx + scale * a * math.cos(t)
        y = cy + 0.55 * scale * a * math.sin(t)
        pts.append(f"{x:.1f},{y:.1f}")
    ring = ' '.join(pts)

    front = []
    for i in range(0, 181):
        phi = -math.pi/2 + i * math.pi / 180
        rx = 36 + 155 * math.exp(-0.5 * ((phi*180/math.pi) / max(hpbw_h_deg/2.0, 8))**2)
        ry = 22 + 108 * math.exp(-0.5 * ((phi*180/math.pi) / max(hpbw_e_deg/2.0, 8))**2)
        x = cx + rx * math.cos(phi)
        y = cy - ry * math.sin(phi) * 0.78
        front.append(f"{x:.1f},{y:.1f}")
    front_path = ' '.join(front)

    return f"""
    <svg viewBox='0 0 {width} {height}' width='100%' height='{height}' xmlns='http://www.w3.org/2000/svg'>
      <rect x='1' y='1' width='{width-2}' height='{height-2}' rx='12' fill='#fbfcfe' stroke='#d9dee7'/>
      <text x='20' y='24' font-size='18' font-weight='bold'>Lobe principal 3D stylisé</text>
      <text x='20' y='44' font-size='13' fill='#475569'>Vue illustrative de la directivité et de l'ouverture angulaire</text>
      <line x1='110' y1='{cy}' x2='650' y2='{cy}' stroke='#94a3b8'/>
      <line x1='{cx}' y1='70' x2='{cx}' y2='306' stroke='#94a3b8'/>
      <line x1='{cx-170}' y1='{cy+72}' x2='{cx+170}' y2='{cy-72}' stroke='#cbd5e1'/>
      <polyline points='{ring}' fill='none' stroke='#dbeafe' stroke-width='2'/>
      <polyline points='{front_path}' fill='rgba(37,99,235,0.15)' stroke='#2563eb' stroke-width='3'/>
      <ellipse cx='{cx}' cy='{cy}' rx='38' ry='24' fill='rgba(5,150,105,0.12)' stroke='#059669' stroke-width='2'/>
      <path d='M {cx-10},{cy-1} Q {cx+85},{cy-88} {cx+195},{cy-5}' fill='none' stroke='#2563eb' stroke-width='3'/>
      <path d='M {cx-10},{cy+2} Q {cx+92},{cy+92} {cx+188},{cy+14}' fill='none' stroke='#059669' stroke-width='3' opacity='0.9'/>
      <text x='34' y='326' font-size='12' fill='#475569'>HPBW H ≈ {hpbw_h_deg:.1f}° ; HPBW E ≈ {hpbw_e_deg:.1f}° ; Gain ≈ {gain_dbi:.2f} dBi</text>
      <text x='{cx+200}' y='{cy-12}' font-size='12'>Axe principal</text>
      <text x='{cx+128}' y='{cy-88}' font-size='12'>Plan H</text>
      <text x='{cx+135}' y='{cy+102}' font-size='12'>Plan E</text>
    </svg>
    """


def directivity_gauge_svg(directivity_dbi: float, gain_dbi: float, score_hpem: float) -> str:
    width, height = 420, 210
    cx, cy, r = 120, 130, 74
    ratio = max(0.0, min(1.0, directivity_dbi / 25.0))
    end_angle = -180 + 180 * ratio
    ex = cx + r * math.cos(math.radians(end_angle))
    ey = cy + r * math.sin(math.radians(end_angle))
    return f"""
    <svg viewBox='0 0 {width} {height}' width='100%' height='{height}' xmlns='http://www.w3.org/2000/svg'>
      <rect x='1' y='1' width='{width-2}' height='{height-2}' rx='12' fill='#fbfcfe' stroke='#d9dee7'/>
      <path d='M {cx-r},{cy} A {r},{r} 0 0 1 {cx+r},{cy}' fill='none' stroke='#e2e8f0' stroke-width='16'/>
      <path d='M {cx-r},{cy} A {r},{r} 0 0 1 {ex:.1f},{ey:.1f}' fill='none' stroke='#2563eb' stroke-width='16'/>
      <line x1='{cx}' y1='{cy}' x2='{ex:.1f}' y2='{ey:.1f}' stroke='#111827' stroke-width='3'/>
      <circle cx='{cx}' cy='{cy}' r='5' fill='#111827'/>
      <text x='{cx-32}' y='{cy-92}' font-size='12' fill='#64748b'>0</text>
      <text x='{cx+r-8}' y='{cy-92}' font-size='12' fill='#64748b'>25 dBi</text>
      <text x='20' y='24' font-size='16' font-weight='bold'>Synthèse directivité</text>
      <text x='40' y='168' font-size='18' font-weight='bold'>{directivity_dbi:.2f} dBi</text>
      <text x='210' y='56' font-size='14'>Gain estimé : {gain_dbi:.2f} dBi</text>
      <text x='210' y='84' font-size='14'>Score HPEM : {score_hpem:.0f} %</text>
      <text x='210' y='112' font-size='14'>Lobe principal : dominant</text>
      <text x='210' y='140' font-size='14'>Utilisable pour comparaison rapide</text>
    </svg>
    """


def measurement_protocol_rows(results: dict) -> list[dict]:
    p = results["params"]
    return [
        {"Etape": 1, "Action": "Inspection mecanique", "But": "Verifier A, B, L, alignement, soudures, etat de surface", "Outil": "Pied a coulisse / controle visuel"},
        {"Etape": 2, "Action": "Mesure S11", "But": f"Verifier l'adaptation sur {p['f_min_ghz']:.2f}-{p['f_max_ghz']:.2f} GHz", "Outil": "VNA calibre"},
        {"Etape": 3, "Action": "Mesure Gain(f)", "But": "Comparer le gain theorique, fabrique et corrige", "Outil": "Antenne de reference / banc de gain"},
        {"Etape": 4, "Action": "Diagramme de rayonnement", "But": "Relever les plans H et E et estimer la HPBW", "Outil": "Rotation angulaire / chambre anechoique"},
        {"Etape": 5, "Action": "Essai apres finition", "But": "Quantifier l'effet du poncage/polissage", "Outil": "Mesures avant/apres"},
        {"Etape": 6, "Action": "Analyse HPEM", "But": "Identifier les zones critiques et la tenue en puissance", "Outil": "Inspection + modele parametrique"},
    ]


def page_measurements(results: dict) -> None:
    st.title("Mesures experimentales")
    st.write("Cette page propose un protocole simple pour valider experimentalement les resultats calcules et comparer l'antenne theorique, fabriquee et corrigee.")

    th = results["theoretical"]
    fab = results["fabricated"]
    corr = results["corrected"]

    st.subheader("1. Valeurs cibles a verifier")
    targets = [
        {"Grandeur": "Gain", "Theorique": f"{th['gain_dbi']:.2f} dBi", "Fabrique estime": f"{fab['gain_dbi']:.2f} dBi", "Corrige estime": f"{corr['gain_dbi']:.2f} dBi"},
        {"Grandeur": "S11", "Theorique": f"{th['base_s11_db']:.1f} dB", "Fabrique estime": f"{fab['penalties']['s11_db']:.1f} dB", "Corrige estime": f"{corr['penalties']['s11_db']:.1f} dB"},
        {"Grandeur": "HPBW H", "Theorique": f"{th['hpbw_h_deg']:.1f} deg", "Fabrique estime": f"{th['hpbw_h_deg'] * (1+fab['penalties']['total_loss_db']/12):.1f} deg", "Corrige estime": f"{th['hpbw_h_deg'] * (1+corr['penalties']['total_loss_db']/14):.1f} deg"},
        {"Grandeur": "HPBW E", "Theorique": f"{th['hpbw_e_deg']:.1f} deg", "Fabrique estime": f"{th['hpbw_e_deg'] * (1+fab['penalties']['total_loss_db']/12):.1f} deg", "Corrige estime": f"{th['hpbw_e_deg'] * (1+corr['penalties']['total_loss_db']/14):.1f} deg"},
    ]
    show_table(targets)

    st.subheader("2. Protocole recommande")
    show_table(measurement_protocol_rows(results))

    st.subheader("3. Diagrammes attendus")
    c1, c2 = st.columns(2)
    with c1:
        components.html(radiation_db_comparison_svg(results, "H"), height=300)
    with c2:
        components.html(radiation_db_comparison_svg(results, "E"), height=300)

    st.subheader("4. Lobe 3D illustratif")
    components.html(radiation_3d_lobe_svg(th['hpbw_h_deg'], th['hpbw_e_deg'], th['gain_dbi']), height=365)

    st.info("Pour la validation, l'ideal est de relever S11(f), Gain(f), ainsi que les coupes de rayonnement dans les plans H et E. Les courbes de cette page servent de reference experimentale indicative.")



def guide_efield_svg(params: AntennaParams) -> str:
    guide = WAVEGUIDES[params.guide_type]
    x0, y0, w, h = 50, 40, 320, 180
    arrows = []
    for i in range(1, 12):
        x = x0 + i * w / 12
        amp = math.sin(math.pi * i / 12)
        length = 20 + 55 * amp
        arrows.append(f"<line x1='{x:.1f}' y1='{y0+h/2-length/2:.1f}' x2='{x:.1f}' y2='{y0+h/2+length/2:.1f}' stroke='#2563eb' stroke-width='3' marker-start='url(#m)' marker-end='url(#m)'/>")
    return f"""
    <svg viewBox='0 0 430 260' width='100%' height='260' xmlns='http://www.w3.org/2000/svg'>
      <defs><marker id='m' markerWidth='8' markerHeight='8' refX='4' refY='4' orient='auto'><path d='M0,0 L8,4 L0,8 z' fill='#2563eb'/></marker></defs>
      <rect x='1' y='1' width='428' height='258' rx='12' fill='#fbfcfe' stroke='#d9dee7'/>
      <rect x='{x0}' y='{y0}' width='{w}' height='{h}' fill='#f8fafc' stroke='#1f2937' stroke-width='2'/>
      {''.join(arrows)}
      <text x='18' y='24' font-size='16' font-weight='bold'>Champ electrique E dans le guide (mode TE10)</text>
      <text x='18' y='44' font-size='13' fill='#475569'>Distribution transverse qualitative - maximum au centre, nulle aux parois laterales</text>
      <text x='{x0+w/2}' y='{y0+h+20}' text-anchor='middle' font-size='13'>Dimension a = {guide.a_mm:.1f} mm</text>
      <text x='{x0+w+8}' y='{y0+h/2}' font-size='13'>b = {guide.b_mm:.1f} mm</text>
    </svg>
    """


def guide_hfield_svg(params: AntennaParams) -> str:
    guide = WAVEGUIDES[params.guide_type]
    x0, y0, w, h = 50, 40, 320, 180
    curves = []
    for j in range(1, 5):
        y = y0 + j * h / 5
        curves.append(f"<path d='M {x0+25},{y:.1f} C {x0+120},{y-18:.1f} {x0+200},{y+18:.1f} {x0+w-25},{y:.1f}' fill='none' stroke='#059669' stroke-width='3' marker-end='url(#n)'/>")
        curves.append(f"<path d='M {x0+w-25},{y+8:.1f} C {x0+210},{y+26:.1f} {x0+110},{y-10:.1f} {x0+25},{y+8:.1f}' fill='none' stroke='#10b981' stroke-width='2' opacity='0.55'/>")
    return f"""
    <svg viewBox='0 0 430 260' width='100%' height='260' xmlns='http://www.w3.org/2000/svg'>
      <defs><marker id='n' markerWidth='8' markerHeight='8' refX='4' refY='4' orient='auto'><path d='M0,0 L8,4 L0,8 z' fill='#059669'/></marker></defs>
      <rect x='1' y='1' width='428' height='258' rx='12' fill='#fbfcfe' stroke='#d9dee7'/>
      <rect x='{x0}' y='{y0}' width='{w}' height='{h}' fill='#f8fafc' stroke='#1f2937' stroke-width='2'/>
      {''.join(curves)}
      <text x='18' y='24' font-size='16' font-weight='bold'>Champ magnetique H dans le guide (mode TE10)</text>
      <text x='18' y='44' font-size='13' fill='#475569'>Lignes de champ qualitatives associees au mode dominant</text>
      <text x='{x0+w/2}' y='{y0+h+20}' text-anchor='middle' font-size='13'>Circulation du champ H et courants de surface associes</text>
    </svg>
    """


def horn_efield_hfield_svg(params: AntennaParams, results: dict) -> str:
    hp = results["fabricated"]["hpem"]
    e_peak = hp["e_peak_throat_kv_per_m"]
    a = 60
    b = 40
    c = 330
    d = 210
    arrows = []
    for i in range(6):
        x = 95 + i * 42
        l = 20 + i * 6
        arrows.append(f"<line x1='{x}' y1='{130-l/2}' x2='{x}' y2='{130+l/2}' stroke='#2563eb' stroke-width='3' marker-start='url(#m)' marker-end='url(#m)'/>")
    loops = []
    for i in range(4):
        y = 90 + i * 25
        loops.append(f"<path d='M 110,{y} C 175,{y-18} 240,{y+18} 305,{y}' fill='none' stroke='#059669' stroke-width='2.5' marker-end='url(#n)'/>")
    return f"""
    <svg viewBox='0 0 400 260' width='100%' height='260' xmlns='http://www.w3.org/2000/svg'>
      <defs>
        <marker id='m' markerWidth='8' markerHeight='8' refX='4' refY='4' orient='auto'><path d='M0,0 L8,4 L0,8 z' fill='#2563eb'/></marker>
        <marker id='n' markerWidth='8' markerHeight='8' refX='4' refY='4' orient='auto'><path d='M0,0 L8,4 L0,8 z' fill='#059669'/></marker>
      </defs>
      <rect x='1' y='1' width='398' height='258' rx='12' fill='#fbfcfe' stroke='#d9dee7'/>
      <polygon points='{a},110 {b},130 {a},150 {c},195 {d},65 {a},110' fill='#f8fafc' stroke='#334155' stroke-width='2'/>
      {''.join(arrows)}
      {''.join(loops)}
      <text x='18' y='24' font-size='16' font-weight='bold'>Evolution qualitative des champs dans le cornet</text>
      <text x='18' y='44' font-size='13' fill='#475569'>E en bleu, H en vert, expansion de la gorge vers l'ouverture</text>
      <text x='18' y='225' font-size='13'>Champ crete estime a la gorge: {e_peak:.0f} kV/m</text>
    </svg>
    """


def comparison_chart_svg(results: dict) -> str:
    rows = results["comparison"]
    gains = [r["Gain dBi"] for r in rows]
    s11s = [abs(r["S11 dB"]) for r in rows]
    scores = [r["Score HPEM %"] for r in rows]
    gmax = max(gains + [1.0])
    smax = max(s11s + [1.0])
    h = 260
    y0 = 215
    groups = []
    colors = ["#2563eb", "#059669", "#f59e0b"]
    labels = ["Gain", "|S11|", "Score"]
    x_start = [70, 205, 340]
    metrics = [gains, s11s, scores]
    maxes = [gmax, smax, 100.0]
    for gi in range(3):
        x = x_start[gi]
        for i, val in enumerate(metrics[gi]):
            bh = 130 * (val / maxes[gi] if maxes[gi] else 0)
            bx = x + i * 28
            by = y0 - bh
            groups.append(f"<rect x='{bx}' y='{by:.1f}' width='18' height='{bh:.1f}' fill='{colors[i]}' rx='3'/>")
            groups.append(f"<text x='{bx+9}' y='{by-6:.1f}' text-anchor='middle' font-size='11'>{val:.1f}</text>")
        groups.append(f"<text x='{x+28}' y='{y0+24}' text-anchor='middle' font-size='13' font-weight='bold'>{labels[gi]}</text>")
    legend = []
    for i, row in enumerate(rows):
        legend.append(f"<rect x='{40 + i*120}' y='24' width='14' height='14' fill='{colors[i]}' rx='2'/><text x='{60 + i*120}' y='36' font-size='12'>{html.escape(row['Cas'])}</text>")
    return f"""
    <svg viewBox='0 0 470 270' width='100%' height='270' xmlns='http://www.w3.org/2000/svg'>
      <rect x='1' y='1' width='468' height='268' rx='12' fill='#fbfcfe' stroke='#d9dee7'/>
      <line x1='45' y1='{y0}' x2='430' y2='{y0}' stroke='#64748b'/>
      {''.join(groups)}
      {''.join(legend)}
      <text x='20' y='255' font-size='12' fill='#64748b'>Comparaison theorique / fabrique / corrige</text>
    </svg>
    """



def color_lerp(c1: str, c2: str, t: float) -> str:
    t = max(0.0, min(1.0, t))
    a = tuple(int(c1[i:i+2], 16) for i in (1, 3, 5))
    b = tuple(int(c2[i:i+2], 16) for i in (1, 3, 5))
    out = tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
    return "#%02x%02x%02x" % out


def field_color(value: float) -> str:
    value = max(0.0, min(1.0, value))
    if value < 0.5:
        return color_lerp("#eff6ff", "#60a5fa", value / 0.5)
    return color_lerp("#60a5fa", "#ef4444", (value - 0.5) / 0.5)


def frequency_response_data(results: dict, n: int = 61) -> dict:
    p = results["params"]
    th = results["theoretical"]
    fab = results["fabricated"]
    corr = results["corrected"]
    fmin = float(p["f_min_ghz"])
    fmax = float(p["f_max_ghz"])
    fc = float(p["f_center_ghz"])
    if fmax <= fmin:
        fmin = max(0.1, fc - 0.1)
        fmax = fc + 0.1
    area = float(th["aperture_area_m2"])
    eta = float(p["aperture_efficiency"])
    fab_loss = float(fab["penalties"]["total_loss_db"])
    corr_loss = float(corr["penalties"]["total_loss_db"])
    base_s11 = float(th["base_s11_db"])
    fab_s11_c = float(fab["penalties"]["s11_db"])
    corr_s11_c = float(corr["penalties"]["s11_db"])
    hp_score = float(fab["hpem"]["score_hpem"])
    corr_score = float(corr["hpem"]["score_hpem"])
    xs = []
    g_th = []
    g_fab = []
    g_corr = []
    s_th = []
    s_fab = []
    s_corr = []
    score_fab = []
    score_corr = []
    span = max(fmax - fmin, 1e-6)
    for i in range(n):
        f = fmin + (fmax - fmin) * i / max(n - 1, 1)
        lam = 299792458.0 / (f * 1e9)
        gain_lin = max(eta, 0.01) * 4.0 * math.pi * max(area, 1e-12) / (lam ** 2)
        gain_db = 10.0 * math.log10(max(gain_lin, 1e-12))
        detune = abs(f - fc) / (span / 2.0)
        xs.append(f)
        g_th.append(gain_db)
        g_fab.append(gain_db - fab_loss - 0.20 * detune)
        g_corr.append(gain_db - corr_loss - 0.10 * detune)
        s_th.append(base_s11 + 9.0 * detune ** 2)
        s_fab.append(fab_s11_c + 10.5 * detune ** 2)
        s_corr.append(corr_s11_c + 8.0 * detune ** 2)
        score_fab.append(max(0.0, min(100.0, hp_score - 7.0 * detune ** 1.2)))
        score_corr.append(max(0.0, min(100.0, corr_score - 4.0 * detune ** 1.1)))
    return {
        "f": xs,
        "gain_theorique": g_th,
        "gain_fabrique": g_fab,
        "gain_corrige": g_corr,
        "s11_theorique": s_th,
        "s11_fabrique": s_fab,
        "s11_corrige": s_corr,
        "score_fabrique": score_fab,
        "score_corrige": score_corr,
    }


def svg_polyline(xs: list[float], ys: list[float], xmin: float, xmax: float, ymin: float, ymax: float, left: float, top: float, width: float, height: float) -> str:
    pts = []
    for x, y in zip(xs, ys):
        px = left + (x - xmin) / max(xmax - xmin, 1e-9) * width
        py = top + (ymax - y) / max(ymax - ymin, 1e-9) * height
        pts.append(f"{px:.1f},{py:.1f}")
    return " ".join(pts)


def multi_curve_svg(title: str, x_label: str, y_label: str, xs: list[float], series: list[tuple[str, list[float], str]], unit: str = "") -> str:
    width = 760
    height = 360
    left, right, top, bottom = 72, 28, 56, 58
    plot_w = width - left - right
    plot_h = height - top - bottom
    xmin, xmax = min(xs), max(xs)
    all_y = [v for _, vals, _ in series for v in vals]
    ymin, ymax = min(all_y), max(all_y)
    pad = max((ymax - ymin) * 0.12, 0.5)
    ymin -= pad
    ymax += pad
    grid = []
    for k in range(5):
        y = top + plot_h * k / 4
        val = ymax - (ymax - ymin) * k / 4
        grid.append(f"<line x1='{left}' y1='{y:.1f}' x2='{left+plot_w}' y2='{y:.1f}' stroke='#e2e8f0'/><text x='12' y='{y+4:.1f}' font-size='12' fill='#475569'>{val:.1f}</text>")
    for k in range(6):
        x = left + plot_w * k / 5
        val = xmin + (xmax - xmin) * k / 5
        grid.append(f"<line x1='{x:.1f}' y1='{top}' x2='{x:.1f}' y2='{top+plot_h}' stroke='#f1f5f9'/><text x='{x:.1f}' y='{top+plot_h+20}' text-anchor='middle' font-size='12' fill='#475569'>{val:.2f}</text>")
    curves = []
    legend = []
    for i, (name, vals, color) in enumerate(series):
        pts = svg_polyline(xs, vals, xmin, xmax, ymin, ymax, left, top, plot_w, plot_h)
        curves.append(f"<polyline points='{pts}' fill='none' stroke='{color}' stroke-width='3'/>")
        legend.append(f"<rect x='{left + i*170}' y='28' width='14' height='14' fill='{color}' rx='2'/><text x='{left + i*170 + 20}' y='40' font-size='13'>{html.escape(name)}</text>")
    return f"""
    <svg viewBox='0 0 {width} {height}' width='100%' height='{height}' xmlns='http://www.w3.org/2000/svg'>
      <rect x='1' y='1' width='{width-2}' height='{height-2}' rx='14' fill='#fbfcfe' stroke='#d9dee7'/>
      <text x='22' y='25' font-size='18' font-weight='bold'>{html.escape(title)}</text>
      {''.join(legend)}
      {''.join(grid)}
      <rect x='{left}' y='{top}' width='{plot_w}' height='{plot_h}' fill='none' stroke='#94a3b8'/>
      {''.join(curves)}
      <text x='{left + plot_w/2}' y='{height-18}' text-anchor='middle' font-size='14'>{html.escape(x_label)}</text>
      <text x='18' y='{top + plot_h/2}' transform='rotate(-90 18,{top + plot_h/2})' text-anchor='middle' font-size='14'>{html.escape(y_label)} {html.escape(unit)}</text>
    </svg>
    """


def efield_heatmap_svg(params: AntennaParams) -> str:
    guide = WAVEGUIDES[params.guide_type]
    cols, rows = 24, 12
    x0, y0, cw, ch = 50, 55, 12, 12
    rects = []
    for j in range(rows):
        for i in range(cols):
            xnorm = (i + 0.5) / cols
            ynorm = abs((j + 0.5) / rows - 0.5)
            val = max(0.0, math.sin(math.pi * xnorm)) * (1.0 - 0.12 * ynorm)
            rects.append(f"<rect x='{x0+i*cw}' y='{y0+j*ch}' width='{cw+0.5}' height='{ch+0.5}' fill='{field_color(val)}'/>")
    return f"""
    <svg viewBox='0 0 420 260' width='100%' height='260' xmlns='http://www.w3.org/2000/svg'>
      <rect x='1' y='1' width='418' height='258' rx='12' fill='#fbfcfe' stroke='#d9dee7'/>
      <text x='18' y='26' font-size='16' font-weight='bold'>Carte qualitative |E| - guide {guide.name}</text>
      <text x='18' y='45' font-size='13' fill='#475569'>Mode TE10: maximum au centre selon la dimension a</text>
      <rect x='{x0}' y='{y0}' width='{cols*cw}' height='{rows*ch}' fill='none' stroke='#111827' stroke-width='2'/>
      {''.join(rects)}
      <rect x='{x0}' y='{y0}' width='{cols*cw}' height='{rows*ch}' fill='none' stroke='#111827' stroke-width='2'/>
      <text x='{x0+cols*cw/2}' y='{y0+rows*ch+22}' text-anchor='middle' font-size='13'>a = {guide.a_mm:.1f} mm</text>
      <text x='{x0+cols*cw+12}' y='{y0+rows*ch/2}' font-size='13'>b = {guide.b_mm:.1f} mm</text>
      <text x='62' y='232' font-size='12' fill='#64748b'>bleu: faible</text><text x='260' y='232' font-size='12' fill='#64748b'>rouge: fort</text>
    </svg>
    """


def hfield_heatmap_svg(params: AntennaParams) -> str:
    guide = WAVEGUIDES[params.guide_type]
    cols, rows = 24, 12
    x0, y0, cw, ch = 50, 55, 12, 12
    rects = []
    for j in range(rows):
        for i in range(cols):
            xnorm = (i + 0.5) / cols
            ynorm = (j + 0.5) / rows
            val = 0.25 + 0.45 * abs(math.cos(math.pi * xnorm)) + 0.20 * abs(ynorm - 0.5)
            rects.append(f"<rect x='{x0+i*cw}' y='{y0+j*ch}' width='{cw+0.5}' height='{ch+0.5}' fill='{field_color(min(val,1.0))}'/>")
    arrows = []
    for k in range(4):
        y = y0 + 25 + k * 25
        arrows.append(f"<path d='M {x0+25},{y} C {x0+95},{y-20} {x0+185},{y+20} {x0+260},{y}' fill='none' stroke='#064e3b' stroke-width='2' marker-end='url(#ha)'/>")
    return f"""
    <svg viewBox='0 0 420 260' width='100%' height='260' xmlns='http://www.w3.org/2000/svg'>
      <defs><marker id='ha' markerWidth='8' markerHeight='8' refX='4' refY='4' orient='auto'><path d='M0,0 L8,4 L0,8 z' fill='#064e3b'/></marker></defs>
      <rect x='1' y='1' width='418' height='258' rx='12' fill='#fbfcfe' stroke='#d9dee7'/>
      <text x='18' y='26' font-size='16' font-weight='bold'>Carte qualitative |H| - guide {guide.name}</text>
      <text x='18' y='45' font-size='13' fill='#475569'>Champ H et courants de surface associes</text>
      <rect x='{x0}' y='{y0}' width='{cols*cw}' height='{rows*ch}' fill='none' stroke='#111827' stroke-width='2'/>
      {''.join(rects)}{''.join(arrows)}
      <rect x='{x0}' y='{y0}' width='{cols*cw}' height='{rows*ch}' fill='none' stroke='#111827' stroke-width='2'/>
      <text x='{x0+cols*cw/2}' y='{y0+rows*ch+22}' text-anchor='middle' font-size='13'>distribution qualitative du mode dominant</text>
    </svg>
    """


def aperture_heatmap_svg(params: AntennaParams, results: dict) -> str:
    cols, rows = 28, 16
    x0, y0, cw, ch = 45, 52, 11, 10
    defect = results["fabricated"]["hpem"]["concentration_factor"]
    rects = []
    for j in range(rows):
        for i in range(cols):
            xn = abs((i + 0.5) / cols - 0.5) * 2
            yn = abs((j + 0.5) / rows - 0.5) * 2
            taper = max(0.0, 1.0 - 0.35 * xn * xn - 0.25 * yn * yn)
            edge = 0.18 if i in (0, cols-1) or j in (0, rows-1) else 0.0
            val = min(1.0, taper * 0.75 + edge * min(defect, 1.7))
            rects.append(f"<rect x='{x0+i*cw}' y='{y0+j*ch}' width='{cw+0.5}' height='{ch+0.5}' fill='{field_color(val)}'/>")
    return f"""
    <svg viewBox='0 0 420 260' width='100%' height='260' xmlns='http://www.w3.org/2000/svg'>
      <rect x='1' y='1' width='418' height='258' rx='12' fill='#fbfcfe' stroke='#d9dee7'/>
      <text x='18' y='26' font-size='16' font-weight='bold'>Carte qualitative du champ a l'ouverture</text>
      <text x='18' y='45' font-size='13' fill='#475569'>Taper d'ouverture et concentration aux aretes</text>
      <rect x='{x0}' y='{y0}' width='{cols*cw}' height='{rows*ch}' fill='none' stroke='#111827' stroke-width='2'/>
      {''.join(rects)}
      <rect x='{x0}' y='{y0}' width='{cols*cw}' height='{rows*ch}' fill='none' stroke='#111827' stroke-width='2'/>
      <text x='{x0+cols*cw/2}' y='{y0+rows*ch+22}' text-anchor='middle' font-size='13'>A x B = {params.aperture_width_mm:.0f} x {params.aperture_height_mm:.0f} mm</text>
    </svg>
    """


def cst_like_horn_map_svg(params: AntennaParams, results: dict) -> str:
    x0, y0 = 30, 50
    body = []
    for k in range(17):
        t = k / 16
        x = x0 + 20 + t * 310
        top = y0 + 90 - t * 58
        bottom = y0 + 110 + t * 58
        width = 14
        local = 1.0 - 0.55 * t
        edge_boost = 0.20 * results["fabricated"]["hpem"]["concentration_factor"] if k > 13 else 0.0
        val = min(1.0, local + edge_boost)
        body.append(f"<polygon points='{x},{top} {x+width},{top+3} {x+width},{bottom-3} {x},{bottom}' fill='{field_color(val)}' opacity='0.92'/>")
    labels = f"""
      <circle cx='82' cy='151' r='6' fill='#ef4444'/><text x='95' y='156' font-size='12'>transition guide-cornet</text>
      <circle cx='305' cy='62' r='6' fill='#f97316'/><text x='318' y='66' font-size='12'>aretes d'ouverture</text>
      <circle cx='190' cy='190' r='6' fill='#f59e0b'/><text x='203' y='195' font-size='12'>soudures internes</text>
    """
    return f"""
    <svg viewBox='0 0 460 280' width='100%' height='280' xmlns='http://www.w3.org/2000/svg'>
      <rect x='1' y='1' width='458' height='278' rx='12' fill='#fbfcfe' stroke='#d9dee7'/>
      <text x='18' y='26' font-size='16' font-weight='bold'>Carte CST-like qualitative dans le cornet</text>
      <text x='18' y='45' font-size='13' fill='#475569'>Evolution de |E| et zones critiques HPEM</text>
      <polygon points='55,140 55,160 365,235 365,65' fill='#f8fafc' stroke='#334155' stroke-width='2'/>
      {''.join(body)}
      <polygon points='55,140 55,160 365,235 365,65' fill='none' stroke='#334155' stroke-width='2'/>
      {labels}
      <text x='24' y='255' font-size='12' fill='#64748b'>Carte illustrative: elle sert a interpreter les resultats et ne remplace pas CST/HFSS.</text>
    </svg>
    """


def memory_text_block(results: dict) -> str:
    p = results["params"]
    th = results["theoretical"]
    fab = results["fabricated"]
    return (
        "L'outil developpe permet de relier les dimensions geometriques du cornet, "
        "les imperfections de fabrication et les indicateurs RF obtenus par calcul parametrique. "
        f"Pour le guide {p['guide_type']} et une frequence centrale de {p['f_center_ghz']:.2f} GHz, "
        f"le gain theorique est estime a {th['gain_dbi']:.2f} dBi, tandis que le gain fabrique est estime a {fab['gain_dbi']:.2f} dBi. "
        "Les cartes qualitatives des champs E et H mettent en evidence les zones sensibles: gorge, transition guide-cornet, soudures internes et aretes de l'ouverture. "
        "Ces zones sont critiques dans un contexte HPEM car elles peuvent provoquer des concentrations locales du champ, des pertes supplementaires et une degradation de la tenue en puissance."
    )

def mode_band_explanation(guide_name: str) -> str:
    guide = WAVEGUIDES[guide_name]
    return (
        f"Pour {guide.name}, la plage recommandee est {guide.recommended_min_ghz:.2f}-{guide.recommended_max_ghz:.2f} GHz. "
        f"Dimensions internes: a = {guide.a_mm:.2f} mm, b = {guide.b_mm:.2f} mm. "
        f"Coupure TE10: {guide.fc_te10_ghz:.3f} GHz ; premier mode superieur: {guide.upper_mode_ghz:.3f} GHz. "
        "La bande saisie doit rester au-dessus de la coupure TE10 et sous le premier mode superieur pour garantir une propagation TE10 dominante."
    )


def conformity_assessment(results: dict) -> tuple[str, str, list[dict]]:
    p = results["params"]
    th = results["theoretical"]
    fab = results["fabricated"]
    guide = WAVEGUIDES[p["guide_type"]]
    selected_auto, _ = auto_select_waveguide(p["f_center_ghz"], p["f_min_ghz"], p["f_max_ghz"])

    def ok_text(cond: bool) -> str:
        return "Conforme" if cond else "A verifier"

    band_ok = guide.recommended_min_ghz <= p["f_min_ghz"] and p["f_max_ghz"] <= guide.recommended_max_ghz
    te10_ok = p["f_min_ghz"] > guide.fc_te10_ghz and p["f_max_ghz"] < guide.upper_mode_ghz
    center_ok = guide.recommended_min_ghz <= p["f_center_ghz"] <= guide.recommended_max_ghz
    recommended_ok = selected_auto == p["guide_type"]
    s11_ok = fab["penalties"]["s11_db"] <= -10.0
    hpem_ok = fab["hpem"]["score_hpem"] >= 70.0
    defects_ok = fab["penalties"]["total_loss_db"] <= 2.0

    rows = [
        {"Critere": "Guide choisi", "Etat": ok_text(recommended_ok), "Constat": f"Guide selectionne: {p['guide_type']} ; guide conseille par l'application: {selected_auto}."},
        {"Critere": "Bande recommandee", "Etat": ok_text(band_ok), "Constat": f"Bande saisie {p['f_min_ghz']:.2f}-{p['f_max_ghz']:.2f} GHz ; plage {guide.name}: {guide.recommended_min_ghz:.2f}-{guide.recommended_max_ghz:.2f} GHz."},
        {"Critere": "Mode dominant TE10", "Etat": ok_text(te10_ok), "Constat": f"fc(TE10) = {guide.fc_te10_ghz:.3f} GHz ; premier mode superieur = {guide.upper_mode_ghz:.3f} GHz."},
        {"Critere": "Frequence centrale", "Etat": ok_text(center_ok), "Constat": f"f0 = {p['f_center_ghz']:.2f} GHz dans la plage recommandee du guide."},
        {"Critere": "Adaptation S11", "Etat": ok_text(s11_ok), "Constat": f"S11 estime fabrique = {fab['penalties']['s11_db']:.1f} dB."},
        {"Critere": "Tenue HPEM", "Etat": ok_text(hpem_ok), "Constat": f"Score HPEM = {fab['hpem']['score_hpem']:.0f} %, risque = {fab['hpem']['breakdown_risk']}."},
        {"Critere": "Defauts de fabrication", "Etat": ok_text(defects_ok), "Constat": f"Pertes de fabrication estimees = {fab['penalties']['total_loss_db']:.2f} dB."},
    ]

    critical_ok = band_ok and te10_ok and center_ok
    practical_ok = s11_ok and hpem_ok and defects_ok
    if critical_ok and practical_ok:
        verdict = "Conforme"
        color = "#059669"
    elif critical_ok:
        verdict = "Conforme avec reserves"
        color = "#f59e0b"
    else:
        verdict = "Non conforme / a corriger"
        color = "#dc2626"
    return verdict, color, rows


def conformity_card_html(results: dict) -> str:
    verdict, color, rows = conformity_assessment(results)
    items = "".join(
        f"<div style='display:flex;gap:8px;align-items:flex-start;margin:6px 0'>"
        f"<span style='min-width:82px;font-weight:700;color:{'#059669' if r['Etat']=='Conforme' else '#dc2626'}'>{html.escape(r['Etat'])}</span>"
        f"<span><b>{html.escape(r['Critere'])}</b> - {html.escape(r['Constat'])}</span></div>"
        for r in rows
    )
    return f"""
    <div style='border:1px solid #e2e8f0;border-left:6px solid {color};border-radius:16px;padding:16px 18px;background:#ffffff;margin:8px 0 14px 0;box-shadow:0 8px 20px rgba(15,23,42,.05)'>
      <div style='font-size:22px;font-weight:800;color:{color};margin-bottom:6px'>Constat de conformité : {html.escape(verdict)}</div>
      <div style='font-size:14px;color:#475569;margin-bottom:8px'>Synthèse automatique basée sur le guide, la bande, le mode TE10, l'adaptation, les défauts et le score HPEM.</div>
      {items}
    </div>
    """




def readiness_score(results: dict) -> float:
    th = results["theoretical"]
    fab = results["fabricated"]
    gain_retention = max(0.0, min(100.0, 100.0 * fab["gain_dbi"] / max(th["gain_dbi"], 0.1)))
    s11 = fab["penalties"]["s11_db"]
    s11_score = max(0.0, min(100.0, (abs(s11) - 6.0) / 18.0 * 100.0))
    hpem_score = max(0.0, min(100.0, fab["hpem"]["score_hpem"]))
    mode_score = 100.0 if th["mode_status"] == "TE10 dominant valide" else 65.0
    return 0.30 * gain_retention + 0.25 * s11_score + 0.30 * hpem_score + 0.15 * mode_score


def dashboard_hero_html(results: dict) -> str:
    p = results["params"]
    th = results["theoretical"]
    fab = results["fabricated"]
    corr = results["corrected"]
    hp = fab["hpem"]
    score = readiness_score(results)
    if score >= 85:
        verdict = "Prototype proche de l'etat optimal"
        color = "#059669"
    elif score >= 70:
        verdict = "Prototype utilisable avec corrections recommandees"
        color = "#f59e0b"
    else:
        verdict = "Prototype a corriger avant validation forte puissance"
        color = "#dc2626"
    delta_gain = corr["gain_dbi"] - fab["gain_dbi"]
    delta_s11 = corr["penalties"]["s11_db"] - fab["penalties"]["s11_db"]
    return f"""
    <div style='border:1px solid #d8dee9;border-radius:18px;padding:18px 20px;background:linear-gradient(135deg,#f8fbff,#eef6ff);margin-bottom:12px'>
      <div style='display:flex;align-items:center;gap:18px;justify-content:space-between;flex-wrap:wrap'>
        <div>
          <div style='font-size:28px;font-weight:800;color:#0f172a;margin-bottom:4px'>Dashboard complet - antenne cornet HPEM</div>
          <div style='font-size:14px;color:#475569'>Guide {p['guide_type']} · {p['f_min_ghz']:.2f}-{p['f_max_ghz']:.2f} GHz · f0 = {p['f_center_ghz']:.2f} GHz · mode: {html.escape(th['mode_status'])}</div>
        </div>
        <div style='min-width:230px;background:white;border:1px solid #dbe4f0;border-radius:15px;padding:13px 16px;box-shadow:0 8px 22px rgba(15,23,42,.06)'>
          <div style='font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.06em'>Indice global</div>
          <div style='font-size:34px;font-weight:800;color:{color}'>{score:.0f}%</div>
          <div style='font-size:13px;color:#334155'>{html.escape(verdict)}</div>
        </div>
      </div>
      <div style='display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:12px;margin-top:18px'>
        <div style='background:white;border-radius:13px;padding:12px;border:1px solid #e2e8f0'><div style='font-size:12px;color:#64748b'>Gain fabrique</div><div style='font-size:22px;font-weight:800;color:#0f172a'>{fab['gain_dbi']:.2f} dBi</div><div style='font-size:12px;color:#059669'>Correction estimée +{delta_gain:.2f} dB</div></div>
        <div style='background:white;border-radius:13px;padding:12px;border:1px solid #e2e8f0'><div style='font-size:12px;color:#64748b'>S11 fabrique</div><div style='font-size:22px;font-weight:800;color:#0f172a'>{fab['penalties']['s11_db']:.1f} dB</div><div style='font-size:12px;color:#059669'>Apres finition {corr['penalties']['s11_db']:.1f} dB</div></div>
        <div style='background:white;border-radius:13px;padding:12px;border:1px solid #e2e8f0'><div style='font-size:12px;color:#64748b'>Score HPEM</div><div style='font-size:22px;font-weight:800;color:#0f172a'>{hp['score_hpem']:.0f}%</div><div style='font-size:12px;color:#475569'>Risque: {html.escape(hp['breakdown_risk'])}</div></div>
        <div style='background:white;border-radius:13px;padding:12px;border:1px solid #e2e8f0'><div style='font-size:12px;color:#64748b'>Rayonnement</div><div style='font-size:22px;font-weight:800;color:#0f172a'>{th['hpbw_h_deg']:.1f}° / {th['hpbw_e_deg']:.1f}°</div><div style='font-size:12px;color:#475569'>Plans H / E</div></div>
      </div>
    </div>
    """


def readiness_radar_svg(results: dict) -> str:
    th = results["theoretical"]
    fab = results["fabricated"]
    hp = fab["hpem"]
    gain_score = max(0.0, min(100.0, 100.0 * fab["gain_dbi"] / max(th["gain_dbi"], 0.1)))
    s11_score = max(0.0, min(100.0, (abs(fab["penalties"]["s11_db"]) - 6.0) / 18.0 * 100.0))
    hpem_score = max(0.0, min(100.0, hp["score_hpem"]))
    defect_score = max(0.0, min(100.0, 100.0 - 22.0 * fab["penalties"]["total_loss_db"]))
    mode_score = 100.0 if th["mode_status"] == "TE10 dominant valide" else 65.0
    values = [("Gain", gain_score), ("S11", s11_score), ("HPEM", hpem_score), ("Defauts", defect_score), ("Mode", mode_score)]
    cx, cy = 210, 145
    rmax = 86
    grid = []
    for r in [0.25, 0.5, 0.75, 1.0]:
        pts = []
        for i in range(len(values)):
            a = -90 + 360 * i / len(values)
            x = cx + rmax * r * math.cos(math.radians(a))
            y = cy + rmax * r * math.sin(math.radians(a))
            pts.append(f"{x:.1f},{y:.1f}")
        grid.append(f"<polygon points='{' '.join(pts)}' fill='none' stroke='#e2e8f0' stroke-width='1'/>")
    pts = []
    labels = []
    for i, (name, val) in enumerate(values):
        a = -90 + 360 * i / len(values)
        x = cx + rmax * (val/100.0) * math.cos(math.radians(a))
        y = cy + rmax * (val/100.0) * math.sin(math.radians(a))
        pts.append(f"{x:.1f},{y:.1f}")
        lx = cx + (rmax+28) * math.cos(math.radians(a))
        ly = cy + (rmax+28) * math.sin(math.radians(a))
        labels.append(f"<text x='{lx:.1f}' y='{ly:.1f}' text-anchor='middle' font-size='12' fill='#334155'>{name}</text><text x='{lx:.1f}' y='{ly+14:.1f}' text-anchor='middle' font-size='11' fill='#64748b'>{val:.0f}%</text>")
    return f"""
    <svg viewBox='0 0 420 300' width='100%' height='300' xmlns='http://www.w3.org/2000/svg'>
      <rect x='1' y='1' width='418' height='298' rx='14' fill='#fbfcfe' stroke='#d9dee7'/>
      <text x='18' y='26' font-size='17' font-weight='bold'>Radar de maturite technique</text>
      <text x='18' y='46' font-size='12' fill='#64748b'>Lecture rapide des criteres RF, fabrication et HPEM</text>
      {''.join(grid)}
      <polygon points='{' '.join(pts)}' fill='rgba(37,99,235,.18)' stroke='#2563eb' stroke-width='3'/>
      {''.join(labels)}
    </svg>
    """


def defect_pareto_svg(results: dict) -> str:
    pen = results["fabricated"]["penalties"]
    items = [
        ("Rugosite", pen["roughness_loss_db"]),
        ("Soudures", pen["weld_loss_db"]),
        ("Tolérance", pen["dimensional_loss_db"]),
        ("Alignement", pen["alignment_loss_db"]),
        ("Oxydation", pen["oxidation_loss_db"]),
        ("Mastic", pen["mastic_loss_db"]),
    ]
    items.sort(key=lambda x: x[1], reverse=True)
    vmax = max([v for _, v in items] + [1.0])
    bars = []
    for i, (name, val) in enumerate(items):
        y = 66 + i * 30
        w = 270 * val / vmax
        color = '#dc2626' if i == 0 and val > 0.35 else '#f59e0b' if val > 0.2 else '#2563eb'
        bars.append(f"<text x='22' y='{y+14}' font-size='12' fill='#334155'>{html.escape(name)}</text><rect x='110' y='{y}' width='270' height='18' rx='5' fill='#e2e8f0'/><rect x='110' y='{y}' width='{w:.1f}' height='18' rx='5' fill='{color}'/><text x='{116+w:.1f}' y='{y+14}' font-size='12' fill='#0f172a'>{val:.2f} dB</text>")
    return f"""
    <svg viewBox='0 0 420 270' width='100%' height='270' xmlns='http://www.w3.org/2000/svg'>
      <rect x='1' y='1' width='418' height='268' rx='14' fill='#fbfcfe' stroke='#d9dee7'/>
      <text x='18' y='26' font-size='17' font-weight='bold'>Pareto des pertes de fabrication</text>
      <text x='18' y='46' font-size='12' fill='#64748b'>Prioriser les corrections mecaniques les plus efficaces</text>
      {''.join(bars)}
    </svg>
    """


def validation_checklist_html(results: dict) -> str:
    th = results["theoretical"]
    fab = results["fabricated"]
    s11_ok = fab["penalties"]["s11_db"] <= -15
    gain_ok = fab["gain_dbi"] >= th["gain_dbi"] - 1.5
    hpem_ok = fab["hpem"]["score_hpem"] >= 75
    mode_ok = th["mode_status"] == "TE10 dominant valide"
    items = [
        ("Mode TE10 valide", mode_ok),
        ("S11 cible ≤ -15 dB", s11_ok),
        ("Gain proche du theorique", gain_ok),
        ("Score HPEM acceptable", hpem_ok),
        ("Mesure VNA a prevoir", False),
        ("Diagramme de rayonnement a relever", False),
    ]
    cards = []
    for name, ok in items:
        symbol = "✓" if ok else "!"
        color = "#059669" if ok else "#f59e0b"
        bg = "#ecfdf5" if ok else "#fffbeb"
        cards.append(f"<div style='background:{bg};border:1px solid {color};border-radius:12px;padding:10px'><span style='display:inline-block;width:22px;height:22px;border-radius:50%;background:{color};color:white;text-align:center;font-weight:800;margin-right:8px'>{symbol}</span>{html.escape(name)}</div>")
    return f"""
    <div style='border:1px solid #d8dee9;border-radius:16px;padding:14px;background:#fbfcfe'>
      <div style='font-size:17px;font-weight:800;margin-bottom:10px;color:#0f172a'>Checklist de validation</div>
      <div style='display:grid;grid-template-columns:repeat(2,minmax(180px,1fr));gap:10px'>{''.join(cards)}</div>
    </div>
    """


def prototype_scores(results: dict) -> dict:
    th = results["theoretical"]
    fab = results["fabricated"]
    pen = fab["penalties"]
    defects = results["defects"]

    # Score RF: adaptation + gain proche du theorique + validite modale
    gain_gap = max(0.0, th["gain_dbi"] - fab["gain_dbi"])
    score_gain = clamp_score(100.0 - 18.0 * gain_gap)
    s11 = pen["s11_db"]
    score_s11 = clamp_score(100.0 if s11 <= -20 else 70.0 + max(0.0, (-15.0 - s11) * 2.0) if s11 <= -15 else max(20.0, 70.0 - (s11 + 15.0) * 7.0))
    score_mode = 100.0 if th["mode_status"] == "TE10 dominant valide" else 55.0
    score_rf = clamp_score(0.40 * score_gain + 0.40 * score_s11 + 0.20 * score_mode)

    # Score fabrication: moins de pertes, meilleure surface, moins d'alignement et de soudures
    score_surface = clamp_score(100.0 - 4.0 * max(0.0, defects.get("roughness_um", 0.0) - 1.0))
    score_weld = clamp_score(100.0 - 9.0 * defects.get("weld_count", 0.0))
    score_align = clamp_score(100.0 - 18.0 * defects.get("alignment_error_mm", 0.0))
    score_fabrication = clamp_score(0.35 * score_surface + 0.30 * score_weld + 0.25 * score_align + 0.10 * clamp_score(100 - pen["total_loss_db"] * 18))

    score_hpem = clamp_score(fab["hpem"]["score_hpem"])
    score_global = clamp_score(0.40 * score_rf + 0.40 * score_hpem + 0.20 * score_fabrication)

    # Indice de confiance du modele parametrique
    confidence = 88.0
    if th["mode_status"] != "TE10 dominant valide":
        confidence -= 18
    if pen["total_loss_db"] > 2.0:
        confidence -= 12
    if defects.get("roughness_um", 0.0) > 10:
        confidence -= 8
    if defects.get("alignment_error_mm", 0.0) > 2.0:
        confidence -= 8
    if results["params"]["f_max_ghz"] > th["upper_mode_ghz"] * 0.92:
        confidence -= 8
    confidence = clamp_score(confidence)

    return {
        "score_rf": score_rf,
        "score_hpem": score_hpem,
        "score_fabrication": score_fabrication,
        "score_global": score_global,
        "confidence": confidence,
        "score_gain": score_gain,
        "score_s11": score_s11,
        "score_mode": score_mode,
    }


def clamp_score(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def score_interpretation(score: float) -> str:
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Satisfaisant"
    if score >= 60:
        return "Corrections recommandees"
    return "Prototype a revoir"


def defect_ranking_rows(results: dict) -> list[dict]:
    pen = results["fabricated"]["penalties"]
    rows = [
        ("Rugosite interne", pen["roughness_loss_db"], "Polissage interne et controle de l'etat de surface"),
        ("Soudures", pen["weld_loss_db"], "Reduire les cordons internes ou privilegier le pliage"),
        ("Tolerance dimensionnelle", pen["dimensional_loss_db"], "Controle metrologique A, B, gorge et longueur"),
        ("Desalignement", pen["alignment_loss_db"], "Bride de centrage, gabarit, reprise d'assemblage"),
        ("Oxydation", pen["oxidation_loss_db"], "Nettoyage, protection compatible RF"),
        ("Mastic interne", pen["mastic_loss_db"], "Supprimer le dielectrique du volume RF"),
    ]
    rows.sort(key=lambda x: x[1], reverse=True)
    out=[]
    for i,(name,loss,action) in enumerate(rows, start=1):
        impact = "Fort" if loss >= 0.45 else "Moyen" if loss >= 0.15 else "Faible"
        out.append({"Priorite": i, "Defaut": name, "Impact": impact, "Perte estimee dB": round(loss,3), "Action recommandee": action})
    return out


def hpem_risk_matrix_rows(results: dict) -> list[dict]:
    defects = results["defects"]
    hp = results["fabricated"]["hpem"]
    pen = results["fabricated"]["penalties"]
    rows = [
        {"Zone": "Gorge / entree cornet", "Risque": "Eleve" if hp["breakdown_risk"] != "Faible" else "Moyen", "Cause": "Champ local intense, transition guide-cornet", "Action": "Polir, arrondir les aretes, verifier l'alignement"},
        {"Zone": "Soudures internes", "Risque": "Eleve" if defects.get("weld_count",0) >= 4 else "Moyen", "Cause": "Discontinuite des courants de surface", "Action": "Deplacer, reduire ou lisser les cordons"},
        {"Zone": "Aretes de l'ouverture", "Risque": "Moyen", "Cause": "Concentration locale et diffraction", "Action": "Ebavurer et arrondir legerement les bords"},
        {"Zone": "Parois internes", "Risque": "Eleve" if pen["roughness_ratio_skin_depth"] > 6 else "Moyen", "Cause": "Rugosite comparee a la profondeur de peau", "Action": "Poncer/polir dans le sens du courant RF"},
        {"Zone": "Zones oxydees", "Risque": "Moyen" if defects.get("oxidation_level",0) >= 2 else "Faible", "Cause": "Resistance de surface supplementaire", "Action": "Nettoyer et proteger la surface"},
    ]
    if defects.get("mastic_present"):
        rows.append({"Zone": "Mastic interne", "Risque": "Eleve", "Cause": "Perturbation dielectrique et echauffement", "Action": "Supprimer le mastic du volume RF"})
    return rows


def sensitivity_rows(results: dict) -> list[dict]:
    base_params = dict(results["params"])
    base_defects = dict(results["defects"])
    base_gain = results["fabricated"]["gain_dbi"]
    base_s11 = results["fabricated"]["penalties"]["s11_db"]
    base_score = results["fabricated"]["hpem"]["score_hpem"]

    scenarios = [
        ("Rugosite +2 um", {}, {"roughness_um": base_defects.get("roughness_um",0)+2.0}),
        ("Alignement +0.5 mm", {}, {"alignment_error_mm": base_defects.get("alignment_error_mm",0)+0.5}),
        ("Soudures +1", {}, {"weld_count": base_defects.get("weld_count",0)+1.0}),
        ("Tolerance +0.2 mm", {}, {"tolerance_mm": base_defects.get("tolerance_mm",0)+0.2}),
        ("Ouverture +5 %", {"aperture_width_mm": base_params["aperture_width_mm"]*1.05, "aperture_height_mm": base_params["aperture_height_mm"]*1.05}, {}),
        ("Longueur +10 %", {"horn_length_mm": base_params["horn_length_mm"]*1.10}, {}),
    ]
    rows=[]
    for label, pchg, dchg in scenarios:
        p2 = dict(base_params); p2.update(pchg)
        d2 = dict(base_defects); d2.update(dchg)
        try:
            sim = calculate_all(AntennaParams(**p2), FabricationDefects(**d2))
            rows.append({
                "Variation": label,
                "Delta gain dB": round(sim["fabricated"]["gain_dbi"] - base_gain, 3),
                "Delta S11 dB": round(sim["fabricated"]["penalties"]["s11_db"] - base_s11, 3),
                "Delta score HPEM": round(sim["fabricated"]["hpem"]["score_hpem"] - base_score, 2),
                "Lecture": "critique" if abs(sim["fabricated"]["hpem"]["score_hpem"] - base_score) > 4 or abs(sim["fabricated"]["gain_dbi"] - base_gain) > 0.4 else "moderee",
            })
        except Exception as exc:
            rows.append({"Variation": label, "Delta gain dB": "n/a", "Delta S11 dB": "n/a", "Delta score HPEM": "n/a", "Lecture": str(exc)[:40]})
    return rows


def vna_protocol_rows(results: dict) -> list[dict]:
    p = results["params"]
    return [
        {"Etape": 1, "Operation": "Calibrage du VNA", "Objectif": "Supprimer les erreurs cables/adaptateurs", "Critere": "Calibration valide sur toute la bande"},
        {"Etape": 2, "Operation": "Connexion guide-transition", "Objectif": "Eviter les jeux mecaniques", "Critere": "Bride serree, alignement verifie"},
        {"Etape": 3, "Operation": f"Balayage {p['f_min_ghz']:.2f}-{p['f_max_ghz']:.2f} GHz", "Objectif": "Mesurer S11(f)", "Critere": "Minimum S11 proche de la frequence cible"},
        {"Etape": 4, "Operation": "Export de la courbe", "Objectif": "Comparer mesure et modele", "Critere": "CSV ou capture du VNA"},
        {"Etape": 5, "Operation": "Mesure apres finition", "Objectif": "Quantifier poncage/polissage", "Critere": "Amelioration S11 et gain"},
    ]


def intelligent_conclusion(results: dict) -> str:
    scores = prototype_scores(results)
    fab = results["fabricated"]
    corr = results["corrected"]
    top_defect = defect_ranking_rows(results)[0]
    return (
        f"Le prototype presente un score global estime de {scores['score_global']:.0f} %, interprete comme: {score_interpretation(scores['score_global'])}. "
        f"Le gain fabrique est estime a {fab['gain_dbi']:.2f} dBi et peut atteindre {corr['gain_dbi']:.2f} dBi apres finition. "
        f"Le defaut prioritaire identifie est: {top_defect['Defaut']} ({top_defect['Perte estimee dB']} dB). "
        "Les actions les plus pertinentes sont donc le controle de la transition guide-cornet, la finition des surfaces internes, la verification de l'alignement et la validation par mesure VNA. "
        f"L'indice de confiance du modele est de {scores['confidence']:.0f} %, ce qui indique le niveau de prudence a conserver avant validation experimentale."
    )


def advanced_diagnostic_html(results: dict) -> str:
    s = prototype_scores(results)
    cards = []
    for title,key,color in [("Score global", "score_global", "#1d4ed8"),("RF", "score_rf", "#2563eb"),("HPEM", "score_hpem", "#059669"),("Fabrication", "score_fabrication", "#f59e0b"),("Confiance modele", "confidence", "#7c3aed")]:
        val=s[key]
        cards.append(f"<div style='background:white;border:1px solid #e2e8f0;border-radius:14px;padding:14px'><div style='font-size:13px;color:#64748b'>{html.escape(title)}</div><div style='font-size:28px;font-weight:900;color:{color}'>{val:.0f}%</div><div style='height:8px;background:#e5e7eb;border-radius:999px;overflow:hidden'><div style='height:8px;width:{val:.0f}%;background:{color}'></div></div></div>")
    return f"""
    <div style='padding:18px;border-radius:18px;background:#f8fafc;border:1px solid #d8dee9'>
      <div style='font-size:22px;font-weight:900;color:#0f172a;margin-bottom:12px'>Diagnostic avance du prototype</div>
      <div style='display:grid;grid-template-columns:repeat(5,minmax(120px,1fr));gap:12px'>{''.join(cards)}</div>
      <div style='margin-top:12px;font-size:13px;color:#475569'>Interpretation: {html.escape(score_interpretation(s['score_global']))}. Les scores sont parametriques et servent a orienter la validation experimentale.</div>
    </div>
    """


def page_advanced_analysis(results: dict) -> None:
    st.title("Analyse avancee")
    st.write("Cette page regroupe les fonctions qui transforment l'application en outil d'aide a la decision: sensibilite, score global, confiance, classement des defauts et matrice de risque HPEM.")
    components.html(advanced_diagnostic_html(results), height=190)

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Sensibilite", "Defauts prioritaires", "Matrice HPEM", "Protocole VNA", "Conclusion intelligente"])
    with tab1:
        st.subheader("Analyse de sensibilite")
        show_table(sensitivity_rows(results))
        st.info("Cette analyse montre comment une variation locale d'un parametre modifie le gain, le S11 et le score HPEM. Elle aide a identifier les parametres les plus sensibles.")
    with tab2:
        st.subheader("Classement automatique des defauts")
        show_table(defect_ranking_rows(results))
    with tab3:
        st.subheader("Matrice de risque HPEM")
        show_table(hpem_risk_matrix_rows(results))
    with tab4:
        st.subheader("Protocole VNA et validation experimentale")
        show_table(vna_protocol_rows(results))
    with tab5:
        st.subheader("Conclusion automatique intelligente")
        st.success(intelligent_conclusion(results))
        st.text_area("Texte pret pour le rapport", intelligent_conclusion(results), height=160)


def page_prototype_inspection(results: dict) -> None:
    st.title("Inspection du prototype")
    st.write("Associe les photos reelles du cornet aux defauts du modele afin de justifier les valeurs introduites et de renforcer l'analyse experimentale.")
    photo_keys = [
        ("vue_globale", "Vue globale du cornet"),
        ("interieur", "Interieur / etat de surface"),
        ("transition", "Transition guide-cornet"),
        ("soudures", "Soudures / pliage"),
        ("ouverture", "Ouverture et aretes"),
        ("vna", "Montage de mesure VNA"),
    ]
    cols = st.columns(2)
    for i,(key,label) in enumerate(photo_keys):
        with cols[i % 2]:
            st.markdown(f"**{label}**")
            uploaded = st.file_uploader(f"Ajouter photo - {label}", type=["png","jpg","jpeg"], key=f"photo_{key}")
            if uploaded is not None:
                st.session_state.prototype_photos[key] = {"name": uploaded.name, "bytes": uploaded.getvalue()}
            if key in st.session_state.prototype_photos:
                st.image(st.session_state.prototype_photos[key]["bytes"], caption=label, use_container_width=True)

    st.subheader("Commentaires d'inspection")
    notes = st.session_state.inspection_notes
    c1,c2 = st.columns(2)
    notes["etat_surface"] = c1.text_area("Etat de surface interne", value=notes.get("etat_surface",""), height=110)
    notes["transition"] = c2.text_area("Transition guide-cornet", value=notes.get("transition",""), height=110)
    notes["soudures"] = c1.text_area("Soudures / pliage", value=notes.get("soudures",""), height=110)
    notes["ouverture"] = c2.text_area("Ouverture / aretes", value=notes.get("ouverture",""), height=110)
    st.session_state.inspection_notes = notes

    st.subheader("Lien photo -> effet RF/HPEM")
    show_table([
        {"Observation": "Surface interne rugueuse", "Parametre associe": "Rugosite Ra", "Effet": "Pertes de surface, echauffement local"},
        {"Observation": "Soudure visible dans le volume RF", "Parametre associe": "Nombre de soudures", "Effet": "Reflexions locales, concentration du champ"},
        {"Observation": "Transition decalee", "Parametre associe": "Defaut d'alignement", "Effet": "Degradation du S11, excitation de modes parasites"},
        {"Observation": "Arete vive", "Parametre associe": "Zone critique HPEM", "Effet": "Risque de decharge electrique"},
        {"Observation": "Oxydation", "Parametre associe": "Niveau d'oxydation", "Effet": "Resistance de surface supplementaire"},
    ])
    export = {"inspection_notes": st.session_state.inspection_notes, "photos": {k: v.get("name","") for k,v in st.session_state.prototype_photos.items()}, "diagnostic": intelligent_conclusion(results)}
    st.download_button("Exporter l'inspection JSON", data=json.dumps(export, indent=2, ensure_ascii=True), file_name="inspection_prototype.json", mime="application/json")


def page_dashboard(results: dict) -> None:
    st.title("Tableau de bord")
    st.write("Vue globale de la conception, des performances RF, des defauts de fabrication, de la tenue HPEM et de la validation experimentale.")

    th = results["theoretical"]
    fab = results["fabricated"]
    corr = results["corrected"]
    hp = fab["hpem"]

    components.html(user_header_html(results), height=118)
    components.html(account_status_html(results), height=145)
    components.html(dashboard_hero_html(results), height=295)
    components.html(conformity_card_html(results), height=300)

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Gain theorique", f"{fmt(th['gain_dbi'])} dBi")
    k2.metric("Gain fabrique", f"{fmt(fab['gain_dbi'])} dBi", delta=f"-{fmt(fab['penalties']['total_loss_db'])} dB")
    k3.metric("Gain corrige", f"{fmt(corr['gain_dbi'])} dBi", delta=f"+{fmt(corr['gain_dbi']-fab['gain_dbi'])} dB")
    k4.metric("S11 fabrique", f"{fmt(fab['penalties']['s11_db'], 1)} dB")
    k5.metric("Score HPEM", f"{fmt(hp['score_hpem'], 0)} %")

    d1, d2 = st.columns([1, 1])
    with d1:
        components.html(readiness_radar_svg(results), height=305)
    with d2:
        components.html(directivity_gauge_svg(th["directivity_dbi"], fab["gain_dbi"], hp["score_hpem"]), height=220)
        components.html(alert_center_html(results), height=255)
        components.html(validation_checklist_html(results), height=210)

    if th["warnings"]:
        st.warning("\n".join(th["warnings"]))

    tabs = st.tabs([
        "Synthese",
        "RF sur bande",
        "Rayonnement",
        "Champs E/H",
        "Defauts",
        "Optimisation",
        "Diagnostic avance",
        "Validation & export",
    ])

    with tabs[0]:
        st.subheader("Tableau recapitulatif final")
        show_table(final_summary_rows(results))
        c1, c2 = st.columns([1.2, 1])
        with c1:
            components.html(comparison_chart_svg(results), height=275)
        with c2:
            st.subheader("Recommandations prioritaires")
            for rec in generate_recommendations(results)[:6]:
                st.info(rec)

    with tabs[1]:
        sweep = frequency_response_data(results, n=61)
        components.html(multi_curve_svg("Gain(f) - theorique / fabrique / corrige", "Frequence (GHz)", "Gain", sweep["f"], [
            ("Theorique", sweep["gain_theorique"], "#2563eb"),
            ("Fabrique", sweep["gain_fabrique"], "#f59e0b"),
            ("Corrige", sweep["gain_corrige"], "#059669"),
        ], "dBi"), height=370)
        components.html(multi_curve_svg("S11(f) - adaptation estimee", "Frequence (GHz)", "S11", sweep["f"], [
            ("Theorique", sweep["s11_theorique"], "#2563eb"),
            ("Fabrique", sweep["s11_fabrique"], "#f59e0b"),
            ("Corrige", sweep["s11_corrige"], "#059669"),
        ], "dB"), height=370)

    with tabs[2]:
        components.html(radiation_pattern_svg(th["hpbw_h_deg"], th["hpbw_e_deg"], th["directivity_dbi"]), height=345)
        c1, c2 = st.columns(2)
        with c1:
            components.html(radiation_db_comparison_svg(results, "H"), height=300)
        with c2:
            components.html(radiation_db_comparison_svg(results, "E"), height=300)
        components.html(radiation_3d_lobe_svg(th["hpbw_h_deg"], th["hpbw_e_deg"], th["gain_dbi"]), height=365)

    with tabs[3]:
        c1, c2 = st.columns(2)
        with c1:
            components.html(guide_efield_svg(st.session_state.params), height=265)
            components.html(efield_heatmap_svg(st.session_state.params), height=270)
            components.html(aperture_heatmap_svg(st.session_state.params, results), height=270)
        with c2:
            components.html(guide_hfield_svg(st.session_state.params), height=265)
            components.html(hfield_heatmap_svg(st.session_state.params), height=270)
            components.html(cst_like_horn_map_svg(st.session_state.params, results), height=290)

    with tabs[4]:
        c1, c2 = st.columns([1, 1.1])
        with c1:
            components.html(defect_pareto_svg(results), height=275)
            st.info(f"Profondeur de peau aluminium: {fmt(fab['penalties']['skin_depth_um'],2)} um. Rapport rugosite/profondeur de peau: {fmt(fab['penalties']['roughness_ratio_skin_depth'],2)}.")
        with c2:
            st.subheader("Pertes estimees")
            rows = [
                {"Defaut": "Rugosite", "Perte dB": round(fab["penalties"]["roughness_loss_db"], 3)},
                {"Defaut": "Soudures", "Perte dB": round(fab["penalties"]["weld_loss_db"], 3)},
                {"Defaut": "Tolerance", "Perte dB": round(fab["penalties"]["dimensional_loss_db"], 3)},
                {"Defaut": "Alignement", "Perte dB": round(fab["penalties"]["alignment_loss_db"], 3)},
                {"Defaut": "Oxydation", "Perte dB": round(fab["penalties"]["oxidation_loss_db"], 3)},
                {"Defaut": "Mastic", "Perte dB": round(fab["penalties"]["mastic_loss_db"], 3)},
            ]
            show_table(rows)

    with tabs[5]:
        st.subheader("Plan d'action automatique")
        show_table(optimization_rows(results))
        st.success(
            f"Apres finition, le gain estime passe de {fmt(fab['gain_dbi'],2)} dBi a {fmt(corr['gain_dbi'],2)} dBi, "
            f"le S11 passe de {fmt(fab['penalties']['s11_db'],1)} dB a {fmt(corr['penalties']['s11_db'],1)} dB, "
            f"et le score HPEM passe de {fmt(fab['hpem']['score_hpem'],0)} % a {fmt(corr['hpem']['score_hpem'],0)} %."
        )

    with tabs[6]:
        components.html(advanced_diagnostic_html(results), height=190)
        a1, a2 = st.columns(2)
        with a1:
            st.subheader("Defauts prioritaires")
            show_table(defect_ranking_rows(results)[:4])
        with a2:
            st.subheader("Risque HPEM")
            show_table(hpem_risk_matrix_rows(results)[:4])
        st.subheader("Conclusion automatique")
        st.success(intelligent_conclusion(results))

    with tabs[7]:
        st.subheader("Protocole de validation")
        show_table(measurement_protocol_rows(results))
        st.subheader("Exports rapides")
        c1, c2, c3 = st.columns(3)
        report = make_report(results)
        c1.download_button("Rapport Markdown", data=report, file_name="rapport_antenne_hpem.md", mime="text/markdown")
        try:
            pdf_bytes = make_academic_pdf_report(results)
        except Exception:
            pdf_bytes = None
        if pdf_bytes:
            c2.download_button("Rapport PDF", data=pdf_bytes, file_name="rapport_antenne_hpem.pdf", mime="application/pdf")
        else:
            c2.warning("PDF non disponible")
        c3.download_button("Figures pour Word", data=make_word_figures_zip(results), file_name="figures_word_antenne_hpem.zip", mime="application/zip")

def page_parameters() -> None:
    st.title("Parametres geometriques")
    st.write("Tu peux soit saisir directement les dimensions, soit demander un pre-dimensionnement selon ta normalisation a partir d'un gain souhaite.")

    p = st.session_state.params
    d = st.session_state.defects

    st.subheader("1. Frequence et guide d'onde")
    c1, c2, c3, c4 = st.columns(4)
    f_center = c1.number_input("Frequence centrale (GHz)", min_value=0.1, max_value=10.0, value=float(p.f_center_ghz), step=0.01)
    f_min = c2.number_input("Borne basse (GHz)", min_value=0.1, max_value=10.0, value=float(p.f_min_ghz), step=0.01)
    f_max = c3.number_input("Borne haute (GHz)", min_value=0.1, max_value=10.0, value=float(p.f_max_ghz), step=0.01)
    names = waveguide_names()
    guide_type = c4.selectbox("Type de guide", names, index=names.index(p.guide_type) if p.guide_type in names else 0)

    if guide_type != p.guide_type:
        selected_guide = WAVEGUIDES[guide_type]
        st.session_state.params.guide_type = guide_type
        st.session_state.params.f_min_ghz = selected_guide.recommended_min_ghz
        st.session_state.params.f_max_ghz = selected_guide.recommended_max_ghz
        st.session_state.params.f_center_ghz = round((selected_guide.recommended_min_ghz + selected_guide.recommended_max_ghz) / 2.0, 3)
        st.session_state.guide_hint = (
            f"Guide {guide_type} charge automatiquement: dimensions internes "
            f"{selected_guide.a_mm:.2f} x {selected_guide.b_mm:.2f} mm, "
            f"bande recommandee {selected_guide.recommended_min_ghz:.2f}-{selected_guide.recommended_max_ghz:.2f} GHz. "
            "Les frequences et les calculs seront recalcules avec ce guide."
        )
        st.rerun()

    guide = WAVEGUIDES[guide_type]
    st.info(f"{guide_type}: dimensions internes {guide.a_mm:.3f} x {guide.b_mm:.3f} mm, plage recommandee {guide.recommended_min_ghz:.2f}-{guide.recommended_max_ghz:.2f} GHz. {guide.comment}")
    st.caption(mode_band_explanation(guide_type))

    b1, b2, b3 = st.columns([1, 1, 1])
    if b1.button("Charger automatiquement la bande recommandee du guide"):
        st.session_state.params.f_min_ghz = guide.recommended_min_ghz
        st.session_state.params.f_max_ghz = guide.recommended_max_ghz
        st.session_state.params.f_center_ghz = round((guide.recommended_min_ghz + guide.recommended_max_ghz) / 2.0, 3)
        st.rerun()
    if b2.button("Mettre seulement la borne haute a la valeur recommandee"):
        st.session_state.params.f_max_ghz = guide.recommended_max_ghz
        st.rerun()
    if b3.button("Calcul automatique du guide conseille"):
        guide_name, msg = auto_select_waveguide(f_center, f_min, f_max)
        st.session_state.params.guide_type = guide_name
        st.session_state.guide_hint = msg
        st.rerun()

    if st.session_state.guide_hint:
        st.success(st.session_state.guide_hint)

    st.subheader("2. Choix du mode de dimensionnement")
    design_mode = st.radio("Mode", ["Saisie directe des dimensions", "Calcul selon ma normalisation (gain souhaite)"], horizontal=True)

    if design_mode == "Calcul selon ma normalisation (gain souhaite)":
        n1, n2, n3 = st.columns(3)
        desired_gain = n1.number_input("Gain souhaite (dBi)", min_value=1.0, max_value=40.0, value=float(st.session_state.norm_gain_dbi), step=0.1)
        ratio_ab = n2.number_input("Rapport A/B", min_value=0.3, max_value=5.0, value=float(st.session_state.norm_ratio_ab), step=0.1)
        eta_norm = n3.slider("Efficacite d'ouverture eta_ap", min_value=0.20, max_value=0.90, value=float(st.session_state.norm_eta), step=0.01)
        st.session_state.norm_gain_dbi = desired_gain
        st.session_state.norm_ratio_ab = ratio_ab
        st.session_state.norm_eta = eta_norm

        norm = normalized_design(f_center, desired_gain, eta_norm, ratio_ab)
        st.markdown("**Resultat du pre-dimensionnement selon la normalisation :**")
        show_table([
            {"Grandeur": "Aire d'ouverture AB", "Valeur": f"{fmt(norm['aperture_area_m2'], 5)} m2"},
            {"Grandeur": "Largeur A", "Valeur": f"{fmt(norm['aperture_width_mm'], 1)} mm"},
            {"Grandeur": "Hauteur B", "Valeur": f"{fmt(norm['aperture_height_mm'], 1)} mm"},
            {"Grandeur": "Longueur effective RH", "Valeur": f"{fmt(norm['r_h_mm'], 1)} mm"},
            {"Grandeur": "Longueur effective RE", "Valeur": f"{fmt(norm['r_e_mm'], 1)} mm"},
            {"Grandeur": "Longueur suggeree L", "Valeur": f"{fmt(norm['horn_length_suggested_mm'], 1)} mm"},
        ])
        st.latex(r"G = \frac{4\pi}{\lambda^2}\eta_{ap}(AB)")
        st.latex(r"AB = \frac{G\lambda^2}{4\pi\eta_{ap}}")
        st.latex(r"\frac{A}{B} \approx 1.5,\quad R_H \approx \frac{A^2}{3\lambda},\quad R_E \approx \frac{B^2}{2\lambda}")
        if st.button("Appliquer ces dimensions au cornet"):
            st.session_state.params.aperture_width_mm = norm["aperture_width_mm"]
            st.session_state.params.aperture_height_mm = norm["aperture_height_mm"]
            st.session_state.params.horn_length_mm = norm["horn_length_suggested_mm"]
            st.session_state.params.aperture_efficiency = eta_norm
            st.rerun()
        horn_length = norm["horn_length_suggested_mm"]
        aperture_width = norm["aperture_width_mm"]
        aperture_height = norm["aperture_height_mm"]
        thickness = p.aluminum_thickness_mm
        efficiency = eta_norm
    else:
        st.subheader("3. Dimensions du cornet")
        c1, c2, c3, c4 = st.columns(4)
        horn_length = c1.number_input("Longueur du cornet (mm)", min_value=1.0, max_value=2000.0, value=float(p.horn_length_mm), step=5.0)
        aperture_width = c2.number_input("Largeur ouverture A (mm)", min_value=1.0, max_value=2000.0, value=float(p.aperture_width_mm), step=5.0)
        aperture_height = c3.number_input("Hauteur ouverture B (mm)", min_value=1.0, max_value=2000.0, value=float(p.aperture_height_mm), step=5.0)
        thickness = c4.number_input("Epaisseur aluminium (mm)", min_value=0.1, max_value=20.0, value=float(p.aluminum_thickness_mm), step=0.1)
        c1, c2 = st.columns(2)
        efficiency = c1.slider("Rendement d'ouverture eta", min_value=0.20, max_value=0.90, value=float(p.aperture_efficiency), step=0.01)

    peak_power = st.number_input("Puissance crete HPEM estimee (MW)", min_value=0.0, max_value=100.0, value=float(p.peak_power_mw), step=0.1)

    st.subheader("4. Defauts de fabrication")
    c1, c2, c3 = st.columns(3)
    roughness = c1.number_input("Rugosite interne Ra (um)", min_value=0.0, max_value=200.0, value=float(d.roughness_um), step=0.5)
    tolerance = c2.number_input("Tolerance dimensionnelle +/- (mm)", min_value=0.0, max_value=20.0, value=float(d.tolerance_mm), step=0.05)
    weld_count = c3.number_input("Nombre de soudures", min_value=0.0, max_value=30.0, value=float(d.weld_count), step=1.0)
    c1, c2, c3 = st.columns(3)
    alignment = c1.number_input("Defaut d'alignement guide-cornet (mm)", min_value=0.0, max_value=30.0, value=float(d.alignment_error_mm), step=0.1)
    oxidation = c2.slider("Oxydation / etat de surface", min_value=0.0, max_value=5.0, value=float(d.oxidation_level), step=0.5)
    mastic_present = c3.checkbox("Mastic ou matiere dielectrique interne", value=bool(d.mastic_present))
    mastic_severity = st.slider("Importance du mastic interne", min_value=0.0, max_value=5.0, value=float(d.mastic_severity), step=0.5)

    if f_min >= f_max:
        st.error("La borne basse doit etre inferieure a la borne haute.")
        return

    st.session_state.params = AntennaParams(
        f_center_ghz=f_center,
        f_min_ghz=f_min,
        f_max_ghz=f_max,
        guide_type=guide_type,
        horn_length_mm=horn_length,
        aperture_width_mm=aperture_width,
        aperture_height_mm=aperture_height,
        aluminum_thickness_mm=thickness,
        aperture_efficiency=efficiency,
        peak_power_mw=peak_power,
    )
    st.session_state.defects = FabricationDefects(
        roughness_um=roughness,
        tolerance_mm=tolerance,
        weld_count=weld_count,
        alignment_error_mm=alignment,
        oxidation_level=oxidation,
        mastic_present=mastic_present,
        mastic_severity=mastic_severity if mastic_present else 0.0,
    )

    st.success("Parametres mis a jour automatiquement.")
    current_results = calculate_all(st.session_state.params, st.session_state.defects)
    components.html(conformity_card_html(current_results), height=300)
    st.subheader("Schemas de conception")
    c1, c2 = st.columns(2)
    with c1:
        components.html(horn_2d_svg(st.session_state.params), height=270)
    with c2:
        components.html(horn_3d_svg(st.session_state.params), height=290)

    payload = {"params": st.session_state.params.__dict__, "defects": st.session_state.defects.__dict__}
    st.download_button("Telecharger la configuration JSON", data=json.dumps(payload, indent=2, ensure_ascii=True), file_name="configuration_antenne_hpem.json", mime="application/json")


def page_rf_results(results: dict) -> None:
    st.title("Resultats RF")
    th = results["theoretical"]
    fab = results["fabricated"]
    guide = WAVEGUIDES[results["params"]["guide_type"]]

    c1, c2, c3 = st.columns(3)
    c1.metric("Longueur d'onde", f"{fmt(th['wavelength_mm'])} mm")
    c2.metric("Coupure TE10", f"{fmt(th['fc_te10_ghz'], 3)} GHz")
    c3.metric("Premier mode superieur", f"{fmt(th['upper_mode_ghz'], 3)} GHz")

    st.subheader("Validation modale")
    if th["mode_status"] == "TE10 dominant valide":
        st.success(th["mode_status"])
    else:
        st.warning(th["mode_status"])
        for warning in th["warnings"]:
            st.write("- " + warning)

    st.info(f"Guide {guide.name}: bande recommandee {guide.recommended_min_ghz:.2f}-{guide.recommended_max_ghz:.2f} GHz ; domaine monomode theorique approximatif {guide.fc_te10_ghz:.3f}-{guide.upper_mode_ghz:.3f} GHz.")

    st.subheader("Grandeurs electromagnetiques")
    rows = [
        {"Grandeur": "Directivite", "Valeur": f"{fmt(th['directivity_dbi'])} dBi"},
        {"Grandeur": "Gain theorique", "Valeur": f"{fmt(th['gain_dbi'])} dBi"},
        {"Grandeur": "Gain fabrique estime", "Valeur": f"{fmt(fab['gain_dbi'])} dBi"},
        {"Grandeur": "Ouverture efficace", "Valeur": f"{fmt(th['effective_aperture_m2'], 4)} m2"},
        {"Grandeur": "HPBW plan H", "Valeur": f"{fmt(th['hpbw_h_deg'], 1)} deg"},
        {"Grandeur": "HPBW plan E", "Valeur": f"{fmt(th['hpbw_e_deg'], 1)} deg"},
        {"Grandeur": "S11 theorique", "Valeur": f"{fmt(th['base_s11_db'], 1)} dB"},
        {"Grandeur": "S11 fabrique", "Valeur": f"{fmt(fab['penalties']['s11_db'], 1)} dB"},
    ]
    show_table(rows)

    st.subheader("Diagrammes de rayonnement plus scientifiques")
    c1, c2 = st.columns(2)
    with c1:
        components.html(beam_cartesian_svg(th["hpbw_h_deg"], "Diagramme plan H - cartesien", "#2563eb"), height=255)
        components.html(beam_polar_svg(th["hpbw_h_deg"], "Diagramme plan H - polaire", "#2563eb"), height=265)
    with c2:
        components.html(beam_cartesian_svg(th["hpbw_e_deg"], "Diagramme plan E - cartesien", "#059669"), height=255)
        components.html(beam_polar_svg(th["hpbw_e_deg"], "Diagramme plan E - polaire", "#059669"), height=265)

    st.subheader("Lecture rapide des diagrammes")
    simple_bar("Ouverture angulaire plan H", th["hpbw_h_deg"], 120.0, " deg")
    simple_bar("Ouverture angulaire plan E", th["hpbw_e_deg"], 120.0, " deg")

    st.subheader("Champs E et H relies a l'analyse HPEM")
    c1, c2 = st.columns(2)
    with c1:
        components.html(guide_efield_svg(st.session_state.params), height=265)
        components.html(horn_efield_hfield_svg(st.session_state.params, results), height=265)
    with c2:
        components.html(guide_hfield_svg(st.session_state.params), height=265)
        st.markdown(
            f"""
            **Interpretation HPEM**
            - le **mode TE10** presente une distribution de **champ electrique transverse** non uniforme, maximale au centre du guide ;
            - le **champ magnetique** est associe aux courants de surface sur les parois conductrices ;
            - les **soudures**, **desalignements** et **rugosites** perturbent localement ces champs ;
            - la **gorge**, la **transition guide-cornet** et les **aretes de l'ouverture** sont des zones critiques en HPEM.
            - champ crete estime a l'ouverture: **{fmt(results['fabricated']['hpem']['e_peak_aperture_kv_per_m'],0)} kV/m** ;
            - marge simplifiee vis-a-vis du claquage: **{fmt(results['fabricated']['hpem']['breakdown_margin_air'],2)}**.
            """
        )

    st.subheader("Diagramme de rayonnement synthétique")
    components.html(radiation_pattern_svg(th["hpbw_h_deg"], th["hpbw_e_deg"], th["directivity_dbi"]), height=345)
    st.caption("Ce diagramme de rayonnement est un tracé synthétique basé sur les largeurs a mi-puissance estimees dans les plans H et E. Il est utile pour la presentation et la comparaison, mais il ne remplace pas un diagramme complet issu d'une simulation EM 3D ou d'une mesure anechoique.")

    st.subheader("Diagrammes normalisés en dB")
    c1, c2 = st.columns(2)
    with c1:
        components.html(radiation_db_comparison_svg(results, "H"), height=300)
    with c2:
        components.html(radiation_db_comparison_svg(results, "E"), height=300)

    st.subheader("Vue 3D stylisée du lobe")
    components.html(radiation_3d_lobe_svg(th["hpbw_h_deg"], th["hpbw_e_deg"], th["gain_dbi"]), height=365)

    st.subheader("Formules principales")
    st.latex(r"f_c = \frac{c}{2a}")
    st.latex(r"G = \eta \frac{4\pi A}{\lambda^2}")


def page_defects(results: dict) -> None:
    st.title("Impact des defauts")
    st.write("Cette page relie les defauts mecaniques aux consequences RF et HPEM probables.")

    st.subheader("Effets physiques attendus")
    show_table(defect_effect_table())

    st.subheader("Pertes estimees par defaut")
    pen = results["fabricated"]["penalties"]
    rows = [
        {"Defaut": "Rugosite interne", "Penalite dB": pen["roughness_loss_db"]},
        {"Defaut": "Soudures", "Penalite dB": pen["weld_loss_db"]},
        {"Defaut": "Erreurs dimensionnelles", "Penalite dB": pen["dimensional_loss_db"]},
        {"Defaut": "Desalignement", "Penalite dB": pen["alignment_loss_db"]},
        {"Defaut": "Oxydation", "Penalite dB": pen["oxidation_loss_db"]},
        {"Defaut": "Mastic", "Penalite dB": pen["mastic_loss_db"]},
    ]
    rows = [{"Defaut": r["Defaut"], "Penalite dB": round(r["Penalite dB"], 3)} for r in rows]
    show_table(rows)
    max_loss = max([float(r["Penalite dB"]) for r in rows] + [1.0])
    for row in rows:
        simple_bar(row["Defaut"], float(row["Penalite dB"]), max_loss, " dB")

    st.info(f"Profondeur de peau aluminium estimee: {fmt(pen['skin_depth_um'], 2)} um. Rapport rugosite/profondeur de peau: {fmt(pen['roughness_ratio_skin_depth'], 2)}.")

    st.subheader("Module HPEM")
    hp = results["fabricated"]["hpem"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Score HPEM", f"{fmt(hp['score_hpem'], 0)} %")
    c2.metric("Risque de decharge", hp["breakdown_risk"])
    c3.metric("Marge air simplifiee", fmt(hp["breakdown_margin_air"], 2))
    st.write("Zones critiques:")
    for zone in hp["critical_zones"]:
        st.write("- " + zone)
    penalty_rows = [{"Cause": key, "Penalite score": round(value, 2)} for key, value in hp["score_penalties"].items()]
    show_table(penalty_rows)



def page_pfe_diagrams(results: dict) -> None:
    st.title("Diagrammes et visualisations")
    st.write("Cette page regroupe les figures explicatives: courbes parametriques, cartes qualitatives de champ, zones critiques, diagrammes de rayonnement et texte de synthese automatique.")

    data = frequency_response_data(results)
    st.subheader("1. Courbes parametriques en fonction de la frequence")
    components.html(
        multi_curve_svg(
            "Gain estime en fonction de la frequence",
            "Frequence (GHz)",
            "Gain",
            data["f"],
            [
                ("Theorique", data["gain_theorique"], "#2563eb"),
                ("Fabrique", data["gain_fabrique"], "#f59e0b"),
                ("Corrige", data["gain_corrige"], "#059669"),
            ],
            "dBi",
        ),
        height=370,
    )
    components.html(
        multi_curve_svg(
            "S11 estime en fonction de la frequence",
            "Frequence (GHz)",
            "S11",
            data["f"],
            [
                ("Theorique", data["s11_theorique"], "#2563eb"),
                ("Fabrique", data["s11_fabrique"], "#f59e0b"),
                ("Corrige", data["s11_corrige"], "#059669"),
            ],
            "dB",
        ),
        height=370,
    )
    components.html(
        multi_curve_svg(
            "Score HPEM estime en fonction de la frequence",
            "Frequence (GHz)",
            "Score HPEM",
            data["f"],
            [
                ("Fabrique", data["score_fabrique"], "#f59e0b"),
                ("Corrige", data["score_corrige"], "#059669"),
            ],
            "%",
        ),
        height=370,
    )

    st.subheader("2. Diagrammes de rayonnement")
    components.html(radiation_pattern_svg(results["theoretical"]["hpbw_h_deg"], results["theoretical"]["hpbw_e_deg"], results["theoretical"]["directivity_dbi"]), height=345)
    c1, c2 = st.columns(2)
    with c1:
        components.html(radiation_db_comparison_svg(results, "H"), height=300)
    with c2:
        components.html(radiation_db_comparison_svg(results, "E"), height=300)
    components.html(radiation_3d_lobe_svg(results["theoretical"]["hpbw_h_deg"], results["theoretical"]["hpbw_e_deg"], results["theoretical"]["gain_dbi"]), height=365)

    st.subheader("3. Cartes qualitatives E-field / H-field")
    c1, c2 = st.columns(2)
    with c1:
        components.html(efield_heatmap_svg(st.session_state.params), height=270)
        components.html(aperture_heatmap_svg(st.session_state.params, results), height=270)
    with c2:
        components.html(hfield_heatmap_svg(st.session_state.params), height=270)
        components.html(cst_like_horn_map_svg(st.session_state.params, results), height=290)

    st.subheader("4. Schema 2D / 3D pour la partie conception")
    c1, c2 = st.columns(2)
    with c1:
        components.html(horn_2d_svg(st.session_state.params), height=270)
    with c2:
        components.html(horn_3d_svg(st.session_state.params), height=290)

    st.subheader("5. Texte de synthese automatique")
    st.text_area("Texte de synthese", memory_text_block(results), height=180)

    st.info(
        "Les cartes E/H et les courbes S11(f) sont des modeles parametriques qualitatifs. Elles sont utiles pour expliquer l'influence des dimensions et des defauts, mais la validation finale doit rester une simulation EM 3D et des mesures experimentales."
    )

def page_fields_pfe(results: dict) -> None:
    st.title("Champs E/H et analyse HPEM")
    st.write("Cette page regroupe les cartes qualitatives des champs electrique et magnetique, les zones critiques et un texte de synthese automatique.")

    st.subheader("Cartes qualitatives type CST-like")
    c1, c2 = st.columns(2)
    with c1:
        components.html(efield_heatmap_svg(st.session_state.params), height=270)
        components.html(aperture_heatmap_svg(st.session_state.params, results), height=270)
    with c2:
        components.html(hfield_heatmap_svg(st.session_state.params), height=270)
        components.html(cst_like_horn_map_svg(st.session_state.params, results), height=290)

    st.subheader("Interpretation scientifique")
    st.markdown(
        f"""
        - Le mode dominant **TE10** impose une distribution de champ electrique transverse avec un maximum au centre du guide.
        - Le champ magnetique est lie aux courants de surface, ce qui rend la qualite des parois internes importante.
        - En contexte **HPEM**, les zones les plus sensibles sont la transition guide-cornet, les aretes de l'ouverture et les soudures internes.
        - Champ crete estime a la gorge : **{fmt(results['fabricated']['hpem']['e_peak_throat_kv_per_m'],0)} kV/m**.
        - Champ crete estime a l'ouverture : **{fmt(results['fabricated']['hpem']['e_peak_aperture_kv_per_m'],0)} kV/m**.
        - Marge simplifiee vis-a-vis du claquage dans l'air : **{fmt(results['fabricated']['hpem']['breakdown_margin_air'],2)}**.
        """
    )

    st.subheader("Texte de synthese automatique")
    st.text_area("Texte de synthese", memory_text_block(results), height=170)


def optimization_rows(results: dict) -> list[dict]:
    pen = results["fabricated"]["penalties"]
    candidates = [
        ("Poncer et polir les surfaces internes", pen["roughness_loss_db"], "rugosite"),
        ("Reduire ou deplacer les soudures internes", pen["weld_loss_db"], "soudures"),
        ("Ameliorer l'alignement guide-cornet", pen["alignment_loss_db"], "alignement"),
        ("Controler les dimensions A, B et gorge", pen["dimensional_loss_db"], "tolerance"),
        ("Nettoyer et proteger contre l'oxydation", pen["oxidation_loss_db"], "oxydation"),
        ("Supprimer le mastic interne", pen["mastic_loss_db"], "mastic"),
    ]
    candidates.sort(key=lambda x: x[1], reverse=True)
    rows = []
    for i, (action, loss, cause) in enumerate(candidates, start=1):
        if loss <= 0.02:
            priority = "faible"
        elif i <= 2:
            priority = "haute"
        else:
            priority = "moyenne"
        rows.append({"Priorite": i, "Action proposee": action, "Cause ciblee": cause, "Gain potentiel dB": round(loss, 3), "Niveau": priority})
    return rows


def page_optimization(results: dict) -> None:
    st.title("Optimisation")
    st.write("Cette page transforme les resultats en plan d'action: quoi corriger, pourquoi, et quel impact attendre sur le gain, le S11 et la tenue HPEM.")

    st.subheader("Courbes sur la bande de frequence")
    sweep = frequency_response_data(results, n=61)
    xs = sweep["f"]
    components.html(multi_curve_svg("Gain(f)", "Frequence (GHz)", "Gain", xs, [
        ("Theorique", sweep["gain_theorique"], "#2563eb"),
        ("Fabrique", sweep["gain_fabrique"], "#059669"),
        ("Corrige", sweep["gain_corrige"], "#f59e0b"),
    ], "dBi"), height=370)
    components.html(multi_curve_svg("S11(f)", "Frequence (GHz)", "S11", xs, [
        ("Theorique", sweep["s11_theorique"], "#2563eb"),
        ("Fabrique", sweep["s11_fabrique"], "#059669"),
        ("Corrige", sweep["s11_corrige"], "#f59e0b"),
    ], "dB"), height=370)
    components.html(multi_curve_svg("Score HPEM(f)", "Frequence (GHz)", "Score HPEM", xs, [
        ("Fabrique", sweep["score_fabrique"], "#059669"),
        ("Corrige", sweep["score_corrige"], "#f59e0b"),
    ], "%"), height=370)

    st.subheader("Plan d'action automatique")
    show_table(optimization_rows(results))

    st.subheader("Conclusion d'optimisation")
    current = results["fabricated"]
    corrected = results["corrected"]
    st.success(
        f"Apres finition, le gain estime passe de {fmt(current['gain_dbi'],2)} dBi a {fmt(corrected['gain_dbi'],2)} dBi, "
        f"le S11 passe de {fmt(current['penalties']['s11_db'],1)} dB a {fmt(corrected['penalties']['s11_db'],1)} dB, "
        f"et le score HPEM passe de {fmt(current['hpem']['score_hpem'],0)} % a {fmt(corrected['hpem']['score_hpem'],0)} %."
    )


def page_report(results: dict) -> None:
    st.title("Rapport automatique")

    meta = get_report_meta()
    with st.expander("Personnalisation du rapport et de la page de garde", expanded=True):
        c1, c2 = st.columns(2)
        meta["university"] = c1.text_input("Universite", value=meta["university"])
        meta["faculty"] = c2.text_input("Faculte / Institut", value=meta["faculty"])
        meta["department"] = c1.text_input("Departement / Laboratoire", value=meta["department"])
        meta["year"] = c2.text_input("Annee universitaire", value=meta["year"])
        meta["author"] = c1.text_input("Etudiant(e)", value=meta["author"])
        meta["supervisor"] = c2.text_input("Encadrant", value=meta["supervisor"])
        meta["document_title"] = st.text_input("Titre du document", value=meta["document_title"])
        meta["subtitle"] = st.text_input("Sous-titre", value=meta["subtitle"])
        uploaded_logo = st.file_uploader("Logo universite (PNG/JPG)", type=["png", "jpg", "jpeg"])
        if uploaded_logo is not None:
            st.session_state.university_logo_bytes = uploaded_logo.getvalue()
            st.session_state.university_logo_name = uploaded_logo.name
            st.image(st.session_state.university_logo_bytes, width=140, caption="Logo charge")
        elif st.session_state.get("university_logo_bytes"):
            st.image(st.session_state.university_logo_bytes, width=140, caption="Logo actuellement utilise")
        st.session_state.report_meta = meta

    report = make_report(results)
    summary = final_summary_rows(results)
    figures_zip = make_word_figures_zip(results)

    st.subheader("Tableau recapitulatif final")
    show_table(summary)

    c1, c2, c3 = st.columns(3)
    c1.download_button("Telecharger le rapport Markdown", data=report, file_name="rapport_antenne_hpem.md", mime="text/markdown")

    pdf_bytes = None
    pdf_error = None
    try:
        pdf_bytes = make_academic_pdf_report(results)
    except Exception as exc:
        pdf_error = exc

    if pdf_bytes is not None:
        c2.download_button("Telecharger le rapport PDF", data=pdf_bytes, file_name="rapport_antenne_hpem.pdf", mime="application/pdf")
    elif pdf_error is not None:
        c2.warning("Erreur PDF")
        st.error("La generation PDF a rencontre une erreur, mais le rapport Markdown reste disponible.")
        st.code(str(pdf_error))
    else:
        c2.warning("PDF indisponible")

    c3.download_button("Telecharger les images pour Word", data=figures_zip, file_name="figures_word_antenne_hpem.zip", mime="application/zip")

    st.subheader("Figures pretes a inserer dans Word")
    figs = figure_exports(results)
    preview = [figs[0], figs[2], figs[5], figs[6], figs[7], figs[12]]
    cols = st.columns(3)
    for i, (fname, svg) in enumerate(preview):
        with cols[i % 3]:
            components.html(svg, height=210)
            st.download_button(f"Telecharger {fname}", data=svg, file_name=fname, mime="image/svg+xml", key=f"dl_{fname}")

    st.subheader("Apercu du rapport")
    st.text_area("Contenu Markdown", report, height=450)

    st.subheader("Recommandations automatiques")
    for rec in generate_recommendations(results):
        st.success(rec)


def page_design_calculs(results: dict) -> None:
    st.title("Conception et calculs")
    tabs = st.tabs(["Parametres", "Resultats RF", "Optimisation"] )
    with tabs[0]:
        page_parameters()
    with tabs[1]:
        page_rf_results(get_results())
    with tabs[2]:
        page_optimization(get_results())


def page_defauts_hpem(results: dict) -> None:
    st.title("Defauts et HPEM")
    tabs = st.tabs(["Impact des defauts", "Champs E/H", "Analyse avancee", "Conformite"] )
    with tabs[0]:
        page_defects(results)
    with tabs[1]:
        page_fields_pfe(results)
    with tabs[2]:
        page_advanced_analysis(results)
    with tabs[3]:
        components.html(conformity_card_html(results), height=310)
        _, _, rows = conformity_assessment(results)
        show_table(rows)


def page_visualisations_objectives(results: dict) -> None:
    st.title("Visualisations scientifiques")
    tabs = st.tabs(["Diagrammes RF", "Rayonnement", "Schemas", "Figures Word"] )
    with tabs[0]:
        page_pfe_diagrams(results)
    with tabs[1]:
        c1, c2 = st.columns(2)
        with c1:
            components.html(radiation_db_comparison_svg(results, "H"), height=310)
        with c2:
            components.html(radiation_db_comparison_svg(results, "E"), height=310)
        components.html(radiation_3d_lobe_svg(results["theoretical"]["hpbw_h_deg"], results["theoretical"]["hpbw_e_deg"], results["theoretical"]["gain_dbi"]), height=365)
    with tabs[2]:
        c1, c2 = st.columns(2)
        with c1:
            components.html(horn_2d_svg(st.session_state.params), height=275)
        with c2:
            components.html(horn_3d_svg(st.session_state.params), height=295)
    with tabs[3]:
        st.download_button("Telecharger toutes les figures SVG", data=make_word_figures_zip(results), file_name="figures_word_antenne_hpem.zip", mime="application/zip")


def page_validation_objective(results: dict) -> None:
    st.title("Validation experimentale")
    tabs = st.tabs(["Mesures", "Inspection prototype", "Conformite"] )
    with tabs[0]:
        page_measurements(results)
    with tabs[1]:
        page_prototype_inspection(results)
    with tabs[2]:
        components.html(conformity_card_html(results), height=310)
        _, _, rows = conformity_assessment(results)
        show_table(rows)


def page_project_account_objective(results: dict) -> None:
    st.title("Projet et utilisateur")
    tabs = st.tabs(["Compte utilisateur", "Espace projet"] )
    with tabs[0]:
        page_account(results)
    with tabs[1]:
        page_project_space(results)


def page_report_export_objective(results: dict) -> None:
    st.title("Rapport et export")
    page_report(results)

def main() -> None:
    init_state()

    if not st.session_state.authenticated:
        show_login_page()
        return

    results = get_results()
    user = current_user()

    st.sidebar.title("Navigation")
    st.sidebar.success(f"Connecte : {user.get('name','')}")
    st.sidebar.caption(f"Role : {user.get('role','')}")
    if st.sidebar.button("Se deconnecter"):
        st.session_state.authenticated = False
        st.session_state.user = None
        st.rerun()

    pages = [
        "Tableau de bord",
        "Conception et calculs",
        "Defauts et HPEM",
        "Visualisations scientifiques",
        "Validation experimentale",
        "Projet et utilisateur",
        "Rapport et export",
    ]
    if user.get("role") == "Admin":
        pages.append("Administration")

    page = st.sidebar.radio("Pages", pages)

    st.sidebar.markdown("---")
    st.sidebar.caption("Synthese rapide")
    st.sidebar.write(f"Guide: **{st.session_state.params.guide_type}**")
    st.sidebar.write(f"Gain fabrique: **{fmt(results['fabricated']['gain_dbi'])} dBi**")
    st.sidebar.write(f"S11: **{fmt(results['fabricated']['penalties']['s11_db'], 1)} dB**")
    st.sidebar.write(f"Score HPEM: **{fmt(results['fabricated']['hpem']['score_hpem'], 0)} %**")
    st.sidebar.markdown("---")
    st.sidebar.caption("Projet")
    st.sidebar.write(f"ID: **{st.session_state.project_info.get('project_id','')}**")
    st.sidebar.write(f"Prototype: **{st.session_state.project_info.get('prototype_name','')}**")

    if page == "Tableau de bord":
        page_dashboard(results)
    elif page == "Conception et calculs":
        page_design_calculs(results)
    elif page == "Defauts et HPEM":
        page_defauts_hpem(results)
    elif page == "Visualisations scientifiques":
        page_visualisations_objectives(results)
    elif page == "Validation experimentale":
        page_validation_objective(results)
    elif page == "Projet et utilisateur":
        page_project_account_objective(results)
    elif page == "Administration":
        page_admin_panel(results)
    else:
        page_report_export_objective(results)


if __name__ == "__main__":
    main()
