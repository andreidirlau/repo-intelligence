import os
import json
import re
from openai import AsyncOpenAI

SYSTEM_PROMPT = """You are a senior software engineer writing a technical review of a GitHub repository for another engineer who is about to work on it.

Your output must read like a real code review: grounded in the files provided, specific, and honest about the limits of what you can determine.

━━━ RULES ━━━

RULE 1 — CITE FILES IN EVERY SECTION
Every claim must reference the file it comes from.
  BAD:  "The app uses FastAPI."
  GOOD: "backend/main.py imports FastAPI and registers two routes: GET /health and POST /analyze."

RULE 2 — DO NOT RESTATE THE README OR DESCRIPTION
The engineer can read those. Add interpretation, not transcription.
  BAD:  "According to the README, this tool analyzes repositories."
  GOOD: "The POST /analyze route in backend/main.py fetches up to 20 files from the GitHub API tree and passes them to the OpenAI chat completions endpoint — the README description matches the implementation."

RULE 3 — USE UNCERTAINTY LANGUAGE FOR INFERENCES
When a conclusion is based on indirect evidence, mark it as such.
Use: "appears to", "likely", "suggests", "probably", "based on X"
  BAD:  "The app is deployed on Heroku."
  GOOD: "No deployment config was found — the app likely runs as a local service or relies on manual server setup."

RULE 4 — TECH STACK: ONLY WHAT IS DIRECTLY EVIDENCED
Include a technology only if you can verify it from an import statement, a package file, or a config file present in the fetched files.
  If requirements.txt lists fastapi → include FastAPI.
  If no Dockerfile was fetched → do NOT include Docker.
  If uncertain → exclude. Never infer from repo name or description alone.

RULE 5 — ARCHITECTURE: DESCRIBE THE ACTUAL STRUCTURE
Name entrypoints, describe how modules relate, state whether it is a monolith, multi-service, or hybrid.
  BAD:  "The project has a frontend and a backend."
  GOOD: "Single-process FastAPI server (backend/main.py) handles both API routes and static file serving. The frontend (frontend/) is served via a StaticFiles mount at / — no reverse proxy or separate frontend process. github_client.py and analyzer.py are plain modules imported by main.py, not separate services."

RULE 6 — RISKS: EVIDENCE → CONSEQUENCE
Each risk must state what was observed and what problem it creates.
Format: "[what you saw in file X] → [concrete consequence]"
  BAD:  "No tests found."
  GOOD: "No tests/ directory or test_*.py files present → regressions will surface in production rather than in CI."
  BAD:  "API key handling could be improved."
  GOOD: "OPENAI_API_KEY is validated on each request in analyzer.py rather than at server startup → a misconfigured deployment silently accepts traffic and fails only when POST /analyze is first called."

RULE 7 — IMPROVEMENTS: FILE-SPECIFIC AND ACTIONABLE
Name the file. Describe the exact change. No generic advice.
  BAD:  "Improve error handling."
  GOOD: "github_client.py._fetch_files() uses a bare except Exception: continue — add structured logging so partial fetch failures are observable without rerunning the full analysis."
  BAD:  "Add documentation."
  GOOD: "FastAPI auto-generates interactive docs at /docs; add a one-line note to the README so reviewers know they can test POST /analyze without writing curl commands."

━━━ OUTPUT FORMAT ━━━

Return ONLY a valid JSON object. No markdown, no code fences, no text outside the JSON.

{
  "project_summary": "2-4 sentences. What the app does technically, citing specific files. Use uncertainty language for anything inferred from partial data.",
  "tech_stack": ["only technologies directly evidenced by imports or package files in the fetched content"],
  "architecture": "Structural description: actual file layout, entrypoints, how backend and frontend are separated, deployment model if determinable from the files.",
  "key_components": [
    {"name": "actual/file/path.py", "role": "what this file specifically does — not just its file type or a restatement of its name"}
  ],
  "how_to_run": [
    "Concrete step derived from an actual file — e.g. if requirements.txt exists: pip install -r requirements.txt",
    "If .env.example exists: cp .env.example .env, then fill in required variables"
  ],
  "risks": [
    "[observed in specific file] → [concrete consequence]"
  ],
  "improvement_suggestions": [
    "[specific file] — [exact change to make and why]"
  ],
  "important_files": ["list every file path from the FILE CONTENTS section above — all provided files were part of this analysis"]
}"""


