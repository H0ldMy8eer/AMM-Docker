import json
import pytest
import frontend_scanner
from frontend_scanner import (
    scan_frontend_project,
    _parse_vite_config,
    _parse_next_config,
    _parse_angular_json,
    _extract_port_from_scripts,
    _extract_cra_proxy,
    _detect_language,
    _detect_node_version,
    _detect_entry_point,
)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _write_pkg(root, deps=None, dev_deps=None, scripts=None, extra=None):
    """Write a minimal package.json to root."""
    pkg = {
        'name': 'test-app',
        'version': '1.0.0',
        'dependencies':    deps     or {},
        'devDependencies': dev_deps or {},
        'scripts':         scripts  or {},
    }
    if extra:
        pkg.update(extra)
    (root / 'package.json').write_text(json.dumps(pkg))
    return pkg


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def react_vite_root(tmp_path):
    """React 18 + Vite project with vite.config.ts, proxy, TypeScript."""
    _write_pkg(
        tmp_path,
        deps    ={'react': '^18.0.0', 'react-dom': '^18.0.0'},
        dev_deps={'vite': '^5.0.0', '@vitejs/plugin-react': '^4.0.0'},
        scripts ={'dev': 'vite', 'build': 'vite build', 'preview': 'vite preview'},
    )
    (tmp_path / 'vite.config.ts').write_text(
        "import { defineConfig } from 'vite';\n"
        "export default defineConfig({\n"
        "  server: {\n"
        "    port: 5174,\n"
        "    proxy: {\n"
        "      '/api': { target: 'http://localhost:8080', changeOrigin: true },\n"
        "    },\n"
        "  },\n"
        "});\n"
    )
    (tmp_path / 'tsconfig.json').write_text('{}')
    src = tmp_path / 'src'
    src.mkdir()
    (src / 'main.tsx').write_text('// entry')
    return tmp_path


@pytest.fixture
def angular_root(tmp_path):
    """Angular 17 project with angular.json and proxy.conf.json."""
    _write_pkg(
        tmp_path,
        deps    ={'@angular/core': '^17.0.0'},
        dev_deps={'@angular-devkit/build-angular': '^17.0.0'},
    )
    ang = {
        'projects': {
            'my-app': {
                'architect': {
                    'serve': {
                        'options': {
                            'port': 4201,
                            'proxyConfig': 'proxy.conf.json',
                        }
                    }
                }
            }
        }
    }
    (tmp_path / 'angular.json').write_text(json.dumps(ang))
    (tmp_path / 'proxy.conf.json').write_text(json.dumps({
        '/api': {'target': 'http://localhost:8080', 'secure': False}
    }))
    (tmp_path / 'tsconfig.json').write_text('{}')
    src = tmp_path / 'src'
    src.mkdir()
    (src / 'main.ts').write_text('// entry')
    return tmp_path


@pytest.fixture
def next_root(tmp_path):
    """Next.js 14 project with rewrites in next.config.js."""
    _write_pkg(
        tmp_path,
        deps   ={'next': '^14.0.0', 'react': '^18.0.0'},
        scripts={'dev': 'next dev', 'build': 'next build'},
    )
    (tmp_path / 'next.config.js').write_text(
        "module.exports = {\n"
        "  async rewrites() {\n"
        "    return [{ source: '/api/:path*',"
        " destination: 'http://localhost:8080/:path*' }];\n"
        "  },\n"
        "};\n"
    )
    app_dir = tmp_path / 'app'
    app_dir.mkdir()
    (app_dir / 'layout.tsx').write_text('// layout')
    return tmp_path


@pytest.fixture
def cra_root(tmp_path):
    """CRA project with string proxy in package.json."""
    _write_pkg(
        tmp_path,
        deps    ={'react': '^18.0.0'},
        dev_deps={'react-scripts': '5.0.1'},
        scripts ={'start': 'react-scripts start', 'build': 'react-scripts build'},
        extra   ={'proxy': 'http://localhost:8080'},
    )
    return tmp_path


@pytest.fixture
def vue_vite_root(tmp_path):
    """Vue 3 + Vite project."""
    _write_pkg(
        tmp_path,
        deps    ={'vue': '^3.0.0'},
        dev_deps={'vite': '^5.0.0', '@vitejs/plugin-vue': '^4.0.0'},
        scripts ={'dev': 'vite --port 5200'},
    )
    return tmp_path


# ─────────────────────────────────────────────────────────────────────────────
# TestFrameworkDetection
# ─────────────────────────────────────────────────────────────────────────────

