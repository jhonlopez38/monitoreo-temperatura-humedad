from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
from collections import deque
import os, json, base64, urllib.request
 
app = FastAPI(title="Monitoreo Ambiental - Facatativa")
 
# ==================== CONFIG ====================
DEVICE_TOKEN = os.environ.get("DEVICE_TOKEN", "ventilacion123")
 
# --- GitHub (persistencia) --- mismos nombres que HERMES
GITHUB_TOKEN = os.environ.get("GH_TOKEN", "")
GITHUB_REPO  = os.environ.get("GH_REPO", "jhonlopez38/monitoreo-temperatura-humedad")
GITHUB_FILE  = os.environ.get("GH_FILE", "registros.json")
GITHUB_BRANCH = os.environ.get("GH_BRANCH", "main")
 
TZ_COL = timezone(timedelta(hours=-5))
MAX_HISTORIAL = 30           # puntos en vivo para la grafica principal
GUARDAR_CADA = 60            # segundos entre guardados permanentes
 
# ==================== ESTADO EN MEMORIA ====================
estado = {
    "temp": 0.0, "hum": 0.0, "pres": 0.0,
    "estado": "---", "ventilador": False, "modo": "AUTO",
    "ultima_actualizacion": None, "online": False,
}
historial = deque(maxlen=MAX_HISTORIAL)   # en vivo
comando_pendiente = None
 
# Registros permanentes (cache en memoria, se sincroniza con GitHub)
registros = []
ultimo_guardado = 0
registros_sha = None   # sha del archivo en GitHub para actualizarlo
 
 
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
    accion: str
 
 
# ==================== GITHUB: cargar y guardar ====================
def gh_headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "monitoreo-ambiental",
    }
 
def cargar_registros_github():
    """Carga los registros existentes desde GitHub al arrancar."""
    global registros, registros_sha
    if not GITHUB_TOKEN:
        return
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}?ref={GITHUB_BRANCH}"
    try:
        req = urllib.request.Request(url, headers=gh_headers())
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
            registros_sha = data["sha"]
            contenido = base64.b64decode(data["content"]).decode()
            registros = json.loads(contenido)
    except Exception as e:
        registros = []
        registros_sha = None
 
def guardar_registros_github():
    """Guarda los registros en GitHub (merge-based, como HERMES)."""
    global registros_sha
    if not GITHUB_TOKEN:
        return
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"
    contenido = base64.b64encode(json.dumps(registros).encode()).decode()
    cuerpo = {
        "message": f"registro {datetime.now(TZ_COL).strftime('%Y-%m-%d %H:%M:%S')}",
        "content": contenido,
        "branch": GITHUB_BRANCH,
    }
    if registros_sha:
        cuerpo["sha"] = registros_sha
    try:
        req = urllib.request.Request(url, data=json.dumps(cuerpo).encode(),
                                     headers=gh_headers(), method="PUT")
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read().decode())
            registros_sha = resp["content"]["sha"]
    except Exception as e:
        pass
 
 
# ==================== ENDPOINTS ESP32 ====================
@app.post("/api/update")
def actualizar(datos: DatosESP32):
    global comando_pendiente, ultimo_guardado
    if datos.token != DEVICE_TOKEN:
        raise HTTPException(status_code=401, detail="Token invalido")
 
    ahora = datetime.now(TZ_COL)
    estado.update({
        "temp": datos.temp, "hum": datos.hum, "pres": datos.pres,
        "estado": datos.estado, "ventilador": datos.vent, "modo": datos.modo,
        "online": True,
        "ultima_actualizacion": ahora.strftime("%Y-%m-%d %H:%M:%S"),
    })
 
    historial.append({
        "hora": ahora.strftime("%H:%M:%S"),
        "temp": datos.temp, "hum": datos.hum, "pres": datos.pres,
    })
 
    # Guardar registro permanente cada GUARDAR_CADA segundos
    ts = ahora.timestamp()
    if ts - ultimo_guardado >= GUARDAR_CADA:
        ultimo_guardado = ts
        registros.append({
            "fecha": ahora.strftime("%Y-%m-%d"),
            "hora": ahora.strftime("%H:%M:%S"),
            "temp": datos.temp, "hum": datos.hum, "pres": datos.pres,
            "estado": datos.estado, "vent": datos.vent,
        })
        guardar_registros_github()
 
    cmd = comando_pendiente
    comando_pendiente = None
    return {"comando": cmd, "modo": estado["modo"]}
 
 
# ==================== ENDPOINTS WEB APP ====================
@app.get("/api/estado")
def obtener_estado():
    if estado["ultima_actualizacion"]:
        ultima = datetime.strptime(estado["ultima_actualizacion"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ_COL)
        if (datetime.now(TZ_COL) - ultima).total_seconds() > 30:
            estado["online"] = False
    return JSONResponse({**estado, "historial": list(historial)})
 
 
@app.post("/api/comando")
def enviar_comando(cmd: Comando):
    global comando_pendiente
    if cmd.accion not in ("on", "off", "auto"):
        raise HTTPException(status_code=400, detail="Accion invalida")
    comando_pendiente = cmd.accion
    return {"ok": True, "encolado": cmd.accion}
 
 
@app.get("/api/historico")
def obtener_historico(
    fecha: str = Query(None, description="YYYY-MM-DD"),
    desde: str = Query(None, description="HH:MM"),
    hasta: str = Query(None, description="HH:MM"),
):
    """Devuelve los registros permanentes, filtrados por fecha y rango de horas."""
    datos = registros
    if fecha:
        datos = [r for r in datos if r["fecha"] == fecha]
    if desde:
        datos = [r for r in datos if r["hora"] >= desde]
    if hasta:
        datos = [r for r in datos if r["hora"] <= hasta]
    # Lista de fechas disponibles para el selector
    fechas = sorted(set(r["fecha"] for r in registros))
    return JSONResponse({"registros": datos, "fechas": fechas, "total": len(datos)})
 
 
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
 
 
# Cargar registros al arrancar
cargar_registros_github()
 
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