_NOTABLE_ABSENT = [
    ("Dockerfile",              "no container build config"),
    ("docker-compose.yml",      "no multi-container orchestration config"),
    ("docker-compose.yaml",     None),   # alias — suppress if already noted
    (".github/workflows",       "no CI/CD pipeline"),
    ("requirements.txt",        "no Python dependency manifest"),
    ("package.json",            "no Node dependency manifest"),
    ("pyproject.toml",          "no pyproject config"),
    (".env.example",            "no documented environment variables"),
    ("Makefile",                "no Makefile"),
    ("tests/",                  "no tests directory"),
    ("test_",                   "no test files detected"),
]


def _absent_flags(files: list[dict]) -> list[str]:
    fetched_paths = {f["path"] for f in files}
    fetched_str = "\n".join(fetched_paths)

    flags = []
    docker_noted = False
    for token, label in _NOTABLE_ABSENT:
        if label is None:
            continue
        if token == "docker-compose.yaml" and docker_noted:
            continue
        present = any(
            token in p or p.startswith(token)
            for p in fetched_paths
        ) or (token in fetched_str)
        if not present:
            flags.append(f"  - {token} → NOT FOUND ({label})")
            if "docker-compose" in token:
                docker_noted = True
    return flags


def _build_user_message(repo_data: dict) -> str:
    meta = repo_data["metadata"]
    files = repo_data["files"]

    lines = [
        f"Repository: {repo_data['owner']}/{repo_data['repo']}",
        f"GitHub description: {meta['description'] or 'None provided'}",
        f"Primary language (GitHub): {meta['language'] or 'Unknown'}",
        f"Topics: {', '.join(meta['topics']) if meta['topics'] else 'None'}",
        f"Stars: {meta['stars']}  |  Forks: {meta['forks']}  |  Open issues: {meta['open_issues']}",
        f"License: {meta['license'] or 'None specified'}",
        f"Repository size: {meta['size_kb']} KB",
        "",
    ]

    # File manifest — gives the model an inventory before reading content
    lines.append(f"=== FILES FETCHED ({len(files)}) ===")
    for f in files:
        lines.append(f"  {f['path']}")
    lines.append("")

    # Notable absences — helps surface risks without hallucination
    absent = _absent_flags(files)
    if absent:
        lines.append("=== NOTABLE ABSENCES (not found in repository tree) ===")
        lines.extend(absent)
        lines.append("")

    lines.append("=== FILE CONTENTS ===")
    lines.append("")

    for f in files:
        lines.append(f"--- {f['path']} ---")
        lines.append(f["content"].strip())
        lines.append("")

    if not files:
        lines.append("No meaningful files were accessible in this repository.")

    return "\n".join(lines)


def _parse_response(text: str) -> dict:
    text = text.strip()

    # Strip markdown code fences if model added them despite instructions
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)

    parsed = json.loads(text)

    # Ensure all required keys are present with safe defaults
    defaults: dict = {
        "project_summary": "",
        "tech_stack": [],
        "architecture": "",
        "key_components": [],
        "how_to_run": [],
        "risks": [],
        "improvement_suggestions": [],
        "important_files": [],
    }
    for key, default in defaults.items():
        if key not in parsed:
            parsed[key] = default

    return parsed


async def analyze_repository(repo_data: dict) -> dict:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY is not set. Add it to your .env file or environment."
        )

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    client = AsyncOpenAI(api_key=api_key)

    user_message = _build_user_message(repo_data)

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
    except Exception as e:
        raise RuntimeError(f"OpenAI API request failed: {e}") from e

    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("OpenAI returned an empty response.")

    try:
        return _parse_response(content)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse model output as JSON: {e}") from e
