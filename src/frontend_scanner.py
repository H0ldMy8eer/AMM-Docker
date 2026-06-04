"""
frontend_scanner.py — Frontend project scanner for AMM-Docker.

Analyses package.json, build-tool configs (vite.config, angular.json,
vue.config, next.config), and source structure to profile a frontend
application. No third-party libraries required.
"""
import os
import re
import json

# ─────────────────────────────────────────────────────────────────────────────
# Detection maps
# ─────────────────────────────────────────────────────────────────────────────

# Ordered: first match wins. More specific frameworks before generic ones.
_FRAMEWORK_MAP = [
    ('next',               'next'),
    ('nuxt',               'nuxt'),
    ('@angular/core',      'angular'),
    ('svelte',             'svelte'),
    ('vue',                'vue'),
    ('react',              'react'),
]

# Ordered: first match wins.
_BUILD_TOOL_MAP = [
    ('vite',                          'vite'),
    ('@vitejs/plugin-react',           'vite'),
    ('@vitejs/plugin-react-swc',       'vite'),
    ('@vitejs/plugin-vue',             'vite'),
    ('react-scripts',                  'cra'),
    ('@angular-devkit/build-angular',  'angular-cli'),
    ('parcel',                         'parcel'),
    ('webpack',                        'webpack'),
    ('webpack-cli',                    'webpack'),
    ('esbuild',                        'esbuild'),
]

# npm package → human-readable UI-library label
_UI_LIBS_MAP = {
    'tailwindcss':       'tailwindcss',
    '@mui/material':     'mui',
    '@emotion/react':    'emotion',
    'antd':              'ant-design',
    '@chakra-ui/react':  'chakra-ui',
    'bootstrap':         'bootstrap',
    'react-bootstrap':   'react-bootstrap',
    'vuetify':           'vuetify',
    'element-plus':      'element-plus',
    'primevue':          'primevue',
    '@headlessui/react': 'headlessui',
    '@ionic/react':      'ionic',
    '@ionic/vue':        'ionic',
    'framer-motion':     'framer-motion',
    'styled-components': 'styled-components',
}

# npm package → state-management label
_STATE_LIBS_MAP = {
    '@reduxjs/toolkit': 'redux-toolkit',
    'redux':            'redux',
    'zustand':          'zustand',
    'jotai':            'jotai',
    'recoil':           'recoil',
    'mobx':             'mobx',
    'pinia':            'pinia',
    'vuex':             'vuex',
    '@ngrx/store':      'ngrx',
}

# Default dev ports when no config file overrides them
_FRAMEWORK_DEFAULT_PORTS = {
    'react':   3000,
    'next':    3000,
    'vue':     5173,   # Vite default; Vue CLI default was 8080
    'nuxt':    3000,
    'angular': 4200,
    'svelte':  5173,
    'unknown': 3000,
}

# ─────────────────────────────────────────────────────────────────────────────
# Regex patterns
# ─────────────────────────────────────────────────────────────────────────────

# port: 3000  (inside JS/TS config files)
_CFG_PORT_RE    = re.compile(r'\bport\s*:\s*(\d+)')

# 'target': 'http://...'  (Vite / Vue CLI proxy blocks)
_PROXY_TARGET_RE = re.compile(
    r'["\']([/][\w*/.-]*)["\']'          # proxy path key
    r'\s*:\s*\{[^}]*?'
    r'target\s*:\s*["\']([^"\']+)["\']', # target URL
    re.DOTALL,
)

# CRA simple proxy: "proxy": "http://localhost:8080"
_CRA_PROXY_RE   = re.compile(r'"proxy"\s*:\s*"([^"]+)"')

# Port flag in npm scripts: --port 3001 or -p 3001
_SCRIPT_PORT_RE = re.compile(r'(?:--port|-p)\s+(\d+)')

# Node version from .nvmrc / .node-version  (e.g. "v20.11.0" or "20")
_NODE_VER_RE    = re.compile(r'v?(\d+)')

# Next.js rewrites destination
_NEXT_DEST_RE   = re.compile(r'destination\s*:\s*["`\'](https?://[^"`\']+)["`\']')

