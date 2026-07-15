"""File tools: read / write / edit / list.

Pure async logic over a HarnessContext. File IO here is bounded (reads capped at
max_read_chars) and fast, so it runs inline; the genuinely slow work (shelling
out) lives in proc.py. Capability gating happens in the server wrapper; these
functions only do path-gated work.
"""

from __future__ import annotations

import hashlib

from ..context import HarnessContext


def _looks_binary(sample: bytes) -> bool:
    return b"\x00" in sample


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _assert_fresh(real, expected_sha: str | None) -> None:
    """Reject a write when the file changed since the model last read it.

    ``expected_sha`` is a prefix of the sha256 shown by read_file. Prevents the
    model from silently clobbering edits made in your editor between read and
    write (last-write-wins data loss)."""
    if not expected_sha:
        return
    current = _sha(real.read_text(encoding="utf-8", errors="replace")) if real.exists() else ""
    if not current.startswith(expected_sha):
        raise ValueError(
            f"Stale write blocked: {real.name} changed since you read it "
            f"(expected sha {expected_sha}…, now {current[:12] or 'absent'}…). "
            "Re-read the file and reapply your change."
        )


async def read_file(
    hc: HarnessContext, path: str, offset: int | None = None, limit: int | None = None
) -> str:
    real = hc.resolve_read(path)
    if not real.exists():
        raise FileNotFoundError(f"File not found: {real}")
    if real.is_dir():
        raise IsADirectoryError(f"{real} is a directory. Use list_dir instead.")

    with real.open("rb") as fh:
        head = fh.read(8192)
    if _looks_binary(head):
        return f"[binary file, {real.stat().st_size} bytes — not shown]"

    text = real.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    total = len(lines)

    start = max(0, (offset - 1)) if offset is not None else 0
    end = min(total, start + limit) if limit is not None else total
    body = "\n".join(lines[start:end])

    truncated = ""
    if len(body) > hc.config.max_read_chars:
        body = body[: hc.config.max_read_chars]
        truncated = (
            f"\n\n[truncated at {hc.config.max_read_chars} chars; "
            "use offset/limit to page through the rest]"
        )

    span = f"[lines {start + 1}-{end} of {total}] " if (offset or limit or end < total) else ""
    # Surface a content hash so a later edit/write can pass expected_sha and be
    # rejected if the file changed underneath (stale-write guard).
    header = f"{span}[sha256:{_sha(text)[:12]}]\n"
    hc.log("read_file", path=str(real), lines=f"{start + 1}-{end}/{total}")
    return header + body + truncated


async def write_file(hc: HarnessContext, path: str, content: str, expected_sha: str | None = None) -> str:
    real = hc.resolve_write(path)
    _assert_fresh(real, expected_sha)
    existed = real.exists()
    real.parent.mkdir(parents=True, exist_ok=True)
    real.write_text(content, encoding="utf-8")
    verb = "Overwrote" if existed else "Created"
    n_lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    n_bytes = len(content.encode("utf-8"))
    hc.log("write_file", path=str(real), action=verb.lower(), bytes=n_bytes)
    return f"{verb} {real} ({n_bytes} bytes, {n_lines} lines)."


async def edit_file(
    hc: HarnessContext,
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
    expected_sha: str | None = None,
) -> str:
    real = hc.resolve_write(path)
    if not real.exists():
        raise FileNotFoundError(f"File not found: {real}")
    if old_string == new_string:
        raise ValueError("old_string and new_string are identical.")
    _assert_fresh(real, expected_sha)

    text = real.read_text(encoding="utf-8", errors="replace")
    count = text.count(old_string)
    if count == 0:
        raise ValueError(
            "old_string not found. It must match exactly, including whitespace and indentation."
        )
    if count > 1 and not replace_all:
        raise ValueError(
            f"old_string appears {count} times. Pass replace_all=true to replace all, "
            "or add surrounding context to make it unique."
        )

    new_text = text.replace(old_string, new_string) if replace_all else text.replace(old_string, new_string, 1)
    real.write_text(new_text, encoding="utf-8")
    n = count if replace_all else 1
    hc.log("edit_file", path=str(real), replacements=n)
    return f"Applied {n} replacement(s) in {real}."


