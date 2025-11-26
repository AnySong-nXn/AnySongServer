import fastapi as api
from supabase import create_client, AuthApiError
import os
from pydantic import BaseModel

SUPABASE_URL = os.getenv("SUPABASE_URL")
API_KEY = os.getenv("API_KEY")

supabase = create_client(SUPABASE_URL, API_KEY)

app = api.FastAPI()

class AuthRequest(BaseModel):
    email: str
    password: str

class Partitura(BaseModel):
    title: str
    composer: str
    style: str
    id: str
    difficulty: int
    popularity: int | None = None

    def __repr__(self):
        return f"Partitura(title={self.title}, composer={self.composer}, style={self.style}, id={self.id}, difficulty={self.difficulty}, popularity={self.popularity})"

class Feed(BaseModel):
    songs: list[Partitura]

class Assessments(BaseModel):
    style: int | None = None
    skill: int | None = None

class User(BaseModel):
    id: str
    email: str
    access_token: str
    assessments: Assessments | None = None

class ConfirmRequest(BaseModel):
    access_token: str
    refresh_token: str | None = None

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
    return """
    <html>
    <head>
        <meta charset="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>Email Confirmed</title>

        <style>
            body {
                background-color: #1A202C; /* scaffoldBackgroundColor */
                color: #FFFFFF;
                font-family: Arial, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
            }

            .card {
                background-color: #2D3748; /* appBar + bottom bar */
                border-radius: 16px;
                padding: 32px;
                max-width: 400px;
                text-align: center;
                box-shadow: 0 8px 20px rgba(0,0,0,0.4);
            }

            h1 {
                color: #6B46C1; /* primaryColor */
                font-size: 26px;
                margin-bottom: 16px;
            }

            p {
                color: #FFFFFFCC; /* White70 */
                font-size: 16px;
                margin-bottom: 16px;
            }

            .status {
                margin-top: 20px;
                padding: 14px;
                border-radius: 10px;
                font-size: 15px;
                background-color: #1A202C;
                border: 1px solid #6B46C1;
                color: #E9D8FD; /* heller Lila */
            }

            .success {
                border-color: #48BB78;
                color: #C6F6D5;
            }

            .fail {
                border-color: #E53E3E;
                color: #FED7D7;
            }
        </style>
    </head>

    <body>
        <div class="card">
            <h1>Email bestätigt!</h1>

            <div id="statusBox" class="status">
                Bitte warten...
            </div>
        </div>

        <script>
            // Token extrahieren (# nach der URL)
            const fragment = window.location.hash.substring(1);
            const params = new URLSearchParams(fragment);

            const access_token = params.get("access_token");
            const refresh_token = params.get("refresh_token");

            const statusBox = document.getElementById("statusBox");

            async function verifyBackend() {
                try {
                    await fetch("/confirm/verify", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            access_token: access_token,
                            refresh_token: refresh_token
                        })
                    });
                } catch (e) {
                    console.error("Verification failed:", e);
                }
            }

            async function tryOpenApp() {
                const appLink = "anysong://confirm";

                // versuchen die App zu öffnen
                window.location.href = appLink;

                let opened = false;

                const start = Date.now();

                // Wenn Browser nach 1.2s nicht "verlassen" wurde → App existiert nicht
                setTimeout(() => {
                    if (Date.now() - start < 1200) {
                        opened = true;
                    }

                    updateStatus(opened);
                }, 1200);
            }

            function updateStatus(opened) {
                if (opened) {
                    statusBox.classList.add("success");
                    statusBox.textContent =
                        "AnySong wurde erfolgreich geöffnet! Du kannst diese Seite jetzt schließen.";
                } else {
                    statusBox.classList.add("fail");
                    statusBox.textContent =
                        "Du kannst diese Seite jetzt schließen.";
                }
            }

            // Ablauf starten
            if (access_token) {
                verifyBackend().then(() => tryOpenApp());
            } else {
                statusBox.classList.add("fail");
                statusBox.textContent = "Ungültiger Bestätigungslink.";
            }
        </script>
    </body>
    </html>
    """



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
        try: 
            res = supabase.auth.sign_in_with_password({
                "email": data.email,
                "password": data.password
            })
        except AuthApiError as e:
            if "JWT" in str(e):
                supabase.auth.refresh_session()
                res = supabase.auth.sign_in_with_password({
                    "email": data.email,
                    "password": data.password
                })
            else:
                raise api.HTTPException(status_code=400, detail=str(e))

        user_data = res.user
        token = res.session.access_token

        if user_data is None:
            raise api.HTTPException(400, "Unknown email")

        if user_data.email_confirmed_at is None:
            raise api.HTTPException(403, "Please confirm your email first.")
        
        # Lade assessment
        assessments = None
        a_resp = supabase.table("assessments").select("*").eq("user_id", user_data.id).execute()
        if getattr(a_resp, "error", None):
            print("Error loading assessments:", a_resp.error, flush=True)
        if a_resp.data:
            a = a_resp.data[0]
            assessments = Assessments(
                style=int(a.get("style")) if a.get("style") is not None else None,
                skill=int(a.get("skill")) if a.get("skill") is not None else None,
            )

        return User(
            id=user_data.id,
            email=user_data.email,
            access_token=token,
            assessments=assessments,
        )
    except Exception as e:
        raise api.HTTPException(status_code=400, detail=str(e))
    
