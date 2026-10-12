
import io
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from google.genai import errors as gemini_errors
from PIL import Image, ImageOps, UnidentifiedImageError

from . import assistant, catalog

STATIC = Path(__file__).resolve().parent.parent / "static"
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_SIDE = 768
MAX_HISTORY_TURNS = 12

app = FastAPI(title="StyleGuru")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/featured")
def featured(gender: str | None = None):
    return catalog.featured(gender or None)


def prepare_image(data):
    
    try:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    except (UnidentifiedImageError, OSError):
        raise HTTPException(400, "That file doesn't look like an image.")
    image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=85)
    return out.getvalue()


def clean_profile(raw):
    
    def number(value):
        try:
            return int(value) or None
        except (TypeError, ValueError):
            return None

    def ids(value):
        return [i for i in value or [] if isinstance(i, int)]

    return {
        "gender": raw.get("gender") if raw.get("gender") in ("Men", "Women") else None,
        "size": str(raw.get("size") or "").upper() or None,
        "shoe_size": str(raw.get("shoe_size") or "") or None,
        "budget": number(raw.get("budget")),
        "colours": [str(c) for c in raw.get("colours") or []][:10],
        "liked": ids(raw.get("liked"))[-30:],
        "disliked": ids(raw.get("disliked"))[-60:],
    }


@app.post("/api/chat")
async def chat(
    message: str = Form(""),
    history: str = Form("[]"),
    profile: str = Form(""),
    image: UploadFile | None = File(None),
):
    
    try:
        turns = [
            {"role": turn["role"], "text": str(turn["text"])[:4000], "note": str(turn.get("note") or "")[:4000]}
            for turn in json.loads(history)[-MAX_HISTORY_TURNS:]
            if turn.get("role") in ("user", "assistant") and turn.get("text")
        ]
        shopper = clean_profile(json.loads(profile)) if profile else None
    except (ValueError, TypeError, AttributeError, KeyError):
        raise HTTPException(400, "Malformed request.")

    photo = None
    if image is not None:
        data = await image.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(413, "That photo is too large (8 MB max).")
        photo = prepare_image(data)

    message = message.strip()[:2000] or ("Find me something similar to this." if photo else "")
    if not message:
        raise HTTPException(400, "Say something or attach a photo.")

    try:
        return await assistant.chat(message, turns, shopper, photo)
    except gemini_errors.APIError as error:
        if error.code == 429:
            raise HTTPException(429, "The AI service is busy right now. Please try again in a minute.")
        raise HTTPException(502, "The AI service couldn't be reached. Please try again.")
    except httpx.TimeoutException:
        raise HTTPException(504, "The AI service took too long to answer. Please try again.")
