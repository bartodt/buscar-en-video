#!/usr/bin/env python3
"""Servidor local para buscar palabras dentro de los subtitulos de un video de YouTube."""

import contextlib
import html
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RAIZ = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.expanduser("~/.cache/buscar-en-video")
PUERTO = int(os.environ.get("BUSCAR_PUERTO") or 8765)
ORIGENES = ("http://127.0.0.1:%d" % PUERTO, "http://localhost:%d" % PUERTO)

# El idioma sale de aca y de ningun otro lado: antes estaba escrito por separado en
# el --sub-langs de yt-dlp, en la preferencia de pistas y en el --language de
# whisperx, y los tres se podian desincronizar.
IDIOMA = os.environ.get("BUSCAR_IDIOMA") or "es"

# Los subtitulos automaticos repiten cada linea mientras rota en pantalla; dos cues
# identicos dentro de esta ventana son la misma frase dicha una sola vez.
VENTANA_DUPLICADOS = 10
CONTEXTO = 60
# Una consulta de una o dos letras matchea decenas de miles de veces en un video
# largo: sin tope el JSON pesa megabytes y el navegador se cuelga armando el DOM.
MAX_RESULTADOS = 200

# Al mostrar la transcripcion entera el texto se corta en bloques con su timestamp.
# Los cues son por palabra: uno por linea seria ilegible.
LARGO_BLOQUE = 240
SEGUNDOS_BLOQUE = 30

# El .vtt se guarda crudo, asi que cambiar el parseo no lo invalida. Expira por otra
# razon: un video puede ganar subtitulos reales despues de haber tenido solo
# automaticos, y sin vencimiento nunca nos enterariamos.
TTL_CACHE_VTT = 30 * 24 * 3600

# Transcripcion con IA. Medido sobre 5 min del mismo audio, comparando contra los
# subtitulos de YouTube: turbo coincide 88.3%, large-v3 87.9%, medium 84.3% y small
# 81.9%. turbo gana en calidad y ademas es el mas rapido de los tres grandes (2:46
# contra 8:10 de large-v3), asi que no hay razon para usar otro en CPU.
MODELO_WHISPER = "large-v3-turbo"
# v3 guarda tambien la transcripcion cruda de whisperx: si cambia como se arman los
# cues se rehacen gratis, en vez de volver a transcribir el audio durante horas.
# El bump desde v2 invalida las transcripciones que hubiera guardadas, una sola vez.
VERSION_CACHE_WHISPER = 3


class ErrorDeUso(Exception):
    """Error con un mensaje pensado para mostrarle al usuario tal cual."""


# --- procesos externos -----------------------------------------------------

_HIJOS = set()
_TEMPORALES = set()
_LOCK_HIJOS = threading.Lock()


@contextlib.contextmanager
def _carpeta_temporal():
    """tempfile.TemporaryDirectory, pero anotada para poder borrarla al salir.

    Los threads del servidor son daemon: al cerrar la ventana mueren sin correr sus
    finally, y el wav de una transcripcion a medias (~170 MB en un video de 90 min)
    quedaba tirado en /var/folders.
    """
    tmp = tempfile.mkdtemp(prefix="buscar-en-video-")
    with _LOCK_HIJOS:
        _TEMPORALES.add(tmp)
    try:
        yield tmp
    finally:
        with _LOCK_HIJOS:
            _TEMPORALES.discard(tmp)
        shutil.rmtree(tmp, ignore_errors=True)


