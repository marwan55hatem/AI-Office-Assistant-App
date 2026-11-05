"""Password hashing for the local (single-PC) database: salted scrypt from the standard
library, so no password is ever stored as typed. The online server uses Argon2id."""
import base64
import hashlib
import hmac
import os

_PREFIX = "scrypt"
_N, _R, _P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(str(password).encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return "$".join([_PREFIX, str(_N), str(_R), str(_P),
                     base64.b64encode(salt).decode(), base64.b64encode(digest).decode()])


def is_hashed(value) -> bool:
    return isinstance(value, str) and value.startswith(_PREFIX + "$") and value.count("$") == 5


def verify_password(stored, password) -> bool:
    if not is_hashed(stored) or password is None:
        return False
    _prefix, n, r, p, salt, digest = stored.split("$")
    candidate = hashlib.scrypt(str(password).encode("utf-8"), salt=base64.b64decode(salt),
                               n=int(n), r=int(r), p=int(p), dklen=32)
    return hmac.compare_digest(candidate, base64.b64decode(digest))
