from fastapi import FastAPI, Form, Response, Request, HTTPException, Depends
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import asyncio
import json
from contextlib import asynccontextmanager
from googleapiclient.discovery import build
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel
from bill import ReadBill
from gmail import Gmail
from gmail_auth import GmailAuth
from graph_plot import *
from db import get_db, SessionLocal, Base, engine
from storage import *

load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        cleanup_expired_sessions(db)
        cleanup_expired_tokens(db)
    finally:
        db.close()
    yield

app = FastAPI(lifespan=lifespan)
_progress_queues: dict[str, asyncio.Queue] = {}

templates = Jinja2Templates(directory="templates")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
KEY = os.getenv("KEY")
if not KEY:
    raise RuntimeError("KEY not set in environment variables")

app.add_middleware(
    SessionMiddleware,
    secret_key=KEY,
    session_cookie="session_id",
    max_age=86400,  # 24 hours
    same_site="lax",
    https_only=(ENVIRONMENT == "production")
)


# CORS maybe for better frontend in the future
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["http://localhost:3000"] if ENVIRONMENT == "development" else ["https://your-domain.com"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

def _push_progress(session_id: str, loop: asyncio.AbstractEventLoop, **kwargs):
    """Called from sync processing thread to send a progress event."""
    queue = _progress_queues.get(session_id)
    if queue:
        loop.call_soon_threadsafe(queue.put_nowait, kwargs)

class FormData(BaseModel):
    email: str
    subject: str | None = None
    keyword: str | None = None
    currency: str
    start_date: str
    end_date: str


async def get_current_user(request: Request, db: Session = Depends(get_db)) -> str | None:
    session_id = request.session.get("session_id")
    if not session_id:
        return None
    g_id = validate_session(db, session_id)
    return g_id


@app.get("/", response_class=HTMLResponse)
async def index_get(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        "index.html",
        {"request": request}
    )


@app.post("/")
async def handle_form(request: Request,
                      db: Session = Depends(get_db),
                      email: str = Form(...),
                      subject: str = Form(None),
                      keyword: str = Form(None),
                      currency: str = Form(...),
                      start_date: str = Form(...),
                      end_date: str = Form(...)):
    g_id = await get_current_user(request, db)
    if not all([email, start_date, end_date, currency]):
        raise HTTPException(status_code=400, detail="Missing required form fields.")

    form_data = {
        "email": email,
        "subject": subject,
        "keyword": keyword,
        "currency": currency,
        "start_date": start_date,
        "end_date": end_date,
    }

    if g_id:
        # Store form data and show loading page — SSE handles the rest
        request.session["pending_form_data"] = form_data
        return templates.TemplateResponse("loading.html", {"request": request})

    # Not logged in — go through OAuth first
    request.session["form_data"] = form_data
    return RedirectResponse("/auth/login", status_code=303)

@app.get("/auth/login")
async def login_redirect(request: Request):
    auth = GmailAuth()
    flow = auth.create_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent"
    )
    request.session["oauth_state"] = state
    return RedirectResponse(auth_url)


@app.get("/oauth2callback")
async def auth_callback(request: Request, code: str,
                        state: str = None,
                        db: Session = Depends(get_db)):
    saved_state = request.session.get("oauth_state")
    if not saved_state or saved_state != state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state.")

    try:
        auth = GmailAuth()
        auth.exchange_code(code)
        user_info = auth.get_user_db_dict()
        save_user_token(db,
                        user_info["user_id"],
                        user_info["email"],
                        user_info["token_dict"]
                        )
        session_id = create_session(db, user_info["user_id"])
        request.session["session_id"] = session_id
        form_data = request.session.pop("form_data", None)
        if form_data:
            request.session["pending_form_data"] = form_data
            return templates.TemplateResponse("loading.html", {"request": request})

        # if form_data:
        #     return await process_flow(request, auth.get_service(), form_data)
        return RedirectResponse("/", status_code=303)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OAuth Error: {str(e)}")

