import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
from flask import Flask, render_template, request, redirect, url_for, session, flash
from datetime import datetime
import os
from werkzeug.utils import secure_filename
from models import (
    db, User, Group, Membership, Post,
    Comment, PostLike, CommentLike, GroupMessage,
    GroupJoinRequest, Notification
)
from sqlalchemy import or_
import requests
from flask import jsonify
import random
import string
import re
from sentence_transformers import SentenceTransformer
import numpy as np
import json
import faiss
from pathlib import Path
from datetime import datetime



app = Flask(__name__)
app.secret_key = "m2-mysql-secret-key"

DB_USER = "root"
DB_PASSWORD = "00000000"
DB_HOST = "127.0.0.1"
DB_PORT = "3306"
DB_NAME = "fishing_platform"

app.config["SQLALCHEMY_DATABASE_URI"] = (
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

@app.context_processor
def inject_notification_count():
    current_user = get_current_user()

    if not current_user:
        return {
            "unread_notification_count": 0
        }

    unread_count = Notification.query.filter_by(
        user_id=current_user.id,
        is_read=False
    ).count()

    return {
        "unread_notification_count": unread_count
    }

UPLOAD_FOLDER = "static/uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

#embedding
#embedding_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
_embedding_model = None

def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    return _embedding_model

EMBED_DIR = Path("embedding_cache")
PUBLIC_INDEX_PATH = EMBED_DIR / "public_posts.index"
PUBLIC_META_PATH = EMBED_DIR / "public_posts_meta.json"

GROUP_INDEX_DIR = EMBED_DIR / "groups"
GROUP_META_DIR = EMBED_DIR / "groups_meta"

EMBED_DIR.mkdir(exist_ok=True)
GROUP_INDEX_DIR.mkdir(exist_ok=True)
GROUP_META_DIR.mkdir(exist_ok=True)

def get_embedding_dim():
    return get_embedding_model().get_embedding_dimension()

#encode
def encode_texts(texts):
    if not texts:
        return np.zeros((0, get_embedding_dim()), dtype="float32")
    return get_embedding_model().encode(
        texts,
        convert_to_numpy=True,
        normalize_embeddings=True
    ).astype("float32")


def encode_query(text):
    return get_embedding_model().encode(
        text,
        convert_to_numpy=True,
        normalize_embeddings=True
    ).astype("float32")

#faiss
def create_faiss_index():
    dim = get_embedding_dim()
    return faiss.IndexIDMap(faiss.IndexFlatIP(dim))


def save_index(index, index_path):
    faiss.write_index(index, str(index_path))


def load_index(index_path):
    if not index_path.exists():
        return None
    return faiss.read_index(str(index_path))


def save_metadata(meta, meta_path):
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def load_metadata(meta_path):
    if not meta_path.exists():
        return {}
    with open(meta_path, "r", encoding="utf-8") as f:
        return json.load(f)
    
#index for public post
def rebuild_public_post_index():
    posts = Post.query.filter_by(
        visibility="public",
        group_id=None
    ).all()

    index = create_faiss_index()
    meta = {}

    if posts:
        texts = [build_post_text(post) for post in posts]
        embeddings = encode_texts(texts)
        ids = np.array([post.id for post in posts], dtype="int64")

        index.add_with_ids(embeddings, ids)

        for post in posts:
            meta[str(post.id)] = {
                "title": post.title,
                "visibility": post.visibility,
                "group_id": post.group_id
            }

    save_index(index, PUBLIC_INDEX_PATH)
    save_metadata(meta, PUBLIC_META_PATH)

#index for group post
def get_group_index_path(group_id):
    return GROUP_INDEX_DIR / f"group_{group_id}.index"


def get_group_meta_path(group_id):
    return GROUP_META_DIR / f"group_{group_id}_meta.json"


def rebuild_group_post_index(group_id):
    posts = Post.query.filter_by(
        visibility="group",
        group_id=group_id
    ).all()

    index = create_faiss_index()
    meta = {}

    if posts:
        texts = [build_post_text(post) for post in posts]
        embeddings = encode_texts(texts)
        ids = np.array([post.id for post in posts], dtype="int64")

        index.add_with_ids(embeddings, ids)

        for post in posts:
            meta[str(post.id)] = {
                "title": post.title,
                "visibility": post.visibility,
                "group_id": post.group_id
            }

    save_index(index, get_group_index_path(group_id))
    save_metadata(meta, get_group_meta_path(group_id))

#index for comments
def rebuild_public_comment_index():
    comments = Comment.query.join(Post).filter(
        Post.visibility == "public",
        Post.group_id.is_(None)
    ).all()

    index = create_faiss_index()
    meta = {}

    if comments:
        texts = [build_comment_text(comment) for comment in comments]
        embeddings = encode_texts(texts)
        ids = np.array([comment.id for comment in comments], dtype="int64")

        index.add_with_ids(embeddings, ids)

        for comment in comments:
            meta[str(comment.id)] = {
                "post_id": comment.post_id,
                "author_id": comment.author_id
            }

    save_index(index, PUBLIC_COMMENT_INDEX_PATH)
    save_metadata(meta, PUBLIC_COMMENT_META_PATH)

def retrieve_relevant_public_comments_semantic(query, top_k=15, min_score=0.35):
    index = load_index(PUBLIC_COMMENT_INDEX_PATH)
    if index is None or index.ntotal == 0:
        return []

    query_vec = encode_query(query).reshape(1, -1)
    scores, ids = index.search(query_vec, top_k)

    results = []
    for score, comment_id in zip(scores[0], ids[0]):
        if comment_id == -1:
            continue
        if float(score) < min_score:
            continue

        comment = db.session.get(Comment, int(comment_id))
        if comment is not None:
            results.append(comment)

    return results

def retrieve_relevant_public_comments(query, top_k=15):
    semantic_results = retrieve_relevant_public_comments_semantic(query, top_k=top_k)
    if semantic_results:
        return semantic_results
    return retrieve_relevant_public_comments_keyword(query, top_k=top_k)

#index for group message
def build_group_message_text(message):
    return f"""
Message: {message.content or ''}
Author: {message.author.username if message.author else ''}
""".strip()

GROUP_MESSAGE_INDEX_DIR = EMBED_DIR / "group_messages"
GROUP_MESSAGE_META_DIR = EMBED_DIR / "group_messages_meta"

GROUP_MESSAGE_INDEX_DIR.mkdir(exist_ok=True)
GROUP_MESSAGE_META_DIR.mkdir(exist_ok=True)

def get_group_message_index_path(group_id):
    return GROUP_MESSAGE_INDEX_DIR / f"group_{group_id}_messages.index"


def get_group_message_meta_path(group_id):
    return GROUP_MESSAGE_META_DIR / f"group_{group_id}_messages_meta.json"

def rebuild_group_message_index(group_id):
    messages = GroupMessage.query.filter_by(group_id=group_id).all()

    index = create_faiss_index()
    meta = {}

    if messages:
        texts = [build_group_message_text(message) for message in messages]
        embeddings = encode_texts(texts)
        ids = np.array([message.id for message in messages], dtype="int64")

        index.add_with_ids(embeddings, ids)

        for message in messages:
            meta[str(message.id)] = {
                "group_id": message.group_id,
                "author_id": message.author_id
            }

    save_index(index, get_group_message_index_path(group_id))
    save_metadata(meta, get_group_message_meta_path(group_id))

def retrieve_relevant_group_messages_semantic(group_id, query, top_k=15, min_score=0.35):
    index = load_index(get_group_message_index_path(group_id))
    if index is None or index.ntotal == 0:
        return []

    query_vec = encode_query(query).reshape(1, -1)
    scores, ids = index.search(query_vec, top_k)

    results = []
    for score, message_id in zip(scores[0], ids[0]):
        if message_id == -1:
            continue
        if float(score) < min_score:
            continue

        message = db.session.get(GroupMessage, int(message_id))
        if message is not None and message.group_id == group_id:
            results.append(message)

    return results

def retrieve_relevant_group_messages(group_id, query, top_k=15):
    semantic_results = retrieve_relevant_group_messages_semantic(group_id, query, top_k=top_k)
    if semantic_results:
        return semantic_results
    return retrieve_relevant_group_messages_keyword(group_id, query, top_k=top_k)

#add index
def add_post_to_public_index(post):
    if post.visibility != "public" or post.group_id is not None:
        return

    index = load_index(PUBLIC_INDEX_PATH)
    if index is None:
        index = create_faiss_index()

    text = build_post_text(post)
    emb = encode_texts([text])
    ids = np.array([post.id], dtype="int64")

    # 如果已经存在同 id，先删再加，避免重复
    index.remove_ids(ids)
    index.add_with_ids(emb, ids)
    save_index(index, PUBLIC_INDEX_PATH)

    meta = load_metadata(PUBLIC_META_PATH)
    meta[str(post.id)] = {
        "title": post.title,
        "visibility": post.visibility,
        "group_id": post.group_id
    }
    save_metadata(meta, PUBLIC_META_PATH)


def add_post_to_group_index(post):
    if post.visibility != "group" or not post.group_id:
        return

    index_path = get_group_index_path(post.group_id)
    meta_path = get_group_meta_path(post.group_id)

    index = load_index(index_path)
    if index is None:
        index = create_faiss_index()

    text = build_post_text(post)
    emb = encode_texts([text])
    ids = np.array([post.id], dtype="int64")

    index.remove_ids(ids)
    index.add_with_ids(emb, ids)
    save_index(index, index_path)

    meta = load_metadata(meta_path)
    meta[str(post.id)] = {
        "title": post.title,
        "visibility": post.visibility,
        "group_id": post.group_id
    }
    save_metadata(meta, meta_path)

def add_comment_to_public_index(comment):
    if not comment.post:
        return
    if comment.post.visibility != "public" or comment.post.group_id is not None:
        return

    index = load_index(PUBLIC_COMMENT_INDEX_PATH)
    if index is None:
        index = create_faiss_index()

    text = build_comment_text(comment)
    emb = encode_texts([text])
    ids = np.array([comment.id], dtype="int64")

    index.remove_ids(ids)
    index.add_with_ids(emb, ids)
    save_index(index, PUBLIC_COMMENT_INDEX_PATH)

    meta = load_metadata(PUBLIC_COMMENT_META_PATH)
    meta[str(comment.id)] = {
        "post_id": comment.post_id,
        "author_id": comment.author_id
    }
    save_metadata(meta, PUBLIC_COMMENT_META_PATH)

def add_group_message_to_index(message):
    if not message.group_id:
        return

    index_path = get_group_message_index_path(message.group_id)
    meta_path = get_group_message_meta_path(message.group_id)

    index = load_index(index_path)
    if index is None:
        index = create_faiss_index()

    text = build_group_message_text(message)
    emb = encode_texts([text])
    ids = np.array([message.id], dtype="int64")

    index.remove_ids(ids)
    index.add_with_ids(emb, ids)
    save_index(index, index_path)

    meta = load_metadata(meta_path)
    meta[str(message.id)] = {
        "group_id": message.group_id,
        "author_id": message.author_id
    }
    save_metadata(meta, meta_path)

#delete index
def remove_post_from_public_index(post_id):
    index = load_index(PUBLIC_INDEX_PATH)
    if index is not None:
        ids = np.array([post_id], dtype="int64")
        index.remove_ids(ids)
        save_index(index, PUBLIC_INDEX_PATH)

    meta = load_metadata(PUBLIC_META_PATH)
    meta.pop(str(post_id), None)
    save_metadata(meta, PUBLIC_META_PATH)


def remove_post_from_group_index(group_id, post_id):
    index_path = get_group_index_path(group_id)
    meta_path = get_group_meta_path(group_id)

    index = load_index(index_path)
    if index is not None:
        ids = np.array([post_id], dtype="int64")
        index.remove_ids(ids)
        save_index(index, index_path)

    meta = load_metadata(meta_path)
    meta.pop(str(post_id), None)
    save_metadata(meta, meta_path)

def remove_comment_from_public_index(comment_id):
    index = load_index(PUBLIC_COMMENT_INDEX_PATH)
    if index is not None:
        ids = np.array([comment_id], dtype="int64")
        index.remove_ids(ids)
        save_index(index, PUBLIC_COMMENT_INDEX_PATH)

    meta = load_metadata(PUBLIC_COMMENT_META_PATH)
    meta.pop(str(comment_id), None)
    save_metadata(meta, PUBLIC_COMMENT_META_PATH)

def remove_group_message_from_index(group_id, message_id):
    index_path = get_group_message_index_path(group_id)
    meta_path = get_group_message_meta_path(group_id)

    index = load_index(index_path)
    if index is not None:
        ids = np.array([message_id], dtype="int64")
        index.remove_ids(ids)
        save_index(index, index_path)

    meta = load_metadata(meta_path)
    meta.pop(str(message_id), None)
    save_metadata(meta, meta_path)

#add comment & message to embeddings
def build_comment_text(comment):
    return f"""
Comment: {comment.content or ''}
Post Title: {comment.post.title if comment.post else ''}
Post Content: {comment.post.content if comment.post else ''}
""".strip()

PUBLIC_COMMENT_INDEX_PATH = EMBED_DIR / "public_comments.index"
PUBLIC_COMMENT_META_PATH = EMBED_DIR / "public_comments_meta.json"

#main
def build_post_text(post):
    return f"""
Title: {post.title or ''}
Content: {post.content or ''}
Location: {post.location or ''}
""".strip()

def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.session.get(User, user_id)


def is_logged_in():
    return "username" in session

def seed_groups():
    if Group.query.first():
        return

    demo_user = User.query.filter_by(username="demo_creator").first()

    if not demo_user:
        demo_user = User(username="demo_creator", password="123456")
        db.session.add(demo_user)
        db.session.commit()
        db.session.refresh(demo_user)

    demo_groups = [
        Group(
            name="San Diego Charters",
            description="Discussions about charter fishing trips in San Diego",
            group_type="public_open",
            creator=demo_user,
            invite_code=None
        ),
        Group(
            name="LA Shore Fishing",
            description="Local shore fishing reports and tips in Los Angeles",
            group_type="public_open",
            creator=demo_user,
            invite_code=None
        ),
        Group(
            name="Tackle Tips",
            description="Talk about rods, reels, bait, and tackle setups",
            group_type="public_open",
            creator=demo_user,
            invite_code=None
        ),
        Group(
            name="Yellowtail Reports",
            description="Share yellowtail catches, methods, and trip reports",
            group_type="public_open",
            creator=demo_user,
            invite_code=None
        ),
        Group(
            name="Beginner Questions",
            description="A place for new anglers to ask beginner-friendly questions",
            group_type="public_open",
            creator=demo_user,
            invite_code=None
        ),
    ]

    db.session.add_all(demo_groups)
    db.session.commit()

def normalize_term(term):
    term = term.lower()
    simple_map = {
        "caught": "catch",
        "catching": "catch",
        "fishes": "fish",
        "fishing": "fish"
    }
    return simple_map.get(term, term)

def extract_search_terms(query):
    stop_words = {
        "how", "what", "where", "when", "why", "is", "are", "to", "the", "a", "an",
        "do", "does", "did", "i", "you", "we", "they", "can", "could", "should",
        "would", "about", "for", "of", "in", "on", "at", "with", "tell", "me"
    }

    words = re.findall(r"\w+", query.lower())
    terms = [normalize_term(w) for w in words if w not in stop_words and len(w) > 2]
    return terms

def score_post(post, terms):
    score = 0
    title = (post.title or "").lower()
    content = (post.content or "").lower()
    location = (post.location or "").lower()

    for term in terms:
        if term in title:
            score += 3
        if term in content:
            score += 2
        if term in location:
            score += 2

    return score

#public ai
def retrieve_relevant_public_posts_keyword(query, top_k=10):
    terms = extract_search_terms(query)

    posts = Post.query.filter_by(
        visibility="public",
        group_id=None
    ).all()

    scored = []
    for post in posts:
        score = score_post(post, terms)
        if score > 0:
            scored.append((score, post))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [post for score, post in scored[:top_k]]

def retrieve_relevant_public_posts_semantic(query, top_k=10, min_score=0.35):
    index = load_index(PUBLIC_INDEX_PATH)
    if index is None or index.ntotal == 0:
        return []

    query_vec = encode_query(query).reshape(1, -1)
    scores, ids = index.search(query_vec, top_k)

    results = []
    for score, post_id in zip(scores[0], ids[0]):
        if post_id == -1:
            continue
        if float(score) < min_score:
            continue

        post = db.session.get(Post, int(post_id))
        if post is not None:
            results.append(post)

    return results

def retrieve_relevant_public_posts(query, top_k=10):
    semantic_results = retrieve_relevant_public_posts_semantic(query, top_k=top_k)
    if semantic_results:
        return semantic_results
    return retrieve_relevant_public_posts_keyword(query, top_k=top_k)

def score_comment(comment, terms):
    score = 0
    content = (comment.content or "").lower()

    for term in terms:
        if term in content:
            score += 2

    return score

def retrieve_relevant_public_comments_keyword(query, top_k=15):
    terms = extract_search_terms(query)

    comments = Comment.query.join(Post).filter(
        Post.visibility == "public",
        Post.group_id.is_(None)
    ).all()

    scored = []
    for comment in comments:
        score = score_comment(comment, terms)
        if score > 0:
            scored.append((score, comment))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [comment for score, comment in scored[:top_k]]



#group ai
def retrieve_relevant_group_posts_keyword(group_id, query, top_k=5):
    terms = extract_search_terms(query)

    posts = Post.query.filter_by(
        group_id=group_id,
        visibility="group"
    ).all()

    scored = []
    for post in posts:
        score = score_post(post, terms)
        if score > 0:
            scored.append((score, post))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [post for score, post in scored[:top_k]]

def retrieve_relevant_group_posts_semantic(group_id, query, top_k=10, min_score=0.35):
    index_path = get_group_index_path(group_id)
    index = load_index(index_path)

    if index is None or index.ntotal == 0:
        return []

    query_vec = encode_query(query).reshape(1, -1)
    scores, ids = index.search(query_vec, top_k)

    results = []
    for score, post_id in zip(scores[0], ids[0]):
        if post_id == -1:
            continue
        if float(score) < min_score:
            continue

        post = db.session.get(Post, int(post_id))
        if post is not None and post.group_id == group_id and post.visibility == "group":
            results.append(post)

    return results

def retrieve_relevant_group_posts(group_id, query, top_k=10):
    semantic_results = retrieve_relevant_group_posts_semantic(group_id, query, top_k=top_k)
    if semantic_results:
        return semantic_results
    return retrieve_relevant_group_posts_keyword(group_id, query, top_k=top_k)


def score_message(message, terms):
    score = 0
    content = (message.content or "").lower()

    for term in terms:
        if term in content:
            score += 2

    return score


def retrieve_relevant_group_messages_keyword(group_id, query, top_k=10):
    terms = extract_search_terms(query)

    messages = GroupMessage.query.filter_by(
        group_id=group_id
    ).all()

    scored = []
    for m in messages:
        score = score_message(m, terms)
        if score > 0:
            scored.append((score, m))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for score, m in scored[:top_k]]

