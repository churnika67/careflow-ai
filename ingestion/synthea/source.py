import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

SUPPORTED_RESOURCE_TYPES = (
    "Patient",
    "Encounter",
    "Condition",
    "Procedure",
    "Observation",
    "MedicationRequest",
)


@dataclass(frozen=True)
class RejectedRecord:
    resource_type: str
    natural_key: str
    reason: str


def load_bundles(zip_path: Path, profile_path: Path, subset_path: Path) -> list[dict]:
    """Checksum-gate the Synthea release archive and each selected bundle file
    individually, then parse the selected bundles. A changed archive or a
    changed bundle file fails here, before any resource is used."""
    profile = json.loads(profile_path.read_text())
    subset = json.loads(subset_path.read_text())
    if profile["zip_sha256"] != subset["zip_sha256"]:
        raise ValueError("Profile and dev subset were built from different releases")
    raw = zip_path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if sha != profile["zip_sha256"]:
        raise ValueError("Synthea archive checksum does not match the reviewed profile")
    bundles = []
    with ZipFile(zip_path) as z:
        if z.testzip():
            raise ValueError("Corrupt Synthea archive")
        for name in subset["bundle_files"]:
            content = z.read(name)
            content_sha = hashlib.sha256(content).hexdigest()
            if content_sha != subset["bundle_sha256"][name]:
                raise ValueError(f"{name}: bundle checksum does not match the reviewed subset")
            bundle = json.loads(content)
            if bundle.get("resourceType") != "Bundle":
                raise ValueError(f"{name}: not a FHIR Bundle")
            bundles.append({"file": name, "sha256": content_sha, "bundle": bundle})
    return bundles
