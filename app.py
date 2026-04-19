from flask import Flask, render_template, request, redirect, url_for, session, flash
from datetime import datetime
import os
from werkzeug.utils import secure_filename
from models import (
    db, User, Post, Comment, PostLike, CommentLike,
    Group, Membership, GroupMessage
)
from sqlalchemy import or_
from sqlalchemy import or_
import requests
from flask import jsonify





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

    demo_groups = [
        Group(name="San Diego Charters", description="Discussions about charter fishing trips in San Diego"),
        Group(name="LA Shore Fishing", description="Local shore fishing reports and tips in Los Angeles"),
        Group(name="Tackle Tips", description="Talk about rods, reels, bait, and tackle setups"),
        Group(name="Yellowtail Reports", description="Share yellowtail catches, methods, and trip reports"),
        Group(name="Beginner Questions", description="A place for new anglers to ask beginner-friendly questions"),
    ]

    db.session.add_all(demo_groups)
    db.session.commit()

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

@app.route("/")
def index():
    if not is_logged_in():
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
    if not is_logged_in():
        return redirect(url_for("login"))

    current_user = get_current_user()
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
    if not is_logged_in():
        return redirect(url_for("login"))

    current_user = get_current_user()
    keyword = request.args.get("q", "").strip()

    query = Group.query

    if keyword:
        query = query.filter(
            or_(
                Group.name.ilike(f"%{keyword}%"),
                Group.description.ilike(f"%{keyword}%")
            )
        )

    groups = query.order_by(Group.name.asc()).all()

    memberships = Membership.query.filter_by(user_id=current_user.id).all()
    user_group_ids = [m.group_id for m in memberships]

    return render_template(
        "groups.html",
        current_user=current_user,
        groups=groups,
        user_group_ids=user_group_ids,
        keyword=keyword
    )


@app.route("/join_group/<int:group_id>", methods=["POST"])
def join_group(group_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    current_user = get_current_user()
    group = db.session.get(Group, group_id)

    if not group:
        flash("Group not found.", "error")
        return redirect(url_for("group_list"))

    existing_membership = Membership.query.filter_by(
        user_id=current_user.id,
        group_id=group_id
    ).first()

    if existing_membership:
        flash("You are already in this group.", "error")
        return redirect(url_for("group_detail", group_id=group_id))

    new_membership = Membership(
        user_id=current_user.id,
        group_id=group_id
    )

    db.session.add(new_membership)
    db.session.commit()

    flash("Joined group successfully!", "success")
    return redirect(url_for("group_detail", group_id=group_id))


@app.route("/groups/<int:group_id>")
def group_detail(group_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    current_user = get_current_user()
    group = db.session.get(Group, group_id)

    if not group:
        flash("Group not found.", "error")
        return redirect(url_for("group_list"))

    is_member = Membership.query.filter_by(
        user_id=current_user.id,
        group_id=group_id
    ).first() is not None

    group_posts = Post.query.filter_by(
        visibility="group",
        group_id=group_id
    ).order_by(Post.created_at.desc()).all()

    messages = GroupMessage.query.filter_by(
        group_id=group_id
    ).order_by(GroupMessage.created_at.asc()).all()

    return render_template(
        "group_detail.html",
        current_user=current_user,
        group=group,
        is_member=is_member,
        group_posts=group_posts,
        messages=messages
    )

@app.route("/send_group_message/<int:group_id>", methods=["POST"])
def send_group_message(group_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    current_user = get_current_user()
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
    if not is_logged_in():
        return redirect(url_for("login"))

    query = request.form.get("query", "").strip()

    if not query:
        flash("Please enter a question.", "error")
        return redirect(url_for("home"))

    posts = Post.query.filter(
        Post.visibility == "public",
        or_(
            Post.title.ilike(f"%{query}%"),
            Post.content.ilike(f"%{query}%"),
            Post.location.ilike(f"%{query}%")
        )
    ).all()

    if not posts:
        return render_template(
            "ai_result.html",
            result=None,
            query=query,
            matched_posts=[],
            no_data=True
        )

    combined_text = "\n\n".join(
        [f"Title: {p.title}\nContent: {p.content}\nLocation: {p.location or 'N/A'}" for p in posts[:10]]
    )

    prompt = f"""
    You are an AI assistant for a fishing knowledge platform.

    You must ONLY use the information provided below.
    Do NOT make up facts that are not supported by the data.
    If the information is insufficient, clearly say so.

    Fishing reports:
    {combined_text}

    User question:
    {query}

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
        matched_posts=posts[:10],
        no_data=False
    )


@app.route("/ask_group_ai/<int:group_id>", methods=["POST"])
def ask_group_ai(group_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    current_user = get_current_user()
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

    group_posts = Post.query.filter_by(
        visibility="group",
        group_id=group_id
    ).order_by(Post.created_at.desc()).limit(15).all()

    group_messages = GroupMessage.query.filter_by(
        group_id=group_id
    ).order_by(GroupMessage.created_at.desc()).limit(20).all()

    matched_posts = [
        p for p in group_posts
        if query.lower() in (p.title or "").lower()
        or query.lower() in (p.content or "").lower()
        or (p.location and query.lower() in p.location.lower())
    ]

    matched_messages = [
        m for m in group_messages
        if query.lower() in (m.content or "").lower()
    ]

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
        for p in matched_posts[:10]
    ])

    message_text = "\n\n".join([
        f"[Group Message]\nAuthor: {m.author.username}\nContent: {m.content}"
        for m in matched_messages[:15]
    ])

    combined_text = "\n\n".join([post_text, message_text]).strip()

    prompt = f"""
    You are a fishing assistant for a specific fishing group.

    You must ONLY use the group content below.
    Do not make up information that is not supported by the content.
    If the content is insufficient, say so clearly.

    Group name: {group.name}

    Group content:
    {combined_text}

    Question: {query}

    Provide a structured answer with:
    - Main discussion themes
    - Common methods or bait
    - Locations mentioned
    - What this group seems to recommend
    - Limitations of available data

    If the question asks for recent activity, focus on the most recent posts and messages.
    """

    response = call_llm(prompt)

    return render_template(
        "group_ai_result.html",
        group=group,
        query=query,
        result=response,
        matched_posts=matched_posts[:10],
        matched_messages=matched_messages[:15],
        no_data=False
    )


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        seed_groups()
    app.run(debug=True)