"""Pytest configuration and fixtures for NEPSE simulator tests."""
import os
import sys
import tempfile

# Ensure the nepse package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from nepse.app import app, db


@pytest.fixture
def app_fixture():
    """Create application for testing with an in-memory SQLite database."""
    test_app = app
    test_app.config["TESTING"] = True
    test_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    test_app.config["WTF_CSRF_ENABLED"] = False

    with test_app.app_context():
        db.create_all()
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app_fixture):
    """Flask test client."""
    return app_fixture.test_client()


@pytest.fixture
def runner(app_fixture):
    """Flask CLI runner."""
    return app_fixture.test_cli_runner()


@pytest.fixture
def app_context(app_fixture):
    """Application context."""
    with app_fixture.app_context():
        yield
