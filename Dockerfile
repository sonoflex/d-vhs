# Basisimage
FROM python:3.12-slim

# Arbeitsverzeichnis
WORKDIR /app

# Abhängigkeiten installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App kopieren
COPY . .

# Port öffnen
EXPOSE 5000

# Startbefehl
CMD ["python", "app.py"]
