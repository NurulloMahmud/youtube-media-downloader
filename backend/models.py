import secrets
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Column, DateTime, Integer, String
from sqlalchemy.orm import Session

from .database import Base


class User(Base):
    __tablename__ = "users"

    id              = Column(Integer, primary_key=True)
    ig_user_id      = Column(String(100), unique=True, nullable=False, index=True)
    ig_username     = Column(String(150))
    token           = Column(String(32), unique=True, nullable=False, index=True)
    telegram_chat_id = Column(BigInteger, nullable=True)
    created_at      = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    linked_at       = Column(DateTime(timezone=True), nullable=True)


# ── DB helpers ────────────────────────────────────────────────────────

def generate_token() -> str:
    """12-char lowercase hex token, e.g. a3f7b2c1d4e5"""
    return secrets.token_hex(6)


def get_user_by_ig_id(db: Session, ig_user_id: str) -> User | None:
    return db.query(User).filter(User.ig_user_id == ig_user_id).first()


def get_user_by_token(db: Session, token: str) -> User | None:
    return db.query(User).filter(User.token == token).first()


def create_user(db: Session, ig_user_id: str, ig_username: str | None) -> User:
    user = User(ig_user_id=ig_user_id, ig_username=ig_username, token=generate_token())
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def link_telegram(db: Session, token: str, telegram_chat_id: int) -> User | None:
    user = get_user_by_token(db, token)
    if not user:
        return None
    user.telegram_chat_id = telegram_chat_id
    user.linked_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return user


def get_user_by_telegram_id(db: Session, telegram_chat_id: int) -> User | None:
    return db.query(User).filter(User.telegram_chat_id == telegram_chat_id).first()
