# =============================================
# Imports
# ---------------------------------------------
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# =============================================
# Constantes
# ---------------------------------------------
PROJECT_DIR = Path(__file__).resolve().parent.parent
REPORTS_DIR = PROJECT_DIR / "reports"
JUNIT_PATH = REPORTS_DIR / "pytest_junit.xml"
NEWMAN_PATH = REPORTS_DIR / "newman_report.json"
COLLECTION_PATH = (
    PROJECT_DIR / "postman" / "Integracion_API_Carrito.postman_collection.json"
)
OUTPUT_PATH = REPORTS_DIR / "metrics.json"

MAX_RESPONSE_MS = 1000
NEGATIVE_FOLDER = "Errores"

# Endpoints que forman el flujo de compra elegido
FLOW_ENDPOINTS = (
    "GET /products",
    "GET /products/{id}",
    "GET /products/categories",
    "POST /auth/login",
    "POST /carts",
    "GET /carts/{id}",
    "PUT /carts/{id}",
)

# Requests críticos del flujo para la métrica de tiempo promedio
CRITICAL_REQUESTS = (
    "TC-01 Consultar catálogo",
    "TC-02 Consultar detalle de producto",
    "TC-06 Crear carrito",
    "TC-07 Consultar carrito existente",
    "TC-05 Login (obtener token)",
    "TC-11 Checkout con token",
)

# Severidad asignada a cada defecto encontrado
DEFECT_SEVERITY = {
    "DEF-01": "Medium",
    "DEF-02": "High",
    "DEF-03": "High",
    "DEF-04": "High",
    "DEF-05": "Low",
    "DEF-06": "Low",
    "DEF-07": "Critical",
    "DEF-08": "Medium",
    "DEF-09": "High",
    "DEF-10": "Low",
}


# =============================================
# Funciones
# ---------------------------------------------
# Lee un archivo y falla con un mensaje claro si no existe
def require_file(path):
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Run the test suites first (see README)"
        )
    return path


# Convierte una URL en "METODO /ruta/{id}" para medir cobertura
def normalize_endpoint(method, path_segments):
    normalized = []
    for segment in path_segments:
        if re.fullmatch(r"\d+|abc", segment):
            normalized.append("{id}")
        else:
            normalized.append(segment)
    return f"{method} /" + "/".join(normalized)


# Calcula las métricas de Pytest a partir del reporte JUnit
def pytest_metrics():
    root = ET.parse(require_file(JUNIT_PATH)).getroot()
    total = 0
    passed = 0
    failed = 0
    xfailed = 0
    defects = set()
    response_times = {}

    # Paso 1: clasificar cada caso como aprobado, fallido o defecto conocido (xfail)
    for testcase in root.iter("testcase"):
        total += 1
        skipped = testcase.find("skipped")
        failure = testcase.find("failure")
        error = testcase.find("error")
        if skipped is not None and skipped.get("type") == "pytest.xfail":
            xfailed += 1
            match = re.search(r"DEF-\d+", skipped.get("message", ""))
            if match is not None:
                defects.add(match.group(0))
        elif failure is not None or error is not None:
            failed += 1
        else:
            passed += 1

        # Paso 2: recoger los tiempos registrados con record_property
        properties = {}
        for prop in testcase.iter("property"):
            properties[prop.get("name")] = prop.get("value")
        if "average_ms" in properties:
            response_times[properties["endpoint"]] = float(properties["average_ms"])

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "xfailed_known_defects": xfailed,
        "pass_rate": round(passed / total * 100, 2),
        "defects": sorted(defects),
        "average_response_ms": response_times,
    }


# Mapea cada request de la colección a su carpeta
def request_folders():
    collection = json.loads(require_file(COLLECTION_PATH).read_text(encoding="utf-8"))
    folders = {}
    for folder in collection["item"]:
        for item in folder["item"]:
            folders[item["name"]] = folder["name"]
    return folders


