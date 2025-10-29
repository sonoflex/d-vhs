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