# Instalación (instrucciones para el asistente de IA)

Este archivo está escrito para vos, el agente de IA que corre en la Mac de quien recibió
esta carpeta. La persona que te lo pasó no necesariamente sabe programar: **hacé vos la
instalación entera, sin pedirle que abra la Terminal ni que copie comandos.** Al final
dejale la app andando y explicale en dos líneas cómo abrirla la próxima vez.

## Qué es esto

Un servidor local en Python que busca una palabra o frase dentro de un video de YouTube y
devuelve el minuto exacto en que se dijo. Tiene dos modos:

1. **Subtítulos** (el normal) — baja los subtítulos automáticos con `yt-dlp`. Rápido.
2. **Modo preciso con IA** — baja el audio y lo transcribe con `whisperx`. Lento, pero
   encuentra lo que YouTube escribió mal y marca el segundo exacto.

El servidor en sí (`app.py`) usa **solo la librería estándar de Python**. No instales
nada con `pip` en el Python del sistema. `whisperx` vive aparte, en un `.venv` dentro de
esta misma carpeta, y `app.py` lo invoca como un proceso externo (ver `_binario_whisperx()`
en `app.py`, que busca `./.venv/bin/whisperx` y si no está cae a `shutil.which`).

## Antes de empezar

- **La carpeta `.venv` no viene incluida y no debe copiarse de otra Mac.** Pesa ~1 GB y
  los binarios adentro tienen rutas absolutas al usuario original. Hay que crearla acá.
- Verificá la arquitectura (`uname -m`): `arm64` es Apple Silicon, `x86_64` es Intel. Los
  dos andan; todo corre en CPU, no se usa GPU.
- Espacio en disco necesario: **~3,5 GB** (≈1 GB el `.venv`, ≈1,9 GB los modelos que se
  bajan la primera vez que se usa el modo IA).

## Paso 1 — Homebrew

```bash
command -v brew || /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

El instalador de Homebrew **pide la contraseña del usuario**. No la ejecutes vos a ciegas:
avisale a la persona que va a aparecer ese pedido en la Terminal y que lo tiene que
escribir ella. En Apple Silicon, después de instalar hay que agregar `brew` al PATH:

```bash
eval "$(/opt/homebrew/bin/brew shellenv)"
```

## Paso 2 — Dependencias del sistema

```bash
brew install yt-dlp ffmpeg uv
```

- `yt-dlp` — baja subtítulos y audio. **Obligatorio para los dos modos.**
- `ffmpeg` — convierte el audio a WAV 16 kHz mono. Obligatorio **solo para el modo IA**,
  pero instalalo igual.
- `uv` — arma el entorno de Python. Alternativa: `curl -LsSf https://astral.sh/uv/install.sh | sh`.

