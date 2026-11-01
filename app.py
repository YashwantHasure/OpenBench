import os
from datetime import datetime, timedelta
from functools import wraps
from uuid import uuid4

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, abort
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

load_dotenv()  # Load local .env settings when running with `python app.py`.

app = Flask(__name__)

# Owner-uploaded payment QR images. For production, use persistent object storage
# (Render instance filesystems may be ephemeral).
QR_UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads", "payment_qr")
os.makedirs(QR_UPLOAD_FOLDER, exist_ok=True)
app.config["QR_UPLOAD_FOLDER"] = QR_UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB request limit
ALLOWED_QR_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

def allowed_qr_file(filename):
    return ("." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_QR_EXTENSIONS)

# In hosted production, require a real secret rather than silently using the
# development fallback. Locally, the fallback keeps first-time setup simple.
secret_key = (os.environ.get("SECRET_KEY") or "").strip()
if os.environ.get("RENDER") and not secret_key:
    raise RuntimeError("SECRET_KEY must be configured in the Render environment variables.")
app.config["SECRET_KEY"] = secret_key or "dev-only-change-this-before-deployment"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
if os.environ.get("RENDER"):
    app.config["SESSION_COOKIE_SECURE"] = True

os.makedirs(app.instance_path, exist_ok=True)
db_path = os.path.join(app.instance_path, "openbench.db")
default_database_url = "sqlite:///" + db_path.replace(os.sep, "/")
database_url = (os.environ.get("DATABASE_URL") or "").strip()

# Neon commonly supplies postgresql:// or postgres:// URLs. Explicitly use the
# psycopg 3 driver installed via requirements.txt. Empty values use SQLite locally.
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url or default_database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True} if database_url else {}
db = SQLAlchemy(app)

CATEGORIES = [
    "Agriculture", "Vehicles", "Properties & Spaces", "Construction & Industrial",
    "Education & Labs", "Tools & Household", "Healthcare & Accessibility",
    "Sports & Recreation", "Events & Media", "Business Equipment", "Other"
]

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="renter")
    verified = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class Resource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    name = db.Column(db.String(140), nullable=False)
    category = db.Column(db.String(80), nullable=False)
    description = db.Column(db.Text, nullable=False)
    location = db.Column(db.String(140), nullable=False)
    price = db.Column(db.Float, nullable=False, default=0)
    price_unit = db.Column(db.String(30), nullable=False, default="day")
    requirements = db.Column(db.String(300), nullable=False, default="No special requirements listed")
    training_required = db.Column(db.Boolean, default=False, nullable=False)
    available = db.Column(db.Boolean, default=True, nullable=False)
    payment_qr_filename = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    owner = db.relationship("User", backref=db.backref("resources", lazy=True))

class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    resource_id = db.Column(db.Integer, db.ForeignKey("resource.id"), nullable=False, index=True)
    renter_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    start_at = db.Column(db.DateTime, nullable=False)
    end_at = db.Column(db.DateTime, nullable=False)
    purpose = db.Column(db.String(500), nullable=False)
    payment_method = db.Column(db.String(20), nullable=False, default="cash")
    payment_status = db.Column(db.String(20), nullable=False, default="UNPAID")
    status = db.Column(db.String(20), nullable=False, default="PENDING")
    decision_reason = db.Column(db.String(300), nullable=True)
    initial_condition = db.Column(db.String(500), nullable=True)
    final_condition = db.Column(db.String(500), nullable=True)
    checked_in_at = db.Column(db.DateTime, nullable=True)
    returned_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    resource = db.relationship("Resource", backref=db.backref("bookings", lazy=True))
    renter = db.relationship("User", foreign_keys=[renter_id], backref=db.backref("bookings", lazy=True))

class Incident(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("booking.id"), nullable=False)
    reporter_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    incident_type = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), nullable=False, default="OPEN")
    resolution = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    booking = db.relationship("Booking", backref=db.backref("incidents", lazy=True))
    reporter = db.relationship("User")