def score_partitura(part, assessment):
    score = 0
    if assessment.get("style", ""):
        if int(part.get("style","")) == int(assessment.style):
            score += 20
    if assessment.get("skill", ""):
        skill = int(assessment.skill)
        difficulty = int(part.get("difficulty", 0) or 0)
        diff = abs(skill - difficulty)
        if diff == 0:
            score += 20
        elif diff == 1:
            score += 12
        elif diff == 2:
            score += 6
    
    if part.get("popularity", 0):
        score += min(int(part.get("popularity", 0) or 0), 100) / 5  # max 20 Punkte

    return score


def get_user_from_auth_header(request: api.Request):
    auth = request.headers.get("authorization")
    if not auth or not auth.lower().startswith("bearer "):
        raise api.HTTPException(status_code=401, detail="Missing Authorization header")
    token = auth.split(" ", 1)[1]
    # validiert JWT serverseitig und liefert user object
    user_resp = supabase.auth.get_user(token)
    if not user_resp or getattr(user_resp, "user", None) is None:
        raise api.HTTPException(status_code=401, detail="Invalid token")
    return user_resp.user.id

@app.post("/user/assessment")
def save_assessment(data: Assessments, request: api.Request):
    user_id = get_user_from_auth_header(request)
    payload = {
        "user_id": str(user_id),
        "style": int(data.style) if data.style is not None else None,
        "skill": int(data.skill) if data.skill is not None else None,
    }
    resp = supabase.table("assessments").upsert(payload, on_conflict="user_id").execute()
    if getattr(resp, "error", None):
        raise api.HTTPException(status_code=500, detail=str(resp.error))
    return {"status": "ok"}

# -------------------- NEW: Get personalized feed --------------------
@app.get("/user/feed", response_model=Feed)
def get_feed(request: api.Request, limit: int = 20):
    user_id = get_user_from_auth_header(request)

    # 1) Lese assessment
    a_resp = supabase.table("assessments").select("*").eq("user_id", user_id).execute()
    if getattr(a_resp, "error", None):
        raise api.HTTPException(status_code=500, detail=str(a_resp.error))
    assessment = a_resp.data[0] if a_resp.data else None

    # 2) Fallback: keine assessment -> beliebte Partituren
    if not assessment:
        parts_resp = supabase.table("partituras").select("*").limit(limit).execute()
        if getattr(parts_resp, "error", None):
            raise api.HTTPException(status_code=500, detail=str(parts_resp.error))
        songs = [Partitura(
            title=p.get("title",""),
            composer=p.get("composer",""),
            style=p.get("style", ""),
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
            popularity=int(p.get("popularity", 0) or 0),
        ))
    print(top, flush=True)

    return Feed(songs=top)

@app.head("/")
def root_head():
    # Du kannst Header setzen, aber keinen Body zurückgeben
    return api.Response(headers={"X-Welcome-Message": "Welcome to the AnySong API"})