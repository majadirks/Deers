"""Document and Inventory models."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from deers.models import BLOCKING_FLAWS, DocumentFlaw, DocumentType

if TYPE_CHECKING:
    pass


@dataclass
class Document:
    doc_type: DocumentType
    display_name: str
    description: str
    fallback_examine_text: str
    fixes_fields: list[str]          # DEERS field names this doc can fix
    can_be_photocopied: bool
    possible_flaws: list[str]        # flaw ids from TOML
    active_flaws: list[DocumentFlaw] = field(default_factory=list)
    instance_id: str = ""            # unique per-instance (set by factory)

    def fixes(self, field_name: str) -> bool:
        """True if this document type can fix the given DEERS field."""
        return field_name in self.fixes_fields

    def has_flaw(self, flaw: DocumentFlaw) -> bool:
        return flaw in self.active_flaws

    def has_blocking_flaw(self) -> bool:
        return any(f in BLOCKING_FLAWS for f in self.active_flaws)

    def is_effectively_valid(self) -> bool:
        """Valid means: no blocking flaws."""
        return not self.has_blocking_flaw()

    def describe_flaws(self) -> str:
        if not self.active_flaws:
            return "No apparent issues."
        descriptions = []
        flaw_text = {
            DocumentFlaw.LAMINATED: "It has been laminated.",
            DocumentFlaw.EXPIRED: "It is expired.",
            DocumentFlaw.MAIDEN_NAME: "It reflects a previous legal name.",
            DocumentFlaw.WRONG_ADDRESS: "The address on file no longer matches.",
            DocumentFlaw.ILLEGIBLE_NOTARY: "The notary stamp is illegible.",
            DocumentFlaw.MISSING_PAGE_2: "Page two is missing.",
            DocumentFlaw.UNOFFICIAL_COPY: "This is an unofficial copy.",
        }
        for f in self.active_flaws:
            descriptions.append(flaw_text.get(f, str(f)))
        return " ".join(descriptions)

    def to_dict(self) -> dict:
        return {
            "doc_type": self.doc_type.value,
            "active_flaws": [f.value for f in self.active_flaws],
            "instance_id": self.instance_id,
        }

    @classmethod
    def from_dict(cls, d: dict, content: dict) -> "Document":
        doc_type = DocumentType(d["doc_type"])
        spec = next(
            doc for doc in content["documents"]["document"]
            if doc["id"] == doc_type.value
        )
        return cls(
            doc_type=doc_type,
            display_name=spec["display_name"],
            description=spec["description"],
            fallback_examine_text=spec["fallback_examine_text"],
            fixes_fields=spec["fixes_fields"],
            can_be_photocopied=spec["can_be_photocopied"],
            possible_flaws=[fl["id"] for fl in spec.get("possible_flaws", [])],
            active_flaws=[DocumentFlaw(f) for f in d["active_flaws"]],
            instance_id=d["instance_id"],
        )


class DocumentFactory:
    """Creates Document instances with randomly assigned flaws."""

    def __init__(self, rng: random.Random, content: dict):
        self._rng = rng
        self._content = content
        self._counter = 0

    def make(
        self,
        doc_type: DocumentType,
        force_flaws: list[DocumentFlaw] | None = None,
        max_flaws: int = 2,
    ) -> Document:
        spec = next(
            doc for doc in self._content["documents"]["document"]
            if doc["id"] == doc_type.value
        )
        possible = [DocumentFlaw(fl["id"]) for fl in spec.get("possible_flaws", [])]

        if force_flaws is not None:
            active = list(force_flaws)
        elif not possible:
            active = []
        else:
            # 0-max_flaws flaws drawn without replacement
            count = self._rng.randint(0, min(max_flaws, len(possible)))
            active = self._rng.sample(possible, count)

        self._counter += 1
        return Document(
            doc_type=doc_type,
            display_name=spec["display_name"],
            description=spec["description"],
            fallback_examine_text=spec["fallback_examine_text"],
            fixes_fields=spec["fixes_fields"],
            can_be_photocopied=spec["can_be_photocopied"],
            possible_flaws=[fl["id"] for fl in spec.get("possible_flaws", [])],
            active_flaws=active,
            instance_id=f"{doc_type.value}_{self._counter}",
        )


@dataclass
class Inventory:
    documents: list[Document] = field(default_factory=list)

    def add(self, doc: Document) -> None:
        self.documents.append(doc)

    def remove(self, doc: Document) -> None:
        self.documents.remove(doc)

    def has(self, doc_type: DocumentType) -> bool:
        return any(d.doc_type == doc_type for d in self.documents)

    def has_valid(self, doc_type: DocumentType) -> bool:
        return any(
            d.doc_type == doc_type and d.is_effectively_valid()
            for d in self.documents
        )

    def get(self, doc_type: DocumentType) -> Document | None:
        return next((d for d in self.documents if d.doc_type == doc_type), None)

    def matching_documents(self, field_name: str) -> list[Document]:
        """All documents that can fix the given DEERS field."""
        return [d for d in self.documents if d.fixes(field_name)]

    def valid_matching_documents(self, field_name: str) -> list[Document]:
        """Documents that can fix the field AND have no blocking flaws."""
        return [d for d in self.matching_documents(field_name) if d.is_effectively_valid()]

    def to_dict(self) -> dict:
        return {"documents": [d.to_dict() for d in self.documents]}

    @classmethod
    def from_dict(cls, d: dict, content: dict) -> "Inventory":
        inv = cls()
        for doc_dict in d["documents"]:
            inv.documents.append(Document.from_dict(doc_dict, content))
        return inv
