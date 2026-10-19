# =============================================
# Imports
# ---------------------------------------------
import pytest
import requests

import cart_service
from cart_service import (
    AuthenticationError,
    CartStorageError,
    CheckoutError,
    InsufficientStockError,
    InvalidQuantityError,
    ProductNotFoundError,
    ProviderUnavailableError,
)

# =============================================
# Constantes
# ---------------------------------------------
BASE_URL = cart_service.BASE_URL
TIMEOUT_SECONDS = 10
MAX_RESPONSE_MS = 1000
NONEXISTENT_ID = 9999
SEED_CART_ID = 1
# Carrito 1 de FakeStore: 4 x 109.95 + 1 x 22.3 + 6 x 55.99
SEED_CART_EXPECTED_TOTAL = 798.04
VALID_CATEGORIES = ("electronics", "jewelery", "men's clothing", "women's clothing")
JSON_HEADERS = {"Content-Type": "application/json"}
VALID_CART_BODY = {"userId": 1, "products": [{"productId": 1, "quantity": 1}]}
CRITICAL_REQUESTS = (
    ("GET", "/products", None),
    ("GET", "/products/1", None),
    ("GET", "/products/categories", None),
    ("GET", "/carts/1", None),
    ("POST", "/carts", VALID_CART_BODY),
)


# =============================================
# Helpers
# ---------------------------------------------
# Busca un producto del catálogo por id
def find_product(catalog, product_id):
    for product in catalog:
        if product["id"] == product_id:
            return product
    raise LookupError(f"Product {product_id} not found in catalog")


# Construye una respuesta HTTP falsa para simular al proveedor
def build_fake_response(status_code, body):
    response = requests.Response()
    response.status_code = status_code
    response._content = body.encode("utf-8")
    return response


# Reemplaza requests.request por una función falsa durante la prueba
def patch_provider(monkeypatch, fake_request):
    monkeypatch.setattr(cart_service.requests, "request", fake_request)


# =============================================
# Catálogo
# ---------------------------------------------
# TC-01: el catálogo responde 200 con una lista no vacía y campos básicos
def test_tc01_get_products_returns_catalog():
    response = requests.get(f"{BASE_URL}/products", timeout=TIMEOUT_SECONDS)
    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/json")
    products = response.json()
    assert isinstance(products, list)
    assert len(products) > 0
    product = products[0]
    assert "id" in product
    assert "title" in product
    assert "price" in product
    assert isinstance(product["price"], (int, float))


# TC-02: el detalle de un producto coincide con lo que muestra el catálogo
def test_tc02_product_detail_matches_catalog(catalog):
    expected = catalog[0]
    response = requests.get(
        f"{BASE_URL}/products/{expected['id']}", timeout=TIMEOUT_SECONDS
    )
    assert response.status_code == 200
    product = response.json()
    assert product["id"] == expected["id"]
    assert product["title"] == expected["title"]
    assert product["price"] == expected["price"]


# TC-03: contrato estricto con tipos exactos de id, title, price, category e image
def test_tc03_strict_product_contract(catalog):
    assert len(catalog) > 0
    for product in catalog:
        label = f"product {product.get('id')}"
        assert type(product["id"]) is int, f"{label}: id is not int"
        assert type(product["title"]) is str, f"{label}: title is not str"
        assert len(product["title"]) > 0, f"{label}: title is empty"
        assert type(product["price"]) in (int, float), f"{label}: price is not numeric"
        assert product["price"] > 0, f"{label}: price is not positive"
        assert type(product["category"]) is str, f"{label}: category is not str"
        assert product["category"] in VALID_CATEGORIES, f"{label}: unknown category"
        assert type(product["image"]) is str, f"{label}: image is not str"
        assert product["image"].startswith("https://"), f"{label}: image is not https"