class Waitlist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    resource_id = db.Column(db.Integer, db.ForeignKey("resource.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    desired_start = db.Column(db.DateTime, nullable=True)
    desired_end = db.Column(db.DateTime, nullable=True)
    note = db.Column(db.String(300), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="WAITING")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    resource = db.relationship("Resource", backref=db.backref("waitlist_entries", lazy=True))
    user = db.relationship("User", backref=db.backref("waitlist_entries", lazy=True))

class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("booking.id"), nullable=True)
    action = db.Column(db.String(80), nullable=False)
    details = db.Column(db.String(500), nullable=False, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    actor = db.relationship("User")
    booking = db.relationship("Booking", backref=db.backref("audit_logs", lazy=True))

def current_user():
    uid = session.get("user_id")
    return db.session.get(User, uid) if uid else None

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            flash("Please log in to continue.", "info")
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper

def roles_required(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user:
                flash("Please log in to continue.", "info")
                return redirect(url_for("login"))
            if user.role not in roles:
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator

def log_action(action, details="", booking_id=None):
    user = current_user()
    db.session.add(AuditLog(actor_id=user.id if user else None, booking_id=booking_id, action=action, details=details))

def overlap_exists(resource_id, start_at, end_at, ignore_booking_id=None):
    query = Booking.query.filter(
        Booking.resource_id == resource_id,
        Booking.status.in_(["APPROVED", "ACTIVE"]),
        Booking.start_at < end_at,
        Booking.end_at > start_at
    )
    if ignore_booking_id:
        query = query.filter(Booking.id != ignore_booking_id)
    return query.first() is not None

@app.context_processor
def inject_globals():
    return {"current_user": current_user(), "categories": CATEGORIES, "now": datetime.now()}

@app.route("/")
def index():
    category = request.args.get("category", "").strip()
    q = request.args.get("q", "").strip()
    resources_query = Resource.query.filter_by(available=True)
    if category:
        resources_query = resources_query.filter_by(category=category)
    if q:
        like = f"%{q}%"
        resources_query = resources_query.filter(db.or_(Resource.name.ilike(like), Resource.description.ilike(like), Resource.location.ilike(like)))
    resources = resources_query.order_by(Resource.created_at.desc()).all()
    return render_template("index.html", resources=resources, selected_category=category, q=q)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "renter")
        if role not in ("renter", "owner"):
            role = "renter"
        if not name or not email or len(password) < 8:
            flash("Enter your name and email, and use a password of at least 8 characters.", "error")
            return render_template("auth.html", mode="register")
        if User.query.filter_by(email=email).first():
            flash("An account with this email already exists.", "error")
            return render_template("auth.html", mode="register")
        user = User(name=name, email=email, password_hash=generate_password_hash(password), role=role)
        db.session.add(user)
        db.session.flush()
        log_action("ACCOUNT_CREATED", f"New {role} account")
        db.session.commit()
        session["user_id"] = user.id
        flash("Welcome to OpenBench!", "success")
        return redirect(url_for("dashboard"))
    return render_template("auth.html", mode="register")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password_hash, password):
            flash("Invalid email or password.", "error")
            return render_template("auth.html", mode="login")
        session["user_id"] = user.id
        flash("You are now logged in.", "success")
        return redirect(request.args.get("next") or url_for("dashboard"))
    return render_template("auth.html", mode="login")

@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("index"))

@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    if user.role == "admin":
        return redirect(url_for("admin_dashboard"))
    if user.role == "owner":
        resources = Resource.query.filter_by(owner_id=user.id).order_by(Resource.created_at.desc()).all()
        bookings = Booking.query.join(Resource).filter(Resource.owner_id == user.id).order_by(Booking.created_at.desc()).all()
    else:
        resources = []
        bookings = Booking.query.filter_by(renter_id=user.id).order_by(Booking.created_at.desc()).all()
    incidents = Incident.query.join(Booking).join(Resource).filter(
        db.or_(Incident.reporter_id == user.id, Booking.renter_id == user.id, Resource.owner_id == user.id)
    ).order_by(Incident.created_at.desc()).all()
    return render_template("dashboard.html", resources=resources, bookings=bookings, incidents=incidents)

