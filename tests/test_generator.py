import re
import string
import pytest
import generator


class TestGeneratePassword:
    def test_default_length(self):
        assert len(generator.generate_password()) == 24

    def test_custom_length(self):
        assert len(generator.generate_password(48)) == 48

    def test_only_alphanumeric_chars(self):
        allowed = set(string.ascii_letters + string.digits)
        pwd = generator.generate_password(200)
        assert set(pwd).issubset(allowed)

    def test_unique_on_each_call(self):
        passwords = {generator.generate_password() for _ in range(20)}
        assert len(passwords) > 1


class TestSanitizeModels:
    def test_removes_foreign_key_argument(self, tmp_path):
        f = tmp_path / "models.py"
        f.write_text(
            "id = db.Column(db.Integer, primary_key=True)\n"
            "order_id = db.Column(db.Integer, db.ForeignKey('orders.id'))\n"
        )
        generator.sanitize_models(str(tmp_path))
        content = f.read_text()
        assert "db.ForeignKey" not in content
        assert "db.Column(db.Integer, primary_key=True)" in content

    def test_removes_relationship_line(self, tmp_path):
        f = tmp_path / "models.py"
        f.write_text(
            "id = db.Column(db.Integer, primary_key=True)\n"
            "orders = db.relationship('Order', backref='user')\n"
        )
        generator.sanitize_models(str(tmp_path))
        content = f.read_text()
        assert "db.relationship" not in content
        assert "db.Column" in content

    def test_unchanged_when_no_orm_relations(self, tmp_path):
        f = tmp_path / "views.py"
        original = "from flask import Blueprint\nbp = Blueprint('x', __name__)\n"
        f.write_text(original)
        generator.sanitize_models(str(tmp_path))
        assert f.read_text() == original

    def test_processes_nested_directories(self, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        f = sub / "models.py"
        f.write_text("fk = db.Column(db.Integer, db.ForeignKey('other.id'))\n")
        generator.sanitize_models(str(tmp_path))
        assert "db.ForeignKey" not in f.read_text()


class TestRunGeneration:
    def test_creates_env_file(self, monolith_dir, tmp_path):
        out = tmp_path / "output"
        generator.run_generation(str(monolith_dir), str(out))
        assert (out / ".env").exists()

    def test_env_password_is_not_literal_password(self, monolith_dir, tmp_path):
        out = tmp_path / "output"
        generator.run_generation(str(monolith_dir), str(out))
        for line in (out / ".env").read_text().splitlines():
            if line.startswith("POSTGRES_PASSWORD="):
                assert line.split("=", 1)[1] != "password"

    def test_env_password_is_unique_per_run(self, monolith_dir, tmp_path):
        def get_password(path):
            for line in (path / ".env").read_text().splitlines():
                if line.startswith("POSTGRES_PASSWORD="):
                    return line.split("=", 1)[1]

        out1, out2 = tmp_path / "out1", tmp_path / "out2"
        generator.run_generation(str(monolith_dir), str(out1))
        generator.run_generation(str(monolith_dir), str(out2))
        assert get_password(out1) != get_password(out2)

    def test_creates_env_example(self, monolith_dir, tmp_path):
        out = tmp_path / "output"
        generator.run_generation(str(monolith_dir), str(out))
        assert (out / ".env.example").exists()

    def test_env_example_has_no_real_password(self, monolith_dir, tmp_path):
        out = tmp_path / "output"
        generator.run_generation(str(monolith_dir), str(out))
        content = (out / ".env.example").read_text()
        assert "POSTGRES_PASSWORD" in content
        for line in content.splitlines():
            if line.startswith("POSTGRES_PASSWORD="):
                value = line.split("=", 1)[1]
                assert len(value) < 16 or not value.isalnum(), \
                    ".env.example should contain a placeholder, not a real password"

    def test_creates_nginx_conf(self, monolith_dir, tmp_path):
        out = tmp_path / "output"
        generator.run_generation(str(monolith_dir), str(out))
        assert (out / "nginx" / "nginx.conf").exists()

    def test_creates_docker_compose(self, monolith_dir, tmp_path):
        out = tmp_path / "output"
        generator.run_generation(str(monolith_dir), str(out))
        assert (out / "docker-compose.yaml").exists()

    def test_compose_uses_env_vars_not_plaintext(self, monolith_dir, tmp_path):
        out = tmp_path / "output"
        generator.run_generation(str(monolith_dir), str(out))
        content = (out / "docker-compose.yaml").read_text()
        assert "${POSTGRES_PASSWORD}" in content
        assert "POSTGRES_PASSWORD: password" not in content

    def test_compose_database_url_uses_env_vars(self, monolith_dir, tmp_path):
        out = tmp_path / "output"
        generator.run_generation(str(monolith_dir), str(out))
        content = (out / "docker-compose.yaml").read_text()
        assert "${POSTGRES_USER}:${POSTGRES_PASSWORD}" in content

    def test_compose_ports_no_collision(self, tmp_path):
        for i in range(1, 11):
            svc = tmp_path / f"service{i:02d}"
            svc.mkdir()
            (svc / "__init__.py").write_text("")
            (svc / "views.py").write_text(f"# service {i}")

        out = tmp_path / "output"
        generator.run_generation(str(tmp_path), str(out))
        content = (out / "docker-compose.yaml").read_text()
        ports = re.findall(r'"(\d+):5000"', content)
        assert len(ports) == len(set(ports)), "Обнаружен конфликт портов"

    def test_compose_ports_correct_for_10_services(self, tmp_path):
        for i in range(1, 11):
            svc = tmp_path / f"svc{i:02d}"
            svc.mkdir()
            (svc / "__init__.py").write_text("")
            (svc / "views.py").write_text(f"# service {i}")

        out = tmp_path / "output"
        generator.run_generation(str(tmp_path), str(out))
        content = (out / "docker-compose.yaml").read_text()
        assert "50010" not in content, "Старый сломанный формат порта 50010"
        assert "5010" in content, "10-й сервис должен получить порт 5010"

    def test_service_dirs_created(self, monolith_dir, tmp_path):
        out = tmp_path / "output"
        generator.run_generation(str(monolith_dir), str(out))
        assert (out / "users").is_dir()
        assert (out / "products").is_dir()

    def test_invalid_source_path_does_not_crash(self, tmp_path):
        out = tmp_path / "output"
        generator.run_generation("/nonexistent/path", str(out))

    def test_nginx_redirect_is_dynamic_not_hardcoded(self, tmp_path):
        # Сервисы намеренно без имени 'products' — редирект должен вести на первый сервис
        alpha = tmp_path / "alpha_svc"
        alpha.mkdir()
        (alpha / "__init__.py").write_text("")
        (alpha / "views.py").write_text("# alpha")

        beta = tmp_path / "beta_svc"
        beta.mkdir()
        (beta / "__init__.py").write_text("")
        (beta / "views.py").write_text("# beta")

        out = tmp_path / "output"
        generator.run_generation(str(tmp_path), str(out))
        content = (out / "nginx" / "nginx.conf").read_text()
        assert "return 302 /products" not in content
        assert "return 302 /alpha_svc" in content
