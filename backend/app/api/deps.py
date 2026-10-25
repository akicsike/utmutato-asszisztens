"""Közös függőségek: admin-jogosultság (X-Admin-Secret fejléc)."""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from ..config import get_settings


def require_admin(x_admin_secret: str = Header(default="")) -> None:
    secret = get_settings().admin_secret
    # bájtként hasonlítunk: ékezetes (nem ASCII) jelszónál a str-es compare_digest TypeError-t dobna
    if secret and not hmac.compare_digest(x_admin_secret.encode(), secret.encode()):
        raise HTTPException(status_code=401, detail="Hibás vagy hiányzó admin jelszó")
