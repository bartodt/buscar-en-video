# Instalación (instrucciones para el asistente de IA)

Este archivo está escrito para vos, el agente de IA que corre en la Mac de quien recibió
esta carpeta. La persona que te lo pasó no necesariamente sabe programar: **hacé vos la
instalación entera, sin pedirle que abra la Terminal ni que copie comandos.** Al final
dejale la app andando y explicale en dos líneas cómo abrirla la próxima vez.

## Qué es esto

Un servidor local en Python que busca una palabra o frase dentro de un video de YouTube y
devuelve el minuto exacto en que se dijo. Tiene dos modos:

1. **Subtítulos** (el normal) — baja los subtítulos automáticos con `yt-dlp`. Rápido.
2. **Modo preciso con IA** — baja el audio y lo transcribe con `whisperx`. Lento, pero
   encuentra lo que YouTube escribió mal y marca el segundo exacto.

El servidor en sí (`app.py`) usa **solo la librería estándar de Python**. No instales
nada con `pip` en el Python del sistema. `whisperx` vive aparte, en un `.venv` dentro de
esta misma carpeta, y `app.py` lo invoca como un proceso externo (ver `_binario_whisperx()`
en `app.py`, que busca `./.venv/bin/whisperx` y si no está cae a `shutil.which`).

## Antes de empezar

- **Lo primero: confirmá que la máquina sea una Mac.**

  ```bash
  uname -s   # tiene que decir Darwin
  ```

  Todo lo que sigue es de macOS y no existe en otro lado: `brew`, `open`, `xattr` y el
  propio `start.command`, que es un lanzador de doble clic de Finder. Si `uname -s` no
  dice `Darwin` (o directamente estás en Windows), **no improvises un equivalente ni
  instales nada**: pará acá y decile a la persona exactamente esto:

  > "Esta app por ahora anda solo en Mac, y esta computadora no es una Mac. No hay nada
  > roto ni hiciste nada mal. Avisale a quien te pasó la carpeta, que él va a saber."

- **La carpeta `.venv` no viene incluida y no debe copiarse de otra Mac.** Pesa ~1 GB y
  los binarios adentro tienen rutas absolutas al usuario original. Hay que crearla acá.
- Verificá la arquitectura (`uname -m`): `arm64` es Apple Silicon, `x86_64` es Intel. Los
  dos andan; todo corre en CPU, no se usa GPU.
- Espacio en disco necesario: **~3,5 GB** (≈1 GB el `.venv`, ≈1,9 GB los modelos que se
  bajan la primera vez que se usa el modo IA). Comprobalo antes de bajar nada, así no te
  quedás sin espacio a mitad de una descarga de 1 GB:

  ```bash
  df -h .
  ```

  La cuarta columna es lo libre. **Si quedan menos de 5 GB, no arranques**: la descarga de
  1 GB del Paso 3 se corta a mitad y el `.venv` queda a medio instalar. Pará y decile esto:

  > "Antes de seguir necesito que hagas lugar en el disco: la app ocupa unos 4 GB y ahora
  > mismo no entran. Vaciá la Papelera y borrá videos o archivos grandes que no uses, y
  > avisame cuando termines."

## Paso 0 — Pararte en la carpeta correcta

Todo lo que sigue asume que estás **parado en la carpeta que contiene `app.py`**, y varios
pasos se rompen en silencio si no lo estás: `uv venv` te crea el `.venv` un nivel más
arriba y después `app.py` no lo encuentra, porque lo busca en `RAIZ/.venv/bin/whisperx`
(ver `_binario_whisperx()`).

Ojo con esto: la persona bajó un ZIP de GitHub y lo descomprimió, así que la carpeta se
llama algo como **`buscar-en-video-main`** (con el sufijo de la rama) y está adentro de
Descargas. Si te señaló "la carpeta", puede tranquilamente haberte señalado `Descargas` o
la carpeta que envuelve a la buena. No lo adivines, buscá `app.py`:

```bash
for d in ~/Downloads ~/Desktop ~/Descargas ~/Escritorio ~/Documents; do
  [ -d "$d" ] && find "$d" -maxdepth 3 -name app.py 2>/dev/null
done
```

(El `for` con el `[ -d ]` no es adorno: `find` sobre una carpeta que no existe sale con
error, y en un macOS en inglés `~/Descargas` y `~/Escritorio` no existen.)

