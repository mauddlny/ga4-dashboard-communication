# GA4 Dashboard — Guide de démarrage

## 1. Installer les dépendances
```
pip install -r requirements.txt
```

## 2. Créer un compte de service Google

1. Va sur https://console.cloud.google.com/
2. Crée un projet (ou sélectionne un projet existant)
3. Active l'API **Google Analytics Data API v1**
   - Menu → API et services → Bibliothèque → cherche "Google Analytics Data API" → Activer
4. Crée un compte de service :
   - Menu → API et services → Identifiants → Créer des identifiants → Compte de service
   - Nom : `ga4-dashboard`
   - Clique sur le compte créé → onglet "Clés" → Ajouter une clé → JSON
   - Télécharge le fichier JSON et renomme-le `service_account.json`
   - Place-le dans ce dossier (`ga4-dashboard/`)

## 3. Donner accès aux propriétés GA4

Pour chaque propriété GA4 :
1. Va dans GA4 → Admin → Gestion des accès à la propriété
2. Clique sur "+" → Ajouter des utilisateurs
3. Entre l'email du compte de service (format : `ga4-dashboard@xxx.iam.gserviceaccount.com`)
4. Donne le rôle **Lecteur**

## 4. Trouver les Property IDs numériques

Dans GA4 → Admin → Paramètres de la propriété → **ID de propriété** (nombre à 9 chiffres)

Remplace dans `app.py` :
```python
PROPERTY_IDS = {
    "ESG Régions":    "123456789",   # ← ton vrai ID
    "Esarc":          "123456789",
    "Digital Campus": "123456789",
    "Elije":          "123456789",
}
```

## 5. Lancer le dashboard
```
streamlit run app.py
```

Le dashboard s'ouvre automatiquement sur http://localhost:8501
