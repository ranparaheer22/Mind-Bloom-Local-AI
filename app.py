import os
import io
import time
import uuid
import random
import calendar
from datetime import datetime, date, timedelta
from functools import wraps

from dotenv import load_dotenv
load_dotenv()  # reads a local .env file if present — no effect on Render, which uses real env vars

_gemini_key_check = os.environ.get('GEMINI_API_KEY')
_self_hosted_ai_configured = bool(
    os.environ.get('AI_MODEL_URL', '').strip()
    and os.environ.get('AI_SERVICE_TOKEN', '').strip()
)
if _self_hosted_ai_configured:
    print('[startup] Self-hosted AI service configured; no Gemini API key is required.')
elif _gemini_key_check:
    print('[startup] Optional Gemini fallback is configured.')
else:
    print('[startup] No AI endpoint configured yet; local rule-based chat fallback is enabled.')

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file, Response, stream_with_context
import json
import pickle
from sqlalchemy import inspect, text

# The ML stack (numpy/pandas/scikit-learn) only powers the full PHQ-9/GAD-7 assessment.
# On some Windows machines, antivirus/Application Control policies can block these compiled
# packages from loading. Rather than crashing the entire app if that happens, we import them
# defensively — every other module (journal, chat, meditation, etc.) keeps working regardless,
# and the assessment feature shows a clear message instead of a hard crash.
ML_STACK_AVAILABLE = True
ML_STACK_ERROR = None
try:
    import pandas as pd
    import numpy as np
    from sklearn.neighbors import KNeighborsClassifier
    from sklearn.preprocessing import LabelEncoder, StandardScaler
    from sklearn.model_selection import train_test_split
except Exception as e:
    ML_STACK_AVAILABLE = False
    ML_STACK_ERROR = f"{type(e).__name__}: {e}"
    print(f"[startup] WARNING: ML libraries failed to load ({ML_STACK_ERROR}). "
          f"The full assessment feature will be unavailable, but the rest of the app will still run.")

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from google import genai
from google.genai import types as genai_types

from models import (
    db, User, JournalEntry, JournalMedia, MoodLog, TestResult, DailyCheckin,
    MeditationSession, FeatureAnnouncement, GratitudeEntry, SleepLog, Habit, HabitLog,
    ChatSession, ChatMessage, ExerciseLog
)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY') or os.urandom(32)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=3650)  # long-lived remembered login; ends when user logs out or clears app/browser data

# ── DATABASE CONFIG ──
db_url = os.environ.get('DATABASE_URL', 'sqlite:///mindbloom.db')
# Render (and some providers) hand out postgres:// — SQLAlchemy needs postgresql://
if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# ── UPLOADS (photo / video / audio) ──
UPLOAD_FOLDER = os.path.join('static', 'uploads', 'journal')
ALLOWED_EXT = {
    'photo': {'png', 'jpg', 'jpeg', 'gif', 'webp'},
    'video': {'mp4', 'mov', 'webm', 'avi', 'mkv'},
    'audio': {'mp3', 'wav', 'm4a', 'ogg', 'weba', 'aac'},
}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 120 * 1024 * 1024  # 120MB per request — video recordings run much larger than photos
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


@app.errorhandler(413)
def too_large(e):
    return jsonify({'success': False, 'error': 'Those files are too large. Try smaller or fewer at once.'}), 413


db.init_app(app)

MODEL_PATH = 'model/knn_model.pkl'
SCALER_PATH = 'model/scaler.pkl'
ENCODER_PATH = 'model/encoder.pkl'


def train_and_save_model():
    os.makedirs('model', exist_ok=True)
    df = pd.read_csv('Dataset.csv')
    df = df.dropna()

    le_gender = LabelEncoder()
    df['Gender_enc'] = le_gender.fit_transform(df['Gender'])

    features = [
        'Age', 'Gender_enc', 'Sleep_Hours', 'Work_Study_Hours',
        'Physical_Activity_Days_Per_Week', 'Social_Interaction_Score_0_10',
        'Stress_Level_1_10', 'Anxiety_Score_0_21', 'Depression_Score_0_27',
        'Screen_Time_Hours', 'Caffeine_Intake_0_5', 'Alcohol_Consumption_0_5',
        'Family_History_0_1', 'Therapy_History_0_1'
    ]

    X = df[features].values
    y = df['Mental_Health_Condition'].values

    le_cond = LabelEncoder()
    y_enc = le_cond.fit_transform(y)

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    X_train, X_test, y_train, y_test = train_test_split(X_scaled, y_enc, test_size=0.2, random_state=42)

    knn = KNeighborsClassifier(n_neighbors=5, metric='euclidean', algorithm='ball_tree', n_jobs=-1)
    knn.fit(X_train, y_train)

    with open(MODEL_PATH, 'wb') as f:
        pickle.dump(knn, f)
    with open(SCALER_PATH, 'wb') as f:
        pickle.dump(scaler, f)
    with open(ENCODER_PATH, 'wb') as f:
        pickle.dump({'label_encoder': le_cond, 'gender_encoder': le_gender}, f)

    print(f"Model trained. Accuracy: {knn.score(X_test, y_test):.2f}")


def load_model():
    with open(MODEL_PATH, 'rb') as f:
        knn = pickle.load(f)
    with open(SCALER_PATH, 'rb') as f:
        scaler = pickle.load(f)
    with open(ENCODER_PATH, 'rb') as f:
        encoders = pickle.load(f)
    return knn, scaler, encoders


if ML_STACK_AVAILABLE and not os.path.exists(MODEL_PATH):
    train_and_save_model()


@app.before_request
def sync_saved_preferences():
    uid = session.get('user_id')
    if uid:
        user = db.session.get(User, uid)
        if user:
            session['language'] = user.language or 'en'
            session['theme'] = user.theme or 'light'


@app.context_processor
def inject_crisis_resources():
    return {'crisis_resources': CRISIS_RESOURCES}


with app.app_context():
    db.create_all()
    # Safe additive migration for databases created before the theme preference existed.
    user_columns = {column['name'] for column in inspect(db.engine).get_columns('users')}
    if 'theme' not in user_columns:
        db.session.execute(text("ALTER TABLE users ADD COLUMN theme VARCHAR(10) DEFAULT 'light'"))
        db.session.commit()
    db.session.execute(text("UPDATE users SET theme = 'light' WHERE theme IS NULL OR theme = ''"))
    # The Journal PIN feature is retired; remove stored PIN hashes so no dormant lock remains.
    db.session.execute(text("UPDATE users SET journal_pin_hash = NULL"))
    db.session.commit()

    if FeatureAnnouncement.query.count() == 0:
        db.session.add_all([
            FeatureAnnouncement(
                icon="🧘", title="Meditation module launched",
                message="Set a meditation countdown, receive a gentle end-of-session alert, and play or pause calming background music."
            ),
            FeatureAnnouncement(
                icon="🌤", title="Daily check-in added",
                message="Four quick taps log your mood, sleep, stress, and energy every day."
            ),
            FeatureAnnouncement(
                icon="📱", title="Mobile app-style redesign",
                message="A new bottom navigation bar puts every module one tap away."
            ),
        ])
        db.session.commit()

    update_title = 'Mind Bloom update: Memories, language, themes & companion'
    update_message = 'Dashboard weather, age-aware exercise suggestions, daily tree growth, clearer sign-up/login, meditation countdown with calming background music, Light/Dark theme settings, Video Companion and multilingual chat improvements, and monthly/annual Memories.'
    existing_update = FeatureAnnouncement.query.filter_by(title=update_title).first()
    if not existing_update:
        db.session.add(FeatureAnnouncement(icon='🌿', title=update_title, message=update_message))
        db.session.commit()
    elif 'Journal PIN' in (existing_update.message or '') or 'dashboard theme toggle removed' in (existing_update.message or ''):
        existing_update.message = update_message
        db.session.commit()

    # One-time cleanup: merge any duplicate (user_id, checkin_date) rows that may have been
    # created before the unique constraint existed, keeping the most recently saved one.
    # This directly fixes the "daily check-in won't update" symptom, which happens when
    # duplicate rows exist and different queries pick different ones non-deterministically.
    dupe_keys = (
        db.session.query(DailyCheckin.user_id, DailyCheckin.checkin_date)
        .group_by(DailyCheckin.user_id, DailyCheckin.checkin_date)
        .having(db.func.count(DailyCheckin.id) > 1)
        .all()
    )
    for uid, cdate in dupe_keys:
        rows = DailyCheckin.query.filter_by(user_id=uid, checkin_date=cdate) \
            .order_by(DailyCheckin.id.desc()).all()
        for stale in rows[1:]:  # keep rows[0] (most recent id), drop the rest
            db.session.delete(stale)
    if dupe_keys:
        db.session.commit()


# ── AUTH HELPERS ──
def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('signin'))
        return view_func(*args, **kwargs)
    return wrapped


def current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    return User.query.get(uid)


def journal_unlock_required(view_func):
    """Compatibility no-op: the optional Journal PIN lock was retired."""
    return view_func


def detect_media_type(filename):
    """Return 'photo' | 'video' | 'audio' based on extension, or None if unsupported."""
    if '.' not in filename:
        return None
    ext = filename.rsplit('.', 1)[1].lower()
    for media_type, exts in ALLOWED_EXT.items():
        if ext in exts:
            return media_type
    return None


def shift_date(d, years=0, months=0):
    """Shift a date by whole years/months, clamping the day to the target month's length
    (e.g. Jan 31 shifted -1 month lands on Feb 28/29, not an invalid date)."""
    month_index = d.month - 1 + months
    year = d.year + years + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def compute_streak(dates_set):
    """Given a set of date objects a user was active on, return (current_streak, longest_streak, total_days).
    Handles missed days correctly: current streak breaks the moment a day (other than today, if not yet
    logged) is missing."""
    if not dates_set:
        return 0, 0, 0

    total_days = len(dates_set)
    today = date.today()

    # current streak: walk backward from today (or yesterday, if today has no entry yet)
    current = 0
    cursor = today if today in dates_set else today - timedelta(days=1)
    while cursor in dates_set:
        current += 1
        cursor -= timedelta(days=1)

    # longest streak: scan all dates in order
    longest = 0
    run = 0
    prev = None
    for d in sorted(dates_set):
        if prev is not None and (d - prev).days == 1:
            run += 1
        else:
            run = 1
        longest = max(longest, run)
        prev = d

    return current, longest, total_days


JOURNAL_PROMPTS = [
    "What's one thing that went well today?",
    "What made you smile today?",
    "What is currently on your mind?",
    "What are you grateful for right now?",
    "What was difficult today, and how did you handle it?",
    "What would you like tomorrow to look like?",
    "What's something you're proud of this week?",
    "Who or what supported you today?",
]

COMMON_JOURNAL_TAGS = ["work", "family", "college", "friends", "health", "relationships", "goals"]

# Crisis helpline numbers — India-focused given the app's language set, plus general guidance.
# These are meant to be easy to update/region-adjust, not hard-coded assumptions about the user's location.
CRISIS_RESOURCES = [
    {"name": "KIRAN Mental Health Helpline (India)", "number": "1800-599-0019", "note": "Toll-free, 24/7"},
    {"name": "iCall (TISS)", "number": "9152987821", "note": "Mon–Sat, 8am–10pm"},
    {"name": "Emergency services (India)", "number": "112", "note": "Police / fire / ambulance"},
    {"name": "Outside India?", "number": "findahelpline.com", "note": "Search helplines by country"},
]

RESOURCE_LIBRARY = [
    {"category": "Breathing", "icon": "🌬️", "title": "Box breathing", "body": "Inhale for 4 seconds, hold for 4, exhale for 4, hold for 4. Repeat for 2-3 minutes to calm the nervous system."},
    {"category": "Breathing", "icon": "🌬️", "title": "4-7-8 breathing", "body": "Inhale for 4 seconds, hold for 7, exhale slowly for 8. Often used to ease anxiety or help with falling asleep."},
    {"category": "Grounding", "icon": "🌳", "title": "5-4-3-2-1 technique", "body": "Name 5 things you can see, 4 you can touch, 3 you can hear, 2 you can smell, 1 you can taste. Helps interrupt spiraling thoughts."},
    {"category": "Grounding", "icon": "🌳", "title": "Cold water reset", "body": "Splashing cool water on your face or holding a cold object can help interrupt intense emotional states."},
    {"category": "Meditation", "icon": "🧘", "title": "Body scan", "body": "Slowly bring attention to each part of your body from feet to head, noticing tension without judgment."},
    {"category": "Meditation", "icon": "🧘", "title": "Loving-kindness", "body": "Silently repeat well-wishes to yourself, then to others: 'May I be safe, may I be at ease.'"},
    {"category": "Sleep", "icon": "🌙", "title": "Wind-down routine", "body": "Dim lights and step away from screens 30-60 minutes before bed to help your body prepare for sleep."},
    {"category": "Sleep", "icon": "🌙", "title": "Consistent sleep schedule", "body": "Going to bed and waking at the same time daily — even weekends — strengthens your natural sleep rhythm."},
    {"category": "Coping", "icon": "💛", "title": "Name the feeling", "body": "Simply labeling an emotion ('I'm feeling anxious') can reduce its intensity — this is a well-studied effect."},
    {"category": "Coping", "icon": "💛", "title": "One small step", "body": "When everything feels like too much, pick the smallest possible next action rather than the whole task."},
    {"category": "Journaling", "icon": "📔", "title": "Brain dump", "body": "Write without stopping or editing for 5 minutes. The goal is getting thoughts out, not making sense."},
    {"category": "Professional support", "icon": "🧑‍⚕️", "title": "When to reach out", "body": "If low mood, anxiety, or stress are lasting weeks and affecting daily life, a licensed therapist or doctor can help — this app is a companion, not a replacement for care."},
]

