# Instalación (instrucciones para el asistente de IA)

Este archivo está escrito para vos, el agente de IA que corre en la Mac de quien recibió
esto. La persona puede no saber nada de computadoras: **hacé vos la instalación entera,
sin pedirle que abra la Terminal ni que copie comandos.**

Primero fijate qué te dieron, porque los dos caminos no se parecen en nada:

- **Un `.dmg`** (`Buscar en video.dmg`) → **Camino A**. Son tres comandos y no hace falta
  instalar absolutamente nada: la app trae Python, whisperx, yt-dlp y ffmpeg adentro.
- **Una carpeta con `app.py` adentro** → **Camino B**, la instalación desde el código.
  Es la larga.

```bash
uname -s   # tiene que decir Darwin: la app sólo anda en Mac
```

Si eso no dice `Darwin`, **no improvises un equivalente ni instales nada**. Pará acá y
decile a la persona exactamente esto:

> "Esta app por ahora anda solo en Mac, y esta computadora no es una Mac. No hay nada
> roto ni hiciste nada mal. Avisale a quien te pasó la carpeta, que él va a saber."

---

# Camino A — desde el `.dmg`

Buscá el `.dmg`, montalo, copiá la app a Aplicaciones y desmontá:

```bash
DMG=$(find ~/Downloads ~/Desktop ~/Documents -maxdepth 2 -name "Buscar en video*.dmg" 2>/dev/null | head -1)
[ -n "$DMG" ] || echo "no lo encontré: preguntale a la persona dónde lo guardó"
MONTAJE=$(hdiutil attach -nobrowse -readonly "$DMG" | grep -o '/Volumes/.*' | head -1)
cp -R "$MONTAJE/Buscar en video.app" /Applications/
hdiutil detach "$MONTAJE" >/dev/null
```

**Y ahora lo que más le ahorra a la persona:** la app va sin firmar, así que en el primer
doble clic macOS la bloquea y la persona tendría que autorizarla a mano en Ajustes del
Sistema. Vos podés sacarle la marca de cuarentena y que eso no pase nunca:

```bash
xattr -dr com.apple.quarantine "/Applications/Buscar en video.app"
```

Hacelo siempre. Es la diferencia entre "doble clic y anda" y cinco pasos por los Ajustes
del Sistema con una contraseña en el medio.

Probá que arranque de verdad y que responda:

```bash
open "/Applications/Buscar en video.app"
for _ in $(seq 1 40); do curl -fs http://127.0.0.1:8765/api/salud && break; sleep 0.5; done
```

Tiene que imprimir `{"ok": true}` y abrirse una pestaña del navegador. Si no, mirá
`~/Library/Logs/buscar-en-video.log`, que es donde la app escribe sus errores (no tiene
ventana de Terminal donde mirarlos).

Después probá una búsqueda real, que es lo único que confirma que quedó usable. Seguí el
procedimiento de **Prueba real del modo subtítulos**, más abajo — incluido el caso del
429 de YouTube, que es frecuente y no hay que confundir con una instalación rota.

Cuando termine, dejá el buscador abierto y decile esto:

> "Listo, ya está andando. La app se llama **Buscar en video** y está en Aplicaciones:
> doble clic y se abre solita en tu navegador. Cuando terminás de usarla, apretá **Cerrar
> el buscador** abajo de la página. Todo lo demás está explicado en el README."

Eso es todo el Camino A. No sigas leyendo.

---

# Camino B — desde el código

Sólo si no hay `.dmg`. Instala el proyecto para correrlo con `start.command`.

Si además de instalarlo querés **armar el `.dmg`** para no repetir esto nunca más en otra
Mac, está en `DISTRIBUIR.md`.

## Antes de empezar

- **La carpeta `.venv` no viene incluida y no debe copiarse de otra Mac.** Pesa ~1 GB y
  los binarios adentro tienen rutas absolutas al usuario original.
- Espacio en disco: **~3,5 GB**. Comprobalo antes de bajar nada:

  ```bash
  df -h .
  ```

  La cuarta columna es lo libre. **Si quedan menos de 5 GB, no arranques**: la descarga
  de 1 GB del Paso 3 se corta a mitad. Pará y decile esto:

  > "Antes de seguir necesito que hagas lugar en el disco: la app ocupa unos 4 GB y ahora
  > mismo no entran. Vaciá la Papelera y borrá videos o archivos grandes que no uses, y
  > avisame cuando termines."

## Paso 0 — Pararte en la carpeta, y moverla antes de instalar

