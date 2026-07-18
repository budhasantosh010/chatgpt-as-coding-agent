from pathlib import Path


def attachment_path(root: Path, name: str) -> Path:
    return root / name