async def apply_edits(hc: HarnessContext, edits: list) -> str:
    """Apply many file operations as a batch with in-process rollback: validate
    all, snapshot all, apply all, and restore the snapshots if any step raises.

    Not a filesystem transaction — a hard crash (power loss, kill -9) can still
    leave partial state, and directory/permission/symlink metadata is not
    restored. It protects against the common case: an ordinary error partway
    through a multi-file change.

    Each edit is an object with a 'path' plus one of:
      * content: str                         -> create/overwrite the file
      * old_string + new_string (+ replace_all) -> exact-string edit
      * delete: true                         -> delete the file
    """
    if not isinstance(edits, list) or not edits:
        raise ValueError("edits must be a non-empty list of operations.")

    # Phase 1 — validate everything; build the planned (kind, path, data) list.
    planned: list[tuple[str, object, str | None]] = []
    for i, e in enumerate(edits, 1):
        if not isinstance(e, dict) or "path" not in e:
            raise ValueError(f"edit #{i} must be an object with a 'path'.")
        real = hc.resolve_write(e["path"])
        _assert_fresh(real, e.get("expected_sha"))
        if e.get("delete"):
            if not real.exists():
                raise ValueError(f"{real}: cannot delete, does not exist.")
            planned.append(("delete", real, None))
        elif "content" in e:
            planned.append(("write", real, e["content"]))
        elif "old_string" in e and "new_string" in e:
            if not real.exists():
                raise FileNotFoundError(f"{real}: not found for edit.")
            text = real.read_text(encoding="utf-8", errors="replace")
            old, new = e["old_string"], e["new_string"]
            if old == new:
                raise ValueError(f"{real}: old_string and new_string are identical.")
            count = text.count(old)
            if count == 0:
                raise ValueError(f"{real}: old_string not found.")
            if count > 1 and not e.get("replace_all"):
                raise ValueError(f"{real}: old_string appears {count} times; set replace_all.")
            new_text = text.replace(old, new) if e.get("replace_all") else text.replace(old, new, 1)
            planned.append(("write", real, new_text))
        else:
            raise ValueError(f"edit #{i}: needs content, or old_string+new_string, or delete:true.")

    # Phase 2 — snapshot originals, then apply; roll back on any failure.
    backups = [(real, real.read_bytes() if real.exists() else None) for _, real, _ in planned]
    results: list[str] = []
    try:
        for kind, real, data in planned:
            if kind == "delete":
                if real.exists():
                    real.unlink()
                results.append(f"deleted {real}")
            else:
                existed = real.exists()
                real.parent.mkdir(parents=True, exist_ok=True)
                real.write_text(data, encoding="utf-8")
                results.append(f"{'wrote' if existed else 'created'} {real}")
    except Exception as exc:  # noqa: BLE001 - restore snapshot, then report
        for real, original in backups:
            try:
                if original is None:
                    if real.exists():
                        real.unlink()
                else:
                    real.write_bytes(original)
            except OSError:
                pass
        raise RuntimeError(f"apply_edits failed and was rolled back: {exc}") from exc

    hc.log("apply_edits", count=len(results))
    return f"Applied {len(results)} operation(s) atomically:\n" + "\n".join(f"  {r}" for r in results)


def _patch_targets(patch: str) -> list[str]:
    """Target paths a unified diff would write (from '+++ b/...' headers)."""
    targets: list[str] = []
    for line in patch.splitlines():
        if line.startswith("+++ "):
            p = line[4:].strip()
            if p in ("/dev/null", ""):
                continue
            if p.startswith(("a/", "b/")):
                p = p[2:]
            targets.append(p)
    return targets


async def apply_patch(hc: HarnessContext, patch: str, expected_shas: dict | None = None) -> str:
    """Apply a unified diff to the workspace via `git apply` (robust context
    matching). Every target path is checked against the workspace confinement +
    secret + .git guards BEFORE applying, so a crafted patch can't escape.
    Optionally pass expected_shas {path: sha_prefix} (from read_file headers)
    for an explicit stale-write guard on top of git's own context matching."""
    import secrets as _secrets

    from . import gitcmd

    ws = hc.require_workspace()
    if not patch or not patch.strip():
        raise ValueError("Empty patch.")
    targets = _patch_targets(patch)
    if not targets:
        raise ValueError("No target files found in patch (need unified diff '+++ b/...' headers).")
    for t in targets:
        hc.resolve_write(t)  # raises SecurityError if outside root / secret / .git
    for p, sha in (expected_shas or {}).items():
        _assert_fresh(hc.resolve_write(p), sha)

    tmp = hc.config.state_dir / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    patch_file = tmp / f"patch-{_secrets.token_hex(6)}.diff"
    patch_file.write_text(patch if patch.endswith("\n") else patch + "\n", encoding="utf-8")
    try:
        result = await gitcmd.git(hc, ws, "apply", "--whitespace=nowarn", str(patch_file))
    finally:
        patch_file.unlink(missing_ok=True)
    if result.returncode != 0:
        return f"Error applying patch: {result.stderr.strip() or result.stdout.strip()}"
    hc.log("apply_patch", files=len(targets))
    return f"Applied patch to {len(targets)} file(s): {', '.join(targets)}"


async def list_dir(hc: HarnessContext, path: str | None = None, limit: int = 400) -> str:
    target = path if path is not None else str(hc.require_workspace())
    real = hc.resolve_read(target)
    if not real.exists():
        raise FileNotFoundError(f"Directory not found: {real}")
    if not real.is_dir():
        raise NotADirectoryError(f"{real} is not a directory.")

    entries = sorted(real.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    rows: list[str] = []
    for entry in entries[:limit]:
        if entry.is_dir():
            rows.append(f"  {entry.name}/")
        else:
            try:
                size = entry.stat().st_size
            except OSError:
                size = 0
            rows.append(f"  {entry.name}  ({size} bytes)")
    more = f"\n  ... and {len(entries) - limit} more" if len(entries) > limit else ""
    return f"{real}:\n" + "\n".join(rows) + more