La persona bajó un ZIP de GitHub, así que la carpeta se llama algo como
**`buscar-en-video-main`**. No lo adivines, buscá `app.py`:

```bash
for d in ~/Downloads ~/Desktop ~/Descargas ~/Escritorio ~/Documents; do
  [ -d "$d" ] && find "$d" -maxdepth 3 -name app.py 2>/dev/null
done
```

(El `[ -d ]` no es adorno: en un macOS en inglés `~/Descargas` no existe y `find` sale
con error.)

Hacé `cd` al directorio que lo contiene y movelo **ahora, antes del Paso 3**. Los venv
guardan rutas absolutas: si movés después, `.venv/bin/whisperx` sigue existiendo pero
explota con `bad interpreter`, y como la verificación no prueba el modo IA, la instalación
te va a dar toda verde con la IA rota.

El `if` tampoco es adorno: si el destino existe, `mv` **no falla, mete la carpeta
adentro**.

```bash
mkdir -p ~/Applications
if [ -e ~/Applications/buscar-en-video ]; then
  echo "OJO: ya hay algo ahí — no lo piso"
else
  mv "$(pwd)" ~/Applications/buscar-en-video
fi
cd ~/Applications/buscar-en-video
pwd && ls app.py index.html start.command requirements.txt
```

Si ya existía, es una instalación anterior a medias: si
`~/Applications/buscar-en-video/.venv/bin/whisperx --help` anda, seguí desde el Paso 3;
si no, borrá la carpeta vieja (`rm -rf`) y repetí el `mv`.

**El `mv` te mueve el piso a vos**: la carpeta donde estabas dejó de existir y la
invocación siguiente va a fallar con `No such file or directory`. Eso no es el ZIP roto.
De acá en adelante empezá **cada** comando con:

```bash
cd ~/Applications/buscar-en-video || exit 1
```

## Paso 1 — Homebrew

Que el chequeo **hable siempre**: encadenado con `||` sale con 0 y no imprime nada cuando
brew existe, y "no imprimió nada" se lee igual que "no está".

```bash
if BREW=$(command -v brew || ls /opt/homebrew/bin/brew /usr/local/bin/brew 2>/dev/null | head -1) && [ -n "$BREW" ]; then
  echo "brew ya está en $BREW"
else
  echo "falta brew"
fi
```

Si falta, **este es el único paso de toda la instalación que no podés hacer solo.** El
instalador pide la contraseña por `sudo`, y `sudo` exige una terminal de verdad: lanzado
desde tu herramienta de shell se cuelga esperando una contraseña que nadie puede escribir.

**Antes de lanzar nada**, decile exactamente esto:

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

**No intentes saltear el Enter con `NONINTERACTIVE=1`**: en ese modo el instalador necesita
un `sudo` sin contraseña o ya cacheado, y si no lo tiene aborta.

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

**Esperá a que la persona te confirme que terminó** y después comprobalo vos. Si se
equivocó de contraseña, volvé a correr el mismo `open`: se puede repetir sin romper nada.