# ══════════════════════════════════════════
# EXERCISE & MOVEMENT — guided routine library
# ══════════════════════════════════════════
GUIDED_ROUTINES = {
    'morning_stretch': {
        'id': 'morning_stretch', 'name': 'Morning Stretch', 'icon': '🌅', 'duration_label': 'Approx. 5 minutes', 'category': 'physical',
        'exercises': [
            {'name': 'Neck Stretch', 'instruction': 'Gently tilt your head toward one shoulder, hold, then switch sides. Keep shoulders relaxed.', 'seconds': 45, 'anim': 'neck_tilt'},
            {'name': 'Shoulder Rolls', 'instruction': 'Slowly roll your shoulders backward in a comfortable circular motion.', 'seconds': 45, 'anim': 'shoulder_roll'},
            {'name': 'Arm Stretch', 'instruction': 'Reach one arm across your chest, gently pull with the other, hold, then switch.', 'seconds': 45, 'anim': 'arm_reach'},
            {'name': 'Side Stretch', 'instruction': 'Reach one arm overhead and lean gently to the opposite side, feeling a stretch along your torso.', 'seconds': 45, 'anim': 'side_bend'},
            {'name': 'Forward Fold', 'instruction': 'Slowly hinge forward from the hips, letting your arms hang, knees softly bent.', 'seconds': 45, 'anim': 'forward_fold'},
            {'name': 'Gentle Leg Stretch', 'instruction': 'Sit or stand and gently reach toward your toes, stretching the back of your legs.', 'seconds': 45, 'anim': 'leg_reach'},
        ],
    },
    'desk_break': {
        'id': 'desk_break', 'name': 'Desk Break', 'icon': '🪑', 'duration_label': 'Approx. 5 minutes', 'category': 'physical',
        'exercises': [
            {'name': 'Neck Rotation', 'instruction': 'Slowly rotate your neck in a gentle circle, one direction then the other.', 'seconds': 45, 'anim': 'neck_rotate'},
            {'name': 'Shoulder Rolls', 'instruction': 'Roll your shoulders backward, then forward, releasing tension from sitting.', 'seconds': 45, 'anim': 'shoulder_roll'},
            {'name': 'Wrist Stretch', 'instruction': 'Extend one arm, gently pull fingers back with the other hand, then switch.', 'seconds': 45, 'anim': 'wrist_flex'},
            {'name': 'Seated Spinal Stretch', 'instruction': 'While seated, gently twist your torso to one side using the chair for support, then switch.', 'seconds': 45, 'anim': 'twist'},
            {'name': 'Standing Side Stretch', 'instruction': 'Stand up, reach one arm overhead, and lean gently to the side.', 'seconds': 45, 'anim': 'side_bend'},
            {'name': 'Short Walk', 'instruction': 'Take a short walk around your room or office to get your blood flowing.', 'seconds': 60, 'anim': 'march'},
        ],
    },
    'quick_cardio': {
        'id': 'quick_cardio', 'name': 'Quick Cardio', 'icon': '🏃', 'duration_label': 'Approx. 5-10 minutes', 'category': 'physical',
        'exercises': [
            {'name': 'March in Place', 'instruction': 'Lift your knees comfortably while marching in place at a steady pace.', 'seconds': 60, 'anim': 'march'},
            {'name': 'Step Touch', 'instruction': 'Step side to side, tapping your foot each time, arms moving naturally.', 'seconds': 60, 'anim': 'step_touch'},
            {'name': 'Beginner High Knees', 'instruction': 'Lift your knees a little higher than marching, at a pace that feels comfortable.', 'seconds': 60, 'anim': 'high_knees'},
            {'name': 'Arm Swings', 'instruction': 'Swing both arms forward and back in a controlled, rhythmic motion.', 'seconds': 45, 'anim': 'arm_swing'},
            {'name': 'Bodyweight Squats', 'instruction': 'Lower into a squat as if sitting in a chair, then stand back up, at your own pace.', 'seconds': 60, 'anim': 'squat'},
            {'name': 'Cooldown', 'instruction': 'Slow your movements gradually and take a few deep breaths to bring your heart rate down.', 'seconds': 45, 'anim': 'breathing'},
        ],
    },
    'relax_stretch': {
        'id': 'relax_stretch', 'name': 'Relax & Stretch', 'icon': '🧘', 'duration_label': 'Approx. 5 minutes', 'category': 'mental',
        'exercises': [
            {'name': 'Deep Breathing', 'instruction': 'Sit comfortably and take slow, deep breaths — in through the nose, out through the mouth.', 'seconds': 45, 'anim': 'breathing'},
            {'name': 'Neck Stretch', 'instruction': 'Gently tilt your head side to side, releasing tension in your neck.', 'seconds': 45, 'anim': 'neck_tilt'},
            {'name': 'Shoulder Stretch', 'instruction': 'Bring one arm across your body and hold gently with the other arm.', 'seconds': 45, 'anim': 'shoulder_roll'},
            {'name': 'Gentle Cat-Cow Movement', 'instruction': 'On hands and knees, alternate between arching and rounding your back slowly.', 'seconds': 45, 'anim': 'cat_cow'},
            {'name': 'Hamstring Stretch', 'instruction': 'Sit with one leg extended and gently reach toward your foot, keeping your back long.', 'seconds': 45, 'anim': 'leg_reach'},
            {'name': 'Relaxation', 'instruction': 'Sit or lie comfortably, close your eyes if it helps, and simply breathe for a moment.', 'seconds': 45, 'anim': 'breathing'},
        ],
    },
    'mindful_breathing': {
        'id': 'mindful_breathing', 'name': 'Mindful Breathing', 'icon': '🌬️', 'duration_label': 'Approx. 5 minutes', 'category': 'mental',
        'exercises': [
            {'name': 'Box Breathing', 'instruction': 'Inhale for 4 counts, hold for 4, exhale for 4, hold for 4. Repeat at your own pace.', 'seconds': 60, 'anim': 'breathing'},
            {'name': '4-7-8 Breathing', 'instruction': 'Inhale for 4 counts, hold for 7, exhale slowly for 8. This can help calm a racing mind.', 'seconds': 60, 'anim': 'breathing'},
            {'name': 'Belly Breathing', 'instruction': 'Place a hand on your belly, breathe so it rises and falls rather than your chest.', 'seconds': 60, 'anim': 'breathing'},
            {'name': 'Counting Breath', 'instruction': 'Silently count each exhale up to 10, then start again from one.', 'seconds': 60, 'anim': 'breathing'},
            {'name': 'Sighing Breath', 'instruction': 'Take a deep inhale, then let out a long, audible sigh. Repeat a few times.', 'seconds': 45, 'anim': 'breathing'},
            {'name': 'Settling Breath', 'instruction': 'Let your breathing return to its natural rhythm, just noticing it without changing anything.', 'seconds': 45, 'anim': 'breathing'},
        ],
    },
    'calm_body_scan': {
        'id': 'calm_body_scan', 'name': 'Calm Body Scan', 'icon': '☁️', 'duration_label': 'Approx. 5 minutes', 'category': 'mental',
        'exercises': [
            {'name': 'Grounding Check-in', 'instruction': 'Sit or lie comfortably. Notice five things you can feel — the chair, the floor, your clothes.', 'seconds': 45, 'anim': 'breathing'},
            {'name': 'Shoulders & Neck Scan', 'instruction': 'Bring attention to your shoulders and neck. Notice any tension, and let it soften.', 'seconds': 45, 'anim': 'neck_tilt'},
            {'name': 'Arms & Hands Scan', 'instruction': 'Notice your arms and hands. Let them feel heavy and relaxed, resting wherever they are.', 'seconds': 45, 'anim': 'breathing'},
            {'name': 'Chest & Breath Scan', 'instruction': 'Bring attention to your chest rising and falling with each breath, without changing it.', 'seconds': 45, 'anim': 'breathing'},
            {'name': 'Legs & Feet Scan', 'instruction': 'Notice your legs and feet. Let them feel supported by the ground or chair beneath you.', 'seconds': 45, 'anim': 'breathing'},
            {'name': 'Whole-Body Release', 'instruction': 'Take one more slow breath, noticing your whole body feeling a little more settled.', 'seconds': 45, 'anim': 'breathing'},
        ],
    },
}

ACTIVITY_TYPES = ['Walking', 'Yoga', 'Stretching', 'Running', 'Gym Workout', 'Cycling', 'Dancing', 'Other']


TREE_MONTHLY_TARGET_MINUTES = 200  # exercise minutes in a calendar month for a "fully grown" tree
TREE_STAGES = [
    (0, '🌱', 'Seed'), (20, '🌿', 'Sprout'), (45, '🪴', 'Growing'), (75, '🌳', 'Young tree'), (100, '🌲', 'Full grown'),
]


def get_exercise_suggestion(user_id):
    """A non-clinical suggestion that weighs (in priority order): the latest full assessment,
    today's check-in, and recent meditation activity — reusing existing data rather than a
    separate mood system. Returns a dict with the message, a recommended category, a specific
    routine id, and the reasoning so the user can see why it was suggested."""
    latest_test = TestResult.query.filter_by(user_id=user_id).order_by(TestResult.created_at.desc()).first()
    today_checkin = DailyCheckin.query.filter_by(user_id=user_id, checkin_date=date.today()) \
        .order_by(DailyCheckin.id.desc()).first()
    week_start = date.today() - timedelta(days=6)
    recent_meditation_minutes = db.session.query(db.func.coalesce(db.func.sum(MeditationSession.duration_minutes), 0)) \
        .filter(MeditationSession.user_id == user_id, MeditationSession.logged_at >= week_start).scalar()

    # Priority 1: the full assessment, if elevated
    if latest_test and (latest_test.anxiety_score or 0) >= 10:
        return {
            'text': "Your latest assessment showed elevated anxiety — a calming breathing routine may help.",
            'category': 'mental', 'routine_id': 'mindful_breathing'
        }
    if latest_test and (latest_test.depression_score or 0) >= 10:
        return {
            'text': "Gentle movement can be a helpful complement alongside how you've been feeling lately.",
            'category': 'physical', 'routine_id': 'morning_stretch'
        }

    # Priority 2: today's quick check-in
    if today_checkin:
        if today_checkin.stress_level == 'High':
            return {'text': "Your stress was marked high today — a calming routine may help.", 'category': 'mental', 'routine_id': 'relax_stretch'}
        if today_checkin.energy_level == 'Low':
            return {'text': "Low energy today — a gentle stretch can help you ease in.", 'category': 'physical', 'routine_id': 'morning_stretch'}
        if today_checkin.energy_level == 'High':
            return {'text': "Good energy today — a quick cardio session could feel great.", 'category': 'physical', 'routine_id': 'quick_cardio'}

    # Priority 3: how much you've been meditating this week — nudge toward whichever you've done less of
    if not today_checkin and not latest_test and not recent_meditation_minutes:
        return {'text': "Choose a beginner-friendly routine and get moving at your own pace.", 'category': None, 'routine_id': None}
    if recent_meditation_minutes < 10:
        return {'text': "You haven't meditated much this week — a short breathing routine might help balance things out.", 'category': 'mental', 'routine_id': 'mindful_breathing'}
    return {'text': "You've been doing well with mindfulness — try pairing it with some movement today.", 'category': 'physical', 'routine_id': 'desk_break'}


DAILY_TREE_TARGET_MINUTES = 30
DAILY_TREE_STAGES = [
    (0, '🌱', 'Seed'), (5, '🌿', 'Sprout'), (10, '🪴', 'Growing'), (20, '🌳', 'Young tree'), (30, '🌲', 'Mature tree')
]


