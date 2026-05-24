# Installation Windows - Antenne cornet HPEM

## Important
Utiliser cette version du dossier :

```powershell
antenne_hpem_app_v4_5_dashboard
```

Ne pas relancer l'ancien dossier `antenne_hpem_app`, car son ancien `requirements.txt` peut contenir `pandas` et `numpy`, ce qui peut provoquer une compilation de NumPy sous Python 3.13.

## Installation

```powershell
cd "C:\Users\yesmin\Downloads\antenne_hpem_app_v4_5_dashboard_complet\antenne_hpem_app_v4_5_dashboard"

& "C:\Users\yesmin\AppData\Local\Programs\Python\Python313\python.exe" -m pip install --upgrade pip
& "C:\Users\yesmin\AppData\Local\Programs\Python\Python313\python.exe" -m pip install --only-binary=:all: -r requirements.txt
```

## Lancement

```powershell
& "C:\Users\yesmin\AppData\Local\Programs\Python\Python313\python.exe" -m streamlit run app.py
```

## Dependances

Cette version utilise seulement :

```text
streamlit==1.56.0
fpdf2>=2.7.9,<3
```

Elle n'importe pas directement pandas ni numpy.
