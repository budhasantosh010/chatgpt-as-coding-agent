"""Objective verifier for the fixed benchmark fixture."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import tempfile
from pathlib import Path


def _load(workspace: Path, module: str):
    path = workspace / f"{module}.py"
    spec = importlib.util.spec_from_file_location(f"bench_{module}_{id(path)}", path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def evaluate(workspace: Path) -> dict[str, dict]:
    workspace = Path(workspace).resolve()
    results = {}
    try:
        pricing = _load(workspace, "pricing")
        passed = pricing.price_after_discount(80, 25) == 60
        detail = "25 percent of 80 produces 60"
    except Exception as exc:
        passed, detail = False, str(exc)
    results["B01"] = {"passed": passed, "detail": detail}

    try:
        model = _load(workspace, "order_model")
        store_mod = _load(workspace, "order_store")
        state_path = workspace / ".benchmark-order-store.json"
        state_path.unlink(missing_ok=True)
        store = store_mod.OrderStore(state_path)
        store.add(model.Order("A"))
        first = store.cancel("A")
        reopened = store_mod.OrderStore(state_path)
        second = reopened.cancel("A")
        passed = first.status == "cancelled" and second.status == "cancelled" and len(reopened.audit) == 1
        detail = "cancellation is durable, audited once, and idempotent"
    except Exception as exc:
        passed, detail = False, str(exc)
    finally:
        try:
            state_path.unlink(missing_ok=True)
        except (NameError, OSError):
            pass
    results["B02"] = {"passed": passed, "detail": detail}

    try:
        reporting = _load(workspace, "reporting")
        passed = reporting.report_total(["$1,000.00", "$20.00"]) == 1020
        detail = "formatted currency values total correctly"
    except Exception as exc:
        passed, detail = False, str(exc)
    results["B03"] = {"passed": passed, "detail": detail}

    try:
        users = _load(workspace, "users")
        source = (workspace / "users.py").read_text(encoding="utf-8")
        created = users.create_user("  PERSON@Example.COM ")
        found = users.find_user([created], "person@example.com")
        passed = callable(getattr(users, "normalize_email", None)) and found == created and source.count("normalize_email(") >= 3
        detail = "one helper is defined and both public paths use it"
    except Exception as exc:
        passed, detail = False, str(exc)
    results["B04"] = {"passed": passed, "detail": detail}

    try:
        attachments = _load(workspace, "attachments")
        with tempfile.TemporaryDirectory(prefix="harness-b05-") as temp:
            base = Path(temp)
            root, outside = base / "uploads", base / "outside"
            root.mkdir()
            outside.mkdir()
            valid = attachments.attachment_path(root, "nested/photo.png")
            attacks = [
                "../secret.txt", "nested/../../secret.txt",
                "../uploads-evil/secret.txt", str(outside / "secret.txt"),
            ]
            if os.name == "nt":
                attacks.extend([r"C:\outside\secret.txt", r"\\server\share\secret.txt"])
            try:
                (root / "escape").symlink_to(outside, target_is_directory=True)
                attacks.append("escape/secret.txt")
            except OSError:
                pass
            rejected = []
            for attack in attacks:
                try:
                    attachments.attachment_path(root, attack)
                except ValueError:
                    rejected.append(attack)
            passed = len(rejected) == len(attacks) and valid.resolve().is_relative_to(root.resolve())
            detail = f"rejected {len(rejected)}/{len(attacks)} traversal variants"
    except Exception as exc:
        passed, detail = False, str(exc)
    results["B05"] = {"passed": passed, "detail": detail}
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path(__file__).parent / "fixture_seed")
    args = parser.parse_args()
    results = evaluate(args.workspace)
    print(json.dumps(results, indent=2))
    return 0 if all(result["passed"] for result in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
