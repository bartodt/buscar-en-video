#!/usr/bin/env python3
"""Servidor local para buscar palabras dentro de los subtitulos de un video de YouTube."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RAIZ = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.expanduser("~/.cache/buscar-en-video")
PUERTO = 8765

# Los subtitulos automaticos repiten cada linea mientras rota en pantalla; dos cues
# identicos dentro de esta ventana son la misma frase dicha una sola vez.
VENTANA_DUPLICADOS = 10
CONTEXTO = 60

# Transcripcion con IA. Medido sobre 5 min del mismo audio, comparando contra los
# subtitulos de YouTube: turbo coincide 88.3%, large-v3 87.9%, medium 84.3% y small
# 81.9%. turbo gana en calidad y ademas es el mas rapido de los tres grandes (2:46
# contra 8:10 de large-v3), asi que no hay razon para usar otro en CPU.
MODELO_WHISPER = "large-v3-turbo"
IDIOMA_WHISPER = "es"
VERSION_CACHE_WHISPER = 2


class ErrorDeUso(Exception):
    """Error con un mensaje pensado para mostrarle al usuario tal cual."""


# --- normalizacion ---------------------------------------------------------

def normalizar(texto):
    """Minusculas y sin tildes, preservando la longitud para no romper los offsets."""
    salida = []
    for c in texto:
        base = unicodedata.normalize("NFD", c)[0].lower()
        salida.append(base if len(base) == 1 else c)
    return "".join(salida)


# --- yt-dlp ----------------------------------------------------------------

def extraer_id(url):
    url = (url or "").strip()
    patrones = (
        r"(?:youtube\.com|youtube-nocookie\.com)/(?:watch\?(?:.*&)?v=|embed/|shorts/|live/|v/)([A-Za-z0-9_-]{11})",
        r"youtu\.be/([A-Za-z0-9_-]{11})",
        r"^([A-Za-z0-9_-]{11})$",
    )
    for patron in patrones:
        match = re.search(patron, url)
        if match:
            return match.group(1)
    raise ErrorDeUso("Ese link no parece un video de YouTube. Pegá la URL completa.")


def _leer_cache(video_id):
    vtt = os.path.join(CACHE, video_id + ".vtt")
    if not os.path.exists(vtt):
        return None
    titulo_path = os.path.join(CACHE, video_id + ".titulo")
    titulo = video_id
    if os.path.exists(titulo_path):
        with open(titulo_path, encoding="utf-8") as fh:
            titulo = fh.read().strip() or video_id
    with open(vtt, encoding="utf-8") as fh:
        return fh.read(), titulo


def _diagnosticar_fallo(salida):
    texto = salida.lower()
    if "429" in texto or "too many requests" in texto:
        raise ErrorDeUso(
            "YouTube te limitó por hacer muchos pedidos seguidos. "
            "Esperá un minuto y probá de nuevo."
        )
    if "sign in to confirm" in texto or "not a bot" in texto:
        raise ErrorDeUso(
            "YouTube pidió verificación para este video. Probá de nuevo en un rato."
        )
    if "video unavailable" in texto or "private video" in texto:
        raise ErrorDeUso("Ese video no está disponible (es privado o fue dado de baja).")
    raise ErrorDeUso("No se pudieron bajar los subtítulos de ese video.")


# Los videos que buscamos son siempre en español, asi que solo pedimos esa pista.
# YouTube ofrece autosubs traducidos a cualquier idioma, pero solo "es-orig" es la
# transcripcion real del audio: "es" a secas puede ser una traduccion de la traduccion
# al ingles, con palabras cambiadas respecto de lo que se dice de verdad.
PREFERENCIA_SUBS = ("es-orig", "es")


def _idioma_de(archivo, video_id):
    """El nombre quedo como "<titulo> [<id>].<lang>.vtt"."""
    partes = archivo.split(" [" + video_id + "].")
    return partes[-1][:-4] if len(partes) > 1 else ""


def _elegir_sub(archivos, video_id):
    por_idioma = {_idioma_de(f, video_id): f for f in archivos}
    for idioma in PREFERENCIA_SUBS:
        if idioma in por_idioma:
            return por_idioma[idioma]
    return archivos[0]


def bajar_subs(video_id):
    """Devuelve (contenido_vtt, titulo). Usa el cache si ya se bajó antes."""
    cacheado = _leer_cache(video_id)
    if cacheado:
        return cacheado

    if not shutil.which("yt-dlp"):
        raise ErrorDeUso(
            "Falta instalar yt-dlp. Abrí la Terminal y corré:  brew install yt-dlp"
        )

    with tempfile.TemporaryDirectory() as tmp:
        comando = [
            "yt-dlp",
            "--skip-download",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs", "es.*",
            "--sub-format", "vtt",
            "--no-playlist",
            "--no-warnings",
            "-o", os.path.join(tmp, "%(title)s [%(id)s].%(ext)s"),
            "https://www.youtube.com/watch?v=" + video_id,
        ]
        try:
            proceso = subprocess.run(
                comando, capture_output=True, text=True, timeout=180
            )
        except subprocess.TimeoutExpired:
            raise ErrorDeUso("YouTube tardó demasiado en responder. Probá de nuevo.")

        archivos = sorted(f for f in os.listdir(tmp) if f.endswith(".vtt"))
        if not archivos:
            if proceso.returncode != 0:
                _diagnosticar_fallo(proceso.stderr + proceso.stdout)
            raise ErrorDeUso(
                "Ese video no tiene subtítulos en español, ni siquiera automáticos, "
                "así que no hay texto donde buscar."
            )

        elegido = _elegir_sub(archivos, video_id)
        titulo = elegido.split(" [" + video_id + "]")[0] or video_id
        with open(os.path.join(tmp, elegido), encoding="utf-8") as fh:
            contenido = fh.read()

    os.makedirs(CACHE, exist_ok=True)
    with open(os.path.join(CACHE, video_id + ".vtt"), "w", encoding="utf-8") as fh:
        fh.write(contenido)
    with open(os.path.join(CACHE, video_id + ".titulo"), "w", encoding="utf-8") as fh:
        fh.write(titulo)
    return contenido, titulo


# --- whisperx (transcripcion con IA) ---------------------------------------

def _binario_whisperx():
    """whisperx vive en el .venv del proyecto; el servidor corre con el python del sistema."""
    local = os.path.join(RAIZ, ".venv", "bin", "whisperx")
    if os.path.exists(local):
        return local
    return shutil.which("whisperx")


def _leer_cache_whisper(video_id):
    """Devuelve (cues, titulo) si hay una transcripcion guardada y compatible."""
    ruta = os.path.join(CACHE, video_id + ".whisperx.json")
    if not os.path.exists(ruta):
        return None
    try:
        with open(ruta, encoding="utf-8") as fh:
            datos = json.load(fh)
    except (ValueError, OSError):
        return None
    # Una transcripcion vieja o hecha con otro modelo no sirve: se rehace.
    if datos.get("version") != VERSION_CACHE_WHISPER:
        return None
    if datos.get("modelo") != MODELO_WHISPER:
        return None
    cues = [(float(segundos), texto) for segundos, texto in datos.get("palabras", [])]
    if not cues:
        return None
    return cues, datos.get("titulo") or video_id


def _cues_de_palabras(transcripcion):
    """Una cue por palabra, con el segundo exacto en que se dice.

    Es de donde sale la precision: el subtitulo de YouTube marca el arranque de una
    linea entera, whisperx alinea palabra por palabra contra el audio.
    """
    cues = []
    for segmento in transcripcion.get("segments", []):
        for palabra in segmento.get("words", []):
            texto = (palabra.get("word") or "").strip()
            if not texto:
                continue
            inicio = palabra.get("start")
            if inicio is None:
                # wav2vec2 no alinea numeros ni simbolos: heredan el ultimo tiempo conocido.
                inicio = cues[-1][0] if cues else segmento.get("start")
            if inicio is not None:
                cues.append((float(inicio), texto))
    return cues


def _cues_de_segmentos(transcripcion):
    """Respaldo por si la alineacion fallo y no vinieron tiempos por palabra."""
    return [
        (float(segmento["start"]), re.sub(r"\s+", " ", segmento["text"]).strip())
        for segmento in transcripcion.get("segments", [])
        if segmento.get("text", "").strip() and segmento.get("start") is not None
    ]


def transcribir_whisper(video_id):
    """Devuelve (cues, titulo) transcribiendo el audio con whisperx.

    Baja el audio completo y lo transcribe, asi que tarda mucho mas que leer los
    subtitulos: el resultado queda cacheado para no repetirlo nunca sobre el mismo video.
    """
    cacheado = _leer_cache_whisper(video_id)
    if cacheado:
        return cacheado

    binario = _binario_whisperx()
    if not binario:
        raise ErrorDeUso(
            "No encontré whisperx. Debería estar en la carpeta .venv del proyecto. "
            "Abrí la Terminal en esta carpeta y corré:  uv venv && uv pip install whisperx"
        )

    with tempfile.TemporaryDirectory() as tmp:
        audio = os.path.join(tmp, "audio.wav")
        comando_audio = [
            "yt-dlp",
            "-x", "--audio-format", "wav",
            # Whisper trabaja en 16 kHz mono igual: pedirlo asi achica mucho el archivo.
            "--postprocessor-args", "ffmpeg:-ac 1 -ar 16000",
            "--no-playlist",
            "--no-warnings",
            "-o", audio,
            "https://www.youtube.com/watch?v=" + video_id,
        ]
        try:
            proceso = subprocess.run(
                comando_audio, capture_output=True, text=True, timeout=600
            )
        except subprocess.TimeoutExpired:
            raise ErrorDeUso("YouTube tardó demasiado en responder. Probá de nuevo.")
        if not os.path.exists(audio):
            _diagnosticar_fallo(proceso.stderr + proceso.stdout)

        comando_titulo = [
            "yt-dlp", "--skip-download", "--print", "%(title)s", "--no-warnings",
            "https://www.youtube.com/watch?v=" + video_id,
        ]
        try:
            proceso_titulo = subprocess.run(
                comando_titulo, capture_output=True, text=True, timeout=60
            )
            titulo = proceso_titulo.stdout.strip() or video_id
        except subprocess.TimeoutExpired:
            titulo = video_id

        comando_whisper = [
            binario, audio,
            "--model", MODELO_WHISPER,
            "--language", IDIOMA_WHISPER,
            # ctranslate2 en CPU no tiene float16; int8 es lo que lo hace usable.
            "--compute_type", "int8",
            "--threads", str(os.cpu_count() or 4),
            "--output_format", "json",
            "--output_dir", tmp,
            "--verbose", "False",
        ]
        print("Transcribiendo %s con whisperx (%s)…" % (video_id, MODELO_WHISPER))
        try:
            proceso = subprocess.run(
                comando_whisper, capture_output=True, text=True, timeout=5400
            )
        except subprocess.TimeoutExpired:
            raise ErrorDeUso(
                "La transcripción tardó demasiado. Probá con un video más corto."
            )

        json_path = os.path.join(tmp, "audio.json")
        if proceso.returncode != 0 or not os.path.exists(json_path):
            _avisar_en_consola(proceso.stderr)
            raise ErrorDeUso("No se pudo transcribir el audio de ese video.")

        with open(json_path, encoding="utf-8") as fh:
            transcripcion = json.load(fh)

    cues = _cues_de_palabras(transcripcion) or _cues_de_segmentos(transcripcion)
    if not cues:
        raise ErrorDeUso("La transcripción de ese video vino vacía.")

    os.makedirs(CACHE, exist_ok=True)
    with open(os.path.join(CACHE, video_id + ".whisperx.json"), "w", encoding="utf-8") as fh:
        json.dump({
            "version": VERSION_CACHE_WHISPER,
            "modelo": MODELO_WHISPER,
            "titulo": titulo,
            "palabras": [[round(segundos, 2), texto] for segundos, texto in cues],
        }, fh, ensure_ascii=False)
    return cues, titulo


def _avisar_en_consola(salida):
    """El stderr crudo no va al navegador, pero sirve tenerlo en la ventana del servidor."""
    lineas = [l for l in (salida or "").splitlines() if l.strip()][-20:]
    if lineas:
        print("whisperx falló:", file=sys.stderr)
        for linea in lineas:
            print("  " + linea, file=sys.stderr)


# --- parseo del vtt --------------------------------------------------------

def _a_segundos(marca):
    partes = marca.split(":")
    if len(partes) == 2:
        partes = ["0"] + partes
    horas, minutos, segundos = partes
    return int(float(horas) * 3600 + float(minutos) * 60 + float(segundos))


def parsear_vtt(contenido):
    """Devuelve [(segundo_inicio, texto)] sin las repeticiones de los auto-subs."""
    crudos, inicio = [], None
    for linea in contenido.splitlines():
        linea = linea.strip()
        if "-->" in linea:
            inicio = _a_segundos(linea.split("-->")[0].strip())
            continue
        if inicio is None or not linea:
            continue
        if linea.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            continue
        texto = re.sub(r"<[^>]+>", "", linea)
        texto = re.sub(r"\s+", " ", texto).strip()
        if texto:
            crudos.append((inicio, texto))

    # Los auto-subs muestran la linea anterior como contexto de la siguiente: si una
    # es prefijo de la otra, se queda la version larga con el timestamp mas temprano.
    fusionados = []
    for segundos, texto in crudos:
        if fusionados and texto.startswith(fusionados[-1][1]):
            fusionados[-1] = (fusionados[-1][0], texto)
        elif not fusionados or texto != fusionados[-1][1]:
            fusionados.append((segundos, texto))

    limpios = []
    for segundos, texto in fusionados:
        repetido = any(
            texto == prev_texto and segundos - prev_segundos <= VENTANA_DUPLICADOS
            for prev_segundos, prev_texto in limpios[-8:]
        )
        if not repetido:
            limpios.append((segundos, texto))
    return limpios


# --- busqueda --------------------------------------------------------------

def construir_indice(cues):
    """Texto corrido + un mapa de offset de caracter -> segundo del video."""
    partes, offsets = [], []
    for segundos, texto in cues:
        fragmento = texto + " "
        partes.append(fragmento)
        offsets.extend([segundos] * len(fragmento))
    completo = "".join(partes)
    return completo, normalizar(completo), offsets


def formatear(segundos):
    segundos = int(segundos)
    return "%d:%02d:%02d" % (segundos // 3600, segundos // 60 % 60, segundos % 60)


# Ninguna transcripcion escribe siempre la palabra como uno la tipea: medido sobre el
# mismo audio, whisperx-small parte "Popstars" en "Pop stars" y turbo lo pone en
# singular. Antes que perseguir eso con un modelo mas grande (3x mas lento y tampoco
# garantiza), la busqueda arranca exacta y solo se afloja si no encontro nada.
LARGO_MINIMO_APROXIMADO = 5
RECORTE_MAXIMO = 2


def _comprimir(texto_norm):
    """Texto sin espacios + mapa de posicion comprimida -> posicion original."""
    chars, mapa = [], []
    for posicion, caracter in enumerate(texto_norm):
        if not caracter.isspace():
            chars.append(caracter)
            mapa.append(posicion)
    return "".join(chars), mapa


def _barrer(aguja, pajar, mapa, completo, offsets, video_id, ventana_dup, aproximado):
    """Todas las apariciones de `aguja` en `pajar`, ubicadas en el texto original."""
    resultados, vistos, desde = [], [], 0
    while True:
        idx = pajar.find(aguja, desde)
        if idx == -1:
            break
        desde = idx + 1
        real = mapa[idx] if mapa else idx
        segundos = offsets[real]
        # Un mismo dicho puede matchear dos veces si el texto quedo repetido.
        if ventana_dup and any(segundos - previo <= ventana_dup for previo in vistos[-4:]):
            continue
        vistos.append(segundos)

        arranque = max(0, real - CONTEXTO)
        fin = min(len(completo), real + len(aguja) + CONTEXTO)
        fragmento = completo[arranque:fin].strip()
        if arranque > 0:
            fragmento = "…" + fragmento
        if fin < len(completo):
            fragmento = fragmento + "…"

        resultados.append({
            "segundos": int(segundos),
            "timestamp": formatear(segundos),
            "texto": fragmento,
            "link": "https://youtu.be/%s?t=%d" % (video_id, int(segundos)),
            "aproximado": aproximado,
        })
    return resultados


def buscar(cues, consulta, video_id, ventana_dup=VENTANA_DUPLICADOS):
    """ventana_dup=0 muestra todas las menciones, incluso dos seguidas.

    Solo hace falta filtrar con los subtitulos automaticos de YouTube, que repiten
    cada linea en pantalla; whisperx no repite nada.
    """
    consulta = re.sub(r"\s+", " ", (consulta or "").strip())
    if not consulta:
        raise ErrorDeUso("Escribí una palabra o frase para buscar.")

    completo, completo_norm, offsets = construir_indice(cues)
    objetivo = normalizar(consulta)

    exactos = _barrer(objetivo, completo_norm, None, completo, offsets,
                      video_id, ventana_dup, False)
    if exactos:
        return exactos

    # Sin espacios: "popstars" encuentra "Pop stars". Se pide un largo minimo porque
    # pegar las palabras hace que una consulta corta matchee dentro de otra frase.
    if len(objetivo.replace(" ", "")) >= LARGO_MINIMO_APROXIMADO:
        comprimido, mapa = _comprimir(completo_norm)
        sueltos = _barrer(objetivo.replace(" ", ""), comprimido, mapa, completo,
                          offsets, video_id, ventana_dup, True)
        if sueltos:
            return sueltos

    # Ultimo intento: recortar el final para que "popstars" alcance a "popstar".
    if " " not in objetivo and len(objetivo) >= LARGO_MINIMO_APROXIMADO + 1:
        for recorte in range(1, RECORTE_MAXIMO + 1):
            raiz = objetivo[:-recorte]
            if len(raiz) < LARGO_MINIMO_APROXIMADO:
                break
            parciales = _barrer(raiz, completo_norm, None, completo, offsets,
                                video_id, ventana_dup, True)
            if parciales:
                return parciales
    return []


# --- servidor --------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def _responder(self, codigo, payload):
        cuerpo = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        if self.path.startswith("/api/salud"):
            return self._responder(200, {"ok": True})
        if self.path in ("/", "/index.html"):
            with open(os.path.join(RAIZ, "index.html"), "rb") as fh:
                cuerpo = fh.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            return self.wfile.write(cuerpo)
        self.send_error(404)

    def do_POST(self):
        if not self.path.startswith("/api/buscar"):
            return self.send_error(404)
        try:
            largo = int(self.headers.get("Content-Length") or 0)
            if largo > 10000:
                raise ErrorDeUso("El pedido es demasiado grande.")
            datos = json.loads(self.rfile.read(largo) or b"{}")

            video_id = extraer_id(datos.get("url"))
            forzar_whisper = bool(datos.get("forzar_whisper"))

            if forzar_whisper:
                cues, titulo = transcribir_whisper(video_id)
                fuente, ventana = "whisperx", 0
            else:
                contenido, titulo = bajar_subs(video_id)
                cues = parsear_vtt(contenido)
                if not cues:
                    raise ErrorDeUso("Los subtítulos de este video vinieron vacíos.")
                fuente, ventana = "subtitulos", VENTANA_DUPLICADOS

            resultados = buscar(cues, datos.get("consulta"), video_id, ventana)
            self._responder(200, {
                "titulo": titulo,
                "video_id": video_id,
                "fuente": fuente,
                "resultados": resultados,
            })
        except ErrorDeUso as err:
            self._responder(400, {"error": str(err)})
        except Exception:
            # Nunca filtramos el stack ni el stderr crudo de yt-dlp a la UI.
            self._responder(500, {"error": "Algo falló al procesar el video."})


def main():
    servidor = ThreadingHTTPServer(("127.0.0.1", PUERTO), Handler)
    print("Buscador andando en http://127.0.0.1:%d" % PUERTO)
    print("Para cerrarlo: Ctrl+C")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nChau.")
        servidor.server_close()


if __name__ == "__main__":
    sys.exit(main())