def _correr(comando, timeout, mensaje_timeout, mostrar_salida=False):
    """subprocess.run, pero con el hijo anotado para poder matarlo al salir.

    Sin el registro, cerrar la ventana mata al servidor y deja a whisperx
    transcribiendo al 100% de CPU hasta una hora, sin ventana que lo delate.
    Con mostrar_salida el stdout del hijo va a la terminal en vez de juntarse en
    memoria: es como se ve el progreso de una transcripcion larga.
    """
    proceso = subprocess.Popen(
        comando,
        stdout=None if mostrar_salida else subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    with _LOCK_HIJOS:
        _HIJOS.add(proceso)
    try:
        salida, error = proceso.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proceso.kill()
        proceso.communicate()
        raise ErrorDeUso(mensaje_timeout) from None
    finally:
        with _LOCK_HIJOS:
            _HIJOS.discard(proceso)
    return proceso.returncode, salida or "", error or ""


def _terminar_hijos():
    with _LOCK_HIJOS:
        hijos, temporales = list(_HIJOS), list(_TEMPORALES)
    for proceso in hijos:
        proceso.kill()
    for tmp in temporales:
        shutil.rmtree(tmp, ignore_errors=True)


def _matar_hijos(*_args):
    """Handler de SIGTERM/SIGHUP. start.command cuenta con esto para no dejar huerfanos."""
    _terminar_hijos()
    sys.exit(0)


def _exigir(binario, arreglo):
    if not shutil.which(binario):
        raise ErrorDeUso(
            "Falta instalar %s. Abrí la Terminal y corré:  %s" % (binario, arreglo)
        )


# --- cache -----------------------------------------------------------------

_CANDADOS = {}
_LOCK_CANDADOS = threading.Lock()


def _candado(clave):
    """Un candado por video: dos pestañas sobre el mismo link no lo bajan dos veces.

    Importa sobre todo en el modo IA: dos whisperx simultaneos, cada uno pidiendo
    todos los cores, dejan la maquina inusable y encima se pisan el archivo final.
    """
    with _LOCK_CANDADOS:
        return _CANDADOS.setdefault(clave, threading.Lock())


def _ruta_cache(nombre):
    return os.path.join(CACHE, nombre)


def _guardar_cache(nombre, texto):
    """Escribe a un temporal y renombra: un corte a mitad no deja un archivo trunco.

    os.replace es atomico dentro del mismo filesystem. Sin esto, un Ctrl+C durante la
    escritura dejaba medio .vtt en el cache y se servia como bueno para siempre.
    """
    os.makedirs(CACHE, exist_ok=True)
    ruta = _ruta_cache(nombre)
    parcial = ruta + ".parcial"
    with open(parcial, "w", encoding="utf-8") as fh:
        fh.write(texto)
    os.replace(parcial, ruta)


# --- normalizacion ---------------------------------------------------------

# La tabla se arma una vez por caracter visto y despues str.translate hace el trabajo
# en C: sobre un transcript de 3 h son 3 ms en vez de 27.
_TABLA_NORM = {}


def normalizar(texto):
    """Minusculas y sin tildes, preservando la longitud para no romper los offsets.

    La "ñ" tambien se descompone en "n", a proposito: es lo que hace que buscar
    "senuk" encuentre "Señuk" sin tener que saber donde esta la ñ en el teclado. El
    precio es que "año" tambien matchea "ano", y esta bien pagarlo.
    """
    for c in set(texto):
        if ord(c) not in _TABLA_NORM:
            base = unicodedata.normalize("NFD", c)[0].lower()
            _TABLA_NORM[ord(c)] = base if len(base) == 1 else c
    return texto.translate(_TABLA_NORM)


# --- yt-dlp ----------------------------------------------------------------

def extraer_id(url):
    # isinstance y no "url or": un numero o una lista en el JSON reventaban con
    # AttributeError y el usuario veia un 500 generico en vez del mensaje de siempre.
    url = url.strip() if isinstance(url, str) else ""
    patrones = (
        # El (?!...) del final evita que un id de 12 caracteres matchee los primeros
        # 11 y termine buscando, en silencio, dentro de otro video.
        r"(?:youtube\.com|youtube-nocookie\.com)/(?:watch\?(?:.*&)?v=|embed/|shorts/|live/|v/)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])",
        r"youtu\.be/([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])",
        r"^([A-Za-z0-9_-]{11})$",
    )
    for patron in patrones:
        match = re.search(patron, url)
        if match:
            return match.group(1)
    raise ErrorDeUso("Ese link no parece un video de YouTube. Pegá la URL completa.")


def _leer_cache(video_id, ignorar_ttl=False):
    vtt = _ruta_cache(video_id + ".vtt")
    if not os.path.exists(vtt):
        return None
    if not ignorar_ttl and time.time() - os.path.getmtime(vtt) > TTL_CACHE_VTT:
        return None
    try:
        with open(vtt, encoding="utf-8") as fh:
            contenido = fh.read()
    except (OSError, UnicodeDecodeError):
        return None
    if not contenido.strip():
        return None
    titulo = video_id
    try:
        with open(_ruta_cache(video_id + ".titulo"), encoding="utf-8") as fh:
            titulo = fh.read().strip() or video_id
    except (OSError, UnicodeDecodeError):
        pass
    return contenido, titulo


def _diagnosticar_fallo(salida, que="los subtítulos"):
    """Traduce el stderr de yt-dlp al castellano. Siempre termina lanzando."""
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
    # Es lo que arregla la enorme mayoria de los casos: YouTube cambia y yt-dlp se
    # queda viejo. Decirlo evita el "no anda mas" sin pista de por donde empezar.
    raise ErrorDeUso(
        "No se pudieron bajar %s de ese video. Si esto empezó de un día para el "
        "otro suele ser yt-dlp desactualizado: abrí la Terminal y corré  "
        "brew upgrade yt-dlp" % que
    )


# Pedimos una sola pista, la del idioma configurado. YouTube ofrece autosubs
# traducidos a cualquier idioma, pero solo la variante "-orig" es la transcripcion
# real del audio: "es" a secas puede ser una traduccion de la traduccion al ingles,
# con palabras cambiadas respecto de lo que se dice de verdad.
PREFERENCIA_SUBS = (IDIOMA + "-orig", IDIOMA)
NOMBRE_IDIOMA = {"es": "español", "en": "inglés", "pt": "portugués"}.get(IDIOMA, IDIOMA)
URL_VIDEO = "https://www.youtube.com/watch?v=%s"


def _idioma_de(archivo, video_id):
    """Con -o "%(id)s.%(ext)s" los subtitulos quedan como "<id>.<lang>.vtt"."""
    return archivo[len(video_id) + 1:-len(".vtt")]


def _titulo_de_info(tmp, base, respaldo):
    """El titulo real, del .info.json que yt-dlp deja junto a lo que bajo.

    Reconstruirlo del nombre del archivo daba la version saneada por yt-dlp: las
    barras cambiadas por otro caracter y el nombre recortado a 255 bytes.
    """
    try:
        with open(os.path.join(tmp, base + ".info.json"), encoding="utf-8") as fh:
            return (json.load(fh).get("title") or "").strip() or respaldo
    except (ValueError, OSError):
        return respaldo


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

    _exigir("yt-dlp", "brew install yt-dlp")

    with _candado("subs:" + video_id):
        # Otro pedido del mismo video pudo haberlo bajado mientras esperabamos.
        cacheado = _leer_cache(video_id)
        if cacheado:
            return cacheado
        try:
            return _bajar_subs(video_id)
        except ErrorDeUso:
            # Un cache vencido sigue siendo mejor que nada: si YouTube no responde o
            # no hay red, se busca sobre lo viejo antes que dejar al usuario a pie.
            vencido = _leer_cache(video_id, ignorar_ttl=True)
            if vencido:
                print("Aviso: no pude refrescar %s, uso los subtítulos guardados."
                      % video_id, file=sys.stderr)
                return vencido
            raise


def _bajar_subs(video_id):
    with _carpeta_temporal() as tmp:
        comando = [
            "yt-dlp",
            "--skip-download",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs", IDIOMA + ".*",
            "--sub-format", "vtt",
            "--write-info-json",
            "--no-playlist",
            "--no-warnings",
            "-o", os.path.join(tmp, "%(id)s.%(ext)s"),
            URL_VIDEO % video_id,
        ]
        codigo, salida, error = _correr(
            comando, 180, "YouTube tardó demasiado en responder. Probá de nuevo."
        )

        archivos = sorted(f for f in os.listdir(tmp) if f.endswith(".vtt"))
        if not archivos:
            if codigo != 0:
                _diagnosticar_fallo(error + salida)
            raise ErrorDeUso(
                "Ese video no tiene subtítulos en %s, ni siquiera automáticos, "
                "así que no hay texto donde buscar." % NOMBRE_IDIOMA
            )

        elegido = _elegir_sub(archivos, video_id)
        titulo = _titulo_de_info(tmp, video_id, video_id)
        with open(os.path.join(tmp, elegido), encoding="utf-8") as fh:
            contenido = fh.read()

    _guardar_cache(video_id + ".vtt", contenido)
    _guardar_cache(video_id + ".titulo", titulo)
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
    ruta = _ruta_cache(video_id + ".whisperx.json")
    if not os.path.exists(ruta):
        return None
    try:
        with open(ruta, encoding="utf-8") as fh:
            datos = json.load(fh)
    except (ValueError, OSError):
        return None
    # Una transcripcion hecha con otro modelo o en otro idioma no sirve: se rehace.
    if datos.get("modelo") != MODELO_WHISPER:
        return None
    if datos.get("idioma", IDIOMA) != IDIOMA:
        return None
    if datos.get("version") != VERSION_CACHE_WHISPER or not datos.get("transcripcion"):
        return None
    # Rearmar los cues desde el crudo cuesta milisegundos; transcribir de nuevo, horas.
    # Por eso el crudo se guarda aunque ocupe mas.
    cues = _cues_de_transcripcion(datos["transcripcion"])
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
            if inicio is None:
                # Descartarla la sacaba del indice, no solo del timing: una frase que
                # la contuviera dejaba de matchear porque le faltaba una palabra.
                inicio = 0.0
            cues.append((float(inicio), texto))
    return cues


def _cues_de_transcripcion(transcripcion):
    """Los cues por palabra, o los del segmento entero si la alineacion fallo."""
    return _cues_de_palabras(transcripcion) or _cues_de_segmentos(transcripcion)


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
            "Abrí la Terminal en esta carpeta y corré:  "
            "uv venv --python 3.12 && uv pip install -r requirements.txt"
        )
    # Se chequean antes de bajar nada: si faltan, subprocess tira FileNotFoundError y
    # el usuario terminaba viendo un "algo falló" generico en vez del comando a correr.
    _exigir("yt-dlp", "brew install yt-dlp")
    _exigir("ffmpeg", "brew install ffmpeg")

    with _candado("whisper:" + video_id):
        cacheado = _leer_cache_whisper(video_id)
        if cacheado:
            return cacheado
        return _transcribir_whisper(video_id, binario)


