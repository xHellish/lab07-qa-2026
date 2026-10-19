# =============================================
# Imports
# ---------------------------------------------
import sqlite3
from datetime import datetime, timezone

import requests

# =============================================
# Constantes
# ---------------------------------------------
BASE_URL = "https://fakestoreapi.com"
REQUEST_TIMEOUT_SECONDS = 10

CART_TABLE_SQL = """
    CREATE TABLE cart (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL UNIQUE,
        name TEXT NOT NULL,
        price REAL NOT NULL,
        quantity INTEGER NOT NULL CHECK (quantity > 0),
        total REAL NOT NULL
    )
"""

ORDERS_TABLE_SQL = """
    CREATE TABLE orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        remote_cart_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        units INTEGER NOT NULL,
        amount REAL NOT NULL,
        created_at TEXT NOT NULL
    )
"""


# =============================================
# Excepciones
# ---------------------------------------------
# El proveedor externo no responde o responde con error 5xx
class ProviderUnavailableError(Exception):
    pass


# El producto solicitado no existe en el catálogo
class ProductNotFoundError(Exception):
    pass


# La cantidad no cumple las reglas de negocio
class InvalidQuantityError(Exception):
    pass


# No hay stock suficiente para la cantidad pedida
class InsufficientStockError(Exception):
    pass


# Falló la persistencia local en SQLite
class CartStorageError(Exception):
    pass


# Falta el token o las credenciales son inválidas
class AuthenticationError(Exception):
    pass


# El proceso de checkout no pudo completarse
class CheckoutError(Exception):
    pass


# =============================================
# Base de datos
# ---------------------------------------------
# Crea las tablas cart y orders en la conexión recibida
def create_schema(conn):
    cursor = conn.cursor()
    cursor.execute(CART_TABLE_SQL)
    cursor.execute(ORDERS_TABLE_SQL)
    conn.commit()


# Devuelve las líneas del carrito local como diccionarios
def get_cart_items(conn):
    cursor = conn.execute(
        "SELECT id, product_id, name, price, quantity, total FROM cart ORDER BY id"
    )
    items = []
    for row in cursor.fetchall():
        items.append(
            {
                "id": row[0],
                "product_id": row[1],
                "name": row[2],
                "price": row[3],
                "quantity": row[4],
                "total": row[5],
            }
        )
    return items


# Calcula líneas, unidades y monto total del carrito local
def get_cart_total(conn):
    row = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(quantity), 0), COALESCE(SUM(total), 0) FROM cart"
    ).fetchone()
    return {"lines": row[0], "units": row[1], "amount": round(row[2], 2)}


# Devuelve las órdenes registradas localmente
def get_orders(conn):
    cursor = conn.execute(
        "SELECT id, remote_cart_id, user_id, units, amount FROM orders ORDER BY id"
    )
    orders = []
    for row in cursor.fetchall():
        orders.append(
            {
                "id": row[0],
                "remote_cart_id": row[1],
                "user_id": row[2],
                "units": row[3],
                "amount": row[4],
            }
        )
    return orders