def call_llm(prompt):
    url = "http://localhost:11434/api/generate"

    payload = {
        "model": "llama3",
        "prompt": prompt,
        "stream": False
    }

    response = requests.post(url, json=payload)
    data = response.json()

    return data["response"]

def redirect_back_to_home():
    view = request.form.get("view", "all")
    group_id = request.form.get("group_id", "")
    keyword = request.form.get("q", "")

    return redirect(url_for("home", view=view, group_id=group_id, q=keyword))

def generate_invite_code(length=8):
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
        existing_group = Group.query.filter_by(invite_code=code).first()
        if not existing_group:
            return code
        




def cosine_similarity(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))


#weather & tide & wind
FISHING_SPOTS = {
    "Long Beach": (33.7701, -118.1937),
    "Santa Monica": (34.0195, -118.4912),
    "Newport Beach": (33.6189, -117.9298),
    "San Diego": (32.7157, -117.1611),
    "Catalina Island": (33.3879, -118.4163),
}

def fetch_fishing_conditions(lat, lon):
    weather_url = "https://api.open-meteo.com/v1/forecast"
    marine_url = "https://marine-api.open-meteo.com/v1/marine"

    weather_params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,precipitation,weather_code,wind_speed_10m,wind_direction_10m",
        "hourly": "temperature_2m,precipitation_probability,wind_speed_10m,wind_gusts_10m",
        "timezone": "auto"
    }

    marine_params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "wave_height,wave_direction,wave_period,swell_wave_height,swell_wave_period",
        "timezone": "auto"
    }

    weather = requests.get(weather_url, params=weather_params, timeout=10).json()
    marine = requests.get(marine_url, params=marine_params, timeout=10).json()

    return weather, marine

