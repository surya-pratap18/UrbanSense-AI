from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.database.session import get_db
from app.models import User

bearer = HTTPBearer(auto_error=False)


def get_current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                     db: Session = Depends(get_db)) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    payload = decode_token(creds.credentials)
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token", headers={"WWW-Authenticate": "Bearer"})
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or disabled")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access required")
    return user


import hmac  # noqa: E402

from fastapi import Header  # noqa: E402

from app.core.config import get_settings  # noqa: E402


def require_cron_or_admin(x_cron_secret: str | None = Header(default=None),
                          creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                          db: Session = Depends(get_db)) -> str:
    """Allows the scheduler (X-Cron-Secret header) or a logged-in admin. Returns 'cron' or 'admin'."""
    secret = get_settings().cron_secret
    if x_cron_secret and secret and hmac.compare_digest(x_cron_secret, secret):
        return "cron"
    user = get_current_user(creds, db)  # raises 401 if no/invalid token
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access required")
    return "admin"