# Angular proxy.conf.json: "/api": { "target": "http://..." }
_NG_PROXY_RE    = re.compile(
    r'"([/][\w*/.-]*)"\s*:\s*\{[^}]*?"target"\s*:\s*"([^"]+)"',
    re.DOTALL,
)

# ─────────────────────────────────────────────────────────────────────────────
# Build-tool / framework config parsers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_vite_config(root_path):
    """Return (dev_port, proxy_rules) from vite.config.{ts,js,mjs}."""
    for name in ('vite.config.ts', 'vite.config.js', 'vite.config.mjs'):
        fpath = os.path.join(root_path, name)
        if not os.path.isfile(fpath):
            continue
        try:
            content = open(fpath, encoding='utf-8').read()
        except Exception:
            continue

        port = None
        m = _CFG_PORT_RE.search(content)
        if m:
            port = int(m.group(1))

        proxies = [
            {'from': m.group(1), 'to': m.group(2)}
            for m in _PROXY_TARGET_RE.finditer(content)
        ]
        return port, proxies
    return None, []


def _parse_vue_config(root_path):
    """Return (dev_port, proxy_rules) from vue.config.{js,ts}."""
    for name in ('vue.config.js', 'vue.config.ts'):
        fpath = os.path.join(root_path, name)
        if not os.path.isfile(fpath):
            continue
        try:
            content = open(fpath, encoding='utf-8').read()
        except Exception:
            continue

        port = None
        m = _CFG_PORT_RE.search(content)
        if m:
            port = int(m.group(1))

        proxies = [
            {'from': m.group(1), 'to': m.group(2)}
            for m in _PROXY_TARGET_RE.finditer(content)
        ]
        return port, proxies
    return None, []


def _parse_next_config(root_path):
    """
    Return (dev_port, proxy_rules) from next.config.{js,mjs,ts}.

    Next.js proxying is done via rewrites(); we extract destination URLs.
    Port is usually taken from npm scripts (handled in _extract_port_from_scripts).
    """
    for name in ('next.config.js', 'next.config.mjs', 'next.config.ts'):
        fpath = os.path.join(root_path, name)
        if not os.path.isfile(fpath):
            continue
        try:
            content = open(fpath, encoding='utf-8').read()
        except Exception:
            continue

        proxies = []
        if 'rewrites' in content:
            for m in _NEXT_DEST_RE.finditer(content):
                proxies.append({'from': '/api', 'to': m.group(1)})
        return None, proxies
    return None, []


def _parse_angular_json(root_path):
    """Return (dev_port, proxy_rules) from angular.json and proxy.conf.json."""
    port    = None
    proxies = []

    ang_path = os.path.join(root_path, 'angular.json')
    if os.path.isfile(ang_path):
        try:
            ang = json.load(open(ang_path, encoding='utf-8'))
            projects = ang.get('projects', {})
            for proj in projects.values():
                serve = (proj.get('architect') or proj.get('targets', {})).get('serve', {})
                # Port can be in defaultConfiguration options or options directly
                opts = serve.get('options', {})
                if 'port' in opts:
                    port = int(opts['port'])
                # Find proxyConfig path
                proxy_cfg = opts.get('proxyConfig') or ''
                if not proxy_cfg:
                    for cfg_opts in serve.get('configurations', {}).values():
                        proxy_cfg = cfg_opts.get('proxyConfig', '')
                        if proxy_cfg:
                            break
                if proxy_cfg:
                    proxy_path = os.path.join(root_path, proxy_cfg)
                    if os.path.isfile(proxy_path):
                        try:
                            proxy_raw = json.load(open(proxy_path, encoding='utf-8'))
                            for path_key, cfg in proxy_raw.items():
                                if 'target' in cfg:
                                    proxies.append({'from': path_key, 'to': cfg['target']})
                        except Exception:
                            pass
        except Exception:
            pass

    # Fallback: look for any proxy.conf.json next to angular.json
    if not proxies:
        for proxy_name in ('proxy.conf.json', 'proxy.config.json'):
            proxy_path = os.path.join(root_path, proxy_name)
            if os.path.isfile(proxy_path):
                try:
                    content = open(proxy_path, encoding='utf-8').read()
                    for m in _NG_PROXY_RE.finditer(content):
                        proxies.append({'from': m.group(1), 'to': m.group(2)})
                except Exception:
                    pass
                break

    return port, proxies


