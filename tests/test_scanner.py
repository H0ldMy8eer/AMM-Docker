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
