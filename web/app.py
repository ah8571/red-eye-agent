from fastapi import FastAPI, Request, Form, Depends, Response, status, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import yaml
from pathlib import Path
import os
import tempfile
from datetime import datetime
from pydantic import BaseModel
from collections import deque

from web.auth import (
    init_users_db,
    register_user,
    verify_user,
    create_session_token,
    verify_session_token
)
from web.config import (
    SECRET_KEY,
    ALLOWED_EMAILS,
    SESSION_MAX_AGE,
    AGENT_CONFIG_PATH,
    AGENT_CHECKLIST_PATH,
    AGENT_LOG_DIR
)
from agent.process import RunManager
from agent.checklist import parse_markdown, parse_yaml_text
from web.github_repos import merge_with_config, get_repo_defaults

app = FastAPI(title="Red-Eye Agent Dashboard")


class StartRunRequest(BaseModel):
    repo: str
    input_text: str
    format: str = "quick"

templates = Jinja2Templates(directory="web/templates")

# Serve files from web/public (favicon, images, etc.)
app.mount("/public", StaticFiles(directory="web/public"), name="public")


class NotAuthenticated(Exception):
    pass


def get_current_user(request: Request):
    """Dependency to get current user from session cookie."""
    session_token = request.cookies.get("session")
    if not session_token:
        raise NotAuthenticated()
    email = verify_session_token(session_token)
    if not email:
        raise NotAuthenticated()
    return email


@app.exception_handler(NotAuthenticated)
async def not_authenticated_handler(request: Request, exc: NotAuthenticated):
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("session")
    return response


