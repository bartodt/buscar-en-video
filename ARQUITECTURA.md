# Cómo funciona por dentro

Notas técnicas. Para usar la app no hace falta leer nada de esto: eso está en el
`README.md`. Para instalarla, `INSTALAR.md`.

Servidor local en Python (solo librería estándar) que llama a `yt-dlp` para bajar los
subtítulos en formato VTT, los limpia de las repeticiones típicas de los subtítulos
automáticos, y busca sobre el texto corrido con un mapa de posición → segundo, para que
las frases partidas entre dos subtítulos también se encuentren.

El mapa es **palabra por palabra** en los dos modos. Los subtítulos automáticos traen el
tiempo de cada palabra adentro del propio cue (`hola<00:00:01.359><c> mundo</c>`) y el
parser lo aprovecha; el modo IA arma el mismo mapa con lo que alinea whisperx contra el
audio. whisperx corre desde el `.venv` de esta carpeta como un proceso aparte, así que el
servidor en sí sigue sin dependencias. Las transcripciones se guardan en
`~/.cache/buscar-en-video/<id>.whisperx.json` junto con el JSON crudo del modelo: si
cambia cómo se arman los cues se rehacen solos, sin volver a transcribir.

Escucha solo en `127.0.0.1:8765` y además rechaza los pedidos que no vengan de esa misma
página, así que ninguna web que visites puede hacerlo trabajar por atrás.

```
app.py                  servidor y lógica
index.html              la interfaz
start.command           el lanzador de doble clic
test_app.py             tests del parseo y la búsqueda
requirements.txt        lo que va en el .venv para el modo IA
requirements.lock.txt   el entorno exacto, por si la instalación normal falla

README.md               para quien usa la app
INSTALAR.md             para el asistente de IA que la instala
CLAUDE.md               ruteo: le dice al asistente que lea INSTALAR.md
ARQUITECTURA.md         este archivo
```
