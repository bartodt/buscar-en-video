#!/usr/bin/env python3
"""Tests de las partes puras: parseo, normalizacion y busqueda.

No tocan la red ni el cache. Solo unittest de la stdlib, igual que el servidor, asi
que corren con  python3 -m unittest test_app  sin instalar nada.
"""

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


class Formatear(unittest.TestCase):
    def test_horas_minutos_segundos(self):
        self.assertEqual(app.formatear(0), "0:00:00")
        self.assertEqual(app.formatear(61), "0:01:01")
        self.assertEqual(app.formatear(3725), "1:02:05")


if __name__ == "__main__":
    unittest.main()
