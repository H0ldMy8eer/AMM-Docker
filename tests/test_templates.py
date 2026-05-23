import re
import os
import pytest
from jinja2 import Environment, FileSystemLoader

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), '..', 'templates')


@pytest.fixture
def jinja_env():
    return Environment(loader=FileSystemLoader(TEMPLATES_DIR))


@pytest.fixture
def two_services():
    return [
        {'name': 'users', 'type': 'service'},
        {'name': 'products', 'type': 'service'},
    ]


class TestNginxTemplate:
    def test_each_service_gets_location_block(self, jinja_env, two_services):
        content = jinja_env.get_template("nginx.conf.jinja2").render(services=two_services)
        assert "location /users" in content
        assert "location /products" in content

    def test_each_service_proxied_to_correct_upstream(self, jinja_env, two_services):
        content = jinja_env.get_template("nginx.conf.jinja2").render(services=two_services)
        assert "proxy_pass http://users:5000" in content
        assert "proxy_pass http://products:5000" in content

    def test_redirect_goes_to_first_service(self, jinja_env, two_services):
        content = jinja_env.get_template("nginx.conf.jinja2").render(services=two_services)
        assert "return 302 /users" in content

    def test_redirect_follows_first_service_name(self, jinja_env):
        services = [
            {'name': 'inventory', 'type': 'service'},
            {'name': 'orders', 'type': 'service'},
        ]
        content = jinja_env.get_template("nginx.conf.jinja2").render(services=services)
        assert "return 302 /inventory" in content
        assert "return 302 /orders" not in content

    def test_no_hardcoded_products_redirect(self, jinja_env):
        services = [{'name': 'catalog', 'type': 'service'}]
        content = jinja_env.get_template("nginx.conf.jinja2").render(services=services)
        assert "return 302 /products" not in content

    def test_no_redirect_when_services_empty(self, jinja_env):
        content = jinja_env.get_template("nginx.conf.jinja2").render(services=[])
        assert "return 302" not in content

    def test_proxy_headers_present(self, jinja_env, two_services):
        content = jinja_env.get_template("nginx.conf.jinja2").render(services=two_services)
        assert "X-Real-IP" in content
        assert "X-Forwarded-For" in content
        assert "X-Forwarded-Proto" in content

    def test_timeout_settings_present(self, jinja_env, two_services):
        content = jinja_env.get_template("nginx.conf.jinja2").render(services=two_services)
        assert "proxy_connect_timeout" in content
        assert "proxy_read_timeout" in content

    def test_single_service_renders_correctly(self, jinja_env):
        services = [{'name': 'api', 'type': 'service'}]
        content = jinja_env.get_template("nginx.conf.jinja2").render(services=services)
        assert "location /api" in content
        assert "return 302 /api" in content


class TestDockerComposeTemplate:
    def test_no_hardcoded_password(self, jinja_env, two_services):
        content = jinja_env.get_template("docker-compose.jinja2").render(services=two_services)
        assert "POSTGRES_PASSWORD: password" not in content
        assert "POSTGRES_PASSWORD=password" not in content

    def test_uses_env_var_syntax_for_postgres(self, jinja_env, two_services):
        content = jinja_env.get_template("docker-compose.jinja2").render(services=two_services)
        assert "${POSTGRES_PASSWORD}" in content
        assert "${POSTGRES_USER}" in content
        assert "${POSTGRES_DB}" in content

    def test_database_url_uses_env_vars(self, jinja_env, two_services):
        content = jinja_env.get_template("docker-compose.jinja2").render(services=two_services)
        assert "${POSTGRES_USER}:${POSTGRES_PASSWORD}" in content

    def test_each_service_has_build_context(self, jinja_env, two_services):
        content = jinja_env.get_template("docker-compose.jinja2").render(services=two_services)
        assert "context: ./users" in content
        assert "context: ./products" in content

    def test_gateway_service_present(self, jinja_env, two_services):
        content = jinja_env.get_template("docker-compose.jinja2").render(services=two_services)
        assert "gateway:" in content
        assert "nginx:alpine" in content

    def test_gateway_depends_on_all_services(self, jinja_env, two_services):
        content = jinja_env.get_template("docker-compose.jinja2").render(services=two_services)
        gateway_section = content[content.index("gateway:"):]
        depends_section = gateway_section[:gateway_section.index("networks:")]
        assert "users" in depends_section
        assert "products" in depends_section

    def test_ports_no_collision_for_10_services(self, jinja_env):
        services = [{'name': f'svc{i:02d}', 'type': 'service'} for i in range(1, 11)]
        content = jinja_env.get_template("docker-compose.jinja2").render(services=services)
        ports = re.findall(r'"(\d+):5000"', content)
        assert len(ports) == 10
        assert len(ports) == len(set(ports)), "Обнаружен конфликт портов"

    def test_port_10_is_5010_not_50010(self, jinja_env):
        services = [{'name': f'svc{i:02d}', 'type': 'service'} for i in range(1, 11)]
        content = jinja_env.get_template("docker-compose.jinja2").render(services=services)
        assert '"5010:5000"' in content
        assert '"50010:5000"' not in content

    def test_postgres_healthcheck_present(self, jinja_env, two_services):
        content = jinja_env.get_template("docker-compose.jinja2").render(services=two_services)
        assert "healthcheck" in content
        assert "pg_isready" in content

    def test_services_depend_on_healthy_postgres(self, jinja_env, two_services):
        content = jinja_env.get_template("docker-compose.jinja2").render(services=two_services)
        assert "service_healthy" in content