Ya instalado, `brew` todavía no está en el PATH de *tu* sesión. **No lo agregues con un
`||` entre los dos `eval`**: si la ruta de Apple Silicon no existe, la sustitución queda
vacía y `eval ""` **sale con 0**, así que el fallback de Intel no corre nunca.

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
brew install yt-dlp ffmpeg uv python
```

`yt-dlp` es obligatorio para los dos modos; `ffmpeg` sólo para el modo IA, pero instalalo
igual; `uv` arma el entorno de Python.

`python` va por Homebrew a propósito. **No compruebes Python con `command -v python3`**:
en una Mac sin las herramientas de Xcode, `/usr/bin/python3` **existe igual** —es un stub
de `xcrun`— así que `command -v` devuelve 0 y vos concluís que hay Python donde no hay. Al
invocarlo salta el diálogo gráfico de "instalar herramientas de línea de comandos".
Comprobalo **corriéndolo**, y también en un login shell, que es el que usa el doble clic:

```bash
python3 -V
zsh -lc 'command -v python3 && python3 -V'
```

Evitá `xcode-select --install`: abre un diálogo que le tenés que pedir a la persona.

## Paso 3 — El entorno de whisperx

Desde la carpeta que contiene `app.py`:

```bash
uv venv --python 3.12
uv pip install -r requirements.txt
```

Si falla porque alguna dependencia sacó una versión que rompe, **borrá el `.venv`
primero** —el intento fallido dejó paquetes a medias— y usá el lock verificado:

```bash
rm -rf .venv
uv venv --python 3.12
uv pip install -r requirements.lock.txt
```

- **Fijá Python 3.12.** `whisperx` no soporta 3.13 y la instalación falla si `uv` elige la
  más nueva por su cuenta. Si no encuentra un 3.12, lo baja solo.
- Son ~1 GB (`torch`, `ctranslate2`, `transformers`). Tarda unos minutos.
- **No hace falta ningún token de Hugging Face.** La app no usa diarización: ignorá lo que
  diga la documentación de whisperx sobre `--hf_token` o los términos de `pyannote`.

Esperado: que exista `.venv/bin/whisperx`.

## Paso 4 — Permisos del lanzador

```bash
chmod +x start.command
xattr -dr com.apple.quarantine . 2>/dev/null || true
```

El `xattr` va **con `-r` y sobre la carpeta entera**: el ZIP bajado del navegador queda
marcado, y al descomprimir la marca queda en todo lo que salió adentro. Limpiar sólo el
lanzador deja marcados `app.py` e `index.html` y el bloqueo reaparece.

## Paso 5 — Verificación

**No declares "quedó andando" hasta que la prueba real del modo subtítulos haya devuelto
resultados.** Todo lo demás puede dar verde con la app igualmente inservible.

**No uses `command -v yt-dlp ffmpeg`**: con dos nombres devuelve 0 si encuentra
**cualquiera** de los dos, así que te da "ok" con `ffmpeg` ausente y el modo IA muerto.

```bash
for b in yt-dlp ffmpeg; do
  if command -v "$b" >/dev/null; then echo "ok: $b"; else echo "FALTA: $b"; fi
done
./.venv/bin/whisperx --help >/dev/null && echo "ok: whisperx"
python3 -m unittest test_app
```

El `whisperx --help` puede tardar 20 segundos la primera vez porque importa torch: no está
colgado, y si tu herramienta de shell tiene timeout corto, subilo.

`ProcesosHijos.test_al_salir_se_lleva_al_nieto` es **inestable**: mide tiempos reales y
falla por timeout si la máquina está cargada. Si es el único que falla, corré los tests de
nuevo; si pasa en la segunda o tercera corrida, está bien. **No te pongas a arreglar
`app.py`**.

Probá **`start.command`**, no `python3 app.py`: es lo único que ejercita el permiso de
ejecución, la cuarentena y el `open` del navegador.

```bash
./start.command &
sleep 4
curl -fs http://127.0.0.1:8765/api/salud
```

Tiene que devolver `{"ok": true}` y abrirse una pestaña. Si el `curl` anda pero la pestaña
no aparece, revisá el Paso 4: casi siempre es cuarentena.

**Ese servidor tiene que seguir vivo para la prueba que sigue.** Muchas herramientas de
shell matan lo que dejaste en segundo plano al terminar cada comando, y entonces vas a ver
"connection refused" y a diagnosticar mal. Corré las dos cosas en **una sola** invocación,
o lanzalo con `nohup ./start.command >/dev/null 2>&1 & disown`.

## Prueba real del modo subtítulos (la que decide)

Sirve igual para el Camino A y el B, con el buscador ya levantado.

**No inventes un video de memoria**: hace falta uno con subtítulos automáticos **en
español** (es el único idioma que pide la app), y con uno en otro idioma vas a recibir "no
tiene subtítulos en español" y creer que está roto. Dejá que `yt-dlp` te consiga uno:

```bash
ID=$(yt-dlp --skip-download --print id "ytsearch1:entrevista completa en español" | head -1)
echo "video elegido: $ID"
curl -s -X POST http://127.0.0.1:8765/api/buscar \
  -H 'Content-Type: application/json' \
  -d "{\"url\":\"https://www.youtube.com/watch?v=$ID\",\"consulta\":\"que\"}"
