# Cómo funciona por dentro

Notas técnicas. Para usar la app no hace falta leer nada de esto: eso está en el
`README.md`. Para instalarla, `INSTALAR.md`; para armar el `.dmg`, `DISTRIBUIR.md`.

Servidor local en Python (solo librería estándar) que llama a `yt-dlp` para bajar los
subtítulos en formato VTT, los limpia de las repeticiones típicas de los subtítulos
automáticos, y busca sobre el texto corrido con un mapa de posición → segundo, para que
las frases partidas entre dos subtítulos también se encuentren.

El mapa es **palabra por palabra** en los dos modos. Los subtítulos automáticos traen el
tiempo de cada palabra adentro del propio cue (`hola<00:00:01.359><c> mundo</c>`) y el
parser lo aprovecha; el modo IA arma el mismo mapa con lo que alinea whisperx contra el
audio. whisperx corre como un proceso aparte, así que el servidor en sí sigue sin
dependencias. Las transcripciones se guardan en
`~/.cache/buscar-en-video/<id>.whisperx.json` junto con el JSON crudo del modelo: si
cambia cómo se arman los cues se rehacen solos, sin volver a transcribir.

Escucha solo en `127.0.0.1:8765` y además rechaza los pedidos que no vengan de esa misma
página, así que ninguna web que visites puede hacerlo trabajar por atrás.

## Las dos formas en que se distribuye

La misma `app.py` corre en dos empaquetados, y `_comando_whisperx()` es lo que los une:
busca whisperx en tres lugares (adentro del bundle, en el `.venv` del proyecto, o suelto
en el PATH) y lo invoca siempre como `python -m whisperx`, nunca por el script
`bin/whisperx`, que lleva la ruta del intérprete escrita en el shebang y se rompe en
cuanto la carpeta cambia de lugar.

- **`Buscar en video.app`** — el bundle autocontenido que recibe la persona. Trae el
  intérprete, `pylibs` (whisperx y torch como directorio plano, no un venv), `yt-dlp` y
  `ffmpeg` con sus dylibs reescritas a `@executable_path`. No busca nada en la máquina.
  Lo arma `construir-app.sh`; el detalle está en `DISTRIBUIR.md`.
- **La carpeta con `start.command`** — la instalación desde el código, para desarrollo.
  whisperx sale del `.venv` y `yt-dlp`/`ffmpeg` del PATH.

El bundle no tiene ninguna ventana de terminal, y eso obligó a dos cosas que en la versión
de `start.command` no hacían falta: `/api/progreso`, que publica etapa y porcentaje para
que la página los muestre (antes el único avance visible era el `Progress:` de whisperx en
la ventana negra), y `/api/apagar`, que es la única forma que tiene la persona de cerrar el
motor. Los errores de arranque van a `~/Library/Logs/buscar-en-video.log`.

```
app.py                  servidor y lógica
index.html              la interfaz
start.command           lanzador de doble clic de la instalación desde el código
construir-app.sh        arma Buscar en video.app y el .dmg
herramientas/icono.py   genera el .icns sin dependencias gráficas
test_app.py             tests del parseo y la búsqueda
requirements.txt        whisperx, para el modo IA (bundle y .venv por igual)
requirements.lock.txt   el entorno exacto, por si la instalación normal falla

README.md               para quien usa la app: instalar y usar
INSTALAR.md             para el asistente de IA que la instala
DISTRIBUIR.md           para quien arma el .dmg
CLAUDE.md               ruteo: le dice al asistente que lea INSTALAR.md
ARQUITECTURA.md         este archivo
```
