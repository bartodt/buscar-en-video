#!/bin/bash
# Arma "Buscar en video.app": un bundle autocontenido de macOS.
#
# Esto NO lo corre la persona que va a usar la app. Lo corre quien la distribuye, una
# vez, en una Mac de desarrollo con Homebrew y uv. El resultado es un .dmg: la persona
# lo abre, arrastra el ícono a Aplicaciones y hace doble clic. No instala Python, ni
# Homebrew, ni whisperx, ni escribe una sola línea en la Terminal.
#
# Adentro del bundle viaja todo: el intérprete de Python, whisperx con torch, yt-dlp y
# ffmpeg con sus dylibs. Nada se resuelve contra /opt/homebrew ni contra el sistema.
set -euo pipefail

cd "$(dirname "$0")"
RAIZ="$PWD"
NOMBRE="Buscar en video"
SALIDA="$RAIZ/dist"
APP="$SALIDA/$NOMBRE.app"
RES="$APP/Contents/Resources"

paso() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
morir() { printf '\n\033[31mERROR: %s\033[0m\n' "$1" >&2; exit 1; }

# --- 0. la máquina de build tiene lo que hace falta --------------------------
paso "Chequeando la máquina de build"
[ "$(uname -s)" = "Darwin" ] || morir "esto sólo se puede armar en una Mac."
ARCO="$(uname -m)"
for h in uv dylibbundler curl; do
  command -v "$h" >/dev/null || morir "falta $h (brew install $h)."
done
# ffmpeg y ffprobe se copian de Homebrew: es la fuente que ya usa el proyecto, y así no
# hay que confiar en un build estático de un tercero.
for b in ffmpeg ffprobe; do
  [ -x "/opt/homebrew/bin/$b" ] || [ -x "/usr/local/bin/$b" ] || morir "falta $b (brew install ffmpeg)."
done
BREW_BIN="/opt/homebrew/bin"; [ -x "$BREW_BIN/ffmpeg" ] || BREW_BIN="/usr/local/bin"

# El intérprete tiene que ser uno "relocatable": los de python-build-standalone que
# maneja uv resuelven su prefix desde argv[0], así que andan desde cualquier ruta. El
# python de Homebrew no sirve para esto, tiene el prefix compilado adentro.
uv python install 3.12 >/dev/null 2>&1 || true
# uv nombra sus directorios con el triple de LLVM: arm64 se escribe aarch64.
ARCO_UV="$ARCO"; [ "$ARCO" = "arm64" ] && ARCO_UV="aarch64"
PY_SRC="$(ls -d "$HOME/.local/share/uv/python/cpython-3.12."*"-macos-$ARCO_UV-none" 2>/dev/null | sort -V | tail -1 || true)"
[ -n "$PY_SRC" ] && [ -x "$PY_SRC/bin/python3" ] || morir "no encontré un Python 3.12 de uv para $ARCO."
echo "Python:  $PY_SRC"
echo "ffmpeg:  $BREW_BIN"
echo "arco:    $ARCO"

# --- 1. esqueleto del bundle ------------------------------------------------
paso "Armando el esqueleto"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$RES/bin"

VERSION="$(git -C "$RAIZ" describe --tags --always 2>/dev/null || echo 1.0)"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>$NOMBRE</string>
  <key>CFBundleDisplayName</key><string>$NOMBRE</string>
  <key>CFBundleIdentifier</key><string>ar.buscarenvideo.app</string>
  <key>CFBundleExecutable</key><string>lanzador</string>
  <key>CFBundleIconFile</key><string>icono</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <!-- El motor es un servidor local sin ventana propia: sin esto queda un ícono
       genérico rebotando en el Dock para siempre. Se apaga desde la página. -->
  <key>LSBackgroundOnly</key><true/>
</dict>
</plist>
PLIST
printf 'APPL????' > "$APP/Contents/PkgInfo"

# --- 2. el lanzador ---------------------------------------------------------
paso "Escribiendo el lanzador"
cat > "$APP/Contents/MacOS/lanzador" <<'LANZADOR'
#!/bin/bash
# Lo que corre el doble clic. Todo se resuelve relativo a este archivo: la .app puede
# estar en /Applications, en el Escritorio o en el volumen del .dmg, y anda igual.
#
# Arranca el servidor DESPRENDIDO y sale en seguida, a propósito. Un bundle cuyo
# ejecutable es un script de shell no hace el check-in que LaunchServices espera de una
# app: si el script se queda vivo esperando al servidor, macOS lo da por colgado y al
# minuto mata el árbol entero sin dejar rastro. Desprendiéndolo, el servidor queda
# adoptado por launchd y sigue andando; se apaga desde el botón de la página.
RES="$(cd "$(dirname "$0")/../Resources" && pwd)"
PUERTO=8765

# Los binarios propios primero: ni yt-dlp ni ffmpeg tienen que salir del bundle.
export PATH="$RES/bin:$PATH"

# Un log de verdad: como la app no tiene terminal, sin esto un arranque fallido no deja
# ningún rastro que se pueda mirar después.
LOG="$HOME/Library/Logs/buscar-en-video.log"
mkdir -p "$(dirname "$LOG")"

# Si ya está andando (doble clic de nuevo, o la pestaña cerrada sin apagar el motor), no
# se levanta un segundo: el puerto está tomado y el nuevo moriría al instante.
if curl -fs "http://127.0.0.1:$PUERTO/api/salud" >/dev/null 2>&1; then
  open "http://127.0.0.1:$PUERTO"
  exit 0
fi

echo "=== arranque $(date) ===" >> "$LOG"
nohup "$RES/python/bin/python3" "$RES/app.py" >>"$LOG" 2>&1 &
disown