class TestFrameworkDetection:
    def test_detects_react(self, react_vite_root):
        assert scan_frontend_project(str(react_vite_root))['framework'] == 'react'

    def test_detects_angular(self, angular_root):
        assert scan_frontend_project(str(angular_root))['framework'] == 'angular'

    def test_detects_next(self, next_root):
        assert scan_frontend_project(str(next_root))['framework'] == 'next'

    def test_detects_vue(self, vue_vite_root):
        assert scan_frontend_project(str(vue_vite_root))['framework'] == 'vue'

    def test_next_beats_react_in_priority(self, next_root):
        # next fixture has both 'next' and 'react' in deps
        assert scan_frontend_project(str(next_root))['framework'] == 'next'

    def test_unknown_framework_when_no_known_dep(self, tmp_path):
        _write_pkg(tmp_path, deps={'some-lib': '1.0.0'})
        assert scan_frontend_project(str(tmp_path))['framework'] == 'unknown'

    def test_missing_package_json_returns_unknown(self, tmp_path):
        assert scan_frontend_project(str(tmp_path))['framework'] == 'unknown'

    def test_detects_svelte(self, tmp_path):
        _write_pkg(tmp_path, deps={'svelte': '^4.0.0'})
        assert scan_frontend_project(str(tmp_path))['framework'] == 'svelte'


# ─────────────────────────────────────────────────────────────────────────────
# TestBuildToolDetection
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildToolDetection:
    def test_detects_vite_from_dep(self, react_vite_root):
        assert scan_frontend_project(str(react_vite_root))['build_tool'] == 'vite'

    def test_detects_cra(self, cra_root):
        assert scan_frontend_project(str(cra_root))['build_tool'] == 'cra'

    def test_detects_angular_cli(self, angular_root):
        assert scan_frontend_project(str(angular_root))['build_tool'] == 'angular-cli'

    def test_next_framework_gets_next_build_tool(self, next_root):
        assert scan_frontend_project(str(next_root))['build_tool'] == 'next'

    def test_vite_plugin_also_triggers_vite(self, tmp_path):
        _write_pkg(tmp_path, dev_deps={'@vitejs/plugin-react': '^4.0.0',
                                       'react': '^18.0.0'})
        assert scan_frontend_project(str(tmp_path))['build_tool'] == 'vite'


# ─────────────────────────────────────────────────────────────────────────────
# TestPortDetection
# ─────────────────────────────────────────────────────────────────────────────

class TestPortDetection:
    def test_reads_port_from_vite_config(self, react_vite_root):
        assert scan_frontend_project(str(react_vite_root))['dev_port'] == 5174

    def test_reads_port_from_angular_json(self, angular_root):
        assert scan_frontend_project(str(angular_root))['dev_port'] == 4201

    def test_script_port_flag_long(self, tmp_path):
        _write_pkg(tmp_path, deps={'react': '^18.0.0'},
                   dev_deps={'vite': '^5.0.0'},
                   scripts={'dev': 'vite --port 3333'})
        assert scan_frontend_project(str(tmp_path))['dev_port'] == 3333

    def test_script_port_flag_short(self, vue_vite_root):
        # vue_vite_root has 'dev': 'vite --port 5200' and no vite.config.ts
        assert scan_frontend_project(str(vue_vite_root))['dev_port'] == 5200

    def test_default_port_react(self, cra_root):
        assert scan_frontend_project(str(cra_root))['dev_port'] == 3000

    def test_default_port_angular(self, tmp_path):
        _write_pkg(tmp_path, deps={'@angular/core': '^17.0.0'})
        assert scan_frontend_project(str(tmp_path))['dev_port'] == 4200

    def test_default_port_vue(self, tmp_path):
        _write_pkg(tmp_path, deps={'vue': '^3.0.0'})
        assert scan_frontend_project(str(tmp_path))['dev_port'] == 5173

    def test_extract_port_long_flag(self):
        assert _extract_port_from_scripts({'dev': 'vite --port 4000'}) == 4000

    def test_extract_port_short_flag(self):
        assert _extract_port_from_scripts({'dev': 'vite -p 5555'}) == 5555

    def test_extract_port_no_flag_returns_none(self):
        assert _extract_port_from_scripts({'dev': 'vite', 'build': 'vite build'}) is None

    def test_extract_port_prefers_dev_over_start(self):
        scripts = {'start': 'node --port 8000', 'dev': 'vite --port 3001'}
        assert _extract_port_from_scripts(scripts) == 3001