# =============================================
# Cliente de la API
# ---------------------------------------------
# Ejecuta un request y traduce fallas de red o 5xx a ProviderUnavailableError
def api_request(method, path, json_body=None, headers=None):
    url = f"{BASE_URL}{path}"

    # Paso 1: llamar al proveedor; cualquier falla de red se reporta explícitamente
    try:
        response = requests.request(
            method,
            url,
            json=json_body,
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        raise ProviderUnavailableError(f"{method} {url} failed: {error}") from error

    # Paso 2: un 5xx significa que el proveedor está caído o degradado
    if response.status_code >= 500:
        raise ProviderUnavailableError(
            f"{method} {url} returned {response.status_code}: {response.text[:200]}"
        )
    return response


# Consulta el catálogo completo y valida que sea una lista
def fetch_products():
    response = api_request("GET", "/products")
    if response.status_code != 200:
        raise ProviderUnavailableError(
            f"GET /products returned unexpected status {response.status_code}"
        )
    products = response.json()
    if not isinstance(products, list):
        raise ProviderUnavailableError(
            f"GET /products returned {type(products).__name__} instead of a list"
        )
    return products


# Consulta un producto y falla si no existe
def fetch_product(product_id):
    # Paso 1: validar el id antes de llamar a la API
    if isinstance(product_id, bool) or not isinstance(product_id, int):
        raise ValueError(f"Product id must be an integer, got {product_id!r}")
    if product_id <= 0:
        raise ValueError(f"Product id must be positive, got {product_id}")

    # Paso 2: FakeStore responde 200 con cuerpo vacío cuando el producto no existe
    response = api_request("GET", f"/products/{product_id}")
    if response.status_code == 404 or len(response.content) == 0:
        raise ProductNotFoundError(f"Product {product_id} does not exist")
    if response.status_code != 200:
        raise ProviderUnavailableError(
            f"GET /products/{product_id} returned unexpected status {response.status_code}"
        )
    return response.json()


# Inicia sesión en FakeStore y devuelve el token
def login(username, password):
    response = api_request(
        "POST", "/auth/login", json_body={"username": username, "password": password}
    )
    if response.status_code in (400, 401):
        raise AuthenticationError(
            f"Login failed with status {response.status_code}: {response.text}"
        )
    if response.status_code not in (200, 201):
        raise ProviderUnavailableError(
            f"POST /auth/login returned unexpected status {response.status_code}"
        )
    return response.json()["token"]


# Envía el carrito al proveedor con el formato de FakeStore
def create_remote_cart(user_id, items, token=None):
    # Paso 1: armar el body con productId y quantity por línea
    products = []
    for item in items:
        products.append({"productId": item["product_id"], "quantity": item["quantity"]})
    body = {
        "userId": user_id,
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "products": products,
    }

    # Paso 2: enviar el token solo si existe
    headers = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return api_request("POST", "/carts", json_body=body, headers=headers)


# =============================================
# Reglas de negocio
# ---------------------------------------------
# FakeStore no expone stock; se simula con rating.count
def get_available_stock(product):
    return product["rating"]["count"]


# Agrega un producto al carrito local respetando cantidad y stock
def add_item(conn, product, quantity):
    # Paso 1: la cantidad debe ser un entero positivo
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise InvalidQuantityError(
            f"Quantity must be an integer, got {type(quantity).__name__}"
        )
    if quantity <= 0:
        raise InvalidQuantityError(
            f"Quantity must be greater than zero, got {quantity}"
        )

    # Paso 2: sumar lo que ya hay en el carrito y validar contra el stock
    try:
        row = conn.execute(
            "SELECT quantity FROM cart WHERE product_id = ?", (product["id"],)
        ).fetchone()
        current_quantity = 0
        if row is not None:
            current_quantity = row[0]
        new_quantity = current_quantity + quantity
        stock = get_available_stock(product)
        if new_quantity > stock:
            raise InsufficientStockError(
                f"Requested {new_quantity} units of product {product['id']} "
                f"but only {stock} are available"
            )

        # Paso 3: actualizar la línea existente o crear una nueva (sin duplicados)
        line_total = round(product["price"] * new_quantity, 2)
        if row is None:
            conn.execute(
                "INSERT INTO cart (product_id, name, price, quantity, total) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    product["id"],
                    product["title"],
                    product["price"],
                    new_quantity,
                    line_total,
                ),
            )
        else:
            conn.execute(
                "UPDATE cart SET quantity = ?, total = ? WHERE product_id = ?",
                (new_quantity, line_total, product["id"]),
            )
        conn.commit()
    except sqlite3.Error as error:
        conn.rollback()
        raise CartStorageError(
            f"Could not save product {product['id']} in the cart: {error}"
        ) from error

    return get_cart_items(conn)


# Confirma la compra: envía el carrito al proveedor y registra la orden local
def checkout(conn, user_id, token):
    # Paso 1: autenticación simulada, sin token no hay compra
    if token is None or len(token) == 0:
        raise AuthenticationError("Checkout requires a valid token")

    # Paso 2: no se permite confirmar un carrito vacío
    items = get_cart_items(conn)
    if len(items) == 0:
        raise CheckoutError("Cannot checkout an empty cart")
    summary = get_cart_total(conn)

    # Paso 3: enviar el carrito al proveedor externo
    response = create_remote_cart(user_id, items, token)
    if response.status_code != 201:
        raise CheckoutError(
            f"Provider rejected the cart with status {response.status_code}: {response.text[:200]}"
        )
    remote_cart = response.json()

    # Paso 4: registrar la orden y vaciar el carrito en una sola transacción
    try:
        conn.execute(
            "INSERT INTO orders (remote_cart_id, user_id, units, amount, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                remote_cart["id"],
                user_id,
                summary["units"],
                summary["amount"],
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.execute("DELETE FROM cart")
        conn.commit()
    except sqlite3.Error as error:
        conn.rollback()
        raise CheckoutError(
            f"Remote cart {remote_cart['id']} was created but the local order could not "
            f"be saved; local cart kept intact for reconciliation: {error}"
        ) from error

    return {"remote_cart_id": remote_cart["id"], **summary}