Y hacé `cd` al directorio que lo contiene antes de seguir. Confirmá que estás bien:

```bash
pwd && ls app.py index.html start.command requirements.txt
```

Si eso falla, no sigas: o estás en el lugar equivocado, o el ZIP se descomprimió a medias.

### Y movela ahora, antes de instalar nada

No trabajes sobre `~/Downloads/buscar-en-video-main`. Ese nombre no lo eligió la persona, la
carpeta de Descargas se vacía o se desordena, y en un rato va a tener el `.venv` adentro:
~1 GB que alguien va a borrar por error.

Movela **ahora**, antes del Paso 3, y no después. Los venv guardan rutas absolutas: el
shebang de `.venv/bin/whisperx` apunta a la carpeta donde se creó. Si movés después, el
binario **sigue existiendo** —así que `app.py` lo encuentra igual— pero explota con
`bad interpreter`, y como el Paso 5 no prueba el modo IA, la instalación te va a dar toda
verde con la IA rota. Mover ahora cuesta un segundo; mover después cuesta borrar el `.venv`
y volver a bajar 1 GB.

El destino es `~/Applications/buscar-en-video`. Usá ese nombre en inglés aunque el Finder
de la persona esté en español: `~/Applications` es la carpeta que macOS ya muestra como
"Aplicaciones", y si creás una `~/Aplicaciones` aparte la persona termina con dos carpetas
que en pantalla se llaman igual.

El `if` tampoco es adorno: si el destino ya existe (un intento anterior tuyo, por ejemplo)
`mv` **no falla, mete la carpeta adentro** y todas las rutas de acá en adelante quedan mal.

```bash
mkdir -p ~/Applications
if [ -e ~/Applications/buscar-en-video ]; then
  echo "OJO: ya hay algo en ~/Applications/buscar-en-video — no lo piso"
else
  mv "$(pwd)" ~/Applications/buscar-en-video
fi
cd ~/Applications/buscar-en-video
pwd && ls app.py index.html start.command requirements.txt
```

Si te avisó que ya existía: es una instalación anterior a medio hacer. Fijate si
`~/Applications/buscar-en-video/.venv/bin/whisperx --help` anda. Si anda, seguí desde el
Paso 4 y listo. Si no anda o no está, borrá esa carpeta vieja (`rm -rf`) y repetí el `mv`.

### Ojo: el `mv` te mueve el piso a vos

La carpeta donde estabas parado dejó de existir, y muchas herramientas de shell arrancan
cada comando nuevo en el directorio original: la invocación siguiente te va a fallar con
`No such file or directory` o con `shell-init: error retrieving current directory`, y el
`cd` del bloque de arriba no sobrevive de un comando al otro. **Eso no es el ZIP roto ni el
`mv` fallado**, y no lo diagnostiques como un problema de la instalación.

De acá en adelante, empezá **cada** comando parándote de nuevo:

```bash
cd ~/Applications/buscar-en-video || exit 1
```

Todo lo que sigue es sobre esta ruta nueva.

## Paso 1 — Homebrew

Primero fijate si ya está. Que el chequeo **hable siempre**: si encadenás los `[ -x ]` con
`||`, el comando sale con 0 y no imprime nada cuando brew existe, y "no imprimió nada" se
lee igual que "no está" — terminás lanzando el instalador y pidiéndole la contraseña a la
persona al vicio.

```bash
if BREW=$(command -v brew || ls /opt/homebrew/bin/brew /usr/local/bin/brew 2>/dev/null | head -1) && [ -n "$BREW" ]; then
  echo "brew ya está en $BREW"
else
  echo "falta brew"
fi
```

Si dice que ya está, saltá al Paso 2 (asegurándote antes de tenerlo en el PATH de tu
sesión, abajo).

Si no aparece, **este es el único paso de toda la instalación que no podés hacer solo.**
El instalador de Homebrew pide la contraseña de la Mac por `sudo`, y `sudo` exige una
terminal de verdad: si lo lanzás desde tu propia herramienta de shell se queda colgado
esperando una contraseña que nadie va a poder escribir, hasta que se corte por timeout.

**Antes de lanzar nada**, decile a la persona exactamente esto:

> "Voy a instalar una herramienta que la app necesita. Se va a abrir una ventana negra con
> un montón de texto en inglés. Te va a pedir dos cosas, en este orden:
>
> **Primero, que aprietes Enter** para empezar (el texto dice algo como "press RETURN").
> Apretá Enter y nada más.
>
> **Después, la contraseña de tu Mac** —la misma que usás para desbloquearla—. Escribila y
> apretá Enter.
>
> Ojo con una cosa que asusta: **mientras escribís la contraseña no vas a ver nada en la
> pantalla**, ni letras ni puntitos ni asteriscos. Es así a propósito, no está colgado.
> Escribila igual y apretá Enter.
>
> Después dejá esa ventana quieta unos minutos hasta que deje de moverse, y avisame."

Los dos prompts son del instalador oficial de Homebrew, en ese orden: primero
`wait_for_user`, después el `sudo`. **No intentes saltear el Enter con `NONINTERACTIVE=1`**:
en ese modo el instalador necesita un `sudo` sin contraseña o ya cacheado, y si no lo tiene
aborta — terminás peor que antes.

Recién ahí lanzalo en una Terminal propia, que es lo que le da el `sudo` su ventana:

```bash
cat > /tmp/instalar-homebrew.sh <<'EOF'
#!/bin/bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
echo
echo "Listo. Ya podés volver con el asistente y cerrar esta ventana."
EOF
chmod +x /tmp/instalar-homebrew.sh
open -a Terminal /tmp/instalar-homebrew.sh
```

La Terminal tarda unos segundos en aparecer. **Esperá a que la persona te confirme que
terminó** —no sigas por tu cuenta— y después comprobalo vos:

```bash
if [ -x /opt/homebrew/bin/brew ] || [ -x /usr/local/bin/brew ]; then
  echo "brew instalado"
else
  echo "brew NO quedó instalado — algo salió mal en la ventana de la Terminal"
fi
```

Si la persona te dice que se equivocó de contraseña o que la ventana cerró con error,
volvé a correr el mismo `open -a Terminal`: el instalador se puede repetir sin romper nada.

Ya instalado, `brew` no está todavía en el PATH de *tu* sesión. Agregalo antes de seguir
(la primera rama es Apple Silicon, la segunda Intel).

**No lo hagas con un `||` entre los dos `eval`.** Si la ruta de Apple Silicon no existe, la
sustitución de comando queda vacía y `eval ""` **sale con 0**, así que el fallback de Intel
no corre nunca: en una Mac Intel te quedás sin `brew` en el PATH y el Paso 2 muere con
"command not found".

```bash
if [ -x /opt/homebrew/bin/brew ]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
elif [ -x /usr/local/bin/brew ]; then
  eval "$(/usr/local/bin/brew shellenv)"
else
  echo "no encontré brew en ninguna de las dos rutas"
fi
command -v brew   # tiene que imprimir una ruta
```

## Paso 2 — Dependencias del sistema

```bash
brew install yt-dlp ffmpeg uv
```

- `yt-dlp` — baja subtítulos y audio. **Obligatorio para los dos modos.**
- `ffmpeg` — convierte el audio a WAV 16 kHz mono. Obligatorio **solo para el modo IA**,
  pero instalalo igual.
- `uv` — arma el entorno de Python. Alternativa: `curl -LsSf https://astral.sh/uv/install.sh | sh`.

Falta `python3`, que es lo que corre el servidor. Sirve cualquier 3.8+.

**No lo compruebes con `command -v python3`.** En una Mac sin las herramientas de línea de
comandos de Xcode, `/usr/bin/python3` **existe igual**: es un stub de `xcrun` —el mismo
binario que `/usr/bin/git` y `/usr/bin/clang`, comparten inodo— así que `command -v`
devuelve 0 y vos concluís que hay Python donde no hay. Al invocarlo salta el diálogo
gráfico de "instalar herramientas de línea de comandos", justo lo que acá abajo se te pide
evitar.

Instalalo con Homebrew, que ya tenés del Paso 1, no necesita que la persona haga nada, y
te deja un `python3` propio que queda antes que el stub en el PATH:

```bash
brew install python
```

Y comprobalo **corriéndolo**, no con `command -v`. Chequealo también en un login shell, que
es el que va a usar el doble clic de `start.command`:

```bash
python3 -V                            # tiene que imprimir una versión, no un error
zsh -lc 'command -v python3 && python3 -V'   # lo que va a ver el doble clic
```

Evitá `xcode-select --install`: abre un diálogo gráfico que tenés que pedirle a la persona
que acepte, y encima tarda. Si igual terminás yendo por ahí, avisale que va a aparecer una
ventana pidiendo instalar "herramientas de línea de comandos" y que tiene que apretar
**Instalar**.

`start.command` manda a python.org si no encuentra `python3`, pero eso es el mensaje de
último recurso para cuando la persona está sola: vos usá `brew install python`.

## Paso 3 — El entorno de whisperx

Desde **esta carpeta** (la que contiene `app.py`):

```bash
uv venv --python 3.12
uv pip install -r requirements.txt
```

Si eso falla porque alguna dependencia de whisperx sacó una versión que rompe, instalá
el entorno exacto que sí anda. **Borrá el `.venv` primero**: el intento fallido dejó
paquetes a medio instalar adentro, y el lock sobre esa base puede quedar en un estado que
resuelve bien pero explota al correr.

```bash
rm -rf .venv
uv venv --python 3.12
uv pip install -r requirements.lock.txt
```

Notas que importan:

- **Fijá Python 3.12.** `whisperx` todavía no soporta 3.13 y la instalación falla si `uv`
  elige la versión más nueva por su cuenta. Si `uv` no encuentra un 3.12 en la máquina, lo
  baja solo.
- La versión `3.8.6` es la verificada andando con esta app. Si falla la resolución de
  dependencias, probá `uv pip install whisperx` sin pin y avisá qué versión quedó.
- Son ~1 GB de descarga (`torch`, `ctranslate2`, `transformers`). Tarda unos minutos.
- **No hace falta ningún token de Hugging Face.** La app no usa diarización, así que
  ignorá cualquier instrucción de la documentación de whisperx sobre `--hf_token` o sobre
  aceptar los términos de `pyannote`.

El resultado esperado es que exista `.venv/bin/whisperx`.

## Paso 4 — Permisos del lanzador

Desde la carpeta del proyecto:

```bash
chmod +x start.command
xattr -dr com.apple.quarantine . 2>/dev/null || true
```

El `xattr` va **con `-r` y sobre la carpeta entera**, no sobre `start.command` solo: cuando
el navegador baja el ZIP le pone la marca de cuarentena, y al descomprimir esa marca queda
en todo lo que salió adentro. Limpiar únicamente el lanzador deja marcados a `app.py` y a
`index.html`, y el bloqueo reaparece igual. Sin esto, el primer doble clic lo frena
Gatekeeper.

El `chmod` es por las dudas: el ZIP de GitHub **suele** conservar el permiso de ejecución,
pero depende de con qué se descomprima, y se pierde seguro si la carpeta viajó por mail o
WhatsApp. Correrlo no cuesta nada.

Si aun así aparece el bloqueo, la persona tiene que hacer
**clic derecho sobre `start.command` → Abrir → Abrir**, o autorizarlo en
**Ajustes del Sistema → Privacidad y seguridad**.

## Paso 5 — Verificación

La regla de este paso: **no declares "quedó andando" hasta que la prueba real del modo
subtítulos haya devuelto resultados.** Todo lo de abajo puede dar verde con la app
igualmente inservible para la persona.

### 5.1 — Dependencias

**No uses `command -v yt-dlp ffmpeg`**: con dos nombres devuelve 0 si encuentra
**cualquiera** de los dos, así que te da "dependencias ok" con `ffmpeg` ausente y el modo IA
muerto. Uno por uno:

```bash
for b in yt-dlp ffmpeg; do
  if command -v "$b" >/dev/null; then echo "ok: $b"; else echo "FALTA: $b"; fi
done
./.venv/bin/whisperx --help >/dev/null && echo "ok: whisperx"
```

El `whisperx --help` puede tardar hasta unos 20 segundos la primera vez porque importa
torch (después, con el caché caliente, son 3): no está colgado, y si tu herramienta de shell
tiene un timeout corto, subilo para este comando.

### 5.2 — Tests del parseo y la búsqueda

No necesitan red ni nada instalado:

```bash
python3 -m unittest test_app
```