def _transcribir_whisper(video_id, binario):
    with _carpeta_temporal() as tmp:
        audio = os.path.join(tmp, "audio.wav")
        comando_audio = [
            "yt-dlp",
            "-x", "--audio-format", "wav",
            # Whisper trabaja en 16 kHz mono igual: pedirlo asi achica mucho el archivo.
            "--postprocessor-args", "ffmpeg:-ac 1 -ar 16000",
            # El titulo sale de aca. Antes era una segunda invocacion completa de
            # yt-dlp: un viaje de red mas y una chance mas de comerse un 429 justo
            # despues de haber bajado bien el audio.
            "--write-info-json",
            "--no-playlist",
            "--no-warnings",
            "-o", os.path.join(tmp, "audio.%(ext)s"),
            URL_VIDEO % video_id,
        ]
        _codigo, salida, error = _correr(
            comando_audio, 600, "YouTube tardó demasiado en responder. Probá de nuevo."
        )
        # Lo que decide no es el returncode sino que el wav haya quedado: yt-dlp puede
        # salir con 0 y no haber escrito nada si el postprocesador falló.
        if not os.path.exists(audio):
            _diagnosticar_fallo(error + salida, "el audio")

        titulo = _titulo_de_info(tmp, "audio", video_id)

        comando_whisper = [
            binario, audio,
            "--model", MODELO_WHISPER,
            "--language", IDIOMA,
            # ctranslate2 en CPU no tiene float16; int8 es lo que lo hace usable.
            "--compute_type", "int8",
            # Explicito para que un cambio de default en whisperx no nos mande a cuda.
            "--device", "cpu",
            "--threads", str(os.cpu_count() or 4),
            "--output_format", "json",
            "--output_dir", tmp,
            "--verbose", "False",
            # Imprime "Progress: 12.34%..." por stdout, que _correr deja salir a la
            # terminal. Sin esto la transcripcion corria a ciegas hasta 90 minutos.
            "--print_progress", "True",
        ]
        print("Transcribiendo %s con whisperx (%s)…" % (video_id, MODELO_WHISPER))
        codigo, _salida, error = _correr(
            comando_whisper, 5400,
            "La transcripción tardó demasiado. Probá con un video más corto.",
            mostrar_salida=True,
        )

        json_path = os.path.join(tmp, "audio.json")
        if codigo != 0 or not os.path.exists(json_path):
            _avisar_en_consola(error)
            raise ErrorDeUso("No se pudo transcribir el audio de ese video.")

        with open(json_path, encoding="utf-8") as fh:
            transcripcion = json.load(fh)

    cues = _cues_de_transcripcion(transcripcion)
    if not cues:
        raise ErrorDeUso("La transcripción de ese video vino vacía.")

    _guardar_cache(video_id + ".whisperx.json", json.dumps({
        "version": VERSION_CACHE_WHISPER,
        "modelo": MODELO_WHISPER,
        "idioma": IDIOMA,
        "titulo": titulo,
        "transcripcion": transcripcion,
    }, ensure_ascii=False))
    return cues, titulo


