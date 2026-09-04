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

# Inicializar cliente de Telegram
SESSION_STRING = os.getenv('TELEGRAM_SESSION')
cliente = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

# Administrador de contexto para el ciclo de vida (Lifespan)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    print("🚀 Conectando a Telegram...")
    await cliente.connect()
    print("✅ Conexión establecida con éxito.")
    
    # ¡Auto-sincronizamos la base de datos si está vacía al arrancar!
    print("🔄 Reconstruyendo caché desde Telegram...")
    await sincronizar_biblioteca()
    
    yield
    
    # --- Shutdown ---
    print("🛑 Desconectando de Telegram...")
    await cliente.disconnect()

# Inicializar FastAPI usando lifespan en lugar de on_event
app = FastAPI(title="Servidor de Streaming Telegram", lifespan=lifespan)

# Configuración CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

@app.get("/stream/{capitulo_id}")
async def stream_video(capitulo_id: int, range: str = Header(None)):
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

    start = 0
    end = peso_total - 1
    status_code = 200

    if range:
        match = re.search(r'bytes=(\d+)-(\d*)', range)
        if match:
            start = int(match.group(1))
            if match.group(2):
                end = int(match.group(2))
            status_code = 206

    tamaño_fragmento = (end - start) + 1

    async def generador_video():
        async for chunk in cliente.iter_download(
            mensaje.media, 
            offset=start, 
            limit=tamaño_fragmento, 
            request_size=1024 * 1024
        ):
            yield chunk

    headers = {
        "Content-Range": f"bytes {start}-{end}/{peso_total}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(tamaño_fragmento),
        "Content-Type": "video/mp4",
    }

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