@app.route("/resources/new", methods=["GET", "POST"])
@roles_required("owner")
def new_resource():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        category = request.form.get("category", "")
        description = request.form.get("description", "").strip()
        location = request.form.get("location", "").strip()
        requirements = request.form.get("requirements", "No special requirements listed").strip()
        try:
            price = float(request.form.get("price", "0"))
        except ValueError:
            price = -1
        if not name or category not in CATEGORIES or not description or not location or price < 0:
            flash("Complete all required fields and enter a valid non-negative price.", "error")
            return render_template("resource_form.html")
        qr_file = request.files.get("payment_qr")
        qr_filename = None
        if qr_file and qr_file.filename:
            if not allowed_qr_file(qr_file.filename):
                flash("Upload a QR image in PNG, JPG, JPEG, or WEBP format.", "error")
                return render_template("resource_form.html")
            extension = secure_filename(qr_file.filename).rsplit(".", 1)[1].lower()
            qr_filename = f"{uuid4().hex}.{extension}"
            qr_file.save(os.path.join(app.config["QR_UPLOAD_FOLDER"], qr_filename))

        resource = Resource(
            owner_id=current_user().id, name=name, category=category, description=description,
            location=location, price=price, price_unit=request.form.get("price_unit", "day"),
            requirements=requirements or "No special requirements listed",
            training_required=bool(request.form.get("training_required")),
            payment_qr_filename=qr_filename
        )
        db.session.add(resource)
        db.session.flush()
        log_action("RESOURCE_LISTED", f"Listed resource: {name}")
        db.session.commit()
        flash("Resource listed successfully.", "success")
        return redirect(url_for("dashboard"))
    return render_template("resource_form.html")

@app.route("/resources/<int:resource_id>/payment-qr", methods=["POST"])
@roles_required("owner")
def update_resource_payment_qr(resource_id):
    resource = db.get_or_404(Resource, resource_id)
    if resource.owner_id != current_user().id:
        abort(403)
    qr_file = request.files.get("payment_qr")
    if not qr_file or not qr_file.filename:
        flash("Choose a QR image to upload.", "error")
        return redirect(url_for("resource_detail", resource_id=resource.id))
    if not allowed_qr_file(qr_file.filename):
        flash("Upload a PNG, JPG, JPEG, or WEBP image.", "error")
        return redirect(url_for("resource_detail", resource_id=resource.id))
    extension = secure_filename(qr_file.filename).rsplit(".", 1)[1].lower()
    new_filename = f"{uuid4().hex}.{extension}"
    qr_file.save(os.path.join(app.config["QR_UPLOAD_FOLDER"], new_filename))
    old_filename = resource.payment_qr_filename
    resource.payment_qr_filename = new_filename
    log_action("PAYMENT_QR_UPDATED", f"Updated payment QR for {resource.name}")
    db.session.commit()
    if old_filename:
        old_path = os.path.join(app.config["QR_UPLOAD_FOLDER"], old_filename)
        if os.path.isfile(old_path):
            try:
                os.remove(old_path)
            except OSError:
                app.logger.warning("Could not remove replaced QR image: %s", old_path)
    flash("Payment QR code updated.", "success")
    return redirect(url_for("resource_detail", resource_id=resource.id))

@app.route("/resources/<int:resource_id>")
def resource_detail(resource_id):
    resource = db.get_or_404(Resource, resource_id)
    bookings = Booking.query.filter(
        Booking.resource_id == resource.id,
        Booking.status.in_(["APPROVED", "ACTIVE", "RETURNED"])
    ).order_by(Booking.start_at.asc()).all()
    return render_template("resource_detail.html", resource=resource, bookings=bookings)

@app.route("/resources/<int:resource_id>/book", methods=["POST"])
@roles_required("renter")
def request_booking(resource_id):
    resource = db.get_or_404(Resource, resource_id)
    if not resource.available:
        flash("This resource is currently unavailable.", "error")
        return redirect(url_for("resource_detail", resource_id=resource.id))
    try:
        start_at = datetime.fromisoformat(request.form.get("start_at", ""))
        end_at = datetime.fromisoformat(request.form.get("end_at", ""))
    except ValueError:
        flash("Choose valid start and end dates and times.", "error")
        return redirect(url_for("resource_detail", resource_id=resource.id))
    purpose = request.form.get("purpose", "").strip()
    if end_at <= start_at or start_at < datetime.now() or not purpose:
        flash("Choose a future time range and explain the purpose.", "error")
        return redirect(url_for("resource_detail", resource_id=resource.id))
    if resource.owner_id == current_user().id:
        flash("You cannot book your own listing.", "error")
        return redirect(url_for("resource_detail", resource_id=resource.id))
    if resource.training_required and request.form.get("training_confirmed") != "yes":
        flash("This resource requires training confirmation. Contact the owner before requesting access.", "error")
        return redirect(url_for("resource_detail", resource_id=resource.id))
    if overlap_exists(resource.id, start_at, end_at):
        flash("That time overlaps an approved or active booking. Try another slot.", "error")
        return redirect(url_for("resource_detail", resource_id=resource.id))

    payment_method = request.form.get("payment_method", "").strip().lower()
    if payment_method not in {"cash", "qr", "card"}:
        flash("Please select Cash, QR payment, or Card.", "error")
        return redirect(url_for("resource_detail", resource_id=resource.id))
    if payment_method == "qr" and not resource.payment_qr_filename:
        flash("This owner has not uploaded a QR code. Choose another payment method.", "error")
        return redirect(url_for("resource_detail", resource_id=resource.id))

    booking = Booking(
        resource_id=resource.id, renter_id=current_user().id,
        start_at=start_at, end_at=end_at, purpose=purpose,
        payment_method=payment_method, payment_status="UNPAID"
    )
    db.session.add(booking)
    db.session.flush()
    log_action("BOOKING_REQUESTED", f"Requested {resource.name}", booking.id)
    db.session.commit()
    flash("Booking request sent to the owner.", "success")
    return redirect(url_for("dashboard"))

