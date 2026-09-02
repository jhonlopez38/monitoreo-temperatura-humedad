from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
from collections import deque
import os

app = FastAPI(title="Monitoreo Ambiental - Facatativa")

# ==================== CONFIG ====================
DEVICE_TOKEN = os.environ.get("DEVICE_TOKEN", "ventilacion123")
TZ_COL = timezone(timedelta(hours=-5))
MAX_HISTORIAL = 30

# ==================== ESTADO EN MEMORIA ====================
estado = {
    "temp": 0.0,
    "hum": 0.0,
    "pres": 0.0,
    "estado": "---",
    "ventilador": False,     # estado real del ventilador (ON/OFF)
    "modo": "AUTO",          # AUTO | ON | OFF
    "ultima_actualizacion": None,
    "online": False,
}

historial = deque(maxlen=MAX_HISTORIAL)
comando_pendiente = None


# ==================== MODELOS ====================
class DatosESP32(BaseModel):
    token: str
    temp: float
    hum: float
    pres: float = 0.0
    estado: str
    vent: bool = False
    modo: str = "AUTO"


class Comando(BaseModel):
    accion: str   # "on" | "off" | "auto"


# ==================== ENDPOINTS ESP32 ====================
@app.post("/api/update")
def actualizar(datos: DatosESP32):
    global comando_pendiente
    if datos.token != DEVICE_TOKEN:
        raise HTTPException(status_code=401, detail="Token invalido")

    ahora = datetime.now(TZ_COL)
    estado["temp"] = datos.temp
    estado["hum"] = datos.hum
    estado["pres"] = datos.pres
    estado["estado"] = datos.estado
    estado["ventilador"] = datos.vent
    estado["modo"] = datos.modo
    estado["online"] = True
    estado["ultima_actualizacion"] = ahora.strftime("%Y-%m-%d %H:%M:%S")

    historial.append({
        "hora": ahora.strftime("%H:%M:%S"),
        "temp": datos.temp,
        "hum": datos.hum,
        "pres": datos.pres,
    })

    cmd = comando_pendiente
    comando_pendiente = None
    return {"comando": cmd, "modo": estado["modo"]}


# ==================== ENDPOINTS WEB APP ====================
@app.get("/api/estado")
def obtener_estado():
    if estado["ultima_actualizacion"]:
        ultima = datetime.strptime(
            estado["ultima_actualizacion"], "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=TZ_COL)
        if (datetime.now(TZ_COL) - ultima).total_seconds() > 30:
            estado["online"] = False

    return JSONResponse({
        **estado,
        "historial": list(historial),
    })


@app.post("/api/comando")
def enviar_comando(cmd: Comando):
    global comando_pendiente
    if cmd.accion not in ("on", "off", "auto"):
        raise HTTPException(status_code=400, detail="Accion invalida")
    comando_pendiente = cmd.accion
    return {"ok": True, "encolado": cmd.accion}


# ==================== DASHBOARD ====================
@app.get("/")
def dashboard():
    return FileResponse("static/index.html")


@app.get("/sw.js")
def service_worker():
    return FileResponse("static/sw.js", media_type="application/javascript")


@app.get("/manifest.json")
def manifest():
    return FileResponse("static/manifest.json", media_type="application/manifest+json")


if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
