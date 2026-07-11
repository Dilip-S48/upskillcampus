
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin, LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = "quiz_secret_key_change_me"
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///quiz.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
from sqlalchemy import event
from sqlalchemy.engine import Engine
import sqlite3

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

login_manager = LoginManager(app)
login_manager.login_view = "login"

# ---------------------- Models ----------------------
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(10), default="user")  # "user" or "admin"
    results = db.relationship(
    'Result',
    backref='user',
    cascade="all, delete-orphan",
    passive_deletes=True,
    lazy=True
)

class Quiz(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    duration_minutes = db.Column(db.Integer, default=5)
    questions = db.relationship(
        'Question',
        backref='quiz',
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy=True
    )
    results = db.relationship(
        'Result',
        backref='quiz',
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy=True
    )

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.String(300), nullable=False)
    option_a = db.Column(db.String(200), nullable=False)
    option_b = db.Column(db.String(200), nullable=False)
    option_c = db.Column(db.String(200), nullable=False)
    option_d = db.Column(db.String(200), nullable=False)
    correct = db.Column(db.String(1), nullable=False)
    quiz_id = db.Column(
        db.Integer,
        db.ForeignKey('quiz.id', ondelete="CASCADE"),
        nullable=False
    )

class Result(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete="CASCADE"), nullable=False)
    quiz_id = db.Column(
        db.Integer,
        db.ForeignKey('quiz.id', ondelete="CASCADE"),
        nullable=False
    )
    score = db.Column(db.Integer)
    total = db.Column(db.Integer)
    percent = db.Column(db.Float)
    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp())
    answers_json = db.Column(db.Text)  # stores user answers as JSON


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ---------------------- Utilities ----------------------
def ensure_admin():
    existing = User.query.filter_by(username='admin').first()
    if not existing:
        admin = User(username='admin', password=generate_password_hash('admin'), role='admin')
        db.session.add(admin)
        db.session.commit()


def admin_required():
    if not current_user.is_authenticated or current_user.role != 'admin':
        flash("Access denied! Admins only.", "danger")
        return False
    return True

# ---------------------- Routes ----------------------
@app.route('/')
def index():
    quizzes = Quiz.query.all()
    stats = None
    if current_user.is_authenticated and current_user.role == 'admin':
        stats = {
            "users": User.query.count(),
            "quizzes": Quiz.query.count(),
            "attempts": Result.query.count()
        }
    return render_template('index.html', quizzes=quizzes, stats=stats)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        if not username or not password:
            flash("Username and password are required.", "danger")
            return redirect(url_for('register'))
        if User.query.filter_by(username=username).first():
            flash("Username already exists.", "danger")
            return redirect(url_for('register'))
        user = User(username=username, password=generate_password_hash(password), role="user")
        db.session.add(user)
        db.session.commit()
        flash("Registration successful! Please log in.", "success")
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user, remember=True, duration=timedelta(days=7))
            flash("Logged in successfully!", "success")
            return redirect(url_for('index'))
        else:
            flash("Invalid username or password.", "danger")
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("Logged out successfully.", "info")
    return redirect(url_for('index'))

# ----- Admin Quiz Management -----
@app.route('/add_quiz', methods=['GET', 'POST'])
@login_required
def add_quiz():
    if not admin_required():
        return redirect(url_for('index'))
    if request.method == 'POST':
        title = request.form['title'].strip()
        duration = int(request.form.get('duration_minutes', 5))
        if not title:
            flash("Title is required.", "danger")
            return redirect(url_for('add_quiz'))
        quiz = Quiz(title=title, duration_minutes=duration)
        db.session.add(quiz)
        db.session.commit()
        flash("Quiz created! Now add questions.", "success")
        return redirect(url_for('manage_quiz', quiz_id=quiz.id))
    return render_template('add_quiz.html')

@app.route('/manage_quiz/<int:quiz_id>', methods=['GET', 'POST'])
@login_required
def manage_quiz(quiz_id):
    if not admin_required():
        return redirect(url_for('index'))
    quiz = Quiz.query.get_or_404(quiz_id)
    if request.method == 'POST':
        text = request.form['text'].strip()
        option_a = request.form['option_a'].strip()
        option_b = request.form['option_b'].strip()
        option_c = request.form['option_c'].strip()
        option_d = request.form['option_d'].strip()
        correct = request.form['correct']
        if not all([text, option_a, option_b, option_c, option_d, correct]):
            flash("All fields are required.", "danger")
            return redirect(url_for('manage_quiz', quiz_id=quiz.id))
        q = Question(text=text, option_a=option_a, option_b=option_b, option_c=option_c, option_d=option_d, correct=correct, quiz=quiz)
        db.session.add(q)
        db.session.commit()
        flash("Question added!", "success")
        return redirect(url_for('manage_quiz', quiz_id=quiz.id))
    return render_template('manage_quiz.html', quiz=quiz)