Comprobá que `python3` exista (`command -v python3`). Si no está, macOS lo ofrece al
correr `xcode-select --install`, o se baja de [python.org](https://www.python.org/downloads/).
Sirve cualquier 3.8+; es solo para el servidor.

## Paso 3 — El entorno de whisperx

Desde **esta carpeta** (la que contiene `app.py`):

```bash
uv venv --python 3.12
uv pip install -r requirements.txt
```

Si eso falla porque alguna dependencia de whisperx sacó una versión que rompe, instalá
el entorno exacto que sí anda:

```bash
uv pip install -r requirements.lock.txt
```

Notas que importan:

- **Fijá Python 3.12.** `whisperx` todavía no soporta 3.13 y la instalación falla si `uv`
  elige la versión más nueva por su cuenta. Si `uv` no encuentra un 3.12 en la máquina, lo
  baja solo.
- La versión `3.8.6` es la verificada andando con esta app. Si falla la resolución de
  dependencias, probá `uv pip install whisperx` sin pin y avisá qué versión quedó.
- Son ~1 GB de descarga (`torch`, `ctranslate2`, `transformers`). Tarda unos minutos.
- **No hace falta ningún token de Hugging Face.** La app no usa diarización, así que
  ignorá cualquier instrucción de la documentación de whisperx sobre `--hf_token` o sobre
  aceptar los términos de `pyannote`.

El resultado esperado es que exista `.venv/bin/whisperx`.

## Paso 4 — Permisos del lanzador

```bash
chmod +x start.command
xattr -d com.apple.quarantine start.command 2>/dev/null || true
```

El `chmod` hace falta porque el permiso de ejecución se pierde al mandar la carpeta por
mail o WhatsApp. El `xattr` saca la marca de cuarentena de macOS; sin eso, el primer doble
clic lo bloquea Gatekeeper. Si aun así aparece el bloqueo, la persona tiene que hacer
**clic derecho sobre `start.command` → Abrir → Abrir**, o autorizarlo en
**Ajustes del Sistema → Privacidad y seguridad**.

## Paso 5 — Verificación

Corré estas comprobaciones y reportá cada una:

```bash
command -v yt-dlp ffmpeg && ./.venv/bin/whisperx --help >/dev/null && echo "dependencias ok"
```

Arrancá el servidor y probá que responda:

```bash
python3 app.py &
sleep 2
curl -fs http://127.0.0.1:8765/api/salud
```

Tiene que devolver `{"ok": true}`.

Los tests del parseo y la búsqueda no necesitan red ni nada instalado:

```bash
python3 -m unittest test_app
```

Prueba real del modo subtítulos (rápida, ~10 segundos) — usá un video de YouTube
cualquiera que tenga subtítulos:

```bash
curl -s -X POST http://127.0.0.1:8765/api/buscar \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://www.youtube.com/watch?v=VIDEO_ID","consulta":"una palabra que se diga"}'
```

Tiene que venir un JSON con `"fuente": "subtitulos"` y una lista de `resultados`.

**No pruebes el modo IA como parte de la instalación.** La primera corrida baja ~1,9 GB de
modelos (`large-v3-turbo` de transcripción, ~1,5 GB, y el de alineación en español, ~360 MB)
y transcribir un video lleva varios minutos. Dejá esa descarga para la primera vez que la
persona tilde la opción en la interfaz, y avisale de antemano que esa primera vez tarda.

Cuando termines, matá el servidor de prueba (`kill %1`) — el uso normal es por doble clic.

## Cómo se usa después

Doble clic en **`start.command`**. Se abre una ventana negra de Terminal (es el motor,
tiene que quedar abierta) y el buscador aparece solo en el navegador, en
`http://127.0.0.1:8765`. Para cerrarlo, se cierra la ventana negra.

El detalle de la interfaz y de los dos modos está en el `README.md` de esta carpeta.

## Si algo falla

| Síntoma | Causa y arreglo |
|---|---|
| `start.command` se abre como texto | Falta el permiso: `chmod +x start.command` |
| macOS dice que no puede verificar el archivo | Cuarentena: clic derecho → Abrir → Abrir |
| `Address already in use` al arrancar | El puerto 8765 ya está ocupado, probablemente por otra copia del servidor corriendo. Cerrala: `pkill -f "python3 app.py"` |
| La app dice "No encontré whisperx" | El Paso 3 no terminó bien. Verificá que exista `.venv/bin/whisperx` y que el `.venv` esté **dentro de esta carpeta** |
| `whisperx` instala pero explota al correr | Casi siempre es la versión de Python. Confirmá `.venv/bin/python -V` → tiene que decir 3.12.x. Si dice 3.13, borrá el `.venv` y repetí el Paso 3 con `--python 3.12` |
| El modo IA falla al bajar el audio | Falta `ffmpeg`: `brew install ffmpeg` |
| YouTube responde que se espere | Demasiados pedidos seguidos. No es un bug: esperar un minuto |

Las transcripciones y subtítulos se cachean en `~/.cache/buscar-en-video/`; los modelos de
IA en `~/.cache/huggingface/` y `~/.cache/torch/`. Se pueden borrar en cualquier momento,
al costo de volver a bajarlos.

## Versiones verificadas

macOS 15 (arm64) · Python 3.12.14 en el `.venv` · whisperx 3.8.6 · torch 2.8.0 ·
ctranslate2 4.8.1 · faster-whisper 1.2.1 · yt-dlp y ffmpeg de Homebrew.