def _avisar_en_consola(salida):
    """El stderr crudo no va al navegador, pero sirve tenerlo en la ventana del servidor."""
    lineas = [linea for linea in (salida or "").splitlines() if linea.strip()][-20:]
    if lineas:
        print("whisperx falló:", file=sys.stderr)
        for linea in lineas:
            print("  " + linea, file=sys.stderr)


# --- parseo del vtt --------------------------------------------------------

_TAG_TIEMPO = re.compile(r"<(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3})>")
_ENCABEZADOS = ("WEBVTT", "Kind:", "Language:", "NOTE", "STYLE", "REGION",
                "X-TIMESTAMP-MAP")


def _a_segundos(marca):
    """Segundos enteros, o None si la marca no es un timestamp valido.

    Devolver None en vez de reventar importa: una linea de subtitulo que contenga
    "-->" (un video de programacion, por ejemplo) hacia que el ValueError se llevara
    puesta la busqueda entera en vez de perder un solo cue.
    """
    partes = marca.split(":")
    if len(partes) == 2:
        partes = ["0"] + partes
    if len(partes) != 3:
        return None
    try:
        horas, minutos, segundos = (float(p.replace(",", ".")) for p in partes)
    except ValueError:
        return None
    return int(horas * 3600 + minutos * 60 + segundos)


