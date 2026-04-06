"""DEERSField, DEERSRecord, and DEERSGenerator."""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field

from deers.models import BLOCKING_FLAWS, DocumentFlaw, FixMethod, FixResult


# How many corruptions to guarantee on loop 1.
LOOP_1_CORRUPTIONS = 3
# Base probability of any given field being corrupted.
BASE_CORRUPTION_PROB = 0.45
# Each resolved corruption in permanent_knowledge reduces probability by this much.
KNOWLEDGE_MITIGATION = 0.12
# Probability of the IMPOSSIBLE combination appearing (dod_id + clearance simultaneously).
IMPOSSIBLE_PROB = 1 / 8


@dataclass
class DEERSField:
    name: str
    display_name: str
    fix_method: FixMethod
    fixing_documents: list[str]     # document type ids
    blocking: bool
    flavor_text: str
    current_value: str = "CORRUPTED"
    is_corrupted: bool = False

    def attempt_fix(self, document) -> FixResult:
        """
        Attempt to fix this field using a Document instance.
        Returns FixResult describing success or reason for failure.
        """
        if not self.is_corrupted:
            return FixResult(
                success=False,
                field_name=self.name,
                message=f"The {self.display_name} field appears to be correct.",
            )

        if self.fix_method == FixMethod.IMPOSSIBLE:
            return FixResult(
                success=False,
                field_name=self.name,
                message=(
                    "This field cannot be corrected at this location. "
                    "A DMDC ticket would take six to eight weeks. "
                    "Your start date is Monday."
                ),
            )

        if document.doc_type.value not in self.fixing_documents:
            return FixResult(
                success=False,
                field_name=self.name,
                message=(
                    f"The {document.display_name} does not apply to "
                    f"the {self.display_name} field."
                ),
            )

        if not document.is_effectively_valid():
            flaw_desc = document.describe_flaws()
            return FixResult(
                success=False,
                field_name=self.name,
                message=(
                    f"The {document.display_name} cannot be accepted. {flaw_desc}"
                ),
            )

        # Non-local fix methods require specific out-of-office actions
        if self.fix_method == FixMethod.HR:
            return FixResult(
                success=False,
                field_name=self.name,
                message=(
                    f"The {self.display_name} must be corrected by your HR office. "
                    "We cannot update this field on-site."
                ),
            )

        if self.fix_method == FixMethod.FSO:
            return FixResult(
                success=False,
                field_name=self.name,
                message=(
                    f"The {self.display_name} must be corrected by your FSO in JPAS. "
                    "We cannot update this field on-site."
                ),
            )

        if self.fix_method == FixMethod.CONGRESSIONAL:
            return FixResult(
                success=False,
                field_name=self.name,
                message=(
                    f"The {self.display_name} requires a contract amendment. "
                    "Contact your contracting officer."
                ),
            )

        # ON_SITE fix
        self.is_corrupted = False
        self.current_value = "CORRECTED"
        return FixResult(
            success=True,
            field_name=self.name,
            message=f"The {self.display_name} has been updated.",
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "is_corrupted": self.is_corrupted,
            "current_value": self.current_value,
        }

    @classmethod
    def from_dict(cls, d: dict, spec: dict) -> "DEERSField":
        return cls(
            name=spec["name"],
            display_name=spec["display_name"],
            fix_method=FixMethod(spec["fix_method"]),
            fixing_documents=spec["fixing_documents"],
            blocking=spec["blocking"],
            flavor_text=spec["flavor_text"],
            current_value=d["current_value"],
            is_corrupted=d["is_corrupted"],
        )


@dataclass
class DEERSRecord:
    fields: dict[str, DEERSField] = field(default_factory=dict)

    def is_issuable(self) -> bool:
        """True if no blocking fields are corrupted."""
        return not any(
            f.is_corrupted and f.blocking for f in self.fields.values()
        )

    def corrupted_fields(self) -> list[DEERSField]:
        return [f for f in self.fields.values() if f.is_corrupted]

    def blocking_corruptions(self) -> list[DEERSField]:
        return [f for f in self.fields.values() if f.is_corrupted and f.blocking]

    def attempt_fix(self, field_name: str, document) -> FixResult:
        if field_name not in self.fields:
            return FixResult(
                success=False,
                field_name=field_name,
                message=f"No field named '{field_name}' in your DEERS record.",
            )
        return self.fields[field_name].attempt_fix(document)

    def has_impossible_combination(self) -> bool:
        """True if both dod_id AND clearance_level are corrupted simultaneously."""
        return (
            self.fields.get("dod_id", DEERSField("", "", FixMethod.ON_SITE, [], False, "")).is_corrupted
            and self.fields.get("clearance_level", DEERSField("", "", FixMethod.ON_SITE, [], False, "")).is_corrupted
        )

    def to_dict(self) -> dict:
        return {"fields": {name: f.to_dict() for name, f in self.fields.items()}}

    @classmethod
    def from_dict(cls, d: dict, content: dict) -> "DEERSRecord":
        field_specs = {spec["name"]: spec for spec in content["deers_fields"]["field"]}
        record = cls()
        for name, fdict in d["fields"].items():
            record.fields[name] = DEERSField.from_dict(fdict, field_specs[name])
        return record


