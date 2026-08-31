#!/bin/bash
# Doble clic en Finder para arrancar el buscador.
cd "$(dirname "$0")" || exit 1

# El mismo que abre app.py.
PUERTO=8765

echo "=== Buscador en videos de YouTube ==="
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "Falta Python 3."
  echo "Instalalo desde https://www.python.org/downloads/ y volvé a abrir este archivo."
  echo
  read -r -p "Enter para cerrar."
  exit 1
fi

if ! command -v yt-dlp >/dev/null 2>&1; then
  echo "Falta yt-dlp, que es lo que baja los subtítulos de YouTube."
  echo
  echo "Abrí la app Terminal y pegá esta línea:"
  echo
  echo "    brew install yt-dlp"
  echo
  echo "Si no tenés Homebrew, instalalo primero desde https://brew.sh"
  echo "Después volvé a abrir este archivo."
  echo
  read -r -p "Enter para cerrar."
  exit 1
fi

# No es obligatorio: solo lo usa el modo "Transcribir con IA", para pasar el audio a
# WAV 16 kHz mono. Avisamos ahora y no después de que el usuario espere una descarga.
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "Aviso: no encontré ffmpeg, así que el modo \"Transcribir con IA\" no va a andar."
  echo "Si lo querés usar, abrí la Terminal y pegá:  brew install ffmpeg"
  echo
fi

python3 app.py &
SERVIDOR=$!
# Si cerrás esta ventana, el servidor se va con ella. El wait no es adorno: le da a
# app.py el tiempo de atender la señal y matar a yt-dlp y whisperx, que si no quedan
# vivos comiéndose todos los cores sin ninguna ventana que los delate.
trap 'kill "$SERVIDOR" 2>/dev/null; wait "$SERVIDOR" 2>/dev/null' EXIT

abierto=0
for _ in $(seq 1 40); do
  # Si el servidor murió al arrancar (el caso común: ya hay otra ventana abierta) hay
  # que decirlo. Antes la ventana se cerraba sola y el error pasaba de largo.
  if ! kill -0 "$SERVIDOR" 2>/dev/null; then
    echo
    echo "El servidor no llegó a arrancar. El motivo está unas líneas más arriba."
    echo "Lo más común es que ya tengas otra ventana del buscador abierta."
    echo
    read -r -p "Enter para cerrar."
    exit 1
  fi
  if curl -fs "http://127.0.0.1:$PUERTO/api/salud" >/dev/null 2>&1; then
    open "http://127.0.0.1:$PUERTO"
    abierto=1
    break
  fi
  sleep 0.25
done

echo
if [ "$abierto" = 1 ]; then
  echo "Ya se abrió en el navegador."
else
  echo "Tardó más de lo normal y no lo abrí solo."
  echo "Entrá a mano a  http://127.0.0.1:$PUERTO"
fi
echo "Dejá esta ventana abierta mientras lo usás. Para cerrarlo, cerrá la ventana."
echo
wait $SERVIDOR
