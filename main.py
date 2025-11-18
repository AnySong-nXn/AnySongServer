import fastapi as api
from supabase import create_client
import os
from pydantic import BaseModel

SUPABASE_URL = os.getenv("SUPABASE_URL")
API_KEY = os.getenv("API_KEY")

supabase = create_client(SUPABASE_URL, API_KEY)

app = api.FastAPI()

class AuthRequest(BaseModel):
    email: str
    password: str

class Assessments(BaseModel):
    style: str
    goal: str
    skill: str

class Partitura(BaseModel):
    title: str
    composer: str
    style: str
    id: str
    difficulty: int
    percentage: int

class Feed(BaseModel):
    songs: list[Partitura]

class User(BaseModel):
    id: str
    email: str
    access_token: str
    feed: Feed

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

        feed = Feed(songs=[]) # da kommen die songs rein

        return User(
            id=user_data.id,
            email=user_data.email,
            access_token=token,
            feed=feed
        )
    except Exception as e:
        raise api.HTTPException(status_code=400, detail=str(e))