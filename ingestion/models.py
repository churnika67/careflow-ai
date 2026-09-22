import hashlib
import json
from dataclasses import dataclass


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class Section:
    field: str
    ordinal: int
    heading: str
    text: str
    raw_field_sha256: str
    links: tuple[str, ...]


@dataclass(frozen=True)
class Document:
    metadata: dict
    sections: tuple[Section, ...]


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    text: str
    metadata: dict

    def payload(self) -> dict:
        return self.metadata | {"chunk_id": self.chunk_id, "text": self.text}