@app.route("/bookings/<int:booking_id>/decision", methods=["POST"])
@roles_required("owner")
def booking_decision(booking_id):
    booking = db.get_or_404(Booking, booking_id)
    if booking.resource.owner_id != current_user().id:
        abort(403)
    if booking.status != "PENDING":
        flash("Only pending requests can be decided.", "error")
        return redirect(url_for("dashboard"))
    decision = request.form.get("decision")
    reason = request.form.get("reason", "").strip()
    if decision == "approve":
        if overlap_exists(booking.resource_id, booking.start_at, booking.end_at, booking.id):
            flash("Cannot approve: another approved booking overlaps this time.", "error")
            return redirect(url_for("dashboard"))
        booking.status = "APPROVED"
        booking.decision_reason = reason or "Approved by resource owner."
        action = "BOOKING_APPROVED"
    elif decision == "reject":
        booking.status = "REJECTED"
        booking.decision_reason = reason or "Rejected by resource owner."
        action = "BOOKING_REJECTED"
    else:
        flash("Choose approve or reject.", "error")
        return redirect(url_for("dashboard"))
    log_action(action, booking.decision_reason, booking.id)
    db.session.commit()
    flash(f"Booking {booking.status.lower()}.", "success")
    return redirect(url_for("dashboard"))

@app.route("/bookings/<int:booking_id>/check-in", methods=["POST"])
@login_required
def check_in(booking_id):
    booking = db.get_or_404(Booking, booking_id)
    user = current_user()
    if user.id not in (booking.renter_id, booking.resource.owner_id) and user.role != "admin":
        abort(403)
    if booking.status != "APPROVED":
        flash("Only approved bookings can be checked in.", "error")
        return redirect(url_for("dashboard"))
    condition = request.form.get("condition", "").strip()
    if not condition:
        flash("Describe the initial condition before handover.", "error")
        return redirect(url_for("dashboard"))
    booking.status = "ACTIVE"
    booking.initial_condition = condition
    booking.checked_in_at = datetime.utcnow()
    log_action("RESOURCE_HANDED_OVER", condition, booking.id)
    db.session.commit()
    flash("Handover recorded.", "success")
    return redirect(url_for("dashboard"))

@app.route("/bookings/<int:booking_id>/return", methods=["POST"])
@login_required
def return_resource(booking_id):
    booking = db.get_or_404(Booking, booking_id)
    user = current_user()
    if user.id not in (booking.renter_id, booking.resource.owner_id) and user.role != "admin":
        abort(403)
    if booking.status != "ACTIVE":
        flash("Only active bookings can be returned.", "error")
        return redirect(url_for("dashboard"))
    condition = request.form.get("condition", "").strip()
    if not condition:
        flash("Describe the final condition before confirming return.", "error")
        return redirect(url_for("dashboard"))
    booking.status = "RETURNED"
    booking.final_condition = condition
    booking.returned_at = datetime.utcnow()
    log_action("RESOURCE_RETURNED", condition, booking.id)
    db.session.commit()
    flash("Return recorded successfully.", "success")
    return redirect(url_for("dashboard"))

