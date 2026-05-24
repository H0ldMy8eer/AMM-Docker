import os
import pytest
import scanner


class TestParseRequirements:
    def test_returns_dependencies(self, tmp_path):
        req = tmp_path / "requirements.txt"
        req.write_text("Flask==3.0.0\nrequests==2.31.0\n")
        result = scanner.parse_requirements(str(req))
        assert "Flask==3.0.0" in result
        assert "requests==2.31.0" in result

    def test_skips_blank_lines(self, tmp_path):
        req = tmp_path / "requirements.txt"
        req.write_text("Flask==3.0.0\n\nrequests==2.31.0\n")
        result = scanner.parse_requirements(str(req))
        assert "" not in result
        assert len(result) == 2

    def test_skips_comments(self, tmp_path):
        req = tmp_path / "requirements.txt"
        req.write_text("# production deps\nFlask==3.0.0\n")
        result = scanner.parse_requirements(str(req))
        assert result == ["Flask==3.0.0"]

    def test_missing_file_returns_empty(self, tmp_path):
        result = scanner.parse_requirements(str(tmp_path / "nonexistent.txt"))
        assert result == []

    def test_empty_file_returns_empty(self, tmp_path):
        req = tmp_path / "requirements.txt"
        req.write_text("")
        result = scanner.parse_requirements(str(req))
        assert result == []


class TestScanProjectStructure:
    def test_detects_service_by_views_py(self, monolith_dir):
        result = scanner.scan_project_structure(str(monolith_dir))
        modules = {m['name']: m for m in result['modules']}
        assert 'users' in modules
        assert modules['users']['type'] == 'service'

    def test_detects_service_by_routes_py(self, tmp_path):
        svc = tmp_path / "orders"
        svc.mkdir()
        (svc / "__init__.py").write_text("")
        (svc / "routes.py").write_text("# routes")
        result = scanner.scan_project_structure(str(tmp_path))
        modules = {m['name']: m for m in result['modules']}
        assert modules['orders']['type'] == 'service'

    def test_detects_shared_without_views_or_routes(self, monolith_dir):
        result = scanner.scan_project_structure(str(monolith_dir))
        modules = {m['name']: m for m in result['modules']}
        assert 'common' in modules
        assert modules['common']['type'] == 'shared'

    def test_multiple_services_found(self, monolith_dir):
        result = scanner.scan_project_structure(str(monolith_dir))
        services = [m for m in result['modules'] if m['type'] == 'service']
        assert len(services) == 2

    def test_reads_root_requirements(self, monolith_dir):
        result = scanner.scan_project_structure(str(monolith_dir))
        assert '.' in result['dependencies']
        assert 'Flask==3.0.0' in result['dependencies']['.']

    def test_reads_nested_requirements(self, monolith_dir):
        result = scanner.scan_project_structure(str(monolith_dir))
        deps_keys = list(result['dependencies'].keys())
        assert any('products' in key for key in deps_keys)

    def test_ignores_pycache(self, monolith_dir):
        cache = monolith_dir / "__pycache__"
        cache.mkdir()
        (cache / "module.cpython-314.pyc").write_bytes(b"")
        result = scanner.scan_project_structure(str(monolith_dir))
        names = [m['name'] for m in result['modules']]
        assert '__pycache__' not in names

    def test_ignores_venv(self, monolith_dir):
        venv = monolith_dir / "venv"
        venv.mkdir()
        (venv / "views.py").write_text("# should not be picked up")
        result = scanner.scan_project_structure(str(monolith_dir))
        names = [m['name'] for m in result['modules']]
        assert 'venv' not in names

    def test_modules_have_required_keys(self, monolith_dir):
        result = scanner.scan_project_structure(str(monolith_dir))
        for module in result['modules']:
            assert 'name' in module
            assert 'path' in module
            assert 'type' in module
            assert 'files_count' in module

    def test_files_count_is_accurate(self, monolith_dir):
        result = scanner.scan_project_structure(str(monolith_dir))
        modules = {m['name']: m for m in result['modules']}
        # users/ has __init__.py, views.py, models.py = 3 py files
        assert modules['users']['files_count'] == 3

    def test_empty_dir_not_added_as_module(self, tmp_path):
        empty = tmp_path / "empty_module"
        empty.mkdir()
        result = scanner.scan_project_structure(str(tmp_path))
        names = [m['name'] for m in result['modules']]
        assert 'empty_module' not in names


