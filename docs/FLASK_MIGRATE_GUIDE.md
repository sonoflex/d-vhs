# Flask-Migrate Setup Guide für D-VHS

Dieses Guide dokumentiert alle Schritte zum Einrichten von Flask-Migrate für sichere Datenbankmigrationen in Production.

---

## Inhaltsverzeichnis

1. [Warum Flask-Migrate?](#warum-flask-migrate)
2. [Schritt 1: Installation](#schritt-1-installation)
3. [Schritt 2: app.py aktualisieren](#schritt-2-apppy-aktualisieren)
4. [Schritt 3: Migrations-Verzeichnis initialisieren](#schritt-3-migrations-verzeichnis-initialisieren)
5. [Schritt 4: Entrypoint-Script erstellen](#schritt-4-entrypoint-script-erstellen)
6. [Schritt 5: Dockerfile aktualisieren](#schritt-5-dockerfile-aktualisieren)
7. [Schritt 6: Lokal testen](#schritt-6-lokal-testen)
8. [Schritt 7: Erste Migration generieren](#schritt-7-erste-migration-generieren)
9. [Schritt 8: Zu Staging deployen](#schritt-8-zu-staging-deployen)
10. [Schritt 9: Zu Production mergen](#schritt-9-zu-production-mergen)
11. [Workflow für zukünftige Schema-Änderungen](#workflow-für-zukünftige-schema-änderungen)
12. [Best Practices](#best-practices)

---

## Warum Flask-Migrate?

**Problem ohne Migrationen:**
- Neue Spalten werden nicht automatisch zur bestehenden Datenbank hinzugefügt
- Bei Schema-Änderungen muss die ganze Datenbank neu erstellt werden
- **In Production = Datenverlust!** 😱

**Lösung mit Flask-Migrate:**
- ✅ Versionskontrolle der Datenbankstruktur
- ✅ Automatische Migrationen beim Startup
- ✅ Rollback möglich (`downgrade`)
- ✅ Safe für Production
- ✅ Industry Standard Tool

---

## Schritt 1: Installation

### 1.1 Paket zu requirements.txt hinzufügen

Öffne `requirements.txt` und füge hinzu:

```
Flask-Migrate==4.0.5
```

Die komplette `requirements.txt` sollte so aussehen:

```
flask==3.0.3
flask_sqlalchemy==3.1.1
tmdbv3api==1.9.0
python-dotenv==1.1.1
werkzeug==3.0.1
requests==2.31.0
psycopg2-binary==2.9.9
gunicorn==21.2.0
Flask-Migrate==4.0.5
```

### 1.2 Lokal installieren

```bash
pip install Flask-Migrate==4.0.5
```

---

## Schritt 2: app.py aktualisieren

Öffne `app.py` und stelle sicher, dass folgende Imports vorhanden sind:

```python
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate  # ← NEU HINZUFÜGEN
from werkzeug.security import generate_password_hash, check_password_hash
import os
import logging

# Lade Umgebungsvariablen
load_dotenv()

# Logging konfigurieren
logging.basicConfig(level=logging.INFO)

# Flask App erstellen
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

# Datenbank konfigurieren
if os.environ.get("DATABASE_URL"):
    database_url = os.environ.get("DATABASE_URL")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    logging.info("✓ Verwende PostgreSQL")
else:
    db_path = os.path.join(os.getcwd(), "data", "filme.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    logging.warning("⚠ DATABASE_URL nicht gesetzt - verwende SQLite")

# Datenbank initialisieren
db = SQLAlchemy(app)
migrate = Migrate(app, db)  # ← NEU HINZUFÜGEN

# Rest deiner app.py ...
```

**Wichtig:** Diese Zeilen müssen **vor** der Klassendeklaration stehen!

---

## Schritt 3: Migrations-Verzeichnis initialisieren

Nur einmalig! Diese Schritte initialisieren das Migrations-System.

### 3.1 Docker Container starten (falls nicht laufen)

```bash
docker-compose up -d
```

### 3.2 In Container gehen

```bash
docker-compose exec d-vhs bash
```

### 3.3 Migrations-Verzeichnis initialisieren

```bash
flask db init
```

**Output sollte sein:**
```
Creating directory /app/migrations ...  done
Creating directory /app/migrations/versions ...  done
Generating /app/migrations/alembic.ini ...  done
Generating /app/migrations/README ...  done
Generating /app/migrations/env.py ...  done
```

### 3.4 Besitzer anpassen (nur Linux/Mac)

```bash
exit  # Aus dem Container
sudo chown -R $(whoami):$(whoami) migrations/
```

### 3.5 Docker-Compose aktualisieren

Öffne `docker-compose.yml` und stelle sicher, dass `migrations/` gemountet ist:

```yaml
services:
  d-vhs:
    # ... rest der config ...
    volumes:
      - ./data:/app/data
      - ./migrations:/app/migrations  # ← DIESE ZEILE HINZUFÜGEN
```

Dann Container neu starten:

```bash
docker-compose down
docker-compose up -d
```

---

## Schritt 4: Entrypoint-Script erstellen

Erstelle eine neue Datei `entrypoint.sh` im Root-Verzeichnis (neben `app.py`):

```bash
#!/bin/bash
set -e

echo "Running database migrations..."
flask db upgrade

echo ""
echo "================================"
echo "Starting Gunicorn..."
echo "App running at: http://localhost:5000"
echo "================================"
echo ""
exec python -m gunicorn --bind 0.0.0.0:5000 app:app
```

**Was macht dieses Script:**
1. ✅ Führt `flask db upgrade` aus (wendet Migrationen an)
2. ✅ Startet dann Gunicorn (Production Server)
3. ✅ `set -e` stoppt bei Fehlern automatisch

---

## Schritt 5: Dockerfile aktualisieren

Öffne `Dockerfile` und ersetze die letzten Zeilen:

**Alter Stand:**
```dockerfile
EXPOSE 5000
CMD ["python", "app.py"]
```

**Neuer Stand:**
```dockerfile
# Entrypoint-Script kopieren und ausführbar machen
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Port öffnen
EXPOSE 5000

# Startbefehl mit Entrypoint-Script
CMD ["./entrypoint.sh"]
```

**Komplettes neues Dockerfile:**
```dockerfile
# Basisimage
FROM python:3.12-slim

# Arbeitsverzeichnis
WORKDIR /app

# Abhängigkeiten installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App kopieren
COPY . .

# Entrypoint-Script kopieren und ausführbar machen
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Port öffnen
EXPOSE 5000

# Startbefehl mit Entrypoint-Script
CMD ["./entrypoint.sh"]
```

---

## Schritt 6: Lokal testen

### 6.1 Neu bauen und starten

```bash
docker-compose down
docker-compose up --build
```

**Ergebete Output sollte zeigen:**
```
d-vhs-1  | Running database migrations...
d-vhs-1  | INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
d-vhs-1  | INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
d-vhs-1  | Starting Gunicorn...
d-vhs-1  | [2025-10-29 07:16:13 +0000] [1] [INFO] Starting gunicorn 21.2.0
```

### 6.2 App testen

Öffne im Browser: `http://localhost:5000`

App sollte normal funktionieren ✅

---

## Schritt 7: Erste Migration generieren

Die erste Migration speichert den "Urzustand" der Datenbank.

### 7.1 In Container gehen

```bash
docker-compose exec d-vhs bash
```

### 7.2 Initial-Migration als Baseline setzen

Bei bestehenden Datenbanken:

```bash
flask db stamp head
```

Das markiert die aktuelle Datenbank als "aktuell" ohne eine Migration zu erstellen.

### 7.3 Verifizieren

```bash
ls -la migrations/versions/
```

Sollte leer sein (keine `.py` Datei) ✅

```bash
exit
```

---

## Schritt 8: Zu Staging deployen

### 8.1 Git committen

```bash
git add .
git commit -m "Add Flask-Migrate for database versioning and auto-migration on startup"
git push origin feature/flask-migrate
```

### 8.2 Docker Image für Staging bauen

```bash
docker build -t sonoflex/dvhs:staging .
docker push sonoflex/dvhs:staging
```

### 8.3 Railway Staging redeploy

- Gehe zu Railway Dashboard
- Wähle Staging Service
- Klick "Redeploy" oder warte auf Auto-Redeploy

### 8.4 Logs in Railway überprüfen

Gehe zu: Railway → Staging Service → Logs

Du solltest sehen:
```
Running database migrations...
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
```

**✅ PostgreSQL wird verwendet (nicht SQLite)!**

### 8.5 Datenbank in Railway prüfen

- Railway → Staging PostgreSQL Datenbank
- Datenbank öffnen und Tabellen überprüfen
- Migration sollte erfolgreich angewendet sein ✅

---

## Schritt 9: Zu Production mergen

### 9.1 Nach erfolgreichem Staging-Test

```bash
# Zurück zu main Branch
git checkout main

# Feature mergen
git merge feature/flask-migrate

# Zu Production pushen
docker build -t sonoflex/dvhs:latest .
docker push sonoflex/dvhs:latest
```

### 9.2 Railway Production redeploy

- Railway → Production Service
- Klick "Redeploy"

### 9.3 Logs überprüfen

Production sollte die gleichen Migrations-Logs zeigen ✅

---

## Workflow für zukünftige Schema-Änderungen

Wenn du später eine neue Spalte oder Tabelle hinzufügst:

### Beispiel: Neue Spalte `rating` hinzufügen

#### 1. Code-Änderung in app.py

```python
class Film(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    # ... existierende Felder ...
    rating = db.Column(db.Float)  # ← NEU
```

#### 2. Feature-Branch erstellen

```bash
git checkout -b feature/add-film-rating
```

#### 3. Lokal testen

```bash
docker-compose down
docker-compose up --build
```

#### 4. Migration generieren

```bash
docker-compose exec d-vhs bash
flask db migrate -m "Add rating field to Film"
```

Das erstellt: `migrations/versions/abc123_add_rating_field_to_film.py`

#### 5. Migration lokal testen

```bash
flask db upgrade  # Anwenden
flask db downgrade  # Rollback zum Testen
flask db upgrade  # Nochmal anwenden
```

#### 6. Besitzer anpassen

```bash
exit
sudo chown -R $(whoami):$(whoami) migrations/
```

#### 7. Git committen

```bash
git add .
git commit -m "Add rating field to Film model"
git push origin feature/add-film-rating
```

#### 8. Zu Staging testen

```bash
docker build -t sonoflex/dvhs:staging .
docker push sonoflex/dvhs:staging
# Railway Staging redeploy
```

#### 9. Nach erfolgreichem Test zu Production

```bash
git checkout main
git merge feature/add-film-rating
docker build -t sonoflex/dvhs:latest .
docker push sonoflex/dvhs:latest
# Railway Production redeploy
```

---

## Best Practices

### ✅ Was du machen solltest

1. **Immer einen Feature-Branch für Schema-Änderungen erstellen**
   ```bash
   git checkout -b feature/add-new-field
   ```

2. **Migrations-Dateien in Git committen**
   - Sie gehören zu deinem Code!
   - Sind reproducierbar und versioniert

3. **Migrations lokal testen, bevor sie zu Staging gehen**
   ```bash
   flask db upgrade
   flask db downgrade
   flask db upgrade
   ```

4. **Staging-Datenbank ist dein Testfeld**
   - Test da bevor es zu Production geht
   - Production hat echte Daten!

5. **Aussagekräftige Migration Messages**
   ```bash
   # ✅ Gut
   flask db migrate -m "Add user subscription status field"
   
   # ❌ Schlecht
   flask db migrate -m "Update schema"
   ```

### ❌ Was du vermeiden solltest

1. **Keine manuellen SQL-Änderungen in Production**
   - Immer über Migrationen!

2. **Nicht die `migrations/` Ordner löschen**
   - Diese sind die Geschichte deiner Datenbank

3. **Nicht gleichzeitig Code und Datenbank ändern**
   - Erst Datenbank-Change, dann Code-Anpassung

4. **Nicht Produktions-Datenbank für Testen nutzen**
   - Dafür ist Staging da!

### 📊 Migration-Status prüfen

```bash
# Welche Migrationen sind angewendet?
docker-compose exec d-vhs bash
flask db current

# Migrationshistorie anschauen
flask db history

# Nächste Migration anschauen
flask db heads
```

---

## Troubleshooting

### Problem: "No changes in schema detected"

**Ursache:** Du hast eine neue Spalte hinzugefügt, aber Alembic sieht keine Änderung

**Lösung:** Starte den Container neu:
```bash
docker-compose down
docker-compose up --build
flask db migrate -m "Your message"
```

### Problem: "flask db: command not found"

**Ursache:** Flask-Migrate nicht installiert

**Lösung:**
```bash
pip install Flask-Migrate==4.0.5
docker-compose down
docker-compose up --build
```

### Problem: Migrations-Dateien haben falsche Besitzer (root)

**Lösung:**
```bash
sudo chown -R $(whoami):$(whoami) migrations/
```

### Problem: "FAILED: Can't drop column" (PostgreSQL)

**Ursache:** PostgreSQL ist strenger als SQLite

**Lösung:** Manuelle Anpassung in der Migration-Datei nötig, oder den ALTER-Statement korrigieren

---

## Zusammenfassung

| Aktion | Befehl |
|--------|--------|
| Initialisierung (einmalig) | `flask db init` |
| Neue Migration erstellen | `flask db migrate -m "Description"` |
| Migrationen anwenden | `flask db upgrade` |
| Migration rollback | `flask db downgrade` |
| Current Version anschauen | `flask db current` |
| History anschauen | `flask db history` |

---

**🎉 Glückwunsch! Du hast jetzt ein production-ready Datenbank-Migrations-System!**