def score_fishing_hour(row):
    score = 100
    reasons = []

    wind = row.get("wind_speed")
    gust = row.get("wind_gust")
    wave = row.get("wave_height")
    rain = row.get("precip_prob")

    if wind is not None:
        if wind > 30:
            score -= 30
            reasons.append("high wind")
        elif wind > 20:
            score -= 15
            reasons.append("moderate wind")

    if gust is not None:
        if gust > 40:
            score -= 25
            reasons.append("strong gusts")
        elif gust > 30:
            score -= 10
            reasons.append("moderate gusts")

    if wave is not None:
        if wave > 1.5:
            score -= 30
            reasons.append("rough waves")
        elif wave > 1.0:
            score -= 15
            reasons.append("moderate waves")

    if rain is not None:
        if rain > 50:
            score -= 25
            reasons.append("high rain chance")
        elif rain > 20:
            score -= 10
            reasons.append("some rain chance")

    if score >= 75:
        level = "Good"
    elif score >= 50:
        level = "Moderate"
    else:
        level = "Poor"

    return score, level, reasons





# route
@app.route("/")
def index():
    current_user = get_current_user()
    if not current_user:
        session.clear()
        return redirect(url_for("login"))
    return redirect(url_for("home"))



@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        user = User.query.filter_by(username=username).first()

        if not user or user.password != password:
            flash("Invalid username or password.", "error")
            return redirect(url_for("login"))

        session["user_id"] = user.id
        session["username"] = user.username

        return redirect(url_for("home"))

    return render_template("login.html")



