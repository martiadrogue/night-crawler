"""Use cases for registration, login, and session tokens."""

import asyncio
import datetime
import uuid

import jwt
from night_crawler.core.config import get_settings
from night_crawler.domain.exceptions import ValidationException
from night_crawler.domain.model.entities import User
from night_crawler.domain.ports.auth_attempt_limiter import (
    AbstractAuthAttemptLimiter,
)
from night_crawler.domain.ports.repository_sets import (
    AbstractReadRepositories,
    AbstractWriteRepositories,
)
from night_crawler.schemas.auth import (
    SessionCreate,
    TokenOut,
    TokenPayloadOut,
    UserCreate,
    UserOut,
)
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from pwdlib.hashers.bcrypt import BcryptHasher
from pydantic import ValidationError

settings = get_settings()

password_hash = PasswordHash((BcryptHasher(),))

_DUMMY_PASSWORD_HASH = "$2b$12$xsVYDD5SYs8pK6d6cCEHo.sZhFL0IXQVB2Zs.TsyuaH3iWLXmIire"
"""A bcrypt hash of no known password, checked for unknown emails.

Login then costs the same bcrypt work whether or not the account exists,
so response timing can't reveal which emails are registered.
"""

ACCESS_TOKEN_TTL = datetime.timedelta(hours=2)
AUTH_ATTEMPT_WINDOW_SECONDS = 900
LOGIN_EMAIL_MAX_ATTEMPTS = 5
LOGIN_IP_MAX_ATTEMPTS = 20
REGISTER_IP_MAX_ATTEMPTS = 10


async def hash_password(password: str) -> str:
    """Hash a password with bcrypt in a worker thread."""
    return await asyncio.to_thread(password_hash.hash, password)


async def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check a password against its hash in a worker thread."""
    try:
        return await asyncio.to_thread(
            password_hash.verify, plain_password, hashed_password
        )
    except (UnknownHashError, ValueError):
        return False


async def _verify_login_password(user: User | None, password: str) -> bool:
    """Verify a password, using dummy bcrypt work for unknown emails."""
    hashed_password = user.hashed_password if user else _DUMMY_PASSWORD_HASH
    return await verify_password(password, hashed_password)


def create_access_token(email: str) -> str:
    """Return a signed access token for `email`, valid for 2 hours."""
    payload = {
        "sub": email,
        "exp": datetime.datetime.now(datetime.UTC) + ACCESS_TOKEN_TTL,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def verify_access_token(token: str) -> TokenPayloadOut:
    """Decode and validate an access token.

    Raises:
        ValidationException: the token is invalid or expired (401).
    """
    try:
        payload_dict = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        return TokenPayloadOut.model_validate(payload_dict)
    except (jwt.PyJWTError, ValidationError) as error:
        raise ValidationException("Invalid or expired session token", 401) from error


async def get_user_from_token(
    read_repositories: AbstractReadRepositories, token: str
) -> UserOut:
    """Return the user an access token belongs to.

    Raises:
        ValidationException: the token is invalid or expired, or its
            user no longer exists (401).
    """
    payload = verify_access_token(token)

    user = await read_repositories.users.get_by_email(payload.sub)
    if None is user:
        raise ValidationException("User no longer exists", 401)

    return UserOut.model_validate(user)


async def register_user(
    write_repositories: AbstractWriteRepositories,
    auth_attempt_limiter: AbstractAuthAttemptLimiter,
    credentials: UserCreate,
    ip_address: str,
) -> TokenOut:
    """Create a `user` account and return a token for it.

    Raises:
        ValidationException: the email is already taken (400), or the IP
            has made too many registration attempts (429).
        ExternalServiceException: the attempt counter is unavailable.
    """
    ip_key = f"register:ip:{ip_address}"
    if await auth_attempt_limiter.is_limited(ip_key, REGISTER_IP_MAX_ATTEMPTS):
        raise ValidationException("Too many registration attempts. Try later.", 429)
    await auth_attempt_limiter.record_attempt(ip_key, AUTH_ATTEMPT_WINDOW_SECONDS)

    existing_user = await write_repositories.users.get_by_email(credentials.email)
    if existing_user:
        raise ValidationException("Email already taken", 400)

    new_user = User(
        id=str(uuid.uuid4()),
        email=credentials.email,
        hashed_password=await hash_password(credentials.password),
        created_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
    )
    saved_user = await write_repositories.users.save(new_user)
    await write_repositories.commit()

    return TokenOut(
        access_token=create_access_token(saved_user.email), role=saved_user.role
    )


async def authenticate_user(
    read_repositories: AbstractReadRepositories,
    auth_attempt_limiter: AbstractAuthAttemptLimiter,
    credentials: SessionCreate,
    ip_address: str,
) -> TokenOut:
    """Return a token for valid credentials.

    Unknown emails and wrong passwords fail identically and take the
    same time.

    Raises:
        ValidationException: the credentials are wrong (401), or a login
            attempt threshold was reached for email or IP (429).
        ExternalServiceException: the attempt counter is unavailable.
    """
    email_key = f"login:email:{credentials.email.casefold()}"
    ip_key = f"login:ip:{ip_address}"
    is_email_limited = await auth_attempt_limiter.is_limited(
        email_key, LOGIN_EMAIL_MAX_ATTEMPTS
    )
    is_ip_limited = await auth_attempt_limiter.is_limited(ip_key, LOGIN_IP_MAX_ATTEMPTS)
    if is_email_limited:
        raise ValidationException(
            "Too many failed login attempts. Try again later.", 429
        )
    if is_ip_limited:
        raise ValidationException(
            "Too many failed login attempts. Try again later.", 429
        )

    user = await read_repositories.users.get_by_email(credentials.email)
    is_password_ok = await _verify_login_password(user, credentials.password)

    if not user or not is_password_ok:
        await auth_attempt_limiter.record_attempt(
            email_key, AUTH_ATTEMPT_WINDOW_SECONDS
        )
        await auth_attempt_limiter.record_attempt(ip_key, AUTH_ATTEMPT_WINDOW_SECONDS)
        raise ValidationException("Incorrect email or password", 401)

    await auth_attempt_limiter.clear(email_key)
    return TokenOut(access_token=create_access_token(user.email), role=user.role)
