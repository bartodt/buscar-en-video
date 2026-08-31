# ¿En qué minuto lo dijeron?

> **¿Sos un asistente de IA y te pidieron instalar esto?** Leé `INSTALAR.md`, que está
> escrito para vos. Este archivo cuenta sólo cómo se *usa* la app, no cómo se instala.

Pegás el link de un video de YouTube, escribís una palabra o una frase, y te dice en qué
minuto se dijo — con un link que abre el video justo en ese momento.

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

---

Si te interesa cómo funciona por dentro, está en `ARQUITECTURA.md`.
