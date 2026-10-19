# Laboratorio 7 - Pruebas de integración de APIs (Postman + Pytest)

Pruebas de integración del flujo de compra **catálogo -> carrito -> total -> checkout** sobre la API pública [FakeStore API](https://fakestoreapi.com). Incluye una colección de Postman con pruebas automatizadas y un proyecto Pytest que integra la API con una base SQLite en memoria (persistencia falsa).

## Integrantes

| Nombre | Carné |
|---|---|
| Ben Farz | 2023121041 |
| Josué Calderón | 2023380883 |

Curso: Aseguramiento de la Calidad del Software

## Estructura

```
qa_api_lab/
  cart_service.py            # cliente de la API + reglas de negocio + persistencia SQLite
  tests/
    conftest.py              # fixtures: BD en memoria por prueba, catálogo, token
    test_api_integration.py  # 55 pruebas (TC-01 a TC-23)
  postman/
    Integracion_API_Carrito.postman_collection.json
    QA_API_LAB.postman_environment.json
  scripts/
    compute_metrics.py       # calcula las métricas a partir de los reportes
  reports/                   # evidencias generadas (Pytest, Newman, métricas)
  docs/
    Reporte_Laboratorio_7.docx
  requirements.txt
  pytest.ini
```

## Requisitos

- Python 3.10 o superior
- Postman (app de escritorio o web)
- Node.js, solo si se quiere correr la colección con Newman desde consola
- Conexión a internet: las pruebas consumen `https://fakestoreapi.com`

## Instalación

```bash
cd qa_api_lab
python -m venv .venv
.venv\Scripts\activate        # Windows (en Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
```

## Ejecutar las pruebas con Pytest

```bash
python -m pytest -v -rxX --junitxml=reports/pytest_junit.xml
```

- Cada prueba crea y destruye su propia base `sqlite3.connect(":memory:")` (fixture `db_connection`), así que no hay que configurar nada.
- Resultado esperado: **42 passed, 13 xfailed**.
- Cada `xfail` es un defecto real de la API documentado con su ID (`DEF-01` a `DEF-10`). Se marcan con `xfail(strict=True)`: si la API corrige el defecto, la prueba pasa a `XPASS` y falla para avisar.

Para guardar la evidencia en texto:

```bash
python -m pytest -v -rxX --junitxml=reports/pytest_junit.xml > reports/pytest_output.txt
```

## Ejecutar la colección en Postman

1. En Postman ir a **Import** y seleccionar los dos archivos de la carpeta `postman/`.
2. Arriba a la derecha, seleccionar el environment **QA_API_LAB**.
3. Abrir la colección **Integración API - Carrito**, entrar en **Run** (Collection Runner), poner **Iterations: 3** y ejecutar.
4. Las carpetas corren en orden: Catálogo, Carrito, Total, Checkout y Errores.

En cada iteración se usan productos distintos (`pm.info.iteration`). Las pruebas que fallan en la carpeta **Errores** y en `TC-12` / `TC-19` son defectos de la API. El nombre de cada una de esas pruebas indica el ID del defecto.

### Ejecutar con Newman (opcional)

```bash
npx newman run postman/Integracion_API_Carrito.postman_collection.json -e postman/QA_API_LAB.postman_environment.json -n 3 --reporters cli,json --reporter-json-export reports/newman_report.json
```

Newman termina con código 1 porque hay aserciones que fallan; esas fallas son los defectos encontrados.

### Mock del proveedor caído (opcional, TC-22)

El request `TC-22 Proveedor externo caído (mock)` trae guardado un ejemplo de respuesta 503. Si `mock_url` está vacío, el request se omite. Para activarlo:

1. En la colección, ir a **... > Mock collection** y crear el mock server.
2. Copiar la URL del mock (`https://<id>.mock.pstmn.io`) en la variable `mock_url` del environment.
3. Ejecutar el request: debe responder 503 con `{"error": ...}` y el header `Retry-After`.

## Calcular las métricas

Después de correr Pytest y Newman:

```bash
python scripts/compute_metrics.py
```

Imprime el resumen y lo guarda en `reports/metrics.json`. Calcula:
- porcentaje de aprobación
- tiempo promedio por endpoint crítico
- cobertura de endpoints
- aserciones por request
- tasa de error
- defectos por severidad

## Credenciales

- El environment usa la cuenta de **demostración pública** de FakeStore (`mor_2314`), que aparece en la documentación oficial de la API. No es una credencial real.
- La variable `token` se exporta vacía y se llena en tiempo de ejecución con `TC-05 Login`.
- Antes de exportar el environment desde Postman, hay que vaciar `token` para no publicar un token.

## Limitaciones de la API elegida

- FakeStore no guarda los carritos creados: `POST /carts` siempre devuelve `id: 11` y `GET /carts/11` devuelve `null`.
- No calcula totales: el total se calcula en Postman y en `cart_service.get_cart_total`.
- No expone stock: se simula con `rating.count`.
- No exige token en ningún endpoint: la autenticación del checkout se simula en `cart_service.checkout`.