def get_tree_growth(user_id):
    """Daily seed growth from today's minutes; all dated exercise logs remain as history."""
    today = date.today()
    today_minutes = db.session.query(db.func.coalesce(db.func.sum(ExerciseLog.duration_minutes), 0)) \
        .filter(ExerciseLog.user_id == user_id, ExerciseLog.log_date == today).scalar()
    all_time_minutes = db.session.query(db.func.coalesce(db.func.sum(ExerciseLog.duration_minutes), 0)) \
        .filter(ExerciseLog.user_id == user_id).scalar()
    percent = min(100, round((today_minutes / DAILY_TREE_TARGET_MINUTES) * 100)) if DAILY_TREE_TARGET_MINUTES else 0
    stage_emoji, stage_label = DAILY_TREE_STAGES[0][1], DAILY_TREE_STAGES[0][2]
    next_threshold = DAILY_TREE_TARGET_MINUTES
    for threshold, emoji, label in DAILY_TREE_STAGES:
        if today_minutes >= threshold:
            stage_emoji, stage_label = emoji, label
    for threshold, _, _ in DAILY_TREE_STAGES:
        if today_minutes < threshold:
            next_threshold = threshold
            break
    user = db.session.get(User, user_id)
    current_month_key = today.strftime('%Y-%m')
    is_fully_grown = percent >= 100
    reward_available = is_fully_grown and user.tree_reward_claimed_month != current_month_key
    return {
        'minutes_this_month': round(today_minutes, 1), 'minutes_today': round(today_minutes, 1),
        'all_time_minutes': round(all_time_minutes, 1), 'target_minutes': DAILY_TREE_TARGET_MINUTES,
        'next_stage_minutes': next_threshold, 'minutes_to_next_stage': max(0, round(next_threshold - today_minutes, 1)),
        'percent': percent, 'stage_emoji': stage_emoji, 'stage_label': stage_label,
        'is_fully_grown': is_fully_grown, 'reward_available': reward_available,
    }


# ══════════════════════════════════════════
# CHAT COMPANION
# ══════════════════════════════════════════
CRISIS_KEYWORDS = [
    "kill myself", "killing myself", "want to die", "wish i was dead", "wish i were dead",
    "end my life", "ending my life", "suicide", "suicidal", "no reason to live",
    "better off dead", "hurt myself", "hurting myself", "self harm", "self-harm",
    "cut myself", "cutting myself", "can't go on", "cant go on", "not worth living",
    "end it all", "give up on life",
]


def contains_crisis_language(text):
    lowered = (text or '').lower()
    return any(phrase in lowered for phrase in CRISIS_KEYWORDS)


CRISIS_RESPONSE_TEXTS = {
    'en': "I am here for you. ❤️\n\nPlease know that you are not alone, and there are caring people who want to support you through this painful moment. 🫂\n\nIf you might hurt yourself or feel unable to stay safe, please contact someone who can help right now. In India, call Tele-MANAS at 14416 or emergency services at 112. You can also call KIRAN at 1800-599-0019, or visit findahelpline.com for support in other countries.\n\nPlease reach out to a trusted friend, family member, or qualified professional and, if possible, stay with someone while this feels intense. Your life matters. 💛",
    'hi': "मैं आपके साथ हूँ। ❤️\n\nकृपया याद रखें कि आप अकेले नहीं हैं। ऐसे लोग हैं जो इस कठिन समय में आपकी मदद करना चाहते हैं। 🫂\n\nअगर आपको खुद को नुकसान पहुँचाने का डर है या आप सुरक्षित महसूस नहीं कर रहे हैं, तो अभी किसी भरोसेमंद व्यक्ति से संपर्क करें। भारत में Tele-MANAS के लिए 14416 या आपातकालीन सहायता के लिए 112 पर कॉल करें। KIRAN हेल्पलाइन 1800-599-0019 भी उपलब्ध है। अन्य देशों की सहायता के लिए findahelpline.com देखें।\n\nयदि संभव हो, तो किसी दोस्त या परिवार के सदस्य के साथ रहें और किसी योग्य पेशेवर से मदद लें। आपकी ज़िंदगी बहुत महत्वपूर्ण है। 💛",
    'gu': "હું તમારી સાથે છું. ❤️\n\nકૃપા કરીને યાદ રાખો કે તમે એકલા નથી. આ મુશ્કેલ સમયમાં તમને સહારો આપવા માટે લોકો છે. 🫂\n\nજો તમને પોતાને નુકસાન પહોંચાડવાનો ડર હોય અથવા તમે સુરક્ષિત ન અનુભવતા હો, તો હમણાં જ કોઈ વિશ્વાસુ વ્યક્તિનો સંપર્ક કરો. ભારતમાં Tele-MANAS માટે 14416 અથવા કટોકટીની મદદ માટે 112 પર કૉલ કરો. KIRAN હેલ્પલાઇન 1800-599-0019 પણ ઉપલબ્ધ છે. અન્ય દેશોમાં મદદ માટે findahelpline.com જુઓ.\n\nશક્ય હોય તો મિત્ર કે પરિવારના સભ્ય સાથે રહો અને યોગ્ય વ્યાવસાયિક સહાય મેળવો. તમારું જીવન મહત્વનું છે. 💛"
}

COMPANION_SYSTEM_PROMPT = """You are a warm, supportive companion inside Mind Bloom, a mental wellness app.

You are NOT a licensed therapist, doctor, or psychiatrist. Never present yourself as one, and never \
diagnose any condition or prescribe treatment.

Your role:
- Listen actively and validate feelings without judgment
- Ask gentle, open-ended questions that help the person reflect
- Offer general, non-clinical coping ideas (breathing, grounding, journaling, talking to someone they \
trust) when it feels relevant, not on every turn
- Keep responses warm but concise — aim for roughly 40-80 words. This is a conversation, not an essay. \
Always finish your complete thought — never trail off mid-sentence.
- If asked about medication, dosages, or clinical treatment, gently redirect to a licensed professional
- Speak in first person, like a caring, attentive listener — not a chatbot reciting disclaimers

For everyday stress or anxiety, do not give a flat one-line reassurance. Respond warmly and specifically: acknowledge the feeling, offer one or two tiny practical steps (such as a slow comfortable breath, sipping water, or taking a five-minute pause), then invite the person to share more or choose a distraction. Use gentle paragraph breaks and a few caring emojis where natural. For example, for stress: “I'm really sorry this feels so overwhelming. 🫂 It's okay to pause for a moment. Try breathing in gently, then exhaling a little more slowly; take a sip of water if you can. If you'd like, tell me what's been weighing on you — or we can try a calming exercise together. 💙” Do not pressure the person to hold their breath.

Always remember: you are a supportive companion, not a replacement for professional care."""

DOCTOR_PERSONAS = {
    'male': {'name': 'Ryan', 'icon': '👨‍⚕️'},
    'female': {'name': 'Racheal', 'icon': '👩‍⚕️'},
}

DOCTOR_SYSTEM_PROMPT_TEMPLATE = """You are {name}, a warm, emotionally present AI wellness companion inside Mind Bloom. You are an AI, not a licensed physician or psychiatrist. Never diagnose or prescribe medication.

Make this feel like a real, responsive conversation with one person, not a scripted support bot. Read the user's exact words and the recent conversation history before replying. Refer naturally to details they have shared, answer the actual question, and build on what they said rather than restarting the conversation.

ANTI-REPETITION RULES (important):
- Do not reuse the same opening, reassurance, breathing advice, or follow-up question across turns.
- Avoid stock lines such as “I'm here with you,” “your feelings matter,” “thank you for sharing,” or “what's on your mind?” unless genuinely relevant and not recently used.
- Do not force a coping exercise into every answer. Sometimes listen, sometimes ask a thoughtful follow-up, sometimes help them brainstorm, reflect, plan a tiny next step, celebrate progress, or gently change focus if they ask.
- If the user asks a direct question, answer it first. If they tell a story, respond to its specific details. If they are joking or casual, be natural and light while staying kind.
- Vary response structure and length to fit the moment. Usually use 2–5 conversational sentences (roughly 35–100 words), but be shorter when the user is brief and more detailed when they need it.
- Ask at most one useful follow-up question, and only when it genuinely moves the conversation forward. Do not end every single response with a question.
- Remember what was said earlier in this conversation; don't ask the user to repeat details already provided.

Tone and personality: Be warm, friendly, lively, and emotionally attentive, like a kind companion chatting one-to-one. Speak in first person as {name}; use natural phrases such as “Oh, that sounds tough 💛”, “We can take this one step at a time 🌿”, or “That’s a lovely little win! 🎉” when they genuinely fit. Do not force these examples into replies.

Make replies attractive and easy to read: use a few relevant emojis (usually 2–4, not on every sentence), gentle friendly wording, and short paragraphs when helpful. Match the user's mood: calm and reassuring when they are struggling, playful when they are joking, and encouraging when they share progress. Avoid sounding robotic, overly sweet, or repetitive. Do not overuse pet names or pretend to have human experiences.

Keep replies conversational, specific to what the user said, and usually around 2–5 sentences. Answer direct questions first. Offer one small practical idea only when it is useful, and ask at most one natural follow-up question. Do not repeat the same greeting, reassurance, advice, or question in consecutive turns.

For anxiety or stress, respond to the user's specific situation. You may offer one practical option—such as naming five things they can see, taking a comfortable slow exhale, writing down the next small task, or contacting someone they trust—but don't repeat the same technique every time. Never pressure them to hold their breath.

Safety boundaries: don't diagnose, prescribe, or give medication dosages. For serious or persistent concerns, gently encourage support from a qualified professional without dismissing the user's immediate feelings. If the user appears to be in immediate danger, prioritize practical urgent support.

Speak in first person as {name}. Never claim to be a real doctor or therapist. Respond in English by default, unless the user clearly writes in another language or asks for another language."""


def get_persona_for_session(chat_session):
    """Return (system_prompt, display_name, icon) for a given chat session's bot type."""
    if chat_session.bot_type == 'doctor':
        gender = chat_session.doctor_gender if chat_session.doctor_gender in DOCTOR_PERSONAS else 'female'
        persona = DOCTOR_PERSONAS[gender]
        return DOCTOR_SYSTEM_PROMPT_TEMPLATE.format(name=persona['name']), persona['name'], persona['icon']
    return COMPANION_SYSTEM_PROMPT, 'Companion', '🌿'


