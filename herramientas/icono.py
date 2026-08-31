#!/usr/bin/env python3
"""Genera el .icns de la app: una lupa sobre un botón de play.

Sin dependencias a propósito —escribe el PNG a mano con zlib— para que armar la app no
necesite instalar Pillow ni nada gráfico. Los colores son los de la interfaz
(index.html): fondo oscuro y el acento rojo.

Uso:  python3 herramientas/icono.py <salida.icns>
"""
import math
import os
import struct
import subprocess
import sys
import tempfile
import zlib

FONDO = (0x17, 0x17, 0x1A)
ACENTO = (0xC8, 0x10, 0x2E)
CLARO = (0xEC, 0xEC, 0xEE)

# Se dibuja a 4x y se promedia: es todo el antialiasing que estas formas necesitan.
MUESTREO = 4


def _png(ancho, alto, pixeles):
    """RGBA sin filtros ni entrelazado, que es lo mínimo que acepta sips."""
    filas = b"".join(
        b"\x00" + bytes(pixeles[y * ancho * 4:(y + 1) * ancho * 4]) for y in range(alto)
    )

    def trozo(tipo, datos):
        return (struct.pack(">I", len(datos)) + tipo + datos
                + struct.pack(">I", zlib.crc32(tipo + datos) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + trozo(b"IHDR", struct.pack(">IIBBBBB", ancho, alto, 8, 6, 0, 0, 0))
            + trozo(b"IDAT", zlib.compress(filas, 9))
            + trozo(b"IEND", b""))


def _dibujar(lado):
    """Devuelve la cobertura de cada forma en una grilla lado x lado, ya promediada."""
    s = lado * MUESTREO
    # (radio de la esquina, centro y radio de la lupa, grosor del aro, mango)
    r_esq = 0.225 * s
    cx, cy, r_lupa = 0.42 * s, 0.42 * s, 0.24 * s
    grosor = 0.055 * s
    # El mango sale del aro a 45° hacia abajo a la derecha.
    mx0, my0 = cx + r_lupa * 0.72, cy + r_lupa * 0.72
    mx1, my1 = 0.80 * s, 0.80 * s
    # Triángulo de play, centrado en la lupa.
    tri = [(cx - 0.09 * s, cy - 0.13 * s), (cx - 0.09 * s, cy + 0.13 * s),
           (cx + 0.13 * s, cy)]

    def en_triangulo(x, y):
        def lado_de(a, b):
            return (b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0])
        signos = [lado_de(tri[i], tri[(i + 1) % 3]) for i in range(3)]
        return all(v >= 0 for v in signos) or all(v <= 0 for v in signos)

    def en_mango(x, y):
        dx, dy = mx1 - mx0, my1 - my0
        largo2 = dx * dx + dy * dy
        t = max(0.0, min(1.0, ((x - mx0) * dx + (y - my0) * dy) / largo2))
        px, py = mx0 + t * dx, my0 + t * dy
        return math.hypot(x - px, y - py) <= grosor * 0.62

    def en_fondo(x, y):
        # Rectángulo redondeado: sólo las cuatro esquinas necesitan la distancia.
        ix = min(max(x, r_esq), s - r_esq)
        iy = min(max(y, r_esq), s - r_esq)
        if ix == x or iy == y:
            return True
        return math.hypot(x - ix, y - iy) <= r_esq

    pix = bytearray(lado * lado * 4)
    for py_ in range(lado):
        for px_ in range(lado):
            acum = [0.0, 0.0, 0.0, 0.0]
            for sy in range(MUESTREO):
                for sx in range(MUESTREO):
                    x = px_ * MUESTREO + sx + 0.5
                    y = py_ * MUESTREO + sy + 0.5
                    if not en_fondo(x, y):
                        continue
                    d = math.hypot(x - cx, y - cy)
                    if abs(d - r_lupa) <= grosor / 2 or en_mango(x, y):
                        color = ACENTO
                    elif en_triangulo(x, y):
                        color = CLARO
                    else:
                        color = FONDO
                    acum[0] += color[0]; acum[1] += color[1]
                    acum[2] += color[2]; acum[3] += 255.0
            n = MUESTREO * MUESTREO
            i = (py_ * lado + px_) * 4
            if acum[3] == 0:
                continue
            # El color se promedia sobre los sub-píxeles cubiertos, el alfa sobre todos:
            # así el borde redondeado queda suave y no gris.
            cubiertos = acum[3] / 255.0
            pix[i] = int(acum[0] / cubiertos)
            pix[i + 1] = int(acum[1] / cubiertos)
            pix[i + 2] = int(acum[2] / cubiertos)
            pix[i + 3] = int(acum[3] / n)
    return bytes(pix)


def main():
    if len(sys.argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    salida = os.path.abspath(sys.argv[1])
    with tempfile.TemporaryDirectory() as tmp:
        conjunto = os.path.join(tmp, "icono.iconset")
        os.makedirs(conjunto)
        # Los tamaños que pide iconutil. Cada uno se dibuja de nuevo en vez de escalar
        # uno grande: a 16 px un resize deja la lupa como una manchita.
        for lado in (16, 32, 64, 128, 256, 512, 1024):
            datos = _png(lado, lado, _dibujar(lado))
            if lado <= 512:
                with open(os.path.join(conjunto, "icon_%dx%d.png" % (lado, lado)), "wb") as fh:
                    fh.write(datos)
            if lado >= 32:
                mitad = lado // 2
                with open(os.path.join(conjunto, "icon_%dx%d@2x.png" % (mitad, mitad)), "wb") as fh:
                    fh.write(datos)
        subprocess.run(["iconutil", "-c", "icns", conjunto, "-o", salida], check=True)
    print("ícono:", salida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
