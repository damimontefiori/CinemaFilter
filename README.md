# YTS Cinema Filter - IMDb +7 & >500 Votos + Streaming en Navegador & Cast a TV

Aplicación web diseñada para navegar y filtrar el catálogo de **YTS** (`https://en.yts-official.biz/browse-movies`), aplicando un control estricto de calidad que el sitio original no ofrece, con **reproducción en streaming directamente en el navegador** y soporte para **transmitir a Smart TV / Chromecast / AirPlay**:

1. **Rating IMDb $\ge 7.0$**: Se descarta cualquier película con nota menor a 7.
2. **Desafío de Calificaciones IMDb**: Solo se incluyen películas con **más de 500 votos reales en IMDb**, descartando falsos estrenos con notas infladas por pocas personas.
3. **Validación Rotten Tomatoes**: Extracción simultánea del **Tomatómetro** (Crítica) y **Popcornómetro** (Audiencia), exigiendo un mínimo de **60%** en ambos.
4. **Streaming en el Navegador (WebTorrent)**:
   - Mira la película directamente en tu navegador sin esperar a que termine de descargar (reproducción secuencial con buffer en memoria).
   - Métricas P2P en vivo: velocidad de descarga, peers y barra de progreso.
5. **Transmitir a la TV (Cast / AirPlay)**:
   - Botón directo para enviar la transmisión a cualquier **Smart TV, Chromecast, Android TV o Apple TV (AirPlay)** en la misma red Wi-Fi.
6. **Descarga Directa al Disco**:
   - Guarda el archivo `.mp4` en tu carpeta tradicional de Descargas del navegador con 1 clic, sin necesidad de clientes torrent externos.
7. **Descarga Tradicional Magnet / Torrent**:
   - Mantiene intactos los botones para copiar enlaces magnet y abrir en clientes torrent habituales (qBittorrent, uTorrent, etc.) en calidades 720p, 1080p y 4K.
8. **Autenticación Multi-Clave (`APP_PASSWORDS`)**:
   - Protección por contraseña para compartir el acceso solo con quien tú decidas.

---

## Requisitos e Instalación

La aplicación utiliza Python 3 y las librerías `flask`, `requests`, `beautifulsoup4`.

Para instalar dependencias:
```bash
pip install -r requirements.txt
```

---

## Configuración de Claves de Acceso (`APP_PASSWORDS`)

Copia el archivo `.env.example` a `.env`:
```bash
copy .env.example .env
```

Configura tus claves autorizadas separadas por comas en `.env`:
```env
APP_PASSWORDS=miClaveSecreta,amigo1,amigo2
FLASK_SECRET_KEY=clave_secreta_aleatoria_2026
```

---

## Cómo Ejecutar y Acceder desde tu Móvil o PC

### 1. Desde tu PC:
Ejecuta:
```bash
python app.py
```
O haz doble clic en `run.bat`.
Abre en tu navegador: **`http://localhost:5000`**

### 2. Desde tu Móvil en la misma red Wi-Fi:
Cuando la aplicación arranca, muestra la IP local de tu PC (por ejemplo `http://192.168.1.118:5000`):
1. Conecta tu móvil a la misma red Wi-Fi que tu PC.
2. Abre el navegador en tu móvil (Chrome en Android o Safari en iPhone) e ingresa:
   👉 **`http://TU_IP_LOCAL:5000`** (ejemplo: `http://192.168.1.118:5000`)
3. Ingresa tu clave de acceso.
4. Elige una película, presiona **"Ver Película en Navegador"** y luego pulsa **"Transmitir a la TV"** para verla en tu Smart TV o Chromecast.

---

## Cómo Publicar en la Nube (Render.com Gratis)

> [!NOTE]
> **¿Por qué Render en lugar de Netlify o Vercel?**
> Netlify y Vercel son plataformas serverless con un tiempo límite de ejecución de 10 a 15 segundos por petición, lo cual corta las conexiones continuas de Server-Sent Events (SSE) del escáner en tiempo real. **Render.com** (o **Railway.app**) corre servidores Flask completos sin interrupción y ofrece certificado **HTTPS** gratuito, ideal para transmitir desde el móvil.

1. Ingresa a **[dashboard.render.com](https://dashboard.render.com/)** (inicia sesión con GitHub).
2. Haz clic en **New +** $\rightarrow$ **Web Service**.
3. Selecciona tu repositorio: `damimontefiori/CinemaFilter`.
4. Completa:
   - **Name**: `cinemafilter`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python app.py`
5. En **Environment Variables**, agrega:
   - `APP_PASSWORDS` = `tus_claves_separadas_por_comas`
   - `FLASK_SECRET_KEY` = `un_texto_secreto_largo`
6. Haz clic en **Create Web Service**. ¡Listo! Tendrás tu URL HTTPS pública (ej. `https://cinemafilter.onrender.com`) accesible desde tu teléfono desde cualquier lugar.
