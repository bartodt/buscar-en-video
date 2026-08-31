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
PUERTO = 8765
ORIGENES = ("http://127.0.0.1:%d" % PUERTO, "http://localhost:%d" % PUERTO)

# El idioma sale de aca y de ningun otro lado: antes estaba escrito por separado en
# el --sub-langs de yt-dlp, en la preferencia de pistas y en el --language de
# whisperx, y los tres se podian desincronizar.
IDIOMA = "es"

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
    """tempfile.TemporaryDirectory, pero anotada para que _terminar_hijos la borre."""
    tmp = tempfile.mkdtemp(prefix="buscar-en-video-")
    with _LOCK_HIJOS:
        _TEMPORALES.add(tmp)
    try:
        yield tmp
    finally:
        with _LOCK_HIJOS:
            _TEMPORALES.discard(tmp)
        shutil.rmtree(tmp, ignore_errors=True)


def _matar(proceso):
    """SIGKILL a todo el grupo, no solo al hijo.

    yt-dlp lanza ffmpeg y le pasa sus pipes. Matando solo al padre, ffmpeg seguia
    vivo comiendose los cores y, peor, manteniendo abierto el stderr heredado: el
    communicate() de abajo esperaba un EOF que no llegaba nunca y colgaba el thread
    del pedido para siempre. Por eso los hijos arrancan en su propia sesion.
    """
    try:
        os.killpg(os.getpgid(proceso.pid), signal.SIGKILL)
    except OSError:
        proceso.kill()


def _correr(comando, timeout, mensaje_timeout, mostrar_salida=False,
            entorno=None, al_progreso=None):
    """subprocess.run, pero con el hijo anotado para poder matarlo al salir.

    Los threads del servidor son daemon: al cerrar la ventana mueren sin correr sus
    finally. Sin este registro, cerrar la ventana dejaba a whisperx transcribiendo al
    100% de CPU hasta una hora y el wav a medias (~170 MB en un video de 90 min)
    tirado en /var/folders, sin ninguna ventana que lo delatara.
    Con mostrar_salida el stdout del hijo va a la terminal en vez de juntarse en
    memoria: es como se ve el progreso de una transcripcion larga.
    Con al_progreso el stdout se lee linea por linea y cada una se le pasa a esa
    funcion ademas de escribirse en la terminal. Es lo que alimenta /api/progreso:
    empaquetada como .app no hay ninguna terminal donde mirar, asi que el porcentaje
    tiene que llegar al navegador o la espera de una transcripcion es a ciegas.
    """
    if al_progreso is not None:
        return _correr_con_progreso(
            comando, timeout, mensaje_timeout, entorno, al_progreso
        )
    proceso = subprocess.Popen(
        comando,
        stdout=None if mostrar_salida else subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env=entorno,
    )
    with _LOCK_HIJOS:
        _HIJOS.add(proceso)
    try:
        salida, error = proceso.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _matar(proceso)
        proceso.communicate()
        raise ErrorDeUso(mensaje_timeout) from None
    finally:
        with _LOCK_HIJOS:
            _HIJOS.discard(proceso)
    return proceso.returncode, salida or "", error or ""