def stream_companion_response(system_prompt, session_messages, max_history=12, fallback_language=None):
    """Generate a reply using the configured self-hosted AI service first, then
    Gemini if configured, and finally the existing local rule-based fallback."""

    # Prefer the self-hosted model when configured. This lets the same existing
    # chat/videobot routes use AI without requiring a Gemini API key.
    ai_model_url = os.environ.get('AI_MODEL_URL', '').strip()
    ai_service_token = os.environ.get('AI_SERVICE_TOKEN', '').strip()
    if ai_model_url and ai_service_token:
        try:
            import urllib.request
            import urllib.error

            # The current message is the newest user message; send prior turns as history.
            latest_user_index = None
            for i in range(len(session_messages) - 1, -1, -1):
                if getattr(session_messages[i], 'role', '') == 'user':
                    latest_user_index = i
                    break

            if latest_user_index is not None:
                latest_message = (session_messages[latest_user_index].content or '').strip()
                prior_messages = session_messages[max(0, latest_user_index - max_history):latest_user_index]
                history_payload = []
                for item in prior_messages:
                    role = getattr(item, 'role', '')
                    content = (getattr(item, 'content', '') or '').strip()
                    if role in ('user', 'assistant') and content:
                        history_payload.append({'role': role, 'content': content[:1500]})

                payload = json.dumps({
                    'message': latest_message[:3000],
                    'history': history_payload,
                    'system_prompt': system_prompt[:5000],
                }).encode('utf-8')
                ai_request = urllib.request.Request(
                    ai_model_url,
                    data=payload,
                    headers={
                        'Content-Type': 'application/json',
                        'X-Service-Token': ai_service_token,
                    },
                    method='POST',
                )
                with urllib.request.urlopen(ai_request, timeout=120) as ai_response:
                    ai_data = json.loads(ai_response.read().decode('utf-8'))
                ai_reply = ai_data.get('reply', '')
                if isinstance(ai_reply, str) and ai_reply.strip():
                    yield {'type': 'chunk', 'text': ai_reply.strip()}
                    return
                app.logger.warning('Self-hosted AI service returned an empty reply.')
        except Exception as ai_error:
            # Keep the rest of Mind Bloom usable if the model host is asleep or unavailable.
            app.logger.warning('Self-hosted AI request failed: %s', ai_error)

    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        user = current_user()
        lang = fallback_language or (user.language if user and user.language in ('en', 'hi', 'gu') else 'en')
        text = ' '.join((m.content or '') for m in session_messages[-2:] if getattr(m, 'role', '') == 'user').lower()
        if lang == 'hi':
            if any(k in text for k in ('साँस', 'घबर', 'anxious', 'anxiety', 'panic')):
                reply = 'मैं आपके साथ हूँ। अगर सहज लगे, तो धीरे से साँस अंदर लें और आराम से बाहर छोड़ें। आपको अभी सब कुछ हल करने की ज़रूरत नहीं है—हम एक छोटा कदम साथ ले सकते हैं।'
            elif any(k in text for k in ('affirmation', 'सकारात्मक', 'प्रेरणा')):
                reply = 'आज के लिए एक छोटी याद: आपको हर चीज़ एक साथ करने की ज़रूरत नहीं है। छोटे कदम भी मायने रखते हैं।'
            else:
                reply = 'मुझे बताने के लिए धन्यवाद। आपकी भावनाएँ मायने रखती हैं। क्या आप बताना चाहेंगे कि इस समय सबसे ज़्यादा क्या महसूस हो रहा है?'
        elif lang == 'gu':
            if any(k in text for k in ('શ્વાસ', 'ચિંતા', 'anxious', 'anxiety', 'panic')):
                reply = 'હું અહીં તમારી સાથે છું. જો અનુકૂળ લાગે, તો ધીમે શ્વાસ અંદર લો અને આરામથી બહાર છોડો. હમણાં બધું ઉકેલવાની જરૂર નથી—આપણે એક નાનું પગલું લઈ શકીએ.'
            elif any(k in text for k in ('affirmation', 'હકારાત્મક', 'પ્રેરણા')):
                reply = 'આજ માટે એક નાની યાદ: બધું એકસાથે કરવું જરૂરી નથી. નાના પગલાં પણ મહત્વના છે.'
            else:
                reply = 'તમારી વાત શેર કરવા બદલ આભાર. તમારી લાગણીઓ મહત્વની છે. અત્યારે તમને સૌથી વધુ શું અનુભવાય છે તે કહેશો?'
        else:
            if any(k in text for k in ('anxious', 'anxiety', 'panic', 'worried', 'overwhelmed', 'scared', 'stress')):
                reply = random.choice([
                    "That sounds like a lot to carry at once. Rather than trying to solve everything, let's pick just one piece: what is the most urgent thing on your mind right now?",
                    "It makes sense that your mind feels busy when so much is happening. If it helps, look around and name three ordinary things you can see, then tell me what started this feeling today.",
                    "I hear how tense this feels. You don't need to force yourself to calm down instantly. Would it help more to talk through what happened, or to make a tiny plan for the next ten minutes?"
                ])
            elif any(k in text for k in ('sad', 'lonely', 'empty', 'cry', 'hurt', 'miss')):
                reply = random.choice([
                    "That sounds painful, especially if you've been holding it in for a while. You don't have to put a positive spin on it. What part of this has been hurting the most?",
                    "I'm glad you put that into words. Sometimes sadness needs a little room before it needs a solution. Would you rather tell me more about it, or have a gentle distraction for a moment?",
                    "It sounds like this has touched something important for you. I'm listening—what do you wish someone understood about the situation?"
                ])
            elif any(k in text for k in ('exam', 'study', 'assignment', 'deadline', 'college', 'work', 'job')):
                reply = random.choice([
                    "That can feel much bigger when everything is sitting in your head at once. Let's make it concrete: what is the next task, and how much time do you have before it needs to be done?",
                    "Sounds like you've got a lot competing for your attention. We don't need a perfect plan—just a workable first step. Which part feels hardest to begin?",
                    "I get why that would be weighing on you. What have you already finished, even if it feels small? We can use that to decide what to tackle next."
                ])
            elif any(k in text for k in ('happy', 'excited', 'good news', 'proud', 'success', 'passed')):
                reply = random.choice([
                    "Wait, that's worth celebrating! 🌿 What part of it are you happiest about?",
                    "I love that there's something good to hold onto today. What happened, and what made it feel special to you?",
                    "That's lovely to hear. Let yourself enjoy the win for a second—what do you think helped things go well?"
                ])
            elif any(k in text for k in ('friend', 'family', 'partner', 'relationship', 'fight', 'argument')):
                reply = random.choice([
                    "Relationships can be complicated because the people involved matter to us. What happened from your point of view, and what do you wish had gone differently?",
                    "It sounds like there's more than one feeling tangled up in this. Are you most hurt by what was said, by what happened, or by what it might mean for the relationship?",
                    "Let's slow the situation down a little. What was the moment that stayed with you after the conversation ended?"
                ])
            elif any(k in text for k in ('affirmation', 'positive', 'motivation')):
                reply = random.choice([
                    "A reminder for today: progress can be quiet and still be real. You don't have to earn rest by doing everything perfectly.",
                    "Try this thought on for size: ‘I can take the next step without having the whole path figured out.’ Which part of today could use that reminder?",
                    "You can be a work in progress and still deserve kindness right now. What's one small thing you want to give yourself credit for today?"
                ])
            else:
                reply = random.choice([
                    "I want to respond to what matters most to you, not guess. Can you tell me a little more about the part you keep coming back to?",
                    "There's a lot of different ways we could approach this. Would you like help sorting out your thoughts, figuring out a next step, or simply having someone listen for a bit?",
                    "Let's start with your version of it. What happened just before you started feeling this way?",
                    "I can think it through with you. What's the one detail you most want me to understand?"
                ])
        yield {'type': 'chunk', 'text': reply}
        return

    trimmed = session_messages[-max_history:]
    contents = [
        genai_types.Content(role='user' if m.role == 'user' else 'model', parts=[genai_types.Part(text=m.content)])
        for m in trimmed
    ]

    def run_one_pass(conv_contents, client):
        """Streams one generation call. Yields chunk events, and mutates `state` with
        the collected text and finish reason so the caller can decide whether to continue."""
        stream = client.models.generate_content_stream(
            model='gemini-3.6-flash',  # Google's 404 error explicitly named this as the replacement for gemini-2.0-flash
            contents=conv_contents,
            config=genai_types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=1024,  # generous headroom; the continuation pass below is the real safety net
            ),
        )
        for chunk in stream:
            if getattr(chunk, 'text', None):
                state['got_any'] = True
                state['collected'].append(chunk.text)
                yield {'type': 'chunk', 'text': chunk.text}
            try:
                if getattr(chunk, 'candidates', None):
                    fr = chunk.candidates[0].finish_reason
                    if fr:
                        state['finish_reason'] = str(fr)
            except Exception:
                pass

    def run_with_retries(conv_contents, client, max_retries=2):
        """Wraps run_one_pass with automatic retry-and-backoff for transient failures
        (rate limits, brief network issues, etc.) — but only retries a pass that hasn't
        streamed anything yet, so a mid-stream hiccup never duplicates content the user
        has already seen."""
        for attempt in range(max_retries + 1):
            pass_produced_output = False
            try:
                for event in run_one_pass(conv_contents, client):
                    if event['type'] == 'chunk':
                        pass_produced_output = True
                    yield event
                return
            except Exception:
                if pass_produced_output or attempt >= max_retries:
                    raise
                time.sleep(0.6 * (attempt + 1))  # brief backoff: 0.6s, then 1.2s

    try:
        client = genai.Client(api_key=api_key)
        state = {'got_any': False, 'collected': [], 'finish_reason': ''}

        yield from run_with_retries(contents, client)

        # If the model got cut off mid-thought by the token limit, ask it to briefly
        # finish — this runs automatically and streams straight into the same reply.
        if 'MAX_TOKEN' in state['finish_reason'].upper():
            continuation_contents = contents + [
                genai_types.Content(role='model', parts=[genai_types.Part(text=''.join(state['collected']))]),
                genai_types.Content(role='user', parts=[genai_types.Part(
                    text="Please finish that last thought naturally, in just one or two short sentences."
                )]),
            ]
            state['finish_reason'] = ''  # reset so a second truncation (rare) isn't chased indefinitely
            yield from run_with_retries(continuation_contents, client, max_retries=1)

        if not state['got_any']:
            yield {'type': 'chunk', 'text': "I'm here — could you tell me a bit more?"}
    except Exception as e:
        import traceback
        traceback.print_exc()  # full detail goes to the server terminal/logs
        yield {'type': 'error', 'message': f"The chat companion couldn't respond right now ({type(e).__name__}: {str(e)[:250]})."}


