import sqlite3

def inicializar_base_de_datos():
    # 1. Nos conectamos al archivo (si no existe, Python lo crea automáticamente)
    conexion = sqlite3.connect("database.db")
    
    # Activamos el soporte para Llaves Foráneas (Foreign Keys) en SQLite
    conexion.execute("PRAGMA foreign_keys = ON;")
    
    cursor = conexion.cursor()

    # 2. Creamos la tabla Serie
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Serie (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            poster_message_id INTEGER UNIQUE NOT NULL
        )
    ''')

    # 3. Creamos la tabla Capitulo (incluyendo la columna para el thumbnail)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Capitulo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            serie_id INTEGER NOT NULL,
            temporada INTEGER NOT NULL,
            numero INTEGER NOT NULL,
            video_message_id INTEGER UNIQUE NOT NULL,
            thumbnail_message_id INTEGER,
            FOREIGN KEY (serie_id) REFERENCES Serie (id) ON DELETE CASCADE
        )
    ''')

    # 4. Guardamos los cambios y cerramos la conexión
    conexion.commit()
    conexion.close()
    
    print("¡Base de datos y tablas configuradas con éxito!")

if __name__ == "__main__":
    inicializar_base_de_datos()