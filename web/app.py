from fastapi import FastAPI, Request, Form, Depends, Response, status, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import yaml
from pathlib import Path
import os

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

app = FastAPI(title="Red-Eye Agent Dashboard")

templates = Jinja2Templates(directory="web/templates")

# Mount static files if needed
# app.mount("/static", StaticFiles(directory="web/static"), name="static")


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
async def dashboard(
    request: Request,
    user_email: str = Depends(get_current_user)
):
    """Dashboard page showing repos and task counts."""
    # Load repos from config.yaml
    repos = []
    if AGENT_CONFIG_PATH.exists():
        with open(AGENT_CONFIG_PATH, 'r') as f:
            config = yaml.safe_load(f)
            repos = config.get('repos', [])
    
    # Load task counts from checklist.yaml
    task_counts = {"pending": 0, "done": 0, "failed": 0, "total": 0}
    if AGENT_CHECKLIST_PATH.exists():
        with open(AGENT_CHECKLIST_PATH, 'r') as f:
            checklist = yaml.safe_load(f)
            task_list = checklist.get('tasks', [])
            task_counts["total"] = len(task_list)
            for task in task_list:
                s = task.get('status', 'pending').lower()
                if s == 'done':
                    task_counts['done'] += 1
                elif s in task_counts:
                    task_counts[s] += 1

    # Recent runs from log directory
    recent_runs = []
    if AGENT_LOG_DIR.exists():
        for f in sorted(AGENT_LOG_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:5]:
            if f.is_file():
                recent_runs.append({"filename": f.name, "date": f.name.replace("run_", "").replace(".log", "")})
    
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user_email": user_email,
            "repos": repos,
            "tasks": task_counts,
            "recent_runs": recent_runs
        }
    )


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
async def runs_list(
    request: Request,
    user_email: str = Depends(get_current_user)
):
    """List all run log files sorted newest first."""
    if not AGENT_LOG_DIR.exists():
        AGENT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    
    log_files = []
    for file_path in AGENT_LOG_DIR.iterdir():
        if file_path.is_file() and file_path.name.startswith('run_'):
            name = file_path.name
            # Parse timestamp from filename like run_20260415_234820.log
            ts = name.replace('run_', '').replace('.log', '')
            display = ts[:8] + ' ' + ts[9:] if len(ts) > 8 else ts
            log_files.append({
                'filename': name,
                'display_name': name,
                'timestamp': display,
                'modified': file_path.stat().st_mtime
            })
    
    # Sort by modified time descending (newest first)
    log_files.sort(key=lambda x: x['modified'], reverse=True)
    
    return templates.TemplateResponse(
        request,
        "runs.html",
        {
            "user_email": user_email,
            "log_files": log_files
        }
    )


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
        return RedirectResponse(url="/checklist?error=1", status_code=status.HTTP_302_FOUND)
    
    # Write to file
    try:
        with open(AGENT_CHECKLIST_PATH, 'w') as f:
            f.write(tasks_yaml)
    except Exception as e:
        # If file write fails, also redirect with error
        return RedirectResponse(url="/checklist?error=1", status_code=status.HTTP_302_FOUND)
    
    return RedirectResponse(url="/checklist", status_code=status.HTTP_302_FOUND)