`ProcesosHijos.test_al_salir_se_lleva_al_nieto` es **inestable**: mide tiempos reales y
falla por timeout si la máquina está cargada (bajando torch, por ejemplo). Si es el único
que falla, corré los tests de nuevo antes de tocar nada; si pasa en la segunda o tercera
corrida, está bien. **No te pongas a arreglar `app.py`**: no es un problema de instalación.

### 5.3 — El lanzador de verdad

Probá **`start.command`**, no `python3 app.py`. Es lo único que ejercita lo que la persona
va a usar realmente: el permiso de ejecución, la cuarentena, el arranque y el `open` del
navegador. Si solo probás `python3 app.py`, el Paso 4 queda sin verificar.

```bash
./start.command &
sleep 4
curl -fs http://127.0.0.1:8765/api/salud
```

Tiene que devolver `{"ok": true}` y además abrirse una pestaña del navegador. Si el
`curl` anda pero la pestaña no aparece, revisá el Paso 4: casi siempre es cuarentena.

**Este servidor tiene que seguir vivo para el 5.4.** Muchas herramientas de shell matan
todo lo que dejaste en segundo plano al terminar cada comando, y entonces el 5.4 te va a
dar "connection refused" y vas a diagnosticar mal. Si te pasa eso, no busques el problema
en la instalación: corré el 5.3 y el 5.4 pegados, en **una sola** invocación de shell, o
lanzá el servidor con `nohup ./start.command >/dev/null 2>&1 & disown`.

### 5.4 — Prueba real del modo subtítulos (la que decide)

Con el servidor levantado del punto anterior. **No inventes un video de memoria**: hace
falta uno con subtítulos automáticos **en español** (es el único idioma que pide la app), y
si elegís uno en otro idioma vas a recibir "no tiene subtítulos en español" y creer que la
instalación está rota. Dejá que `yt-dlp` te consiga uno:

```bash
ID=$(yt-dlp --skip-download --print id "ytsearch1:entrevista completa en español" | head -1)
echo "video elegido: $ID"
curl -s -X POST http://127.0.0.1:8765/api/buscar \
  -H 'Content-Type: application/json' \
  -d "{\"url\":\"https://www.youtube.com/watch?v=$ID\",\"consulta\":\"que\"}"
```

La consulta es `que` a propósito: es una palabra que aparece en cualquier video hablado en
español, así que si no viene ningún resultado el problema es la instalación y no la
elección de la palabra.

Tiene que venir un JSON con `"fuente": "subtitulos"` y una lista de `resultados` no vacía.

**Si en vez de eso viene `"YouTube te limitó por hacer muchos pedidos seguidos"`**, no lo
despaches como "esperá un minuto". Es un 429 de YouTube sobre el endpoint de subtítulos y
es frecuente; el punto es que **desde acá no podés distinguir una instalación sana de una
rota**. Hacé esto:

1. Esperá 60 segundos y reintentá. Hasta tres veces, con otro video la última.
2. Si sigue dando 429, comprobá que el problema sea de YouTube y no tuyo:

   ```bash
   yt-dlp --skip-download --write-auto-subs --sub-langs 'es.*' --sub-format vtt \
     -o '/tmp/prueba.%(ext)s' 'https://www.youtube.com/watch?v=VIDEO_ID'
   ```

   Si `yt-dlp` a mano también da 429, la instalación está bien y el bloqueo es de red.
3. En ese caso **no le digas a la persona que quedó andando**. Decile la verdad:

   > "Quedó todo instalado, pero no lo pude probar de punta a punta: YouTube está
   > bloqueando pedidos desde esta conexión en este momento. Probalo vos en un rato con
   > doble clic; si te sigue diciendo que esperes, andá probando cada tanto. No hay que
   > reinstalar nada."

**No pruebes el modo IA como parte de la instalación.** La primera corrida baja ~1,9 GB de
modelos (`large-v3-turbo` de transcripción, ~1,5 GB, y el de alineación en español, ~360 MB)
y transcribir un video lleva varios minutos. Dejá esa descarga para la primera vez que la
persona tilde la opción en la interfaz, y avisale de antemano que esa primera vez tarda.

