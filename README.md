# Editor tipográfico

Deja prolijos los borradores nuevos de Base Tucumán. No reescribe la nota y no publica.

El código lista, compara temas, aplica negrita, itálica y cita en bloque, y guarda el borrador. El modelo solo mira la foto y dice qué fragmentos marcar, el pie y la categoría. Si la foto tiene marca de agua, borra la nota y su imagen.

## Prueba local, sin CMS

```bash
python3 -m typeface check
python3 -m typeface once --fixture fixtures/article-938.json --decisions fixtures/article-938-decisions.json
```

La segunda línea no llama al modelo y no escribe en el CMS. Mientras trabaja, deja en la consola el id de cada nota. Si llama a Cursor, también aparecen las peticiones HTTP del SDK. Al final imprime el resumen.

## Corrida real

Hace falta Python 3.10 o más. `python3` del sistema es 3.9 y pip no encuentra `cursor-sdk`.

```bash
/opt/homebrew/bin/python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
export CURSOR_API_KEY=cursor_...
export CMS_TOKEN=...
# o CMS_EMAIL y CMS_PASSWORD
.venv/bin/python -m typeface once --since-id 900
```

`--dry-run` lee y arma el mensaje, sin guardar ni mover el último id.

El último id queda en `state/last-id`. La corrida siguiente toma borradores con id mayor. En el workflow hay que conservar ese archivo entre corridas. Para repetir una nota, bajá el número.

Categorías: 1 Política, 2 Economía, 3 Deportes, 4 Sociedad, 5 Mundo.

Todavía no está enganchado a `shared-github-actions`.