# TC-04: las categorías son una lista de textos y cubren a todos los productos
def test_tc04_categories_cover_catalog(catalog):
    response = requests.get(f"{BASE_URL}/products/categories", timeout=TIMEOUT_SECONDS)
    assert response.status_code == 200
    categories = response.json()
    assert isinstance(categories, list)
    assert sorted(categories) == sorted(VALID_CATEGORIES)
    for product in catalog:
        assert product["category"] in categories


# =============================================
# Autenticación
# ---------------------------------------------
# TC-05: el login con credenciales demo devuelve un token con formato JWT
def test_tc05_login_returns_jwt_token(auth_token):
    assert isinstance(auth_token, str)
    parts = auth_token.split(".")
    assert len(parts) == 3
    for part in parts:
        assert len(part) > 0


# TC-18: credenciales incorrectas producen un error de autenticación claro
def test_tc18_login_with_invalid_credentials_fails():
    with pytest.raises(AuthenticationError, match="401"):
        cart_service.login("unknown_user", "wrong_password")


# TC-18: login sin credenciales responde 400 con un mensaje explicativo
def test_tc18_login_without_credentials_returns_clear_error():
    response = requests.post(f"{BASE_URL}/auth/login", json={}, timeout=TIMEOUT_SECONDS)
    assert response.status_code == 400
    assert "username and password" in response.text


# =============================================
# Carrito
# ---------------------------------------------
# TC-06: crear un carrito remoto devuelve id, usuario, productos y cantidades
def test_tc06_create_remote_cart_contract(catalog, auth_token):
    items = [
        {"product_id": catalog[0]["id"], "quantity": 2},
        {"product_id": catalog[1]["id"], "quantity": 1},
    ]
    response = cart_service.create_remote_cart(1, items, auth_token)
    assert response.status_code == 201
    cart = response.json()
    assert isinstance(cart["id"], int)
    assert cart["userId"] == 1
    assert len(cart["products"]) == len(items)
    for index, line in enumerate(cart["products"]):
        assert line["productId"] == items[index]["product_id"]
        assert line["quantity"] == items[index]["quantity"]


# TC-07: un carrito existente cumple el contrato esperado
def test_tc07_existing_cart_contract():
    response = requests.get(f"{BASE_URL}/carts/{SEED_CART_ID}", timeout=TIMEOUT_SECONDS)
    assert response.status_code == 200
    cart = response.json()
    assert cart["id"] == SEED_CART_ID
    assert isinstance(cart["userId"], int)
    assert isinstance(cart["date"], str)
    assert isinstance(cart["products"], list)
    assert len(cart["products"]) > 0
    for line in cart["products"]:
        assert isinstance(line["productId"], int)
        assert isinstance(line["quantity"], int)
        assert line["quantity"] > 0


# TC-09: el producto consultado en la API se guarda en SQLite con nombre y cantidad
def test_tc09_insert_product_in_sqlite(db_connection):
    product = cart_service.fetch_product(1)
    cart_service.add_item(db_connection, product, 2)
    row = db_connection.execute(
        "SELECT product_id, name, price, quantity, total FROM cart"
    ).fetchone()
    assert row[0] == product["id"]
    assert row[1] == product["title"]
    assert row[2] == product["price"]
    assert row[3] == 2
    assert row[4] == round(product["price"] * 2, 2)


# TC-23: actualizar un carrito devuelve la nueva cantidad
def test_tc23_update_cart_quantity():
    body = {"userId": 1, "products": [{"productId": 1, "quantity": 3}]}
    response = requests.put(
        f"{BASE_URL}/carts/{SEED_CART_ID}", json=body, timeout=TIMEOUT_SECONDS
    )
    assert response.status_code == 200
    cart = response.json()
    assert cart["id"] == SEED_CART_ID
    assert cart["products"][0]["productId"] == 1
    assert cart["products"][0]["quantity"] == 3


