from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import requests
import logging
import os
import re
from datetime import datetime
from functools import wraps

# Flask Setup
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
db_path = os.path.join(os.getcwd(), "data", "filme.db")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# Logging
logging.basicConfig(level=logging.INFO)

# TMDb API Key aus environment variable
TMDB_API_KEY = os.environ.get("TMDB_API_KEY")

# Model
class Film(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    year = db.Column(db.Integer)
    beschreibung = db.Column(db.Text)
    tmdb_id = db.Column(db.String(20))
    poster_url = db.Column(db.String(500))
    besitzer = db.Column(db.String(100))
    verliehen_an = db.Column(db.String(100))
    verliehen_seit = db.Column(db.DateTime)
    genres = db.Column(db.String(500))  # Komma-separierte Liste von Genres
    wunschliste = db.Column(db.Boolean, default=True)

class Benutzer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    
    def set_password(self, password):
        """Passwort hashen und speichern"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Passwort überprüfen"""
        return check_password_hash(self.password_hash, password)

# DB initialisieren
with app.app_context():
    os.makedirs("data", exist_ok=True)
    db.create_all()
    
    # Initial-Benutzer aus .env anlegen falls noch nicht vorhanden
    if Benutzer.query.count() == 0:
        initial_users_env = os.environ.get("INITIAL_USERS", "")
        
        if initial_users_env:
            # Format: "username:password,username:password"
            for user_pair in initial_users_env.split(","):
                if ":" in user_pair:
                    username, password = user_pair.strip().split(":", 1)
                    user = Benutzer(name=username.strip())
                    user.set_password(password.strip())
                    db.session.add(user)
                    logging.info(f"Initial-Benutzer '{username}' angelegt")
            db.session.commit()
        else:
            logging.warning("INITIAL_USERS nicht in .env definiert")

# Login-Decorator
def login_erforderlich(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "benutzer_id" not in session:
            flash("Du musst dich anmelden", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

def extract_tmdb_id(input_str):
    """
    Extrahiert TMDb-ID aus verschiedenen Formaten:
    - 348 (nur ID)
    - https://www.themoviedb.org/movie/348-alien
    - https://www.themoviedb.org/movie/348
    """
    if not input_str:
        return None
    
    input_str = input_str.strip()
    
    # Wenn es eine URL ist
    url_match = re.search(r'/movie/(\d+)', input_str)
    if url_match:
        return url_match.group(1)
    
    # Wenn es nur Zahlen sind
    if input_str.isdigit():
        return input_str
    
    return None

def fetch_film_data_tmdb(tmdb_id):
    """
    Holt Filmdaten von TMDb API basierend auf TMDb-ID
    """
    if not TMDB_API_KEY:
        raise ValueError("TMDB_API_KEY nicht gesetzt")
    
    # Extrahiere die TMDb-ID
    movie_id = extract_tmdb_id(tmdb_id)
    if not movie_id:
        raise ValueError(f"Ungültige TMDb-ID: {tmdb_id}")
    
    logging.info(f"Suche Film mit TMDb-ID: {movie_id}")
    
    # Direkte Movie-API verwenden statt Find-API
    url = f"https://api.themoviedb.org/3/movie/{movie_id}"
    params = {
        "api_key": TMDB_API_KEY,
        "language": "de-DE"
    }
    
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()
    
    logging.info(f"TMDb Response: {data}")
    
    # Prüfe ob der Film gefunden wurde
    if "title" not in data:
        raise ValueError(f"Kein Film mit TMDb-ID {movie_id} gefunden")
    
    # Erstelle vollständige Poster-URL
    poster_url = None
    if data.get("poster_path"):
        poster_url = f"https://image.tmdb.org/t/p/w500{data.get('poster_path')}"
    
    # Extrahiere Genres
    genres = data.get("genres", [])
    genres_str = ", ".join([g["name"] for g in genres]) if genres else ""
    
    return {
        "title": data.get("title"),
        "release_date": data.get("release_date"),
        "overview": data.get("overview"),
        "tmdb_id": movie_id,
        "poster_url": poster_url,
        "genres": genres_str
    }

# Routen
@app.context_processor
def inject_user():
    return dict(session=session)
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        name = request.form.get("name")
        password = request.form.get("password")
        
        user = Benutzer.query.filter_by(name=name).first()
        
        if user and user.check_password(password):
            session["benutzer_id"] = user.id
            session["benutzer_name"] = user.name
            flash(f"Willkommen {name}!", "success")
            return redirect(url_for("index"))
        else:
            flash("Ungültiger Benutzername oder Passwort", "error")
    
    return render_template("login.html")

@app.route("/logout")
def logout():
    name = session.get("benutzer_name")
    session.clear()
    flash(f"Auf Wiedersehen {name}!", "info")
    return redirect(url_for("index"))


@app.route("/")
def index():
    # Filter nach Besitzer
    besitzer_filter = request.args.get("besitzer", "")
    ansicht = request.args.get("ansicht", "liste")
    
    # Filter nach Jahr (von bis)
    jahr_von = request.args.get("jahr_von", "")
    jahr_bis = request.args.get("jahr_bis", "")
    
    # Query aufbauen
    query = Film.query
    
    if besitzer_filter:
        if besitzer_filter == "ohne":
            query = query.filter(Film.besitzer.is_(None))
        else:
            query = query.filter_by(besitzer=besitzer_filter)
    
    if jahr_von:
        try:
            jahr_von_int = int(jahr_von)
            query = query.filter(Film.year >= jahr_von_int)
        except ValueError:
            pass
    
    if jahr_bis:
        try:
            jahr_bis_int = int(jahr_bis)
            query = query.filter(Film.year <= jahr_bis_int)
        except ValueError:
            pass
    
    filme = query.all()
    benutzer = Benutzer.query.order_by(Benutzer.name).all()
    
    return render_template("index.html", filme=filme, benutzer=benutzer, 
                          besitzer_filter=besitzer_filter, ansicht=ansicht,
                          jahr_von=jahr_von, jahr_bis=jahr_bis)

@app.route("/add", methods=["POST"])
@login_erforderlich
def add_film():
    tmdb_id = request.form.get("tmdb_id")
    
    if not tmdb_id:
        flash("Keine TMDb-ID angegeben", "error")
        return redirect(url_for("index"))
    
    try:
        film_data = fetch_film_data_tmdb(tmdb_id)
        
        logging.info("===== Movie Objekt =====")
        logging.info(f"Title: {film_data.get('title')}")
        logging.info(f"Year: {film_data.get('release_date', '')[:4]}")
        logging.info(f"Overview: {film_data.get('overview')}")
        logging.info(f"TMDb-ID: {film_data.get('tmdb_id')}")
        logging.info(f"Poster: {film_data.get('poster_url')}")
        logging.info(f"Genres: {film_data.get('genres')}")
        
        # Prüfe ob Film bereits existiert
        existing = Film.query.filter_by(tmdb_id=film_data.get('tmdb_id')).first()
        if existing:
            flash(f"Film '{existing.title}' ist bereits in der Sammlung", "warning")
            return redirect(url_for("index"))
        
         # Hole aktuellen Benutzer
        current_user = Benutzer.query.filter_by(id=session.get("benutzer_id")).first()
        
        film = Film(
            title=film_data.get("title"),
            year=int(film_data.get("release_date", "0")[:4]) if film_data.get("release_date") else None,
            beschreibung=film_data.get("overview", ""),
            tmdb_id=film_data.get("tmdb_id"),
            poster_url=film_data.get("poster_url"),
            genres=film_data.get("genres", ""),
            besitzer=current_user.name if current_user else None,
            wunschliste=True
        )
        
        db.session.add(film)
        db.session.commit()
        
        flash(f"Film '{film.title}' erfolgreich hinzugefügt", "success")
        
    except ValueError as e:
        logging.error(f"Validierungsfehler: {e}")
        flash(str(e), "error")
        return redirect(url_for("index"))
    
    except requests.exceptions.RequestException as e:
        logging.error(f"Netzwerkfehler bei TMDb-Abruf: {e}")
        flash("Fehler bei der Verbindung zu TMDb. Bitte später versuchen.", "error")
        return redirect(url_for("index"))
    
    except Exception as e:
        logging.error(f"Fehler beim Hinzufügen des Films: {e}")
        flash("Ein unerwarteter Fehler ist aufgetreten", "error")
        return redirect(url_for("index"))
    
    return redirect(url_for("index"))

@app.route("/film/<int:film_id>")
def film_detail(film_id):
    film = Film.query.get_or_404(film_id)
    benutzer = Benutzer.query.order_by(Benutzer.name).all()
    return render_template("detail.html", film=film, benutzer=benutzer, datetime=datetime)

@app.route("/film/<int:film_id>/besitzer", methods=["POST"])
@login_erforderlich
def update_besitzer(film_id):
    film = Film.query.get_or_404(film_id)
    besitzer = request.form.get("besitzer")
    
    if besitzer == "":
        film.besitzer = None
        flash(f"Besitzer für '{film.title}' entfernt", "success")
    else:
        user = Benutzer.query.filter_by(name=besitzer).first()
        if not user:
            flash(f"Benutzer '{besitzer}' nicht gefunden", "error")
            return redirect(url_for("film_detail", film_id=film_id))
        
        film.besitzer = besitzer
        flash(f"'{film.title}' gehört jetzt {besitzer}", "success")
    
    db.session.commit()
    return redirect(url_for("film_detail", film_id=film_id))

@app.route("/film/<int:film_id>/wunschliste", methods=["POST"])
@login_erforderlich
def toggle_wunschliste(film_id):
    film = Film.query.get_or_404(film_id)
    film.wunschliste = not film.wunschliste
    db.session.commit()
    
    if film.wunschliste:
        flash(f"'{film.title}' zur Wunschliste hinzugefügt", "success")
    else:
        flash(f"'{film.title}' von der Wunschliste entfernt", "success")
    
    return redirect(url_for("film_detail", film_id=film_id))

@app.route("/film/<int:film_id>/verleihen", methods=["POST"])
@login_erforderlich
def verleihen(film_id):
    film = Film.query.get_or_404(film_id)
    verliehen_an = request.form.get("verliehen_an")
    verliehen_datum = request.form.get("verliehen_datum")
    
    if not verliehen_an:
        flash("Bitte einen Benutzer auswählen", "error")
        return redirect(url_for("film_detail", film_id=film_id))
    
    user = Benutzer.query.filter_by(name=verliehen_an).first()
    if not user:
        flash(f"Benutzer '{verliehen_an}' nicht gefunden", "error")
        return redirect(url_for("film_detail", film_id=film_id))
    
    if film.verliehen_an:
        flash(f"Film ist bereits an {film.verliehen_an} verliehen", "warning")
        return redirect(url_for("film_detail", film_id=film_id))
    
    if verliehen_datum:
        try:
            verliehen_seit = datetime.strptime(verliehen_datum, "%Y-%m-%d")
        except ValueError:
            flash("Ungültiges Datum", "error")
            return redirect(url_for("film_detail", film_id=film_id))
    else:
        verliehen_seit = datetime.now()
    
    film.verliehen_an = verliehen_an
    film.verliehen_seit = verliehen_seit
    db.session.commit()
    
    flash(f"'{film.title}' an {verliehen_an} verliehen", "success")
    return redirect(url_for("film_detail", film_id=film_id))

@app.route("/film/<int:film_id>/zurueckgeben", methods=["POST"])
@login_erforderlich
def zurueckgeben(film_id):
    film = Film.query.get_or_404(film_id)
    
    if not film.verliehen_an:
        flash("Film ist nicht verliehen", "warning")
        return redirect(url_for("film_detail", film_id=film_id))
    
    verliehen_an = film.verliehen_an
    film.verliehen_an = None
    film.verliehen_seit = None
    db.session.commit()
    
    flash(f"'{film.title}' von {verliehen_an} zurückgegeben", "success")
    return redirect(url_for("film_detail", film_id=film_id))

@app.route("/benutzer")
@login_erforderlich
def benutzer_liste():
    benutzer = Benutzer.query.order_by(Benutzer.name).all()
    benutzer_mit_count = []
    for user in benutzer:
        filme_count = Film.query.filter_by(besitzer=user.name).count()
        benutzer_mit_count.append({
            'user': user,
            'filme_count': filme_count
        })
    return render_template("benutzer.html", benutzer_data=benutzer_mit_count)

@app.route("/benutzer/add", methods=["POST"])
@login_erforderlich
def add_benutzer():
    name = request.form.get("name", "").strip()
    password = request.form.get("password", "").strip()
    
    if not name:
        flash("Bitte einen Namen eingeben", "error")
        return redirect(url_for("benutzer_liste"))
    
    if not password:
        flash("Bitte ein Passwort eingeben", "error")
        return redirect(url_for("benutzer_liste"))
    
    existing = Benutzer.query.filter_by(name=name).first()
    if existing:
        flash(f"Benutzer '{name}' existiert bereits", "warning")
        return redirect(url_for("benutzer_liste"))
    
    user = Benutzer(name=name)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    
    flash(f"Benutzer '{name}' hinzugefügt", "success")
    return redirect(url_for("benutzer_liste"))

@app.route("/benutzer/delete/<int:user_id>", methods=["POST"])
@login_erforderlich
def delete_benutzer(user_id):
    user = Benutzer.query.get_or_404(user_id)
    name = user.name
    
    filme_count = Film.query.filter_by(besitzer=name).count()
    if filme_count > 0:
        flash(f"Benutzer '{name}' kann nicht gelöscht werden, da er noch {filme_count} Film(e) besitzt", "error")
        return redirect(url_for("benutzer_liste"))
    
    db.session.delete(user)
    db.session.commit()
    
    flash(f"Benutzer '{name}' wurde gelöscht", "success")
    return redirect(url_for("benutzer_liste"))

@app.route("/delete/<int:film_id>", methods=["POST"])
@login_erforderlich
def delete_film(film_id):
    film = Film.query.get_or_404(film_id)
    title = film.title
    db.session.delete(film)
    db.session.commit()
    flash(f"Film '{title}' wurde gelöscht", "success")
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)