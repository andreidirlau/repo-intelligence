import os
import re
import base64
from typing import Optional
import requests

GITHUB_API = "https://api.github.com"
MAX_FILES = 35
MAX_TOTAL_BYTES = 200 * 1024  # 200 KB
MAX_FILE_BYTES = 50 * 1024    # 50 KB per file

# Filenames matched regardless of directory
EXACT_MEANINGFUL = frozenset([
    "README.md", "README.rst", "README",
    "requirements.txt", "Pipfile",
    "pyproject.toml", "setup.py", "setup.cfg",
    "package.json",
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
    "compose.yaml", "compose.yml",
    "Makefile",
    "main.py", "app.py", "server.py", "wsgi.py", "asgi.py",
    "index.html",
    "index.js", "app.js", "server.js",
    ".env.example", ".env.sample",
    "go.mod", "go.sum", "Cargo.toml",
    "pom.xml", "build.gradle", "build.gradle.kts",
    "tsconfig.json",
    "next.config.js", "next.config.ts",
    "vite.config.js", "vite.config.ts",
    "nginx.conf",
])

# Directories that are never meaningful
SKIP_DIRS = frozenset([
    "node_modules", ".venv", "venv", "__pycache__", ".git",
    "dist", "build", ".next", ".nuxt", "coverage",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "vendor", "bower_components", ".yarn",
])

# File extensions that are never meaningful (binary, media, compiled)
SKIP_EXTENSIONS = frozenset([
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".bmp", ".tiff",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".wasm",
    ".exe", ".dll", ".so", ".dylib", ".a", ".lib",
    ".pyc", ".pyo", ".class", ".o",
    ".mp4", ".mp3", ".avi", ".mov",
    ".pdf",
    ".map",  # source maps
])

# Exact filenames to skip (lock files, legal, meta)
SKIP_FILENAMES = frozenset([
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb",
    "Pipfile.lock", "poetry.lock", "composer.lock", "Cargo.lock",
    "LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "LICENCE.md",
    ".gitignore", ".gitattributes", ".editorconfig",
    "CHANGELOG.md", "CHANGELOG.rst", "CHANGELOG.txt",
])

# Priority scores — lower = fetched first.
# Keyed by full path OR bare filename (full path checked first).
_PRIORITY: list[tuple[str, int]] = [
    # Project overview
    ("README.md", 0), ("README.rst", 0), ("README", 0),
    (".env.example", 1), (".env.sample", 1),
    # Dependency manifests
    ("requirements.txt", 10), ("pyproject.toml", 11),
    ("package.json", 12), ("Pipfile", 13), ("go.mod", 14), ("Cargo.toml", 15),
    # Container / orchestration
    ("Dockerfile", 20), ("docker-compose.yml", 21), ("docker-compose.yaml", 21),
    ("compose.yaml", 22), ("compose.yml", 22),
    # Build / task runner
    ("Makefile", 30),
    # Known entry points by full path (highest specificity)
    ("backend/main.py", 40), ("backend/app.py", 41), ("backend/server.py", 42),
    ("backend/analyzer.py", 43), ("backend/github_client.py", 44),
    ("frontend/index.html", 50), ("frontend/script.js", 51), ("frontend/styles.css", 52),
    # Common entry points by bare filename (fallback)
    ("main.py", 45), ("app.py", 46), ("server.py", 47),
    ("index.html", 53), ("index.js", 55), ("app.js", 56), ("server.js", 57),
    # Config
    ("tsconfig.json", 60), ("nginx.conf", 61),
    ("next.config.js", 62), ("next.config.ts", 62),
    ("vite.config.js", 63), ("vite.config.ts", 63),
]
_PRIORITY_MAP: dict[str, int] = {k: v for k, v in _PRIORITY}


class GitHubError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def parse_repo_url(url: str) -> tuple[str, str]:
    url = url.strip().rstrip("/")
    patterns = [
        r"^https?://github\.com/([^/]+)/([^/?#]+?)(?:\.git)?(?:[/?#].*)?$",
        r"^github\.com/([^/]+)/([^/?#]+?)(?:\.git)?$",
        r"^([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)$",
    ]
    for pattern in patterns:
        m = re.match(pattern, url)
        if m:
            return m.group(1), m.group(2)
    raise GitHubError(
        f"Invalid GitHub URL: '{url}'. Expected format: https://github.com/owner/repo"
    )


def is_meaningful(path: str) -> bool:
    parts = path.split("/")
    filename = parts[-1]

    # ── Exclusions (evaluated first, cheapest exit) ──────────────────────

    # Any segment of the path is a known skip directory
    if any(part in SKIP_DIRS for part in parts[:-1]):
        return False

    # Extension-based exclusion
    dot = filename.rfind(".")
    ext = filename[dot:].lower() if dot > 0 else ""
    if ext in SKIP_EXTENSIONS:
        return False

    # Minified bundles
    if ".min." in filename:
        return False

    # Exact filename exclusions (lock files, legal, meta)
    if filename in SKIP_FILENAMES:
        return False

    # ── Inclusions ────────────────────────────────────────────────────────

    # Exact filename match
    if filename in EXACT_MEANINGFUL:
        return True

    # CI workflows
    if path.startswith(".github/workflows/") and ext in (".yml", ".yaml"):
        return True

    # Terraform
    if ext == ".tf":
        return True

    # Kubernetes / Helm / infra YAML
    infra_prefixes = (
        "k8s/", "kubernetes/", "helm/", "manifests/",
        "deploy/", "deployment/", "chart/", "charts/",
    )
    if any(path.startswith(p) for p in infra_prefixes) and ext in (".yml", ".yaml"):
        return True

    # Python source under common backend dirs, or at repo root
    if ext == ".py":
        if len(parts) == 1:
            return True
        top = parts[0]
        if top in ("backend", "app", "src", "api", "core", "lib",
                   "services", "utils", "models", "routes", "handlers", "middleware"):
            return True
        # Test files anywhere outside excluded dirs (already filtered above)
        if filename.startswith("test_") or filename.endswith("_test.py"):
            return True
        if "tests" in parts or "test" in parts:
            return True

    # JavaScript / TypeScript under frontend or common source dirs (max depth 3)
    if ext in (".js", ".ts", ".jsx", ".tsx"):
        top = parts[0]
        if top in ("frontend", "src", "client", "web", "ui") and len(parts) <= 3:
            return True

    # CSS / SCSS under frontend or style dirs
    if ext in (".css", ".scss", ".sass"):
        top = parts[0]
        if top in ("frontend", "src", "client", "web", "ui", "styles", "css"):
            return True

    return False


