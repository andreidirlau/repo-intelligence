# Repo Intelligence

A practical developer tool that fetches real data from any public GitHub repository and produces opinionated technical analysis — stack, architecture, run instructions, risks, and improvement suggestions.

---

## Why it exists

Reviewing an unfamiliar repository wastes time. You clone it, grep through files, read the README, puzzle over the folder structure, and still leave with gaps. Repo Intelligence automates that cold-start reconnaissance: it reads the files that actually matter, infers how the project is structured and how it runs, and surfaces what's missing or risky — in seconds.

---

## How it works

1. You paste a GitHub repository URL.
2. The backend fetches the repository tree and the most meaningful files (README, entry points, config files, Dockerfiles, CI workflows, infrastructure code) using the GitHub API.
3. The fetched content is passed to an LLM for structured analysis.
4. The frontend renders the result — summary, stack, architecture, run steps, risks, and suggestions.

---

## Stack

| Layer    | Technology                        |
|----------|-----------------------------------|
| Backend  | Python, FastAPI, requests         |
| LLM      | OpenAI API (`gpt-4o-mini` default)|
| Frontend | HTML, CSS, vanilla JavaScript     |
| Serving  | Uvicorn (frontend served by FastAPI) |

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/andreidirlau/repo-intelligence.git
cd repo-intelligence
```

### 2. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r backend/requirements.txt
```

### 4. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your values:

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
GITHUB_TOKEN=ghp_...        # optional, increases GitHub rate limit
```

### 5. Start the server

```bash
uvicorn backend.main:app --reload --port 8000
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

> **Note:** If you see `NotOpenSSLWarning` or other SSL/urllib3 warnings on macOS system Python, make sure you are using a virtual environment and that the pinned requirements (`urllib3<2`) are installed. The `.venv` setup in step 2 handles this automatically.

---

## Environment Variables

| Variable        | Required | Default       | Description                                     |
|-----------------|----------|---------------|-------------------------------------------------|
| `OPENAI_API_KEY`| Yes      | —             | Your OpenAI API key                             |
| `OPENAI_MODEL`  | No       | `gpt-4o-mini` | OpenAI model to use for analysis                |
| `GITHUB_TOKEN`  | No       | —             | GitHub personal access token (raises rate limit from 60 to 5000 req/hr) |

---

## API

### `GET /health`

Returns server status.

```json
{ "status": "ok", "service": "repo-intelligence" }
```

### `POST /analyze`

**Request:**

```json
{ "repo_url": "https://github.com/owner/repo" }
```

**Response:**

```json
{
  "project_summary": "...",
  "tech_stack": ["FastAPI", "Python", "Docker"],
  "architecture": "...",
  "key_components": [{ "name": "backend/main.py", "role": "..." }],
  "how_to_run": ["pip install -r requirements.txt", "uvicorn main:app --reload"],
  "risks": ["No Dockerfile present — deployment is not standardized"],
  "improvement_suggestions": ["Add .env.example to document required variables"],
  "important_files": ["README.md", "backend/main.py", "requirements.txt"]
}
```

---

## Example repository URLs

```
https://github.com/andreidirlau/ai-log-analyzer
https://github.com/andreidirlau/infra-docs-generator
https://github.com/tiangolo/fastapi
https://github.com/pallets/flask
```

---

## Project structure

```
repo-intelligence/
├── backend/
│   ├── __init__.py
│   ├── main.py            # FastAPI app, routes, static file serving
│   ├── github_client.py   # GitHub API fetching and file selection
│   ├── analyzer.py        # LLM analysis and structured output
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── styles.css
│   └── script.js
├── .env.example
├── .gitignore
├── LICENSE
└── README.md
```

---

## Contributing

1. Fork the repository.
2. Create a feature branch: `git checkout -b feature/my-change`
3. Make your changes and test them locally.
4. Open a pull request with a clear description of what changed and why.

Issues and suggestions are welcome via GitHub Issues.

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

## Author

Built by [Andrei Dirlau](https://github.com/andreidirlau).
