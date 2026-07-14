"""Configuration loading for the harness.

All settings come from environment variables (prefix ``HARNESS_``) with sane
defaults, plus an optional ``.env`` file in the working directory. Config is a
plain dataclass so tests can construct it directly without touching the
environment.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


# Files that must never be read or written through the harness, so their
# contents can't be exfiltrated to ChatGPT or clobbered. Matched against every
# path component and the full path (fnmatch semantics).
DEFAULT_SECRET_GLOBS: tuple[str, ...] = (
    "id_rsa", "id_rsa.*", "id_ed25519", "id_ed25519.*", "id_ecdsa", "id_ecdsa.*",
    "*.pem", "*.key", "*.ppk", "*.p12", "*.pfx", "*.keystore", "*.jks",
    ".git-credentials", ".npmrc", ".pypirc", ".netrc", "credentials",
    "*.kdbx", "id_dsa", "*.gpg", "secring.*",
)


def _default_state_dir() -> Path:
    env = os.environ.get("HARNESS_STATE_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".chatgpt-code-harness"


def _split_list(value: str, *, sep: str) -> list[str]:
    if sep == "pathsep":
        raw = value.replace("\n", os.pathsep).split(os.pathsep)
    else:
        raw = value.replace("\n", sep).split(sep)
    return [p.strip() for p in raw if p.strip()]


def _env(name: str, default: str = "") -> str:
    return os.environ.get(f"HARNESS_{name}", default)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(f"HARNESS_{name}")
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(f"HARNESS_{name}")
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader: KEY=VALUE lines, no export, no interpolation.

    Only sets variables that aren't already in the environment, so real env
    vars win over the file.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


@dataclass
class Config:
    host: str = "127.0.0.1"
    port: int = 8848
    mode: str = "full"  # "full" | "read_only"
    secret_route: str = ""
    bearer_token: str = ""
    state_dir: Path = field(default_factory=_default_state_dir)
    workspace_roots: list[Path] = field(default_factory=list)
    allowed_origins: list[str] = field(
        default_factory=lambda: [
            "https://chatgpt.com",
            "https://chat.openai.com",
            "https://platform.openai.com",
        ]
    )
    allowed_hosts: list[str] = field(default_factory=lambda: ["localhost", "127.0.0.1"])
    allow_ts_net: bool = True
    shell: str = ""  # "" => auto (PowerShell on Windows, bash on POSIX)
    max_output_chars: int = 30000
    max_read_chars: int = 100000
    rate_limit_per_min: int = 120
    stateless_http: bool = True
    json_response: bool = True  # matches the proven-working ChatGPT connector config
    secret_globs: list[str] = field(default_factory=lambda: list(DEFAULT_SECRET_GLOBS))

    # ---- derived / validated ------------------------------------------------

    def __post_init__(self) -> None:
        self.state_dir = Path(self.state_dir).expanduser()
        self.state_dir.mkdir(parents=True, exist_ok=True)

        # Persist the secret route so the ChatGPT connector URL is stable across
        # restarts (otherwise you'd reconfigure ChatGPT every launch).
        if not self.secret_route:
            f = self.state_dir / "secret_route.txt"
            if f.exists():
                self.secret_route = f.read_text(encoding="utf-8").strip()
            else:
                self.secret_route = secrets.token_urlsafe(32)
                f.write_text(self.secret_route, encoding="utf-8")
        self.secret_route = self.secret_route.strip().strip("/")

        # Resolve workspace roots; default to a sandbox dir under state_dir.
        roots = [Path(r).expanduser() for r in self.workspace_roots]
        if not roots:
            default_ws = self.state_dir / "workspaces"
            default_ws.mkdir(parents=True, exist_ok=True)
            roots = [default_ws]
        resolved: list[Path] = []
        for r in roots:
            try:
                resolved.append(Path(os.path.realpath(str(r))))
            except OSError:
                resolved.append(r)
        # Harness-owned worktree area is always an allowed root so task worktrees
        # created here can be opened and operated on like any workspace.
        worktrees_root = self.state_dir / "worktrees"
        worktrees_root.mkdir(parents=True, exist_ok=True)
        resolved.append(Path(os.path.realpath(str(worktrees_root))))
        self.workspace_roots = resolved

        if self.mode not in ("full", "read_only"):
            raise ValueError(f"HARNESS_MODE must be 'full' or 'read_only', got {self.mode!r}")

    @property
    def mcp_path(self) -> str:
        return f"/{self.secret_route}/mcp"

    def local_url(self) -> str:
        return f"http://{self.host}:{self.port}{self.mcp_path}"

    @classmethod
    def from_env(cls, *, load_dotenv: bool = True) -> "Config":
        if load_dotenv:
            _load_dotenv(Path.cwd() / ".env")

        roots_raw = _env("WORKSPACE_ROOTS")
        origins_raw = _env("ALLOWED_ORIGINS")
        hosts_raw = _env("ALLOWED_HOSTS")
        globs_raw = _env("EXTRA_SECRET_GLOBS")

        kwargs: dict = dict(
            host=_env("HOST", "127.0.0.1"),
            port=_env_int("PORT", 8848),
            mode=_env("MODE", "full"),
            secret_route=_env("SECRET_ROUTE", ""),
            bearer_token=_env("BEARER_TOKEN", ""),
            allow_ts_net=_env_bool("ALLOW_TS_NET", True),
            shell=_env("SHELL", ""),
            max_output_chars=_env_int("MAX_OUTPUT_CHARS", 30000),
            max_read_chars=_env_int("MAX_READ_CHARS", 100000),
            rate_limit_per_min=_env_int("RATE_LIMIT_PER_MIN", 120),
            stateless_http=_env_bool("STATELESS_HTTP", True),
            json_response=_env_bool("JSON_RESPONSE", True),
        )
        state_dir = _env("STATE_DIR")
        if state_dir:
            kwargs["state_dir"] = Path(state_dir).expanduser()
        if roots_raw:
            kwargs["workspace_roots"] = [Path(p) for p in _split_list(roots_raw, sep="pathsep")]
        if origins_raw:
            kwargs["allowed_origins"] = _split_list(origins_raw, sep=",")
        if hosts_raw:
            kwargs["allowed_hosts"] = _split_list(hosts_raw, sep=",")

        cfg = cls(**kwargs)
        if globs_raw:
            cfg.secret_globs = list(DEFAULT_SECRET_GLOBS) + _split_list(globs_raw, sep=",")
        return cfg

    def redacted(self) -> dict:
        """Config summary safe to print (no secret route / token values)."""
        return {
            "host": self.host,
            "port": self.port,
            "mode": self.mode,
            "secret_route": f"<{len(self.secret_route)} chars, hidden>",
            "bearer_token": "set" if self.bearer_token else "not set",
            "state_dir": str(self.state_dir),
            "workspace_roots": [str(r) for r in self.workspace_roots],
            "allowed_origins": self.allowed_origins,
            "allowed_hosts": self.allowed_hosts + (["*.ts.net"] if self.allow_ts_net else []),
            "shell": self.shell or "auto",
            "stateless_http": self.stateless_http,
            "json_response": self.json_response,
            "rate_limit_per_min": self.rate_limit_per_min,
        }