for _ in $(seq 1 80); do
  if curl -fs "http://127.0.0.1:$PUERTO/api/salud" >/dev/null 2>&1; then
    open "http://127.0.0.1:$PUERTO"
    exit 0
  fi
  sleep 0.25
done

# Veinte segundos y no contestó. Sin ventana ni ícono, callarse acá deja a la persona
# mirando una pantalla donde no pasó nada: el cartel es la única señal posible.
echo "no arrancó en 20 segundos" >> "$LOG"
osascript -e 'display alert "Buscar en video" message "No pude arrancar el buscador. Pasale el archivo ~/Library/Logs/buscar-en-video.log a quien te dio la app." as critical' >/dev/null 2>&1
exit 1
LANZADOR
chmod +x "$APP/Contents/MacOS/lanzador"

# --- 3. la app misma --------------------------------------------------------
paso "Copiando app.py e index.html"
cp "$RAIZ/app.py" "$RAIZ/index.html" "$RES/"

# --- 4. yt-dlp --------------------------------------------------------------
paso "Bajando yt-dlp (binario oficial, autocontenido)"
curl -fL --retry 3 -o "$RES/bin/yt-dlp" \
  https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos
chmod +x "$RES/bin/yt-dlp"

# --- 5. ffmpeg + ffprobe con sus dylibs -------------------------------------
paso "Empaquetando ffmpeg y ffprobe"
cp "$BREW_BIN/ffmpeg" "$BREW_BIN/ffprobe" "$RES/bin/"
# El de Homebrew apunta a /opt/homebrew/Cellar/...: en la Mac de la persona eso no
# existe. dylibbundler copia el árbol entero de dependencias adentro y reescribe cada
# ruta a @executable_path/lib, que es relativa al binario y viaja con el bundle.
# ffprobe entra en la misma pasada (-x dos veces) para que compartan un solo lib/.
dylibbundler -of -b -cd \
  -x "$RES/bin/ffmpeg" -x "$RES/bin/ffprobe" \
  -d "$RES/bin/lib" -p "@executable_path/lib" >/dev/null
# Verificación real: que no quede ni una referencia a Homebrew.
if otool -L "$RES/bin/ffmpeg" "$RES/bin/ffprobe" "$RES/bin/lib/"*.dylib \
   | grep -q "/opt/homebrew\|/usr/local/Cellar"; then
  morir "quedaron dylibs apuntando a Homebrew: el ffmpeg no es portable."
fi

# --- 6. el intérprete -------------------------------------------------------
paso "Copiando el intérprete de Python"
cp -R "$PY_SRC" "$RES/python"
# Los .pyc y los headers de compilación no los usa nadie en runtime y son cientos de MB.
find "$RES/python" -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true
rm -rf "$RES/python/lib/python3.12/test" "$RES/python/lib/python3.12/idlelib" \
       "$RES/python/lib/python3.12/tkinter" "$RES/python/share" 2>/dev/null || true

# --- 7. whisperx ------------------------------------------------------------
paso "Instalando whisperx y torch (~1 GB, tarda unos minutos)"
# --target y no un venv: un venv guarda la ruta absoluta de su intérprete y se rompe al
# mover la carpeta. Un directorio plano de librerías se resuelve por PYTHONPATH, que el
# propio app.py arma relativo a sí mismo (ver _comando_whisperx).
LOCK="$RAIZ/requirements.txt"
uv pip install --python "$RES/python/bin/python3" --target "$RES/pylibs" -r "$LOCK" \
  || { echo "falló con requirements.txt, reintento con el lock verificado"
       rm -rf "$RES/pylibs"
       uv pip install --python "$RES/python/bin/python3" --target "$RES/pylibs" \
         -r "$RAIZ/requirements.lock.txt"; }
[ -d "$RES/pylibs/whisperx" ] || morir "whisperx no quedó instalado en el bundle."
find "$RES/pylibs" -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true

# --- 8. ícono ---------------------------------------------------------------
paso "Generando el ícono"
python3 "$RAIZ/herramientas/icono.py" "$RES/icono.icns" || echo "sin ícono (no es fatal)"

# --- 9. verificación --------------------------------------------------------
paso "Verificando el bundle"
# Desde una ruta distinta a la de build, que es justo lo que rompe a los venv: si algo
# quedó con una ruta absoluta escrita adentro, acá salta.
PRUEBA="$(mktemp -d)/Buscar en video.app"
mkdir -p "$(dirname "$PRUEBA")" && cp -R "$APP" "$PRUEBA"
PRES="$PRUEBA/Contents/Resources"
"$PRES/bin/ffmpeg" -version >/dev/null || morir "ffmpeg no corre fuera de la carpeta de build."
"$PRES/bin/yt-dlp" --version >/dev/null || morir "yt-dlp no corre."
"$PRES/python/bin/python3" -V >/dev/null || morir "el Python del bundle no corre."
PYTHONPATH="$PRES/pylibs" "$PRES/python/bin/python3" -m whisperx --help >/dev/null \
  || morir "whisperx no corre desde el bundle."
rm -rf "$(dirname "$PRUEBA")"
echo "todo corre desde una ruta ajena a la de build."

# --- 10. dmg ----------------------------------------------------------------
paso "Armando el .dmg"
DMG="$SALIDA/$NOMBRE.dmg"
rm -f "$DMG"
ETAPA="$(mktemp -d)/$NOMBRE"
mkdir -p "$ETAPA"
cp -R "$APP" "$ETAPA/"
ln -s /Applications "$ETAPA/Aplicaciones"
hdiutil create -volname "$NOMBRE" -srcfolder "$ETAPA" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$(dirname "$ETAPA")"

paso "Listo"
du -sh "$APP" "$DMG"
echo
echo "Para probarlo acá mismo:  open \"$APP\""
echo "Para mandarlo:            $DMG"
