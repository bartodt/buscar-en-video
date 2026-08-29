#!/bin/bash
# Doble clic en Finder para arrancar el buscador.
cd "$(dirname "$0")" || exit 1

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

python3 app.py &
SERVIDOR=$!
# Si cerrás esta ventana, el servidor se va con ella.
trap 'kill $SERVIDOR 2>/dev/null' EXIT

for _ in $(seq 1 40); do
  if curl -fs "http://127.0.0.1:$PUERTO/api/salud" >/dev/null 2>&1; then
    open "http://127.0.0.1:$PUERTO"
    break
  fi
  sleep 0.25
done

echo
echo "Ya se abrió en el navegador."
echo "Dejá esta ventana abierta mientras lo usás. Para cerrarlo, cerrá la ventana."
echo
wait $SERVIDOR
