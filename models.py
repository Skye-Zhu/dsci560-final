from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)


class Group(db.Model):
    __tablename__ = "groups"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    description = db.Column(db.String(255), nullable=True)

    group_type = db.Column(db.String(30), nullable=False, default="public_open")
    creator_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    creator = db.relationship("User", backref=db.backref("created_groups", lazy=True))


class Membership(db.Model):
    __tablename__ = "memberships"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"), nullable=False)

    user = db.relationship("User", backref=db.backref("memberships", lazy=True))
    group = db.relationship("Group", backref=db.backref("memberships", lazy=True, cascade="all, delete-orphan"))

    __table_args__ = (
        db.UniqueConstraint("user_id", "group_id", name="unique_membership"),
    )


class Post(db.Model):
    __tablename__ = "posts"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    content = db.Column(db.Text, nullable=False)
    image = db.Column(db.String(255), nullable=True)
    location = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # public or group
    visibility = db.Column(db.String(20), nullable=False, default="public")

    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"), nullable=True)

    author = db.relationship("User", backref=db.backref("posts", lazy=True))
    group = db.relationship("Group", backref=db.backref("posts", lazy=True))


class Comment(db.Model):
    __tablename__ = "comments"

    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    post_id = db.Column(db.Integer, db.ForeignKey("posts.id"), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    post = db.relationship("Post", backref=db.backref("comments", lazy=True, cascade="all, delete-orphan"))
    author = db.relationship("User", backref=db.backref("comments", lazy=True))


class PostLike(db.Model):
    __tablename__ = "post_likes"

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    post = db.relationship("Post", backref=db.backref("likes", lazy=True, cascade="all, delete-orphan"))
    user = db.relationship("User", backref=db.backref("post_likes", lazy=True))

    __table_args__ = (
        db.UniqueConstraint("post_id", "user_id", name="unique_post_like"),
    )


class CommentLike(db.Model):
    __tablename__ = "comment_likes"

    id = db.Column(db.Integer, primary_key=True)
    comment_id = db.Column(db.Integer, db.ForeignKey("comments.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    comment = db.relationship("Comment", backref=db.backref("likes", lazy=True, cascade="all, delete-orphan"))
    user = db.relationship("User", backref=db.backref("comment_likes", lazy=True))

    __table_args__ = (
        db.UniqueConstraint("comment_id", "user_id", name="unique_comment_like"),
    )


class GroupMessage(db.Model):
    __tablename__ = "group_messages"

    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    group = db.relationship("Group", backref=db.backref("group_messages", lazy=True, cascade="all, delete-orphan"))
    author = db.relationship("User", backref=db.backref("group_messages", lazy=True))