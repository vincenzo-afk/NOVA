"""Lightweight FastAPI wrapper for OmniParser."""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import uvicorn

app = FastAPI()
omniparser = None
omniparser_lock = threading.Lock()
AUTH_TOKEN = None  # Set via --auth-token argument


class ParseRequest(BaseModel):
    base64_image: str


def _resolve_paths(repo_dir: str | None, som_path: str | None, caption_path: str | None) -> tuple[str | None, str | None]:
    if not repo_dir:
        return som_path, caption_path
    repo = Path(repo_dir).expanduser().resolve()
    default_som = repo / "weights" / "icon_detect" / "model.pt"
    default_caption = repo / "weights" / "icon_caption_florence"
    return (
        som_path or str(default_som),
        caption_path or str(default_caption),
    )


def _get_omniparser(config: dict) -> object:
    global omniparser
    if omniparser is None:
        with omniparser_lock:
            if omniparser is None:
                repo_dir = config.get("repo_dir")
                if repo_dir:
                    repo_path = Path(repo_dir).expanduser().resolve()
                    if str(repo_path) not in sys.path:
                        sys.path.insert(0, str(repo_path))
                from util.omniparser import Omniparser

                omniparser = Omniparser(config)
    return omniparser


@app.get("/health")
async def health(request: Request):
    if AUTH_TOKEN:
        query_token = request.query_params.get("token", "")
        if query_token != AUTH_TOKEN:
            raise HTTPException(status_code=401, detail="Invalid or missing authentication token")
    return {"status": "ok"}


@app.get("/probe/")
async def probe(request: Request):
    if AUTH_TOKEN:
        query_token = request.query_params.get("token", "")
        if query_token != AUTH_TOKEN:
            raise HTTPException(status_code=401, detail="Invalid or missing authentication token")
    return {"message": "OmniParser API ready"}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Validate authentication token for all endpoints except health/probe."""
    if AUTH_TOKEN and request.url.path not in ["/health", "/probe/"]:
        auth_header = request.headers.get("Authorization")
        if not auth_header or auth_header != f"Bearer {AUTH_TOKEN}":
            raise HTTPException(status_code=401, detail="Invalid or missing authentication token")
    return await call_next(request)


@app.post("/parse/")
async def parse(parse_request: ParseRequest):
    start = time.time()
    parser = _get_omniparser(app.state.config)
    dino_labled_img, parsed_content_list = parser.parse(parse_request.base64_image)
    latency = time.time() - start
    return {
        "som_image_base64": dino_labled_img,
        "parsed_content_list": parsed_content_list,
        "latency": latency,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="OmniParser API")
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--repo-dir", type=str, default="")
    parser.add_argument("--som-model-path", type=str, default="")
    parser.add_argument("--caption-model-path", type=str, default="")
    parser.add_argument("--caption-model-name", type=str, default="florence2")
    parser.add_argument("--device", type=str, default="cpu")
    parser.add_argument("--BOX_TRESHOLD", type=float, default=0.05)
    parser.add_argument("--auth-token", type=str, default="", help="Authentication token for API security")
    args = parser.parse_args()
    
    # Set global auth token
    global AUTH_TOKEN
    AUTH_TOKEN = args.auth_token if args.auth_token else os.environ.get("OMNIPARSER_AUTH_TOKEN") or None

    som_path, caption_path = _resolve_paths(args.repo_dir, args.som_model_path or None, args.caption_model_path or None)

    app.state.config = {
        "som_model_path": som_path,
        "caption_model_name": args.caption_model_name,
        "caption_model_path": caption_path,
        "device": args.device,
        "BOX_TRESHOLD": args.BOX_TRESHOLD,
        "repo_dir": args.repo_dir or None,
    }

    uvicorn.run(app, host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