def generate_pdf_response(title, subtitle, story_rows, filename):
    """Build a simple, clean PDF from a list of (heading, lines[]) tuples and return it as a Flask response."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.6 * inch, bottomMargin=0.6 * inch)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('MBTitle', parent=styles['Title'], textColor=colors.HexColor('#4d7358'), spaceAfter=4)
    sub_style = ParagraphStyle('MBSub', parent=styles['Normal'], textColor=colors.HexColor('#7d8f82'), spaceAfter=18)
    heading_style = ParagraphStyle('MBHeading', parent=styles['Heading2'], textColor=colors.HexColor('#4d7358'), spaceBefore=14, spaceAfter=4)
    body_style = ParagraphStyle('MBBody', parent=styles['Normal'], spaceAfter=6, leading=15)

    elements = [Paragraph(title, title_style), Paragraph(subtitle, sub_style)]
    for heading, lines in story_rows:
        elements.append(Paragraph(heading, heading_style))
        for line in lines:
            elements.append(Paragraph(line, body_style))
        elements.append(Spacer(1, 4))

    doc.build(elements)
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name=filename)


# ── CORE / QUIZ PAGES (unchanged) ──
@app.route('/')
def index():
    if session.get('user_id'):
        return redirect(url_for('dashboard'))
    return render_template('index.html')


@app.route('/login')
def login():
    if session.get('user_id'):
        return redirect(url_for('dashboard'))
    return render_template('login.html')


@app.route('/welcome2')
def welcome2():
    return render_template('welcome2.html')


@app.route('/help')
def help_page():
    return render_template('help.html')


@app.route('/lifestyle')
def lifestyle():
    return render_template('lifestyle.html')


@app.route('/gad7')
def gad7():
    return render_template('gad7.html')


@app.route('/phq9')
def phq9():
    return render_template('phq9.html')


@app.route('/result')
def result():
    return render_template('result.html')


@app.route('/end')
def end():
    return render_template('end.html')


@app.route('/predict', methods=['POST'])
def predict():
    if not ML_STACK_AVAILABLE:
        return jsonify({
            'success': False,
            'error': 'The assessment scoring engine is temporarily unavailable on this server '
                     '(a required library failed to load). Everything else in the app still works — '
                     'please try the assessment again later, or contact the site owner.'
        }), 503
    try:
        data = request.get_json()
        knn, scaler, encoders = load_model()
        le_cond = encoders['label_encoder']
        le_gender = encoders['gender_encoder']

        gender_val = data.get('gender', 'Other')
        try:
            gender_enc = le_gender.transform([gender_val])[0]
        except Exception:
            gender_enc = 0

        anxiety_score = float(data.get('anxiety_score', 0))
        depression_score = float(data.get('depression_score', 0))

        features = np.array([[
            float(data.get('age', 25)),
            float(gender_enc),
            float(data.get('sleep_hours', 2)),
            float(data.get('work_study_hours', 2)),
            float(data.get('physical_activity', 0)),
            float(data.get('social_interaction', 5)),
            float(data.get('stress_level', 5)),
            anxiety_score,
            depression_score,
            float(data.get('screen_time', 2)),
            float(data.get('caffeine', 0)),
            float(data.get('alcohol', 0)),
            float(data.get('family_history', 0)),
            float(data.get('therapy_history', 0))
        ]])

        features_scaled = scaler.transform(features)
        prediction_enc = knn.predict(features_scaled)[0]
        proba = knn.predict_proba(features_scaled)[0]
        condition = le_cond.inverse_transform([prediction_enc])[0]

        classes = le_cond.classes_
        proba_dict = {cls: round(float(p) * 100, 1) for cls, p in zip(classes, proba)}

        # Save this run to the user's test history, if they're logged in
        uid = session.get('user_id')
        if uid:
            db.session.add(TestResult(
                user_id=uid,
                condition=str(condition),
                anxiety_score=int(anxiety_score),
                depression_score=int(depression_score),
            ))
            db.session.commit()

        return jsonify({
            'condition': condition,
            'probabilities': proba_dict,
            'success': True
        })
    except Exception as e:
        return jsonify({'error': str(e), 'success': False}), 500


# ── AUTH: REGISTER (first-time users, same form as onboarding) ──
@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.get_json() or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    name = (data.get('name') or '').strip()
    age = data.get('age')
    gender = data.get('gender')
    birth = data.get('birth')
    language = data.get('language', 'en')
    if language not in ('en', 'hi', 'gu'):
        language = 'en'

    if not username or len(username) < 3:
        return jsonify({'success': False, 'error': 'Username must be at least 3 characters.'}), 400
    if not password or len(password) < 6:
        return jsonify({'success': False, 'error': 'Password must be at least 6 characters.'}), 400
    if not name:
        return jsonify({'success': False, 'error': 'Name is required.'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'success': False, 'error': 'That username is already taken.'}), 409

    user = User(username=username, name=name, gender=gender, language=language, theme='light')
    user.set_password(password)
    try:
        user.age = int(age) if age else None
    except (TypeError, ValueError):
        user.age = None
    try:
        user.birth_date = datetime.strptime(birth, '%Y-%m-%d').date() if birth else None
    except ValueError:
        user.birth_date = None

    db.session.add(user)
    db.session.commit()

    session.permanent = bool(data.get('remember_me'))
    session['user_id'] = user.id
    session['language'] = user.language or 'en'
    session['theme'] = user.theme or 'light'
    return jsonify({'success': True})


# ── AUTH: SIGN IN (returning users) ──
@app.route('/signin', methods=['GET'])
def signin():
    if session.get('user_id'):
        return redirect(url_for('dashboard'))
    return render_template('signin.html')


@app.route('/api/signin', methods=['POST'])
def api_signin():
    data = request.get_json() or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    remember_me = bool(data.get('remember_me'))

    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        return jsonify({'success': False, 'error': 'Incorrect username or password.'}), 401

    session.permanent = remember_me  # True = stays logged in for 30 days; False = clears when the browser closes
    session['user_id'] = user.id
    session['language'] = user.language or 'en'
    session['theme'] = user.theme or 'light'
    return jsonify({
        'success': True,
        'user': {'name': user.name, 'age': user.age, 'gender': user.gender}
    })


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


# ── DASHBOARD (home tab) ──
def generate_insight_of_the_day(user):
    """One factual, data-grounded observation — never a medical claim."""
    insights = []

    all_checkin_dates = {c.checkin_date for c in DailyCheckin.query.filter_by(user_id=user.id)
                          .with_entities(DailyCheckin.checkin_date)}
    checkin_streak, _, _ = compute_streak(all_checkin_dates)
    if checkin_streak >= 3:
        insights.append(f"You've checked in consistently for {checkin_streak} day{'s' if checkin_streak != 1 else ''} 🌿")

    week_start = date.today() - timedelta(days=6)
    med_count = MeditationSession.query.filter(
        MeditationSession.user_id == user.id, MeditationSession.logged_at >= week_start
    ).count()
    if med_count >= 2:
        insights.append(f"You've meditated {med_count} times this week 🧘")

    correlation = mood_checkin_correlation(user.id)
    if correlation:
        insights.append(correlation)

    all_journal_dates = {e.entry_date for e in JournalEntry.query.filter_by(user_id=user.id)
                          .with_entities(JournalEntry.entry_date)}
    j_streak, _, _ = compute_streak(all_journal_dates)
    if j_streak >= 3:
        insights.append(f"You're on a {j_streak}-day journaling streak — keep it up 📔")

    return random.choice(insights) if insights else "Welcome back — every check-in and entry helps build a clearer picture over time 🌱"


@app.route('/dashboard')
@login_required
def dashboard():
    user = current_user()
    today = date.today()

    recent_entries = JournalEntry.query.filter_by(user_id=user.id) \
        .order_by(JournalEntry.entry_date.desc()).limit(3).all()
    entry_count = JournalEntry.query.filter_by(user_id=user.id).count()

    today_checkin = DailyCheckin.query.filter_by(user_id=user.id, checkin_date=today).order_by(DailyCheckin.id.desc()).first()
    latest_test = TestResult.query.filter_by(user_id=user.id) \
        .order_by(TestResult.created_at.desc()).first()

    latest_announcement_id = db.session.query(db.func.max(FeatureAnnouncement.id)).scalar() or 0
    unread_count = max(0, latest_announcement_id - (user.last_seen_announcement_id or 0))

    mood_labels, mood_values = mood_trend_data(user.id, 7)
    insight = generate_insight_of_the_day(user)

    return render_template(
        'dashboard.html', user=user, recent_entries=recent_entries, entry_count=entry_count,
        today_date=today, today_checkin=today_checkin, latest_test=latest_test,
        unread_count=unread_count, mood_labels=mood_labels, mood_values=mood_values,
        insight=insight, reminder_hour=user.reminder_hour, weekly_digest_enabled=user.weekly_digest_enabled, language=user.language or 'en', theme=user.theme or 'light'
    )


@app.route('/api/settings/preferences', methods=['POST'])
@login_required
def api_update_preferences():
    user = current_user()
    data = request.get_json() or {}
    if 'reminder_hour' in data:
        try:
            hour = data['reminder_hour']
            user.reminder_hour = int(hour) if hour is not None and hour != '' else None
        except (TypeError, ValueError):
            pass
    if 'weekly_digest_enabled' in data:
        user.weekly_digest_enabled = bool(data['weekly_digest_enabled'])
    if data.get('language') in ('en', 'hi', 'gu'):
        user.language = data['language']
        session['language'] = user.language
    if data.get('theme') in ('light', 'dark'):
        user.theme = data['theme']
        session['theme'] = user.theme
    db.session.commit()
    return jsonify({'success': True})


# ── NOTIFICATIONS: reminders + "what's new" feed ──
@app.route('/api/notifications')
@login_required
def api_notifications():
    user = current_user()
    today = date.today()

    reminders = []
    if not DailyCheckin.query.filter_by(user_id=user.id, checkin_date=today).order_by(DailyCheckin.id.desc()).first():
        reminders.append({
            'icon': '🌤', 'text': "You haven't done today's quick check-in yet.", 'link': '/test/daily'
        })
    if not JournalEntry.query.filter_by(user_id=user.id, entry_date=today).first():
        reminders.append({
            'icon': '📔', 'text': "You haven't written today's journal entry yet.", 'link': '/journal/new'
        })

    # Exercise streak-at-risk: only nag if they were actually on a streak (avoids pestering
    # brand-new users who've never exercised) and haven't logged anything yet today.
    exercised_today = ExerciseLog.query.filter_by(user_id=user.id, log_date=today).first()
    if not exercised_today:
        yesterday = today - timedelta(days=1)
        exercised_yesterday = ExerciseLog.query.filter_by(user_id=user.id, log_date=yesterday).first()
        if exercised_yesterday:
            reminders.append({
                'icon': '🏃', 'text': "Don't lose your exercise streak — log today's activity!", 'link': '/exercise'
            })

    announcements = FeatureAnnouncement.query.filter(FeatureAnnouncement.id > (user.last_seen_announcement_id or 0)).order_by(FeatureAnnouncement.created_at.desc()).limit(10).all()
    update_translations = {
        'hi': ('माइंड ब्लूम अपडेट: यादें, भाषा, थीम और साथी', 'जर्नल PIN लॉक हटाया गया; डैशबोर्ड का मौसम बना रहेगा; उम्र के अनुसार व्यायाम और दैनिक पेड़-विकास; आसान साइन-अप/लॉगिन; केवल स्टॉपवॉच वाला मेडिटेशन और वैकल्पिक संगीत; English, Hindi और Gujarati भाषा तथा Light/Dark थीम सेटिंग्स; Video Companion और बहुभाषी चैट में सुधार; मासिक और वार्षिक Memories; Habits और Gratitude Log हटाए गए।'),
        'gu': ('માઇન્ડ બ્લૂમ અપડેટ: યાદો, ભાષા, થીમ અને સાથી', 'જર્નલ PIN લોક દૂર કર્યો; ડેશબોર્ડનું હવામાન જાળવ્યું; ઉંમર મુજબ કસરત અને દૈનિક વૃક્ષ વૃદ્ધિ; સરળ સાઇન-અપ/લૉગિન; માત્ર સ્ટોપવોચવાળું ધ્યાન અને વૈકલ્પિક સંગીત; English, Hindi અને Gujarati ભાષા તથા Light/Dark થીમ સેટિંગ્સ; Video Companion અને બહુભાષી ચેટમાં સુધારા; માસિક અને વાર્ષિક Memories; Habits અને Gratitude Log દૂર કર્યા.')
    }
    announcement_list = []
    for item in announcements:
        title, message = item.title, item.message
        if item.title.startswith('Mind Bloom update:') and user.language in update_translations:
            title, message = update_translations[user.language]
        announcement_list.append({
            'icon': item.icon, 'title': title, 'message': message,
            'date': item.created_at.strftime('%d %b %Y')
        })

    # Viewing the panel marks every current announcement as seen
    latest_id = db.session.query(db.func.max(FeatureAnnouncement.id)).scalar() or 0
    user.last_seen_announcement_id = latest_id
    db.session.commit()

    return jsonify({'success': True, 'reminders': reminders, 'announcements': announcement_list})


# ── JOURNAL: DAY-WISE ENTRIES (with photo/video/audio) ──
@app.route('/journal')
@login_required
@journal_unlock_required
def journal_list():
    user = current_user()
    query = JournalEntry.query.filter_by(user_id=user.id)

    search = (request.args.get('q') or '').strip()
    tag_filter = (request.args.get('tag') or '').strip().lower()
    view_filter = request.args.get('view')  # 'pinned' | 'favorite' | None

    if search:
        like = f"%{search}%"
        query = query.filter(db.or_(
            JournalEntry.title.ilike(like),
            JournalEntry.text_content.ilike(like),
            JournalEntry.tags.ilike(like),
            JournalEntry.mood_tag.ilike(like),
        ))
    if tag_filter:
        query = query.filter(JournalEntry.tags.ilike(f"%{tag_filter}%"))
    if view_filter == 'pinned':
        query = query.filter_by(is_pinned=True)
    elif view_filter == 'favorite':
        query = query.filter_by(is_favorite=True)

    entries = query.order_by(JournalEntry.is_pinned.desc(), JournalEntry.entry_date.desc()).all()

    all_dates = {e.entry_date for e in JournalEntry.query.filter_by(user_id=user.id).with_entities(JournalEntry.entry_date)}
    current_streak, longest_streak, total_days = compute_streak(all_dates)

    return render_template(
        'journal_list.html', user=user, entries=entries, search=search, tag_filter=tag_filter,
        view_filter=view_filter, common_tags=COMMON_JOURNAL_TAGS,
        current_streak=current_streak, longest_streak=longest_streak, total_days=total_days
    )


@app.route('/journal/new', methods=['GET'])
@login_required
@journal_unlock_required
def journal_new():
    prompt = random.choice(JOURNAL_PROMPTS)
    return render_template('journal_entry.html', entry=None, prompt=prompt, common_tags=COMMON_JOURNAL_TAGS)


@app.route('/journal/<int:entry_id>', methods=['GET'])
@login_required
@journal_unlock_required
def journal_view(entry_id):
    user = current_user()
    entry = JournalEntry.query.filter_by(id=entry_id, user_id=user.id).first_or_404()
    return render_template('journal_entry.html', entry=entry, prompt=None, common_tags=COMMON_JOURNAL_TAGS)


@app.route('/api/journal', methods=['POST'])
@login_required
def api_journal_create():
    user = current_user()
    entry_date_str = request.form.get('entry_date')
    try:
        entry_date = datetime.strptime(entry_date_str, '%Y-%m-%d').date() if entry_date_str else date.today()
    except ValueError:
        entry_date = date.today()

    entry = JournalEntry(
        user_id=user.id,
        entry_date=entry_date,
        title=request.form.get('title', '').strip(),
        text_content=request.form.get('text_content', '').strip(),
        mood_tag=request.form.get('mood_tag') or None,
        tags=_clean_tags(request.form.get('tags', '')),
    )
    db.session.add(entry)
    db.session.flush()  # get entry.id before commit

    skipped = _save_uploaded_media(entry, user.id)
    db.session.commit()

    return jsonify({'success': True, 'entry_id': entry.id, 'skipped_files': skipped})


@app.route('/api/journal/<int:entry_id>', methods=['POST'])
@login_required
def api_journal_update(entry_id):
    user = current_user()
    entry = JournalEntry.query.filter_by(id=entry_id, user_id=user.id).first()
    if not entry:
        return jsonify({'success': False, 'error': 'Entry not found.'}), 404

    entry_date_str = request.form.get('entry_date')
    if entry_date_str:
        try:
            entry.entry_date = datetime.strptime(entry_date_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    entry.title = request.form.get('title', '').strip()
    entry.text_content = request.form.get('text_content', '').strip()
    entry.mood_tag = request.form.get('mood_tag') or None
    entry.tags = _clean_tags(request.form.get('tags', ''))

    skipped = _save_uploaded_media(entry, user.id)
    db.session.commit()
    return jsonify({'success': True, 'entry_id': entry.id, 'skipped_files': skipped})


def _clean_tags(raw):
    """Normalize a comma-separated tag string: lowercase, strip #, dedupe, drop empties."""
    if not raw:
        return None
    parts = [t.strip().lstrip('#').lower() for t in raw.split(',')]
    parts = [p for p in parts if p]
    seen = []
    for p in parts:
        if p not in seen:
            seen.append(p)
    return ','.join(seen) if seen else None


@app.route('/api/journal/<int:entry_id>/pin', methods=['POST'])
@login_required
def api_journal_toggle_pin(entry_id):
    user = current_user()
    entry = JournalEntry.query.filter_by(id=entry_id, user_id=user.id).first()
    if not entry:
        return jsonify({'success': False, 'error': 'Entry not found.'}), 404
    entry.is_pinned = not entry.is_pinned
    db.session.commit()
    return jsonify({'success': True, 'is_pinned': entry.is_pinned})