def _limpiar(texto):
    """Saca los tags del cue y desescapa las entidades, en ese orden.

    Al reves, un "&lt;b&gt;" escrito por el autor se volveria un tag de verdad y el
    regex se comeria el texto que viene despues. Sin el unescape, "AT&amp;T" quedaba
    tal cual en el indice y buscar "AT&T" no encontraba nada.
    """
    texto = re.sub(r"<[^>]+>", "", texto)
    texto = html.unescape(texto)
    return re.sub(r"\s+", " ", texto).strip()


def _piezas_de_linea(linea, inicio):
    """Parte una linea del vtt en (segundo, texto) usando los tags de tiempo inline.

    Los autosubs traen el timing de cada palabra dentro del propio cue
    ("hola<00:00:01.359><c> mundo</c>"). Aprovecharlo da precision por palabra sin
    bajar el audio ni transcribir: es casi lo mismo que consigue el modo IA, gratis.
    Una linea sin tags devuelve una sola pieza, que es lo que se hacia antes.
    """
    piezas, actual = [], inicio
    for indice, parte in enumerate(_TAG_TIEMPO.split(linea)):
        if indice % 2:                      # los impares son las marcas capturadas
            marca = _a_segundos(parte)
            if marca is not None:
                actual = marca
            continue
        texto = _limpiar(parte)
        if texto:
            piezas.append((actual, texto))
    return piezas


def parsear_vtt(contenido):
    """Devuelve [(segundo, texto)] por palabra, sin las repeticiones de los autosubs.

    La deduplicacion trabaja a nivel de linea, que es donde los autosubs repiten, y
    recien despues cada linea que sobrevive se abre en sus palabras con timing propio.
    """
    lineas = contenido.splitlines()
    crudos, inicio, fin_cue = [], None, None
    for numero, linea in enumerate(lineas):
        linea = linea.strip()
        if "-->" in linea:
            izquierda, _, derecha = linea.partition("-->")
            inicio = _a_segundos(izquierda.strip())
            # A la derecha viene la marca de fin y, en los autosubs, los ajustes de
            # posicion pegados atras ("align:start position:0%").
            marcas = derecha.split()
            fin_cue = _a_segundos(marcas[0]) if marcas else None
            continue
        if inicio is None or not linea:
            continue
        if linea.startswith(_ENCABEZADOS):
            continue
        # Identificador de cue: una linea suelta justo antes de un timestamp. Los
        # autosubs de YouTube no los traen, pero un vtt convertido desde srt si, y
        # sin esto los numeros de cue entraban al indice como texto hablado.
        if numero + 1 < len(lineas) and "-->" in lineas[numero + 1]:
            continue
        piezas = _piezas_de_linea(linea, inicio)
        if piezas:
            crudos.append((piezas[0][0], " ".join(t for _, t in piezas), piezas, fin_cue))

    # Los autosubs muestran la linea anterior como contexto de la siguiente: si una es
    # prefijo de la otra, se queda la version larga con el timestamp mas temprano. Lo
    # que distingue ese rollup de una frase repetida cinco minutos despues es que el
    # cue nuevo arranca donde termino el anterior, asi que la condicion es esa y no un
    # umbral de segundos: con un umbral, una linea que tardaba mas que el en crecer no
    # se fusionaba y el texto quedaba duplicado en el indice.
    fusionados = []
    for segundos, texto, piezas, fin in crudos:
        if fusionados and texto == fusionados[-1][1]:
            # Repeticion exacta: se queda la primera, que trae el timestamp real y,
            # cuando la repeticion viene sin tags, tambien el timing por palabra. Lo
            # unico que se toma de la repeticion es el fin: la linea sigue en pantalla.
            if fin is not None:
                fusionados[-1] = fusionados[-1][:3] + (fin,)
            continue
        anterior_termina = fusionados[-1][3] if fusionados else None
        if (fusionados and texto.startswith(fusionados[-1][1])
                and anterior_termina is not None and segundos <= anterior_termina + 1):
            arranque = fusionados[-1][0]
            fusionados[-1] = (arranque, texto,
                              [(arranque, piezas[0][1])] + piezas[1:], fin)
            continue
        fusionados.append((segundos, texto, piezas, fin))

    limpios = []
    for segundos, texto, piezas, _fin in fusionados:
        repetido = any(
            texto == prev_texto and segundos - prev_segundos <= VENTANA_DUPLICADOS
            for prev_segundos, prev_texto, _ in limpios[-8:]
        )
        if not repetido:
            limpios.append((segundos, texto, piezas))
    return [pieza for _, _, piezas in limpios for pieza in piezas]


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


