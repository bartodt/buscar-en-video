#!/usr/bin/env python3
"""Tests de las partes puras: parseo, normalizacion y busqueda.

No tocan la red, y lo que toca el cache lo hace contra una carpeta temporal. Solo
unittest de la stdlib, igual que el servidor, asi que corren con
python3 -m unittest test_app  sin instalar nada.
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest

import app


def vtt(*bloques):
    return "WEBVTT\nKind: captions\nLanguage: es\n\n" + "\n\n".join(bloques) + "\n"


def indice(cues):
    return app.construir_indice(cues)


class ExtraerId(unittest.TestCase):
    def test_formatos_conocidos(self):
        for url in (
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://www.youtube.com/watch?list=RD&v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ?t=42",
            "https://www.youtube.com/shorts/dQw4w9WgXcQ",
            "https://www.youtube.com/live/dQw4w9WgXcQ",
            "dQw4w9WgXcQ",
        ):
            self.assertEqual(app.extraer_id(url), "dQw4w9WgXcQ", url)

    def test_id_de_mas_de_once_no_se_recorta(self):
        # Sin la frontera matcheaba los primeros 11 y buscaba en otro video.
        with self.assertRaises(app.ErrorDeUso):
            app.extraer_id("https://youtu.be/dQw4w9WgXcQXX")

    def test_basura(self):
        for url in ("", None, "https://vimeo.com/12345", "hola"):
            with self.assertRaises(app.ErrorDeUso):
                app.extraer_id(url)

    def test_lo_que_no_sea_texto_da_error_de_uso(self):
        # Antes reventaba con AttributeError y salia un 500 "algo fallo con el video".
        for url in (123, {"v": "x"}, ["x"], True):
            with self.assertRaises(app.ErrorDeUso):
                app.extraer_id(url)


class Normalizar(unittest.TestCase):
    def test_saca_tildes_y_baja(self):
        self.assertEqual(app.normalizar("Canción DÍA"), "cancion dia")

    def test_preserva_largo(self):
        for texto in ("Canción", "ÑOÑO", "ábc", "😀 hola"):
            self.assertEqual(len(app.normalizar(texto)), len(texto), texto)

    def test_la_enie_se_convierte_en_ene_a_proposito(self):
        # Es lo que hace que buscar "senuk" encuentre "Señuk", como promete el README.
        self.assertEqual(app.normalizar("SEÑUK"), "senuk")
        self.assertEqual(app.normalizar("Pingüino"), "pinguino")


class ASegundos(unittest.TestCase):
    def test_validos(self):
        self.assertEqual(app._a_segundos("00:01:02.500"), 62)
        self.assertEqual(app._a_segundos("01:00.000"), 60)

    def test_invalidos_devuelven_none(self):
        for marca in ("la flecha", "1:2:3:4", "", "aa:bb:cc.ddd"):
            self.assertIsNone(app._a_segundos(marca), marca)


class ParsearVtt(unittest.TestCase):
    def test_flecha_en_el_texto_no_rompe_el_video_entero(self):
        contenido = vtt(
            "00:00:01.000 --> 00:00:02.000\nla flecha --> apunta",
            "00:00:05.000 --> 00:00:06.000\ndespués",
        )
        cues = app.parsear_vtt(contenido)          # antes: ValueError y 500
        self.assertIn("después", [t for _, t in cues])

    def test_identificadores_de_cue_no_entran_al_indice(self):
        contenido = vtt(
            "1\n00:00:01.000 --> 00:00:02.000\nuno",
            "2\n00:00:03.000 --> 00:00:04.000\ndos",
        )
        self.assertEqual(app.parsear_vtt(contenido), [(1, "uno"), (3, "dos")])

    def test_entidades_html(self):
        contenido = vtt("00:00:01.000 --> 00:00:02.000\nAT&amp;T y &lt;b&gt;chau&lt;/b&gt;")
        texto = " ".join(t for _, t in app.parsear_vtt(contenido))
        self.assertIn("AT&T", texto)
        self.assertIn("<b>chau</b>", texto)

    def test_prefijo_lejano_no_se_fusiona(self):
        # El bug: la mencion tardia desaparecia y "claro" se reportaba en el segundo 10.
        contenido = vtt(
            "00:00:10.000 --> 00:00:12.000\nsí",
            "00:05:00.000 --> 00:05:03.000\nsí, claro que sí",
        )
        cues = app.parsear_vtt(contenido)
        self.assertEqual([s for s, _ in cues][0], 10)
        resultados, _ = app.buscar(indice(cues), "claro", "x")
        self.assertEqual([r["timestamp"] for r in resultados], ["0:05:00"])

    def test_rollup_lento_no_duplica_el_texto(self):
        # Con un umbral fijo de segundos, una linea que tardaba mas que el en crecer
        # no se fusionaba y el indice quedaba con "buenas buenas tardes a todos".
        contenido = vtt(
            "00:00:10.000 --> 00:00:20.000\nbuenas",
            "00:00:20.000 --> 00:00:30.000\nbuenas tardes a todos",
        )
        self.assertEqual(app.parsear_vtt(contenido), [(10, "buenas tardes a todos")])

    def test_sin_marca_de_fin_no_se_fusiona(self):
        # Sin fin de cue no hay como saber si el rollup es contiguo: se prefiere dejar
        # las dos entradas antes que comerse una mencion legitima de mas tarde.
        contenido = vtt(
            "00:00:10.000 --> mal\nbuenas",
            "00:00:20.000 --> 00:00:30.000\nbuenas tardes",
        )
        self.assertEqual([s for s, _ in app.parsear_vtt(contenido)], [10, 20])

    def test_autosubs_reales_de_youtube(self):
        # El formato tal cual lo deja yt-dlp: rollup de dos renglones, cues de 10 ms,
        # renglones que son un solo espacio y los ajustes de posicion en la flecha.
        contenido = (
            "WEBVTT\nKind: captions\nLanguage: es\n\n"
            "00:00:00.030 --> 00:00:02.669 align:start position:0%\n"
            " \nhola<00:00:00.599><c> a</c><00:00:00.960><c> todos</c>\n\n"
            "00:00:02.669 --> 00:00:02.679 align:start position:0%\n"
            "hola a todos\n \n\n"
            "00:00:02.679 --> 00:00:05.310 align:start position:0%\n"
            "hola a todos\n"
            "bienvenidos<00:00:03.200><c> al</c><00:00:03.760><c> canal</c>\n"
        )
        self.assertEqual(app.parsear_vtt(contenido), [
            (0, "hola"), (0, "a"), (0, "todos"),
            (2, "bienvenidos"), (3, "al"), (3, "canal"),
        ])

    def test_prefijo_cercano_si_se_fusiona(self):
        contenido = vtt(
            "00:00:10.000 --> 00:00:12.000\nhola qué",
            "00:00:12.000 --> 00:00:14.000\nhola qué tal",
        )
        self.assertEqual(app.parsear_vtt(contenido), [(10, "hola qué tal")])

    def test_repeticion_exacta_se_descarta(self):
        contenido = vtt(
            "00:00:10.000 --> 00:00:12.000\nhola",
            "00:00:12.000 --> 00:00:14.000\nhola",
        )
        self.assertEqual(app.parsear_vtt(contenido), [(10, "hola")])

    def test_timings_por_palabra_inline(self):
        # Es lo que da precision sin transcribir: cada palabra con su propio segundo.
        contenido = vtt(
            "00:00:05.000 --> 00:00:09.000\n"
            "La<00:00:06.040><c> noche</c><00:00:07.500><c> larga</c>"
        )
        self.assertEqual(app.parsear_vtt(contenido),
                         [(5, "La"), (6, "noche"), (7, "larga")])

    def test_linea_sin_tags_sigue_dando_una_sola_pieza(self):
        contenido = vtt("00:00:05.000 --> 00:00:09.000\nLa noche larga")
        self.assertEqual(app.parsear_vtt(contenido), [(5, "La noche larga")])

    def test_el_rollup_conserva_el_timing_por_palabra(self):
        # El cue nuevo reescribe el texto viejo sin tags y le agrega una palabra. Antes
        # la fusion se quedaba con esa version sin tags y las tres primeras palabras
        # colapsaban en el segundo 0, justo lo que este modo viene a evitar.
        contenido = vtt(
            "00:00:00.030 --> 00:00:03.000\n"
            "hola<00:00:01.500><c> a</c><00:00:02.400><c> todos</c>",
            "00:00:03.000 --> 00:00:06.000\n"
            "hola a todos<00:00:04.500><c> bienvenidos</c>",
        )
        self.assertEqual(app.parsear_vtt(contenido), [
            (0, "hola"), (1, "a"), (2, "todos"), (4, "bienvenidos"),
        ])

    def test_note_hablado_adentro_de_un_cue_entra_al_indice(self):
        # El filtro de encabezados aplicaba a todo el archivo y se comia la linea.
        contenido = vtt("00:00:01.000 --> 00:00:02.000\nNOTE que esto es importante")
        self.assertEqual(app.parsear_vtt(contenido),
                         [(1, "NOTE que esto es importante")])

    def test_note_estructural_sigue_afuera(self):
        # Como bloque propio, separado por lineas en blanco, si es del formato.
        contenido = vtt(
            "00:00:01.000 --> 00:00:02.000\nhola",
            "NOTE esto es un comentario del archivo",
            "00:00:05.000 --> 00:00:06.000\nchau",
        )
        self.assertEqual(app.parsear_vtt(contenido), [(1, "hola"), (5, "chau")])

    def test_cues_pegados_no_pierden_su_ultima_linea(self):
        # Sin linea en blanco de por medio, "primera" parecia un identificador de cue.
        contenido = ("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nprimera\n"
                     "00:00:05.000 --> 00:00:06.000\nsegunda\n")
        self.assertEqual(app.parsear_vtt(contenido), [(1, "primera"), (5, "segunda")])

    def test_identificadores_de_cue_siguen_afuera(self):
        contenido = vtt("7\n00:00:01.000 --> 00:00:02.000\nuno")
        self.assertEqual(app.parsear_vtt(contenido), [(1, "uno")])


class PistaDeSubtitulos(unittest.TestCase):
    def test_prefiere_la_transcripcion_real(self):
        archivos = ["vid.es.vtt", "vid.es-orig.vtt"]
        self.assertEqual(app._elegir_sub(archivos, "vid"), ("vid.es-orig.vtt", "es-orig"))

    def test_una_variante_suelta_se_marca_como_traduccion(self):
        # "es-419" en un video hablado en ingles es una traduccion automatica: los
        # tiempos estan bien pero las palabras no son las que se dijeron.
        archivo, idioma = app._elegir_sub(["vid.es-419.vtt"], "vid")
        self.assertEqual((archivo, idioma), ("vid.es-419.vtt", "es-419"))
        self.assertIn("traducidos", app._aviso_de(idioma))

    def test_la_pista_buena_no_avisa_nada(self):
        self.assertIsNone(app._aviso_de("es-orig"))
        self.assertIsNone(app._aviso_de("es"))

    def test_el_cache_vencido_avisa(self):
        self.assertIn("no pude refrescarlos", app._aviso_de("es", vencido=True))


class Buscar(unittest.TestCase):
    def test_consulta_vacia(self):
        with self.assertRaises(app.ErrorDeUso):
            app.buscar(indice([(0, "hola")]), "   ", "x")

    def test_exacta_con_tildes_y_mayusculas(self):
        cues = [(30, "Que la Canción empiece")]
        resultados, total = app.buscar(indice(cues), "cancion", "x")
        self.assertEqual(total, 1)
        self.assertEqual(resultados[0]["timestamp"], "0:00:30")
        self.assertEqual(resultados[0]["link"], "https://youtu.be/x?t=30")
        self.assertFalse(resultados[0]["aproximado"])

    def test_aproximada_pegando_palabras(self):
        cues = [(10, "son unas Pop stars")]
        resultados, _ = app.buscar(indice(cues), "popstars", "x")
        self.assertTrue(resultados and resultados[0]["aproximado"])

    def test_aproximada_recortando_el_final(self):
        cues = [(10, "es una popstar")]
        resultados, _ = app.buscar(indice(cues), "popstars", "x")
        self.assertTrue(resultados and resultados[0]["aproximado"])

    def test_tope_de_resultados(self):
        cues = [(i, "hola") for i in range(0, 3000, 2)]
        resultados, total = app.buscar(indice(cues), "hola", "x")
        self.assertEqual(len(resultados), app.MAX_RESULTADOS)
        self.assertEqual(total, 1500)

    def test_dos_frases_distintas_cercanas_no_colapsan(self):
        # Antes _barrer deduplicaba por tiempo y se comia la segunda mencion. De las
        # repeticiones de verdad se encarga parsear_vtt, no la busqueda.
        cues = [(10, "el perro corre"), (14, "un perro duerme")]
        resultados, _ = app.buscar(indice(cues), "perro", "x")
        self.assertEqual([r["timestamp"] for r in resultados],
                         ["0:00:10", "0:00:14"])

    def test_sin_resultados(self):
        resultados, total = app.buscar(indice([(0, "hola")]), "murcielago", "x")
        self.assertEqual((resultados, total), ([], 0))

    def test_consulta_que_se_solapa_consigo_misma(self):
        # Avanzando de a un caracter, "jaja" entraba tres veces en "jajajaja" y
        # salian tres resultados identicos, con el mismo segundo y el mismo texto.
        resultados, total = app.buscar(indice([(10, "jajajaja")]), "jaja", "x")
        self.assertEqual((len(resultados), total), (2, 2))

    def test_el_contexto_no_corta_palabras_al_medio(self):
        # Palabras de largo fijo 7 para que los 60 caracteres de CONTEXTO caigan a
        # mitad de palabra en los dos extremos y el recorte tenga algo que arreglar.
        relleno = "abcdefg " * 20
        cues = [(5, relleno + "objetivo " + relleno)]
        completo = indice(cues)[0]
        resultados, _ = app.buscar(indice(cues), "objetivo", "x")
        fragmento = resultados[0]["texto"]
        self.assertTrue(fragmento.startswith("…") and fragmento.endswith("…"), fragmento)
        # Antes los extremos caian a mitad de palabra: "…te larga que sirve…".
        palabras = fragmento.strip("…").split()
        for extremo in (palabras[0], palabras[-1]):
            self.assertIn(extremo, completo.split(), fragmento)

    def test_el_fragmento_siempre_contiene_lo_que_matcheo(self):
        relleno = "palabra de relleno " * 8
        cues = [(10, relleno + "son unas Pop stars y siguen " + relleno)]
        for consulta in ("pop stars", "popstars"):
            resultados, _ = app.buscar(indice(cues), consulta, "x")
            self.assertIn("Pop stars", resultados[0]["texto"], consulta)

    def test_consulta_que_no_es_texto(self):
        for consulta in (123, {"q": "x"}, ["x"], None):
            with self.assertRaises(app.ErrorDeUso):
                app.buscar(indice([(0, "hola")]), consulta, "x")


class Transcripcion(unittest.TestCase):
    def test_agrupa_sin_partir_palabras(self):
        cues = [(i, "palabra%02d" % i) for i in range(60)]
        completo, _norm, offsets = indice(cues)
        bloques = app.agrupar(completo, offsets)
        self.assertGreater(len(bloques), 1)
        for _segundos, texto in bloques:
            self.assertLessEqual(len(texto), app.LARGO_BLOQUE)
            self.assertNotIn("  ", texto)
        # Junto vuelve a dar el texto original: no se pierde ni se duplica nada.
        self.assertEqual(" ".join(t for _, t in bloques), completo.strip())

    def test_el_timestamp_es_el_de_la_primera_palabra(self):
        cues = [(10, "hola"), (11, "que"), (12, "tal")]
        completo, _norm, offsets = indice(cues)
        self.assertEqual(app.agrupar(completo, offsets), [(10, "hola que tal")])

    def test_corta_en_los_saltos_de_tiempo(self):
        # Dos frases cortas separadas por un silencio largo no pueden compartir bloque:
        # el timestamp del segundo 0 no sirve para algo que se dice en el minuto 5.
        cues = [(0, "antes"), (300, "después")]
        completo, _norm, offsets = indice(cues)
        self.assertEqual(app.agrupar(completo, offsets),
                         [(0, "antes"), (300, "después")])

    def test_forma_igual_a_la_de_una_busqueda(self):
        cues = [(30, "hola que tal")]
        bloques = app.transcripcion(indice(cues), "abc")
        self.assertEqual(bloques, [{
            "segundos": 30,
            "timestamp": "0:00:30",
            "texto": "hola que tal",
            "link": "https://youtu.be/abc?t=30",
            "aproximado": False,
        }])


class CacheWhisper(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        previo, app.CACHE = app.CACHE, tmp
        self.addCleanup(setattr, app, "CACHE", previo)
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)

    def guardar(self, datos):
        app._guardar_cache("vid.whisperx.json", json.dumps(datos))

    def test_se_rearma_desde_la_transcripcion_cruda(self):
        # Es la razon de guardar el crudo: cambiar como se arman los cues cuesta
        # milisegundos en vez de horas de re-transcribir el audio.
        self.guardar({
            "version": app.VERSION_CACHE_WHISPER,
            "modelo": app.MODELO_WHISPER, "idioma": app.IDIOMA, "titulo": "Un video",
            "transcripcion": {"segments": [{
                "start": 5.0, "text": "hola mundo",
                "words": [{"word": "hola", "start": 5.0},
                          {"word": "mundo", "start": 6.2}],
            }]},
        })
        self.assertEqual(app._leer_cache_whisper("vid"),
                         ([(5.0, "hola"), (6.2, "mundo")], "Un video"))

    def test_otro_modelo_o_idioma_se_descarta(self):
        for cambio in ({"modelo": "small"}, {"idioma": "en"}, {"version": 99}):
            datos = {"version": app.VERSION_CACHE_WHISPER, "modelo": app.MODELO_WHISPER,
                     "idioma": app.IDIOMA, "transcripcion": {"segments": [
                         {"start": 0.0, "text": "hola", "words": []}]}}
            datos.update(cambio)
            self.guardar(datos)
            self.assertIsNone(app._leer_cache_whisper("vid"), cambio)

    def test_el_formato_viejo_se_rehace(self):
        # v2 guardaba solo los cues ya armados, sin el crudo del modelo. Mantener la
        # compat era codigo para un caso que ocurre una vez y nunca mas.
        self.guardar({"version": 2, "modelo": app.MODELO_WHISPER, "idioma": app.IDIOMA,
                      "titulo": "Un video", "palabras": [[5.0, "hola"], [6.2, "mundo"]]})
        self.assertIsNone(app._leer_cache_whisper("vid"))

    def test_json_roto_no_revienta(self):
        app._guardar_cache("vid.whisperx.json", "{esto no es json")
        self.assertIsNone(app._leer_cache_whisper("vid"))


class CacheSubtitulos(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        previo, app.CACHE = app.CACHE, tmp
        self.addCleanup(setattr, app, "CACHE", previo)
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)

    def test_devuelve_titulo_e_idioma(self):
        app._guardar_cache("vid.vtt", "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhola\n")
        app._guardar_cache("vid.meta.json",
                           json.dumps({"titulo": "Un video", "idioma": "es-orig"}))
        contenido, titulo, idioma = app._leer_cache("vid")
        self.assertIn("hola", contenido)
        self.assertEqual((titulo, idioma), ("Un video", "es-orig"))

    def test_sin_metadata_se_rebaja(self):
        # No saber de que pista salio el vtt es no saber si es lo que se dijo o una
        # traduccion: se prefiere rebajarlo antes que mostrarlo sin la advertencia.
        app._guardar_cache("vid.vtt", "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhola\n")
        self.assertIsNone(app._leer_cache("vid"))

    def test_vtt_vacio_no_cuenta(self):
        app._guardar_cache("vid.vtt", "   \n")
        app._guardar_cache("vid.meta.json", json.dumps({"titulo": "x", "idioma": "es"}))
        self.assertIsNone(app._leer_cache("vid"))


class CarpetaTemporal(unittest.TestCase):
    def test_se_borra_sola_al_salir(self):
        with app._carpeta_temporal() as tmp:
            open(os.path.join(tmp, "audio.wav"), "w").close()
        self.assertFalse(os.path.exists(tmp))
        self.assertNotIn(tmp, app._TEMPORALES)

    def test_la_borra_el_cierre_del_servidor(self):
        # Los threads del servidor son daemon: al cerrar la ventana mueren sin correr
        # su finally, y el wav de la transcripcion quedaba tirado en /var/folders.
        with app._carpeta_temporal() as tmp:
            open(os.path.join(tmp, "audio.wav"), "w").close()
            self.assertIn(tmp, app._TEMPORALES)
            app._terminar_hijos()          # sin argumentos no llama a sys.exit
            self.assertFalse(os.path.exists(tmp))
        self.assertNotIn(tmp, app._TEMPORALES)


class ProcesosHijos(unittest.TestCase):
    def test_el_timeout_no_se_cuelga_esperando_a_un_nieto(self):
        # yt-dlp lanza ffmpeg y le pasa sus pipes. Matando solo al padre, ffmpeg
        # mantenia abierto el stderr heredado y el communicate() de despues esperaba
        # un EOF que no llegaba nunca: el thread del pedido quedaba colgado.
        arranque = time.monotonic()
        with self.assertRaises(app.ErrorDeUso):
            app._correr(["/bin/sh", "-c", "sleep 30 & sleep 30"], 1, "tardo demasiado")
        self.assertLess(time.monotonic() - arranque, 10)

    def test_al_salir_se_lleva_al_nieto(self):
        proceso = subprocess.Popen(
            ["/bin/sh", "-c", "sleep 30 & echo $!; sleep 30"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            start_new_session=True,
        )
        self.addCleanup(app._matar, proceso)
        nieto = int(proceso.stdout.readline())
        app._matar(proceso)
        proceso.communicate(timeout=5)
        # Si el nieto sobrevivio, sigue comiendose los cores sin ventana que lo delate.
        for _ in range(50):
            if subprocess.run(["kill", "-0", str(nieto)],
                              capture_output=True).returncode != 0:
                return
            time.sleep(0.1)
        self.fail("el nieto %d quedo vivo" % nieto)


class Formatear(unittest.TestCase):
    def test_horas_minutos_segundos(self):
        self.assertEqual(app.formatear(0), "0:00:00")
        self.assertEqual(app.formatear(61), "0:01:01")
        self.assertEqual(app.formatear(3725), "1:02:05")


if __name__ == "__main__":
    unittest.main()
