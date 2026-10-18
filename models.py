from datetime import datetime, date
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(40), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(60), nullable=False)
    age = db.Column(db.Integer)
    birth_date = db.Column(db.Date)
    gender = db.Column(db.String(20))  # 'Male' | 'Female' | 'Other'
    language = db.Column(db.String(5), default='en')
    theme = db.Column(db.String(10), default='light')
    last_seen_announcement_id = db.Column(db.Integer, default=0)
    journal_pin_hash = db.Column(db.String(255))  # optional PIN lock scoped to the Journal module only
    weekly_digest_enabled = db.Column(db.Boolean, default=True)
    reminder_hour = db.Column(db.Integer)  # preferred hour (0-23) for daily reminders, user-configurable
    tree_reward_claimed_month = db.Column(db.String(7))  # 'YYYY-MM' of the last exercise-tree reward claimed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    journal_entries = db.relationship(
        'JournalEntry', backref='user', lazy=True,
        cascade='all, delete-orphan', order_by='JournalEntry.entry_date.desc()'
    )
    mood_logs = db.relationship(
        'MoodLog', backref='user', lazy=True,
        cascade='all, delete-orphan', order_by='MoodLog.logged_at.desc()'
    )
    test_results = db.relationship(
        'TestResult', backref='user', lazy=True,
        cascade='all, delete-orphan', order_by='TestResult.created_at.desc()'
    )

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)

    def set_journal_pin(self, raw_pin):
        self.journal_pin_hash = generate_password_hash(raw_pin)

    def check_journal_pin(self, raw_pin):
        return bool(self.journal_pin_hash) and check_password_hash(self.journal_pin_hash, raw_pin)


class JournalEntry(db.Model):
    __tablename__ = 'journal_entries'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    entry_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    title = db.Column(db.String(120))
    text_content = db.Column(db.Text)
    mood_tag = db.Column(db.String(20))  # matches homepage mood set: amazing/good/okay/low/sad/stressed/anxious
    tags = db.Column(db.String(300))     # comma-separated, e.g. "work,family"
    is_pinned = db.Column(db.Boolean, default=False, index=True)
    is_favorite = db.Column(db.Boolean, default=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    media = db.relationship(
        'JournalMedia', backref='entry', lazy=True,
        cascade='all, delete-orphan'
    )


class JournalMedia(db.Model):
    """A photo, video, or audio clip attached to a journal entry."""
    __tablename__ = 'journal_media'

    id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(db.Integer, db.ForeignKey('journal_entries.id'), nullable=False, index=True)
    filename = db.Column(db.String(255), nullable=False)
    media_type = db.Column(db.String(10), nullable=False, default='photo')  # 'photo' | 'video' | 'audio'
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)


class MoodLog(db.Model):
    """Quick standalone mood check-ins, separate from full journal entries."""
    __tablename__ = 'mood_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    mood = db.Column(db.String(10), nullable=False)  # emoji, matches the homepage mood set
    note = db.Column(db.String(200))
    logged_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class TestResult(db.Model):
    """A saved outcome of a completed PHQ-9 / GAD-7 assessment run."""
    __tablename__ = 'test_results'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    condition = db.Column(db.String(80))
    anxiety_score = db.Column(db.Integer)
    depression_score = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class DailyCheckin(db.Model):
    """A short, 3-4 question daily mental-state check-in (separate from the full PHQ-9/GAD-7 test)."""
    __tablename__ = 'daily_checkins'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'checkin_date', name='uq_user_checkin_date'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    checkin_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    mood = db.Column(db.String(10))
    sleep_quality = db.Column(db.String(20))   # 'Poor' | 'Okay' | 'Good'
    stress_level = db.Column(db.String(20))    # 'Low' | 'Medium' | 'High'
    energy_level = db.Column(db.String(20))    # 'Low' | 'Medium' | 'High'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class MeditationSession(db.Model):
    """A logged meditation session: how long, and how the user felt afterward."""
    __tablename__ = 'meditation_sessions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    duration_minutes = db.Column(db.Float, nullable=False)
    vibe = db.Column(db.String(10))  # emoji reflecting how they felt after
    note = db.Column(db.String(200))
    logged_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class FeatureAnnouncement(db.Model):
    """A broadcast 'what's new' entry shown to every user via the notification bell."""
    __tablename__ = 'feature_announcements'

    id = db.Column(db.Integer, primary_key=True)
    icon = db.Column(db.String(10), default='🌿')
    title = db.Column(db.String(120), nullable=False)
    message = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class GratitudeEntry(db.Model):
    """Lightweight '3 good things today' log — separate from the full journal."""
    __tablename__ = 'gratitude_entries'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'entry_date', name='uq_user_gratitude_date'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    entry_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    item1 = db.Column(db.String(200))
    item2 = db.Column(db.String(200))
    item3 = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class SleepLog(db.Model):
    """Bedtime / wake time / quality tracking, one entry per night."""
    __tablename__ = 'sleep_logs'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'log_date', name='uq_user_sleep_date'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    log_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    bedtime = db.Column(db.String(5))     # 'HH:MM', 24h
    wake_time = db.Column(db.String(5))   # 'HH:MM', 24h
    duration_hours = db.Column(db.Float)
    quality = db.Column(db.String(20))    # 'Poor' | 'Okay' | 'Good'
    note = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Habit(db.Model):
    """A user-defined habit or goal to track daily."""
    __tablename__ = 'habits'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    icon = db.Column(db.String(10), default='✅')
    archived = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    logs = db.relationship('HabitLog', backref='habit', lazy=True, cascade='all, delete-orphan')


class HabitLog(db.Model):
    """A single day's completion record for a habit."""
    __tablename__ = 'habit_logs'
    __table_args__ = (
        db.UniqueConstraint('habit_id', 'log_date', name='uq_habit_log_date'),
    )

    id = db.Column(db.Integer, primary_key=True)
    habit_id = db.Column(db.Integer, db.ForeignKey('habits.id'), nullable=False, index=True)
    log_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ExerciseLog(db.Model):
    """A logged physical activity — either a manually logged activity or a completed guided routine."""
    __tablename__ = 'exercise_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    activity_name = db.Column(db.String(100), nullable=False)
    activity_type = db.Column(db.String(30), default='Other')  # Walking, Yoga, Stretching, Running, Gym Workout, Cycling, Dancing, Other
    routine_name = db.Column(db.String(80))  # set only when logged via a completed guided routine
    duration_minutes = db.Column(db.Float, nullable=False)
    feeling = db.Column(db.String(10))  # emoji, matches the app's existing mood set
    log_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class ChatSession(db.Model):
    """A single conversation thread with the chat companion."""
    __tablename__ = 'chat_sessions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    title = db.Column(db.String(120), default='New conversation')
    bot_type = db.Column(db.String(10), default='companion')  # 'companion' | 'doctor'
    doctor_gender = db.Column(db.String(10))  # 'male' | 'female' | None (only used when bot_type == 'doctor')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = db.relationship(
        'ChatMessage', backref='session', lazy=True,
        cascade='all, delete-orphan', order_by='ChatMessage.created_at.asc()'
    )


class ChatMessage(db.Model):
    """A single message within a chat session, from either the user or the companion."""
    __tablename__ = 'chat_messages'

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('chat_sessions.id'), nullable=False, index=True)
    role = db.Column(db.String(10), nullable=False)  # 'user' | 'assistant'
    content = db.Column(db.Text, nullable=False)
    is_crisis_flagged = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
