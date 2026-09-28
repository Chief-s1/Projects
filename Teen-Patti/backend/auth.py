import hashlib, hmac, secrets
from config import settings

def issue_token(): return secrets.token_urlsafe(32)
def hash_token(token): return hmac.new(settings.secret_key.encode(), token.encode(), hashlib.sha256).hexdigest()
def verify_token(token, expected_hash): return hmac.compare_digest(hash_token(token), expected_hash)
