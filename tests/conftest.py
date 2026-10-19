# =============================================
# Imports
# ---------------------------------------------
import sqlite3

import pytest

import cart_service

# =============================================
# Constantes
# ---------------------------------------------
# Credenciales públicas de demostración publicadas en la documentación de FakeStore
DEMO_USERNAME = "mor_2314"
DEMO_PASSWORD = "83r5^_"


# =============================================
# Fixtures
# ---------------------------------------------
# Crea una base SQLite en memoria por prueba y la destruye al terminar
@pytest.fixture
def db_connection():
    conn = sqlite3.connect(":memory:")
    cart_service.create_schema(conn)
    yield conn
    conn.close()


# Descarga el catálogo una sola vez por sesión (solo lectura)
@pytest.fixture(scope="session")
def catalog():
    return cart_service.fetch_products()


# Obtiene un token real de FakeStore una sola vez por sesión
@pytest.fixture(scope="session")
def auth_token():
    return cart_service.login(DEMO_USERNAME, DEMO_PASSWORD)
