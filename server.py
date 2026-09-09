import os
import sqlite3
import re
import tempfile
import cv2
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Header, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from telethon import TelegramClient
from dotenv import load_dotenv
from telethon.sessions import StringSession

# Cargar credenciales
load_dotenv()
API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')
CHAT_ID = int(os.getenv('CHAT_ID'))

ORÍGENES_PERMITIDOS = [
    "http://localhost:5173",
    "http://localhost:4173",
]
url_produccion = os.getenv('FRONTEND_URL')

# Limpiamos el texto por si hay espacios o barras al final
if url_produccion:
    url_limpia = url_produccion.strip().rstrip('/')
    ORÍGENES_PERMITIDOS.append(url_limpia)

# Imprimimos la lista en los Logs de Render para confirmar qué está leyendo
print("=== ORÍGENES CORS PERMITIDOS ===")
print(ORÍGENES_PERMITIDOS)
print("================================")

# Inicializar cliente de Telegram
SESSION_STRING = os.getenv('TELEGRAM_SESSION')
cliente = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

def inicializar_db():
    conexion = sqlite3.connect("database.db")
    cursor = conexion.cursor()
    
    # Usamos IF NOT EXISTS para que solo las cree la primera vez, sin borrarlas en cada reinicio
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Serie (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT,
            poster_message_id INTEGER UNIQUE,
            categoria TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Capitulo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            serie_id INTEGER,
            temporada INTEGER,
            numero INTEGER,
            video_message_id INTEGER UNIQUE,
            thumbnail_message_id INTEGER,
            FOREIGN KEY(serie_id) REFERENCES Serie(id)
        )
    ''')
    
    conexion.commit()
    conexion.close()
    print("🗄️ Base de datos verificada/inicializada con reglas UNIQUE.")

# Administrador de contexto para el ciclo de vida (Lifespan)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- 1. Preparamos la base de datos local ---
    inicializar_db()

    # --- 2. Conectamos a Telegram ---
    print("Conectando a Telegram...")
    await cliente.connect()
    print("Conexión establecida con éxito.")
    
    # --- 3. Sincronizamos ---
    print("Reconstruyendo caché desde Telegram...")
    await sincronizar_biblioteca()
    
    yield
    
    print("Desconectando de Telegram...")
    await cliente.disconnect()

# Inicializar FastAPI (UNA SOLA VEZ)
app = FastAPI(title="Servidor de Streaming Telegram", lifespan=lifespan)

# Configuración CORS (UNA SOLA VEZ)
# Configuración CORS (Lista blanca estricta)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ORÍGENES_PERMITIDOS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.api_route("/", methods=["GET", "HEAD"])
async def root():
    return {"estado": "ok", "mensaje": "Servidor TelegramFlix activo y funcionando "}

# ... (Aquí continúan tus endpoints @app.get...)

@app.get("/poster/{serie_id}")
async def obtener_poster(serie_id: int):
    conexion = sqlite3.connect("database.db")
    cursor = conexion.cursor()
    cursor.execute("SELECT poster_message_id FROM Serie WHERE id = ?", (serie_id,))
    resultado = cursor.fetchone()
    conexion.close()

    if not resultado or not resultado[0]:
        raise HTTPException(status_code=404, detail="Póster no encontrado")
        
    poster_id = resultado[0]
    
    mensaje = await cliente.get_messages(CHAT_ID, ids=poster_id)
    if not mensaje or not (mensaje.photo or mensaje.document):
        raise HTTPException(status_code=404, detail="Imagen no encontrada")

    async def generador_foto():
        async for chunk in cliente.iter_download(mensaje.media):
            yield chunk

    return StreamingResponse(generador_foto(), media_type="image/jpeg")

@app.get("/catalogo")
async def obtener_catalogo():
    conexion = sqlite3.connect("database.db")
    cursor = conexion.cursor()
    # Ahora pedimos también la categoría
    cursor.execute("SELECT id, titulo, categoria FROM Serie")
    series = [{"id": row[0], "titulo": row[1], "categoria": row[2]} for row in cursor.fetchall()]
    conexion.close()
    return {"series": series}

@app.api_route("/stream/{capitulo_id}", methods=["GET", "HEAD"])
async def stream_video(capitulo_id: int, request: Request):
    conexion = sqlite3.connect("database.db")
    cursor = conexion.cursor()
    cursor.execute("SELECT video_message_id FROM Capitulo WHERE id = ?", (capitulo_id,))
    resultado = cursor.fetchone()
    conexion.close()

    if not resultado:
        raise HTTPException(status_code=404, detail="Capítulo no encontrado")
        
    video_message_id = resultado[0]

    mensaje = await cliente.get_messages(CHAT_ID, ids=video_message_id)
    if not mensaje or not mensaje.document:
        raise HTTPException(status_code=404, detail="Video no encontrado en Telegram")

    peso_total = mensaje.document.size

    # --- RESPUESTA AL "PING" DEL IPHONE ---
    if request.method == "HEAD":
        return Response(headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(peso_total),
            "Content-Type": "video/mp4"
        })

    range_header = request.headers.get("Range")
    
    start = 0
    end = peso_total - 1
    status_code = 200

    if range_header:
        range_match = re.match(r'bytes=(?P<start>\d+)?-(?P<end>\d+)?', range_header)
        if range_match:
            start_str = range_match.group("start")
            end_str = range_match.group("end")
            
            if start_str and end_str:
                start = int(start_str)
                end = int(end_str)
            elif start_str: 
                start = int(start_str)
                end = peso_total - 1
            elif end_str: 
                start = peso_total - int(end_str)
                end = peso_total - 1

            status_code = 206

    if start >= peso_total or end >= peso_total or start > end:
        return Response(
            status_code=416, 
            headers={"Content-Range": f"bytes */{peso_total}"}
        )

    tamaño_fragmento = (end - start) + 1

    tamaño_fragmento = (end - start) + 1

    # --- EL GENERADOR CON PRECISIÓN MILIMÉTRICA ---
    async def generador_video():
        bytes_enviados = 0
        async for chunk in cliente.iter_download(
            mensaje.media, 
            offset=start, 
            request_size=1024 * 512 # Bajamos el bloque a 512KB para que sea más ágil en móviles
        ):
            # ¿Cuántos bytes nos faltan para cumplir exactamente lo que pidió el iPhone?
            faltan = tamaño_fragmento - bytes_enviados
            
            # Si el bloque de Telegram trae más de lo que necesitamos, lo cortamos (Slicing)
            if len(chunk) > faltan:
                chunk = chunk[:faltan]
                
            yield chunk
            
            bytes_enviados += len(chunk)
            
            # Si ya cumplimos con la cuota exacta solicitada, detenemos la descarga
            if bytes_enviados >= tamaño_fragmento:
                break

    # Cabeceras estrictas ordenadas para iOS
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(tamaño_fragmento),
        "Content-Type": "video/mp4",
    }
    
    if status_code == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{peso_total}"

    return StreamingResponse(generador_video(), status_code=status_code, headers=headers)

@app.get("/capitulos/{serie_id}")
async def obtener_capitulos(serie_id: int):
    conexion = sqlite3.connect("database.db")
    cursor = conexion.cursor()
    cursor.execute("""
        SELECT id, temporada, numero 
        FROM Capitulo 
        WHERE serie_id = ? 
        ORDER BY temporada, numero
    """, (serie_id,))
    
    capitulos = [{"id": row[0], "temporada": row[1], "numero": row[2]} for row in cursor.fetchall()]
    conexion.close()
    
    return {"capitulos": capitulos}

@app.get("/thumbnail/{capitulo_id}")
async def obtener_thumbnail(capitulo_id: int):
    conexion = sqlite3.connect("database.db")
    cursor = conexion.cursor()
    cursor.execute("SELECT thumbnail_message_id FROM Capitulo WHERE id = ?", (capitulo_id,))
    resultado = cursor.fetchone()
    conexion.close()

    if not resultado or not resultado[0]:
        raise HTTPException(status_code=404, detail="Thumbnail no encontrado en la base de datos")
        
    thumb_id = resultado[0]
    
    # Buscamos la foto en Telegram usando directamente su ID de mensaje guardado
    mensaje = await cliente.get_messages(CHAT_ID, ids=thumb_id)
    if not mensaje or not (mensaje.photo or mensaje.document):
        raise HTTPException(status_code=404, detail="Imagen no encontrada en Telegram")

    async def generador_thumb():
        async for chunk in cliente.iter_download(mensaje.media):
            yield chunk

    return StreamingResponse(generador_thumb(), media_type="image/jpeg")

@app.get("/sincronizar")
async def sincronizar_biblioteca():
    print("🔍 Sincronizando catálogo con Telegram...")
    patron_capitulo = re.compile(r'[sS](\d+)[eE](\d+)')
    nuevos_registros = 0

    # Iteramos desde el mensaje más antiguo al más nuevo
    async for mensaje in cliente.iter_messages(CHAT_ID, reverse=True):

        print(f"Mensaje leído: {mensaje.text} | Es archivo: {bool(mensaje.file)}")
        
        # CASO 1: SERIE
        if mensaje.text and mensaje.text.startswith('#'):
            partes_texto = mensaje.text.split()
            
            # Si tiene al menos 2 palabras (ej: #Accion #Breaking_Bad)
            if len(partes_texto) >= 2:
                categoria = partes_texto[0].replace('#', '')
                titulo = partes_texto[1].replace('#', '').replace('_', ' ')
            else:
                # Por si olvidaste poner la categoría y solo pusiste #Breaking_Bad
                categoria = "General"
                titulo = partes_texto[0].replace('#', '').replace('_', ' ')
                
            conexion = sqlite3.connect("database.db")
            cursor = conexion.cursor()
            
            # Actualizamos el INSERT para que también guarde la categoría
            cursor.execute("""
                INSERT OR IGNORE INTO Serie (titulo, poster_message_id, categoria) 
                VALUES (?, ?, ?)
            """, (titulo, mensaje.id, categoria))
            
            if cursor.rowcount > 0: 
                nuevos_registros += 1
            conexion.commit()
            conexion.close()
            continue
            
        # CASO 2: CAPÍTULO (VIDEO)
        if mensaje.file and mensaje.reply_to_msg_id:
            nombre_archivo = mensaje.file.name
            if nombre_archivo:
                match = patron_capitulo.search(nombre_archivo)
                if match:
                    temporada = int(match.group(1))
                    numero = int(match.group(2))
                    
                    conexion = sqlite3.connect("database.db")
                    cursor = conexion.cursor()
                    cursor.execute("SELECT id FROM Serie WHERE poster_message_id = ?", (mensaje.reply_to_msg_id,))
                    serie = cursor.fetchone()
                    
                    if serie:
                        cursor.execute("""
                            INSERT OR IGNORE INTO Capitulo (serie_id, temporada, numero, video_message_id) 
                            VALUES (?, ?, ?, ?)
                        """, (serie[0], temporada, numero, mensaje.id))
                        if cursor.rowcount > 0: 
                            nuevos_registros += 1
                    conexion.commit()
                    conexion.close()
                    continue

        # CASO 3: MINIATURA
        if (mensaje.photo or mensaje.file) and mensaje.reply_to_msg_id:
            conexion = sqlite3.connect("database.db")
            cursor = conexion.cursor()
            cursor.execute("SELECT id FROM Capitulo WHERE video_message_id = ?", (mensaje.reply_to_msg_id,))
            capitulo = cursor.fetchone()
            
            if capitulo:
                cursor.execute("""
                    UPDATE Capitulo 
                    SET thumbnail_message_id = ? 
                    WHERE video_message_id = ?
                """, (mensaje.id, mensaje.reply_to_msg_id))
            conexion.commit()
            conexion.close()

    return {"status": "ok", "nuevos": nuevos_registros}

@app.delete("/serie/{serie_id}")
async def eliminar_serie(serie_id: int):
    conexion = sqlite3.connect("database.db")
    cursor = conexion.cursor()
    
    # 1. Borramos los capítulos explícitamente primero (a prueba de fallos)
    cursor.execute("DELETE FROM Capitulo WHERE serie_id = ?", (serie_id,))
    
    # 2. Ahora sí, borramos la serie
    cursor.execute("DELETE FROM Serie WHERE id = ?", (serie_id,))
    conexion.commit()
    
    if cursor.rowcount == 0:
        conexion.close()
        raise HTTPException(status_code=404, detail="Serie no encontrada")
        
    conexion.close()
    return {"mensaje": "Serie y sus capítulos eliminados correctamente"}