# ─────────────────────────────────────────────────────────────────────────────
# TestProxyDetection
# ─────────────────────────────────────────────────────────────────────────────

class TestProxyDetection:
    def test_vite_proxy_detected(self, react_vite_root):
        result = scan_frontend_project(str(react_vite_root))
        assert any(p['from'] == '/api' and 'localhost:8080' in p['to']
                   for p in result['api_proxy'])

    def test_angular_proxy_from_proxy_conf(self, angular_root):
        result = scan_frontend_project(str(angular_root))
        assert any(p['from'] == '/api' and 'localhost:8080' in p['to']
                   for p in result['api_proxy'])

    def test_next_rewrites_extracted(self, next_root):
        result = scan_frontend_project(str(next_root))
        assert any('localhost:8080' in p['to'] for p in result['api_proxy'])

    def test_cra_string_proxy(self, cra_root):
        result = scan_frontend_project(str(cra_root))
        assert any('localhost:8080' in p['to'] for p in result['api_proxy'])

    def test_no_proxy_when_unconfigured(self, tmp_path):
        _write_pkg(tmp_path, deps={'vue': '^3.0.0'})
        assert scan_frontend_project(str(tmp_path))['api_proxy'] == []

    def test_vite_config_parse_direct(self, react_vite_root):
        port, proxies = _parse_vite_config(str(react_vite_root))
        assert port == 5174
        assert len(proxies) == 1
        assert proxies[0]['from'] == '/api'

    def test_next_config_parse_direct(self, next_root):
        _, proxies = _parse_next_config(str(next_root))
        assert any('localhost:8080' in p['to'] for p in proxies)

    def test_angular_json_parse_direct(self, angular_root):
        port, proxies = _parse_angular_json(str(angular_root))
        assert port == 4201
        assert any(p['from'] == '/api' for p in proxies)

    def test_cra_proxy_from_string(self, tmp_path):
        pkg = {'proxy': 'http://localhost:9000'}
        proxies = _extract_cra_proxy(str(tmp_path), pkg)
        assert proxies == [{'from': '/api', 'to': 'http://localhost:9000'}]

    def test_cra_proxy_from_dict(self, tmp_path):
        pkg = {'proxy': {'/api': {'target': 'http://localhost:9001'}}}
        proxies = _extract_cra_proxy(str(tmp_path), pkg)
        assert any(p['from'] == '/api' and 'localhost:9001' in p['to']
                   for p in proxies)

    def test_no_vite_config_returns_none_empty(self, tmp_path):
        port, proxies = _parse_vite_config(str(tmp_path))
        assert port is None
        assert proxies == []


# ─────────────────────────────────────────────────────────────────────────────
# TestLanguageDetection
# ─────────────────────────────────────────────────────────────────────────────

class TestLanguageDetection:
    def test_typescript_from_tsconfig_json(self, react_vite_root):
        assert scan_frontend_project(str(react_vite_root))['language'] == 'typescript'

    def test_typescript_from_typescript_dep(self, tmp_path):
        pkg = {'devDependencies': {'typescript': '^5.0.0'}}
        assert _detect_language(str(tmp_path), pkg) == 'typescript'

    def test_typescript_from_tsx_file_in_src(self, tmp_path):
        src = tmp_path / 'src'
        src.mkdir()
        (src / 'App.tsx').write_text('export default () => null;')
        assert _detect_language(str(tmp_path), {}) == 'typescript'

    def test_typescript_from_ts_file_in_src(self, tmp_path):
        src = tmp_path / 'src'
        src.mkdir()
        (src / 'main.ts').write_text('// ts')
        assert _detect_language(str(tmp_path), {}) == 'typescript'

    def test_javascript_when_no_ts_indicators(self, tmp_path):
        assert _detect_language(str(tmp_path), {}) == 'javascript'


# ─────────────────────────────────────────────────────────────────────────────
# TestNodeVersionDetection
# ─────────────────────────────────────────────────────────────────────────────

class TestNodeVersionDetection:
    def test_reads_version_from_nvmrc_with_v_prefix(self, tmp_path):
        (tmp_path / '.nvmrc').write_text('v20.11.0')
        assert _detect_node_version(str(tmp_path), {}) == '20'

    def test_reads_version_from_nvmrc_no_prefix(self, tmp_path):
        (tmp_path / '.nvmrc').write_text('18\n')
        assert _detect_node_version(str(tmp_path), {}) == '18'

    def test_reads_version_from_node_version_file(self, tmp_path):
        (tmp_path / '.node-version').write_text('v16.20.0')
        assert _detect_node_version(str(tmp_path), {}) == '16'

    def test_reads_version_from_engines_field(self, tmp_path):
        pkg = {'engines': {'node': '>=18.0.0'}}
        assert _detect_node_version(str(tmp_path), pkg) == '18'

    def test_nvmrc_beats_engines(self, tmp_path):
        (tmp_path / '.nvmrc').write_text('20')
        pkg = {'engines': {'node': '16'}}
        assert _detect_node_version(str(tmp_path), pkg) == '20'

    def test_returns_none_when_not_specified(self, tmp_path):
        assert _detect_node_version(str(tmp_path), {}) is None


