import hashlib
import hmac
import re
import unicodedata
from collections.abc import Iterable, Iterator

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
    value = unicodedata.normalize("NFKC", str(value)).casefold()
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
    elif isinstance(data, (list, tuple)):
        for item in data:
            yield from iter_text_values(item)


def extract_text_from_data(data) -> str:
    return " ".join(map(normalize_text, iter_text_values(data)))


def iter_trigrams(text: str) -> Iterator[bytes]:
    # TODO: split by whitespace and yield trigrams of each word or also yield trigrams for space-separators
    s = normalize_text(text)
    if not s or len(s) < 3:
        return
    # Use UTF-8 bytes of NFKC/casefolded string for stable trigram bytes
    b = s.encode("utf-8", errors="ignore")
    if len(b) < 3:
        return
    for i in range(0, len(b) - 2):
        yield b[i : i + 3]


def token_for_trigram(trigram: bytes, key: bytes | None = None) -> bytes:
    k = get_blind_trigram_key() if key is None else key
    digest = hmac.new(k, TRIGRAM_HMAC_PREFIX + trigram, hashlib.sha256).digest()
    return digest[:TOKEN_LEN]


def tokens_for_text(text: str, *, key: bytes | None = None) -> list[bytes]:
    key = key or get_blind_trigram_key()
    out = set()
    for tg in iter_trigrams(text):
        out.add(token_for_trigram(tg, key=key))
    return sorted(out)


def tokens_for_data(data, *, key: bytes | None = None) -> list[bytes]:
    return tokens_for_text(extract_text_from_data(data), key=key)