```

La consulta es `que` a propósito: aparece en cualquier video hablado en español, así que si
no viene ningún resultado el problema es la instalación y no la palabra.

Tiene que venir un JSON con `"fuente": "subtitulos"` y una lista de `resultados` no vacía.

(En el Camino A, si `yt-dlp` no está en el PATH del sistema porque viaja adentro del
bundle, usá el del bundle:
`"/Applications/Buscar en video.app/Contents/Resources/bin/yt-dlp"`.)

**Si en vez de eso viene `"YouTube te limitó por hacer muchos pedidos seguidos"`**, no lo
despaches como "esperá un minuto": es un 429 sobre el endpoint de subtítulos, es frecuente,
y desde acá **no podés distinguir una instalación sana de una rota**.

1. Esperá 60 segundos y reintentá. Hasta tres veces, con otro video la última.
2. Si sigue, comprobá que el problema sea de YouTube y no tuyo:

   ```bash
   yt-dlp --skip-download --write-auto-subs --sub-langs 'es.*' --sub-format vtt \
     -o '/tmp/prueba.%(ext)s' 'https://www.youtube.com/watch?v=VIDEO_ID'
   ```

   Si a mano también da 429, la instalación está bien y el bloqueo es de red.
3. En ese caso **no le digas que quedó andando**. Decile la verdad:

   > "Quedó todo instalado, pero no lo pude probar de punta a punta: YouTube está
   > bloqueando pedidos desde esta conexión en este momento. Probalo vos en un rato con
   > doble clic; si te sigue diciendo que esperes, andá probando cada tanto. No hay que
   > reinstalar nada."

**No pruebes el modo IA como parte de la instalación.** La primera corrida baja ~1,9 GB de
modelos y transcribir lleva minutos. Dejalo para la primera vez que la persona tilde la
opción, y avisale de antemano que esa primera vez tarda.

Cuando termines, cerrá el servidor de prueba. `pkill -f "python3 app.py"` **no sirve**: el
proceso queda en la tabla con la ruta real del binario de Python y el patrón no matchea
nunca — sale sin decir nada y el servidor queda vivo. Cerralo por el puerto:

```bash
lsof -ti tcp:8765 | xargs kill
```

## Paso 6 (Camino B) — Dejarle la app a mano

```bash
ln -sf ~/Applications/buscar-en-video/start.command ~/Desktop/"Buscar en video.command"
```

Es un enlace, no una copia: Finder lo resuelve antes de ejecutarlo, así que
`start.command` se para en la carpeta buena y no en el Escritorio.

> "Listo, ya está andando. Te dejé en el Escritorio un archivo que se llama **Buscar en
> video**: doble clic ahí y se abre. Se va a abrir una ventana negra con letras: no la
> cierres mientras lo usás, es el motor. El buscador se abre solo en tu navegador. Cuando
> terminás, cerrás la ventana negra y listo. Si alguna vez se te cierra sin querer, no
> pasa nada: doble clic de nuevo."

---

# Si algo falla

| Síntoma | Causa y arreglo |
|---|---|
| La `.app` no abre nada (Camino A) | Mirá `~/Library/Logs/buscar-en-video.log`: la app no tiene terminal y ahí escribe todo |
| macOS bloquea la `.app` (Camino A) | Falta el `xattr -dr com.apple.quarantine` sobre la app |
| `start.command` se abre como texto | Falta el permiso: `chmod +x start.command` |
| macOS dice que no puede verificar el archivo | Cuarentena: `xattr -dr` sobre la carpeta entera, o clic derecho → Abrir → Abrir |
| `Address already in use` al arrancar | El puerto 8765 ya está tomado por otra copia: `lsof -ti tcp:8765 \| xargs kill`. (`pkill -f "python3 app.py"` **no matchea**.) |
| El `.venv` dejó de andar después de mover la carpeta | Los venv guardan rutas absolutas: `rm -rf .venv` y repetí el Paso 3 desde la ubicación nueva |
| "El modo preciso con IA no está disponible" | Falta `pylibs` (Camino A) o el `.venv` (Camino B). Verificá el Paso 3 |
| `whisperx` instala pero explota al correr | Casi siempre la versión de Python. `.venv/bin/python -V` tiene que decir 3.12.x; si dice 3.13, borrá el `.venv` y repetí con `--python 3.12` |
| El modo IA falla al bajar el audio | Falta `ffmpeg`: `brew install ffmpeg` |
| YouTube responde que se espere | Un 429. En el uso normal se pasa esperando un minuto. **Durante la instalación no lo despaches**: seguí el procedimiento de arriba |
| Un solo test falla, el del nieto | Es inestable por timing. Corré los tests de nuevo |

Las transcripciones y subtítulos se cachean en `~/.cache/buscar-en-video/`; los modelos de
IA en `~/.cache/huggingface/` y `~/.cache/torch/`. Se pueden borrar en cualquier momento,
al costo de volver a bajarlos.

## Versiones verificadas

macOS 15 (arm64) · Python 3.12.14 · whisperx 3.8.6 · torch 2.8.0 · ctranslate2 4.8.1 ·
faster-whisper 1.2.1 · yt-dlp y ffmpeg de Homebrew.
