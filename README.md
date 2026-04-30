# Menu Telegram Bot

Bot de Telegram para generar un menú semanal con 4 comidas, 2 colaciones, envío diario y lista de compra consolidada.

## Qué hace

- Guarda perfil del usuario.
- Guarda condiciones alimentarias y preferencias.
- Permite cargar ofertas manualmente desde Telegram.
- Genera menú semanal priorizando ingredientes en oferta.
- Crea lista de compra semanal agregada.
- Envía el menú del día automáticamente.

## Instalación

```bash
cd /Users/santiago.prario/menu-telegram-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Editá `.env` y pegá el token de BotFather:

```env
TELEGRAM_BOT_TOKEN=...
```

## Ejecutar

```bash
python -m menu_bot.bot
```

## Ejecutar frontend web

Para ver el menú en una pantalla tipo Samsung Family Hub:

```bash
uvicorn menu_bot.web:app --host 0.0.0.0 --port 8000
```

Abrí:

```text
http://localhost:8000
```

La pantalla se refresca sola cada 15 minutos.

## Deploy gratis en Render

El proyecto incluye `render.yaml`. En Render:

1. Subí este proyecto a GitHub.
2. Creá un Blueprint o Web Service desde ese repo.
3. Configurá estas variables de entorno:

```env
TELEGRAM_BOT_TOKEN=tu_token
DEFAULT_CHAT_ID=tu_chat_id
DB_PATH=/tmp/menu_bot.sqlite3
TIMEZONE=America/Argentina/Buenos_Aires
SEED_PATH=data/default_seed.json
```

El servicio usa:

```bash
uvicorn menu_bot.web:app --host 0.0.0.0 --port $PORT
```

Nota: en hosting gratis la base local puede ser efímera. El archivo `data/default_seed.json` carga tu perfil, reglas y marcas iniciales al arrancar.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Comandos de Telegram

```text
/start
/perfil objetivo=bajar grasa, personas=1, calorias=2200, presupuesto=50000
/condiciones restricciones=sin lactosa, evitar=atun, preferencias=pollo huevo
/oferta pollo $4500 kg
/ofertas
/limpiar_ofertas
/generar_semana
/menu_hoy
/menu_semana
/compra
```

El bot también muestra un teclado persistente con botones para:

- Menú de hoy
- Regenerar semana
- Menú semanal
- Compra
- Ver ofertas
- Ver perfil
- Ver reglas
- Ayuda

## Reglas cargadas para el caso actual

- Ubicación: Argentina, Buenos Aires, Mar del Plata.
- Personas: hombre de 35 y mujer de 34.
- Objetivo: bajar grasa con proteína suficiente para entrenamiento regular.
- Restricciones: intolerancia al kiwi, poca lactosa cuando sea posible y evitar cerdo.
- Plan semanal: una cena random de delivery, platos saludables y variados, verduras y frutas frecuentes.
- Mediodía: recetas de hasta 40 minutos.
- Fines de semana: platos más ricos y flexibles, incluyendo un gusto semanal.
- Comidas: 5 por día, con una sola colación de media mañana.
- Pescado: poco y nada.
- Carnes ocasionales: vacío, entraña, asado y bife de costilla.
- Ingredientes base: carnes, pollo, atún en conserva, arroz, fideos, verduras, frutas y lácteos bajos en lactosa.
- Postre ocasional: Dannette o Copa Cindor, priorizando el que esté en oferta.
- Compra semanal: incluye rotación de limpieza e higiene personal.

## Próximos pasos posibles

- Integrar OpenAI para generar recetas más variadas con validación JSON.
- Agregar scraping o carga por archivo de ofertas de supermercados específicos.
- Agregar macros por comida y ajuste de calorías.
- Sumar reemplazos: "no tengo pollo", "quiero algo rápido", "hoy como afuera".