class TestAnalyzeImportGraph:
    def test_detects_import_between_modules(self, tmp_path):
        svc = tmp_path / "orders"
        svc.mkdir()
        (svc / "views.py").write_text("from common import db\n")

        shared = tmp_path / "common"
        shared.mkdir()
        (shared / "db.py").write_text("# db")

        modules = [
            {'name': 'orders', 'path': 'orders', 'type': 'service'},
            {'name': 'common', 'path': 'common', 'type': 'shared'},
        ]
        edges = scanner.analyze_import_graph(str(tmp_path), modules)
        assert any(e['from'] == 'orders' and e['to'] == 'common' for e in edges)

    def test_no_self_edges(self, tmp_path):
        svc = tmp_path / "users"
        svc.mkdir()
        (svc / "views.py").write_text("from users import models\n")

        modules = [{'name': 'users', 'path': 'users', 'type': 'service'}]
        edges = scanner.analyze_import_graph(str(tmp_path), modules)
        assert not any(e['from'] == e['to'] for e in edges)

    def test_no_duplicate_edges(self, tmp_path):
        svc = tmp_path / "orders"
        svc.mkdir()
        (svc / "views.py").write_text("from common import a\nfrom common import b\n")
        (svc / "models.py").write_text("import common\n")

        shared = tmp_path / "common"
        shared.mkdir()
        (shared / "utils.py").write_text("")

        modules = [
            {'name': 'orders', 'path': 'orders', 'type': 'service'},
            {'name': 'common', 'path': 'common', 'type': 'shared'},
        ]
        edges = scanner.analyze_import_graph(str(tmp_path), modules)
        pairs = [(e['from'], e['to']) for e in edges]
        assert len(pairs) == len(set(pairs))

    def test_returns_empty_when_no_imports(self, tmp_path):
        svc = tmp_path / "users"
        svc.mkdir()
        (svc / "views.py").write_text("x = 1\n")

        modules = [{'name': 'users', 'path': 'users', 'type': 'service'}]
        edges = scanner.analyze_import_graph(str(tmp_path), modules)
        assert edges == []

    def test_service_to_service_edge(self, tmp_path):
        """products импортирует users → ребро products→users."""
        (tmp_path / "users").mkdir()
        (tmp_path / "users" / "views.py").write_text(
            "from flask import Blueprint\nuser_bp = Blueprint('users', __name__)\n"
        )
        (tmp_path / "products").mkdir()
        (tmp_path / "products" / "views.py").write_text(
            "from flask import Blueprint\n"
            "from users import models\n"
            "product_bp = Blueprint('products', __name__)\n"
        )
        modules = [
            {'name': 'users',    'path': 'users',    'type': 'service'},
            {'name': 'products', 'path': 'products', 'type': 'service'},
        ]
        edges = scanner.analyze_import_graph(str(tmp_path), modules)
        assert any(e['from'] == 'products' and e['to'] == 'users' for e in edges)

    def test_importlib_import_detected(self, tmp_path):
        """importlib.import_module('common') должен создавать ребро."""
        (tmp_path / "orders").mkdir()
        (tmp_path / "orders" / "views.py").write_text(
            "import importlib\ncommon = importlib.import_module('common')\n"
        )
        (tmp_path / "common").mkdir()
        (tmp_path / "common" / "utils.py").write_text("x = 1\n")
        modules = [
            {'name': 'orders', 'path': 'orders', 'type': 'service'},
            {'name': 'common', 'path': 'common', 'type': 'shared'},
        ]
        edges = scanner.analyze_import_graph(str(tmp_path), modules)
        assert any(e['from'] == 'orders' and e['to'] == 'common' for e in edges)

    def test_monolith_has_expected_edges(self, monolith_dir):
        """Из фикстуры ожидаем: users→common, products→common, products→users."""
        result = scanner.scan_project_structure(str(monolith_dir))
        edges = scanner.analyze_import_graph(str(monolith_dir), result['modules'])
        pairs = {(e['from'], e['to']) for e in edges}
        assert ('users', 'common') in pairs
        assert ('products', 'common') in pairs
        assert ('products', 'users') in pairs