# =============================================
# Total
# ---------------------------------------------
# TC-08: el total del carrito 1 calculado con precios del catálogo es el esperado
def test_tc08_seed_cart_total_matches_expected(catalog):
    response = requests.get(f"{BASE_URL}/carts/{SEED_CART_ID}", timeout=TIMEOUT_SECONDS)
    assert response.status_code == 200
    total = 0
    for line in response.json()["products"]:
        product = find_product(catalog, line["productId"])
        total += product["price"] * line["quantity"]
    assert round(total, 2) == SEED_CART_EXPECTED_TOTAL


# TC-10: el carrito local suma líneas, unidades y monto correctamente
def test_tc10_local_cart_total(db_connection, catalog):
    first = catalog[0]
    second = catalog[1]
    cart_service.add_item(db_connection, first, 3)
    cart_service.add_item(db_connection, second, 2)
    summary = cart_service.get_cart_total(db_connection)
    assert summary["lines"] == 2
    assert summary["units"] == 5
    assert summary["amount"] == round(first["price"] * 3 + second["price"] * 2, 2)


# =============================================
# Checkout
# ---------------------------------------------
# TC-11: flujo completo catálogo, carrito, total y checkout con orden persistida
def test_tc11_checkout_with_token_persists_order(db_connection, catalog, auth_token):
    cart_service.add_item(db_connection, catalog[0], 1)
    cart_service.add_item(db_connection, catalog[2], 2)
    expected = cart_service.get_cart_total(db_connection)
    result = cart_service.checkout(db_connection, 1, auth_token)
    assert isinstance(result["remote_cart_id"], int)
    orders = cart_service.get_orders(db_connection)
    assert len(orders) == 1
    assert orders[0]["amount"] == expected["amount"]
    assert orders[0]["units"] == expected["units"]
    assert len(cart_service.get_cart_items(db_connection)) == 0


# TC-12: el checkout local se rechaza sin token y no deja datos a medias
@pytest.mark.parametrize("token", [None, ""])
def test_tc12_checkout_without_token_is_rejected(db_connection, catalog, token):
    cart_service.add_item(db_connection, catalog[0], 1)
    with pytest.raises(AuthenticationError, match="requires a valid token"):
        cart_service.checkout(db_connection, 1, token)
    assert len(cart_service.get_orders(db_connection)) == 0
    assert len(cart_service.get_cart_items(db_connection)) == 1


# TC-12: la API debería rechazar crear carritos sin token
@pytest.mark.xfail(
    strict=True, reason="DEF-07: POST /carts accepts requests without token"
)
def test_tc12_api_rejects_cart_without_token():
    response = requests.post(
        f"{BASE_URL}/carts", json=VALID_CART_BODY, timeout=TIMEOUT_SECONDS
    )
    assert response.status_code == 401


# =============================================
# Errores: productos y carritos inexistentes
# ---------------------------------------------
# TC-13: un producto inexistente no se puede agregar al carrito local
def test_tc13_missing_product_is_not_added(db_connection):
    with pytest.raises(ProductNotFoundError, match=str(NONEXISTENT_ID)):
        product = cart_service.fetch_product(NONEXISTENT_ID)
        cart_service.add_item(db_connection, product, 1)
    assert len(cart_service.get_cart_items(db_connection)) == 0


# TC-13: la API debería responder 404 para un producto inexistente
@pytest.mark.xfail(
    strict=True, reason="DEF-01: GET /products/{id} returns 200 with empty body"
)
def test_tc13_api_returns_404_for_missing_product():
    response = requests.get(
        f"{BASE_URL}/products/{NONEXISTENT_ID}", timeout=TIMEOUT_SECONDS
    )
    assert response.status_code == 404


# TC-13: la API debería rechazar un carrito con un producto inexistente
@pytest.mark.xfail(
    strict=True, reason="DEF-09: POST /carts accepts products that do not exist"
)
def test_tc13_api_rejects_cart_with_missing_product():
    body = {"userId": 1, "products": [{"productId": NONEXISTENT_ID, "quantity": 1}]}
    response = requests.post(f"{BASE_URL}/carts", json=body, timeout=TIMEOUT_SECONDS)
    assert response.status_code == 400


