# Menú Familiar PWA

App web instalable para generar un menú semanal con desayuno, colación, almuerzo, merienda y cena, recetas y lista de compra consolidada. Telegram queda como integración opcional si se configura un token.

## Qué hace

- Guarda perfil del usuario.
- Guarda condiciones alimentarias y preferencias.
- Permite configurar perfil, reglas, stock y ofertas desde la PWA.
- Genera menú semanal priorizando ingredientes en oferta.
- Crea lista de compra semanal agregada.
- Simula compra parcial en Disco usando precios públicos del catálogo online.
- Envía el menú del día automáticamente si Telegram está habilitado.
- Permite aplicar presets familiares, por ejemplo `/preset sanda`.
- Expone frontend instalable como PWA para heladera, tablet o celular.

## Instalación

```bash
cd /Users/santiago.prario/menu-telegram-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Editá `.env`. Para usar solo PWA no hace falta `TELEGRAM_BOT_TOKEN`; si querés Telegram, pegá el token de BotFather:

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

El frontend incluye manifest y service worker, por lo que puede instalarse como app desde el navegador compatible.

Rutas de app:

```text
/        menú de hoy
/semana  semana completa
/compra  compra por rubro y productos sugeridos
/platos  platos creados por usuarios, creación y puntajes
/config  perfil, reglas, stock y ofertas
/onboarding configuración inicial con 5 preguntas
/login   ingreso con email y contraseña
/register creación de cuenta web
```

Si el usuario todavía no tiene perfil o reglas, la app lo manda a `/onboarding`. Desde `/config` se puede regenerar la semana, editar preferencias, cargar stock de alacena y sumar ofertas sin usar Telegram.

Login web:

```text
/login
/register
```

La PWA usa cuentas con email y contraseña. La contraseña se guarda hasheada con PBKDF2-SHA256 y la sesión queda en cookie firmada.

`DASHBOARD_PIN` queda como PIN de alta para crear cuentas nuevas. Una cuenta puede vincularse a un perfil familiar existente o crear un perfil nuevo, que después completa `/onboarding`.

Compra editable:

- En `/compra` podés marcar cada producto como comprado.
- Podés cargar cantidad real comprada, sobrante y nota.
- Si cargás sobrante, se guarda como stock para descontarlo de próximas compras.

Platos de usuarios:

- En `/platos` podés crear platos propios con ingredientes por porción.
- Los platos públicos los ven otros usuarios.
- Cada plato se puede puntuar de 1 a 5.
- Los platos activos entran como candidatos cuando se regenera la semana y sus ingredientes pasan a la compra.

## Deploy gratis en Render

El proyecto incluye `render.yaml`. En Render:

1. Subí este proyecto a GitHub.
2. Creá un Blueprint o Web Service desde ese repo.
3. Configurá estas variables de entorno:

```env
TELEGRAM_BOT_TOKEN=tu_token_opcional
DEFAULT_CHAT_ID=tu_chat_id
ALLOWED_CHAT_ID=tu_chat_id
ALLOWED_CHAT_IDS=tu_chat_id,otro_chat_id
DASHBOARD_PIN=un_pin
WEB_SESSION_SECRET=clave_larga_random_para_cookies
DB_PATH=/tmp/menu_bot.sqlite3
TIMEZONE=America/Argentina/Buenos_Aires
SEED_PATH=data/default_seed.json
```

El servicio usa:

```bash
uvicorn menu_bot.web:app --host 0.0.0.0 --port $PORT
```

Nota: en hosting gratis la base local puede ser efímera. El archivo `data/default_seed.json` carga tu perfil, reglas, marcas iniciales y usuarios familiares fijos al arrancar.

Para persistencia real en Render, usá plan Starter o superior con un Disk montado, por ejemplo:

```text
Mount path: /var/data
DB_PATH=/var/data/menu_bot.sqlite3
```

Con eso se conservan perfiles, reglas, stock, ofertas, semanas generadas y checks de compra aunque Render reinicie.

Para que una cuenta familiar no dependa de invitaciones después de un reinicio, agregá su ID a `ALLOWED_CHAT_IDS` y al bloque `users` del seed. Ejemplo actual:

```json
"users": [
  {
    "chat_id": 6419465333,
    "preset": "sanda"
  }
]
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Telegram opcional

Si `TELEGRAM_BOT_TOKEN` está vacío, Render levanta solo la PWA. Si lo configurás, también quedan disponibles estos comandos:

```text
/start
/perfil objetivo=bajar grasa, personas=1, calorias=2200, presupuesto=50000
/condiciones restricciones=sin lactosa, evitar=atun, preferencias=pollo huevo
/oferta pollo $4500 kg
/ofertas
/limpiar_ofertas
/presets
/preset sanda
/disco_config sc=33, zona=Santa Clara del Mar
/buscar_disco leche zero lactosa
/simular_disco
/compra_disco
/generar_semana
/menu_hoy
/menu_semana
/compra
/stock arroz=500, huevo=6
/mi_stock
/limpiar_stock
/favorito milanesas de nalga
/no_repetir pescado
/cambiar_hoy
/invitar
/mi_id
```

El bot también muestra un teclado persistente con botones para:

- Menú de hoy
- Regenerar semana
- Menú semanal
- Compra
- Ver ofertas
- Mis marcas
- Hogar
- Disco
- Stock
- Cambiar hoy
- Invitar
- Mi ID
- Presets
- Ver perfil
- Ver reglas
- Ayuda

## Presets familiares

```text
/preset sanda
```

Configura una cuenta para 2 adultos y 2 chicos, comida argentina familiar, porciones para 4 y clima de Santa Clara del Mar, Mar Chiquita.

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
