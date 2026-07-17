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
    ".env", ".env.*",  # dotenv files hold live secrets (…but see SECRET_EXCEPTIONS)
)

# Filenames that LOOK like secret files by glob but are safe by convention
# (templates/examples that ship placeholder values). Suffix match, case-insensitive.
SECRET_EXCEPTION_SUFFIXES: tuple[str, ...] = (
    ".example", ".sample", ".template", ".dist", ".tmpl",
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
    mode: str = "full"  # operator's own mode (direct/local contexts)
    # Mode for tool calls that arrive WITHOUT a task_id (the shared fallback
    # session). Default read_only: browsing works, but writes/commands tell the
    # model to start_task first. Legacy behavior: HARNESS_NO_TASK_MODE=full.
    no_task_mode: str = "read_only"
    # Highest permission_mode ChatGPT may request via start_task. Anything above
    # (full / bypass_sandboxed by default) is operator-only, granted with
    # `python -m harness tasks set-mode`. This is the anti-self-escalation gate.
    max_mode: str = "auto_workspace"
    # Where a new task's files land by default (like Codex/Claude Code, we work
    # IN the project folder). "workspace" = edit the project checkout directly
    # (files appear where you made the project; review via git diff — the norm
    # for a single-user tool). "worktree" = always an isolated private copy.
    # "auto" = worktree for git repos, shared checkout otherwise (the old
    # default; kept for anyone who wants isolation-by-default).
    default_isolation: str = "workspace"
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
    # Redact known secret formats from all tool output before it reaches ChatGPT.
    scrub_output: bool = True
    # Append every tool call to state_dir/audit.jsonl (what ChatGPT did, when).
    audit_log: bool = True
    # Auto-snapshot the workspace before edits (debounced) so there's always a
    # restore point even if the model forgets to checkpoint.
    auto_checkpoint: bool = True
    auto_checkpoint_interval: int = 60
    # Let git_commit run the repo's own hooks (pre-commit etc.). Off by default:
    # repo hooks are repo-controlled code executing on the host.
    commit_hooks: bool = False
    # In auto_workspace mode, what happens to commands the classifier does NOT
    # recognize: "ask" (default; fail closed — anything unrecognized needs a
    # one-shot operator approval, or a remembered per-project approval via
    # `harness commands allow`) or "allow" (the classifier is advisory only).
    # The positive SAFE tier (pytest/npm test/linters/local git…) always runs.
    arbitrary_commands: str = "ask"
    # Live-event push sink (set by the supervisor when it spawns the engine):
    # events POST to this localhost URL so the cockpit gets a real-time feed.
    event_sink: str = ""
    event_token: str = ""
    # Cockpit (operator GUI) port — localhost-only, NEVER funneled.
    cockpit_port: int = 8849
    # Run the project's formatter on files after WRITE (checklist 6.2). Off by
    # default: formatting is a real edit the model didn't ask for.
    auto_format: bool = False
    # Enable operator-configured hooks from <state_dir>/hooks.json (Phase 7).
    user_hooks: bool = True
    # Execution backend for run_command: "local" (host shell) or "docker" (sandbox).
    sandbox: str = "local"
    sandbox_image: str = "python:3.12-slim"
    sandbox_network: str = "none"
    sandbox_cpus: str = "2"       # --cpus
    sandbox_memory: str = "2g"    # --memory
    sandbox_pids: int = 512       # --pids-limit (fork-bomb guard)
    sandbox_user: str = ""        # --user (e.g. "1000:1000"); empty = image default
    sandbox_readonly: bool = False  # read-only rootfs + tmpfs /tmp
    # Extra env var names a command may see, on top of the safe base set. Anything
    # not listed (cloud creds, tokens) is withheld so `run_command` can't print it.
    env_allowlist: list[str] = field(default_factory=list)
    # Other MCP servers to federate: {name: {command, args} | {url}}. From
    # HARNESS_MCP_SERVERS (JSON) or <state_dir>/mcp_servers.json.
    mcp_servers: dict = field(default_factory=dict)

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

        _valid_modes = ("full", "read_only", "plan", "build_ask", "auto_workspace", "bypass_sandboxed")
        if self.mode not in _valid_modes:
            raise ValueError(f"HARNESS_MODE must be one of {_valid_modes}, got {self.mode!r}")
        if self.no_task_mode not in _valid_modes:
            raise ValueError(f"HARNESS_NO_TASK_MODE must be one of {_valid_modes}, got {self.no_task_mode!r}")
        if self.max_mode not in _valid_modes:
            raise ValueError(f"HARNESS_MAX_MODE must be one of {_valid_modes}, got {self.max_mode!r}")
        if self.sandbox not in ("local", "docker"):
            raise ValueError(f"HARNESS_SANDBOX must be 'local' or 'docker', got {self.sandbox!r}")
        if self.arbitrary_commands not in ("allow", "ask"):
            raise ValueError(f"HARNESS_ARBITRARY_COMMANDS must be 'allow' or 'ask', got {self.arbitrary_commands!r}")
        if self.default_isolation not in ("auto", "worktree", "workspace"):
            raise ValueError(
                f"HARNESS_DEFAULT_ISOLATION must be 'auto', 'worktree', or 'workspace', got {self.default_isolation!r}")

    @property
    def mcp_path(self) -> str:
        return f"/{self.secret_route}/mcp"

    def local_url(self) -> str:
        return f"http://{self.host}:{self.port}{self.mcp_path}"

    @staticmethod
    def _roots_file(state_dir: Path) -> Path:
        return Path(state_dir).expanduser() / "roots.json"

    @classmethod
    def load_extra_roots(cls, state_dir: Path) -> list[str]:
        """Operator-added workspace roots persisted by `harness roots add`. Kept
        in the state dir (outside every workspace root), so the model's
        path-gated tools can't write it — only the local CLI can."""
        import json as _json

        f = cls._roots_file(state_dir)
        if not f.exists():
            return []
        try:
            data = _json.loads(f.read_text(encoding="utf-8"))
            return [str(p) for p in data] if isinstance(data, list) else []
        except (ValueError, OSError):
            return []

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
            no_task_mode=_env("NO_TASK_MODE", "read_only"),
            max_mode=_env("MAX_MODE", "auto_workspace"),
            default_isolation=_env("DEFAULT_ISOLATION", "workspace"),
            secret_route=_env("SECRET_ROUTE", ""),
            bearer_token=_env("BEARER_TOKEN", ""),
            allow_ts_net=_env_bool("ALLOW_TS_NET", True),
            shell=_env("SHELL", ""),
            max_output_chars=_env_int("MAX_OUTPUT_CHARS", 30000),
            max_read_chars=_env_int("MAX_READ_CHARS", 100000),
            rate_limit_per_min=_env_int("RATE_LIMIT_PER_MIN", 120),
            stateless_http=_env_bool("STATELESS_HTTP", True),
            json_response=_env_bool("JSON_RESPONSE", True),
            scrub_output=_env_bool("SCRUB_OUTPUT", True),
            audit_log=_env_bool("AUDIT_LOG", True),
            auto_checkpoint=_env_bool("AUTO_CHECKPOINT", True),
            auto_checkpoint_interval=_env_int("AUTO_CHECKPOINT_INTERVAL", 60),
            commit_hooks=_env_bool("COMMIT_HOOKS", False),
            arbitrary_commands=_env("ARBITRARY_COMMANDS", "ask"),
            event_sink=_env("EVENT_SINK", ""),
            event_token=_env("EVENT_TOKEN", ""),
            cockpit_port=_env_int("COCKPIT_PORT", 8849),
            auto_format=_env_bool("AUTO_FORMAT", False),
            user_hooks=_env_bool("USER_HOOKS", True),
            sandbox=_env("SANDBOX", "local"),
            sandbox_image=_env("SANDBOX_IMAGE", "python:3.12-slim"),
            sandbox_network=_env("SANDBOX_NETWORK", "none"),
            sandbox_cpus=_env("SANDBOX_CPUS", "2"),
            sandbox_memory=_env("SANDBOX_MEMORY", "2g"),
            sandbox_pids=_env_int("SANDBOX_PIDS", 512),
            sandbox_user=_env("SANDBOX_USER", ""),
            sandbox_readonly=_env_bool("SANDBOX_READONLY", False),
        )
        env_allow_raw = _env("ENV_ALLOWLIST")
        state_dir = _env("STATE_DIR")
        if state_dir:
            kwargs["state_dir"] = Path(state_dir).expanduser()
        # Workspace roots come from HARNESS_WORKSPACE_ROOTS (env) AND the
        # operator-managed roots.json in the state dir (the `harness roots` CLI),
        # merged. roots.json lets you add a folder without editing launch-cwd env.
        resolved_state = kwargs.get("state_dir") or _default_state_dir()
        env_roots = _split_list(roots_raw, sep="pathsep") if roots_raw else []
        file_roots = cls.load_extra_roots(resolved_state)
        merged_roots = env_roots + [r for r in file_roots if r not in env_roots]
        if merged_roots:
            kwargs["workspace_roots"] = [Path(p) for p in merged_roots]
        if origins_raw:
            kwargs["allowed_origins"] = _split_list(origins_raw, sep=",")
        if hosts_raw:
            kwargs["allowed_hosts"] = _split_list(hosts_raw, sep=",")

        cfg = cls(**kwargs)
        if globs_raw:
            cfg.secret_globs = list(DEFAULT_SECRET_GLOBS) + _split_list(globs_raw, sep=",")
        if env_allow_raw:
            cfg.env_allowlist = _split_list(env_allow_raw, sep=",")
        # MCP federation servers: env JSON wins, else a file in the state dir.
        import json as _json

        servers_raw = _env("MCP_SERVERS")
        if servers_raw:
            try:
                cfg.mcp_servers = _json.loads(servers_raw)
            except ValueError:
                cfg.mcp_servers = {}
        else:
            f = cfg.state_dir / "mcp_servers.json"
            if f.exists():
                try:
                    cfg.mcp_servers = _json.loads(f.read_text(encoding="utf-8"))
                except (ValueError, OSError):
                    cfg.mcp_servers = {}
        return cfg

    def redacted(self) -> dict:
        """Config summary safe to print (no secret route / token values)."""
        return {
            "host": self.host,
            "port": self.port,
            "mode": self.mode,
            "no_task_mode": self.no_task_mode,
            "max_mode": self.max_mode,
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
            "scrub_output": self.scrub_output,
            "audit_log": self.audit_log,
            "sandbox": self.sandbox + (f" ({self.sandbox_image})" if self.sandbox == "docker" else ""),
        }