@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        if not username or not password or not confirm_password:
            flash("All fields are required.", "error")
            return redirect(url_for("register"))

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return redirect(url_for("register"))

        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash("Username already exists.", "error")
            return redirect(url_for("register"))

        new_user = User(
            username=username,
            password=password,
            display_name=username,
            points=0
        )

        db.session.add(new_user)
        db.session.commit()

        flash("Registration successful! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have logged out.", "success")
    return redirect(url_for("login"))


@app.route("/home")
def home():
    current_user = get_current_user()
    if not current_user:
        session.clear()
        return redirect(url_for("login"))
    keyword = request.args.get("q", "").strip()
    view = request.args.get("view", "all").strip()
    group_filter = request.args.get("group_id", "").strip()
    target_post_id = request.args.get("post_id", "").strip()

    if target_post_id:
        target_post = db.session.get(Post, int(target_post_id))
        if target_post:
            if target_post.visibility == "group":
                group_filter = str(target_post.group_id)
            else:
                view = "all"

    query = Post.query


    if group_filter:
        query = query.filter(
            Post.visibility == "group",
            Post.group_id == int(group_filter)
        )
    else:
        if view == "my":
            query = query.filter(Post.author_id == current_user.id)
        else:
            query = query.filter(Post.visibility == "public")

    if keyword:
        query = query.filter(
            or_(
                Post.title.ilike(f"%{keyword}%"),
                Post.content.ilike(f"%{keyword}%"),
                Post.location.ilike(f"%{keyword}%")
            )
        )

    posts = query.order_by(Post.created_at.desc()).all()
    comments = Comment.query.order_by(Comment.created_at.desc()).all()
    likes = PostLike.query.all()
    comment_likes = CommentLike.query.all()

    memberships = Membership.query.filter_by(user_id=current_user.id).all()
    user_group_ids = [m.group_id for m in memberships]
    my_groups = Group.query.filter(Group.id.in_(user_group_ids)).all() if user_group_ids else []

    unread_counts = {}

    for membership in memberships:
        query = GroupMessage.query.filter_by(group_id=membership.group_id)

        if membership.last_read_at:
            query = query.filter(GroupMessage.created_at > membership.last_read_at)

        unread_counts[membership.group_id] = query.count()

    selected_group = None
    if group_filter:
        selected_group = db.session.get(Group, int(group_filter))

    return render_template(
        "home.html",
        current_user=current_user,
        posts=posts,
        my_groups=my_groups,
        comments=comments,
        likes=likes,
        comment_likes=comment_likes,
        keyword=keyword,
        view=view,
        group_filter=group_filter,
        selected_group=selected_group,
        target_post_id=target_post_id,
        unread_counts=unread_counts
    )

@app.route("/profile", methods=["GET", "POST"])
def profile():
    current_user = get_current_user()
    if not current_user:
        session.clear()
        return redirect(url_for("login"))

    if request.method == "POST":
        display_name = request.form.get("display_name", "").strip()
        bio = request.form.get("bio", "").strip()

        if not display_name:
            flash("Display name cannot be empty.", "error")
            return redirect(url_for("profile"))

        current_user.display_name = display_name
        current_user.bio = bio if bio else None

        db.session.commit()
        flash("Profile updated successfully!", "success")
        return redirect(url_for("profile"))

    post_count = Post.query.filter_by(author_id=current_user.id).count()
    group_count = Membership.query.filter_by(user_id=current_user.id).count()

    return render_template(
        "profile.html",
        current_user=current_user,
        post_count=post_count,
        group_count=group_count
    )

