from flask import Flask, render_template, request, redirect, url_for, session, flash
from datetime import datetime
import os
from werkzeug.utils import secure_filename
from models import (
    db, User, Post, Comment, PostLike, CommentLike,
    Group, Membership, GroupMessage, GroupJoinRequest
)
from sqlalchemy import or_
from sqlalchemy import or_
import requests
from flask import jsonify
import random
import string
import re




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

UPLOAD_FOLDER = "static/uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

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

def retrieve_relevant_public_posts(query, top_k=10):
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

def score_comment(comment, terms):
    score = 0
    content = (comment.content or "").lower()

    for term in terms:
        if term in content:
            score += 2

    return score

def retrieve_relevant_public_comments(query, top_k=15):
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

def retrieve_relevant_group_posts(group_id, query, top_k=5):
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


def score_message(message, terms):
    score = 0
    content = (message.content or "").lower()

    for term in terms:
        if term in content:
            score += 2

    return score


def retrieve_relevant_group_messages(group_id, query, top_k=10):
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
            password=password
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

    query = Post.query

    # 先处理帖子范围
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

    # 搜索
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
        selected_group=selected_group
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
    db.session.commit()

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

    db.session.delete(post)
    db.session.commit()

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
    db.session.commit()

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

    db.session.delete(comment)
    db.session.commit()

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
        keyword=keyword
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
                flash("Your join request is already pending.", "info")
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

        # 创建后自动加入 group
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

    # 这里判断你是不是 member（你刚刚问的第一段）
    membership = Membership.query.filter_by(
        user_id=current_user.id,
        group_id=group.id
    ).first()

    is_member = membership is not None

    # 判断是不是 creator
    is_creator = (group.creator_id == current_user.id)

    #  如果是 creator，就查 pending requests
    pending_requests = []
    if is_creator:
        pending_requests = GroupJoinRequest.query.filter_by(
            group_id=group.id,
            status="pending"
        ).all()

    # 你之前页面用的 posts / messages 也要一起传
    group_posts = Post.query.filter_by(
        group_id=group.id,
        visibility="group"
    ).order_by(Post.created_at.desc()).all()

    messages = GroupMessage.query.filter_by(
        group_id=group.id
    ).order_by(GroupMessage.created_at.asc()).all()

    #  关键：把这些变量传给 HTML（你刚刚问的第二段就在这里）
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


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        seed_groups()
    app.run(debug=True)