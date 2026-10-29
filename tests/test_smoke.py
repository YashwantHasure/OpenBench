import os
import tempfile
import unittest

os.environ["SEED_DEMO"] = "false"
from app import app, db, User, Resource
from werkzeug.security import generate_password_hash

class OpenBenchSmokeTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        app.config.update(
            TESTING=True,
            WTF_CSRF_ENABLED=False,
            SQLALCHEMY_DATABASE_URI="sqlite:///" + os.path.join(self.tempdir.name, "test.db"),
            SECRET_KEY="test-secret"
        )
        with app.app_context():
            db.engine.dispose()
            db.drop_all()
            db.create_all()
            owner = User(name="Test Owner", email="owner@test.local", password_hash=generate_password_hash("OwnerPass123!"), role="owner")
            renter = User(name="Test Renter", email="renter@test.local", password_hash=generate_password_hash("RenterPass123!"), role="renter")
            db.session.add_all([owner, renter])
            db.session.flush()
            db.session.add(Resource(owner_id=owner.id, name="Test Camera", category="Events & Media", description="Test resource", location="Test City", price=10, price_unit="day"))
            db.session.commit()
        self.client = app.test_client()

    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.tempdir.cleanup()

    def test_home_page(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"OpenBench", response.data)

    def test_login_and_dashboard(self):
        response = self.client.post("/login", data={"email":"renter@test.local", "password":"OwnerPass123!"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)

    def test_owner_route_requires_login(self):
        response = self.client.get("/resources/new")
        self.assertIn(response.status_code, (302, 401))

if __name__ == "__main__":
    unittest.main()
