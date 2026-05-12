import hashlib
import hmac
import re
import unicodedata
from collections.abc import Iterator

from django.conf import settings

TRIGRAM_HMAC_PREFIX = b"sysreptor|blind_trigram|v1|"
TOKEN_LEN = 16  # bytes (truncate HMAC-SHA256)
WHITESPACE_RE = re.compile(r"\s+")


def get_blind_trigram_key() -> bytes:
    """
    Key used to blind-index plaintext trigrams.

    Requirements (per project spec):
    - Use the key bytes of settings.ENCRYPTION_KEYS[settings.DEFAULT_ENCRYPTION_KEY_ID]
    - If encryption is disabled or key missing: fall back to empty key (b"")
    """
    key_id = settings.DEFAULT_ENCRYPTION_KEY_ID
    if not key_id:
        return b""
    key_obj = settings.ENCRYPTION_KEYS.get(key_id)
    return key_obj.key if key_obj else b""


def normalize_text(value: str) -> str:
    if value is None:
        return ""
    # Accent-insensitive: compatibility-decompose, strip combining marks, then re-compose.
    value = unicodedata.normalize("NFKD", str(value))
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = unicodedata.normalize("NFKC", value).casefold()
    value = WHITESPACE_RE.sub(" ", value).strip()
    return value


def iter_text_values(data) -> Iterator[str]:
    """
    Deterministically walk JSON-ish data and yield string scalars.
    Dict traversal is sorted by key to keep stable output.
    """
    if data is None:
        return
    elif isinstance(data, str):
        if data:
            yield data
    elif isinstance(data, dict):
        for k in sorted(data.keys(), key=lambda x: str(x)):
            yield from iter_text_values(data.get(k))
    elif isinstance(data, list|tuple):
        for item in data:
            yield from iter_text_values(item)


def iter_trigrams(text: str) -> Iterator[bytes]:
    s = normalize_text(text)
    if not s or len(s) < 3:
        return
    # Use UTF-8 bytes of NFKC/casefolded string for stable trigram bytes
    b = s.encode("utf-8", errors="ignore")
    if len(b) < 3:
        return
    for i in range(len(b) - 2):
        yield b[i : i + 3]


def token_for_trigram(trigram: bytes, key: bytes | None = None) -> bytes:
    k = get_blind_trigram_key() if key is None else key
    digest = hmac.new(k, TRIGRAM_HMAC_PREFIX + trigram, hashlib.sha256).digest()
    return digest[:TOKEN_LEN]


def tokens_for_text(text: str|list[str], *, key: bytes | None = None) -> list[bytes]:
    if isinstance(text, str):
        text = [text]
    trigrams = set()
    for t in text:
        trigrams.update(iter_trigrams(t))

    key = key or get_blind_trigram_key()
    out = set()
    for tg in trigrams:
        out.add(token_for_trigram(tg, key=key))
    return sorted(out)


def tokens_for_data(data, *, key: bytes | None = None) -> list[bytes]:
    return tokens_for_text(list(iter_text_values(data)), key=key)

