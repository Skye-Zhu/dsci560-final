from flask import Flask, render_template, request, redirect, url_for, session, flash
from datetime import datetime
from data import users, groups, memberships, public_posts, group_messages

app = Flask(__name__)
app.secret_key = "m1-secret-key"


def get_current_user():
    username = session.get("username")
    if not username:
        return None
    return next((u for u in users if u["username"] == username), None)


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

        user = next(
            (u for u in users if u["username"] == username and u["password"] == password),
            None
        )

        if user:
            session["username"] = user["username"]
            flash("Login successful!", "success")
            return redirect(url_for("home"))
        else:
            flash("Invalid username or password.", "error")

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

        existing_user = next((u for u in users if u["username"] == username), None)
        if existing_user:
            flash("Username already exists.", "error")
            return redirect(url_for("register"))

        new_user = {
            "id": len(users) + 1,
            "username": username,
            "password": password
        }
        users.append(new_user)

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
    recent_posts = sorted(public_posts, key=lambda x: x["id"], reverse=True)

    user_group_ids = [m["group_id"] for m in memberships if m["user_id"] == current_user["id"]]
    my_groups = [g for g in groups if g["id"] in user_group_ids]

    return render_template(
        "home.html",
        current_user=current_user,
        posts=recent_posts,
        my_groups=my_groups
    )


@app.route("/create_public_post", methods=["POST"])
def create_public_post():
    if not is_logged_in():
        return redirect(url_for("login"))

    current_user = get_current_user()
    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()

    if not title or not content:
        flash("Title and content cannot be empty.", "error")
        return redirect(url_for("home"))

    new_post = {
        "id": len(public_posts) + 1,
        "title": title,
        "content": content,
        "author": current_user["username"],
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    public_posts.append(new_post)

    flash("Public post created successfully!", "success")
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
    app.run(debug=True)