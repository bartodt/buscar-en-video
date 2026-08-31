# Armar el `.dmg`

Esto es para quien distribuye la app, una sola vez por versión, en una Mac de desarrollo.
Quien la va a *usar* no necesita nada de esto: recibe el `.dmg` y sigue el `README.md`.

```bash
./construir-app.sh
```

Deja `dist/Buscar en video.dmg` (~490 MB) y `dist/Buscar en video.app` (1,1 GB sin
comprimir). Tarda unos minutos: la mayor parte es bajar e instalar `torch`.

## Qué necesita la máquina de build

`uv`, `dylibbundler` y `ffmpeg` de Homebrew:

```bash
brew install uv dylibbundler ffmpeg
```

El script chequea todo eso al arrancar y muere con un mensaje claro si falta algo.

## Qué viaja adentro del bundle

Todo. La app no busca nada en la Mac de destino: ni Python, ni Homebrew, ni `/usr/local`.

```
Buscar en video.app/Contents/
  MacOS/lanzador      arranca el servidor y abre el navegador
  Resources/
    app.py            el servidor (solo stdlib)
    index.html        la interfaz
    icono.icns        generado por herramientas/icono.py
    python/           intérprete relocatable (python-build-standalone, vía uv)
    pylibs/           whisperx + torch, como directorio plano
    bin/yt-dlp        binario oficial autocontenido
    bin/ffmpeg        de Homebrew, con sus dylibs adentro de bin/lib
```

Tres decisiones que hacen que el bundle ande desde cualquier ruta, y que son lo único
que no se puede cambiar sin romperlo:

- **El intérprete es de `python-build-standalone`** (los que administra `uv`), no el de
  Homebrew. Resuelve su propio `prefix` desde `argv[0]`, así que anda desde donde sea.
  El de Homebrew tiene el prefix compilado adentro y no se puede mover.

- **`pylibs` es un directorio plano (`uv pip install --target`), no un venv.** Un venv
  guarda la ruta absoluta de su intérprete en `pyvenv.cfg` y en el shebang de cada
  script: se rompe en cuanto la carpeta cambia de lugar. Un directorio de librerías se
  resuelve por `PYTHONPATH`, que `app.py` arma relativo a sí mismo.

- **whisperx se invoca como `python -m whisperx`**, nunca por el script `bin/whisperx`.
  Ese script lleva la ruta del intérprete en el shebang: después de mover la carpeta
  *sigue existiendo* —así que se encuentra igual— pero explota con `bad interpreter`.
  Ver `_comando_whisperx()` en `app.py`.

El `ffmpeg` de Homebrew apunta a `/opt/homebrew/Cellar/...`, que en la Mac de destino no
existe. `dylibbundler` copia el árbol de dependencias adentro del bundle y reescribe cada
ruta a `@executable_path/lib`. El script **verifica** que no quede ni una referencia a
Homebrew y aborta si queda alguna.

## La verificación del paso 9

Antes de armar el `.dmg`, el script copia la `.app` a un directorio temporal y corre
desde ahí `ffmpeg`, `yt-dlp`, el intérprete y `whisperx --help`. Eso es lo que atrapa las
rutas absolutas: si algo quedó atado a la carpeta de build, falla acá y no en la máquina
de la persona.

Lo que **no** verifica es una transcripción completa: eso baja ~1,9 GB de modelos y lleva
minutos. Probalo a mano una vez por versión.

## La firma

La app va **sin firmar**, así que en la primera apertura macOS la bloquea y la persona
tiene que autorizarla en **Ajustes del Sistema → Privacidad y seguridad → Abrir de todos
modos**. Está explicado paso a paso en el `README.md`.

Se elimina por completo firmando y notarizando, lo que requiere una cuenta de Apple
Developer paga. Con eso, el `codesign` y el `notarytool` irían al final del script, entre
la verificación y el `hdiutil`.

## El `.dmg` pesa ~490 MB

Es el precio de que la persona no instale nada: el modo IA se lleva `torch` y
`ctranslate2` puestos. La `.app` desplegada son 1,1 GB, pero comprime muy bien. No entra
en un mail; va por Drive, WeTransfer o un pendrive sin problema.

Si eso molesta más que el instalar, la alternativa es sacar `pylibs` del bundle y bajarlo
la primera vez que alguien tilde el modo IA: la app quedaría en ~100 MB, porque `app.py`
usa solo la librería estándar y arranca perfecto sin whisperx (`_comando_whisperx()`
devuelve `(None, None)` y el modo normal ni se entera).

## El bundle es por arquitectura

`construir-app.sh` arma para la arquitectura de la máquina donde corre: en una Mac Apple
Silicon sale un bundle `arm64`, que **no** anda en una Intel. Para cubrir las dos hay que
correrlo en cada una. `yt-dlp` es el único universal de los tres binarios.
