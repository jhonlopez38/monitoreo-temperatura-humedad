from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
from collections import deque
import os

app = FastAPI(title="Monitoreo de Temperatura y Humedad - Facatativa")

# ==================== CONFIG ====================
# Token compartido: el ESP32 debe enviar el mismo valor.
# En Render puedes ponerlo como Environment Variable DEVICE_TOKEN.
DEVICE_TOKEN = os.environ.get("DEVICE_TOKEN", "ventilacion123")

TZ_COL = timezone(timedelta(hours=-5))  # UTC-5 Colombia
MAX_HISTORIAL = 30  # cuantos puntos guarda la grafica

# ==================== ESTADO EN MEMORIA ====================
estado = {
    "temp": 0.0,
    "hum": 0.0,
    "estado": "---",
    "sistema": True,          # True = encendido, False = apagado
    "ultima_actualizacion": None,
    "online": False,
}

# Historial para la grafica (ultimas MAX_HISTORIAL lecturas)
historial = deque(maxlen=MAX_HISTORIAL)

# Cola de comandos pendientes para el ESP32 ("on" / "off" / None)
comando_pendiente = None


# ==================== MODELOS ====================
class DatosESP32(BaseModel):
    token: str
    temp: float
    hum: float
    estado: str


class Comando(BaseModel):
    accion: str  # "on" | "off"


# ==================== ENDPOINTS ESP32 ====================
@app.post("/api/update")
def actualizar(datos: DatosESP32):
    """El ESP32 envia sus datos y recibe el comando pendiente (si hay)."""
    global comando_pendiente
    if datos.token != DEVICE_TOKEN:
        raise HTTPException(status_code=401, detail="Token invalido")

    ahora = datetime.now(TZ_COL)
    estado["temp"] = datos.temp
    estado["hum"] = datos.hum
    estado["estado"] = datos.estado
    estado["online"] = True
    estado["ultima_actualizacion"] = ahora.strftime("%Y-%m-%d %H:%M:%S")

    # guardar punto en el historial para la grafica
    historial.append({
        "hora": ahora.strftime("%H:%M:%S"),
        "temp": datos.temp,
        "hum": datos.hum,
    })

    # entregar el comando y limpiarlo
    cmd = comando_pendiente
    comando_pendiente = None
    if cmd == "on":
        estado["sistema"] = True
    elif cmd == "off":
        estado["sistema"] = False

    return {"comando": cmd, "sistema": estado["sistema"]}


# ==================== ENDPOINTS WEB APP ====================
@app.get("/api/estado")
def obtener_estado():
    """El dashboard consulta el estado actual + el historial para la grafica."""
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
    """El dashboard encola un comando para el ESP32."""
    global comando_pendiente
    if cmd.accion not in ("on", "off"):
        raise HTTPException(status_code=400, detail="Accion invalida")
    comando_pendiente = cmd.accion
    return {"ok": True, "encolado": cmd.accion}


# ==================== DASHBOARD ====================
@app.get("/")
def dashboard():
    return FileResponse("static/index.html")


if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