@app.route("/create_public_post", methods=["POST"])
def create_public_post():
    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"}), 401

    current_user = get_current_user()

    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    location = request.form.get("location", "").strip()
    visibility = request.form.get("visibility", "public").strip()
    group_id = request.form.get("group_id", "").strip()
    file = request.files.get("image")

    if not title or not content:
        return jsonify({"success": False, "error": "Title and content cannot be empty."}), 400

    image_filename = None

    if file and file.filename != "":
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)

        counter = 1
        original_name, ext = os.path.splitext(filename)

        while os.path.exists(filepath):
            filename = f"{original_name}_{counter}{ext}"
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            counter += 1

        file.save(filepath)
        image_filename = filename

    selected_group_id = None
    selected_group_name = None

    if visibility == "group":
        if not group_id:
            return jsonify({"success": False, "error": "Please select a group."}), 400

        selected_group_id = int(group_id)

        membership = Membership.query.filter_by(
            user_id=current_user.id,
            group_id=selected_group_id
        ).first()

        if not membership:
            return jsonify({"success": False, "error": "You can only post to groups you joined."}), 403

        selected_group = db.session.get(Group, selected_group_id)
        selected_group_name = selected_group.name if selected_group else None

    new_post = Post(
        title=title,
        content=content,
        image=image_filename,
        location=location if location else None,
        visibility=visibility,
        group_id=selected_group_id,
        author_id=current_user.id
    )

    db.session.add(new_post)
    current_user.points += 10
    db.session.commit()
    
    if new_post.visibility == "public":
        add_post_to_public_index(new_post)
    elif new_post.visibility == "group" and new_post.group_id:
        add_post_to_group_index(new_post)

    return jsonify({
        "success": True,
        "post": {
            "id": new_post.id,
            "title": new_post.title,
            "content": new_post.content,
            "location": new_post.location,
            "image": new_post.image,
            "created_at": new_post.created_at.strftime("%Y-%m-%d %H:%M"),
            "author": current_user.username,
            "author_id": current_user.id,
            "visibility": new_post.visibility,
            "group_id": new_post.group_id,
            "group_name": selected_group_name
        }
    })

@app.route("/delete_public_post/<int:post_id>", methods=["POST"])
def delete_public_post(post_id):

    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"}), 401

    current_user = get_current_user()

    post = db.session.get(Post, post_id)
  

    if not post:
        all_posts = Post.query.all()
        print("all Post ids =", [p.id for p in all_posts])
        return jsonify({"success": False, "error": "Post not found"}), 404

    if post.author_id != current_user.id:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    post_visibility = post.visibility
    post_group_id = post.group_id

    db.session.delete(post)
    db.session.commit()

    if post_visibility == "public":
        remove_post_from_public_index(post_id)
    elif post_visibility == "group" and post_group_id:
        remove_post_from_group_index(post_group_id, post_id)

    return jsonify({
        "success": True,
        "post_id": post_id
    })

@app.route("/add_comment/<int:post_id>", methods=["POST"])
def add_comment(post_id):
    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"}), 401

    current_user = get_current_user()
    content = request.form.get("content", "").strip()

    post = db.session.get(Post, post_id)
    if not post:
        return jsonify({"success": False, "error": "Post not found"}), 404

    if not content:
        return jsonify({"success": False, "error": "Comment cannot be empty"}), 400

    new_comment = Comment(
        post_id=post_id,
        author_id=current_user.id,
        content=content
    )

    db.session.add(new_comment)
    if post.author_id != current_user.id:
        notification = Notification(
            user_id=post.author_id,
            sender_id=current_user.id,
            notification_type="comment",
            message=f"{current_user.display_name or current_user.username} commented on your post.",
            post_id=post.id
        )
        db.session.add(notification)
    db.session.commit()
    if post.visibility == "public" and post.group_id is None:
        add_comment_to_public_index(new_comment)

    return jsonify({
        "success": True,
        "comment": {
            "id": new_comment.id,
            "content": new_comment.content,
            "author": current_user.username,
            "author_id": current_user.id,
            "created_at": new_comment.created_at.strftime("%Y-%m-%d %H:%M")
        }
    })

@app.route("/delete_comment/<int:comment_id>", methods=["POST"])
def delete_comment(comment_id):
    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"}), 401

    current_user = get_current_user()
    comment = db.session.get(Comment, comment_id)

    if not comment:
        return jsonify({"success": False, "error": "Comment not found"}), 404

    if comment.author_id != current_user.id:
        return jsonify({"success": False, "error": "Unauthorized"}), 403



    post_id = comment.post_id
    comment_id_to_remove = comment.id
    post = db.session.get(Post, post_id)

    db.session.delete(comment)
    db.session.commit()

    if post and post.visibility == "public" and post.group_id is None:
        remove_comment_from_public_index(comment_id_to_remove)

    remaining_count = Comment.query.filter_by(post_id=post_id).count()

    return jsonify({
        "success": True,
        "comment_id": comment_id,
        "post_id": post_id,
        "remaining_count": remaining_count
    })


@app.route("/toggle_like/<int:post_id>", methods=["POST"])
def toggle_like(post_id):
    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"}), 401

    current_user = get_current_user()
    post = db.session.get(Post, post_id)

    if not post:
        return jsonify({"success": False, "error": "Post not found"}), 404

    existing_like = PostLike.query.filter_by(
        post_id=post_id,
        user_id=current_user.id
    ).first()

    if existing_like:
        db.session.delete(existing_like)
        liked = False
    else:
        new_like = PostLike(
            post_id=post_id,
            user_id=current_user.id
        )
        db.session.add(new_like)
        liked = True

        # 不给自己发通知
        if post.author_id != current_user.id:
            notification = Notification(
                user_id=post.author_id,
                sender_id=current_user.id,
                notification_type="post_like",
                message=f"{current_user.display_name or current_user.username} liked your post.",
                post_id=post.id
            )
            db.session.add(notification)

    db.session.commit()

    like_count = PostLike.query.filter_by(post_id=post_id).count()

    return jsonify({
        "success": True,
        "liked": liked,
        "like_count": like_count
    })

