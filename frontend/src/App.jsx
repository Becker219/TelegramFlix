import { useEffect, useState } from 'react'
import './App.css'
const API_URL =import.meta.env.VITE_API_URL

function App() {
  const [series, setSeries] = useState([])
  const [serieSeleccionada, setSerieSeleccionada] = useState(null)
  const [capitulos, setCapitulos] = useState([])
  const [capituloReproduciendo, setCapituloReproduciendo] = useState(null)
  const [sincronizando, setSincronizando] = useState(false);

  const obtenerCatalogo = () => {
    fetch(`${API_URL}/catalogo`)
      .then(response => response.json())
      .then(data => setSeries(data.series))
      .catch(error => console.error("Error conectando al servidor:", error))
  }

  useEffect(() => {
    window.__onGCastApiAvailable = (isAvailable) => {
      if (isAvailable) {
        window.cast.framework.CastContext.getInstance().setOptions({
          // Usamos el reproductor estándar de Google para MP4
          receiverApplicationId: window.chrome.cast.media.DEFAULT_MEDIA_RECEIVER_APP_ID,
          autoJoinPolicy: window.chrome.cast.AutoJoinPolicy.ORIGIN_SCOPED
        });
      }
    };
  }, []);

  const seleccionarSerie = (serie) => {
    // 1. Guardar la posición exacta de la pantalla en este momento
    sessionStorage.setItem('posicionScroll', window.scrollY);
    
    setSerieSeleccionada(serie)
    fetch(`${API_URL}/capitulos/${serie.id}`)
      .then(response => response.json())
      .then(data => setCapitulos(data.capitulos))
      .catch(error => console.error("Error trayendo capítulos:", error))
  }

  // 2. La función que dispara la película a la TV
  const transmitirAlTelevisor = () => {
    // Verificamos si el usuario ya se conectó a una TV usando el botón
    const castSession = window.cast.framework.CastContext.getInstance().getCurrentSession();

    if (castSession) {
      const videoUrl = `${API_URL}/stream/${capituloReproduciendo.id}`;
      const mediaInfo = new window.chrome.cast.media.MediaInfo(videoUrl, 'video/mp4');

      // Le pasamos metadatos para que el nombre de la serie salga en la pantalla de la TV
      const metadata = new window.chrome.cast.media.GenericMediaMetadata();
      metadata.title = `Episodio ${capituloReproduciendo.numero}`;
      metadata.subtitle = serieSeleccionada?.titulo || "TelegramFlix";
      mediaInfo.metadata = metadata;

      const request = new window.chrome.cast.media.LoadRequest(mediaInfo);
      
      castSession.loadMedia(request).then(
        () => console.log('Transmisión enviada con éxito a la TV'),
        (error) => alert('Error enviando el video: ' + JSON.stringify(error))
      );
    } else {
      alert("Primero conéctate a un televisor usando el ícono de Cast");
    }
  };

  // Función 1: Para el logo 
  const irAlInicio = () => {
    setSerieSeleccionada(null)
    setCapituloReproduciendo(null)
    window.scrollTo(0, 0);
  }

  // Función 2: Para el botón de "Volver al catálogo"
  const volverAlCatalogo = () => {
    setSerieSeleccionada(null);
    setCapituloReproduciendo(null);
    
    // darle 100 milisegundos a React 
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
      const respuesta = await fetch(`${API_URL}/sincronizar`);
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
      const respuesta = await fetch(`${API_URL}/serie/${serieId}`, {
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
      // Calcular la posición restando la altura del navbar fijo
      const offset = 80;
      const elementPosition = elemento.getBoundingClientRect().top;
      const offsetPosition = elementPosition + window.pageYOffset - offset;
      
      window.scrollTo({
        top: offsetPosition,
        behavior: "smooth"
      });
    }
  };

  // Verificar si hay un scroll guardado en la memoria al cargar la app
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
          
          {/* Solo se muestra el menú de categorías si se esta en la vista principal */}
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
              
              {/* CONTROLES DE CHROMECAST */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '15px' }}>
                
                {/* 1. Botón nativo de Google */}
                <google-cast-launcher style={{ width: '24px', height: '24px', cursor: 'pointer' }}></google-cast-launcher>
                
                {/* 2. Botón para enviar la película una vez conectado */}
                <button onClick={transmitirAlTelevisor} style={{ padding: '8px 15px', background: '#3b82f6', color: 'white', border: 'none', borderRadius: '5px', cursor: 'pointer', fontWeight: 'bold' }}>
                  ▶ Reproducir en TV
                </button>
                
              </div>
            </div>
            <video controls autoPlay playsInline crossOrigin="anonymous" className="video-player">
              <source src={`${API_URL}/stream/${capituloReproduciendo.id}`} type="video/mp4" />
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
                    <img src={`${API_URL}/thumbnail/${cap.id}`} alt={`S${cap.temporada}E${cap.numero}`} className="cap-thumb" />
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
                        <img src={`${API_URL}/poster/${serie.id}`} alt={serie.titulo} className="serie-poster" />
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