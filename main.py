import fastapi as api
from supabase import create_client
import os
from pydantic import BaseModel
from fastapi import Request

SUPABASE_URL = os.getenv("SUPABASE_URL")
API_KEY = os.getenv("API_KEY")

supabase = create_client(SUPABASE_URL, API_KEY)

app = api.FastAPI()

# -------------------- Models --------------------
class AuthRequest(BaseModel):
    email: str
    password: str

class Assessments(BaseModel):
    style: str | None = None
    goal: str | None = None
    skill: str | None = None

class Partitura(BaseModel):
    title: str
    composer: str
    style: str
    id: str
    difficulty: int

class Feed(BaseModel):
    songs: list[Partitura]

class User(BaseModel):
    id: str
    email: str
    access_token: str
    assessments: Assessments | None = None

class ConfirmRequest(BaseModel):
    access_token: str
    refresh_token: str | None = None

# -------------------- Helpers --------------------
def get_user_from_auth_header(request: Request):
    auth = request.headers.get("authorization")
    if not auth or not auth.lower().startswith("bearer "):
        raise api.HTTPException(status_code=401, detail="Missing Authorization header")
    token = auth.split(" ", 1)[1]
    # validiert JWT serverseitig und liefert user object
    user_resp = supabase.auth.get_user(token)
    if not user_resp or getattr(user_resp, "user", None) is None:
        raise api.HTTPException(status_code=401, detail="Invalid token")
    return user_resp.user.id

def score_partitura(part, assessment):
    score = 0
    # Style match
    if assessment.get("style") and part.get("style") == assessment.get("style"):
        score += 40
    # Skill mapping
    skill_to_range = {
        "beginner": range(1,4),
        "intermediate": range(4,7),
        "advanced": range(7,11)
    }
    skill = (assessment.get("skill") or "").lower()
    if skill and part.get("difficulty") in skill_to_range.get(skill, range(1,11)):
        score += 30
    # Goal as tag match (optional)
    if assessment.get("goal"):
        tags = part.get("tags") or ""
        if isinstance(tags, str) and assessment.get("goal").lower() in tags.lower():
            score += 10
    # popularity/percentage as bonus if present
    try:
        score += int(part.get("popularity", 0))
    except Exception:
        pass
    return score

# -------------------- Confirm Flow --------------------
@app.post("/confirm/verify")
def confirm_verify(data: ConfirmRequest):
    try:
        user = supabase.auth.set_session(
            access_token=data.access_token,
            refresh_token=data.refresh_token,
        )
        return {"status": "ok", "user_id": user.user.id}
    except Exception as e:
        raise api.HTTPException(400, str(e))

@app.get("/confirm", response_class=api.responses.HTMLResponse)
def confirm_page():
    # (HTML wie zuvor — ausgelassen hier zur Kürze; verwende deine bestehende)
    return "<html>...email confirmed page...</html>"

# -------------------- Auth --------------------
@app.get('/resend-confirm')
def resend_confirm(data:AuthRequest):
    try:
        supabase.auth.resend({
            "email": data.email,
            "type": "signup"
        })
        return {"status": "ok", "message": "Confirmation email resent"}
    except Exception as e:
        raise api.HTTPException(status_code=400, detail=str(e))

@app.post("/signup")
def signup(data: AuthRequest):
    try:
        res = supabase.auth.sign_up({"email": data.email, "password": data.password})
        return {"user": res.user, "session": res.session, "needs_confirm": True}
    except Exception as e:
        raise api.HTTPException(status_code=400, detail=str(e))

@app.post("/signin")
def signin(data: AuthRequest):
    try:
        res = supabase.auth.sign_in_with_password({
            "email": data.email,
            "password": data.password
        })
        user_data = res.user
        token = res.session.access_token
        if user_data is None:
            raise api.HTTPException(400, "Unknown email")
        if user_data.email_confirmed_at is None:
            raise api.HTTPException(403, "Please confirm your email first.")
        return {
            "id": user_data.id,
            "email": user_data.email,
            "access_token": token,
            "assessments": None
        }
    except Exception as e:
        raise api.HTTPException(status_code=400, detail=str(e))

@app.post("/user/assessment")
def save_assessment(data: Assessments, request: Request):
    user_id = get_user_from_auth_header(request)
    payload = {
        "user_id": user_id,
        "style": data.style,
        "goal": data.goal,
        "skill": data.skill,
    }
    resp = supabase.table("assessments").upsert(payload, on_conflict="user_id").execute()
    if getattr(resp, "error", None):
        raise api.HTTPException(status_code=500, detail=str(resp.error))
    return {"status": "ok"}

# -------------------- NEW: Get personalized feed --------------------
@app.get("/user/feed", response_model=Feed)
def get_feed(request: Request, limit: int = 20):
    user_id = get_user_from_auth_header(request)

    # 1) Lese assessment
    a_resp = supabase.table("assessments").select("*").eq("user_id", user_id).execute()
    if getattr(a_resp, "error", None):
        raise api.HTTPException(status_code=500, detail=str(a_resp.error))
    assessment = a_resp.data[0] if a_resp.data else None

    # 2) Fallback: keine assessment -> beliebte Partituren
    if not assessment:
        parts_resp = supabase.table("partituras").select("*").order("popularity", desc=True).limit(limit).execute()
        if getattr(parts_resp, "error", None):
            raise api.HTTPException(status_code=500, detail=str(parts_resp.error))
        songs = [Partitura(
            title=p.get("title",""),
            composer=p.get("composer",""),
            style=p.get("style",""),
            id=str(p.get("id","")),
            difficulty=int(p.get("difficulty", 0) or 0),
        ) for p in parts_resp.data]
        return Feed(songs=songs)

    # 3) Bei vorhandener assessment -> alle Partituren laden und bewerten
    parts_resp = supabase.table("partituras").select("*").execute()
    if getattr(parts_resp, "error", None):
        raise api.HTTPException(status_code=500, detail=str(parts_resp.error))

    scored = []
    for p in parts_resp.data:
        s = score_partitura(p, assessment)
        scored.append((s, p))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = []
    for score_val, p in scored[:limit]:
        top.append(Partitura(
            title=p.get("title",""),
            composer=p.get("composer",""),
            style=p.get("style",""),
            id=str(p.get("id","")),
            difficulty=int(p.get("difficulty", 0) or 0),
        ))
    return Feed(songs=top)

# -------------------- Root --------------------
@app.get('/')
def root():
    return {"message": "Welcome to the AnySong API"}