# TC-13: la API debería responder 404 para un carrito inexistente
@pytest.mark.xfail(
    strict=True, reason="DEF-10: GET /carts/{id} returns 200 with null body"
)
def test_tc13_api_returns_404_for_missing_cart():
    response = requests.get(
        f"{BASE_URL}/carts/{NONEXISTENT_ID}", timeout=TIMEOUT_SECONDS
    )
    assert response.status_code == 404


# =============================================
# Errores: cantidades
# ---------------------------------------------
# TC-14: cantidades cero o negativas se rechazan antes de tocar la BD
@pytest.mark.parametrize("quantity", [0, -1, -50])
def test_tc14_invalid_quantity_is_rejected_locally(db_connection, catalog, quantity):
    with pytest.raises(InvalidQuantityError, match="greater than zero"):
        cart_service.add_item(db_connection, catalog[0], quantity)
    assert len(cart_service.get_cart_items(db_connection)) == 0


# TC-14: no se puede superar el stock disponible (simulado con rating.count)
def test_tc14_quantity_above_stock_is_rejected(db_connection, catalog):
    product = catalog[0]
    stock = cart_service.get_available_stock(product)
    cart_service.add_item(db_connection, product, stock)
    with pytest.raises(InsufficientStockError, match="available"):
        cart_service.add_item(db_connection, product, 1)
    items = cart_service.get_cart_items(db_connection)
    assert items[0]["quantity"] == stock


# TC-14: la API debería rechazar cantidades cero o negativas
@pytest.mark.xfail(
    strict=True, reason="DEF-02: POST /carts accepts zero or negative quantities"
)
@pytest.mark.parametrize("quantity", [0, -1])
def test_tc14_api_rejects_invalid_quantity(quantity):
    body = {"userId": 1, "products": [{"productId": 1, "quantity": quantity}]}
    response = requests.post(f"{BASE_URL}/carts", json=body, timeout=TIMEOUT_SECONDS)
    assert response.status_code == 400


# =============================================
# Errores: body incompleto y tipos incorrectos
# ---------------------------------------------
# TC-15: la API debería rechazar bodies incompletos
@pytest.mark.xfail(strict=True, reason="DEF-03: POST /carts accepts incomplete bodies")
@pytest.mark.parametrize(
    "body",
    [{}, {"userId": 1}, {"products": [{"productId": 1, "quantity": 1}]}],
    ids=["empty", "without_products", "without_user"],
)
def test_tc15_api_rejects_incomplete_body(body):
    response = requests.post(f"{BASE_URL}/carts", json=body, timeout=TIMEOUT_SECONDS)
    assert response.status_code == 400


# TC-16: tipos incorrectos de cantidad se rechazan localmente
@pytest.mark.parametrize("quantity", ["2", 1.5, True, None])
def test_tc16_wrong_quantity_type_is_rejected_locally(db_connection, catalog, quantity):
    with pytest.raises(InvalidQuantityError, match="must be an integer"):
        cart_service.add_item(db_connection, catalog[0], quantity)
    assert len(cart_service.get_cart_items(db_connection)) == 0


# TC-16: tipos incorrectos de id de producto se rechazan antes de llamar a la API
@pytest.mark.parametrize("product_id", ["abc", 1.0, True])
def test_tc16_wrong_product_id_type_is_rejected_locally(product_id):
    with pytest.raises(ValueError, match="must be an integer"):
        cart_service.fetch_product(product_id)


