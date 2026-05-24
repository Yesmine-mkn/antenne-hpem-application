# Application Antenne HPEM - URL publique valable

Cette version contient uniquement l'application Streamlit. La page de carte QR n'est pas incluse.

## Objectif
Obtenir une URL publique stable pour ouvrir l'application, par exemple :

```text
https://nom-application.streamlit.app
```

## Methode recommandee : Streamlit Community Cloud

Netlify Drop ne convient pas pour cette application, car il ne lance pas Python/Streamlit. Pour cette application, utilisez Streamlit Community Cloud.

### Etapes

1. Creez un compte GitHub si vous n'en avez pas.
2. Creez un nouveau depot GitHub, par exemple : `antenne-hpem-app`.
3. Envoyez tous les fichiers de ce dossier dans le depot GitHub.
4. Ouvrez Streamlit Community Cloud : `https://share.streamlit.io/`
5. Cliquez sur `New app`.
6. Choisissez votre depot GitHub.
7. Dans `Main file path`, mettez :

```text
streamlit_app.py
```

8. Cliquez sur `Deploy`.

## Comptes de demonstration

- `admin` / `admin123`
- `yesmine` / `antenne123`
- `invite` / `invite`

## Fichiers importants

- `streamlit_app.py` : point d'entree pour Streamlit Cloud
- `app.py` : application principale
- `core.py` : calculs et logique scientifique
- `requirements.txt` : dependances Python
- `.streamlit/config.toml` : configuration cloud

## Important

Ne publiez pas cette application avec Netlify Drop. Netlify Drop est adapte aux sites HTML/CSS/JS, pas aux applications Python Streamlit.
