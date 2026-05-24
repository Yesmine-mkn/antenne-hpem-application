# Version finale - Application antenne cornet HPEM bande S

Cette version finale regroupe toutes les fonctionnalités demandées :

- authentification locale avec identifiant et mot de passe ;
- création de compte et changement de mot de passe ;
- compte administrateur de démonstration ;
- espace projet avec historique et sauvegarde des configurations ;
- tableau de bord complet avec indicateurs RF/HPEM/fabrication ;
- score global du prototype ;
- indice de confiance du modèle ;
- analyse de sensibilité ;
- classement automatique des défauts ;
- matrice de risque HPEM ;
- inspection du prototype avec photos ;
- protocole VNA et validation expérimentale ;
- diagrammes de rayonnement H/E et lobe 3D stylisé ;
- cartes qualitatives E-field / H-field ;
- recommandations automatiques ;
- conclusion automatique intelligente ;
- export PDF avec page de garde ;
- export Markdown ;
- export des figures SVG prêtes pour Word.

## Comptes de démonstration

- admin / admin123
- yesmine / antenne123
- invite / invite

## Installation Windows

```powershell
cd "C:\Users\yesmin\Downloads\antenne_hpem_app_FINAL\antenne_hpem_app_FINAL"
& "C:\Users\yesmin\AppData\Local\Programs\Python\Python313\python.exe" -m pip install --only-binary=:all: -r requirements.txt
& "C:\Users\yesmin\AppData\Local\Programs\Python\Python313\python.exe" -m streamlit run app.py
```

## Dépendances

Le fichier `requirements.txt` reste léger :

```text
streamlit==1.56.0
fpdf2>=2.7.9,<3
```

Il n'y a pas de dépendance directe à `pandas` ou `numpy`, afin d'éviter les erreurs de compilation sous Windows/Python 3.13.