@app.route("/bookings/<int:booking_id>/cancel", methods=["POST"])
@login_required
def cancel_booking(booking_id):
    booking = db.get_or_404(Booking, booking_id)
    user = current_user()
    if user.id != booking.renter_id and user.id != booking.resource.owner_id and user.role != "admin":
        abort(403)
    if booking.status not in ("PENDING", "APPROVED"):
        flash("This booking can no longer be cancelled from this screen.", "error")
        return redirect(url_for("dashboard"))
    booking.status = "CANCELLED"
    log_action("BOOKING_CANCELLED", "Booking cancelled by an authorized participant.", booking.id)
    db.session.commit()
    flash("Booking cancelled.", "success")
    return redirect(url_for("dashboard"))

@app.route("/bookings/<int:booking_id>/incident", methods=["POST"])
@login_required
def report_incident(booking_id):
    booking = db.get_or_404(Booking, booking_id)
    user = current_user()
    if user.id not in (booking.renter_id, booking.resource.owner_id) and user.role != "admin":
        abort(403)
    kind = request.form.get("incident_type", "Other")
    description = request.form.get("description", "").strip()
    if not description:
        flash("Describe the incident.", "error")
        return redirect(url_for("dashboard"))
    incident = Incident(booking_id=booking.id, reporter_id=user.id, incident_type=kind, description=description)
    db.session.add(incident)
    db.session.flush()
    log_action("INCIDENT_REPORTED", f"{kind}: {description[:250]}", booking.id)
    db.session.commit()
    flash("Incident report submitted.", "success")
    return redirect(url_for("dashboard"))

@app.route("/api/ai-search", methods=["POST"])
def ai_search():
    """Interpret a request with Gemini when configured; always search real listings locally."""
    payload = request.get_json(silent=True) or {}
    prompt = (payload.get("query") or "").strip()[:1000]
    if not prompt:
        return jsonify({"message": "Enter what you need.", "resources": []}), 400
    interpreted, ai_used = prompt, False
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
                contents=("You are a search query parser for a resource sharing marketplace. Extract only useful search keywords, likely category, location, and constraints. Do not invent listings or make decisions. Return comma-separated keywords. Request: " + prompt)
            )
            interpreted = (response.text or prompt).strip()
            ai_used = bool(response.text)
        except Exception:
            interpreted = prompt
    # Include important words from the original request so the fallback remains useful.
    terms = [t.strip(" .,!?;:").lower() for t in (interpreted + "," + prompt).replace("\n", ",").split(",") if len(t.strip()) > 2]
    words = [w.strip(".,!?;:") for w in prompt.lower().split() if len(w.strip(".,!?;:")) > 3]
    terms = list(dict.fromkeys((terms + words)[:18]))
    query = Resource.query.filter_by(available=True)
    conditions = []
    for term in terms:
        like = f"%{term}%"
        conditions.extend([Resource.name.ilike(like), Resource.category.ilike(like), Resource.description.ilike(like), Resource.location.ilike(like)])
    resources = query.filter(db.or_(*conditions)).limit(40).all() if conditions else query.limit(40).all()
    # Explainable relevance scoring: keyword overlap + verified owner + listing availability.
    prompt_words = {w for w in words if len(w) > 3}
    ranked = []
    for r in resources:
        text_blob = f"{r.name} {r.category} {r.description} {r.location}".lower()
        overlap = sum(1 for w in prompt_words if w in text_blob)
        score = min(96, 48 + overlap * 12 + (8 if r.owner.verified else 0))
        reasons = []
        if overlap: reasons.append(f"Matches {overlap} search term{'s' if overlap != 1 else ''}")
        if r.owner.verified: reasons.append("Owner marked verified")
        if r.available: reasons.append("Listing currently active")
        ranked.append((score, r, reasons))
    ranked.sort(key=lambda x: (x[0], x[1].created_at), reverse=True)
    return jsonify({
        "message": f"Found {len(ranked)} possible matches. Dates, eligibility and final approval are checked by OpenBench's booking workflow.",
        "ai_enabled": ai_used, "mode": "Gemini-assisted" if ai_used else "Smart keyword fallback",
        "parsed_query": interpreted if ai_used else prompt,
        "resources": [{"id": r.id, "name": r.name, "category": r.category, "location": r.location,
            "price": r.price, "price_unit": r.price_unit, "url": url_for("resource_detail", resource_id=r.id),
            "match_score": score, "reasons": reasons} for score, r, reasons in ranked[:12]]
    })