def _extract_port_from_scripts(scripts):
    """
    Extract dev server port from npm scripts.

    Checks 'dev', 'start', 'serve' for flags like --port 3001 or -p 3001.
    """
    for key in ('dev', 'start', 'serve'):
        cmd = scripts.get(key, '')
        m = _SCRIPT_PORT_RE.search(cmd)
        if m:
            return int(m.group(1))
    return None


def _extract_cra_proxy(root_path, pkg):
    """
    Return proxy rules from CRA-style 'proxy' field in package.json,
    or from src/setupProxy.js if it exists.
    """
    proxies = []
    raw = pkg.get('proxy')
    if isinstance(raw, str) and raw.startswith('http'):
        proxies.append({'from': '/api', 'to': raw})
    elif isinstance(raw, dict):
        for path_key, cfg in raw.items():
            if isinstance(cfg, dict) and 'target' in cfg:
                proxies.append({'from': path_key, 'to': cfg['target']})
    return proxies

# ─────────────────────────────────────────────────────────────────────────────
# Source-structure helpers
# ─────────────────────────────────────────────────────────────────────────────

def _detect_language(root_path, pkg):
    """Return 'typescript' if the project uses TS, else 'javascript'."""
    if os.path.isfile(os.path.join(root_path, 'tsconfig.json')):
        return 'typescript'
    all_deps = {**pkg.get('dependencies', {}), **pkg.get('devDependencies', {})}
    if 'typescript' in all_deps:
        return 'typescript'
    src = os.path.join(root_path, 'src')
    if os.path.isdir(src):
        for fname in os.listdir(src):
            if fname.endswith(('.ts', '.tsx')):
                return 'typescript'
    return 'javascript'


def _detect_node_version(root_path, pkg):
    """
    Return the Node major version as a string, or None if not specified.

    Priority: .nvmrc → .node-version → engines.node in package.json.
    """
    for fname in ('.nvmrc', '.node-version'):
        fpath = os.path.join(root_path, fname)
        if os.path.isfile(fpath):
            try:
                text = open(fpath, encoding='utf-8').read().strip()
                m = _NODE_VER_RE.match(text)
                if m:
                    return m.group(1)
            except Exception:
                pass

    engines_node = pkg.get('engines', {}).get('node', '')
    m = _NODE_VER_RE.search(engines_node)
    if m:
        return m.group(1)
    return None


def _detect_entry_point(root_path, framework, language):
    """
    Return the relative path to the app's main entry file, or None.
    """
    ext_ts = '.tsx' if framework == 'react' else '.ts'
    ext_js = '.jsx' if framework == 'react' else '.js'

    candidates = {
        'next':    ['app/layout.tsx', 'app/layout.js', 'pages/_app.tsx', 'pages/_app.js'],
        'nuxt':    ['app.vue', 'nuxt.config.ts', 'nuxt.config.js'],
        'angular': ['src/main.ts'],
        'svelte':  ['src/main.ts', 'src/main.js', 'src/App.svelte'],
        'vue':     ['src/main.ts', 'src/main.js'],
        'react':   [f'src/main{ext_ts}', f'src/main{ext_js}',
                    'src/index.tsx', 'src/index.jsx', 'src/index.js'],
        'unknown': ['src/main.ts', 'src/main.js', 'src/index.ts', 'src/index.js'],
    }

    for rel in candidates.get(framework, candidates['unknown']):
        if os.path.isfile(os.path.join(root_path, rel)):
            return rel
    return None


