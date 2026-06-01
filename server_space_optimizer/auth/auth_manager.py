"""
Authentication manager for user login, signup, and session handling.

Uses SHA-256 password hashing and cookie-based sessions via itsdangerous.
Default password for new signups is 'welcome123'.
"""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from server_space_optimizer.models.database import User, hash_password

logger = logging.getLogger(__name__)

# Default password assigned to new user signups
DEFAULT_PASSWORD = "welcome123"


def authenticate_user(
    db: Session, username: str, password: str
) -> Optional[User]:
    """
    Authenticate a user by username and password.

    Returns the User object if credentials match, None otherwise.
    """
    pw_hash = hash_password(password)
    user = (
        db.query(User)
        .filter(
            User.username == username,
            User.password_hash == pw_hash,
            User.is_active == 1,
        )
        .first()
    )
    if user:
        # Update last login timestamp
        user.last_login = datetime.utcnow()
        db.commit()
        logger.info("User '%s' authenticated successfully", username)
    return user


def create_user(
    db: Session,
    username: str,
    email: str,
    password: Optional[str] = None,
    display_name: Optional[str] = None,
) -> Optional[User]:
    """
    Create a new user account.

    Uses DEFAULT_PASSWORD ('welcome123') if no password is provided.
    Returns the new User or None if username/email already exists.
    """
    # Check for existing username or email
    existing = (
        db.query(User)
        .filter((User.username == username) | (User.email == email))
        .first()
    )
    if existing:
        logger.warning(
            "Signup failed: username '%s' or email '%s' already exists",
            username,
            email,
        )
        return None

    pw = password or DEFAULT_PASSWORD
    user = User(
        username=username,
        email=email,
        password_hash=hash_password(pw),
        display_name=display_name or username,
        created_at=datetime.utcnow(),
    )
    db.add(user)
    db.commit()
    logger.info("New user created: '%s' (%s)", username, email)
    return user
