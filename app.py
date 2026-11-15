from __future__ import annotations

import json
import base64
import hashlib
import hmac
import os
import secrets
import smtplib
import uuid
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from functools import wraps
from pathlib import Path

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, or_
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

from civicai.triage import analyze_complaint, find_similar_complaint

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
db = SQLAlchemy()
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
STATUSES = ["Submitted", "Under Review", "Approved", "Assigned", "In Progress", "Resolved", "Rejected"]
ADMIN_TRANSITIONS = {
    "Submitted": ["Under Review", "Rejected"],
    "Under Review": ["Approved", "Rejected"],
    "Approved": ["Assigned", "Rejected"],
    "Assigned": ["In Progress", "Rejected"],
    "In Progress": ["Resolved", "Rejected"],
    "Resolved": [], "Rejected": [],
}
OFFICER_TRANSITIONS = {"Assigned": ["In Progress"], "In Progress": ["Resolved"]}


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(180), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(30), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    address = db.Column(db.String(240), default="")
    preferred_language = db.Column(db.String(5), default="en")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    complaints = db.relationship("Complaint", back_populates="citizen", cascade="all, delete-orphan")


class Admin(db.Model):
    __tablename__ = "admins"
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(180), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Department(db.Model):
    __tablename__ = "departments"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.String(300), default="")
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    officers = db.relationship("DepartmentOfficer", back_populates="department")
    complaints = db.relationship("Complaint", back_populates="department")


class DepartmentOfficer(db.Model):
    __tablename__ = "department_officers"
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(180), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id", ondelete="SET NULL"))
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    department = db.relationship("Department", back_populates="officers")
    complaints = db.relationship("Complaint", back_populates="officer")


class Complaint(db.Model):
    __tablename__ = "complaints"
    id = db.Column(db.Integer, primary_key=True)
    complaint_id = db.Column(db.String(32), unique=True, nullable=False, index=True)
    citizen_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(80), nullable=False)
    priority = db.Column(db.String(20), nullable=False, default="Medium")
    status = db.Column(db.String(30), nullable=False, default="Submitted", index=True)
    location = db.Column(db.String(240), nullable=False)
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id", ondelete="SET NULL"))
    officer_id = db.Column(db.Integer, db.ForeignKey("department_officers.id", ondelete="SET NULL"))
    ai_summary = db.Column(db.String(500), default="")
    ai_confidence = db.Column(db.Float, default=0.0)
    duplicate_of_id = db.Column(db.Integer, db.ForeignKey("complaints.id", ondelete="SET NULL"))
    admin_note = db.Column(db.Text, default="")
    resolution_comment = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    citizen = db.relationship("User", back_populates="complaints")
    department = db.relationship("Department", back_populates="complaints")
    officer = db.relationship("DepartmentOfficer", back_populates="complaints")
    images = db.relationship("ComplaintImage", back_populates="complaint", cascade="all, delete-orphan")
    history = db.relationship("ComplaintStatusHistory", back_populates="complaint", cascade="all, delete-orphan", order_by="ComplaintStatusHistory.created_at")
    feedback = db.relationship("Feedback", back_populates="complaint", uselist=False, cascade="all, delete-orphan")


class ComplaintImage(db.Model):
    __tablename__ = "complaint_images"
    id = db.Column(db.Integer, primary_key=True)
    complaint_id = db.Column(db.Integer, db.ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False)
    file_name = db.Column(db.String(255), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(100), default="")
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    complaint = db.relationship("Complaint", back_populates="images")


class ComplaintStatusHistory(db.Model):
    __tablename__ = "complaint_status_history"
    id = db.Column(db.Integer, primary_key=True)
    complaint_id = db.Column(db.Integer, db.ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True)
    old_status = db.Column(db.String(30))
    new_status = db.Column(db.String(30), nullable=False)
    note = db.Column(db.Text, default="")
    changed_by_role = db.Column(db.String(30), nullable=False)
    changed_by_id = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    complaint = db.relationship("Complaint", back_populates="history")