@app.on_event("startup")
async def startup_event():
    """Initialize users database on startup."""
    init_users_db()


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Render login form."""
    return templates.TemplateResponse(request, "login.html")


@app.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...)
):
    """Process login form."""
    if verify_user(email, password):
        session_token = create_session_token(email)
        response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        response.set_cookie(
            key="session",
            value=session_token,
            max_age=SESSION_MAX_AGE,
            httponly=True,
            secure=False,  # Set to True in production with HTTPS
            samesite="lax"
        )
        return response
    else:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid email or password"},
            status_code=status.HTTP_401_UNAUTHORIZED
        )


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    """Render registration form."""
    return templates.TemplateResponse(request, "register.html")


@app.post("/register")
async def register_submit(
    email: str = Form(...),
    password: str = Form(...)
):
    """Process registration form."""
    success = register_user(email, password)
    if success:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    else:
        # Could be email not allowed or already registered
        return RedirectResponse(url="/register", status_code=status.HTTP_302_FOUND)


@app.get("/logout")
async def logout(response: Response):
    """Clear session cookie and redirect to login."""
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("session")
    return response


@app.get("/", response_class=HTMLResponse)
async def root_redirect():
    """Redirect root to command center."""
    return RedirectResponse(url="/command-center", status_code=302)


@app.get("/checklist", response_class=HTMLResponse)
async def checklist_page(
    request: Request,
    user_email: str = Depends(get_current_user)
):
    """Display checklist tasks in a table."""
    tasks = []
    checklist_raw = ""
    if AGENT_CHECKLIST_PATH.exists():
        with open(AGENT_CHECKLIST_PATH, 'r') as f:
            checklist_raw = f.read()
        try:
            checklist = yaml.safe_load(checklist_raw)
            tasks = checklist.get('tasks', [])
        except yaml.YAMLError:
            tasks = []
    else:
        checklist_raw = ""
    
    # Process tasks for display
    for task in tasks:
        # Truncate description to 80 chars
        desc = task.get('description', '')
        if len(desc) > 80:
            task['description_display'] = desc[:80] + '...'
        else:
            task['description_display'] = desc
        
        # Determine status color
        status = task.get('status', 'pending').lower()
        if status in ('completed', 'done'):
            task['status_color'] = 'success'
        elif status == 'failed':
            task['status_color'] = 'danger'
        else:
            task['status_color'] = 'warning'
    
    error = request.query_params.get("error", "")
    return templates.TemplateResponse(
        request,
        "checklist.html",
        {
            "user_email": user_email,
            "tasks": tasks,
            "checklist_raw": checklist_raw,
            "error": error
        }
    )


@app.get("/runs", response_class=HTMLResponse)
async def runs_redirect():
    """Run history is now part of command center."""
    return RedirectResponse(url="/command-center", status_code=302)


@app.get("/runs/{filename}", response_class=HTMLResponse)
async def run_detail(
    request: Request,
    filename: str,
    user_email: str = Depends(get_current_user)
):
    """Display contents of a specific log file."""
    # Validate filename to prevent path traversal
    if '..' in filename or '/' in filename or '\\' in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    log_path = AGENT_LOG_DIR / filename
    if not log_path.exists() or not log_path.is_file():
        raise HTTPException(status_code=404, detail="Log file not found")
    
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        content = "Unable to read log file"
    
    return templates.TemplateResponse(
        request,
        "run_detail.html",
        {
            "user_email": user_email,
            "filename": filename,
            "content": content
        }
    )


@app.get("/command-center", response_class=HTMLResponse)
async def command_center(
    request: Request,
    user_email: str = Depends(get_current_user)
):
    """All-in-one command center."""
    # Load repos from config.yaml
    config_repos = []
    if AGENT_CONFIG_PATH.exists():
        with open(AGENT_CONFIG_PATH, 'r') as f:
            config = yaml.safe_load(f)
            config_repos = config.get('repos', [])

    connected_repo_names = sorted([r['name'] for r in config_repos])
    all_repo_names = merge_with_config(config_repos)

    # Active/all runs
    manager = RunManager()
    active_runs = manager.list_runs()

    # Run log files (history)
    log_files = []
    if AGENT_LOG_DIR.exists():
        for file_path in AGENT_LOG_DIR.iterdir():
            if file_path.is_file() and file_path.name.startswith('run_'):
                name = file_path.name
                ts = name.replace('run_', '').replace('.log', '')
                display = ts[:8] + ' ' + ts[9:] if len(ts) > 8 else ts
                log_files.append({
                    'filename': name,
                    'display_name': name,
                    'timestamp': display,
                    'modified': file_path.stat().st_mtime
                })
        log_files.sort(key=lambda x: x['modified'], reverse=True)

    # Checklist data
    tasks = []
    checklist_raw = ""
    if AGENT_CHECKLIST_PATH.exists():
        with open(AGENT_CHECKLIST_PATH, 'r') as f:
            checklist_raw = f.read()
        try:
            parsed = yaml.safe_load(checklist_raw)
            tasks = parsed.get('tasks', []) if parsed else []
        except yaml.YAMLError:
            tasks = []

    checklist_error = request.query_params.get("error", "")

    return templates.TemplateResponse(
        request,
        "command_center.html",
        {
            "user_email": user_email,
            "repos": connected_repo_names,
            "all_repos": all_repo_names,
            "active_runs": active_runs,
            "log_files": log_files,
            "tasks": tasks,
            "checklist_raw": checklist_raw,
            "checklist_error": checklist_error,
        }
    )


@app.get("/command-center/{run_id}/logs", response_class=HTMLResponse)
async def run_logs_page(
    request: Request,
    run_id: str,
    user_email: str = Depends(get_current_user)
):
    """Page showing live logs for a specific run."""
    # Validate run_id to prevent path traversal
    if '..' in run_id or '/' in run_id or '\\' in run_id:
        raise HTTPException(status_code=400, detail="Invalid run ID")
    
    # Verify run exists via RunManager
    try:
        manager = RunManager()
        status = manager.get_status(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Run not found")
    
    return templates.TemplateResponse(
        request,
        "run_logs.html",
        {
            "user_email": user_email,
            "run_id": run_id
        }
    )


@app.get("/command-center/help", response_class=HTMLResponse)
async def command_center_help(
    request: Request,
    user_email: str = Depends(get_current_user)
):
    """Display help documentation for input formats."""
    return templates.TemplateResponse(
        request,
        "import_help.html",
        {
            "user_email": user_email
        }
    )


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    user_email: str = Depends(get_current_user)
):
    """Settings page."""
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "user_email": user_email
        }
    )


@app.post("/checklist/save")
async def checklist_save(
    request: Request,
    tasks_yaml: str = Form(...),
    user_email: str = Depends(get_current_user)
):
    """Save checklist YAML after validation."""
    try:
        parsed = yaml.safe_load(tasks_yaml)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("tasks"), list):
            raise ValueError("YAML must have a 'tasks' key that is a list")
    except Exception as e:
        # Redirect with error query parameter
        return RedirectResponse(url="/command-center?error=1", status_code=status.HTTP_302_FOUND)
    
    # Write to file
    try:
        with open(AGENT_CHECKLIST_PATH, 'w') as f:
            f.write(tasks_yaml)
    except Exception as e:
        # If file write fails, also redirect with error
        return RedirectResponse(url="/command-center?error=1", status_code=status.HTTP_302_FOUND)
    
    return RedirectResponse(url="/command-center", status_code=status.HTTP_302_FOUND)


@app.post("/api/runs/preview")
async def preview_run(
    request: StartRunRequest,
    user_email: str = Depends(get_current_user)
):
    """Preview parsed tasks without starting a run."""
    # Load repos from config.yaml
    if not AGENT_CONFIG_PATH.exists():
        raise HTTPException(status_code=500, detail="Configuration not found")
    
    with open(AGENT_CONFIG_PATH, 'r') as f:
        config = yaml.safe_load(f)
    repos = config.get('repos', [])
    
    # Extract repo names for validation
    repo_names = [r['name'] for r in repos]
    
    # Validate repo
    if request.repo not in repo_names:
        raise HTTPException(status_code=400, detail=f"Repo '{request.repo}' not in configured repos")
    
    # Validate format
    if request.format not in ("quick", "markdown", "yaml"):
        raise HTTPException(status_code=400, detail="Invalid format")
    
    # Build checklist dict based on format
    try:
        if request.format == "quick":
            # Split input_text by newlines, filter empty lines
            lines = [line.strip() for line in request.input_text.splitlines() if line.strip()]
            checklist = {
                "tasks": [
                    {
                        "id": i + 1,
                        "repo": request.repo,
                        "description": desc,
                        "status": "pending",
                        "context_files": []
                    }
                    for i, desc in enumerate(lines)
                ]
            }
        elif request.format == "markdown":
            checklist = parse_markdown(request.input_text, request.repo)
        else:  # yaml
            checklist = parse_yaml_text(request.input_text)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    
    # Return tasks preview
    tasks = checklist.get("tasks", [])
    # Ensure each task has id, description, context_files
    for task in tasks:
        task.setdefault("id", "")
        task.setdefault("description", "")
        task.setdefault("context_files", [])
    
    return JSONResponse(
        status_code=200,
        content={"tasks": tasks, "count": len(tasks)}
    )


@app.post("/api/runs/start")
async def start_run(
    request: StartRunRequest,
    user_email: str = Depends(get_current_user)
):
    """Start a new run with given repo and tasks."""
    # Load repos from config.yaml
    if not AGENT_CONFIG_PATH.exists():
        raise HTTPException(status_code=500, detail="Configuration not found")
    
    with open(AGENT_CONFIG_PATH, 'r') as f:
        config = yaml.safe_load(f)
    repos = config.get('repos', [])
    
    # Extract repo names for validation
    repo_names = [r['name'] for r in repos]

    # If repo not in config.yaml, auto-register it using GitHub API defaults
    if request.repo not in repo_names:
        defaults = get_repo_defaults(request.repo)
        if defaults is None:
            raise HTTPException(status_code=400, detail=f"Repo '{request.repo}' not found — check your GitHub PAT has access")
        repos.append(defaults)
        config['repos'] = repos
        with open(AGENT_CONFIG_PATH, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    # Validate format
    if request.format not in ("quick", "markdown", "yaml"):
        raise HTTPException(status_code=400, detail="Invalid format")

    # Build checklist dict based on format
    try:
        if request.format == "quick":
            # Split input_text by newlines, filter empty lines
            lines = [line.strip() for line in request.input_text.splitlines() if line.strip()]
            checklist = {
                "tasks": [
                    {
                        "id": i + 1,
                        "repo": request.repo,
                        "description": desc,
                        "status": "pending",
                        "context_files": []
                    }
                    for i, desc in enumerate(lines)
                ]
            }
        elif request.format == "markdown":
            checklist = parse_markdown(request.input_text, request.repo)
        else:  # yaml
            checklist = parse_yaml_text(request.input_text)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})

    # Generate run_id
    run_id = f"{request.repo}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    
    # Write to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp:
        yaml.dump(checklist, tmp)
        temp_checklist_path = tmp.name
    
    try:
        # Start run via RunManager
        manager = RunManager()
        manager.start_run(run_id, request.repo, temp_checklist_path)
    except Exception as e:
        # Clean up temp file on error
        os.unlink(temp_checklist_path)
        raise HTTPException(status_code=500, detail=f"Failed to start run: {e}")
    
    # Temp file will be cleaned up by the subprocess or after copy
    # We could schedule cleanup but RunManager copies it.
    
    return JSONResponse(
        status_code=200,
        content={"run_id": run_id, "status": "started"}
    )


@app.post("/api/runs/upload")
async def upload_run(
    repo: str = Form(...),
    file: UploadFile = File(...),
    user_email: str = Depends(get_current_user)
):
    """Start a new run from an uploaded file."""
    # Load repos from config.yaml
    if not AGENT_CONFIG_PATH.exists():
        raise HTTPException(status_code=500, detail="Configuration not found")
    
    with open(AGENT_CONFIG_PATH, 'r') as f:
        config = yaml.safe_load(f)
    repos = config.get('repos', [])
    
    # Extract repo names for validation
    repo_names = [r['name'] for r in repos]

    # If repo not in config.yaml, auto-register it using GitHub API defaults
    if repo not in repo_names:
        defaults = get_repo_defaults(repo)
        if defaults is None:
            raise HTTPException(status_code=400, detail=f"Repo '{repo}' not found — check your GitHub PAT has access")
        repos.append(defaults)
        config['repos'] = repos
        with open(AGENT_CONFIG_PATH, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
    
    # Detect format by file extension
    filename = file.filename.lower()
    if filename.endswith('.md'):
        format = "markdown"
    elif filename.endswith('.yaml') or filename.endswith('.yml'):
        format = "yaml"
    else:
        raise HTTPException(status_code=400, detail="Unsupported file type")
    
    # Read file content as text
    try:
        content = await file.read()
        input_text = content.decode('utf-8')
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {e}")
    
    # Build checklist dict based on format
    try:
        if format == "markdown":
            checklist = parse_markdown(input_text, repo)
        else:  # yaml
            checklist = parse_yaml_text(input_text)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    
    # Generate run_id
    run_id = f"{repo}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    
    # Write to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp:
        yaml.dump(checklist, tmp)
        temp_checklist_path = tmp.name
    
    try:
        # Start run via RunManager
        manager = RunManager()
        manager.start_run(run_id, repo, temp_checklist_path)
    except Exception as e:
        # Clean up temp file on error
        os.unlink(temp_checklist_path)
        raise HTTPException(status_code=500, detail=f"Failed to start run: {e}")
    
    return JSONResponse(
        status_code=200,
        content={"run_id": run_id, "status": "started"}
    )


@app.post("/api/repos/connect")
async def connect_repo(
    request: Request,
    user_email: str = Depends(get_current_user)
):
    """Register a repo in config.yaml without starting a run."""
    body = await request.json()
    repo_name = body.get("repo", "").strip()
    if not repo_name:
        raise HTTPException(status_code=400, detail="repo is required")

    # Load current config
    if not AGENT_CONFIG_PATH.exists():
        config = {"repos": []}
    else:
        with open(AGENT_CONFIG_PATH, 'r') as f:
            config = yaml.safe_load(f) or {"repos": []}

    existing_names = [r['name'] for r in config.get('repos', [])]
    if repo_name not in existing_names:
        defaults = get_repo_defaults(repo_name)
        config.setdefault('repos', []).append(defaults)
        with open(AGENT_CONFIG_PATH, 'w') as f:
            yaml.dump(config, f, default_flow_style=False)

    return JSONResponse(status_code=200, content={"status": "connected", "repo": repo_name})


@app.post("/api/runs/{run_id}/stop")
async def stop_run(
    run_id: str,
    user_email: str = Depends(get_current_user)
):
    """Stop a running process."""
    try:
        manager = RunManager()
        success = manager.stop_run(run_id)
        if success:
            return JSONResponse(
                status_code=200,
                content={"run_id": run_id, "status": "stopped"}
            )
        else:
            # stop_run returns False on failure (e.g., permission error)
            # but still raises KeyError if run not found, caught below.
            raise HTTPException(status_code=500, detail="Failed to stop run")
    except KeyError:
        raise HTTPException(status_code=404, detail="Run not found")


@app.get("/api/runs")
async def get_runs(
    user_email: str = Depends(get_current_user)
):
    """Return JSON list of all runs."""
    manager = RunManager()
    runs = manager.list_runs()
    return JSONResponse(content=runs)


@app.get("/api/runs/{run_id}/status")
async def get_run_status(
    run_id: str,
    user_email: str = Depends(get_current_user)
):
    """Return JSON status of a specific run."""
    try:
        manager = RunManager()
        status = manager.get_status(run_id)
        return JSONResponse(content=status)
    except KeyError:
        raise HTTPException(status_code=404, detail="Run not found")


@app.get("/api/runs/{run_id}/logs")
async def get_run_logs(
    run_id: str,
    user_email: str = Depends(get_current_user)
):
    """Return last 200 lines of the run's output log."""
    try:
        manager = RunManager()
        status = manager.get_status(run_id)
        log_file_path = Path(status["log_file"])
    except KeyError:
        raise HTTPException(status_code=404, detail="Run not found")
    
    lines = []
    if log_file_path.exists() and log_file_path.is_file():
        try:
            with open(log_file_path, 'r', encoding='utf-8') as f:
                # Use deque to efficiently keep last 200 lines
                last_lines = deque(maxlen=200)
                for line in f:
                    last_lines.append(line.rstrip('\n'))
                lines = list(last_lines)
        except Exception:
            # If any error reading file, return empty lines
            lines = []
    
    return JSONResponse(content={"run_id": run_id, "lines": lines})
