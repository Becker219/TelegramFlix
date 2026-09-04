import os
import sys
import re
import sqlite3
from dotenv import load_dotenv
from telethon import TelegramClient

# 1. Cargar configuración del .env
load_dotenv()
try:
    API_ID = int(os.getenv('API_ID'))
    API_HASH = os.getenv('API_HASH')
    CHAT_ID = int(os.getenv('CHAT_ID'))
except TypeError:
    print("❌ ERROR: Falta algún dato en el .env (API_ID, API_HASH o CHAT_ID)")
    sys.exit()

cliente = TelegramClient('mi_sesion', API_ID, API_HASH)

# --- FUNCIONES DE BASE DE DATOS ---
def obtener_conexion():
    conexion = sqlite3.connect("database.db")
    conexion.execute("PRAGMA foreign_keys = ON;")
    return conexion

def guardar_serie(titulo, msg_id):
    conexion = obtener_conexion()
    cursor = conexion.cursor()
    cursor.execute("INSERT OR IGNORE INTO Serie (titulo, poster_message_id) VALUES (?, ?)", (titulo, msg_id))
    conexion.commit()
    if cursor.rowcount > 0:
        print(f"🎬 Nueva serie registrada: {titulo}")
    conexion.close()

def obtener_serie_por_poster(poster_msg_id):
    conexion = obtener_conexion()
    cursor = conexion.cursor()
    cursor.execute("SELECT id, titulo FROM Serie WHERE poster_message_id = ?", (poster_msg_id,))
    resultado = cursor.fetchone()
    conexion.close()
    return resultado

def guardar_capitulo(serie_id, temporada, numero, video_msg_id):
    conexion = obtener_conexion()
    cursor = conexion.cursor()
    cursor.execute("""
        INSERT OR IGNORE INTO Capitulo (serie_id, temporada, numero, video_message_id) 
        VALUES (?, ?, ?, ?)
    """, (serie_id, temporada, numero, video_msg_id))
    conexion.commit()
    if cursor.rowcount > 0:
        print(f"📺 Nuevo capítulo guardado: S{temporada:02d}E{numero:02d}")
    conexion.close()

def actualizar_thumbnail_capitulo(video_msg_id, thumb_msg_id):
    conexion = obtener_conexion()
    cursor = conexion.cursor()
    cursor.execute("""
        UPDATE Capitulo 
        SET thumbnail_message_id = ? 
        WHERE video_message_id = ?
    """, (thumb_msg_id, video_msg_id))
    conexion.commit()
    if cursor.rowcount > 0:
        print(f"🖼️ Miniatura enlazada al video ID: {video_msg_id}")
    conexion.close()

# --- LÓGICA PRINCIPAL (EL ESCÁNER) ---
async def main():
    print("🔍 Iniciando escaneo del canal...\n")
    
    patron_capitulo = re.compile(r'[sS](\d+)[eE](\d+)')
    
    async for mensaje in cliente.iter_messages(CHAT_ID, reverse=True):
        
        # CASO 1: ES UNA SERIE (PÓSTER)
        if mensaje.text and mensaje.text.startswith('#'):
            titulo_bruto = mensaje.text.split()[0]
            titulo_limpio = titulo_bruto.replace('#', '').replace('_', ' ')
            guardar_serie(titulo_limpio, mensaje.id)
            continue
            
        # CASO 2: ES UN CAPÍTULO (VIDEO)
        if mensaje.file and mensaje.reply_to_msg_id:
            nombre_archivo = mensaje.file.name
            if nombre_archivo:
                match = patron_capitulo.search(nombre_archivo)
                if match:
                    temporada = int(match.group(1))
                    numero = int(match.group(2))
                    serie = obtener_serie_por_poster(mensaje.reply_to_msg_id)
                    if serie:
                        guardar_capitulo(serie[0], temporada, numero, mensaje.id)
                        continue

        # CASO 3: ES UNA IMAGEN QUE RESPONDE A UN VIDEO (MINIATURA)
        if (mensaje.photo or mensaje.file) and mensaje.reply_to_msg_id:
            # Verificamos si el mensaje al que responde es un video de nuestra BD
            conexion = obtener_conexion()
            cursor = conexion.cursor()
            cursor.execute("SELECT id FROM Capitulo WHERE video_message_id = ?", (mensaje.reply_to_msg_id,))
            capitulo_encontrado = cursor.fetchone()
            conexion.close()

            if capitulo_encontrado:
                actualizar_thumbnail_capitulo(mensaje.reply_to_msg_id, mensaje.id)
                
    print("\n✅ Escaneo finalizado. Base de datos actualizada.")

if __name__ == "__main__":
    with cliente:
        cliente.loop.run_until_complete(main())