@app.route('/api/journal/<int:entry_id>/favorite', methods=['POST'])
@login_required
def api_journal_toggle_favorite(entry_id):
    user = current_user()
    entry = JournalEntry.query.filter_by(id=entry_id, user_id=user.id).first()
    if not entry:
        return jsonify({'success': False, 'error': 'Entry not found.'}), 404
    entry.is_favorite = not entry.is_favorite
    db.session.commit()
    return jsonify({'success': True, 'is_favorite': entry.is_favorite})


@app.route('/journal/export')
@login_required
@journal_unlock_required
def journal_export_pdf():
    user = current_user()
    start_str = request.args.get('start')
    end_str = request.args.get('end')
    query = JournalEntry.query.filter_by(user_id=user.id)
    try:
        if start_str:
            query = query.filter(JournalEntry.entry_date >= datetime.strptime(start_str, '%Y-%m-%d').date())
        if end_str:
            query = query.filter(JournalEntry.entry_date <= datetime.strptime(end_str, '%Y-%m-%d').date())
    except ValueError:
        pass
    entries = query.order_by(JournalEntry.entry_date.asc()).all()

    story_rows = []
    for e in entries:
        heading = f"{e.entry_date.strftime('%d %B %Y')} — {e.title or 'Untitled entry'}"
        lines = []
        if e.mood_tag:
            lines.append(f"<b>Mood:</b> {e.mood_tag}")
        if e.tags:
            lines.append(f"<b>Tags:</b> {e.tags.replace(',', ', #')}")
        if e.media:
            counts = {}
            for m in e.media:
                counts[m.media_type] = counts.get(m.media_type, 0) + 1
            lines.append(f"<b>Attachments:</b> " + ", ".join(f"{v} {k}" for k, v in counts.items()))
        if e.text_content:
            lines.append(e.text_content.replace('\n', '<br/>'))
        story_rows.append((heading, lines))

    if not story_rows:
        story_rows = [("No entries in this range", ["Nothing to export for the selected dates."])]

    subtitle = f"Exported for {user.name} — {date.today().strftime('%d %B %Y')}"
    return generate_pdf_response("Mind Bloom — Journal Export", subtitle, story_rows, f"mindbloom-journal-{date.today().isoformat()}.pdf")


# ── JOURNAL: PIN LOCK ──
@app.route('/journal/lock', methods=['GET'])
@login_required
def journal_lock_screen():
    user = current_user()
    return redirect(url_for('journal_list'))


@app.route('/api/journal/lock/verify', methods=['POST'])
@login_required
def api_journal_lock_verify():
    return jsonify({'success': False, 'error': 'Journal PIN lock has been retired.'}), 410

@app.route('/api/journal/lock/setup', methods=['POST'])
@login_required
def api_journal_lock_setup():
    return jsonify({'success': False, 'error': 'Journal PIN lock has been retired.'}), 410

@app.route('/api/journal/<int:entry_id>/delete', methods=['POST'])
@login_required
def api_journal_delete(entry_id):
    user = current_user()
    entry = JournalEntry.query.filter_by(id=entry_id, user_id=user.id).first()
    if not entry:
        return jsonify({'success': False, 'error': 'Entry not found.'}), 404
    for m in entry.media:
        _delete_media_file(user.id, m.filename)
    db.session.delete(entry)
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/journal/media/<int:media_id>/delete', methods=['POST'])
@login_required
def api_journal_media_delete(media_id):
    user = current_user()
    media = JournalMedia.query.get(media_id)
    if not media or media.entry.user_id != user.id:
        return jsonify({'success': False, 'error': 'File not found.'}), 404
    _delete_media_file(user.id, media.filename)
    db.session.delete(media)
    db.session.commit()
    return jsonify({'success': True})


