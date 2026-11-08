"""
Minimal login: a signed token that says which user you are.
The demo button logs judges in as a demo freelancer without signing up.
(Production would use passwords or OAuth plus expiring tokens.)
"""
import hashlib
import hmac

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from . import config
from .database import get_db
from .models import User

bearer = HTTPBearer(auto_error=False)

DEMO_EMAIL = "demo@getpaid.app"
DEMO_NAME = "Maria Lopez Design"


def _sign(value: str) -> str:
    return hmac.new(config.SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()


def create_token(user_id: int) -> str:
    return f"{user_id}.{_sign(str(user_id))}"


def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                     db: Session = Depends(get_db)) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Please log in.")
    try:
        user_id, signature = credentials.credentials.split(".", 1)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid login token.")
    if not hmac.compare_digest(signature, _sign(user_id)):
        raise HTTPException(status_code=401, detail="Invalid login token.")
    user = db.get(User, int(user_id))
    if user is None:
        raise HTTPException(status_code=401, detail="User not found.")
    return user


def get_or_create_demo_user(db: Session) -> User:
    user = db.query(User).filter(User.email == DEMO_EMAIL).first()
    if user is None:
        user = User(email=DEMO_EMAIL, name=DEMO_NAME)
        db.add(user)
        db.commit()
    return user