def _correr_con_progreso(comando, timeout, mensaje_timeout, entorno, al_progreso):
    """Igual que _correr, pero drenando stdout con un thread propio.

    No se puede usar communicate() para esto: seria el segundo lector del mismo pipe
    y las dos mitades se roban las lineas. Con dos threads (uno por pipe) y un wait()
    aparte, el progreso sale en tiempo real y el stderr sigue completo para el
    diagnostico de errores.
    """
    # Sin esto Python bufferea por bloques cuando la salida es un pipe y los porcentajes
    # llegan todos juntos al final, cuando ya no le sirven a nadie. Vale para los dos
    # hijos que pasan por aca: yt-dlp y whisperx son los dos programas en Python.
    entorno = dict(entorno or os.environ, PYTHONUNBUFFERED="1")
    proceso = subprocess.Popen(
        comando,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        start_new_session=True,
        env=entorno,
    )
    with _LOCK_HIJOS:
        _HIJOS.add(proceso)
    errores = []

    def _drenar_stdout():
        for linea in proceso.stdout:
            # El progreso viaja en lineas que terminan en \r, no en \n: whisperx
            # repinta el porcentaje sobre si mismo. Sin este split la barra entera
            # llega como una sola linea gigante al final y no sirve para nada.
            for pedazo in linea.replace("\r", "\n").splitlines():
                if pedazo.strip():
                    print(pedazo)
                    try:
                        al_progreso(pedazo)
                    except Exception:  # el progreso es cosmetico: no puede tumbar el job
                        pass

    def _drenar_stderr():
        errores.append(proceso.stderr.read() or "")

    hilos = [
        threading.Thread(target=_drenar_stdout, daemon=True),
        threading.Thread(target=_drenar_stderr, daemon=True),
    ]
    for hilo in hilos:
        hilo.start()
    try:
        proceso.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _matar(proceso)
        proceso.wait()
        raise ErrorDeUso(mensaje_timeout) from None
    finally:
        with _LOCK_HIJOS:
            _HIJOS.discard(proceso)
        for hilo in hilos:
            hilo.join(timeout=5)
    return proceso.returncode, "", "".join(errores)


def _terminar_hijos(*senal):
    """Mata a los hijos y borra los temporales; ver _correr.

    Con argumentos es el handler de SIGTERM/SIGHUP y ademas termina el proceso:
    start.command cuenta con eso para no dejar huerfanos al cerrar la ventana.
    """
    with _LOCK_HIJOS:
        hijos, temporales = list(_HIJOS), list(_TEMPORALES)
    for proceso in hijos:
        _matar(proceso)
    for tmp in temporales:
        shutil.rmtree(tmp, ignore_errors=True)
    if senal:
        sys.exit(0)


def _exigir(binario, arreglo):
    if not shutil.which(binario):
        raise ErrorDeUso(
            "Falta instalar %s. Abrí la Terminal y corré:  %s" % (binario, arreglo)
        )


# --- progreso --------------------------------------------------------------

# Uno solo, el del trabajo mas reciente, no un diccionario por video: el caso real es
# una persona con una pestaña buscando una cosa a la vez, y el navegador pregunta por
# "lo que esta pasando" sin saber ningun id. Dos busquedas simultaneas se pisan el
# porcentaje entre si, y eso es todo lo que pasa.
#
# Lo que si importa es _TRABAJOS: sin el contador, la primera de dos busquedas en
# terminar le borraba el progreso a la otra, que seguia corriendo. Se veia como el
# porcentaje desapareciendo en la mitad de una transcripcion de dos minutos.
_PROGRESO = {"etapa": None, "pct": None}
_TRABAJOS = 0
_LOCK_PROGRESO = threading.Lock()

_PCT_WHISPERX = re.compile(r"Progress:\s*([\d.]+)\s*%")
_PCT_YTDLP = re.compile(r"\[download\]\s+([\d.]+)\s*%")


def _fijar_progreso(etapa, pct=None):
    with _LOCK_PROGRESO:
        _PROGRESO["etapa"] = etapa
        _PROGRESO["pct"] = pct


def _abrir_trabajo():
    global _TRABAJOS
    with _LOCK_PROGRESO:
        _TRABAJOS += 1


def _cerrar_trabajo():
    """Limpia el progreso solo cuando no queda ningun trabajo en curso."""
    global _TRABAJOS
    with _LOCK_PROGRESO:
        _TRABAJOS = max(0, _TRABAJOS - 1)
        if _TRABAJOS == 0:
            _PROGRESO["etapa"] = None
            _PROGRESO["pct"] = None


def _ver_progreso():
    with _LOCK_PROGRESO:
        return {"etapa": _PROGRESO["etapa"], "pct": _PROGRESO["pct"]}


def _modelo_ya_bajado():
    """Si el modelo esta en el cache de Hugging Face, la espera es de calculo y no de red.

    Cambia el cartel que ve la persona: la primera corrida se lleva ~1,9 GB de descarga y
    ahi conviene decirlo, porque son varios minutos en los que whisperx no imprime nada y
    parece colgado. De la segunda en adelante seria mentira.
    """
    hub = os.path.expanduser("~/.cache/huggingface/hub")
    try:
        return any("faster-whisper" in nombre for nombre in os.listdir(hub))
    except OSError:
        return False


