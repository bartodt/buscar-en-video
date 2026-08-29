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

- **Busca sobre los subtítulos automáticos de YouTube**, que no son perfectos. Si YouTube
  entendió mal una palabra —pasa seguido con nombres propios y apellidos— esa palabra no
  se va a encontrar. Si no aparece algo que jurás que se dijo, probá con otra palabra de
  la misma frase.

- **Modo preciso (IA):** tildá **"Transcribir el audio con IA (WhisperX)"** y en vez de
  leer los subtítulos de YouTube, baja el audio y lo transcribe con **whisperx**. Sirve
  para dos cosas:

  - **Encuentra lo que YouTube escribió mal** — nombres propios y apellidos, sobre todo.
  - **Marca el segundo exacto**, no el arranque de la línea de subtítulo. Y muestra
    *todas* las veces que se dijo la palabra, incluso dos seguidas.

  El precio es el tiempo: baja el audio entero y lo pasa por el modelo, así que son
  **varios minutos** según lo largo del video (la ventana del navegador te va mostrando
  cuánto lleva). La primera vez baja el modelo `medium`, ~1,5 GB. Una vez transcripto, el
  video queda en caché y las búsquedas siguientes son instantáneas.

- **"Si no hay subtítulos, transcribir con IA"** es la versión moderada: usa los
  subtítulos de YouTube si existen, y solo cae en la transcripción cuando el video no
  tiene ninguno.

- Si YouTube te corta con un mensaje de que esperes, es porque le hiciste muchos pedidos
  seguidos. Esperá un minuto y seguí.

## Detalles técnicos

Servidor local en Python (solo librería estándar) que llama a `yt-dlp` para bajar los
subtítulos en formato VTT, los limpia de las repeticiones típicas de los subtítulos
automáticos, y busca sobre el texto corrido con un mapa de posición → segundo, para que
las frases partidas entre dos subtítulos también se encuentren.

El modo IA usa el mismo mapa, pero armado **palabra por palabra** con los tiempos que
alinea whisperx contra el audio — de ahí sale el segundo exacto. Corre el `whisperx` del
`.venv` de esta carpeta como un proceso aparte, así que el servidor en sí sigue sin
dependencias. Las transcripciones se guardan en `~/.cache/buscar-en-video/<id>.whisperx.json`.

Escucha solo en `127.0.0.1:8765`, así que no queda expuesto en la red.

```
app.py          servidor y lógica
index.html      la interfaz
start.command   el lanzador de doble clic
```
