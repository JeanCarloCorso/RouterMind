import base64
import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from app.services.database import Database, User


class AuthService:
    def __init__(self, database: Database, secret_key: str):
        self.database = database
        self.secret = secret_key.encode("utf-8")
        encryption_key = hmac.new(self.secret, b"routemind:encryption:v1", hashlib.sha256).digest()
        self.cipher = Fernet(base64.urlsafe_b64encode(encryption_key))
        self.passwords = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)

    @staticmethod
    def normalize_email(email: str) -> str:
        return email.strip().casefold()

    def register(self, email: str, password: str) -> User:
        normalized = self.normalize_email(email)
        if "@" not in normalized or len(normalized) > 254:
            raise ValueError("Informe um e-mail válido.")
        if len(password) < 12 or len(password) > 256:
            raise ValueError("A senha deve ter entre 12 e 256 caracteres.")
        return self.database.create_user(normalized, self.passwords.hash(password))

    def authenticate_password(self, email: str, password: str) -> User | None:
        user = self.database.get_user_by_email(self.normalize_email(email))
        if not user:
            self.passwords.hash(password or "invalid-password")
            return None
        try:
            if not self.passwords.verify(user.password_hash, password):
                return None
        except (VerifyMismatchError, InvalidHashError):
            return None
        return user

    def encrypt_openrouter_key(self, key: str) -> str:
        value = key.strip()
        if len(value) < 16:
            raise ValueError("A chave OpenRouter parece inválida.")
        return self.cipher.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt_openrouter_key(self, user: User) -> str | None:
        if not user.openrouter_key_encrypted:
            return None
        try:
            return self.cipher.decrypt(user.openrouter_key_encrypted.encode("ascii")).decode("utf-8")
        except InvalidToken:
            return None

    def _api_hash(self, token: str) -> str:
        return hmac.new(self.secret, b"routemind:api:v1:" + token.encode("utf-8"), hashlib.sha256).hexdigest()

    def issue_api_key(self, user_id: int, label: str) -> str:
        clean_label = label.strip()[:80] or "Chave principal"
        token = "rm_live_" + secrets.token_urlsafe(32)
        self.database.create_api_key(user_id, clean_label, token[:16], self._api_hash(token))
        return token

    def authenticate_api_key(self, token: str) -> User | None:
        if not token.startswith("rm_live_") or len(token) < 32:
            return None
        return self.database.find_user_by_api_hash(self._api_hash(token))
