# ¿En qué minuto lo dijeron?

Pegás el link de un video de YouTube, escribís una palabra o una frase, y te dice en qué
minuto se dijo — con un link que abre el video justo en ese momento.

## Primera vez

Hace falta instalar **yt-dlp** una sola vez. Abrí la app **Terminal** y pegá esto:

```bash
brew install yt-dlp
```

Si te dice que no conoce el comando `brew`, instalá primero Homebrew desde
[brew.sh](https://brew.sh) y después volvé a correr la línea de arriba.

## Cómo se usa

Doble clic en **`start.command`**.

Se abre una ventana negra de Terminal (dejala abierta, es el motor) y el buscador
aparece solo en el navegador. Cuando terminaste, cerrá la ventana negra.

> La primera vez que hacés doble clic, macOS puede desconfiar del archivo. Si pasa:
> clic derecho sobre `start.command` → **Abrir** → **Abrir** de nuevo. Solo la primera vez.

## Cosas para saber

- **La primera búsqueda de un video tarda unos segundos** porque baja los subtítulos.
  Las siguientes búsquedas sobre el mismo video son instantáneas: quedan guardados en
  `~/.cache/buscar-en-video/`. Podés borrar esa carpeta cuando quieras.

- **No hace falta escribir tildes.** Buscar `senuk` encuentra `Señuk`.

- **Podés buscar frases enteras**, no solo palabras sueltas.

- **"Ver toda la transcripción"** muestra el texto completo del video, cortado en
  bloques con su minuto. Cada bloque es un link que abre el video ahí. Sirve cuando no
  te acordás de la palabra exacta y querés leer por arriba hasta encontrar la parte.
  No hace falta escribir nada en el campo de búsqueda, y respeta el tilde de IA: si
  está marcado, te muestra la transcripción de whisperx en vez de los subtítulos.

- **Te avisa cuando el texto no es de fiar.** Arriba de los resultados, al lado del
  título, aparece una advertencia si los subtítulos son una traducción automática (los
  tiempos están bien, pero las palabras no son las que se dijeron) o si no se pudieron
  refrescar y salieron del caché guardado.

- **Busca sobre los subtítulos automáticos de YouTube**, que no son perfectos. Si YouTube
  entendió mal una palabra —pasa seguido con nombres propios y apellidos— esa palabra no
  se va a encontrar. Si no aparece algo que jurás que se dijo, probá con otra palabra de
  la misma frase.

- **Modo preciso (IA):** tildá **"Transcribir el audio con IA (WhisperX)"** y en vez de
  leer los subtítulos de YouTube, baja el audio y lo transcribe con **whisperx**. Sirve
  para **encontrar lo que YouTube escribió mal** —nombres propios y apellidos, sobre
  todo— y para los videos que no tienen ningún subtítulo.

  El segundo exacto ya no es motivo para usarlo: los subtítulos automáticos de YouTube
  traen el tiempo de cada palabra y el modo normal ahora lo aprovecha.

  El precio es el tiempo: baja el audio entero y lo pasa por el modelo, así que son
  **varios minutos** según lo largo del video (la ventana del navegador te va mostrando
  cuánto lleva). La primera vez baja el modelo `large-v3-turbo`, ~1,5 GB. Una vez
  transcripto, el video queda en caché y las búsquedas siguientes son instantáneas —
  aunque pegues el link en otro formato, porque el caché va por id de video.

- Si YouTube te corta con un mensaje de que esperes, es porque le hiciste muchos pedidos
  seguidos. Esperá un minuto y seguí.

## Detalles técnicos

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
```
