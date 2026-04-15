from fastapi import FastAPI, Request, Form, Depends, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import yaml
from pathlib import Path

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
    AGENT_CHECKLIST_PATH
)

app = FastAPI(title="Red-Eye Agent Dashboard")

templates = Jinja2Templates(directory="web/templates")

# Mount static files if needed
# app.mount("/static", StaticFiles(directory="web/static"), name="static")


def get_current_user(request: Request, response: Response):
    """Dependency to get current user from session cookie.
    If invalid, redirects to /login."""
    session_token = request.cookies.get("session")
    if not session_token:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    
    email = verify_session_token(session_token)
    if not email:
        # Clear invalid cookie
        response.delete_cookie("session")
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    
    return email


@app.on_event("startup")
async def startup_event():
    """Initialize users database on startup."""
    init_users_db()


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Render login form."""
    return templates.TemplateResponse("login.html", {"request": request})


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
            "login.html",
            {"request": request, "error": "Invalid email or password"},
            status_code=status.HTTP_401_UNAUTHORIZED
        )


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    """Render registration form."""
    return templates.TemplateResponse("register.html", {"request": request})


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
    task_counts = {"pending": 0, "completed": 0, "failed": 0}
    if AGENT_CHECKLIST_PATH.exists():
        with open(AGENT_CHECKLIST_PATH, 'r') as f:
            checklist = yaml.safe_load(f)
            tasks = checklist.get('tasks', [])
            for task in tasks:
                status = task.get('status', 'pending').lower()
                if status in task_counts:
                    task_counts[status] += 1
                else:
                    task_counts[status] = 1
    
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user_email": user_email,
            "repos": repos,
            "task_counts": task_counts
        }
    )