def _observar(etapa, patron, etapa_2=None):
    """Devuelve el callback de _correr que va traduciendo la salida a un porcentaje.

    whisperx cuenta de 0 a 100 dos veces —primero transcribe, despues alinea palabra por
    palabra contra el audio— y sin etapa_2 la barra llegaba al 100% y volvia al 20% sin
    ninguna explicacion. El salto para atras es la senal de que empezo la segunda pasada.
    """
    estado = {"etapa": etapa, "ultimo": -1.0}

    def _mirar(linea):
        encontrado = patron.search(linea)
        if not encontrado:
            return
        pct = float(encontrado.group(1))
        if etapa_2 and pct < estado["ultimo"]:
            estado["etapa"] = etapa_2
        estado["ultimo"] = pct
        _fijar_progreso(estado["etapa"], pct)
    return _mirar


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
    """Devuelve (contenido_vtt, titulo, idioma) si hay algo guardado y vigente.

    Sin el .meta.json no sabemos de que pista salio el vtt, y esa es justamente la
    diferencia entre la transcripcion real y una traduccion automatica: se rebaja.
    """
    vtt = _ruta_cache(video_id + ".vtt")
    if not os.path.exists(vtt):
        return None
    if not ignorar_ttl and time.time() - os.path.getmtime(vtt) > TTL_CACHE_VTT:
        return None
    try:
        with open(vtt, encoding="utf-8") as fh:
            contenido = fh.read()
        with open(_ruta_cache(video_id + ".meta.json"), encoding="utf-8") as fh:
            meta = json.load(fh)
    except (ValueError, OSError):
        return None
    if not contenido.strip():
        return None
    return contenido, meta.get("titulo") or video_id, meta.get("idioma") or ""


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
    """(archivo, idioma) de la mejor pista que haya bajado."""
    por_idioma = {_idioma_de(f, video_id): f for f in archivos}
    for idioma in PREFERENCIA_SUBS:
        if idioma in por_idioma:
            return por_idioma[idioma], idioma
    # Ultimo recurso: alguna variante suelta ("es-419", "es-US"). En un video hablado
    # en otro idioma eso es una traduccion automatica, asi que se avisa.
    return archivos[0], _idioma_de(archivos[0], video_id)


def _aviso_de(idioma, vencido=False):
    """El texto que la interfaz muestra al lado del titulo, o None si no hay nada raro."""
    if vencido:
        return "subtítulos guardados, no pude refrescarlos"
    if idioma and idioma not in PREFERENCIA_SUBS:
        return ("subtítulos traducidos automáticamente, las palabras pueden no ser "
                "las que se dijeron")
    return None


def _con_aviso(cacheado, vencido=False):
    """(contenido, titulo, aviso) a partir de lo que devolvio _leer_cache."""
    contenido, titulo, idioma = cacheado
    return contenido, titulo, _aviso_de(idioma, vencido)


def bajar_subs(video_id):
    """Devuelve (contenido_vtt, titulo, aviso). Usa el cache si ya se bajó antes."""
    cacheado = _leer_cache(video_id)
    if cacheado:
        return _con_aviso(cacheado)

    _exigir("yt-dlp", "brew install yt-dlp")

    with _candado("subs:" + video_id):
        # Otro pedido del mismo video pudo haberlo bajado mientras esperabamos.
        cacheado = _leer_cache(video_id)
        if cacheado:
            return _con_aviso(cacheado)
        try:
            return _bajar_subs(video_id)
        except ErrorDeUso:
            # Un cache vencido sigue siendo mejor que nada: si YouTube no responde o
            # no hay red, se busca sobre lo viejo antes que dejar al usuario a pie.
            # El aviso viaja hasta la interfaz: un print a stderr no lo ve nadie.
            vencido = _leer_cache(video_id, ignorar_ttl=True)
            if vencido:
                return _con_aviso(vencido, vencido=True)
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
                "Ese video no tiene subtítulos en español, ni siquiera "
                "automáticos, así que no hay texto donde buscar."
            )

        elegido, idioma = _elegir_sub(archivos, video_id)
        titulo = _titulo_de_info(tmp, video_id, video_id)
        with open(os.path.join(tmp, elegido), encoding="utf-8") as fh:
            contenido = fh.read()

    _guardar_cache(video_id + ".vtt", contenido)
    _guardar_cache(video_id + ".meta.json",
                   json.dumps({"titulo": titulo, "idioma": idioma}, ensure_ascii=False))
    return contenido, titulo, _aviso_de(idioma)


