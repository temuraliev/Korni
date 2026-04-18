from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeSerializer

from korni_bot.config import get_settings

_SESSION_COOKIE = "korni_admin_session"
_SESSION_SALT = "admin-auth"


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(get_settings().session_secret, salt=_SESSION_SALT)


def sign_session(login: str) -> str:
    return _serializer().dumps({"login": login})


def verify_session(token: str) -> str | None:
    try:
        data = _serializer().loads(token)
        return data.get("login") if isinstance(data, dict) else None
    except BadSignature:
        return None


def set_session_cookie(response, login: str) -> None:
    response.set_cookie(
        _SESSION_COOKIE,
        sign_session(login),
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 14,
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(_SESSION_COOKIE)


def require_admin(request: Request) -> str:
    token = request.cookies.get(_SESSION_COOKIE)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/admin/login"},
        )
    login = verify_session(token)
    if not login:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/admin/login"},
        )
    return login


AdminDep = Depends(require_admin)