@app.route("/api/listing-assistant", methods=["POST"])
@roles_required("owner")
def listing_assistant():
    payload = request.get_json(silent=True) or {}
    raw = (payload.get("description") or "").strip()[:1800]
    name = (payload.get("name") or "resource").strip()[:140]
    category = (payload.get("category") or "Other").strip()[:80]
    if len(raw) < 10:
        return jsonify({"error": "Add a little more detail so the assistant can help."}), 400
    suggestion = None
    if os.environ.get("GEMINI_API_KEY"):
        try:
            from google import genai
            client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
            result = client.models.generate_content(model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"), contents=(
                "Improve this marketplace resource listing. Be factual, don't invent specs/certifications. Return concise friendly description plus a separate checklist of details owner should verify. Resource name: " + name + ". Category: " + category + ". Owner notes: " + raw))
            suggestion = (result.text or "").strip() or None
        except Exception:
            suggestion = None
    if not suggestion:
        suggestion = f"{name} is available to request through OpenBench. {raw}\n\nBefore publishing, confirm condition, included accessories, operating requirements, pickup/return arrangements, and any training or safety requirements."
    return jsonify({"suggestion": suggestion, "mode": "Gemini-assisted" if os.environ.get("GEMINI_API_KEY") else "Guided template"})

@app.route("/resources/<int:resource_id>/waitlist", methods=["POST"])
@roles_required("renter")
def join_waitlist(resource_id):
    resource = db.get_or_404(Resource, resource_id)
    existing = Waitlist.query.filter_by(resource_id=resource.id, user_id=current_user().id, status="WAITING").first()
    if existing:
        flash("You are already on the waitlist for this resource.", "info")
    else:
        entry = Waitlist(resource_id=resource.id, user_id=current_user().id, note=request.form.get("note", "").strip()[:300])
        db.session.add(entry)
        db.session.flush()
        log_action("WAITLIST_JOINED", f"Joined waitlist for {resource.name}")
        db.session.commit()
        flash("You joined the waitlist. The owner can review demand from the admin/operator workflow.", "success")
    return redirect(url_for("resource_detail", resource_id=resource.id))

@app.route("/impact")
def impact_dashboard():
    total_resources = Resource.query.filter_by(available=True).count()
    completed = Booking.query.filter_by(status="RETURNED").count()
    active = Booking.query.filter(Booking.status.in_(["APPROVED", "ACTIVE"])).count()
    hours = sum(max(0, (b.end_at-b.start_at).total_seconds()/3600) for b in Booking.query.filter_by(status="RETURNED").all())
    estimated_savings = sum((b.resource.price or 0) for b in Booking.query.filter_by(status="RETURNED").all())
    categories = db.session.query(Resource.category, db.func.count(Resource.id)).filter_by(available=True).group_by(Resource.category).order_by(db.func.count(Resource.id).desc()).all()
    return render_template("impact.html", total_resources=total_resources, completed=completed, active=active, hours=round(hours), estimated_savings=round(estimated_savings), categories=categories)

@app.route("/admin")
@roles_required("admin")
def admin_dashboard():
    users = User.query.order_by(User.created_at.desc()).all()
    resources = Resource.query.order_by(Resource.created_at.desc()).all()
    bookings = Booking.query.order_by(Booking.created_at.desc()).limit(30).all()
    incidents = Incident.query.order_by(Incident.created_at.desc()).all()
    waitlist = Waitlist.query.filter_by(status="WAITING").order_by(Waitlist.created_at.asc()).all()
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(50).all()
    stats = {"users": User.query.count(), "resources": Resource.query.count(), "bookings": Booking.query.count(), "open_incidents": Incident.query.filter_by(status="OPEN").count()}
    return render_template("admin.html", users=users, resources=resources, bookings=bookings, incidents=incidents, waitlist=waitlist, logs=logs, stats=stats)

@app.route("/admin/users/<int:user_id>/verify", methods=["POST"])
@roles_required("admin")
def admin_verify_user(user_id):
    user = db.get_or_404(User, user_id)
    user.verified = not user.verified
    log_action("USER_VERIFICATION_CHANGED", f"Admin set {user.email} verified={user.verified}")
    db.session.commit()
    flash("Verification status updated. This is an admin review flag, not a third-party identity check.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/resources/<int:resource_id>/toggle", methods=["POST"])