# --- whisperx (transcripcion con IA) ---------------------------------------

def _hilos():
    """Solo los cores de rendimiento.

    os.cpu_count() en Apple Silicon cuenta tambien los de eficiencia, y ctranslate2
    reparte el trabajo parejo entre todos: los lentos terminan marcando el ritmo.
    Sin medir todavia sobre este equipo; si no mejora, volver a os.cpu_count().
    """
    try:
        return max(1, int(subprocess.check_output(
            ["sysctl", "-n", "hw.perflevel0.logicalcpu"], text=True)))
    except (OSError, ValueError, subprocess.SubprocessError):
        return os.cpu_count() or 4


def _comando_whisperx():
    """Devuelve (comando, entorno) para invocar whisperx, o (None, None) si no esta.

    Nunca el script `bin/whisperx`, siempre `python -m whisperx`. El script lleva la
    ruta absoluta del interprete escrita en el shebang: sigue existiendo despues de
    mover la carpeta, asi que se encuentra igual, pero explota con "bad interpreter".
    Invocando al interprete a mano el modulo se resuelve por PYTHONPATH y la carpeta
    se puede mover a cualquier lado. Es lo que hace posible la .app.

    Tres ubicaciones, en orden: adentro del bundle, en el .venv del proyecto (la
    instalacion de desarrollo), o un whisperx suelto en el PATH.
    """
    py_bundle = os.path.join(RAIZ, "python", "bin", "python3")
    libs = os.path.join(RAIZ, "pylibs")
    if os.path.exists(py_bundle) and os.path.isdir(os.path.join(libs, "whisperx")):
        return [py_bundle, "-m", "whisperx"], dict(os.environ, PYTHONPATH=libs)
    py_venv = os.path.join(RAIZ, ".venv", "bin", "python3")
    if os.path.exists(py_venv):
        return [py_venv, "-m", "whisperx"], None
    suelto = shutil.which("whisperx")
    if suelto:
        return [suelto], None
    return None, None


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

    comando_base, entorno = _comando_whisperx()
    if not comando_base:
        raise ErrorDeUso(
            "El modo preciso con IA no está disponible en esta copia de la app. "
            "Probá con el modo normal, que no lo necesita."
        )
    # Se chequean antes de bajar nada: si faltan, subprocess tira FileNotFoundError y
    # el usuario terminaba viendo un "algo falló" generico en vez del comando a correr.
    _exigir("yt-dlp", "brew install yt-dlp")
    _exigir("ffmpeg", "brew install ffmpeg")

    with _candado("whisper:" + video_id):
        cacheado = _leer_cache_whisper(video_id)
        if cacheado:
            return cacheado
        return _transcribir_whisper(video_id, comando_base, entorno)