# El indice de un video de 3 h son unos 2 MB, asi que guardamos unos pocos.
MAX_INDICES = 6
_INDICES = {}
_LOCK_INDICES = threading.Lock()


def indice_de(video_id, forzar_whisper):
    """(indice, titulo, fuente), armando el indice una sola vez por video.

    Sin esto, cada consulta volvia a leer el cache del disco, a re-parsear el vtt
    entero y a re-normalizarlo caracter por caracter: decenas de milisegundos por
    tecla, para un resultado que no cambia mientras no cambie el video.
    """
    fuente = "whisperx" if forzar_whisper else "subtitulos"
    clave = (video_id, fuente)
    with _LOCK_INDICES:
        if clave in _INDICES:
            _INDICES[clave] = _INDICES.pop(clave)   # al final: se descarta el mas viejo
            indice, titulo = _INDICES[clave]
            return indice, titulo, fuente

    if forzar_whisper:
        cues, titulo = transcribir_whisper(video_id)
    else:
        contenido, titulo = bajar_subs(video_id)
        cues = parsear_vtt(contenido)
        if not cues:
            raise ErrorDeUso("Los subtítulos de este video vinieron vacíos.")

    indice = construir_indice(cues)
    with _LOCK_INDICES:
        _INDICES[clave] = (indice, titulo)
        while len(_INDICES) > MAX_INDICES:
            _INDICES.pop(next(iter(_INDICES)))
    return indice, titulo, fuente


def agrupar(completo, offsets):
    """Corta el texto corrido en bloques legibles, cada uno con el segundo en que arranca.

    Corta por largo o por salto de tiempo, lo que llegue primero: un bloque que abarca
    medio minuto de video ya es demasiado grande para que su timestamp signifique algo,
    y en un video con silencios largos pasa aunque el bloque sea corto.
    """
    bloques, inicio, total = [], 0, len(completo)
    while inicio < total:
        while inicio < total and completo[inicio].isspace():
            inicio += 1
        if inicio >= total:
            break
        tope = min(total, inicio + LARGO_BLOQUE)
        fin = tope
        arranque = offsets[inicio]
        for posicion in range(inicio, tope):
            if offsets[posicion] - arranque > SEGUNDOS_BLOQUE:
                fin = posicion
                break
        # Cortar en el espacio anterior para no partir una palabra al medio.
        if fin < total:
            corte = completo.rfind(" ", inicio, fin)
            if corte > inicio:
                fin = corte
        texto = completo[inicio:fin].strip()
        if texto:
            bloques.append((arranque, texto))
        inicio = fin
    return bloques


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