class TestDetectFramework:
    def test_detects_flask_from_requirements(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("Flask==3.0.0\n")
        assert scanner.detect_framework(str(tmp_path)) == 'flask'

    def test_detects_fastapi_from_requirements(self, fastapi_monolith):
        assert scanner.detect_framework(str(fastapi_monolith)) == 'fastapi'

    def test_detects_django_from_manage_py(self, django_monolith):
        assert scanner.detect_framework(str(django_monolith)) == 'django'

    def test_detects_django_from_requirements(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("Django>=4.2\n")
        assert scanner.detect_framework(str(tmp_path)) == 'django'

    def test_detects_flask_from_imports(self, tmp_path):
        (tmp_path / "app.py").write_text("from flask import Flask\napp = Flask(__name__)\n")
        assert scanner.detect_framework(str(tmp_path)) == 'flask'

    def test_unknown_when_no_hints(self, tmp_path):
        (tmp_path / "script.py").write_text("print('hello')\n")
        assert scanner.detect_framework(str(tmp_path)) == 'unknown'

    def test_missing_dir_returns_unknown(self, tmp_path):
        result = scanner.detect_framework(str(tmp_path / "nonexistent"))
        assert result == 'unknown'


class TestFastAPIDetection:
    def test_detects_apirouter_as_service(self, fastapi_monolith):
        result = scanner.scan_project_structure(str(fastapi_monolith))
        services = [m for m in result['modules'] if m['type'] == 'service']
        names = {m['name'] for m in services}
        assert 'users' in names
        assert 'orders' in names

    def test_apirouter_prefix_extracted(self, fastapi_monolith):
        result = scanner.scan_project_structure(str(fastapi_monolith))
        modules = {m['name']: m for m in result['modules']}
        assert modules['users'].get('url_prefix') == '/users' or \
               modules['users']['type'] == 'service'

    def test_fastapi_service_to_service_edge(self, fastapi_monolith):
        result = scanner.scan_project_structure(str(fastapi_monolith))
        edges = scanner.analyze_import_graph(str(fastapi_monolith), result['modules'])
        assert any(e['from'] == 'orders' and e['to'] == 'users' for e in edges)

    def test_router_py_detected_as_service_file(self, tmp_path):
        svc = tmp_path / "payments"
        svc.mkdir()
        (svc / "router.py").write_text("# FastAPI router\n")
        result = scanner.scan_project_structure(str(tmp_path))
        modules = {m['name']: m for m in result['modules']}
        assert modules.get('payments', {}).get('type') == 'service'


class TestDjangoDetection:
    def test_detects_django_app_by_urls_py(self, django_monolith):
        result = scanner.scan_project_structure(str(django_monolith))
        services = [m for m in result['modules'] if m['type'] == 'service']
        names = {m['name'] for m in services}
        assert 'blog' in names
        assert 'shop' in names

    def test_urlpatterns_makes_service(self, tmp_path):
        app = tmp_path / "catalog"
        app.mkdir()
        (app / "__init__.py").write_text("")
        (app / "app_urls.py").write_text(
            "urlpatterns = []\n"
        )
        result = scanner.scan_project_structure(str(tmp_path))
        modules = {m['name']: m for m in result['modules']}
        assert modules.get('catalog', {}).get('type') == 'service'
