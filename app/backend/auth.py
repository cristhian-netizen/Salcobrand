import base64
import hashlib
import hmac
import os
import secrets
import time

import db

SESSION_COOKIE = "pf_session"
SESSION_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 días
PBKDF2_ITERATIONS = 200_000

_SECRET_PATH = db.DATA_DIR / "secret.key"


def _load_or_create_secret() -> bytes:
    env_secret = os.environ.get("SESSION_SECRET")
    if env_secret:
        return env_secret.encode("utf-8")
    if _SECRET_PATH.exists():
        return _SECRET_PATH.read_bytes()
    secret = secrets.token_bytes(32)
    _SECRET_PATH.write_bytes(secret)
    return secret


_SECRET = _load_or_create_secret()


PASSWORD_HELP = 'La contraseña debe tener entre 8 y 512 caracteres, al menos una mayúscula y un número.'


def validate_password(password):
    if (not isinstance(password,str) or not 8 <= len(password) <= 512
            or not any(char.isupper() for char in password) or not any(char in '0123456789' for char in password)):
        from infrastructure import ManagementError
        raise ManagementError(PASSWORD_HELP)


def login_user(identifier):
    identifier=identifier.strip().lower()
    with db.get_conn() as conn:
        rows=conn.execute('SELECT username FROM users WHERE LOWER(username)=? UNION '
            'SELECT u.username FROM users u JOIN management_people p ON LOWER(p.username)=LOWER(u.username) WHERE LOWER(p.email)=?',
            (identifier,identifier)).fetchall()
    # Old ambiguous aliases fail closed, without choosing an account arbitrarily.
    return db.get_user(rows[0]['username']) if len(rows)==1 else None


def validate_login_identity(conn, username, email='', exclude_username=None):
    from infrastructure import ManagementError
    identifiers={value.strip().lower() for value in (username,email) if value}
    exclude=(exclude_username or '').lower()
    for row in conn.execute('SELECT username FROM users').fetchall():
        if row['username'].lower()!=exclude and row['username'].lower() in identifiers:
            raise ManagementError('Ya existe una cuenta con ese usuario o email.',409)
    for row in conn.execute('SELECT username,email FROM management_people').fetchall():
        if row['username'].lower()!=exclude and identifiers.intersection({row['username'].lower(),row['email'].lower()}):
            raise ManagementError('Ya existe una persona con ese usuario o email.',409)


def hash_password(password: str, salt: str = None) -> tuple:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS)
    return base64.b64encode(digest).decode("ascii"), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    candidate, _ = hash_password(password, salt)
    return hmac.compare_digest(candidate, password_hash)


def _sign(payload: str) -> str:
    return hmac.new(_SECRET, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _account_fingerprint(user):
    raw = f"{user.get('auth_version', 0)}:{user['salt']}:{user['password_hash']}"
    return 'v1-' + hashlib.sha256(raw.encode()).hexdigest()


def create_session_token(username: str) -> str:
    expires_at = int(time.time()) + SESSION_TTL_SECONDS
    user = db.get_user(username)
    fingerprint = _account_fingerprint(user) if user else 'v1-missing'
    payload = f"{username}:{expires_at}:{fingerprint}"
    signature = _sign(payload)
    return base64.urlsafe_b64encode(f"{payload}:{signature}".encode()).decode('ascii')


def verify_session_token(token: str):
    try:
        raw = base64.urlsafe_b64decode(token.encode('ascii')).decode('utf-8')
        payload, signature = raw.rsplit(':', 1)
        if not hmac.compare_digest(_sign(payload), signature):
            return None
        pieces = payload.rsplit(':', 2)
        modern = len(pieces) == 3 and pieces[-1].startswith('v1-')
        if modern:
            username, expires_at, fingerprint = pieces
        else:
            username, expires_at = payload.rsplit(':', 1)
        if int(expires_at) < int(time.time()):
            return None
        user = db.get_user(username)
        if not user:
            return None
        if modern:
            if not hmac.compare_digest(fingerprint, _account_fingerprint(user)):
                return None
        elif user.get('auth_version', 0) != 0:
            return None
        return username
    except (ValueError, TypeError, UnicodeError, KeyError):
        return None