# Calcula las métricas de Postman a partir del reporte JSON de Newman
def newman_metrics():
    report = json.loads(require_file(NEWMAN_PATH).read_text(encoding="utf-8"))
    folders = request_folders()
    run = report["run"]
    executions = run["executions"]

    per_request = {}
    endpoints = set()
    unexpected_errors = 0
    defects = set()

    seen_executions = set()
    for execution in executions:
        name = execution["item"]["name"]
        response = execution.get("response")
        if response is None:
            continue

        # Newman duplica la ejecución cuando el script usa pm.sendRequest; se cuenta una vez
        execution_key = (execution["id"], execution["cursor"]["iteration"])
        if execution_key in seen_executions:
            continue
        seen_executions.add(execution_key)
        stats = per_request.setdefault(
            name, {"runs": 0, "times": [], "assertions": 0, "failed": 0, "codes": []}
        )
        stats["runs"] += 1
        stats["times"].append(response["responseTime"])
        stats["codes"].append(response["code"])

        # Paso 1: contar aserciones y defectos referenciados en los fallos
        for assertion in execution.get("assertions", []):
            stats["assertions"] += 1
            if "error" in assertion:
                stats["failed"] += 1
                match = re.search(r"DEF-\d+", assertion["assertion"])
                if match is not None:
                    defects.add(match.group(0))

        # Paso 2: un 4xx/5xx fuera de la carpeta de errores es inesperado
        if response["code"] >= 400 and folders.get(name) != NEGATIVE_FOLDER:
            unexpected_errors += 1

        # Paso 3: registrar el endpoint para la cobertura
        url = execution["request"]["url"]
        endpoints.add(normalize_endpoint(execution["request"]["method"], url["path"]))

    total_assertions = run["stats"]["assertions"]["total"]
    failed_assertions = run["stats"]["assertions"]["failed"]
    executed_requests = run["stats"]["requests"]["total"]
    requests_all_passed = 0
    assertions_per_request = {}
    average_times = {}
    for name, stats in per_request.items():
        assertions_per_request[name] = stats["assertions"] // stats["runs"]
        average_times[name] = round(sum(stats["times"]) / len(stats["times"]), 2)
        if stats["failed"] == 0:
            requests_all_passed += 1

    critical_times = {}
    for name in CRITICAL_REQUESTS:
        if name in average_times:
            critical_times[name] = average_times[name]

    covered = []
    for endpoint in FLOW_ENDPOINTS:
        if endpoint in endpoints:
            covered.append(endpoint)

    return {
        "iterations": run["stats"]["iterations"]["total"],
        "requests_executed": executed_requests,
        "requests_defined": len(per_request),
        "requests_all_assertions_passed": requests_all_passed,
        "assertions_total": total_assertions,
        "assertions_failed": failed_assertions,
        "assertion_pass_rate": round(
            (total_assertions - failed_assertions) / total_assertions * 100, 2
        ),
        "request_pass_rate": round(requests_all_passed / len(per_request) * 100, 2),
        "average_response_ms_critical": critical_times,
        "average_response_ms_all": average_times,
        "assertions_per_request": assertions_per_request,
        "min_assertions_per_request": min(assertions_per_request.values()),
        "unexpected_error_responses": unexpected_errors,
        "error_rate": round(unexpected_errors / executed_requests * 100, 2),
        "flow_endpoints": list(FLOW_ENDPOINTS),
        "covered_endpoints": covered,
        "endpoint_coverage": round(len(covered) / len(FLOW_ENDPOINTS) * 100, 2),
        "defects": sorted(defects),
    }


# Imprime un resumen legible de las métricas
def print_summary(metrics):
    # La consola de Windows puede no usar UTF-8; se fuerza para los nombres con tildes
    sys.stdout.reconfigure(encoding="utf-8")
    pytest_data = metrics["pytest"]
    newman_data = metrics["postman"]
    print("=== Pytest ===")
    print(
        f"Tests: {pytest_data['total']} | passed: {pytest_data['passed']} | "
        f"failed: {pytest_data['failed']} | known defects (xfail): "
        f"{pytest_data['xfailed_known_defects']} | pass rate: {pytest_data['pass_rate']}%"
    )
    for endpoint, average in pytest_data["average_response_ms"].items():
        print(f"  {endpoint}: {average} ms")
    print("=== Postman / Newman ===")
    print(
        f"Iterations: {newman_data['iterations']} | requests executed: "
        f"{newman_data['requests_executed']} | assertions: {newman_data['assertions_total']} "
        f"(failed {newman_data['assertions_failed']}) | assertion pass rate: "
        f"{newman_data['assertion_pass_rate']}%"
    )
    print(
        f"Requests with all assertions passed: {newman_data['requests_all_assertions_passed']}"
        f"/{newman_data['requests_defined']} ({newman_data['request_pass_rate']}%)"
    )
    print(
        f"Endpoint coverage: {newman_data['endpoint_coverage']}% | min assertions per request: "
        f"{newman_data['min_assertions_per_request']} | error rate: {newman_data['error_rate']}%"
    )
    for name, average in newman_data["average_response_ms_critical"].items():
        print(f"  {name}: {average} ms")
    print("=== Defects ===")
    for defect_id in metrics["defects"]:
        print(f"  {defect_id} ({DEFECT_SEVERITY.get(defect_id, 'Unclassified')})")


# Punto de entrada: calcula, imprime y guarda las métricas
def main():
    pytest_data = pytest_metrics()
    newman_data = newman_metrics()

    # Unir los defectos detectados por ambas herramientas
    all_defects = set(pytest_data["defects"])
    for defect_id in newman_data["defects"]:
        all_defects.add(defect_id)
    severity_count = {}
    for defect_id in all_defects:
        severity = DEFECT_SEVERITY.get(defect_id, "Unclassified")
        severity_count[severity] = severity_count.get(severity, 0) + 1

    metrics = {
        "pytest": pytest_data,
        "postman": newman_data,
        "defects": sorted(all_defects),
        "defects_by_severity": severity_count,
        "max_response_ms": MAX_RESPONSE_MS,
    }
    OUTPUT_PATH.write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print_summary(metrics)
    print(f"Metrics saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError as error:
        print(f"Error: {error}")
        sys.exit(1)
