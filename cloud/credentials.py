"""Keep the refresh token in Windows Credential Manager (never in a file).

The access token lives only in memory. On a system without Credential Manager the
token is simply not remembered, so the user signs in again next time.
"""
import logging

logger = logging.getLogger(__name__)

TARGET_PREFIX = "OfficeAssistant/refresh-token/"


class CredentialStore:
    """Read, write and delete one secret per server address."""

    def __init__(self, server: str):
        self.target = TARGET_PREFIX + server.rstrip("/")

    def load(self):
        try:
            import win32cred
            credential = win32cred.CredRead(self.target, win32cred.CRED_TYPE_GENERIC)
            blob = credential["CredentialBlob"]
            return blob.decode("utf-16-le") if isinstance(blob, bytes) else blob
        except ImportError:
            return None
        except Exception:                   # not found, or the store is unavailable
            return None

    def save(self, secret: str) -> bool:
        try:
            import win32cred
            win32cred.CredWrite({
                "Type": win32cred.CRED_TYPE_GENERIC,
                "TargetName": self.target,
                "UserName": "refresh-token",
                "CredentialBlob": secret,
                "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
                "Comment": "Office Assistant sign-in (delete to sign out)",
            }, 0)
            return True
        except Exception:
            logger.warning("Could not save the sign-in to Windows Credential Manager", exc_info=False)
            return False

    def delete(self) -> None:
        try:
            import win32cred
            win32cred.CredDelete(self.target, win32cred.CRED_TYPE_GENERIC, 0)
        except Exception:
            pass


class MemoryCredentialStore:
    """Used by tests and when nothing may be remembered."""

    def __init__(self, secret=None):
        self.secret = secret

    def load(self):
        return self.secret

    def save(self, secret):
        self.secret = secret
        return True

    def delete(self):
        self.secret = None