# ─────────────────────────────────────────────────────────────────────────────
# TestEntryPointDetection
# ─────────────────────────────────────────────────────────────────────────────

class TestEntryPointDetection:
    def test_react_tsx_entry(self, react_vite_root):
        assert _detect_entry_point(str(react_vite_root), 'react', 'typescript') == 'src/main.tsx'

    def test_angular_main_ts(self, angular_root):
        assert _detect_entry_point(str(angular_root), 'angular', 'typescript') == 'src/main.ts'

    def test_next_app_layout(self, next_root):
        # next_root has app/layout.tsx
        assert _detect_entry_point(str(next_root), 'next', 'typescript') == 'app/layout.tsx'

    def test_returns_none_when_no_entry_found(self, tmp_path):
        assert _detect_entry_point(str(tmp_path), 'react', 'typescript') is None


# ─────────────────────────────────────────────────────────────────────────────
# TestLibraryDetection
# ─────────────────────────────────────────────────────────────────────────────

class TestLibraryDetection:
    def test_detects_mui(self, tmp_path):
        _write_pkg(tmp_path, deps={'react': '^18.0.0', '@mui/material': '^5.0.0'})
        assert 'mui' in scan_frontend_project(str(tmp_path))['ui_libs']

    def test_detects_tailwindcss(self, tmp_path):
        _write_pkg(tmp_path, deps={'react': '^18.0.0'},
                   dev_deps={'tailwindcss': '^3.0.0'})
        assert 'tailwindcss' in scan_frontend_project(str(tmp_path))['ui_libs']

    def test_detects_zustand_state_lib(self, tmp_path):
        _write_pkg(tmp_path, deps={'react': '^18.0.0', 'zustand': '^4.0.0'})
        assert 'zustand' in scan_frontend_project(str(tmp_path))['state_libs']

    def test_detects_redux_toolkit(self, tmp_path):
        _write_pkg(tmp_path, deps={'react': '^18.0.0'},
                   dev_deps={'@reduxjs/toolkit': '^2.0.0'})
        assert 'redux-toolkit' in scan_frontend_project(str(tmp_path))['state_libs']

    def test_no_libs_when_none_present(self, tmp_path):
        _write_pkg(tmp_path, deps={'react': '^18.0.0'})
        result = scan_frontend_project(str(tmp_path))
        assert result['ui_libs'] == []
        assert result['state_libs'] == []


# ─────────────────────────────────────────────────────────────────────────────
# TestScanFrontendProject — result shape & integration
# ─────────────────────────────────────────────────────────────────────────────

class TestScanFrontendProject:
    def test_result_has_all_required_keys(self, react_vite_root):
        result = scan_frontend_project(str(react_vite_root))
        for key in ('root', 'framework', 'build_tool', 'language',
                    'dev_port', 'api_proxy', 'entry_point',
                    'node_version', 'ui_libs', 'state_libs', 'scripts'):
            assert key in result, f"Missing key: {key}"

    def test_scripts_are_returned(self, react_vite_root):
        result = scan_frontend_project(str(react_vite_root))
        assert 'dev' in result['scripts']
        assert 'build' in result['scripts']

    def test_root_path_in_result(self, react_vite_root):
        result = scan_frontend_project(str(react_vite_root))
        assert result['root'] == str(react_vite_root)

    def test_node_version_from_nvmrc(self, react_vite_root):
        (react_vite_root / '.nvmrc').write_text('20\n')
        assert scan_frontend_project(str(react_vite_root))['node_version'] == '20'

    def test_entry_point_react_tsx(self, react_vite_root):
        assert scan_frontend_project(str(react_vite_root))['entry_point'] == 'src/main.tsx'

    def test_entry_point_next_layout(self, next_root):
        assert scan_frontend_project(str(next_root))['entry_point'] == 'app/layout.tsx'

    def test_entry_point_angular_main(self, angular_root):
        assert scan_frontend_project(str(angular_root))['entry_point'] == 'src/main.ts'