Cuando termines, cerrá el servidor de prueba. Ojo con esto: `pkill -f "python3 app.py"` **no
sirve**, porque el proceso queda en la tabla con la ruta real del binario de Python
(`.../Python.app/Contents/MacOS/Python app.py`) y el patrón no matchea nunca. Sale sin decir
nada y el servidor te queda vivo. Cerralo por el puerto, que además se lleva puesto a
cualquier otra copia:

```bash
lsof -ti tcp:8765 | xargs kill
```

El uso normal es por doble clic.

## Paso 6 — Dejarle la app a mano

La carpeta ya quedó en su lugar definitivo desde el Paso 0, así que acá no hay que mover
nada. Falta sólo el acceso en el Escritorio, que es por donde la persona la va a abrir:

```bash
ln -sf ~/Applications/buscar-en-video/start.command ~/Desktop/"Buscar en video.command"
```

Es un enlace, no una copia, y el doble clic funciona igual: Finder lo resuelve antes de
ejecutarlo, así que `start.command` se para en la carpeta buena y no en el Escritorio.

Para cerrar, decile a la persona dónde quedó y cómo se abre:

> "Listo, ya está andando. Te dejé en el Escritorio un archivo que se llama **Buscar en
> video**: doble clic ahí y se abre. Se va a abrir una ventana negra con letras: no la
> cierres mientras lo usás, es el motor. El buscador se abre solo en tu navegador. Cuando
> terminás, cerrás la ventana negra y listo. Si alguna vez se te cierra sin querer, no
> pasa nada: doble clic de nuevo."

## Cómo se usa después

Doble clic en **Buscar en video**, el acceso del Escritorio (o en `start.command` dentro de
la carpeta, es lo mismo). Se abre una ventana negra de Terminal (es el motor, tiene que
quedar abierta) y el buscador aparece solo en el navegador, en `http://127.0.0.1:8765`.
Para cerrarlo, se cierra la ventana negra.

El detalle de la interfaz y de los dos modos está en el `README.md` de esta carpeta, que
es lo único que la persona necesita leer.

## Si algo falla

| Síntoma | Causa y arreglo |
|---|---|
| `start.command` se abre como texto | Falta el permiso: `chmod +x start.command` |
| macOS dice que no puede verificar el archivo | Cuarentena: clic derecho → Abrir → Abrir |
| `Address already in use` al arrancar | El puerto 8765 ya está ocupado, probablemente por otra copia del servidor corriendo. Cerrala por el puerto: `lsof -ti tcp:8765 \| xargs kill`. (`pkill -f "python3 app.py"` **no matchea**: el proceso queda con la ruta real del binario de Python.) |
| El `.venv` dejó de andar después de mover la carpeta | Los venv guardan rutas absolutas: `rm -rf .venv` y repetí el Paso 3 desde la ubicación nueva |
| La app dice "No encontré whisperx" | El Paso 3 no terminó bien. Verificá que exista `.venv/bin/whisperx` y que el `.venv` esté **dentro de esta carpeta** |
| `whisperx` instala pero explota al correr | Casi siempre es la versión de Python. Confirmá `.venv/bin/python -V` → tiene que decir 3.12.x. Si dice 3.13, borrá el `.venv` y repetí el Paso 3 con `--python 3.12` |
| El modo IA falla al bajar el audio | Falta `ffmpeg`: `brew install ffmpeg` |
| YouTube responde que se espere | Un 429. En el uso normal se pasa esperando un minuto. **Durante la instalación no lo despaches**: seguí el procedimiento del Paso 5.4 |
| El navegador no se abre solo con doble clic | Cuarentena sin limpiar: repetí el Paso 4 con `xattr -dr` sobre la carpeta entera |
| Un solo test falla, el del nieto | Es inestable por timing. Corré los tests de nuevo; ver Paso 5.2 |

Las transcripciones y subtítulos se cachean en `~/.cache/buscar-en-video/`; los modelos de
IA en `~/.cache/huggingface/` y `~/.cache/torch/`. Se pueden borrar en cualquier momento,
al costo de volver a bajarlos.

## Versiones verificadas

macOS 15 (arm64) · Python 3.12.14 en el `.venv` · whisperx 3.8.6 · torch 2.8.0 ·
ctranslate2 4.8.1 · faster-whisper 1.2.1 · yt-dlp y ffmpeg de Homebrew.