def _collect_libs(all_deps, lib_map):
    """Return a sorted list of detected library labels from all_deps."""
    return sorted({label for pkg, label in lib_map.items() if pkg in all_deps})


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def scan_frontend_project(root_path):
    """
    Scan a frontend project and return its full profile.

    Returns:
        {
            'root':        str,
            'framework':   'react'|'vue'|'angular'|'svelte'|'next'|'nuxt'|'unknown',
            'build_tool':  'vite'|'cra'|'angular-cli'|'webpack'|'parcel'|'unknown',
            'language':    'typescript'|'javascript',
            'dev_port':    int,
            'api_proxy':   [{'from': str, 'to': str}, ...],
            'entry_point': str | None,
            'node_version': str | None,
            'ui_libs':     [str, ...],
            'state_libs':  [str, ...],
            'scripts':     {name: command, ...},
        }
    """
    print(f"🌐 [FRONTEND-SCANNER] Начинаю анализ: {root_path}")

    # ── package.json ──────────────────────────────────────────────────────────
    pkg_path = os.path.join(root_path, 'package.json')
    try:
        pkg = json.load(open(pkg_path, encoding='utf-8'))
    except Exception:
        pkg = {}

    all_deps = {**pkg.get('dependencies', {}), **pkg.get('devDependencies', {})}
    scripts  = pkg.get('scripts', {})

    # ── Framework & build tool ────────────────────────────────────────────────
    framework = 'unknown'
    for pkg_name, fw in _FRAMEWORK_MAP:
        if pkg_name in all_deps:
            framework = fw
            break

    build_tool = 'unknown'
    for pkg_name, bt in _BUILD_TOOL_MAP:
        if pkg_name in all_deps:
            build_tool = bt
            break

    # Next.js has built-in build tooling (Turbopack/Webpack)
    if framework == 'next' and build_tool == 'unknown':
        build_tool = 'next'
    # Angular always uses its own CLI
    if framework == 'angular':
        build_tool = 'angular-cli'

    print(f"   🌐 [FRONTEND-SCANNER] framework={framework}  build_tool={build_tool}")

    # ── Dev port & proxy ──────────────────────────────────────────────────────
    port    = None
    proxies = []

    if build_tool == 'vite':
        port, proxies = _parse_vite_config(root_path)
    elif framework == 'vue' and build_tool != 'vite':
        port, proxies = _parse_vue_config(root_path)
    elif framework == 'next':
        _, proxies = _parse_next_config(root_path)
    elif framework == 'angular':
        port, proxies = _parse_angular_json(root_path)
    elif build_tool == 'cra':
        proxies = _extract_cra_proxy(root_path, pkg)

    # Fallback: check npm scripts for --port flag
    if port is None:
        port = _extract_port_from_scripts(scripts)

    # Final fallback: framework default
    if port is None:
        port = _FRAMEWORK_DEFAULT_PORTS.get(framework, 3000)

    print(f"   🌐 [FRONTEND-SCANNER] dev_port={port}")
    if proxies:
        for p in proxies:
            print(f"   🌐 [FRONTEND-SCANNER] proxy: {p['from']} → {p['to']}")

    # ── Language, Node version, entry point ───────────────────────────────────
    language     = _detect_language(root_path, pkg)
    node_version = _detect_node_version(root_path, pkg)
    entry_point  = _detect_entry_point(root_path, framework, language)

    print(f"   🌐 [FRONTEND-SCANNER] language={language}  node={node_version}"
          f"  entry={entry_point}")

    # ── UI & state libraries ──────────────────────────────────────────────────
    ui_libs    = _collect_libs(all_deps, _UI_LIBS_MAP)
    state_libs = _collect_libs(all_deps, _STATE_LIBS_MAP)

    if ui_libs:
        print(f"   🌐 [FRONTEND-SCANNER] ui_libs={ui_libs}")
    if state_libs:
        print(f"   🌐 [FRONTEND-SCANNER] state_libs={state_libs}")

    return {
        'root':         root_path,
        'framework':    framework,
        'build_tool':   build_tool,
        'language':     language,
        'dev_port':     port,
        'api_proxy':    proxies,
        'entry_point':  entry_point,
        'node_version': node_version,
        'ui_libs':      ui_libs,
        'state_libs':   state_libs,
        'scripts':      scripts,
    }


if __name__ == '__main__':
    pass
