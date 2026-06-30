from sqlalchemy import Column, String, Text, Boolean, Index, LargeBinary, DateTime
from db import Base
from sqlalchemy.sql import func


class User(Base):
    __tablename__ = "users"
    g_id = Column(String(255), primary_key=True, index=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    token = Column(LargeBinary, nullable=False)  # Encrypted token
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_active = Column(Boolean, default=True)
    last_accessed = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index('idx_expires_at', 'expires_at'),
    )


class SessionToken(Base):
    __tablename__ = "sessions"

    session_id = Column(String(255), primary_key=True, index=True)
    g_id = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_active = Column(Boolean, default=True)

    __table_args__ = (
        Index('idx_session_google_id', 'g_id'),
        Index('idx_session_expires', 'expires_at'),
    )