def _barrer(aguja, pajar, mapa, completo, offsets, video_id, aproximado):
    """Todas las apariciones de `aguja` en `pajar`, ubicadas en el texto original.

    No deduplica: de las repeticiones de los autosubs se encarga parsear_vtt, que
    trabaja a nivel de linea y sabe cuales son la misma frase rotando en pantalla.
    Aca habia un segundo filtro por tiempo que descartaba cualquier match a menos de
    diez segundos del anterior, y se llevaba puestas menciones reales: medido sobre
    un video de una hora, "que" pasaba de 200 menciones a 63.

    Devuelve (resultados, total): se arman como mucho MAX_RESULTADOS, pero el total
    se sigue contando para poder avisar que la lista quedo cortada.
    """
    resultados, desde, total = [], 0, 0
    while True:
        idx = pajar.find(aguja, desde)
        if idx == -1:
            break
        # No idx + 1: con el paso de a uno, "jaja" matcheaba tres veces dentro de
        # "jajajaja" y salian tres resultados identicos, con el mismo segundo.
        desde = idx + len(aguja)
        real = mapa[idx] if mapa else idx
        # En el modo comprimido el largo de la aguja no incluye los espacios que si
        # tiene el texto original, asi que el fin sale del mapa y no de una suma.
        real_fin = mapa[idx + len(aguja) - 1] + 1 if mapa else idx + len(aguja)
        segundos = offsets[real]
        total += 1
        if len(resultados) >= MAX_RESULTADOS:
            continue

        arranque = max(0, real - CONTEXTO)
        fin = min(len(completo), real_fin + CONTEXTO)
        # Correrse hasta el espacio mas cercano: cortar a mitad de palabra dejaba
        # fragmentos como "…te larga que sirve para…" en vez de "…bastante larga…".
        if arranque > 0:
            espacio = completo.find(" ", arranque, real)
            if espacio != -1:
                arranque = espacio + 1
        if fin < len(completo):
            espacio = completo.rfind(" ", real_fin, fin)
            if espacio != -1:
                fin = espacio
        fragmento = completo[arranque:fin].strip()
        if arranque > 0:
            fragmento = "…" + fragmento
        if fin < len(completo):
            fragmento = fragmento + "…"

        resultados.append(_resultado(segundos, fragmento, video_id, aproximado))
    return resultados, total


def _resultado(segundos, texto, video_id, aproximado=False):
    return {
        "segundos": int(segundos),
        "timestamp": formatear(segundos),
        "texto": texto,
        "link": "https://youtu.be/%s?t=%d" % (video_id, int(segundos)),
        "aproximado": aproximado,
    }


def transcripcion(indice, video_id):
    """La transcripcion entera, con la misma forma que los resultados de una busqueda.

    Asi el navegador la pinta con el mismo codigo: cada bloque es un link al video en
    el momento en que arranca.
    """
    completo, _norm, offsets = indice
    return [_resultado(segundos, texto, video_id)
            for segundos, texto in agrupar(completo, offsets)]


def buscar(indice, consulta, video_id):
    """Devuelve (resultados, total) para la consulta sobre un indice ya armado."""
    if not isinstance(consulta, str):
        consulta = ""
    consulta = re.sub(r"\s+", " ", consulta.strip())
    if not consulta:
        raise ErrorDeUso("Escribí una palabra o frase para buscar.")

    completo, completo_norm, offsets = indice
    objetivo = normalizar(consulta)

    exactos, total = _barrer(objetivo, completo_norm, None, completo, offsets,
                             video_id, False)
    if exactos:
        return exactos, total

    # Sin espacios: "popstars" encuentra "Pop stars". Se pide un largo minimo porque
    # pegar las palabras hace que una consulta corta matchee dentro de otra frase.
    if len(objetivo.replace(" ", "")) >= LARGO_MINIMO_APROXIMADO:
        comprimido, mapa = _comprimir(completo_norm)
        sueltos, total = _barrer(objetivo.replace(" ", ""), comprimido, mapa, completo,
                                 offsets, video_id, True)
        if sueltos:
            return sueltos, total

    # Ultimo intento: recortar el final para que "popstars" alcance a "popstar".
    if " " not in objetivo and len(objetivo) >= LARGO_MINIMO_APROXIMADO + 1:
        for recorte in range(1, RECORTE_MAXIMO + 1):
            raiz = objetivo[:-recorte]
            if len(raiz) < LARGO_MINIMO_APROXIMADO:
                break
            parciales, total = _barrer(raiz, completo_norm, None, completo, offsets,
                                       video_id, True)
            if parciales:
                return parciales, total
    return [], 0