class Notification(db.Model):
    __tablename__ = "notifications"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"))
    complaint_id = db.Column(db.Integer, db.ForeignKey("complaints.id", ondelete="CASCADE"))
    channel = db.Column(db.String(20), default="in-app", nullable=False)
    subject = db.Column(db.String(180), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Feedback(db.Model):
    __tablename__ = "feedback"
    id = db.Column(db.Integer, primary_key=True)
    complaint_id = db.Column(db.Integer, db.ForeignKey("complaints.id", ondelete="CASCADE"), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    complaint = db.relationship("Complaint", back_populates="feedback")


TRANSLATIONS = {
    "Home": "హోమ్", "About": "ప్రాజెక్ట్ గురించి", "Contact": "సంప్రదించండి", "My workspace": "నా పని స్థలం",
    "Dashboard": "డాష్‌బోర్డ్", "Submit a complaint": "ఫిర్యాదు సమర్పించండి", "Track complaint": "ఫిర్యాదును ట్రాక్ చేయండి",
    "My complaints": "నా ఫిర్యాదులు", "Analytics": "విశ్లేషణలు", "Departments": "శాఖలు", "Citizens": "పౌరులు",
    "About": "ప్రాజెక్ట్ గురించి", "Contact": "సంప్రదించండి", "Profile": "ప్రొఫైల్", "Sign in": "లాగిన్",
    "Sign out": "లాగౌట్", "Create account": "ఖాతా సృష్టించండి", "New complaint": "కొత్త ఫిర్యాదు",
    "Complaint ID": "ఫిర్యాదు ID", "Status": "స్థితి", "Priority": "ప్రాధాన్యత", "Location": "ప్రాంతం",
    "Description": "వివరణ", "Title": "శీర్షిక", "Department": "శాఖ", "Save changes": "మార్పులను సేవ్ చేయండి",
    "Search complaints": "ఫిర్యాదులను వెతకండి", "Welcome back": "మళ్లీ స్వాగతం", "Recent activity": "ఇటీవలి కార్యకలాపాలు",
    "Total complaints": "మొత్తం ఫిర్యాదులు", "Pending": "పెండింగ్", "In progress": "పనిలో ఉంది", "Resolved": "పరిష్కరించబడింది",
    "Submit complaint": "ఫిర్యాదు సమర్పించండి", "Email address": "ఇమెయిల్ చిరునామా", "Password": "పాస్‌వర్డ్",
    "Full name": "పూర్తి పేరు", "Phone number": "ఫోన్ నంబర్", "Address": "చిరునామా", "Send message": "సందేశం పంపండి",
}


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY", "civicai-demo-change-this-secret-before-deploying"),
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", f"sqlite:///{ROOT / 'instance' / 'civicai.db'}").replace("postgres://", "postgresql://", 1),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY=os.getenv("JWT_SECRET_KEY", "civicai-demo-jwt-secret-change-before-deploying"),
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(hours=8),
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
        UPLOAD_FOLDER=str(ROOT / "instance" / "uploads"),
        SESSION_COOKIE_NAME="civicai_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "0") == "1",
    )
    if test_config:
        app.config.update(test_config)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    db.init_app(app)

    @app.before_request
    def csrf_guard():
        if request.method == "POST" and not request.path.startswith("/api/"):
            sent = request.form.get("csrf_token", "")
            expected = session.get("csrf_token", "")
            if not sent or not expected or not secrets.compare_digest(sent, expected):
                abort(400, "Your form expired. Refresh the page and try again.")

    @app.context_processor
    def inject_globals():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(24)
        def tr(value):
            return TRANSLATIONS.get(value, value) if session.get("lang", "en") == "te" else value
        return {"tr": tr, "csrf_token_value": session["csrf_token"], "current_role": session.get("role"),
                "current_user_name": current_name(), "current_language": session.get("lang", "en")}

    @app.template_filter("dt")
    def dt_filter(value):
        return value.strftime("%d %b %Y · %I:%M %p") if value else "—"

    @app.template_filter("slug")
    def slug_filter(value):
        return (value or "").lower().replace(" ", "-")

    @app.route("/language", methods=["POST"])
    def set_language():
        session["lang"] = "te" if request.form.get("lang") == "te" else "en"
        return redirect(request.form.get("next") or url_for("index"))

    @app.route("/")
    def index():
        stats = public_stats()
        recent = Complaint.query.order_by(Complaint.created_at.desc()).limit(4).all()
        return render_template("home.html", stats=stats, recent=recent, title="CIVICAI | Public issue, real action")

    @app.route("/about")
    def about():
        return render_template("info.html", page="about", title="About CIVICAI")

    @app.route("/contact", methods=["GET", "POST"])
    def contact():
        if request.method == "POST":
            name = request.form.get("name", "").strip()[:120]
            email = request.form.get("email", "").strip()[:180]
            message = request.form.get("message", "").strip()[:2000]
            if not name or "@" not in email or len(message) < 8:
                flash("Please enter your name, a valid email and a message of at least 8 characters.", "error")
            else:
                db.session.add(Notification(subject=f"Contact request from {name}", message=f"{email}: {message}", channel="contact"))
                db.session.commit()
                flash("Thanks — your message has been received by the CIVICAI team.", "success")
                return redirect(url_for("contact"))
        return render_template("info.html", page="contact", title="Contact CIVICAI")

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            name, email = request.form.get("full_name", "").strip(), request.form.get("email", "").strip().lower()
            phone, password = request.form.get("phone", "").strip(), request.form.get("password", "")
            if not name or "@" not in email or len(phone) < 7 or len(password) < 8:
                flash("Enter valid details. Passwords must contain at least 8 characters.", "error")
            elif User.query.filter_by(email=email).first():
                flash("An account with that email already exists.", "error")
            else:
                user = User(full_name=name[:120], email=email[:180], phone=phone[:30], address=request.form.get("address", "").strip()[:240], password_hash=generate_password_hash(password))
                db.session.add(user); db.session.commit()
                login_user(user, "citizen")
                flash("Your citizen account is ready. Tell us what needs fixing.", "success")
                return redirect(url_for("citizen_dashboard"))
        return render_template("auth.html", mode="register", role="citizen", title="Create your citizen account")

    @app.route("/login", methods=["GET", "POST"])
    @app.route("/citizen/login", methods=["GET", "POST"])
    def citizen_login():
        return login_page("citizen")

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        return login_page("admin")

    @app.route("/officer/login", methods=["GET", "POST"])
    def officer_login():
        return login_page("officer")

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear(); flash("You have signed out.", "success")
        return redirect(url_for("index"))

    @app.route("/dashboard")
    def dashboard():
        role = session.get("role")
        return redirect(url_for({"citizen": "citizen_dashboard", "admin": "admin_dashboard", "officer": "officer_dashboard"}.get(role, "citizen_login")))

    @app.route("/citizen/dashboard")
    @role_required("citizen")
    def citizen_dashboard():
        user = current_user()
        complaints = Complaint.query.filter_by(citizen_id=user.id).order_by(Complaint.created_at.desc()).limit(5).all()
        counts = complaint_counts(Complaint.query.filter_by(citizen_id=user.id))
        return render_template("dashboard.html", view="citizen", title="Citizen dashboard", counts=counts, complaints=complaints,
                               resolution_rate=resolution_rate(Complaint.query.filter_by(citizen_id=user.id)))

    @app.route("/admin/dashboard")
    @role_required("admin")
    def admin_dashboard():
        counts = complaint_counts(Complaint.query)
        monthly, dept_chart = dashboard_chart_data()
        return render_template("dashboard.html", view="admin", title="Command center", counts=counts,
                               complaints=Complaint.query.order_by(Complaint.created_at.desc()).limit(8).all(),
                               citizens=User.query.count(), dept_count=Department.query.filter_by(active=True).count(),
                               resolution_rate=resolution_rate(), monthly=monthly, dept_chart=dept_chart)

    @app.route("/officer/dashboard")
    @role_required("officer")
    def officer_dashboard():
        officer = current_user()
        query = Complaint.query.filter_by(officer_id=officer.id)
        counts = complaint_counts(query)
        return render_template("dashboard.html", view="officer", title="Officer workspace", counts=counts,
                               complaints=query.order_by(Complaint.updated_at.desc()).limit(8).all(), resolution_rate=resolution_rate(query))

    @app.route("/complaints/new", methods=["GET", "POST"])
    @role_required("citizen")
    def new_complaint():
        departments = Department.query.filter_by(active=True).order_by(Department.name).all()
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            description = request.form.get("description", "").strip()
            location = request.form.get("location", "").strip()
            if len(title) < 5 or len(description) < 20 or len(location) < 4:
                flash("Add a clear title, at least 20 characters of detail, and a specific location.", "error")
            else:
                ai = analyze_complaint(title + ". " + description)
                dept = Department.query.filter(func.lower(Department.name) == ai["department"].lower()).first()
                dupe = find_similar_complaint(title, description, Complaint.query.filter(Complaint.status != "Rejected").all())
                complaint = Complaint(
                    complaint_id=f"CVC-{datetime.utcnow():%y%m%d}-{secrets.token_hex(3).upper()}",
                    citizen_id=current_user().id, title=title[:160], description=description[:5000],
                    location=location[:240], category=ai["category"], priority=ai["priority"],
                    department_id=dept.id if dept else None, ai_summary=ai["summary"], ai_confidence=ai["confidence"],
                    duplicate_of_id=dupe.id if dupe else None,
                    latitude=parse_float(request.form.get("latitude")), longitude=parse_float(request.form.get("longitude")))
                db.session.add(complaint); db.session.flush()
                record_status(complaint, None, "Submitted", "Complaint submitted by citizen.", "citizen", current_user().id)
                for upload in request.files.getlist("images")[:3]:
                    if upload and upload.filename:
                        saved = save_image(upload)
                        if saved:
                            db.session.add(ComplaintImage(complaint_id=complaint.id, file_name=saved, original_name=secure_filename(upload.filename)[:255], mime_type=upload.mimetype or ""))
                db.session.commit()
                notify_user(current_user(), complaint, "Complaint received", f"Your complaint {complaint.complaint_id} has been submitted and is under review.")
                flash(f"Complaint submitted. Your tracking ID is {complaint.complaint_id}.", "success")
                return redirect(url_for("complaint_detail", complaint_id=complaint.id))
        return render_template("complaints.html", page="new", title="Submit a civic complaint", departments=departments)

    @app.route("/complaints")
    @role_required("citizen")
    def my_complaints():
        query = Complaint.query.filter_by(citizen_id=current_user().id)
        query = apply_complaint_filters(query)
        complaints = query.order_by(Complaint.created_at.desc()).all()
        return render_template("complaints.html", page="list", title="My complaints", complaints=complaints)

    @app.route("/complaints/<int:complaint_id>")
    @login_required
    def complaint_detail(complaint_id):
        complaint = Complaint.query.get_or_404(complaint_id)
        if session.get("role") == "citizen" and complaint.citizen_id != current_user().id:
            abort(403)
        if session.get("role") == "officer" and complaint.officer_id != current_user().id:
            abort(403)
        return render_template("complaints.html", page="detail", title=f"Complaint {complaint.complaint_id}", complaint=complaint,
                               departments=Department.query.filter_by(active=True).all(), officers=DepartmentOfficer.query.filter_by(active=True).all(), statuses=allowed_statuses(complaint, session.get("role")))

    @app.route("/track", methods=["GET", "POST"])
    def track():
        complaint = None
        if request.method == "POST":
            cid = request.form.get("complaint_id", "").strip().upper()
            candidate = Complaint.query.filter_by(complaint_id=cid).first()
            contact = request.form.get("contact", "").strip().lower()
            if candidate and contact and contact in {candidate.citizen.email.lower(), candidate.citizen.phone.strip().lower()}:
                complaint = candidate
            else:
                flash("We could not verify those details. Check the tracking ID and registered email or phone.", "error")
        return render_template("complaints.html", page="track", title="Track a complaint", complaint=complaint, verified=complaint is not None)

    @app.route("/admin/complaints")
    @role_required("admin")
    def manage_complaints():
        query = apply_complaint_filters(Complaint.query)
        return render_template("complaints.html", page="manage", title="Complaint queue", complaints=query.order_by(Complaint.created_at.desc()).all(), departments=Department.query.filter_by(active=True).all(), statuses=STATUSES)

    @app.route("/officer/complaints")
    @role_required("officer")
    def assigned_complaints():
        query = apply_complaint_filters(Complaint.query.filter_by(officer_id=current_user().id))
        return render_template("complaints.html", page="manage", title="Assigned complaints", complaints=query.order_by(Complaint.updated_at.desc()).all(), statuses=STATUSES)

    @app.route("/complaints/<int:complaint_id>/update", methods=["POST"])
    @role_required("admin", "officer")
    def update_complaint(complaint_id):
        complaint = Complaint.query.get_or_404(complaint_id)
        role, actor = session["role"], current_user()
        if role == "officer" and complaint.officer_id != actor.id:
            abort(403)
        old_status = complaint.status
        new_status = request.form.get("status", old_status)
        if new_status not in STATUSES:
            abort(400)
        note = request.form.get("note", "").strip()[:2000]
        if role == "admin":
            dept_id = request.form.get("department_id", "")
            if dept_id.isdigit():
                dept = Department.query.get(int(dept_id))
                if dept and dept.active:
                    complaint.department_id = dept.id
            officer_id = request.form.get("officer_id", "")
            if officer_id.isdigit():
                officer = DepartmentOfficer.query.get(int(officer_id))
                if officer and officer.active and (complaint.department_id is None or officer.department_id == complaint.department_id):
                    complaint.officer_id = officer.id
                    if new_status == "Approved":
                        new_status = "Assigned"
            complaint.admin_note = request.form.get("admin_note", "").strip()[:2000]
        else:
            complaint.resolution_comment = note
        if new_status != old_status and new_status not in allowed_statuses(complaint, role, include_current=False):
            flash(f"That status change is not allowed from {old_status}.", "error")
            return redirect(request.form.get("next") or url_for("complaint_detail", complaint_id=complaint.id))
        if role == "officer" and new_status not in [old_status] + OFFICER_TRANSITIONS.get(old_status, []):
            flash("Officers can move assigned work to In Progress and then Resolved.", "error")
            return redirect(request.form.get("next") or url_for("complaint_detail", complaint_id=complaint.id))
        if new_status == "Assigned" and complaint.officer_id is None:
            flash("Choose a department officer before assigning this complaint.", "error")
            return redirect(request.form.get("next") or url_for("complaint_detail", complaint_id=complaint.id))
        complaint.status = new_status
        if old_status != new_status or note:
            record_status(complaint, old_status, new_status, note or ("Updated by " + role + "."), role, actor.id)
        db.session.commit()
        notify_user(complaint.citizen, complaint, "Complaint update", f"{complaint.complaint_id} is now {new_status}. {note}")
        flash("Complaint updated and the citizen has been notified.", "success")
        return redirect(request.form.get("next") or url_for("complaint_detail", complaint_id=complaint.id))

    @app.route("/admin/citizens")
    @role_required("admin")
    def manage_citizens():
        q = request.args.get("q", "").strip()
        query = User.query
        if q:
            like = f"%{q}%"; query = query.filter(or_(User.full_name.ilike(like), User.email.ilike(like), User.phone.ilike(like)))
        return render_template("manage.html", page="citizens", title="Citizen directory", citizens=query.order_by(User.created_at.desc()).all())

    @app.route("/admin/departments", methods=["GET", "POST"])
    @role_required("admin")
    def manage_departments():
        if request.method == "POST":
            action = request.form.get("action", "create")
            if action == "create":
                name = request.form.get("name", "").strip()
                if len(name) < 3 or Department.query.filter(func.lower(Department.name) == name.lower()).first():
                    flash("Enter a unique department name (at least 3 characters).", "error")
                else:
                    db.session.add(Department(name=name[:100], description=request.form.get("description", "").strip()[:300]))
                    db.session.commit(); flash("Department created.", "success")
            elif action == "officer":
                email = request.form.get("officer_email", "").strip().lower()
                dept_id = request.form.get("officer_department_id", "")
                password = request.form.get("officer_password", "")
                dept = Department.query.get(int(dept_id)) if dept_id.isdigit() else None
                if not dept or "@" not in email or len(password) < 8 or DepartmentOfficer.query.filter_by(email=email).first():
                    flash("Check the officer details, department and password length (8+ characters).", "error")
                else:
                    officer = DepartmentOfficer(full_name=request.form.get("officer_name", "").strip()[:120], email=email, password_hash=generate_password_hash(password), department_id=dept.id)
                    db.session.add(officer); db.session.commit(); flash("Department officer account created.", "success")
            return redirect(url_for("manage_departments"))
        return render_template("manage.html", page="departments", title="Departments & officers", departments=Department.query.order_by(Department.name).all(), officers=DepartmentOfficer.query.order_by(DepartmentOfficer.full_name).all())

    @app.route("/admin/departments/<int:department_id>/toggle", methods=["POST"])
    @role_required("admin")
    def toggle_department(department_id):
        department = Department.query.get_or_404(department_id); department.active = not department.active
        db.session.commit(); flash(f"{department.name} is now {'active' if department.active else 'paused'}.", "success")
        return redirect(url_for("manage_departments"))

    @app.route("/admin/analytics")
    @app.route("/admin/reports")
    @role_required("admin")
    def analytics():
        months = []
        for offset in range(5, -1, -1):
            d = date.today().replace(day=1)
            idx = d.month - 1 - offset
            year = d.year + idx // 12
            month = idx % 12 + 1
            months.append((year, month))
        monthly = [{"label": date(y, m, 1).strftime("%b"), "count": Complaint.query.filter(func.extract("year", Complaint.created_at) == y, func.extract("month", Complaint.created_at) == m).count()} for y, m in months]
        by_dept = db.session.query(Department.name, func.count(Complaint.id)).outerjoin(Complaint).group_by(Department.id).order_by(func.count(Complaint.id).desc()).all()
        dept_chart = [{"label": name, "count": count} for name, count in by_dept]
        return render_template("analytics.html", title="Analytics & reports", counts=complaint_counts(Complaint.query), resolution_rate=resolution_rate(), monthly=monthly, by_dept=by_dept,
                               dept_chart=dept_chart, high_priority=Complaint.query.filter(Complaint.priority.in_(["High", "Critical"])).count(), avg_resolution=average_resolution_days())

    @app.route("/profile", methods=["GET", "POST"])
    @role_required("citizen")
    def profile():
        user = current_user()
        if request.method == "POST":
            name = request.form.get("full_name", "").strip(); phone = request.form.get("phone", "").strip()
            if not name or len(phone) < 7:
                flash("Enter a name and valid phone number.", "error")
            else:
                user.full_name, user.phone, user.address = name[:120], phone[:30], request.form.get("address", "").strip()[:240]
                lang = request.form.get("preferred_language", "en"); user.preferred_language = lang if lang in ("en", "te") else "en"
                db.session.commit(); flash("Your profile has been updated.", "success")
        return render_template("manage.html", page="profile", title="My profile", user=user)

    @app.route("/feedback/<int:complaint_id>", methods=["GET", "POST"])
    @role_required("citizen")
    def feedback(complaint_id):
        complaint = Complaint.query.get_or_404(complaint_id)
        if complaint.citizen_id != current_user().id or complaint.status != "Resolved": abort(403)
        if request.method == "POST":
            rating = request.form.get("rating", "")
            if rating not in {"1", "2", "3", "4", "5"}:
                flash("Choose a rating from 1 to 5 stars.", "error")
            elif complaint.feedback:
                flash("Feedback has already been submitted for this complaint.", "error")
            else:
                db.session.add(Feedback(complaint_id=complaint.id, user_id=current_user().id, rating=int(rating), comment=request.form.get("comment", "").strip()[:1200]))
                db.session.commit(); flash("Thanks for helping us improve civic services.", "success")
                return redirect(url_for("complaint_detail", complaint_id=complaint.id))
        return render_template("complaints.html", page="feedback", title="Rate the resolution", complaint=complaint)

    @app.route("/uploads/<path:filename>")
    @login_required
    def uploaded_file(filename):
        image = ComplaintImage.query.filter_by(file_name=filename).first_or_404()
        complaint = image.complaint
        if session.get("role") == "citizen" and complaint.citizen_id != current_user().id: abort(403)
        if session.get("role") == "officer" and complaint.officer_id != current_user().id: abort(403)
        return send_from_directory(app.config["UPLOAD_FOLDER"], image.file_name, as_attachment=False)

    @app.route("/api/triage", methods=["POST"])
    def api_triage():
        payload = request.get_json(silent=True) or {}
        return jsonify(analyze_complaint(f"{payload.get('title', '')}. {payload.get('description', '')}"))

    @app.route("/api/auth/token", methods=["POST"])
    def api_token():
        payload = request.get_json(silent=True) or {}
        email = str(payload.get("email", "")).strip().lower(); password = str(payload.get("password", ""))
        user, role = find_account(email)
        if not user or not check_password_hash(user.password_hash, password): return jsonify(error="Invalid credentials"), 401
        token = create_access_token(f"{role}:{user.id}", app.config["JWT_SECRET_KEY"], app.config["JWT_ACCESS_TOKEN_EXPIRES"])
        return jsonify(access_token=token, token_type="Bearer", role=role, name=user.full_name)

    @app.route("/api/complaints", methods=["GET", "POST"])
    @jwt_required()
    def api_complaints():
        role, actor_id = parse_identity(get_jwt_identity())
        if request.method == "GET":
            query = Complaint.query
            if role == "citizen": query = query.filter_by(citizen_id=actor_id)
            elif role == "officer": query = query.filter_by(officer_id=actor_id)
            return jsonify([complaint_json(c) for c in query.order_by(Complaint.created_at.desc()).limit(100).all()])
        if role != "citizen": return jsonify(error="Citizen role required"), 403
        payload = request.get_json(silent=True) or {}
        title, desc, location = str(payload.get("title", "")).strip(), str(payload.get("description", "")).strip(), str(payload.get("location", "")).strip()
        if len(title) < 5 or len(desc) < 20 or len(location) < 4: return jsonify(error="Title, 20+ character description and location are required"), 400
        ai = analyze_complaint(title + ". " + desc); dept = Department.query.filter(func.lower(Department.name) == ai["department"].lower()).first()
        c = Complaint(complaint_id=f"CVC-{datetime.utcnow():%y%m%d}-{secrets.token_hex(3).upper()}", citizen_id=actor_id,
                      title=title[:160], description=desc[:5000], location=location[:240], category=ai["category"], priority=ai["priority"],
                      department_id=dept.id if dept else None, ai_summary=ai["summary"], ai_confidence=ai["confidence"])
        db.session.add(c); db.session.flush(); record_status(c, None, "Submitted", "Created through REST API.", "citizen", actor_id); db.session.commit()
        return jsonify(complaint_json(c)), 201

    @app.route("/api/stats")
    def api_stats():
        return jsonify(public_stats())

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("error.html", code="403", heading="This space is protected.", message="Sign in with an account that has access to this workspace."), 403

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("error.html", code="404", heading="We couldn’t find that page.", message="The link may have moved, or the report ID may be incorrect."), 404

    @app.errorhandler(400)
    def bad_request(error):
        description = getattr(error, "description", "That request could not be processed.")
        return render_template("error.html", code="400", heading="Please refresh and try again.", message=description), 400

    @app.errorhandler(413)
    def too_large(_error):
        return render_template("error.html", code="413", heading="That upload is too large.", message="The total request limit is 5 MB. Choose smaller images and try again."), 413

    @app.errorhandler(500)
    def server_error(_error):
        db.session.rollback()
        return render_template("error.html", code="500", heading="Something went wrong.", message="Please try again. If it continues, contact the CIVICAI support desk."), 500

    @app.cli.command("init-db")
    def init_db_command():
        db.create_all(); print("CIVICAI database tables are ready.")

    @app.cli.command("seed-demo")
    def seed_demo_command():
        db.create_all(); seed_demo_data(); print("Demo accounts and sample data are ready.")

    with app.app_context():
        db.create_all()
        if os.getenv("CIVICAI_SEED_DEMO", "1") == "1": seed_demo_data()
    return app


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("user_id") or not session.get("role"):
            flash("Please sign in to continue.", "error"); return redirect(url_for("citizen_login", next=request.path))
        return fn(*args, **kwargs)
    return wrapped


def role_required(*roles):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if session.get("role") not in roles or not session.get("user_id"):
                flash("Sign in with an authorized account to open this page.", "error")
                dest = {"admin": "admin_login", "officer": "officer_login"}.get(roles[0], "citizen_login")
                return redirect(url_for(dest))
            return fn(*args, **kwargs)
        return wrapped
    return decorate


def current_user():
    role, ident = session.get("role"), session.get("user_id")
    model = {"citizen": User, "admin": Admin, "officer": DepartmentOfficer}.get(role)
    return model.query.get(ident) if model and ident else None


def current_name():
    user = current_user()
    return user.full_name.split()[0] if user else None


def login_user(user, role):
    session.clear(); session["user_id"] = user.id; session["role"] = role; session["lang"] = getattr(user, "preferred_language", "en")
    session["csrf_token"] = secrets.token_urlsafe(24)


def login_page(role):
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower(); password = request.form.get("password", "")
        account, actual_role = find_account(email)
        if actual_role != role or not account or not check_password_hash(account.password_hash, password):
            flash("Email or password is incorrect for this sign-in portal.", "error")
        elif role == "officer" and not account.active:
            flash("This officer account is paused. Contact an administrator.", "error")
        else:
            login_user(account, role); flash(f"Welcome back, {account.full_name.split()[0]}.", "success")
            destination = {"citizen": "citizen_dashboard", "admin": "admin_dashboard", "officer": "officer_dashboard"}[role]
            return redirect(request.args.get("next") or url_for(destination))
    return render_template("auth.html", mode="login", role=role, title=f"{role.title()} sign in")


def find_account(email):
    for model, role in ((User, "citizen"), (Admin, "admin"), (DepartmentOfficer, "officer")):
        account = model.query.filter_by(email=email).first()
        if account: return account, role
    return None, None


def parse_identity(identity):
    role, ident = identity.split(":", 1); return role, int(ident)


def allowed_statuses(complaint, role, include_current=True):
    transitions = OFFICER_TRANSITIONS if role == "officer" else ADMIN_TRANSITIONS
    options = [complaint.status] + transitions.get(complaint.status, [])
    if role == "officer":
        options = [complaint.status] + OFFICER_TRANSITIONS.get(complaint.status, [])
    return options if include_current else [status for status in options if status != complaint.status]


def _b64url(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def create_access_token(identity, secret, lifetime):
    now = int(datetime.utcnow().timestamp())
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64url(json.dumps({"sub": identity, "iat": now, "exp": now + int(lifetime.total_seconds())}, separators=(",", ":")).encode())
    body = f"{header}.{payload}"
    signature = _b64url(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{signature}"


def get_jwt_identity():
    return getattr(g, "jwt_identity", None)


def jwt_required(fn=None):
    def decorate(target):
        @wraps(target)
        def wrapped(*args, **kwargs):
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                return jsonify(error="Bearer token required"), 401
            token = auth[7:].strip()
            try:
                head, payload, signature = token.split(".")
                header = json.loads(base64.urlsafe_b64decode(head + "=" * (-len(head) % 4)))
                body = f"{head}.{payload}"
                expected = _b64url(hmac.new(current_app_secret().encode(), body.encode(), hashlib.sha256).digest())
                if header.get("alg") != "HS256" or not hmac.compare_digest(expected, signature): raise ValueError("Signature mismatch")
                claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
                if claims.get("exp", 0) <= int(datetime.utcnow().timestamp()): raise ValueError("Token expired")
                g.jwt_identity = claims["sub"]
            except Exception:
                return jsonify(error="Invalid or expired token"), 401
            return target(*args, **kwargs)
        return wrapped
    return decorate(fn) if fn is not None else decorate


def current_app_secret():
    from flask import current_app
    return current_app.config["JWT_SECRET_KEY"]


def record_status(complaint, old, new, note, role, actor_id):
    db.session.add(ComplaintStatusHistory(complaint_id=complaint.id, old_status=old, new_status=new, note=note[:2000], changed_by_role=role, changed_by_id=actor_id))


def notify_user(user, complaint, subject, message):
    db.session.add(Notification(user_id=user.id, complaint_id=complaint.id, subject=subject, message=message))
    # SMTP is optional: the in-app notification is always saved; email sends when configured.
    host = os.getenv("SMTP_HOST")
    if not host: return
    try:
        msg = EmailMessage(); msg["Subject"] = f"CIVICAI · {subject}"; msg["From"] = os.getenv("SMTP_FROM", "no-reply@civicai.local"); msg["To"] = user.email
        msg.set_content(f"Hello {user.full_name},\n\n{message}\n\nTracking ID: {complaint.complaint_id}\n\nCIVICAI Public Services")
        with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=10) as server:
            if os.getenv("SMTP_STARTTLS", "1") == "1": server.starttls()
            if os.getenv("SMTP_USERNAME"): server.login(os.getenv("SMTP_USERNAME"), os.getenv("SMTP_PASSWORD", ""))
            server.send_message(msg)
        db.session.add(Notification(user_id=user.id, complaint_id=complaint.id, channel="email", subject=subject, message="Email sent."))
    except Exception as exc:
        app_logger = __import__("logging").getLogger("civicai.email"); app_logger.warning("Email delivery failed: %s", exc)


def save_image(upload):
    original = secure_filename(upload.filename or "")
    suffix = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if suffix not in ALLOWED_EXTENSIONS or (upload.mimetype and not upload.mimetype.startswith("image/")): return None
    name = f"{uuid.uuid4().hex}.{suffix}"
    try:
        from PIL import Image
        upload.stream.seek(0)
        image = Image.open(upload.stream)
        if image.format not in {"PNG", "JPEG", "WEBP"}: return None
        image.verify()
    except ImportError:
        upload.stream.seek(0)
        signature = upload.stream.read(12)
        valid = (suffix == "png" and signature.startswith(b"\x89PNG\r\n\x1a\n")) or \
                (suffix in {"jpg", "jpeg"} and signature.startswith(b"\xff\xd8\xff")) or \
                (suffix == "webp" and signature[:4] == b"RIFF" and signature[8:12] == b"WEBP")
        if not valid: return None
    except Exception:
        return None
    upload.stream.seek(0)
    upload.save(Path(create_app_placeholder_upload_folder()) / name)
    return name


def create_app_placeholder_upload_folder():
    # `current_app` is avoided here to keep helpers import-safe during CLI use.
    from flask import current_app
    return current_app.config["UPLOAD_FOLDER"]


def parse_float(value):
    try: return float(value) if value else None
    except (TypeError, ValueError): return None


def apply_complaint_filters(query):
    status = request.args.get("status", "").strip(); q = request.args.get("q", "").strip()
    if status in STATUSES: query = query.filter_by(status=status)
    if q:
        like = f"%{q}%"; query = query.outerjoin(User, Complaint.citizen_id == User.id).filter(or_(Complaint.complaint_id.ilike(like), Complaint.title.ilike(like), Complaint.location.ilike(like), User.full_name.ilike(like)))
    return query


def complaint_counts(query):
    items = query.all()
    return {"total": len(items), "pending": sum(c.status in ("Submitted", "Under Review", "Approved", "Assigned") for c in items),
            "progress": sum(c.status == "In Progress" for c in items), "resolved": sum(c.status == "Resolved" for c in items),
            "rejected": sum(c.status == "Rejected" for c in items), "critical": sum(c.priority == "Critical" for c in items)}


def resolution_rate(query=None):
    if query is None:
        query = Complaint.query
    total = query.count()
    resolved = query.filter_by(status="Resolved").count()
    return round(resolved * 100 / total) if total else 0


def average_resolution_days():
    rows = Complaint.query.filter_by(status="Resolved").all()
    days = [(c.updated_at - c.created_at).total_seconds() / 86400 for c in rows if c.updated_at and c.created_at]
    return round(sum(days) / len(days), 1) if days else 0


def public_stats():
    return {"total": Complaint.query.count(), "resolved": Complaint.query.filter_by(status="Resolved").count(),
            "in_progress": Complaint.query.filter_by(status="In Progress").count(), "departments": Department.query.filter_by(active=True).count()}


def dashboard_chart_data():
    months = []
    for offset in range(5, -1, -1):
        d = date.today().replace(day=1)
        idx = d.month - 1 - offset
        year, month = d.year + idx // 12, idx % 12 + 1
        months.append((year, month))
    monthly = [{"label": date(y, m, 1).strftime("%b"), "count": Complaint.query.filter(func.extract("year", Complaint.created_at) == y, func.extract("month", Complaint.created_at) == m).count()} for y, m in months]
    dept_chart = [{"label": name, "count": count} for name, count in db.session.query(Department.name, func.count(Complaint.id)).outerjoin(Complaint).group_by(Department.id).order_by(func.count(Complaint.id).desc()).limit(5).all()]
    return monthly, dept_chart


def complaint_json(c):
    return {"id": c.complaint_id, "title": c.title, "description": c.description, "category": c.category, "priority": c.priority,
            "status": c.status, "location": c.location, "department": c.department.name if c.department else None,
            "summary": c.ai_summary, "created_at": c.created_at.isoformat() + "Z"}


def seed_demo_data():
    depts = [
        ("Roads & Infrastructure", "Road damage, sidewalks, traffic assets and public infrastructure."),
        ("Water Supply", "Water connections, supply interruptions, leaks and quality."),
        ("Sanitation & Drainage", "Drainage, sewage, sanitation and public health."),
        ("Waste Management", "Garbage collection, dumping and recycling."),
        ("Electricity & Lighting", "Streetlights, public power and electrical hazards."),
        ("Environment", "Air, noise, trees and environmental concerns."),
    ]
    for name, desc in depts:
        if not Department.query.filter_by(name=name).first(): db.session.add(Department(name=name, description=desc))
    db.session.flush()
    if not Admin.query.filter_by(email="admin@civicai.demo").first():
        db.session.add(Admin(full_name="CIVICAI Administrator", email="admin@civicai.demo", password_hash=generate_password_hash("CivicAI@2026")))
    roads = Department.query.filter_by(name="Roads & Infrastructure").first()
    officers_by_department = {}
    for department in Department.query.filter_by(active=True).all():
        short = department.name.lower().replace(" & ", "-").replace(" ", "-")
        email = "officer@civicai.demo" if department.name == "Roads & Infrastructure" else f"{short}.officer@civicai.demo"
        officer = DepartmentOfficer.query.filter_by(email=email).first()
        if not officer:
            officer = DepartmentOfficer(full_name="Ananya Rao" if department.name == "Roads & Infrastructure" else f"{department.name} Officer",
                                        email=email, password_hash=generate_password_hash("CivicAI@2026"), department_id=department.id)
            db.session.add(officer); db.session.flush()
        officers_by_department[department.id] = officer
    citizen = User.query.filter_by(email="citizen@civicai.demo").first()
    if not citizen:
        citizen = User(full_name="Priya Sharma", email="citizen@civicai.demo", phone="+91 98765 43210", address="Banjara Hills, Hyderabad", password_hash=generate_password_hash("CivicAI@2026"))
        db.session.add(citizen); db.session.flush()
    if Complaint.query.count() == 0:
        examples = [
            ("Deep pothole near the school crossing", "A large pothole has opened on Road No. 12 near the school crossing. Motorbikes swerve into traffic to avoid it and it is getting wider after the rain.", "Banjara Hills · Road No. 12", "High", "In Progress", "Roads & Infrastructure"),
            ("No water supply since yesterday", "There has been no water supply to our street since yesterday morning. Several households have called but the line appears dry.", "Jubilee Hills · Plot 44", "Medium", "Under Review", "Water Supply"),
            ("Overflowing drain beside the park", "The open drain beside the children’s park has been overflowing for three days and smells strongly. Please clear the blockage as soon as possible.", "Madhapur · Botanical Garden Road", "Critical", "Under Review", "Sanitation & Drainage"),
            ("Street light out on main lane", "The street light at the corner of our main lane has been out for two weeks. It is very dark at night and pedestrians cannot see the curb.", "Kondapur · Masjid Banda Lane", "Medium", "Resolved", "Electricity & Lighting"),
            ("Uncollected waste at market entrance", "Garbage bags have piled up at the market entrance since Monday. Animals are tearing them open and waste is spreading across the pavement.", "Ameerpet · Market Road", "High", "Submitted", "Waste Management"),
        ]
        for index, (title, desc, loc, priority, status, deptname) in enumerate(examples):
            ai = analyze_complaint(title + ". " + desc)
            c = Complaint(complaint_id=f"CVC-DEMO-{index+1:03}", citizen_id=citizen.id, title=title, description=desc, location=loc, category=ai["category"], priority=priority, status=status, department_id=Department.query.filter_by(name=deptname).first().id, ai_summary=ai["summary"], ai_confidence=ai["confidence"], created_at=datetime.utcnow() - timedelta(days=2 + index * 3))
            if status in ("Assigned", "In Progress", "Resolved") and c.department_id in officers_by_department:
                c.officer_id = officers_by_department[c.department_id].id
            db.session.add(c); db.session.flush()
            path = {
                "Submitted": ["Submitted"],
                "Under Review": ["Submitted", "Under Review"],
                "Approved": ["Submitted", "Under Review", "Approved"],
                "Assigned": ["Submitted", "Under Review", "Approved", "Assigned"],
                "In Progress": ["Submitted", "Under Review", "Approved", "Assigned", "In Progress"],
                "Resolved": ["Submitted", "Under Review", "Approved", "Assigned", "In Progress", "Resolved"],
                "Rejected": ["Submitted", "Under Review", "Rejected"],
            }.get(status, ["Submitted"])
            previous = None
            for path_status in path:
                actor_role = "citizen" if path_status == "Submitted" else ("officer" if path_status in ("In Progress", "Resolved") else "admin")
                actor_id = citizen.id if actor_role == "citizen" else (c.officer_id if actor_role == "officer" else 1)
                record_status(c, previous, path_status, "Complaint received from a citizen." if path_status == "Submitted" else "Demo workflow update.", actor_role, actor_id)
                previous = path_status
        db.session.commit()


app = create_app()

if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1", port=int(os.getenv("PORT", "5000")))