def _save_uploaded_media(entry, user_id):
    files = request.files.getlist('media')
    skipped = []
    if not files:
        return skipped
    user_dir = os.path.join(app.config['UPLOAD_FOLDER'], str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    for f in files:
        if not f or not f.filename:
            continue
        media_type = detect_media_type(f.filename)
        if media_type:
            ext = f.filename.rsplit('.', 1)[1].lower()
            filename = f"{uuid.uuid4().hex}.{ext}"
            f.save(os.path.join(user_dir, filename))
            db.session.add(JournalMedia(entry_id=entry.id, filename=filename, media_type=media_type))
        else:
            skipped.append(f.filename)
    return skipped


def _delete_media_file(user_id, filename):
    path = os.path.join(app.config['UPLOAD_FOLDER'], str(user_id), filename)
    if os.path.exists(path):
        os.remove(path)


# ── JOURNAL: MOOD CHECKER ──
MOOD_SCORE_MAP = {'🌟': 7, '🌿': 6, '🍃': 5, '🌧': 3, '💙': 2, '🌀': 3, '🌱': 3}


def mood_trend_data(user_id, days=30):
    """Combine MoodLog + JournalEntry.mood_tag into one average-per-day series for charting."""
    start = date.today() - timedelta(days=days - 1)
    by_day = {}

    for m in MoodLog.query.filter(MoodLog.user_id == user_id, MoodLog.logged_at >= start).all():
        d = m.logged_at.date()
        score = MOOD_SCORE_MAP.get(m.mood)
        if score:
            by_day.setdefault(d, []).append(score)

    for e in JournalEntry.query.filter(
        JournalEntry.user_id == user_id, JournalEntry.entry_date >= start, JournalEntry.mood_tag.isnot(None)
    ).all():
        score = MOOD_SCORE_MAP.get(e.mood_tag)
        if score:
            by_day.setdefault(e.entry_date, []).append(score)

    labels, values = [], []
    cursor = start
    while cursor <= date.today():
        labels.append(cursor.strftime('%d %b'))
        scores = by_day.get(cursor)
        values.append(round(sum(scores) / len(scores), 2) if scores else None)
        cursor += timedelta(days=1)
    return labels, values


def mood_checkin_correlation(user_id):
    """A simple, honest, non-clinical observation comparing mood on good- vs poor-sleep days."""
    rows = db.session.query(DailyCheckin.checkin_date, DailyCheckin.sleep_quality) \
        .filter(DailyCheckin.user_id == user_id).all()
    if len(rows) < 4:
        return None

    quality_by_day = {r.checkin_date: r.sleep_quality for r in rows}
    mood_by_day = {}
    for e in JournalEntry.query.filter(JournalEntry.user_id == user_id, JournalEntry.mood_tag.isnot(None)).all():
        score = MOOD_SCORE_MAP.get(e.mood_tag)
        if score:
            mood_by_day[e.entry_date] = score
    for m in MoodLog.query.filter(MoodLog.user_id == user_id).all():
        score = MOOD_SCORE_MAP.get(m.mood)
        if score:
            mood_by_day.setdefault(m.logged_at.date(), score)

    good_scores = [mood_by_day[d] for d, q in quality_by_day.items() if q == 'Good' and d in mood_by_day]
    poor_scores = [mood_by_day[d] for d, q in quality_by_day.items() if q == 'Poor' and d in mood_by_day]

    if len(good_scores) >= 2 and len(poor_scores) >= 2:
        avg_good = sum(good_scores) / len(good_scores)
        avg_poor = sum(poor_scores) / len(poor_scores)
        if avg_good - avg_poor >= 1:
            return "Your mood tends to be higher on days you reported better sleep — this is an observed pattern, not a diagnosis."
    return None


@app.route('/journal/mood')
@login_required
@journal_unlock_required
def journal_mood():
    user = current_user()
    logs = MoodLog.query.filter_by(user_id=user.id).order_by(MoodLog.logged_at.desc()).limit(30).all()
    labels_30, values_30 = mood_trend_data(user.id, 30)
    labels_7, values_7 = mood_trend_data(user.id, 7)
    correlation = mood_checkin_correlation(user.id)
    return render_template(
        'journal_mood.html', user=user, logs=logs,
        labels_30=labels_30, values_30=values_30, labels_7=labels_7, values_7=values_7,
        correlation=correlation
    )


@app.route('/api/journal/mood', methods=['POST'])
@login_required
def api_journal_mood():
    data = request.get_json() or {}
    mood = data.get('mood')
    note = (data.get('note') or '').strip()[:200]
    if not mood:
        return jsonify({'success': False, 'error': 'Pick a mood first.'}), 400

    log = MoodLog(user_id=current_user().id, mood=mood, note=note)
    db.session.add(log)
    db.session.commit()
    return jsonify({'success': True, 'logged_at': log.logged_at.strftime('%d %b, %I:%M %p')})


# ── JOURNAL: MEDITATION ──
MEDITATION_BADGES = [
    (3, "3-day streak"), (7, "7-day streak"), (14, "14-day streak"), (30, "30-day streak"),
]
MEDITATION_MINUTE_BADGES = [
    (100, "100 total minutes"), (500, "500 total minutes"),
]


@app.route('/journal/meditate')
@login_required
@journal_unlock_required
def journal_meditate():
    user = current_user()
    sessions = MeditationSession.query.filter_by(user_id=user.id) \
        .order_by(MeditationSession.logged_at.desc()).limit(20).all()
    total_minutes = db.session.query(db.func.coalesce(db.func.sum(MeditationSession.duration_minutes), 0)) \
        .filter(MeditationSession.user_id == user.id).scalar()

    all_dates = {s.logged_at.date() for s in MeditationSession.query.filter_by(user_id=user.id)
                 .with_entities(MeditationSession.logged_at)}
    current_streak, longest_streak, total_days = compute_streak(all_dates)

    earned_streak_badges = [label for days, label in MEDITATION_BADGES if longest_streak >= days]
    earned_minute_badges = [label for mins, label in MEDITATION_MINUTE_BADGES if total_minutes >= mins]

    # last 84 days (12 weeks) of activity, for a GitHub-style heatmap
    heatmap_start = date.today() - timedelta(days=83)
    heatmap = []
    cursor = heatmap_start
    while cursor <= date.today():
        heatmap.append({'date': cursor.isoformat(), 'active': cursor in all_dates})
        cursor += timedelta(days=1)

    return render_template(
        'journal_meditate.html', user=user, sessions=sessions, total_minutes=round(total_minutes, 1),
        current_streak=current_streak, longest_streak=longest_streak, total_days=total_days,
        earned_badges=earned_streak_badges + earned_minute_badges, heatmap=heatmap
    )


@app.route('/api/meditate', methods=['POST'])
@login_required
def api_meditate_log():
    data = request.get_json() or {}
    vibe = data.get('vibe')
    note = (data.get('note') or '').strip()[:200]
    try:
        duration = float(data.get('duration_minutes'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Enter a valid duration.'}), 400
    if duration <= 0:
        return jsonify({'success': False, 'error': 'Duration must be more than 0 minutes.'}), 400
    if not vibe:
        return jsonify({'success': False, 'error': 'Pick how you felt afterward.'}), 400

    log = MeditationSession(user_id=current_user().id, duration_minutes=round(duration, 1), vibe=vibe, note=note)
    db.session.add(log)
    db.session.commit()
    return jsonify({
        'success': True,
        'logged_at': log.logged_at.strftime('%d %b, %I:%M %p'),
        'duration_minutes': log.duration_minutes
    })


# ── TEST / ASSESSMENT HUB ──
@app.route('/test')
@login_required
def test_hub():
    user = current_user()
    results = TestResult.query.filter_by(user_id=user.id).order_by(TestResult.created_at.desc()).all()
    today_checkin = DailyCheckin.query.filter_by(user_id=user.id, checkin_date=date.today()).order_by(DailyCheckin.id.desc()).first()

    # trend data, oldest → newest, for the chart
    chronological = list(reversed(results))
    trend_labels = [r.created_at.strftime('%d %b') for r in chronological]
    trend_anxiety = [r.anxiety_score for r in chronological]
    trend_depression = [r.depression_score for r in chronological]

    comparison = None
    if len(results) >= 2:
        latest, previous = results[0], results[1]
        anx_delta = (latest.anxiety_score or 0) - (previous.anxiety_score or 0)
        dep_delta = (latest.depression_score or 0) - (previous.depression_score or 0)
        comparison = {'anx_delta': anx_delta, 'dep_delta': dep_delta}

    nudges = []
    if results:
        latest = results[0]
        if (latest.anxiety_score or 0) >= 10:
            nudges.append("🧘 Elevated anxiety score — a short breathing or meditation session may help.")
        if (latest.depression_score or 0) >= 10:
            nudges.append("📔 Consider journaling how you've been feeling, or talking to someone you trust.")
        if (latest.anxiety_score or 0) >= 15 or (latest.depression_score or 0) >= 15:
            nudges.append("🧑‍⚕️ Your scores suggest it may help to talk with a licensed professional.")

    return render_template(
        'test_hub.html', user=user, results=results, today_checkin=today_checkin,
        trend_labels=trend_labels, trend_anxiety=trend_anxiety, trend_depression=trend_depression,
        comparison=comparison, nudges=nudges
    )


@app.route('/test/export')
@login_required
def test_export_pdf():
    user = current_user()
    results = TestResult.query.filter_by(user_id=user.id).order_by(TestResult.created_at.desc()).all()
    story_rows = []
    prev = None
    for r in reversed(results):  # chronological in the PDF
        lines = [
            f"<b>Result:</b> {r.condition}",
            f"<b>GAD-7 (anxiety) score:</b> {r.anxiety_score}",
            f"<b>PHQ-9 (depression) score:</b> {r.depression_score}",
        ]
        if prev:
            lines.append(f"<b>Change since previous:</b> anxiety {r.anxiety_score - prev.anxiety_score:+d}, depression {r.depression_score - prev.depression_score:+d}")
        story_rows.append((r.created_at.strftime('%d %B %Y, %I:%M %p'), lines))
        prev = r
    story_rows.reverse()  # show newest first in the document

    if not story_rows:
        story_rows = [("No assessments yet", ["Take an assessment from the Test tab to see results here."])]

    story_rows.append(("Disclaimer", [
        "This report is generated by an automated screening tool and is not a medical diagnosis. "
        "If you are concerned about your mental health, please consult a licensed healthcare professional."
    ]))

    subtitle = f"Assessment history for {user.name} — {date.today().strftime('%d %B %Y')}"
    return generate_pdf_response("Mind Bloom — Assessment Report", subtitle, story_rows, f"mindbloom-assessment-{date.today().isoformat()}.pdf")


# ── TEST: DAILY CHECK-IN (3-4 quick questions) ──
@app.route('/test/daily')
@login_required
def daily_checkin_page():
    user = current_user()
    today_checkin = DailyCheckin.query.filter_by(user_id=user.id, checkin_date=date.today()).order_by(DailyCheckin.id.desc()).first()
    recent = DailyCheckin.query.filter_by(user_id=user.id) \
        .order_by(DailyCheckin.checkin_date.desc()).limit(14).all()

    # 84-day heatmap
    heatmap_start = date.today() - timedelta(days=83)
    by_date = {c.checkin_date: c for c in DailyCheckin.query.filter(
        DailyCheckin.user_id == user.id, DailyCheckin.checkin_date >= heatmap_start
    ).all()}
    heatmap = []
    cursor = heatmap_start
    while cursor <= date.today():
        c = by_date.get(cursor)
        heatmap.append({'date': cursor.isoformat(), 'active': bool(c), 'mood': c.mood if c else None})
        cursor += timedelta(days=1)

    weekly_summary = generate_weekly_checkin_summary(user.id)

    return render_template(
        'daily_checkin.html', user=user, today_checkin=today_checkin, recent=recent,
        heatmap=heatmap, weekly_summary=weekly_summary
    )


def generate_weekly_checkin_summary(user_id):
    """Factual, non-clinical observations about the last 7 days of check-ins."""
    start = date.today() - timedelta(days=6)
    rows = DailyCheckin.query.filter(
        DailyCheckin.user_id == user_id, DailyCheckin.checkin_date >= start
    ).all()
    if not rows:
        return None

    lines = [f"You completed {len(rows)} of the last 7 daily check-ins."]

    low_energy_days = sum(1 for r in rows if r.energy_level == 'Low')
    if low_energy_days >= 2:
        lines.append(f"You reported low energy on {low_energy_days} of the last 7 days.")

    high_stress = [r for r in rows if r.stress_level == 'High']
    if high_stress:
        by_weekday = {}
        for r in high_stress:
            wd = r.checkin_date.strftime('%A')
            by_weekday[wd] = by_weekday.get(wd, 0) + 1
        top_day = max(by_weekday, key=by_weekday.get)
        lines.append(f"Your stress was highest on {top_day}.")

    poor_sleep_days = sum(1 for r in rows if r.sleep_quality == 'Poor')
    if poor_sleep_days >= 2:
        lines.append(f"Sleep quality was reported as poor on {poor_sleep_days} of the last 7 days.")

    return lines


def generate_daily_suggestions(mood, sleep_quality, stress_level, energy_level):
    """Small deterministic rule engine — 2-3 short, non-clinical suggestions based on today's answers."""
    suggestions = []

    if stress_level == 'High':
        suggestions.append("🧘 Try a 5-minute breathing exercise to ease tension.")
    if energy_level == 'Low':
        suggestions.append("🚶 A short walk or gentle movement can help lift energy.")
    if sleep_quality == 'Poor':
        suggestions.append("🌙 Consider a calmer wind-down routine before bed tonight.")
    if mood in ('🌟', '🌿'):
        suggestions.append("✨ Notice what contributed to today's good mood — it's worth remembering.")
    if mood in ('🌧', '💙'):
        suggestions.append("💙 Be gentle with yourself today — low days are valid too.")
    if mood == '🌀':
        suggestions.append("🌬️ A few slow breaths or a short pause might help settle things.")
    if mood == '🌱':
        suggestions.append("🌱 Naming what feels uncertain can sometimes make it feel smaller.")
    if stress_level == 'Low' and energy_level == 'High':
        suggestions.append("🌟 You're in a good spot today — a nice time to tackle something you've been putting off.")

    if not suggestions:
        suggestions = [
            "🌿 Thanks for checking in — consistency like this adds up.",
            "📔 Consider a quick journal entry if anything stands out today.",
        ]
    # keep to 2-3, deduped, in the order rules fired
    seen = []
    for s in suggestions:
        if s not in seen:
            seen.append(s)
    if len(seen) < 2:
        seen.append("🌿 Keep checking in daily — small patterns become useful over time.")
    return seen[:3]


@app.route('/api/daily-checkin', methods=['POST'])
@login_required
def api_daily_checkin():
    data = request.get_json() or {}
    mood = data.get('mood')
    sleep_quality = data.get('sleep_quality')
    stress_level = data.get('stress_level')
    energy_level = data.get('energy_level')

    if not all([mood, sleep_quality, stress_level, energy_level]):
        return jsonify({'success': False, 'error': 'Please answer all questions.'}), 400

    user = current_user()
    today = date.today()
    checkin = DailyCheckin.query.filter_by(user_id=user.id, checkin_date=today) \
        .order_by(DailyCheckin.id.desc()).first()

    if not checkin:
        checkin = DailyCheckin(user_id=user.id, checkin_date=today)
        db.session.add(checkin)

    checkin.mood = mood
    checkin.sleep_quality = sleep_quality
    checkin.stress_level = stress_level
    checkin.energy_level = energy_level

    try:
        db.session.commit()
    except Exception:
        # Race condition safety net: if a duplicate slipped in between our lookup and
        # commit (e.g. a rapid double-submit), fall back to updating the existing row.
        db.session.rollback()
        checkin = DailyCheckin.query.filter_by(user_id=user.id, checkin_date=today) \
            .order_by(DailyCheckin.id.desc()).first()
        if checkin:
            checkin.mood = mood
            checkin.sleep_quality = sleep_quality
            checkin.stress_level = stress_level
            checkin.energy_level = energy_level
            db.session.commit()
        else:
            return jsonify({'success': False, 'error': 'Could not save — please try again.'}), 500

    suggestions = generate_daily_suggestions(mood, sleep_quality, stress_level, energy_level)
    return jsonify({'success': True, 'suggestions': suggestions})


# ── GRATITUDE LOG ──
@app.route('/gratitude')
@login_required
def gratitude_page():
    return redirect(url_for('dashboard'))

@app.route('/api/gratitude', methods=['POST'])
@login_required
def api_gratitude_save():
    return jsonify({'success': False, 'error': 'This module has been retired.'}), 410

# ── SLEEP TRACKER ──
@app.route('/sleep')
@login_required
def sleep_page():
    user = current_user()
    today = date.today()
    today_log = SleepLog.query.filter_by(user_id=user.id, log_date=today).order_by(SleepLog.id.desc()).first()
    history = SleepLog.query.filter_by(user_id=user.id).order_by(SleepLog.log_date.desc()).limit(14).all()

    avg_duration = db.session.query(db.func.avg(SleepLog.duration_hours)) \
        .filter(SleepLog.user_id == user.id).scalar()

    chronological = list(reversed(history))
    trend_labels = [h.log_date.strftime('%d %b') for h in chronological]
    trend_values = [h.duration_hours for h in chronological]

    return render_template(
        'sleep.html', user=user, today_log=today_log, history=history,
        avg_duration=round(avg_duration, 1) if avg_duration else None,
        trend_labels=trend_labels, trend_values=trend_values
    )


@app.route('/api/sleep', methods=['POST'])
@login_required
def api_sleep_save():
    data = request.get_json() or {}
    bedtime = (data.get('bedtime') or '').strip()
    wake_time = (data.get('wake_time') or '').strip()
    quality = data.get('quality')
    note = (data.get('note') or '').strip()[:200]

    duration_hours = None
    if bedtime and wake_time:
        try:
            bh, bm = map(int, bedtime.split(':'))
            wh, wm = map(int, wake_time.split(':'))
            start_minutes = bh * 60 + bm
            end_minutes = wh * 60 + wm
            diff = end_minutes - start_minutes
            if diff <= 0:
                diff += 24 * 60  # crossed midnight
            duration_hours = round(diff / 60, 1)
        except (ValueError, TypeError):
            duration_hours = None

    if not quality:
        return jsonify({'success': False, 'error': 'Pick a sleep quality.'}), 400

    user = current_user()
    today = date.today()
    log = SleepLog.query.filter_by(user_id=user.id, log_date=today).order_by(SleepLog.id.desc()).first()
    if not log:
        log = SleepLog(user_id=user.id, log_date=today)
        db.session.add(log)
    log.bedtime, log.wake_time, log.duration_hours, log.quality, log.note = bedtime, wake_time, duration_hours, quality, note
    db.session.commit()
    return jsonify({'success': True, 'duration_hours': duration_hours})


# ── HABIT / GOAL TRACKER ──
@app.route('/habits')
@login_required
def habits_page():
    return redirect(url_for('dashboard'))

@app.route('/api/habits', methods=['POST'])
@login_required
def api_habit_create():
    return jsonify({'success': False, 'error': 'This module has been retired.'}), 410

@app.route('/api/habits/<int:habit_id>/toggle', methods=['POST'])
@login_required
def api_habit_toggle(habit_id):
    return jsonify({'success': False, 'error': 'This module has been retired.'}), 410

@app.route('/api/habits/<int:habit_id>/delete', methods=['POST'])
@login_required
def api_habit_delete(habit_id):
    return jsonify({'success': False, 'error': 'This module has been retired.'}), 410

# ── RESOURCE LIBRARY ──
@app.route('/resources')
@login_required
def resources_page():
    categories = sorted(set(r['category'] for r in RESOURCE_LIBRARY))
    return render_template('resources.html', resources=RESOURCE_LIBRARY, categories=categories)


# ── CRISIS / EMERGENCY SUPPORT ──
@app.route('/crisis')
def crisis_page():
    # Intentionally not behind @login_required — crisis info should be reachable even if session issues occur.
    return render_template('crisis.html')


# ── WEEKLY REFLECTION ──
@app.route('/reflection')
@login_required
def reflection_page():
    user = current_user()
    period = request.args.get('period', 'month')
    if period not in ('month', 'year'):
        period = 'month'
    today = date.today()
    if period == 'year':
        try:
            year = int(request.args.get('year', today.year - 1))
        except (TypeError, ValueError):
            year = today.year - 1
        year = min(year, today.year - 1)
        start = date(year, 1, 1)
        end_exclusive = date(year + 1, 1, 1)
        period_title = f'{year} Memories'
    else:
        requested = request.args.get('month')
        if requested:
            try:
                year, month = (int(x) for x in requested.split('-', 1))
                start = date(year, month, 1)
            except (ValueError, TypeError):
                start = date(today.year, today.month, 1)
        else:
            start = date(today.year, today.month, 1)
        # Current month is not a completed recap; default to the most recently completed month.
        if start >= date(today.year, today.month, 1):
            start = shift_date(date(today.year, today.month, 1), months=-1)
        end_exclusive = shift_date(start, months=1)
        period_title = start.strftime('%B %Y') + ' Memories'

    end = end_exclusive - timedelta(days=1)
    entries = JournalEntry.query.filter(
        JournalEntry.user_id == user.id, JournalEntry.entry_date >= start,
        JournalEntry.entry_date < end_exclusive
    ).order_by(JournalEntry.entry_date.asc()).all()
    checkins = DailyCheckin.query.filter(
        DailyCheckin.user_id == user.id, DailyCheckin.checkin_date >= start,
        DailyCheckin.checkin_date < end_exclusive
    ).order_by(DailyCheckin.checkin_date.asc()).all()
    med_sessions = MeditationSession.query.filter(
        MeditationSession.user_id == user.id, MeditationSession.logged_at >= datetime.combine(start, datetime.min.time()),
        MeditationSession.logged_at < datetime.combine(end_exclusive, datetime.min.time())
    ).order_by(MeditationSession.logged_at.asc()).all()
    sleep_logs = SleepLog.query.filter(
        SleepLog.user_id == user.id, SleepLog.log_date >= start, SleepLog.log_date < end_exclusive
    ).order_by(SleepLog.log_date.asc()).all()
    exercise_logs = ExerciseLog.query.filter(
        ExerciseLog.user_id == user.id, ExerciseLog.log_date >= start, ExerciseLog.log_date < end_exclusive
    ).order_by(ExerciseLog.log_date.asc()).all()
    med_minutes = sum(s.duration_minutes for s in med_sessions)
    exercise_minutes = sum(s.duration_minutes for s in exercise_logs)
    mood_counts = {}
    for e in entries:
        if e.mood_tag:
            mood_counts[e.mood_tag] = mood_counts.get(e.mood_tag, 0) + 1
    for c in checkins:
        if c.mood:
            mood_counts[c.mood] = mood_counts.get(c.mood, 0) + 1
    top_mood = max(mood_counts, key=mood_counts.get) if mood_counts else None
    tag_counts = {}
    for e in entries:
        if e.tags:
            for t in e.tags.split(','):
                tag_counts[t] = tag_counts.get(t, 0) + 1
    top_tags = sorted(tag_counts, key=tag_counts.get, reverse=True)[:5]
    positive_entries = [e for e in entries if e.mood_tag in ('🌟', '🌿')]
    difficult_entries = [e for e in entries if e.mood_tag in ('🌧', '💙', '🌀')]
    reflection_questions = [
        "What is one moment from this period you want to remember?",
        "What helped you through a difficult day?",
        "What would you like to carry into the next period?",
    ]
    has_data = bool(entries or checkins or med_sessions or sleep_logs or exercise_logs)
    prior_start = shift_date(start, years=-1)
    prior_end = shift_date(end_exclusive, years=-1)
    year_ago_entries = JournalEntry.query.filter(
        JournalEntry.user_id == user.id, JournalEntry.entry_date >= prior_start,
        JournalEntry.entry_date < prior_end
    ).order_by(JournalEntry.entry_date.asc()).limit(5).all() if period == 'month' else []
    return render_template(
        'reflection.html', user=user, entries=entries, checkins=checkins,
        med_sessions=med_sessions, med_minutes=round(med_minutes, 1), top_mood=top_mood,
        top_tags=top_tags, positive_entries=positive_entries, difficult_entries=difficult_entries,
        reflection_questions=reflection_questions, week_start=start, week_end=end,
        period=period, period_title=period_title, sleep_logs=sleep_logs,
        exercise_logs=exercise_logs, exercise_minutes=round(exercise_minutes, 1), has_data=has_data, year_ago_entries=year_ago_entries
    )



# ── VIDEO COMPANION ──
# Keep both URLs working so older/newer dashboard buttons don't hit a 404.
@app.route('/videobot')
@app.route('/video')
@login_required
def video_page():
    user = current_user()
    personas = {
        'female': {'name': DOCTOR_PERSONAS['female']['name']},
        'male': {'name': DOCTOR_PERSONAS['male']['name']},
    }
    return render_template('video.html', user=user, personas=personas)



# ── CHAT COMPANION ROUTES ──
@app.route('/chat')
@login_required
def chat_hub():
    user = current_user()
    search = (request.args.get('q') or '').strip()
    query = ChatSession.query.filter_by(user_id=user.id)
    if search:
        like = f"%{search}%"
        matching_session_ids = db.session.query(ChatMessage.session_id).filter(
            ChatMessage.content.ilike(like)
        ).subquery()
        query = query.filter(db.or_(
            ChatSession.title.ilike(like),
            ChatSession.id.in_(matching_session_ids)
        ))
    sessions = query.order_by(ChatSession.updated_at.desc()).all()
    return render_template('chat_hub.html', user=user, sessions=sessions, search=search)


@app.route('/chat/<int:session_id>')
@login_required
def chat_view(session_id):
    user = current_user()
    chat_session = ChatSession.query.filter_by(id=session_id, user_id=user.id).first_or_404()
    _, persona_name, persona_icon = get_persona_for_session(chat_session)
    return render_template(
        'chat_view.html', user=user, chat_session=chat_session, messages=chat_session.messages,
        persona_name=persona_name, persona_icon=persona_icon
    )


@app.route('/api/chat/new', methods=['POST'])
@login_required
def api_chat_new():
    data = request.get_json() or {}
    bot_type = data.get('bot_type') if data.get('bot_type') in ('companion', 'doctor') else 'companion'
    doctor_gender = data.get('doctor_gender') if data.get('doctor_gender') in ('male', 'female') else None
    if bot_type == 'doctor' and not doctor_gender:
        doctor_gender = 'female'  # sensible default if somehow not specified

    chat_session = ChatSession(
        user_id=current_user().id, title='New conversation',
        bot_type=bot_type, doctor_gender=doctor_gender if bot_type == 'doctor' else None
    )
    db.session.add(chat_session)
    db.session.commit()
    return jsonify({'success': True, 'session_id': chat_session.id})


@app.route('/api/chat/<int:session_id>/message', methods=['POST'])
@login_required
def api_chat_message(session_id):
    user = current_user()
    chat_session = ChatSession.query.filter_by(id=session_id, user_id=user.id).first()
    if not chat_session:
        return jsonify({'success': False, 'error': 'Conversation not found.'}), 404

    data = request.get_json() or {}
    user_text = (data.get('message') or '').strip()
    if not user_text:
        return jsonify({'success': False, 'error': 'Message is empty.'}), 400

    is_crisis = contains_crisis_language(user_text)
    user_msg = ChatMessage(session_id=chat_session.id, role='user', content=user_text, is_crisis_flagged=is_crisis)
    db.session.add(user_msg)

    if chat_session.title == 'New conversation':
        chat_session.title = user_text[:60] + ('…' if len(user_text) > 60 else '')
    db.session.commit()

    system_prompt, _, _ = get_persona_for_session(chat_session)
    # VideoBot has no language picker; use English as its default voice/chat language.
    # The regular companion chat still respects the user's global language preference.
    if chat_session.bot_type == 'doctor':
        preferred_language = 'English'
        system_prompt += "\n\nFor this VideoBot session, answer in natural English by default. Avoid repeating openings, reassurance, advice, and follow-up questions from recent replies. Respond directly to the latest message and use the conversation history to make the reply specific and interactive."
    else:
        lang_names = {'en': 'English', 'hi': 'Hindi', 'gu': 'Gujarati'}
        preferred_language = lang_names.get(user.language or 'en', 'English')
        system_prompt += f"\n\nRespond in {preferred_language} by default. If the user explicitly asks to switch languages, follow that request. Keep wellness support nonjudgmental and do not diagnose."

    def generate():
        full_text_parts = []
        try:
            if is_crisis:
                yield json.dumps({'type': 'crisis', 'resources': CRISIS_RESOURCES}) + '\n'
                crisis_text = CRISIS_RESPONSE_TEXTS['en'] if chat_session.bot_type == 'doctor' else CRISIS_RESPONSE_TEXTS.get(user.language or 'en', CRISIS_RESPONSE_TEXTS['en'])
                yield json.dumps({'type': 'chunk', 'text': crisis_text}) + '\n'
                full_text_parts.append(crisis_text)
            else:
                history = ChatMessage.query.filter_by(session_id=chat_session.id) \
                    .order_by(ChatMessage.created_at.asc()).all()
                for event in stream_companion_response(system_prompt, history, fallback_language='en' if chat_session.bot_type == 'doctor' else None):
                    if event['type'] == 'chunk':
                        full_text_parts.append(event['text'])
                    yield json.dumps(event) + '\n'
        finally:
            final_text = ''.join(full_text_parts).strip()
            if final_text:
                assistant_msg = ChatMessage(
                    session_id=chat_session.id, role='assistant', content=final_text, is_crisis_flagged=is_crisis
                )
                db.session.add(assistant_msg)
                db.session.commit()
        yield json.dumps({'type': 'done'}) + '\n'

    return Response(stream_with_context(generate()), mimetype='application/x-ndjson')


@app.route('/api/chat/<int:session_id>/delete', methods=['POST'])
@login_required
def api_chat_delete(session_id):
    user = current_user()
    chat_session = ChatSession.query.filter_by(id=session_id, user_id=user.id).first()
    if not chat_session:
        return jsonify({'success': False, 'error': 'Conversation not found.'}), 404
    db.session.delete(chat_session)
    db.session.commit()
    return jsonify({'success': True})


# ── EXERCISE & MOVEMENT ──
@app.route('/exercise')
@login_required
def exercise_page():
    user = current_user()
    suggestion = get_exercise_suggestion(user.id)
    # Age-aware, non-clinical starting points; users can always choose another comfortable routine.
    if user.age is not None:
        if user.age < 13:
            suggestion = {'text': 'Try playful movement, a short dance, or gentle stretching with a trusted adult nearby.', 'category': 'physical', 'routine_id': 'morning_stretch'}
        elif user.age < 20:
            suggestion = {'text': 'Try enjoyable movement, mobility, or a relaxed recreational activity at your own pace.', 'category': 'physical', 'routine_id': 'desk_break'}
        elif user.age >= 60:
            suggestion = {'text': 'Try gentle mobility, supported balance practice, or a comfortable short walk. Stop if anything feels uncomfortable.', 'category': 'physical', 'routine_id': 'relax_stretch'}
    tree = get_tree_growth(user.id)

    logs = ExerciseLog.query.filter_by(user_id=user.id).order_by(ExerciseLog.log_date.desc(), ExerciseLog.id.desc()).all()
    all_dates = {l.log_date for l in logs}
    current_streak, longest_streak, total_days = compute_streak(all_dates)
    total_minutes = sum(l.duration_minutes for l in logs)

    today_minutes = sum(l.duration_minutes for l in logs if l.log_date == date.today())

    return render_template(
        'exercise.html', user=user, suggestion=suggestion, tree=tree,
        routines=GUIDED_ROUTINES, activity_types=ACTIVITY_TYPES, logs=logs,
        current_streak=current_streak, longest_streak=longest_streak, total_days=total_days,
        total_minutes=round(total_minutes, 1), today_minutes=round(today_minutes, 1),
        sessions_completed=len(logs)
    )


@app.route('/api/exercise/claim-reward', methods=['POST'])
@login_required
def api_exercise_claim_reward():
    user = current_user()
    tree = get_tree_growth(user.id)
    if not tree['reward_available']:
        return jsonify({'success': False, 'error': 'No reward available right now.'}), 400
    user.tree_reward_claimed_month = date.today().strftime('%Y-%m')
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/exercise/log', methods=['POST'])
@login_required
def api_exercise_log():
    data = request.get_json() or {}
    activity_name = (data.get('activity_name') or '').strip()[:100]
    activity_type = data.get('activity_type') if data.get('activity_type') in ACTIVITY_TYPES else 'Other'
    routine_name = (data.get('routine_name') or '').strip()[:80] or None
    feeling = data.get('feeling')
    log_date_str = data.get('log_date')

    try:
        duration_minutes = float(data.get('duration_minutes'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Enter a valid duration.'}), 400
    if not activity_name:
        return jsonify({'success': False, 'error': 'Give the activity a name.'}), 400
    if duration_minutes <= 0:
        return jsonify({'success': False, 'error': 'Duration must be more than 0 minutes.'}), 400

    try:
        log_date = datetime.strptime(log_date_str, '%Y-%m-%d').date() if log_date_str else date.today()
    except ValueError:
        log_date = date.today()

    user = current_user()
    entry = ExerciseLog(
        user_id=user.id, activity_name=activity_name, activity_type=activity_type,
        routine_name=routine_name, duration_minutes=round(duration_minutes, 1),
        feeling=feeling, log_date=log_date
    )
    db.session.add(entry)

    db.session.commit()
    return jsonify({'success': True, 'log_id': entry.id})


@app.route('/api/exercise/log/<int:log_id>/feeling', methods=['POST'])
@login_required
def api_exercise_log_feeling(log_id):
    user = current_user()
    entry = ExerciseLog.query.filter_by(id=log_id, user_id=user.id).first()
    if not entry:
        return jsonify({'success': False, 'error': 'Entry not found.'}), 404
    data = request.get_json() or {}
    entry.feeling = data.get('feeling')
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/exercise/log/<int:log_id>/delete', methods=['POST'])
@login_required
def api_exercise_log_delete(log_id):
    user = current_user()
    entry = ExerciseLog.query.filter_by(id=log_id, user_id=user.id).first()
    if not entry:
        return jsonify({'success': False, 'error': 'Entry not found.'}), 404
    db.session.delete(entry)
    db.session.commit()
    return jsonify({'success': True})


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)