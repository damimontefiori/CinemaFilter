# YTS Cinema Filter - IMDb +7 & >500 Votos + Rotten Tomatoes

Aplicación web diseñada para navegar y filtrar el catálogo de **YTS** (`https://en.yts-official.biz/browse-movies`), aplicando un control estricto de calidad que el sitio original no ofrece:

1. **Rating IMDb $\ge 7.0$**: Se descarta cualquier película con nota menor a 7.
2. **Desafío de Calificaciones IMDb**: Solo se incluyen películas con **más de 500 votos reales en IMDb**. Esto descarta falsos estrenos con notas infladas (como notas 8.4 con sólo 20 votos).
3. **Validación Rotten Tomatoes**: Extracción simultánea del **Tomatómetro** (Crítica) y **Popcornómetro** (Audiencia), exigiendo un mínimo de **60%** en ambos.
4. **Enlaces Magnet directos**: Extracción directa de los enlaces torrent/magnet (720p, 1080p, 2160p/4K) con botón de copiado rápido y apertura directa en el cliente torrent.
5. **Autenticación Multi-Clave**: Protección por contraseña mediante variable de entorno `APP_PASSWORDS` para compartir el acceso solo con quien tú decidas.

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

- Si el usuario ingresa cualquiera de esas claves, se le concede acceso inmediato y se mantiene la sesión abierta por 30 días.
- En servicios como **Render** o **Railway**, simplemente configuras `APP_PASSWORDS` en la sección **Environment Variables** del panel de control.

---

## Cómo Ejecutar la Aplicación

Ejecuta el servidor con:
```bash
python app.py
```
O simplemente haciendo doble click en `run.bat`.

Luego abre en tu navegador:
👉 **[http://localhost:5000](http://localhost:5000)**

---

## Características de la WebApp

- **Filtros Personalizables**:
  - **Año**: 2026 (por default), 2025, 2024, 2023, 2022 o cualquier año personalizado.
  - **Género**: Todos (`all`), Acción, Ciencia Ficción, Comedia, Drama, Terror, etc.
  - **Rating Mínimo**: Deslizador desde 5.0 hasta 9.0 (por default 7.0).
  - **Votos Mínimos**: Por default 500 votos.
  - **Modo Rotten Tomatoes**:
    - *Híbrido (Recomendado)*: Exige +60% en tomatómetro y popcornómetro si la película ya tiene ficha en RT; si es un estreno 2026 tan reciente que aún no está en RT, pasa el filtro si cumple con IMDb.
    - *Estricto*: Exige obligatoriamente tener ficha RT con +60% en ambos.
    - *Desactivado*: Muestra las notas de RT de forma informativa.
  - **Páginas a Escanear**: De 1 a 8 páginas de YTS (~20 a 160 películas).
- **Escaneo en Tiempo Real (Server-Sent Events)**:
  - Mira en vivo cómo cada película es consultada en IMDb y evaluada.
  - Barra de progreso interactiva con contadores en directo.
  - Botón de parada de emergencia.
- **Doble Panel de Resultados**:
  - **Aprobadas**: Fichas completas con póster HD, badges de notas ⭐ IMDb (con conteo exacto de votos), 🍅 Tomatómetro, 🍿 Popcornómetro, sinopsis y botones magnet (720p, 1080p, 4K).
  - **Descartadas (Transparencia)**: Tabla detallada con el motivo exacto por el que cada película no superó el filtro (ej. *"Votos en IMDb insuficientes: 19 votos (se requiere >500)"*).
- **Exportación**:
  - Descarga a archivo CSV con títulos, notas, votos, enlaces de IMDb y enlaces magnet principales.
  - Copiado masivo de todos los enlaces magnet al portapapeles.