# --- servidor --------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def _responder(self, codigo, payload):
        """Si el usuario cerro la pestaña, el write falla y no vale un traceback."""
        cuerpo = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)
        except OSError:
            pass

    def _mismo_origen(self):
        """Escuchar solo en 127.0.0.1 no alcanza: el navegador del usuario sigue llegando.

        Un fetch cross-origin con Content-Type JSON queda frenado por el preflight,
        pero un <form enctype="text/plain"> no lo dispara y su cuerpo se puede armar
        como JSON valido. Sin este chequeo, cualquier pagina que el usuario visitara
        podia lanzarle una transcripcion de 90 minutos al 100% de CPU. El Host ademas
        cierra el rebinding de DNS, que es lo unico que permitiria leer la respuesta.
        """
        anfitrion = (self.headers.get("Host") or "").split(":")[0]
        if anfitrion not in ("127.0.0.1", "localhost"):
            return False
        sitio = self.headers.get("Sec-Fetch-Site")
        if sitio and sitio not in ("same-origin", "none"):
            return False
        origen = self.headers.get("Origin")
        return not origen or origen in ORIGENES

    def do_GET(self):
        if self.path == "/api/salud":
            return self._responder(200, {"ok": True})
        if self.path in ("/", "/index.html"):
            try:
                with open(os.path.join(RAIZ, "index.html"), "rb") as fh:
                    cuerpo = fh.read()
            except OSError:
                return self.send_error(500, "No encuentro index.html")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            return self.wfile.write(cuerpo)
        self.send_error(404)

    def do_POST(self):
        if self.path == "/api/buscar":
            return self._api(self._buscar)
        if self.path == "/api/transcripcion":
            return self._api(self._transcripcion)
        self.send_error(404)

    def _api(self, accion):
        """Lo comun a las dos rutas: chequeo de origen, cuerpo, video y errores.

        Las dos devuelven `resultados` con la misma forma, asi que el navegador las
        pinta con el mismo codigo.
        """
        if not self._mismo_origen():
            return self.send_error(403, "Pedido de otro origen")
        try:
            datos = self._leer_json()
            video_id = extraer_id(datos.get("url"))
            indice, titulo, fuente = indice_de(
                video_id, bool(datos.get("forzar_whisper"))
            )
            payload = accion(datos, indice, video_id)
            payload.update({"titulo": titulo, "video_id": video_id, "fuente": fuente})
        except ErrorDeUso as err:
            return self._responder(400, {"error": str(err)})
        except Exception:
            # Nunca filtramos el stack a la UI, pero sin imprimirlo aca el 500 era
            # mudo: la interfaz manda a mirar la Terminal y no habia nada que mirar.
            traceback.print_exc()
            return self._responder(500, {"error": "Algo falló al procesar el video."})
        # Fuera del try a proposito: si el write falla porque cerraron la pestaña, no
        # tiene sentido intentar un 500 sobre el mismo socket ya empezado.
        self._responder(200, payload)

    def _leer_json(self):
        try:
            largo = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ErrorDeUso("El pedido vino mal armado.") from None
        if largo > 10000:
            raise ErrorDeUso("El pedido es demasiado grande.")
        try:
            datos = json.loads(self.rfile.read(largo) or b"{}")
        except ValueError:
            raise ErrorDeUso("El pedido vino mal armado.") from None
        if not isinstance(datos, dict):
            raise ErrorDeUso("El pedido vino mal armado.")
        return datos

    def _buscar(self, datos, indice, video_id):
        resultados, total = buscar(indice, datos.get("consulta"), video_id)
        return {"resultados": resultados, "total": total}

    def _transcripcion(self, _datos, indice, video_id):
        bloques = transcripcion(indice, video_id)
        return {"resultados": bloques, "total": len(bloques)}


def main():
    # Sin esto, Python bufferea por bloques cuando la salida no es una terminal y los
    # avisos aparecen despues del progreso de whisperx, o directamente al final.
    sys.stdout.reconfigure(line_buffering=True)
    # start.command manda SIGTERM al cerrar la ventana y cuenta con que esto se lleve
    # puestos a yt-dlp y whisperx: si no, siguen vivos comiendose todos los cores.
    # SIGHUP tambien, porque al cerrar la ventana la Terminal se lo manda directo a
    # este proceso y el default de Python es morirse sin correr ningun handler.
    for senal in (signal.SIGTERM, getattr(signal, "SIGHUP", None)):
        if senal is not None:
            signal.signal(senal, _matar_hijos)
    try:
        servidor = ThreadingHTTPServer(("127.0.0.1", PUERTO), Handler)
    except OSError as err:
        print("No pude abrir el puerto %d (%s)." % (PUERTO, err), file=sys.stderr)
        print("¿Ya tenés otra ventana del buscador abierta?", file=sys.stderr)
        return 1
    print("Buscador andando en http://127.0.0.1:%d" % PUERTO)
    print("Para cerrarlo: Ctrl+C")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nChau.")
    finally:
        _terminar_hijos()
        servidor.server_close()


if __name__ == "__main__":
    sys.exit(main())
