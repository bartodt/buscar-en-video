# ¿En qué minuto lo dijeron?

Pegás el link de un video de YouTube, escribís una palabra o una frase, y te dice en qué
minuto se dijo — con un link que abre el video justo en ese momento.

## Instalación

No hay que instalar nada aparte. Ni Python, ni programas, ni escribir comandos: la app
trae todo adentro.

1. Doble clic en **Buscar en video.dmg**. Se abre una ventana.
2. Arrastrá el ícono **Buscar en video** a la carpeta **Aplicaciones**, que está en esa
   misma ventana.
3. Andá a Aplicaciones y hacé doble clic en **Buscar en video**.

Tarda unos segundos en arrancar la primera vez. Después se abre solo el buscador en tu
navegador y ya podés usarlo.

### La primera vez, macOS va a desconfiar

Es normal y no significa que la app tenga nada malo: macOS avisa así de cualquier
programa que no venga de su tienda. Pasa una sola vez.

Vas a ver un cartel que dice que **no se puede abrir porque Apple no puede comprobar que
esté libre de malware**. Apretá **Aceptar** o **Listo** para sacarlo del medio, y después:

1. Abrí **Ajustes del Sistema** (el engranaje).
2. En la lista de la izquierda, **Privacidad y seguridad**.
3. Bajá hasta abajo. Ahí va a haber un renglón que menciona **"Buscar en video"** con un
   botón **Abrir de todos modos**. Apretalo.
4. Te va a pedir tu contraseña de la Mac o el Touch ID. Confirmá.
5. Volvé a hacer doble clic en la app. Ya no molesta nunca más.

## Cómo se usa

Doble clic en **Buscar en video**, en Aplicaciones. El buscador se abre solo en el
navegador. No hay ninguna ventana que dejar abierta.

Cuando terminás, apretá **Cerrar el buscador** abajo de la página. Si te olvidás no pasa
nada, pero deja el motor prendido: no consume casi nada, y con cerrar el buscador queda
todo apagado.

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
  **varios minutos** según lo largo del video. La página te va mostrando en qué anda y
  cuánto lleva. **La primera vez que lo usás baja el modelo, ~1,9 GB**, y en ese rato
  dice "bajando el modelo de IA" sin avanzar: es la descarga, no está colgado. Pasa una
  sola vez. Después dice "transcribiendo con IA" durante casi toda la espera, y el
  porcentaje aparece recién sobre el final: es whisperx, que no lo informa antes.
  Una vez transcripto, el video queda en caché y las búsquedas
  siguientes son instantáneas — aunque pegues el link en otro formato, porque el caché
  va por id de video.

- Si YouTube te corta con un mensaje de que esperes, es porque le hiciste muchos pedidos
  seguidos. Esperá un minuto y seguí.

## Si algo falla

| Qué pasa | Qué hacer |
|---|---|
| macOS dice que no puede comprobar el archivo | Es el aviso de la primera vez: seguí los pasos de arriba |
| Doble clic y no se abre nada en el navegador | Esperá diez segundos y probá de nuevo. Si sigue igual, entrá a mano a `http://127.0.0.1:8765` |
| "Se cortó la conexión con el buscador" | El motor se apagó. Doble clic en la app otra vez |
| El modo IA dice "preparando el modelo" hace mucho | La primera vez son ~1,9 GB de descarga. Dejalo y volvé en un rato |
| Nada de lo anterior | El registro de errores queda en `~/Library/Logs/buscar-en-video.log`. Pasáselo a quien te dio la app |

---

Si te interesa cómo funciona por dentro, está en `ARQUITECTURA.md`.
Si querés armar el `.dmg` vos mismo, en `DISTRIBUIR.md`.
