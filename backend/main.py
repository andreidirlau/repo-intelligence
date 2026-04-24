import os

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .github_client import GitHubClient, GitHubError
from .analyzer import analyze_repository

app = FastAPI(title="Repo Intelligence", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class AnalyzeRequest(BaseModel):
    repo_url: str


@app.get("/health")
def health():
    return {"status": "ok", "service": "repo-intelligence"}


@app.post("/analyze")
async def analyze(request: AnalyzeRequest):
    repo_url = (request.repo_url or "").strip()
    if not repo_url:
        raise HTTPException(status_code=400, detail="repo_url is required.")

    client = GitHubClient()

    try:
        repo_data = client.fetch_repo(repo_url)
    except GitHubError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch repository: {e}")

    if not repo_data["files"]:
        raise HTTPException(
            status_code=422,
            detail=(
                "No readable files were found in this repository. "
                "It may be empty, use only binary files, or have an unusual structure."
            ),
        )

    try:
        result = await analyze_repository(repo_data)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed unexpectedly: {e}")

    return result


# Serve the frontend — must be mounted last so API routes take precedence
_here = os.path.dirname(os.path.abspath(__file__))
_frontend_dir = os.path.normpath(os.path.join(_here, "..", "frontend"))
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
