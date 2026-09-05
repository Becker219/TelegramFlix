import { useEffect, useState } from 'react'
import './App.css'

function App() {
  const [series, setSeries] = useState([])
  const [serieSeleccionada, setSerieSeleccionada] = useState(null)
  const [capitulos, setCapitulos] = useState([])
  const [capituloReproduciendo, setCapituloReproduciendo] = useState(null)
  const [sincronizando, setSincronizando] = useState(false);

  const obtenerCatalogo = () => {
    fetch('https://telegramflix.onrender.com/catalogo')
      .then(response => response.json())
      .then(data => setSeries(data.series))
      .catch(error => console.error("Error conectando al servidor:", error))
  }

  useEffect(() => {
    obtenerCatalogo()
  }, [])

  const seleccionarSerie = (serie) => {
    // 1. Guardamos la posición exacta de la pantalla en este momento
    sessionStorage.setItem('posicionScroll', window.scrollY);
    
    setSerieSeleccionada(serie)
    fetch(`https://telegramflix.onrender.com/capitulos/${serie.id}`)
      .then(response => response.json())
      .then(data => setCapitulos(data.capitulos))
      .catch(error => console.error("Error trayendo capítulos:", error))
  }

  // Función 1: Para el logo (va hasta arriba)
  const irAlInicio = () => {
    setSerieSeleccionada(null)
    setCapituloReproduciendo(null)
    window.scrollTo(0, 0);
  }

  // Función 2: Para el botón de "Volver al catálogo"
  const volverAlCatalogo = () => {
    setSerieSeleccionada(null);
    setCapituloReproduciendo(null);
    
    // Usamos setTimeout para darle 100 milisegundos a React de volver a dibujar 
    // el catálogo en pantalla antes de intentar mover el scroll
    setTimeout(() => {
      const scrollGuardado = sessionStorage.getItem('posicionScroll');
      if (scrollGuardado) {
        window.scrollTo(0, parseInt(scrollGuardado));
      }
    }, 100);
  };

  const sincronizarBiblioteca = async () => {
    setSincronizando(true);
    try {
      const respuesta = await fetch("https://telegramflix.onrender.com/sincronizar");
      await respuesta.json();
      obtenerCatalogo(); 
    } catch (error) {
      console.error("Error al sincronizar:", error);
      alert("Hubo un error al sincronizar.");
    }
    setSincronizando(false);
  };

  const eliminarSerie = async (e, serieId) => {
    e.stopPropagation(); 
    if (!window.confirm("¿Seguro que quieres eliminar esta serie de la biblioteca?")) return;
    
    try {
      const respuesta = await fetch(`https://telegramflix.onrender.com/serie/${serieId}`, {
        method: "DELETE"
      });
      if (respuesta.ok) obtenerCatalogo();
    } catch (error) {
      console.error("Error al eliminar:", error);
    }
  };

  const seriesPorCategoria = (series || []).reduce((grupos, serie) => {
    const categoria = serie.categoria || 'General';
    if (!grupos[categoria]) grupos[categoria] = [];
    grupos[categoria].push(serie);
    return grupos;
  }, {});

  // Función para desplazamiento suave hacia la categoría
  const irACategoria = (categoria) => {
    const elemento = document.getElementById(`cat-${categoria}`);
    if (elemento) {
      // Calculamos la posición restando la altura del navbar fijo (aprox 80px)
      const offset = 80;
      const elementPosition = elemento.getBoundingClientRect().top;
      const offsetPosition = elementPosition + window.pageYOffset - offset;
      
      window.scrollTo({
        top: offsetPosition,
        behavior: "smooth"
      });
    }
  };

  // Verificamos si hay un scroll guardado en la memoria al cargar la app
  useEffect(() => {
    const scrollGuardado = sessionStorage.getItem('posicionScroll');
    if (scrollGuardado) {
        window.scrollTo(0, parseInt(scrollGuardado));
    }
  }, []); 

  return (
    <div className="app-container">
      {/* NAVBAR RENOVADO */}
      <header className="navbar">
        <div className="navbar-left">
          <h1 className="logo" onClick={irAlInicio}>
            TelegramFlix
          </h1>
          
          {/* Solo mostramos el menú de categorías si estamos en la vista principal */}
          {!serieSeleccionada && !capituloReproduciendo && (
            <nav className="nav-categorias">
              {Object.keys(seriesPorCategoria).map((categoria) => (
                <button 
                  key={categoria} 
                  className="nav-link" 
                  onClick={() => irACategoria(categoria)}
                >
                  {categoria}
                </button>
              ))}
            </nav>
          )}
        </div>

        <button 
          onClick={sincronizarBiblioteca} 
          disabled={sincronizando}
          className={`btn-actualizar ${sincronizando ? 'cargando' : ''}`}
        >
          <span className="icono-sync">↻</span> 
          {sincronizando ? "Actualizando..." : "Actualizar"}
        </button>
      </header>
      
      <main className="content">
        {capituloReproduciendo ? (
          <div className="player-container">
            <div className="player-header">
              {/* Este botón solo cierra el reproductor y te deja en los episodios */}
              <button className="back-button" onClick={() => setCapituloReproduciendo(null)}>
                ⬅ Volver a episodios
              </button>
              <h2>S{capituloReproduciendo.temporada.toString().padStart(2, '0')}E{capituloReproduciendo.numero.toString().padStart(2, '0')}</h2>
            </div>
            <video controls autoPlay playsInline crossOrigin="anonymous" className="video-player">
              <source src={`https://telegramflix.onrender.com/stream/${capituloReproduciendo.id}`} type="video/mp4" />
            </video>
          </div>
        ) : 
        
        serieSeleccionada ? (
          <div className="capitulos-container">
            {/* Este botón cierra la serie y te devuelve al catálogo en la posición correcta */}
            <button className="back-button" onClick={volverAlCatalogo}>
              ⬅ Volver al catálogo
            </button>
            <h2 className="section-title">Capítulos de {serieSeleccionada.titulo}</h2>
            <div className="capitulos-list">
              {capitulos.map((cap) => (
                <div key={cap.id} className="capitulo-item" onClick={() => setCapituloReproduciendo(cap)}>
                  <div className="cap-thumb-container">
                    <img src={`https://telegramflix.onrender.com/thumbnail/${cap.id}`} alt={`S${cap.temporada}E${cap.numero}`} className="cap-thumb" />
                    <span className="cap-play-icon">▶</span>
                  </div>
                  <div className="cap-info">
                    <span className="cap-numero">Temporada {cap.temporada}</span>
                    <span className="cap-titulo">Episodio {cap.numero}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : 
        
        (
          <div className="catalog">
            {Object.keys(seriesPorCategoria).map((categoria) => (
              <div key={categoria} id={`cat-${categoria}`} className="categoria-section">
                <h2 className="categoria-titulo">{categoria}</h2>
                <div className="series-grid">
                  {seriesPorCategoria[categoria].map((serie) => (
                    <div key={serie.id} className="serie-card" onClick={() => seleccionarSerie(serie)}>
                      
                      <button 
                        className="btn-eliminar-hover" 
                        onClick={(e) => eliminarSerie(e, serie.id)}
                        title="Eliminar serie"
                      >
                        ✕
                      </button>

                      <div className="image-container">
                        <img src={`https://telegramflix.onrender.com/poster/${serie.id}`} alt={serie.titulo} className="serie-poster" />
                        <div className="overlay-play">
                          <span className="play-button-hover">▶</span>
                        </div>
                      </div>
                      <h3 className="serie-title">{serie.titulo}</h3>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  )
}

export default App