# TC-16: la API debería rechazar tipos de dato incorrectos en el carrito
@pytest.mark.xfail(strict=True, reason="DEF-04: POST /carts accepts wrong data types")
def test_tc16_api_rejects_wrong_types():
    body = {"userId": "abc", "products": "not-a-list"}
    response = requests.post(f"{BASE_URL}/carts", json=body, timeout=TIMEOUT_SECONDS)
    assert response.status_code == 400


# TC-16: la API debería rechazar un id de producto no numérico
@pytest.mark.xfail(
    strict=True, reason="DEF-05: GET /products/abc returns 200 with empty body"
)
def test_tc16_api_rejects_non_numeric_product_id():
    response = requests.get(f"{BASE_URL}/products/abc", timeout=TIMEOUT_SECONDS)
    assert response.status_code == 400


# =============================================
# Errores: body inválido
# ---------------------------------------------
# TC-17: un JSON malformado se rechaza con 400
def test_tc17_malformed_json_returns_400():
    response = requests.post(
        f"{BASE_URL}/carts",
        data='{"userId": 1,',
        headers=JSON_HEADERS,
        timeout=TIMEOUT_SECONDS,
    )
    assert response.status_code == 400
    assert "Bad Request" in response.text


# TC-17: el error de JSON malformado debería venir en formato JSON
@pytest.mark.xfail(
    strict=True, reason="DEF-06: malformed JSON error is returned as HTML"
)
def test_tc17_malformed_json_error_is_json():
    response = requests.post(
        f"{BASE_URL}/carts",
        data='{"userId": 1,',
        headers=JSON_HEADERS,
        timeout=TIMEOUT_SECONDS,
    )
    assert response.headers["Content-Type"].startswith("application/json")


# =============================================
# Idempotencia
# ---------------------------------------------
# TC-19: dos GET iguales devuelven exactamente el mismo producto
def test_tc19_get_product_is_idempotent():
    first = requests.get(f"{BASE_URL}/products/1", timeout=TIMEOUT_SECONDS)
    second = requests.get(f"{BASE_URL}/products/1", timeout=TIMEOUT_SECONDS)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()


# TC-19: agregar dos veces el mismo producto no duplica la línea en SQLite
def test_tc19_adding_same_product_twice_does_not_duplicate(db_connection, catalog):
    product = catalog[0]
    cart_service.add_item(db_connection, product, 1)
    cart_service.add_item(db_connection, product, 1)
    items = cart_service.get_cart_items(db_connection)
    assert len(items) == 1
    assert items[0]["quantity"] == 2
    assert items[0]["total"] == round(product["price"] * 2, 2)