class DEERSGenerator:
    """
    Deterministically generate a DEERSRecord for a given loop and
    permanent_knowledge set. Same inputs always produce the same record.
    """

    def __init__(self, content: dict):
        self._content = content
        self._field_specs = content["deers_fields"]["field"]

    def _make_seed(self, loop: int, permanent_knowledge: frozenset[str]) -> int:
        key_str = f"{loop}|{sorted(permanent_knowledge)}"
        return int(hashlib.md5(key_str.encode()).hexdigest(), 16)

    def generate(self, loop: int, permanent_knowledge: frozenset[str]) -> DEERSRecord:
        rng = random.Random(self._make_seed(loop, permanent_knowledge))
        record = DEERSRecord()

        # Build all fields uncorrupted first
        for spec in self._field_specs:
            record.fields[spec["name"]] = DEERSField(
                name=spec["name"],
                display_name=spec["display_name"],
                fix_method=FixMethod(spec["fix_method"]),
                fixing_documents=spec["fixing_documents"],
                blocking=spec["blocking"],
                flavor_text=spec["flavor_text"],
                current_value="CORRECT",
                is_corrupted=False,
            )

        # --- Transcendence gate: roll for IMPOSSIBLE combination ---
        if rng.random() < IMPOSSIBLE_PROB:
            record.fields["dod_id"].is_corrupted = True
            record.fields["dod_id"].current_value = self._corrupt_value("dod_id", rng)
            record.fields["clearance_level"].is_corrupted = True
            record.fields["clearance_level"].current_value = self._corrupt_value("clearance_level", rng)

        # --- Regular corruption pass ---
        # Fields already marked impossible can be skipped to avoid double-counting
        resolved_keys = {
            k.replace("DEERS_FIELD_", "")
            for k in permanent_knowledge
            if k.startswith("DEERS_FIELD_")
        }

        for spec in self._field_specs:
            name = spec["name"]
            if record.fields[name].is_corrupted:
                continue  # already set by impossible combination

            # Knowledge about a field reduces its corruption probability
            mitigation = KNOWLEDGE_MITIGATION if name in resolved_keys else 0.0
            prob = max(0.05, BASE_CORRUPTION_PROB - mitigation)

            if rng.random() < prob:
                record.fields[name].is_corrupted = True
                record.fields[name].current_value = self._corrupt_value(name, rng)

        # --- Guarantee at least 1 corruption always ---
        if not record.corrupted_fields():
            # Force-corrupt a random non-IMPOSSIBLE blocking field
            candidates = [
                spec["name"] for spec in self._field_specs
                if spec["fix_method"] != "IMPOSSIBLE" and spec["blocking"]
            ]
            chosen = rng.choice(candidates)
            record.fields[chosen].is_corrupted = True
            record.fields[chosen].current_value = self._corrupt_value(chosen, rng)

        # --- Loop 1 guarantee: at least LOOP_1_CORRUPTIONS ---
        if loop == 1:
            while len(record.corrupted_fields()) < LOOP_1_CORRUPTIONS:
                not_yet = [
                    spec["name"] for spec in self._field_specs
                    if not record.fields[spec["name"]].is_corrupted
                ]
                if not not_yet:
                    break
                chosen = rng.choice(not_yet)
                record.fields[chosen].is_corrupted = True
                record.fields[chosen].current_value = self._corrupt_value(chosen, rng)

        return record

    def _corrupt_value(self, field_name: str, rng: random.Random) -> str:
        """Generate a plausible-looking corrupted value for a field."""
        corrupt_values: dict[str, list[str]] = {
            "last_name": ["REDACTED", "NULL", "PENDING", "RESERVED", "CLASSIFIED"],
            "ssn_last4": ["0000", "9999", "####", "XXXX", "----"],
            "dod_id": ["0000000000", "9999999999", "XXXXXXXXXX", "INVALID"],
            "clearance_level": ["NONE", "UNKNOWN", "PENDING", "N/A", "ERROR"],
            "component": ["UNKNOWN", "N/A", "CIVILIAN_ERROR", "JOINT"],
            "uic": ["W0XXXX", "INVALID", "00000", "LEGACY"],
            "rank_grade": ["E-0", "GS-00", "UNKNOWN", "N/A"],
            "contract_end": ["01/01/1900", "EXPIRED", "00/00/0000", "PENDING"],
        }
        options = corrupt_values.get(field_name, ["ERROR"])
        return rng.choice(options)