def _process_flow_sync(service, form_data: dict, progress_cb) -> dict:
    progress_cb(step="gmail", message="Reading emails...",
                detail=f"Searching from {form_data['email']}")
    gmail_client = Gmail(
        address=form_data["email"],
        subject=form_data.get("subject"),
        date_range=[form_data["start_date"], form_data["end_date"]],
    )
    attachments = gmail_client.search_mail(service)
    found = len(attachments) if attachments else 0
 
    progress_cb(step="extract", message="Processing invoices...",
                detail=f"Found {found} invoice(s)")
 
    def bill_progress(step, message, detail=""):
        progress_cb(step=step, message=message, detail=detail)
 
    bill_reader = ReadBill(
    attachments,
    form_data["currency"],
    range=[form_data["start_date"], form_data["end_date"]],
    parse_key=form_data.get("keyword"))
    bill_dict = bill_reader.parser(progress_cb=bill_progress)
 
    progress_cb(step="graph", message="Building graph...", detail="")
    graph = GraphPlot(bill_dict)
    graph_html = graph.get_html_graph()
 
    return {"graph_html": graph_html, "bill_dict": bill_dict}

@app.get("/progress")
async def progress_stream(request: Request, db: Session = Depends(get_db)):
    g_id = await get_current_user(request, db)
    if not g_id:
        return RedirectResponse("/auth/login", status_code=303)
 
    token_dict = load_user_token(db, g_id)
    service = GmailAuth.get_service_from_token_dict(token_dict)
    form_data = request.session.pop("pending_form_data", None)
    if not form_data:
        return RedirectResponse("/", status_code=303)
 
    session_id = request.session.get("session_id")
    queue: asyncio.Queue = asyncio.Queue()
    _progress_queues[session_id] = queue
    loop = asyncio.get_event_loop()
 
    def progress(step: str = None, message: str = None, detail: str = ""):
        _push_progress(session_id, loop, step=step, message=message, detail=detail)
 
    async def run_processing():
        try:
            result = await loop.run_in_executor(
                None,
                lambda: _process_flow_sync(service, form_data, progress)
            )
            request.session["bill_dict"] = result["bill_dict"]
            await queue.put({"done": True, "graph_html": result["graph_html"]})
        except Exception as e:
            await queue.put({"error": str(e)})
 
    asyncio.create_task(run_processing())
 
    async def generate():
        try:
            while True:
                msg = await asyncio.wait_for(queue.get(), timeout=300.0)
                yield f"data: {json.dumps(msg)}\n\n"
                if msg.get("done") or msg.get("error"):
                    break
        except asyncio.TimeoutError:
            yield f"data: {json.dumps({'error': 'Processing timed out'})}\n\n"
        finally:
            _progress_queues.pop(session_id, None)
 
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # important for nginx on EC2
        }
    )

async def process_flow(request: Request, service: build, form_data: dict):
    try:
        gmail_client = Gmail(
            address=form_data["email"],
            subject=form_data.get("subject"),
            date_range=[form_data["start_date"], form_data["end_date"]],
        )
        attachments = gmail_client.search_mail(service)
        bill_reader = ReadBill(attachments, form_data["currency"], parse_key=form_data.get("keyword"), range=[form_data["start_date"], form_data["end_date"]])
        bill_dict = bill_reader.parser()
        request.session["bill_dict"] = bill_dict
        # if I add title option save it in session to
        graph = GraphPlot(bill_dict)
        graph_html = graph.get_html_graph()
        return templates.TemplateResponse(
            "graph.html", {
                "request": request,
                "graph_html": graph_html,
            })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing error: {str(e)}")


@app.get("/download")
def download_graph(request: Request, format: str):
    bill_dict = request.session.get("bill_dict")
    if not bill_dict:
        raise HTTPException(status_code=400, detail="No bill data found in session")
    graph = GraphPlot(bill_dict)
    file_bytes = graph.download_by_f(format)
    media = "image" if format == "png" else "application"
    return Response(
        content=file_bytes,
        media_type=f"{media}/{format}",
        headers={
            "Content-Disposition": f"attachment; filename=graph.{format}"
        }
    )

@app.get("/show_graph", response_class=HTMLResponse)
async def show_graph(request: Request):
    graph_html = request.session.get("graph_html")
    if not graph_html:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("graph.html", {
        "request": request,
        "graph_html": graph_html,
    })



# app = FastAPI()