@app.route('/update_quiz/<int:quiz_id>', methods=['POST'])
@login_required
def update_quiz(quiz_id):
    if not admin_required():
        return redirect(url_for('index'))
    quiz = Quiz.query.get_or_404(quiz_id)
    quiz.title = request.form['title'].strip()
    quiz.duration_minutes = int(request.form['duration_minutes'])
    db.session.commit()
    flash("Quiz details updated!", "success")
    return redirect(url_for('manage_quiz', quiz_id=quiz.id))

@app.route('/edit_question/<int:question_id>', methods=['GET', 'POST'])
@login_required
def edit_question(question_id):
    if not admin_required():
        return redirect(url_for('index'))
    question = Question.query.get_or_404(question_id)
    if request.method == 'POST':
        question.text = request.form['text'].strip()
        question.option_a = request.form['option_a'].strip()
        question.option_b = request.form['option_b'].strip()
        question.option_c = request.form['option_c'].strip()
        question.option_d = request.form['option_d'].strip()
        question.correct = request.form['correct']
        db.session.commit()
        flash("Question updated!", "success")
        return redirect(url_for('manage_quiz', quiz_id=question.quiz_id))
    return render_template('edit_question.html', question=question)

@app.route('/delete_quiz/<int:quiz_id>', methods=['POST'])
@login_required
def delete_quiz(quiz_id):
    if not admin_required():
        return redirect(url_for('index'))
    quiz = Quiz.query.get_or_404(quiz_id)
    db.session.delete(quiz)
    db.session.commit()
    flash("Quiz deleted!", "warning")
    return redirect(url_for('index'))

@app.route('/delete_question/<int:question_id>', methods=['POST'])
@login_required
def delete_question(question_id):
    if not admin_required():
        return redirect(url_for('index'))
    q = Question.query.get_or_404(question_id)
    quiz_id = q.quiz_id
    db.session.delete(q)
    db.session.commit()
    flash("Question deleted!", "warning")
    return redirect(url_for('manage_quiz', quiz_id=quiz_id))

# ----- Taking Quizzes & Results -----
@app.route('/quiz/<int:quiz_id>', methods=['GET', 'POST'])
@login_required
def quiz(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)
    key = f"quiz_start_{quiz_id}"
    # Initialize / enforce server-side timer
    if request.method == 'GET':
        if key not in session:
            session[key] = datetime.utcnow().isoformat()
    else:
        # POST -> check timer
        try:
            start = datetime.fromisoformat(session.get(key))
        except Exception:
            start = datetime.utcnow()
        elapsed = (datetime.utcnow() - start).total_seconds()
        allowed = quiz.duration_minutes * 60
        time_up = elapsed > allowed
        score = 0
        total = len(quiz.questions)
        answers = {}
        for q in quiz.questions:
            user_answer = request.form.get(str(q.id))
            answers[q.id] = user_answer or ""
            if user_answer == q.correct:
                score += 1
        percent = round((score / total) * 100, 2) if total else 0
        # Save result
        result = Result(user_id=current_user.id, quiz_id=quiz.id, score=score, total=total, percent=percent, answers_json=json.dumps(answers))
        db.session.add(result)
        db.session.commit()
        # Clear start time
        session.pop(key, None)
        if time_up:
            flash("Time is up! Your answers were auto-submitted.", "warning")
        return render_template('result.html', quiz=quiz, score=score, total=total, percent=percent, answers=answers)
    return render_template('quiz.html', quiz=quiz)

@app.route('/my_results')
@login_required
def my_results():
    results = Result.query.filter_by(user_id=current_user.id).order_by(Result.timestamp.desc()).all()
    return render_template('my_results.html', results=results)

@app.route('/result/<int:result_id>')
@login_required
def view_result(result_id):
    result = Result.query.get_or_404(result_id)
    if result.user_id != current_user.id and current_user.role != 'admin':
        flash("Access denied!", "danger")
        return redirect(url_for('my_results'))

    quiz = Quiz.query.get(result.quiz_id)
    answers = json.loads(result.answers_json or "{}")

    # Build detailed data for template
    details = []
    for q in quiz.questions:
        details.append({
            "question": q.text,
            "options": {
                "A": q.option_a,
                "B": q.option_b,
                "C": q.option_c,
                "D": q.option_d
            },
            "correct": q.correct,
            "user_answer": answers.get(str(q.id), None)
        })

    return render_template("view_result.html", quiz=quiz, result=result, details=details)

@app.route('/admin/users')
@login_required
def admin_users():
    if not admin_required():
        return redirect(url_for('index'))
    users = User.query.all()
    return render_template("admin_users.html", users=users)


@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if not admin_required():
        return redirect(url_for('index'))
    user = User.query.get_or_404(user_id)
    if user.role == "admin":
        flash("You cannot delete the admin account!", "danger")
        return redirect(url_for('admin_users'))
    db.session.delete(user)
    db.session.commit()
    flash(f"User '{user.username}' deleted successfully.", "warning")
    return redirect(url_for('admin_users'))


# ---------------------- Bootstrap the DB ----------------------
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        ensure_admin()
    app.run(debug=True)