@roles_required("admin")
def admin_toggle_resource(resource_id):
    resource = db.get_or_404(Resource, resource_id)
    resource.available = not resource.available
    log_action("RESOURCE_VISIBILITY_CHANGED", f"{resource.name}: available={resource.available}")
    db.session.commit()
    flash("Resource visibility updated.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/incidents/<int:incident_id>/resolve", methods=["POST"])
@roles_required("admin")
def admin_resolve_incident(incident_id):
    incident = db.get_or_404(Incident, incident_id)
    incident.status = "RESOLVED"
    incident.resolution = request.form.get("resolution", "Reviewed by admin")[:500]
    log_action("INCIDENT_RESOLVED", incident.resolution, incident.booking_id)
    db.session.commit()
    flash("Incident marked resolved.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/health")
def health():
    return jsonify({"status": "ok", "app": "OpenBench"})

@app.errorhandler(413)
def file_too_large(_error):
    flash("The uploaded file is too large. Maximum upload size is 5 MB.", "error")
    return redirect(request.referrer or url_for("index"))

@app.errorhandler(403)
def forbidden(_error):
    return render_template("error.html", code=403, message="You do not have permission to perform that action."), 403

@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="We could not find that page or resource."), 404

def seed_demo():
    if User.query.first():
        if not User.query.filter_by(email="admin@openbench.demo").first():
            db.session.add(User(name="Demo Admin", email="admin@openbench.demo", password_hash=generate_password_hash("AdminDemo123!"), role="admin", verified=True))
            db.session.commit()
        return
    owner = User(name="Demo Owner", email="owner@openbench.demo", password_hash=generate_password_hash("OwnerDemo123!"), role="owner", verified=True)
    renter = User(name="Demo Renter", email="renter@openbench.demo", password_hash=generate_password_hash("RenterDemo123!"), role="renter", verified=True)
    admin = User(name="Demo Admin", email="admin@openbench.demo", password_hash=generate_password_hash("AdminDemo123!"), role="admin", verified=True)
    db.session.add_all([owner, renter, admin])
    db.session.flush()
    demo_resources = [
        Resource(owner_id=owner.id, name="Farm Tractor", category="Agriculture", description="A medium-duty tractor for common farm preparation tasks. Confirm operator capability and local conditions with the owner.", location="Dhule, Maharashtra", price=1800, price_unit="day", requirements="Valid operator licence/qualification where applicable; owner approval required."),
        Resource(owner_id=owner.id, name="Rotavator Attachment", category="Agriculture", description="Agricultural rotavator attachment for compatible tractors. Confirm compatibility before booking.", location="Dhule, Maharashtra", price=900, price_unit="day", requirements="Compatible tractor and safe operation required.", training_required=True),
        Resource(owner_id=owner.id, name="Mirrorless Camera Kit", category="Events & Media", description="Camera kit for student projects, events and content creation.", location="Shirpur, Maharashtra", price=650, price_unit="day", requirements="Handle carefully; return with all accessories."),
        Resource(owner_id=owner.id, name="Meeting Room", category="Properties & Spaces", description="Small meeting room suitable for team discussions and project planning.", location="Shirpur, Maharashtra", price=300, price_unit="hour", requirements="Leave the room clean and return access card."),
        Resource(owner_id=owner.id, name="Portable Generator", category="Construction & Industrial", description="Portable generator for approved temporary power needs.", location="Nashik, Maharashtra", price=1200, price_unit="day", requirements="Owner approval and safe operating conditions required.", training_required=True),
        Resource(owner_id=owner.id, name="Laptop for Project Work", category="Education & Labs", description="Laptop available for short-term project or workshop use.", location="Shirpur, Maharashtra", price=400, price_unit="day", requirements="Return with charger; no unauthorized software installation.")
    ]
    db.session.add_all(demo_resources)
    db.session.commit()

with app.app_context():
    db.create_all()
    # Demo accounts have public, predictable passwords. Enable seeding locally by
    # default, but disable it on Render unless explicitly requested for a demo.
    default_seed_setting = "false" if os.environ.get("RENDER") else "true"
    if os.environ.get("SEED_DEMO", default_seed_setting).lower() == "true":
        seed_demo()

if __name__ == "__main__":
    app.run(
        debug=os.environ.get("FLASK_DEBUG", "false" if os.environ.get("RENDER") else "true").lower() == "true",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
    )
