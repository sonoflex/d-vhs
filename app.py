from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import requests
import logging
import os
import re
from datetime import datetime
from functools import wraps
from flask_migrate import Migrate
from dotenv import load_dotenv

load_dotenv() 

# Flask Setup
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
# Debugging: Prüfe welche Datenbank verwendet wird
if os.environ.get("DATABASE_URL"):
    database_url = os.environ.get("DATABASE_URL")
    logging.info(f"✓ DATABASE_URL gefunden: {database_url[:50]}...")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    logging.info("✓ Verwende PostgreSQL")
else:
    # Local Development: SQLite
    db_path = os.path.join(os.getcwd(), "data", "filme.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    logging.warning("⚠ DATABASE_URL nicht gesetzt - verwende SQLite (Daten gehen nach Deployment verloren!)")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)
migrate = Migrate(app, db)

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

class LendingRequest(db.Model):
    """Modell für Film-Ausleih-Anfragen"""
    id = db.Column(db.Integer, primary_key=True)
    borrower_id = db.Column(db.Integer, db.ForeignKey('benutzer.id'), nullable=False)  # Wer möchte leihen?
    owner_id = db.Column(db.Integer, db.ForeignKey('benutzer.id'), nullable=False)      # Wer besitzt den Film?
    film_id = db.Column(db.Integer, db.ForeignKey('film.id'), nullable=False)           # Welcher Film?
    
    # Relationships für einfachere Abfragen
    borrower = db.relationship('Benutzer', foreign_keys=[borrower_id])
    owner = db.relationship('Benutzer', foreign_keys=[owner_id])
    film = db.relationship('Film')
    
    def __repr__(self):
        return f'<LendingRequest {self.borrower.name} → {self.owner.name}: {self.film.title}>'

class Benutzer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    
    def set_password(self, password):
        """Passwort hashen und speichern"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Passwort überprüfen"""
        return check_password_hash(self.password_hash, password)

# DB initialisieren - wird durch Flask-Migrate verwaltet, deher gibt es das nicht. Initiale Nutzer werden durch ein CLI Comand erstellt

# Login-Decorator
def login_erforderlich(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "benutzer_id" not in session:
            flash("Du musst dich anmelden", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

def admin_erforderlich(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "benutzer_id" not in session:
            flash("Du musst dich anmelden", "warning")
            return redirect(url_for("login"))
        
        user = Benutzer.query.filter_by(id=session.get("benutzer_id")).first()
        if not user or not user.is_admin:
            flash("Du hast keine Admin-Berechtigung", "warning")
            return redirect(url_for("index"))
        
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

@app.cli.command()
def init_users():
    """Initialize admin users from INITIAL_USERS environment variable"""
    with app.app_context():
        os.makedirs("data", exist_ok=True)
        
        if Benutzer.query.count() == 0:
            initial_users_env = os.environ.get("INITIAL_USERS", "")
            
            if initial_users_env:
                # Format: "username:password,username:password"
                for user_pair in initial_users_env.split(","):
                    if ":" in user_pair:
                        username, password = user_pair.strip().split(":", 1)
                        user = Benutzer(name=username.strip())
                        user.set_password(password.strip())
                        user.is_admin = True
                        db.session.add(user)
                        logging.info(f"Initial-Admin-Benutzer '{username}' angelegt")
                db.session.commit()
            else:
                logging.warning("INITIAL_USERS nicht in .env definiert")

# Routen
@app.context_processor
def inject_user():
    user_admin = False
    if session.get("benutzer_id"):
        user = Benutzer.query.filter_by(id=session.get("benutzer_id")).first()
        user_admin = user.is_admin if user else False
    
    return dict(session=session, user_admin=user_admin)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        name = request.form.get("name")
        password = request.form.get("password")
        
        user = Benutzer.query.filter_by(name=name).first()
        
        if user and user.check_password(password):
            session["benutzer_id"] = user.id
            session["benutzer_name"] = user.name
            session["benutzer_admin"] = user.is_admin
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
    ansicht = request.args.get("ansicht", "kacheln")
    
    # Filter nach Jahr (von bis)
    jahr_von = request.args.get("jahr_von", "")
    jahr_bis = request.args.get("jahr_bis", "")
    
    # Filter nach Wunschliste
    wunschliste_filter = request.args.get("wunschliste", "")
    
    # Filter nach Genre
    genre_filter = request.args.get("genre", "")
    
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
    
    if wunschliste_filter == "ja":
        query = query.filter_by(wunschliste=True)
    elif wunschliste_filter == "nein":
        query = query.filter_by(wunschliste=False)
    
    if genre_filter:
        # Filter nach Genre (case-insensitive, weil Genres komma-separiert sind)
        query = query.filter(Film.genres.ilike(f"%{genre_filter}%"))
    
    filme = query.order_by(Film.year.desc()).all()
    benutzer = Benutzer.query.order_by(Benutzer.name).all()
    
    # Sammle alle Genres aus den Filmen für die Dropdown
    all_genres = set()
    all_films = Film.query.all()
    for film in all_films:
        if film.genres:
            for genre in film.genres.split(", "):
                all_genres.add(genre.strip())
    all_genres = sorted(list(all_genres))
    
    return render_template("index.html", filme=filme, benutzer=benutzer, 
                          besitzer_filter=besitzer_filter, ansicht=ansicht,
                          jahr_von=jahr_von, jahr_bis=jahr_bis,
                          wunschliste_filter=wunschliste_filter,
                          genre_filter=genre_filter, all_genres=all_genres)

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
        
        # Prüfe welcher Button geklickt wurde
        action = request.form.get("action", "have")
        is_wishlist = (action == "wishlist")
        
        film = Film(
            title=film_data.get("title"),
            year=int(film_data.get("release_date", "0")[:4]) if film_data.get("release_date") else None,
            beschreibung=film_data.get("overview", ""),
            tmdb_id=film_data.get("tmdb_id"),
            poster_url=film_data.get("poster_url"),
            genres=film_data.get("genres", ""),
            besitzer=current_user.name if current_user else None,
            wunschliste=is_wishlist
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
    lending_requests = LendingRequest.query.filter_by(film_id=film_id).all()
    
    # Prüfe ob aktueller Benutzer bereits eine Anfrage gestellt hat
    user_has_request = False
    if session.get('benutzer_name'):
        user_has_request = any(req.borrower.name == session.get('benutzer_name') for req in lending_requests)
    
    return render_template("detail.html", film=film, benutzer=benutzer, lending_requests=lending_requests, user_has_request=user_has_request, datetime=datetime)

@app.route("/film/<int:film_id>/besitzer", methods=["POST"])
@login_erforderlich
@admin_erforderlich
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

     # Lösche die Ausleih-Anfrage für diesen Film von dem Benutzer, an den verliehen wird
    borrower = Benutzer.query.filter_by(name=verliehen_an).first()
    if borrower:
        LendingRequest.query.filter_by(film_id=film_id, borrower_id=borrower.id).delete()

    db.session.commit()
    
    next_page = request.form.get('next', 'film_detail')
    if next_page == 'leihboard':
        return redirect(url_for('leihboard'))
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
    
    next_page = request.form.get('next', 'film_detail')
    if next_page == 'leihboard':
        return redirect(url_for('leihboard'))
    return redirect(url_for("film_detail", film_id=film_id))

@app.route('/film/<int:film_id>/request-lending', methods=['POST'])
def request_lending(film_id):
    # Prüfe ob User angemeldet ist
    if 'benutzer_name' not in session:
        flash('Du musst angemeldet sein um einen Film auszuleihen!', 'danger')
        return redirect(url_for('login'))
    
    benutzer = Benutzer.query.filter_by(name=session['benutzer_name']).first()
    if not benutzer:
        flash('Benutzer nicht gefunden!', 'danger')
        return redirect(url_for('index'))
    
    film = Film.query.get_or_404(film_id)
    
    # Prüfungen
    if not film.besitzer: 
        return redirect(url_for('film_detail', film_id=film_id))
    
    if film.wunschliste:
        return redirect(url_for('film_detail', film_id=film_id))
    
    if film.verliehen_an:
        return redirect(url_for('film_detail', film_id=film_id))
    
    if film.besitzer == benutzer.name:
        return redirect(url_for('film_detail', film_id=film_id))
    existing_request = LendingRequest.query.filter_by(
        film_id=film_id, 
        borrower_id=benutzer.id
    ).first()
    
    if existing_request:
        return redirect(url_for('film_detail', film_id=film_id))
    
    owner = Benutzer.query.filter_by(name=film.besitzer).first()
    if not owner:
        return redirect(url_for('film_detail', film_id=film_id))
    # Neue Anfrage erstellen
    lending_request = LendingRequest(
        film_id=film_id,
        borrower_id=benutzer.id,
        owner_id=owner.id
    )
    db.session.add(lending_request)
    db.session.commit()
    
    return redirect(url_for('film_detail', film_id=film_id))

@app.route('/lending-request/<int:request_id>/delete', methods=['POST'])
@login_erforderlich
def delete_lending_request(request_id):
    """Löscht eine Ausleih-Anfrage"""
    lending_request = LendingRequest.query.get_or_404(request_id)
    
    film_id = lending_request.film_id
    
    db.session.delete(lending_request)
    db.session.commit()

    next_page = request.form.get('next', 'film_detail')
    if next_page == 'leihboard':
        return redirect(url_for('leihboard'))
    return redirect(url_for('film_detail', film_id=film_id))

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
@admin_erforderlich
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
@admin_erforderlich
def delete_benutzer(user_id):
    user = Benutzer.query.get_or_404(user_id)
    name = user.name
    
    filme_count = Film.query.filter_by(besitzer=name).count()
    if filme_count > 0:
        flash(f"Benutzer '{name}' kann nicht gelöscht werden, da er noch {filme_count} Film(e) besitzt", "error")
        return redirect(url_for("benutzer_liste"))
    
    # Lösche alle Leihanfragen des Benutzers (als Anfragender oder als Besitzer)
    LendingRequest.query.filter((LendingRequest.borrower_id == user_id) | (LendingRequest.owner_id == user_id)).delete()

    db.session.delete(user)
    db.session.commit()
    
    flash(f"Benutzer '{name}' wurde gelöscht", "success")
    return redirect(url_for("benutzer_liste"))

@app.route('/change-password', methods=['POST'])
@login_erforderlich
def change_password():
    """Ändert das Passwort des eingeloggten Nutzers"""
    old_password = request.form.get('old_password')
    new_password = request.form.get('new_password')
    new_password_confirm = request.form.get('new_password_confirm')
    
    current_user = Benutzer.query.get(session['benutzer_id'])
    
    # Prüfe altes Passwort
    if not current_user.check_password(old_password):
        flash('Altes Passwort ist falsch', 'error')
        return redirect(url_for('benutzer_liste'))
    
    # Prüfe ob neue Passwörter identisch sind
    if new_password != new_password_confirm:
        flash('Neue Passwörter stimmen nicht überein', 'error')
        return redirect(url_for('benutzer_liste'))
    
    # Prüfe ob neues Passwort nicht leer ist
    if not new_password or len(new_password) < 3:
        flash('Neues Passwort muss mindestens 3 Zeichen lang sein', 'error')
        return redirect(url_for('benutzer_liste'))
    
    # Passwort ändern
    current_user.set_password(new_password)
    db.session.commit()
    
    flash('Passwort erfolgreich geändert', 'success')
    return redirect(url_for('benutzer_liste'))

@app.route("/delete/<int:film_id>", methods=["POST"])
@login_erforderlich
def delete_film(film_id):
    film = Film.query.get_or_404(film_id)
    title = film.title
    current_user = Benutzer.query.get(session['benutzer_id'])
    
    # Prüfe ob Nutzer Admin oder Besitzer ist
    if not current_user.is_admin and current_user.name != film.besitzer:
        flash('Du darfst diesen Film nicht löschen!', 'danger')
        return redirect(url_for('film_detail', film_id=film_id))

    # Lösche alle Ausleih-Anfragen für diesen Film
    LendingRequest.query.filter_by(film_id=film_id).delete()

    db.session.delete(film)
    db.session.commit()
    flash(f"Film '{title}' wurde gelöscht", "success")
    return redirect(url_for("index"))

@app.route('/leihboard')
@login_erforderlich
def leihboard():
    """Zeigt das Leih Board mit Anfragen an den Nutzer, von dem Nutzer und verliehenen Filmen"""
    current_user = Benutzer.query.get(session['benutzer_id'])
    
    # Anfragen an den eingeloggten Nutzer (er ist Besitzer)
    requests_to_me = LendingRequest.query.filter_by(owner_id=current_user.id).all()
    requests_to_me = sorted(requests_to_me, key=lambda x: x.borrower.name)
    
    # Anfragen von dem eingeloggten Nutzer (er ist Anfragender)
    requests_from_me = LendingRequest.query.filter_by(borrower_id=current_user.id).all()
    requests_from_me = sorted(requests_from_me, key=lambda x: x.owner.name)
    
    # Filme die vom eingeloggten Nutzer verliehen sind
    lent_films = Film.query.filter_by(besitzer=current_user.name).filter(Film.verliehen_an.isnot(None)).all()
    lent_films = sorted(lent_films, key=lambda x: x.verliehen_an or "")
    
    # Filme die der eingeloggte Nutzer von anderen geliehen hat
    borrowed_films = Film.query.filter_by(verliehen_an=current_user.name).all()
    borrowed_films = sorted(borrowed_films, key=lambda x: x.besitzer or "")
    
    return render_template('leihboard.html', requests_to_me=requests_to_me, requests_from_me=requests_from_me, lent_films=lent_films, borrowed_films=borrowed_films, datetime=datetime)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)