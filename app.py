from flask import Flask, render_template, request, redirect, url_for, session, flash
from data import groups, memberships, group_messages
from datetime import datetime
import os
from werkzeug.utils import secure_filename
from models import db, User, PublicPost, Comment, PostLike
from sqlalchemy import or_




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

    query = PublicPost.query

    if keyword:
        query = query.filter(
            or_(
                PublicPost.title.ilike(f"%{keyword}%"),
                PublicPost.content.ilike(f"%{keyword}%"),
                PublicPost.location.ilike(f"%{keyword}%")
            )
        )

    posts = query.order_by(PublicPost.created_at.desc()).all()

    # 评论倒序
    comments = Comment.query.order_by(Comment.created_at.desc()).all()

    # 暂时 group 还用内存版
    user_group_ids = [m["group_id"] for m in memberships if m["user_id"] == current_user.id]
    my_groups = [g for g in groups if g["id"] in user_group_ids]

    return render_template(
        "home.html",
        current_user=current_user,
        posts=posts,
        my_groups=my_groups,
        comments=comments,
        keyword=keyword
    )


@app.route("/create_public_post", methods=["POST"])
def create_public_post():
    if not is_logged_in():
        return redirect(url_for("login"))

    current_user = get_current_user()

    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    location = request.form.get("location", "").strip()
    file = request.files.get("image")

    if not title or not content:
        flash("Title and content cannot be empty.", "error")
        return redirect(url_for("home"))

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

    new_post = PublicPost(
        title=title,
        content=content,
        image=image_filename,
        location=location if location else None,
        author_id=current_user.id
    )

    db.session.add(new_post)
    db.session.commit()

    flash("Post created successfully!", "success")
    return redirect(url_for("home"))

@app.route("/delete_public_post/<int:post_id>", methods=["POST"])
def delete_public_post(post_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    current_user = get_current_user()
    post = db.session.get(PublicPost, post_id)

    if not post:
        flash("Post not found.", "error")
        return redirect(url_for("home"))

    if post.author_id != current_user.id:
        flash("You can only delete your own posts.", "error")
        return redirect(url_for("home"))

    db.session.delete(post)
    db.session.commit()

    flash("Post deleted successfully.", "success")
    return redirect(url_for("home"))

@app.route("/add_comment/<int:post_id>", methods=["POST"])
def add_comment(post_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    current_user = get_current_user()
    content = request.form.get("content", "").strip()

    post = db.session.get(PublicPost, post_id)
    if not post:
        flash("Post not found.", "error")
        return redirect(url_for("home"))

    if not content:
        flash("Comment cannot be empty.", "error")
        return redirect(url_for("home"))

    new_comment = Comment(
        post_id=post_id,
        author_id=current_user.id,
        content=content
    )

    db.session.add(new_comment)
    db.session.commit()

    flash("Comment added successfully!", "success")
    return redirect(url_for("home"))

@app.route("/delete_comment/<int:comment_id>", methods=["POST"])
def delete_comment(comment_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    current_user = get_current_user()
    comment = db.session.get(Comment, comment_id)

    if not comment:
        flash("Comment not found.", "error")
        return redirect(url_for("home"))

    if comment.author_id != current_user.id:
        flash("You can only delete your own comments.", "error")
        return redirect(url_for("home"))

    db.session.delete(comment)
    db.session.commit()

    flash("Comment deleted successfully.", "success")
    return redirect(url_for("home"))

@app.route("/groups")
def group_list():
    if not is_logged_in():
        return redirect(url_for("login"))

    current_user = get_current_user()
    keyword = request.args.get("q", "").strip().lower()

    filtered_groups = groups
    if keyword:
        filtered_groups = [
            g for g in groups
            if keyword in g["name"].lower() or keyword in g["description"].lower()
        ]

    user_group_ids = [m["group_id"] for m in memberships if m["user_id"] == current_user["id"]]

    return render_template(
        "groups.html",
        current_user=current_user,
        groups=filtered_groups,
        user_group_ids=user_group_ids,
        keyword=request.args.get("q", "")
    )


@app.route("/join_group/<int:group_id>", methods=["POST"])
def join_group(group_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    current_user = get_current_user()

    existing_membership = next(
        (m for m in memberships if m["user_id"] == current_user["id"] and m["group_id"] == group_id),
        None
    )

    if existing_membership:
        flash("You are already in this group.", "error")
        return redirect(url_for("group_detail", group_id=group_id))

    memberships.append({
        "user_id": current_user["id"],
        "group_id": group_id
    })

    flash("Joined group successfully!", "success")
    return redirect(url_for("group_detail", group_id=group_id))


@app.route("/groups/<int:group_id>")
def group_detail(group_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    current_user = get_current_user()
    group = next((g for g in groups if g["id"] == group_id), None)

    if not group:
        flash("Group not found.", "error")
        return redirect(url_for("group_list"))

    is_member = any(
        m["user_id"] == current_user["id"] and m["group_id"] == group_id
        for m in memberships
    )

    messages = [m for m in group_messages if m["group_id"] == group_id]
    messages = sorted(messages, key=lambda x: x["id"])

    return render_template(
        "group_detail.html",
        current_user=current_user,
        group=group,
        is_member=is_member,
        messages=messages
    )


@app.route("/send_group_message/<int:group_id>", methods=["POST"])
def send_group_message(group_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    current_user = get_current_user()

    is_member = any(
        m["user_id"] == current_user["id"] and m["group_id"] == group_id
        for m in memberships
    )

    if not is_member:
        flash("You must join the group before sending messages.", "error")
        return redirect(url_for("group_detail", group_id=group_id))

    content = request.form.get("content", "").strip()

    if not content:
        flash("Message cannot be empty.", "error")
        return redirect(url_for("group_detail", group_id=group_id))

    new_message = {
        "id": len(group_messages) + 1,
        "group_id": group_id,
        "content": content,
        "author": current_user["username"],
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    group_messages.append(new_message)

    flash("Message sent!", "success")
    return redirect(url_for("group_detail", group_id=group_id))


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)