class GitHubClient:
    def __init__(self):
        token = os.getenv("GITHUB_TOKEN")
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "repo-intelligence/1.0",
        })
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def _get(self, url: str, **kwargs) -> requests.Response:
        try:
            resp = self.session.get(url, timeout=15, **kwargs)
        except requests.exceptions.ConnectionError:
            raise GitHubError("Cannot reach GitHub API. Check your network connection.", 503)
        except requests.exceptions.Timeout:
            raise GitHubError("GitHub API request timed out.", 504)

        if resp.status_code == 401:
            raise GitHubError(
                "GitHub authentication failed. Check your GITHUB_TOKEN.", 401
            )
        if resp.status_code == 403:
            remaining = resp.headers.get("X-RateLimit-Remaining", "")
            if remaining == "0" or "rate limit" in resp.text.lower():
                raise GitHubError(
                    "GitHub API rate limit exceeded. Set GITHUB_TOKEN to increase the limit.", 429
                )
            raise GitHubError(
                "Access forbidden. This repository may be private.", 403
            )
        if resp.status_code == 404:
            raise GitHubError(
                "Repository not found. Verify the URL and ensure the repository is public.", 404
            )

        resp.raise_for_status()
        return resp

    def fetch_repo(self, repo_url: str) -> dict:
        owner, repo = parse_repo_url(repo_url)
        metadata = self._fetch_metadata(owner, repo)
        tree = self._fetch_tree(owner, repo, metadata["default_branch"])
        selected = self._select_files(tree)
        files = self._fetch_files(owner, repo, selected)
        return {
            "owner": owner,
            "repo": repo,
            "url": repo_url,
            "metadata": metadata,
            "files": files,
        }

    def _fetch_metadata(self, owner: str, repo: str) -> dict:
        resp = self._get(f"{GITHUB_API}/repos/{owner}/{repo}")
        d = resp.json()
        return {
            "name": d.get("name", ""),
            "description": d.get("description") or "",
            "default_branch": d.get("default_branch", "main"),
            "language": d.get("language") or "",
            "topics": d.get("topics", []),
            "stars": d.get("stargazers_count", 0),
            "forks": d.get("forks_count", 0),
            "open_issues": d.get("open_issues_count", 0),
            "created_at": d.get("created_at", ""),
            "updated_at": d.get("updated_at", ""),
            "size_kb": d.get("size", 0),
            "has_wiki": d.get("has_wiki", False),
            "license": (d.get("license") or {}).get("name", ""),
        }

    def _fetch_tree(self, owner: str, repo: str, branch: str) -> list[dict]:
        resp = self._get(
            f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{branch}",
            params={"recursive": "1"},
        )
        data = resp.json()
        return [item for item in data.get("tree", []) if item.get("type") == "blob"]

    def _select_files(self, tree: list[dict]) -> list[dict]:
        candidates = [item for item in tree if is_meaningful(item["path"])]

        def priority(item: dict) -> int:
            path = item["path"]
            filename = path.split("/")[-1]
            # Full path wins over bare filename for specificity
            if path in _PRIORITY_MAP:
                return _PRIORITY_MAP[path]
            if filename in _PRIORITY_MAP:
                return _PRIORITY_MAP[filename]
            # CI workflows
            if path.startswith(".github/workflows/"):
                return 70
            # Test files
            if filename.startswith("test_") or filename.endswith("_test.py") or \
               "tests/" in path or "/test/" in path:
                return 75
            # Other Python / JS / TS source
            dot = filename.rfind(".")
            ext = filename[dot:].lower() if dot > 0 else ""
            if ext in (".py", ".js", ".ts", ".jsx", ".tsx", ".css", ".scss"):
                return 80
            return 90

        candidates.sort(key=priority)
        return candidates[:MAX_FILES]

    def _fetch_files(self, owner: str, repo: str, items: list[dict]) -> list[dict]:
        results = []
        total_bytes = 0

        for item in items:
            if total_bytes >= MAX_TOTAL_BYTES:
                break

            size = item.get("size", 0)
            if size > MAX_FILE_BYTES:
                continue

            path = item["path"]
            try:
                resp = self._get(f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}")
                data = resp.json()

                encoding = data.get("encoding", "")
                raw = data.get("content", "")

                if encoding == "base64":
                    try:
                        content = base64.b64decode(raw).decode("utf-8", errors="replace")
                    except Exception:
                        continue
                else:
                    content = raw

                # Skip binary files
                if "\x00" in content[:1024]:
                    continue

                content_bytes = len(content.encode("utf-8"))
                if total_bytes + content_bytes > MAX_TOTAL_BYTES:
                    available = MAX_TOTAL_BYTES - total_bytes
                    content = content[:available] + "\n... [truncated due to size limit]"

                results.append({"path": path, "content": content})
                total_bytes += len(content.encode("utf-8"))

            except GitHubError:
                continue
            except Exception:
                continue

        return results