def _transcribir_whisper(video_id, comando_base, entorno):
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
        _fijar_progreso("bajando el audio")
        _codigo, salida, error = _correr(
            comando_audio, 600, "YouTube tardó demasiado en responder. Probá de nuevo.",
            al_progreso=_observar("bajando el audio", _PCT_YTDLP),
        )
        # Lo que decide no es el returncode sino que el wav haya quedado: yt-dlp puede
        # salir con 0 y no haber escrito nada si el postprocesador falló.
        if not os.path.exists(audio):
            _diagnosticar_fallo(error + salida, "el audio")

        titulo = _titulo_de_info(tmp, "audio", video_id)

        comando_whisper = [
            *comando_base, audio,
            "--model", MODELO_WHISPER,
            "--language", IDIOMA,
            # ctranslate2 en CPU no tiene float16; int8 es lo que lo hace usable.
            "--compute_type", "int8",
            # Explicito para que un cambio de default en whisperx no nos mande a cuda.
            "--device", "cpu",
            "--threads", str(_hilos()),
            "--output_format", "json",
            "--output_dir", tmp,
            "--verbose", "False",
            # Imprime "Progress: 12.34%..." por stdout, que _correr deja salir a la
            # terminal. Sin esto la transcripcion corria a ciegas hasta 90 minutos.
            "--print_progress", "True",
        ]
        print("Transcribiendo %s con whisperx (%s)…" % (video_id, MODELO_WHISPER))
        # Declarada de antemano porque whisperx no imprime nada durante la carga del
        # modelo, y sus "Progress:" ademas llegan de golpe al final: el cartel de la
        # etapa es lo unico que la persona va a tener durante casi toda la espera.
        _fijar_progreso("transcribiendo con IA" if _modelo_ya_bajado()
                        else "bajando el modelo de IA (~1,9 GB, una sola vez)")
        codigo, _salida, error = _correr(
            comando_whisper, 5400,
            "La transcripción tardó demasiado. Probá con un video más corto.",
            entorno=entorno,
            al_progreso=_observar("transcribiendo", _PCT_WHISPERX,
                                  "alineando las palabras"),
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
    crudos, inicio, fin_cue, en_cue = [], None, None, False
    for numero, linea in enumerate(lineas):
        linea = linea.strip()
        # La linea en blanco cierra el cue: es lo unico que distingue una linea
        # estructural de una hablada, porque las dos pueden decir "NOTE ...".
        if not linea:
            en_cue = False
            continue
        if "-->" in linea:
            izquierda, _, derecha = linea.partition("-->")
            inicio = _a_segundos(izquierda.strip())
            # A la derecha viene la marca de fin y, en los autosubs, los ajustes de
            # posicion pegados atras ("align:start position:0%").
            marcas = derecha.split()
            fin_cue = _a_segundos(marcas[0]) if marcas else None
            en_cue = True
            continue
        if inicio is None:
            continue
        # Fuera de un cue, NOTE/STYLE/REGION abren un bloque estructural. Adentro,
        # "NOTE que esto importa" es lo que alguien dijo y va al indice.
        if not en_cue and linea.startswith(_ENCABEZADOS):
            continue
        # Identificador de cue: una linea suelta entre un blanco y un timestamp. Los
        # autosubs de YouTube no los traen, pero un vtt convertido desde srt si, y
        # sin esto los numeros de cue entraban al indice como texto hablado. El
        # not en_cue evita comerse la ultima linea de un cue sin blanco que lo cierre.
        if not en_cue and numero + 1 < len(lineas) and "-->" in lineas[numero + 1]:
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
            arranque, previo, piezas_previas = fusionados[-1][:3]
            # Cuando el cue nuevo reescribe el texto viejo sin tags, su primera pieza
            # trae todo junto en un solo tiempo y las de antes traian una marca por
            # palabra: nos quedamos con las viejas, que es donde esta la precision.
            nuevas = (piezas_previas if piezas[0][1] == previo
                      else [(arranque, piezas[0][1])])
            fusionados[-1] = (arranque, texto, nuevas + piezas[1:], fin)
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


# El indice de un video de 3 h son unos 2,5 MB y se mira un video a la vez: con los
# dos ultimos alcanza para ir y venir entre subtitulos e IA sin rearmar nada.
MAX_INDICES = 2
_INDICES = {}
_LOCK_INDICES = threading.Lock()


def indice_de(video_id, forzar_whisper):
    """(indice, titulo, fuente, aviso), armando el indice una sola vez por video.

    Sin esto, cada consulta volvia a leer el cache del disco, a re-parsear el vtt
    entero y a re-normalizarlo caracter por caracter: decenas de milisegundos por
    tecla, para un resultado que no cambia mientras no cambie el video.
    """
    fuente = "whisperx" if forzar_whisper else "subtitulos"
    clave = (video_id, fuente)
    with _LOCK_INDICES:
        if clave in _INDICES:
            indice, titulo, aviso = _INDICES[clave]
            return indice, titulo, fuente, aviso

    aviso = None
    if forzar_whisper:
        cues, titulo = transcribir_whisper(video_id)
    else:
        contenido, titulo, aviso = bajar_subs(video_id)
        cues = parsear_vtt(contenido)
        if not cues:
            raise ErrorDeUso("Los subtítulos de este video vinieron vacíos.")

    indice = construir_indice(cues)
    with _LOCK_INDICES:
        if len(_INDICES) >= MAX_INDICES:
            _INDICES.clear()
        _INDICES[clave] = (indice, titulo, aviso)
    return indice, titulo, fuente, aviso


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

    Devuelve (resultados, total): cada resultado es una tarjeta, el total cuenta las
    menciones una por una. No son lo mismo, ver _agrupar.
    """
    crudos, desde = [], 0
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
        crudos.append((real, real_fin, offsets[real]))

    resultados = [_tarjeta(grupo, completo, video_id, aproximado)
                  for grupo in _agrupar(crudos)]
    return resultados, len(crudos)


# Cuando alguien repite una palabra, las menciones caen a menos de CONTEXTO caracteres
# una de otra y las dos tarjetas terminan mostrando casi la misma frase, con el
# resaltado en distinto lugar. En pantalla se lee como el mismo resultado repetido:
# medido sobre una entrevista real, "Martita" daba cinco tarjetas que eran dos frases.
# Ojo con lo que esto NO es: el filtro por tiempo que hubo aca antes descartaba
# menciones y bajaba el total. Esto solo junta tarjetas, y el total no se toca.
MAX_MENCIONES_POR_TARJETA = 8


def _agrupar(crudos):
    """Junta las menciones cuyos contextos se solapan. Corta en MAX_RESULTADOS grupos.

    El tope se cuenta en tarjetas y no en menciones: es lo que evita que el navegador
    tenga que pintar una lista infinita, y una tarjeta con ocho resaltados sigue
    siendo una sola fila.
    """
    grupos = []
    for mencion in crudos:
        # Dos condiciones, y las dos hacen falta. La de caracteres es la que define el
        # solape: el borde derecho de la tarjeta abierta es el fin de su ultima mencion
        # mas el contexto, y si la que sigue arranca antes de ahi las frases se pisan.
        # La de segundos es por los silencios: el texto de un video corre pegado aunque
        # el video no, asi que dos menciones separadas por dos minutos de musica quedan
        # a diez caracteres una de otra. Sin este corte la segunda perdia su timestamp
        # adentro de la primera. Es el mismo motivo por el que agrupar() corta ahi.
        if (grupos and len(grupos[-1]) < MAX_MENCIONES_POR_TARJETA
                and mencion[0] <= grupos[-1][-1][1] + CONTEXTO
                and mencion[2] - grupos[-1][0][2] <= SEGUNDOS_BLOQUE):
            grupos[-1].append(mencion)
            continue
        # El corte va despues de intentar sumar a la ultima: una mencion que pertenece
        # a la tarjeta abierta entra igual, aunque ya no se puedan abrir mas.
        if len(grupos) >= MAX_RESULTADOS:
            break
        grupos.append([mencion])
    return grupos


def _tarjeta(grupo, completo, video_id, aproximado):
    """El fragmento que rodea a un grupo de menciones, con cada una ubicada adentro."""
    arranque = max(0, grupo[0][0] - CONTEXTO)
    fin = min(len(completo), grupo[-1][1] + CONTEXTO)
    # Correrse hasta el espacio mas cercano: cortar a mitad de palabra dejaba
    # fragmentos como "…te larga que sirve para…" en vez de "…bastante larga…".
    if arranque > 0:
        espacio = completo.find(" ", arranque, grupo[0][0])
        if espacio != -1:
            arranque = espacio + 1
    if fin < len(completo):
        espacio = completo.rfind(" ", grupo[-1][1], fin)
        if espacio != -1:
            fin = espacio

    crudo = completo[arranque:fin]
    fragmento = crudo.strip()
    # Donde cae cada mencion dentro del fragmento que se manda. El navegador las usa
    # para resaltarlas sin tener que rehacer la busqueda: aca ya sabemos cual de las
    # tres estrategias matcheo y hasta donde llego, y del otro lado no.
    desplazamiento = -arranque - (len(crudo) - len(crudo.lstrip()))
    if arranque > 0:
        fragmento = "…" + fragmento
        desplazamiento += 1
    if fin < len(completo):
        fragmento = fragmento + "…"
    marcas = [[real + desplazamiento, real_fin + desplazamiento]
              for real, real_fin, _segundos in grupo]
    # El timestamp es el de la primera: es donde arranca lo que se ve en la tarjeta.
    return _resultado(grupo[0][2], fragmento, video_id, aproximado, marcas)


def _resultado(segundos, texto, video_id, aproximado=False, marcas=None):
    resultado = {
        "segundos": int(segundos),
        "timestamp": formatear(segundos),
        "texto": texto,
        "link": "https://youtu.be/%s?t=%d" % (video_id, int(segundos)),
        "aproximado": aproximado,
    }
    # Sólo cuando hay algo que resaltar: la transcripción completa no busca nada, y
    # así sus bloques conservan exactamente la forma que tenían antes.
    if marcas:
        resultado["marcas"] = marcas
        # Redundante con len(marcas), pero es el número que la tarjeta muestra y el
        # que va a la columna de la planilla al copiar: mejor que sea explícito.
        resultado["menciones"] = len(marcas)
    return resultado


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
        if self.path == "/api/progreso":
            return self._responder(200, _ver_progreso())
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
        if self.path == "/api/apagar":
            return self._apagar()
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
            return self._responder(403, {"error": "Pedido de otro origen."})
        _abrir_trabajo()
        try:
            datos = self._leer_json()
            video_id = extraer_id(datos.get("url"))
            indice, titulo, fuente, aviso = indice_de(
                video_id, bool(datos.get("forzar_whisper"))
            )
            payload = accion(datos, indice, video_id)
            payload.update({"titulo": titulo, "video_id": video_id,
                            "fuente": fuente, "aviso": aviso})
        except ErrorDeUso as err:
            return self._responder(400, {"error": str(err)})
        except Exception:
            # Nunca filtramos el stack a la UI, pero sin imprimirlo aca el 500 era
            # mudo: la interfaz manda a mirar la Terminal y no habia nada que mirar.
            traceback.print_exc()
            return self._responder(500, {"error": "Algo falló al procesar el video."})
        finally:
            # Que el porcentaje no quede clavado en la pantalla despues de terminar:
            # el navegador sigue preguntando hasta que le llega la respuesta, y sin
            # esto lo ultimo que ve es "transcribiendo 99%" para siempre.
            _cerrar_trabajo()
        # Fuera del try a proposito: si el write falla porque cerraron la pestaña, no
        # tiene sentido intentar un 500 sobre el mismo socket ya empezado.
        self._responder(200, payload)

    def _apagar(self):
        """Cerrar el buscador desde la pagina.

        Empaquetado como .app no hay ninguna ventana que cerrar: el servidor queda
        corriendo invisible y el puerto tomado, y el proximo doble clic no arranca
        nada. El boton de la interfaz es la unica forma de apagarlo que la persona ve.
        """
        if not self._mismo_origen():
            return self._responder(403, {"error": "Pedido de otro origen."})
        self._responder(200, {"ok": True})
        # En un thread aparte: shutdown() espera a que serve_forever corte, y llamarlo
        # desde el handler que ese mismo loop esta atendiendo es un abrazo mortal.
        threading.Thread(target=_apagar_servidor, daemon=True).start()

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


_SERVIDOR = None


def _apagar_servidor():
    _terminar_hijos()
    if _SERVIDOR is not None:
        _SERVIDOR.shutdown()


def main():
    # Sin esto, Python bufferea por bloques cuando la salida no es una terminal y los
    # avisos aparecen despues del progreso de whisperx, o directamente al final.
    sys.stdout.reconfigure(line_buffering=True)
    # SIGHUP ademas de SIGTERM: al cerrar la ventana la Terminal se lo manda directo a
    # este proceso y el default de Python es morirse sin correr ningun handler.
    for senal in (signal.SIGTERM, getattr(signal, "SIGHUP", None)):
        if senal is not None:
            signal.signal(senal, _terminar_hijos)
    global _SERVIDOR
    try:
        servidor = _SERVIDOR = ThreadingHTTPServer(("127.0.0.1", PUERTO), Handler)
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