@app.route("/toggle_comment_like/<int:comment_id>", methods=["POST"])
def toggle_comment_like(comment_id):
    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"}), 401

    current_user = get_current_user()
    comment = db.session.get(Comment, comment_id)

    if not comment:
        return jsonify({"success": False, "error": "Comment not found"}), 404

    existing_like = CommentLike.query.filter_by(
        comment_id=comment_id,
        user_id=current_user.id
    ).first()

    if existing_like:
        db.session.delete(existing_like)
        liked = False
    else:
        new_like = CommentLike(
            comment_id=comment_id,
            user_id=current_user.id
        )
        db.session.add(new_like)
        liked = True

    db.session.commit()

    like_count = CommentLike.query.filter_by(comment_id=comment_id).count()

    return jsonify({
        "success": True,
        "liked": liked,
        "like_count": like_count
    })

@app.route("/notifications")
def notifications():
    current_user = get_current_user()
    if not current_user:
        session.clear()
        return redirect(url_for("login"))

    notifications = Notification.query.filter_by(
        user_id=current_user.id
    ).order_by(Notification.created_at.desc()).all()

    return render_template(
        "notifications.html",
        current_user=current_user,
        notifications=notifications
    )

@app.route("/notifications/mark_read/<int:notification_id>", methods=["POST"])
def mark_notification_read(notification_id):
    current_user = get_current_user()
    if not current_user:
        session.clear()
        return redirect(url_for("login"))

    notification = db.session.get(Notification, notification_id)

    if not notification or notification.user_id != current_user.id:
        flash("Notification not found.", "error")
        return redirect(url_for("notifications"))

    notification.is_read = True
    db.session.commit()

    return redirect(url_for("notifications"))

@app.route("/notifications/open/<int:notification_id>")
def open_notification(notification_id):
    current_user = get_current_user()
    if not current_user:
        session.clear()
        return redirect(url_for("login"))

    notification = db.session.get(Notification, notification_id)

    if not notification or notification.user_id != current_user.id:
        flash("Notification not found.", "error")
        return redirect(url_for("notifications"))

    notification.is_read = True
    db.session.commit()

    if notification.post_id:
        return redirect(url_for("home", post_id=notification.post_id))

    return redirect(url_for("notifications"))

@app.route("/groups")
def group_list():
    current_user = get_current_user()
    if not current_user:
        session.clear()
        return redirect(url_for("login"))

    keyword = request.args.get("q", "").strip()

    memberships = Membership.query.filter_by(user_id=current_user.id).all()
    my_group_ids = [m.group_id for m in memberships]
    my_groups = Group.query.filter(Group.id.in_(my_group_ids)).all() if my_group_ids else []
    
    unread_counts = {}

    for membership in memberships:
        query = GroupMessage.query.filter_by(group_id=membership.group_id)

        if membership.last_read_at:
            query = query.filter(GroupMessage.created_at > membership.last_read_at)

        unread_counts[membership.group_id] = query.count()

    requests = GroupJoinRequest.query.filter_by(user_id=current_user.id).all()
    pending_request_ids = [r.group_id for r in requests if r.status == "pending"]

    discover_query = Group.query.filter(Group.group_type != "private_approval")

    if keyword:
        discover_query = discover_query.filter(
            or_(
                Group.name.ilike(f"%{keyword}%"),
                Group.description.ilike(f"%{keyword}%")
            )
        )

    discover_groups = discover_query.order_by(Group.name.asc()).all()

    if keyword:
        private_code_group = Group.query.filter_by(
            group_type="private_approval",
            invite_code=keyword
        ).first()

        if private_code_group and all(g.id != private_code_group.id for g in discover_groups):
            discover_groups.append(private_code_group)

    return render_template(
        "groups.html",
        current_user=current_user,
        my_groups=my_groups,
        discover_groups=discover_groups,
        my_group_ids=my_group_ids,
        pending_request_ids=pending_request_ids,
        keyword=keyword,
        unread_counts=unread_counts
    )


@app.route("/groups/<int:group_id>/join", methods=["POST"])
def join_group(group_id):
    current_user = get_current_user()
    if not current_user:
        session.clear()
        return redirect(url_for("login"))

    group = Group.query.get_or_404(group_id)

    existing_membership = Membership.query.filter_by(
        user_id=current_user.id,
        group_id=group.id
    ).first()

    if existing_membership:
        flash("You are already a member of this group.", "info")
        return redirect(url_for("group_list"))

    existing_request = GroupJoinRequest.query.filter_by(
        user_id=current_user.id,
        group_id=group.id
    ).first()

    note = request.form.get("note", "").strip()

    if group.group_type == "public_open":
        membership = Membership(user_id=current_user.id, group_id=group.id)
        db.session.add(membership)
        db.session.commit()
        flash("You joined the group successfully.", "success")

    elif group.group_type in ["public_approval", "private_approval"]:
        if existing_request:
            if existing_request.status == "pending":
                existing_request.note = note if note else None
                db.session.commit()
                flash("Your join request is already pending. Your note has been updated.", "info")
            elif existing_request.status == "approved":
                flash("Your request has already been approved.", "info")
            elif existing_request.status == "rejected":
                existing_request.status = "pending"
                existing_request.note = note if note else None
                db.session.commit()
                flash("Your join request has been resubmitted.", "success")
        else:
            join_request = GroupJoinRequest(
                user_id=current_user.id,
                group_id=group.id,
                status="pending",
                note=note if note else None
            )
            db.session.add(join_request)
            db.session.commit()
            flash("Join request submitted. Waiting for approval.", "success")

    else:
        flash("Invalid group type.", "danger")

    return redirect(url_for("group_detail", group_id=group.id))

