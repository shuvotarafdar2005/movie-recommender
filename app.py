import os
from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session, jsonify
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash
from helpers import apology, login_required
import requests

# Configure app
app = Flask(__name__)
app.secret_key = os.urandom(24)

# Auto-reload templates
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Custom filters
app.jinja_env.filters["usd"] = lambda x: f"${x:,.2f}"

# Configure session
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# DB
db = SQL("sqlite:///movies.db")

# API Key (set your own TMDB key)
TMDB_API_KEY = "334f1171fdf4b4896faeb8dd6a672809"

@app.route("/")
@login_required
def index():
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")

        if not username or not password or not confirmation:
            return apology("Missing fields", 400)

        if password != confirmation:
            return apology("Passwords must match", 400)

        hash_pw = generate_password_hash(password)

        try:
            db.execute("INSERT INTO users (username, hash) VALUES (?, ?)", username, hash_pw)
        except:
            return apology("Username already exists", 400)

        return redirect("/login")

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    session.clear()

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        rows = db.execute("SELECT * FROM users WHERE username = ?", username)

        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], password):
            return apology("Invalid username/password", 403)

        session["user_id"] = rows[0]["id"]
        return redirect("/")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/search", methods=["GET", "POST"])
@login_required
def search():
    if request.method == "POST":
        query = request.form.get("query")
        if not query:
            return apology("Search term required", 400)

        response = requests.get(
            "https://api.themoviedb.org/3/search/movie",
            params={
                "api_key": TMDB_API_KEY,
                "query": query
            }
        )

        if response.status_code != 200:
            return apology("API error", 500)

        results = response.json()["results"]

        return render_template("search.html", movies=results, query=query)

    return render_template("search.html")

@app.route("/movie/<int:movie_id>", methods=["GET", "POST"])
@login_required
def movie(movie_id):
    # Handle rating submission
    if request.method == "POST":
        rating = int(request.form.get("rating"))
        user_id = session["user_id"]

        # Check if already rated
        existing = db.execute("SELECT * FROM ratings WHERE user_id = ? AND movie_id = ?", user_id, movie_id)
        if existing:
            db.execute("UPDATE ratings SET rating = ? WHERE user_id = ? AND movie_id = ?", rating, user_id, movie_id)
        else:
            db.execute("INSERT INTO ratings (user_id, movie_id, rating) VALUES (?, ?, ?)", user_id, movie_id, rating)

        flash("Rating submitted!", "success")
        return redirect(f"/movie/{movie_id}")

    # Fetch movie details from TMDB
    response = requests.get(
        f"https://api.themoviedb.org/3/movie/{movie_id}",
        params={"api_key": TMDB_API_KEY}
    )
    movie = response.json()

    # Get current user's rating if exists
    rating = db.execute("SELECT rating FROM ratings WHERE user_id = ? AND movie_id = ?", session["user_id"], movie_id)
    user_rating = rating[0]["rating"] if rating else None

    return render_template("movie.html", movie=movie, user_rating=user_rating)

@app.route("/recommend")
@login_required
def recommend():
    # Get user's top-rated movie genres
    rows = db.execute("""
      SELECT movie_id, rating FROM ratings
      WHERE user_id = ?
      ORDER BY rating DESC LIMIT 20
    """, session["user_id"])
    if not rows:
        flash("You need to rate some movies first!", "warning")
        return redirect("/")

    genre_counts = {}
    for row in rows:
        resp = requests.get(
          f"https://api.themoviedb.org/3/movie/{row['movie_id']}",
          params={"api_key": TMDB_API_KEY}
        ).json()
        for g in resp.get("genres", []):
            genre_counts[g["id"]] = genre_counts.get(g["id"], 0) + 1

    top_genres = sorted(genre_counts, key=genre_counts.get, reverse=True)[:3]

    # Fetch recommendations from TMDb
    resp = requests.get("https://api.themoviedb.org/3/discover/movie",
      params={
        "api_key": TMDB_API_KEY,
        "with_genres": ",".join(map(str, top_genres)),
        "sort_by": "popularity.desc",
        "page": 1
      }).json()

    movies = resp.get("results", [])[:20]
    return render_template("recommend.html", movies=movies)

@app.route("/ratings")
@login_required
def ratings():
    rows = db.execute("SELECT movie_id, rating FROM ratings WHERE user_id = ?", session["user_id"])
    movies = []
    for r in rows:
        m = requests.get(
          f"https://api.themoviedb.org/3/movie/{r['movie_id']}",
          params={"api_key": TMDB_API_KEY}
        ).json()
        m['your_rating'] = r['rating']
        movies.append(m)
    return render_template("ratings.html", movies=movies)

@app.route("/trending")
@login_required
def trending():
    rows = db.execute("""
      SELECT movie_id, COUNT(*) AS cnt
      FROM ratings GROUP BY movie_id
      ORDER BY cnt DESC LIMIT 20
    """)
    movies = []
    for r in rows:
        m = requests.get(
          f"https://api.themoviedb.org/3/movie/{r['movie_id']}",
          params={"api_key": TMDB_API_KEY}
        ).json()
        m['count'] = r['cnt']
        movies.append(m)
    return render_template("trending.html", movies=movies)

@app.route("/suggest")
def suggest():
    query = request.args.get("q", "")
    if not query:
        return jsonify([])

    response = requests.get(
        "https://api.themoviedb.org/3/search/movie",
        params={
            "api_key": TMDB_API_KEY,
            "query": query
        }
    )

    if response.status_code != 200:
        return jsonify([])

    results = response.json().get("results", [])[:5]
    suggestions = [movie["title"] for movie in results]
    return jsonify(suggestions)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
