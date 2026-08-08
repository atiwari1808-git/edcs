from django.conf import settings
from django.db import models


def _fernet():
    from cryptography.fernet import Fernet
    key = settings.TOKEN_ENCRYPTION_KEY
    return Fernet(key.encode()) if key else None


class GraphToken(models.Model):
    """One MSAL token cache per user. Encrypted at rest when
    TOKEN_ENCRYPTION_KEY is set (mandatory in production)."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="graph_token")
    cache_blob = models.TextField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    def store(self, serialized: str):
        f = _fernet()
        self.cache_blob = f.encrypt(serialized.encode()).decode() if f else serialized
        self.save()

    def load(self) -> str:
        if not self.cache_blob:
            return ""
        f = _fernet()
        try:
            return f.decrypt(self.cache_blob.encode()).decode() if f else self.cache_blob
        except Exception:
            return ""