# TC-19: el mismo POST dos veces devuelve la misma respuesta (no crea duplicados)
def test_tc19_same_post_twice_returns_same_cart():
    first = requests.post(
        f"{BASE_URL}/carts", json=VALID_CART_BODY, timeout=TIMEOUT_SECONDS
    )
    second = requests.post(
        f"{BASE_URL}/carts", json=VALID_CART_BODY, timeout=TIMEOUT_SECONDS
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert first.json() == second.json()


# TC-19: un carrito recién creado debería poder consultarse después
@pytest.mark.xfail(
    strict=True, reason="DEF-08: created carts are not persisted by the API"
)
def test_tc19_created_cart_can_be_retrieved():
    created = requests.post(
        f"{BASE_URL}/carts", json=VALID_CART_BODY, timeout=TIMEOUT_SECONDS
    )
    cart_id = created.json()["id"]
    response = requests.get(f"{BASE_URL}/carts/{cart_id}", timeout=TIMEOUT_SECONDS)
    assert response.status_code == 200
    assert response.json() is not None


# =============================================
# Tiempo de respuesta
# ---------------------------------------------
# TC-20: el promedio de 3 llamadas a cada endpoint crítico está bajo el umbral
@pytest.mark.parametrize("method, path, body", CRITICAL_REQUESTS)
def test_tc20_response_time_is_acceptable(method, path, body, record_property):
    durations = []
    for _ in range(3):
        response = requests.request(
            method, f"{BASE_URL}{path}", json=body, timeout=TIMEOUT_SECONDS
        )
        assert response.status_code < 400
        durations.append(response.elapsed.total_seconds() * 1000)
    average_ms = round(sum(durations) / len(durations), 2)

    # Se guarda en el reporte JUnit para calcular la métrica después
    record_property("endpoint", f"{method} {path}")
    record_property("average_ms", average_ms)
    assert average_ms < MAX_RESPONSE_MS, f"{method} {path} averaged {average_ms} ms"


# =============================================
# Integración parcial: la BD falla
# ---------------------------------------------
# TC-21: la API responde bien pero la tabla no existe; el error es explícito
def test_tc21_db_failure_when_adding_item_raises_storage_error(db_connection):
    product = cart_service.fetch_product(1)
    assert product["id"] == 1
    db_connection.execute("DROP TABLE cart")
    with pytest.raises(CartStorageError, match="Could not save product 1"):
        cart_service.add_item(db_connection, product, 1)


# TC-21: el proveedor confirma el carrito pero la BD falla; se revierte todo lo local
def test_tc21_db_failure_during_checkout_rolls_back(db_connection, catalog, auth_token):
    cart_service.add_item(db_connection, catalog[0], 2)
    items_before = cart_service.get_cart_items(db_connection)

    # Simula una falla de disco: SQLite aborta al intentar vaciar el carrito
    db_connection.execute(
        "CREATE TRIGGER fail_cart_delete BEFORE DELETE ON cart "
        "BEGIN SELECT RAISE(ABORT, 'simulated disk failure'); END"
    )
    with pytest.raises(CheckoutError, match="kept intact for reconciliation"):
        cart_service.checkout(db_connection, 1, auth_token)

    # La orden insertada antes de la falla se revirtió y el carrito sigue igual
    assert len(cart_service.get_orders(db_connection)) == 0
    assert cart_service.get_cart_items(db_connection) == items_before


# =============================================
# Mock: proveedor externo caído
# ---------------------------------------------
# TC-22: un error de conexión del proveedor se traduce a un error controlado
def test_tc22_provider_connection_error_is_controlled(monkeypatch):
    # Paso 1: simular que la red rechaza la conexión
    def fake_request(*args, **kwargs):
        raise requests.ConnectionError("simulated connection refused")

    patch_provider(monkeypatch, fake_request)

    # Paso 2: el servicio debe fallar con un mensaje claro
    with pytest.raises(ProviderUnavailableError, match="simulated connection refused"):
        cart_service.fetch_products()


# TC-22: un 503 del proveedor se traduce a un error controlado
def test_tc22_provider_503_is_controlled(monkeypatch):
    # Paso 1: simular que el proveedor responde 503
    def fake_request(*args, **kwargs):
        return build_fake_response(503, '{"error": "Service Unavailable"}')

    patch_provider(monkeypatch, fake_request)

    # Paso 2: el servicio debe reportar el estado recibido
    with pytest.raises(ProviderUnavailableError, match="503"):
        cart_service.fetch_products()


# TC-22: si el proveedor cae en el checkout no se registra orden ni se vacía el carrito
def test_tc22_checkout_with_provider_down_keeps_cart(
    db_connection, catalog, monkeypatch
):
    cart_service.add_item(db_connection, catalog[0], 1)

    # Paso 1: a partir de aquí el proveedor responde 503
    def fake_request(*args, **kwargs):
        return build_fake_response(503, '{"error": "Service Unavailable"}')

    patch_provider(monkeypatch, fake_request)

    # Paso 2: el checkout falla de forma controlada y sin efectos locales
    with pytest.raises(ProviderUnavailableError, match="503"):
        cart_service.checkout(db_connection, 1, "fake-token")
    assert len(cart_service.get_orders(db_connection)) == 0
    assert len(cart_service.get_cart_items(db_connection)) == 1