@app.route("/create_group", methods=["GET", "POST"])
def create_group():
    current_user = get_current_user()
    if not current_user:
        session.clear()
        return redirect(url_for("login"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        group_type = request.form.get("group_type", "public_open").strip()

        if not name:
            flash("Group name is required.", "error")
            return redirect(url_for("create_group"))

        existing_group = Group.query.filter_by(name=name).first()
        if existing_group:
            flash("A group with this name already exists.", "error")
            return redirect(url_for("create_group"))

        invite_code = None
        if group_type == "private_approval":
            invite_code = generate_invite_code()

        new_group = Group(
            name=name,
            description=description if description else None,
            group_type=group_type,
            creator_id=current_user.id,
            invite_code=invite_code
        )

        db.session.add(new_group)
        db.session.commit()

        new_membership = Membership(
            user_id=current_user.id,
            group_id=new_group.id
        )
        db.session.add(new_membership)
        db.session.commit()

        if group_type == "private_approval":
            flash(f"Private group created! Invite code: {invite_code}", "success")
        else:
            flash("Group created successfully!", "success")
        return redirect(url_for("group_detail", group_id=new_group.id))

    return render_template("create_group.html", current_user=current_user)


@app.route("/groups/<int:group_id>")
def group_detail(group_id):
    current_user = get_current_user()
    if not current_user:
        session.clear()
        return redirect(url_for("login"))

    group = Group.query.get_or_404(group_id)

    membership = Membership.query.filter_by(
        user_id=current_user.id,
        group_id=group.id
    ).first()

    is_member = membership is not None

    if membership:
        membership.last_read_at = datetime.utcnow()
        db.session.commit()

    is_creator = (group.creator_id == current_user.id)

    pending_requests = []
    if is_creator:
        pending_requests = GroupJoinRequest.query.filter_by(
            group_id=group.id,
            status="pending"
        ).all()

    group_posts = Post.query.filter_by(
        group_id=group.id,
        visibility="group"
    ).order_by(Post.created_at.desc()).all()

    messages = GroupMessage.query.filter_by(
        group_id=group.id
    ).order_by(GroupMessage.created_at.asc()).all()

    return render_template(
        "group_detail.html",
        group=group,
        current_user=current_user,
        is_member=is_member,
        is_creator=is_creator,
        pending_requests=pending_requests,
        group_posts=group_posts,
        messages=messages
    )


@app.route("/join_requests/<int:request_id>/approve", methods=["POST"])
def approve_join_request(request_id):
    current_user = get_current_user()
    if not current_user:
        session.clear()
        return redirect(url_for("login"))

    join_request = GroupJoinRequest.query.get_or_404(request_id)
    group = Group.query.get_or_404(join_request.group_id)

    if group.creator_id != current_user.id:
        flash("You are not allowed to approve requests for this group.", "danger")
        return redirect(url_for("group_list"))

    if join_request.status != "pending":
        flash("This request is no longer pending.", "info")
        return redirect(url_for("group_detail", group_id=group.id))

    existing_membership = Membership.query.filter_by(
        user_id=join_request.user_id,
        group_id=group.id
    ).first()

    if not existing_membership:
        membership = Membership(
            user_id=join_request.user_id,
            group_id=group.id
        )
        db.session.add(membership)

    join_request.status = "approved"
    db.session.commit()

    flash("Join request approved.", "success")
    return redirect(url_for("group_detail", group_id=group.id))

@app.route("/join_requests/<int:request_id>/reject", methods=["POST"])
def reject_join_request(request_id):
    current_user = get_current_user()
    if not current_user:
        session.clear()
        return redirect(url_for("login"))

    join_request = GroupJoinRequest.query.get_or_404(request_id)
    group = Group.query.get_or_404(join_request.group_id)

    if group.creator_id != current_user.id:
        flash("You are not allowed to reject requests for this group.", "danger")
        return redirect(url_for("group_list"))

    if join_request.status != "pending":
        flash("This request is no longer pending.", "info")
        return redirect(url_for("group_detail", group_id=group.id))

    join_request.status = "rejected"
    db.session.commit()

    flash("Join request rejected.", "success")
    return redirect(url_for("group_detail", group_id=group.id))

@app.route("/send_group_message/<int:group_id>", methods=["POST"])
def send_group_message(group_id):
    current_user = get_current_user()
    if not current_user:
        session.clear()
        return redirect(url_for("login"))
    group = db.session.get(Group, group_id)

    if not group:
        flash("Group not found.", "error")
        return redirect(url_for("group_list"))

    is_member = Membership.query.filter_by(
        user_id=current_user.id,
        group_id=group_id
    ).first()

    if not is_member:
        flash("You must join the group before sending messages.", "error")
        return redirect(url_for("group_detail", group_id=group_id))

    content = request.form.get("content", "").strip()

    if not content:
        flash("Message cannot be empty.", "error")
        return redirect(url_for("group_detail", group_id=group_id))

    new_message = GroupMessage(
        group_id=group_id,
        author_id=current_user.id,
        content=content
    )

    db.session.add(new_message)
    db.session.commit()

    add_group_message_to_index(new_message)

    flash("Message sent!", "success")
    return redirect(url_for("group_detail", group_id=group_id))



#ai
'''@app.route("/ask_ai", methods=["POST"])
def ask_ai():
    query = request.form.get("query")

    # 找相关帖子（简单版：关键词匹配）
    posts = PublicPost.query.filter(
        PublicPost.content.ilike(f"%{query}%")
    ).all()

    combined_text = "\n".join([p.content for p in posts[:10]])

    # 调用 LLM（先用简单 prompt）
    response = call_llm(f"""
    You are a fishing expert.

    Based on the following fishing reports:

    {combined_text}

    Answer the question: {query}

    Give a structured answer with:
    - Best methods
    - Best locations
    - Tips
    - Common mistakes

    Keep it short and clear.
    """)

    return render_template("ai_result.html", result=response)'''

#ai
@app.route("/ask_ai", methods=["POST"])
def ask_ai():
    current_user = get_current_user()
    if not current_user:
        session.clear()
        return redirect(url_for("login"))

    query = request.form.get("query", "").strip()
    if not query:
        flash("Please enter a question.", "error")
        return redirect(url_for("home"))

    matched_posts = retrieve_relevant_public_posts(query, top_k=10)
    matched_comments = retrieve_relevant_public_comments(query, top_k=15)

    if not matched_posts and not matched_comments:
        return render_template(
            "ai_result.html",
            result=None,
            query=query,
            matched_posts=[],
            matched_comments=[],
            no_data=True
        )

    post_text = "\n\n".join([
        f"[Public Post]\nTitle: {p.title}\nContent: {p.content}\nLocation: {p.location or 'N/A'}\nAuthor: {p.author.username}"
        for p in matched_posts
    ])

    comment_text = "\n\n".join([
        f"[Public Comment]\nAuthor: {c.author.username}\nPost Title: {c.post.title}\nContent: {c.content}"
        for c in matched_comments
    ])

    combined_text = "\n\n".join([post_text, comment_text]).strip()

    prompt = f"""
You are an AI assistant for a fishing knowledge platform.

You must ONLY use the information provided below.
Do NOT make up facts that are not supported by the data.
If the information is insufficient, clearly say so.

User question:
{query}

Relevant public fishing content:
{combined_text}

Provide a structured answer with:
- Key insights
- Common fishing methods or bait
- Locations mentioned
- Practical tips
- Limitations of the available data

Keep the answer clear, concise, and useful for beginners.
"""

    response = call_llm(prompt)

    return render_template(
        "ai_result.html",
        result=response,
        query=query,
        matched_posts=matched_posts,
        matched_comments=matched_comments,
        no_data=False
    )


@app.route("/ask_group_ai/<int:group_id>", methods=["POST"])
def ask_group_ai(group_id):
    current_user = get_current_user()
    if not current_user:
        session.clear()
        return redirect(url_for("login"))

    group = db.session.get(Group, group_id)
    if not group:
        flash("Group not found.", "error")
        return redirect(url_for("group_list"))

    is_member = Membership.query.filter_by(
        user_id=current_user.id,
        group_id=group_id
    ).first()

    if not is_member:
        flash("You must join this group to use Group AI.", "error")
        return redirect(url_for("group_detail", group_id=group_id))

    query = request.form.get("query", "").strip()
    if not query:
        flash("Please enter a question.", "error")
        return redirect(url_for("group_detail", group_id=group_id))

    matched_posts = retrieve_relevant_group_posts(group_id, query, top_k=10)
    matched_messages = retrieve_relevant_group_messages(group_id, query, top_k=15)

    if not matched_posts and not matched_messages:
        return render_template(
            "group_ai_result.html",
            group=group,
            query=query,
            result=None,
            matched_posts=[],
            matched_messages=[],
            no_data=True
        )

    post_text = "\n\n".join([
        f"[Group Post]\nTitle: {p.title}\nContent: {p.content}\nLocation: {p.location or 'N/A'}"
        for p in matched_posts
    ])

    message_text = "\n\n".join([
        f"[Group Message]\nAuthor: {m.author.username}\nContent: {m.content}"
        for m in matched_messages
    ])

    combined_text = "\n\n".join([post_text, message_text]).strip()

    prompt = f"""
You are a fishing assistant for a specific fishing group.

You must ONLY use the group content below.
Do not make up information that is not supported by the content.
If the content is insufficient, say so clearly.

Group name: {group.name}

User question:
{query}

Relevant group content:
{combined_text}

Provide a structured answer with:
- Main discussion themes
- Common methods or bait
- Locations mentioned
- What this group seems to recommend
- Limitations of available data

If the question asks for recent activity, focus more on recent content.
"""

    response = call_llm(prompt)

    return render_template(
        "group_ai_result.html",
        group=group,
        query=query,
        result=response,
        matched_posts=matched_posts,
        matched_messages=matched_messages,
        no_data=False
    )

#for old posts, delete after use
@app.route("/rebuild_all_indexes")
def rebuild_all_indexes():
    rebuild_public_post_index()
    rebuild_public_comment_index()

    group_ids = [g.id for g in Group.query.all()]
    for gid in group_ids:
        rebuild_group_post_index(gid)
        rebuild_group_message_index(gid)

    return "All indexes rebuilt."



#weather & tide & wind

@app.route("/conditions", methods=["GET", "POST"])
def conditions():
    current_user = get_current_user()
    if not current_user:
        session.clear()
        return redirect(url_for("login"))

    result = None
    ai_summary = None
    selected_spot = None
    selected_date = None
    selected_time = None

    if request.method == "POST":
        selected_spot = request.form.get("spot")
        selected_date = request.form.get("date")
        selected_time = request.form.get("time")

        if not selected_date or not selected_time:
            flash("Please select both date and start time.", "error")
            return redirect(url_for("conditions"))

        selected_datetime = datetime.strptime(
            f"{selected_date} {selected_time}",
            "%Y-%m-%d %H:%M"
        )

        lat, lon = FISHING_SPOTS[selected_spot]
        weather, marine = fetch_fishing_conditions(lat, lon)

        current = weather.get("current", {})
        hourly_weather = weather.get("hourly", {})
        hourly_marine = marine.get("hourly", {})

        hourly_rows = []
        all_times = hourly_weather.get("time", [])
        start_index = 0

        for i, t in enumerate(all_times):
            api_time = datetime.strptime(t, "%Y-%m-%dT%H:%M")
            if api_time >= selected_datetime:
                start_index = i
                break

        times = all_times[start_index:start_index + 12]

        for i, t in enumerate(times):
            idx = start_index + i

            hourly_rows.append({
                "time": t,
                "temperature": hourly_weather.get("temperature_2m", [None] * len(all_times))[idx],
                "precip_prob": hourly_weather.get("precipitation_probability", [None] * len(all_times))[idx],
                "wind_speed": hourly_weather.get("wind_speed_10m", [None] * len(all_times))[idx],
                "wind_gust": hourly_weather.get("wind_gusts_10m", [None] * len(all_times))[idx],
                "wave_height": hourly_marine.get("wave_height", [None] * len(all_times))[idx] if idx < len(hourly_marine.get("wave_height", [])) else None,
                "wave_period": hourly_marine.get("wave_period", [None] * len(all_times))[idx] if idx < len(hourly_marine.get("wave_period", [])) else None,
                "swell_height": hourly_marine.get("swell_wave_height", [None] * len(all_times))[idx] if idx < len(hourly_marine.get("swell_wave_height", [])) else None,
                "swell_period": hourly_marine.get("swell_wave_period", [None] * len(all_times))[idx] if idx < len(hourly_marine.get("swell_wave_period", [])) else None,
            })

        for row in hourly_rows:
            score, level, reasons = score_fishing_hour(row)
            row["score"] = score
            row["level"] = level
            row["reasons"] = reasons

        result = {
            "spot": selected_spot,
            "current": current,
            "hourly_rows": hourly_rows,
            "selected_date": selected_date,
            "selected_time": selected_time
        }

        prompt = f"""
You are a fishing condition assistant.

Use ONLY the scored hourly data below.
Do NOT exaggerate small differences.
A precipitation probability below 10% should be treated as low.
Wave height differences smaller than 0.2 meters should not be treated as meaningful.
Wind speed is in km/h, wave height is in meters.

Hourly scored conditions:
{hourly_rows}

Your task:
- Select the best 2-3 hour window based mainly on score
- Explain the main reasons using the score, wind, gust, wave, and rain values
- Identify hours to avoid only if risk is clearly higher
- Do not claim precipitation is significant unless it is above 20%
- Do not claim waves are worse unless wave height is meaningfully higher
- Keep the explanation concise and practical
"""

        ai_summary = call_llm(prompt)

    return render_template(
        "conditions.html",
        current_user=current_user,
        spots=FISHING_SPOTS.keys(),
        result=result,
        ai_summary=ai_summary,
        selected_spot=selected_spot,
        selected_date=selected_date,
        selected_time=selected_time
    )


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        seed_groups()
    app.run(debug=False)