"""
COEN 448 Assignment 2 - Task 3: Integration Tests
Tests TC_01 through TC_04 as defined in Task 2.

Run with: python -m pytest tests/test_integration_a2.py -v
(Services must already be running via docker-compose on VM1, RabbitMQ on VM2)
"""

import os
import time
import uuid
import pytest
import requests
import pymongo
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def api_url():
    """Kong API Gateway base URL."""
    return "http://localhost:8000"


@pytest.fixture(scope="module")
def mongo():
    """MongoDB Atlas connection. Yields (users_collection, orders_collection)."""
    client = pymongo.MongoClient(os.getenv("MONGO_URI"))
    db = client[os.getenv("DATABASE_NAME", "aware_microservices")]
    yield db["users"], db["orders"]
    client.close()


@pytest.fixture(scope="module")
def created_user(api_url):
    """Create a user for use across multiple tests. Returns the response JSON."""
    payload = {
        "firstName": "John",
        "lastName": "Doe",
        "emails": [f"tc01_{uuid.uuid4().hex[:8]}@test.com"],
        "deliveryAddress": {
            "street": "100 Sherbrooke W",
            "city": "Montreal",
            "state": "QC",
            "postalCode": "H3A1G5",
            "country": "Canada"
        }
    }
    resp = requests.post(f"{api_url}/users/", json=payload)
    assert resp.status_code == 201, f"User creation failed: {resp.text}"
    return resp.json()


@pytest.fixture(scope="module")
def created_order(api_url, created_user):
    """Create an order linked to the created_user. Returns the response JSON."""
    payload = {
        "userId": created_user["userId"],
        "items": [
            {"itemId": "ITEM001", "quantity": 2, "price": 29.99},
            {"itemId": "ITEM002", "quantity": 1, "price": 49.99}
        ],
        "userEmails": created_user["emails"],
        "deliveryAddress": created_user["deliveryAddress"],
        "orderStatus": "under process"
    }
    resp = requests.post(f"{api_url}/orders/", json=payload)
    assert resp.status_code == 201, f"Order creation failed: {resp.text}"
    return resp.json()


# ---------------------------------------------------------------------------
# TC_01: Validate User Creation and Retrieval
# Linked to Requirements: 1.1, 1.9, 3.3
# ---------------------------------------------------------------------------

class TestTC01UserCreation:
    """TC_01: Validate User Creation and Retrieval."""

    def test_create_user_returns_201(self, created_user):
        """Step 1-2: POST /users/ returns 201."""
        assert created_user is not None

    def test_create_user_has_uuid(self, created_user):
        """Step 3: Response contains a system-generated userId in UUID format."""
        user_id = created_user["userId"]
        assert user_id is not None
        # Validate UUID format (8-4-4-4-12 hex chars)
        parts = user_id.split("-")
        assert len(parts) == 5, f"userId is not UUID format: {user_id}"

    def test_create_user_fields_match(self, created_user):
        """Step 4: Response contains submitted emails and deliveryAddress."""
        assert len(created_user["emails"]) == 1
        assert "@" in created_user["emails"][0]
        assert created_user["deliveryAddress"]["city"] == "Montreal"
        assert created_user["deliveryAddress"]["postalCode"] == "H3A1G5"

    def test_user_exists_in_mongodb(self, created_user, mongo):
        """Step 5: User document exists in MongoDB and matches response."""
        users_col, _ = mongo
        db_user = users_col.find_one({"userId": created_user["userId"]})
        assert db_user is not None, "User not found in MongoDB"
        assert db_user["emails"] == created_user["emails"]
        assert db_user["deliveryAddress"]["street"] == created_user["deliveryAddress"]["street"]

    def test_duplicate_email_rejected(self, api_url, created_user):
        """Step 6: Duplicate email returns 400."""
        duplicate_payload = {
            "emails": created_user["emails"],
            "deliveryAddress": {
                "street": "200 Ste-Catherine",
                "city": "Montreal",
                "state": "QC",
                "postalCode": "H3B1A7",
                "country": "Canada"
            }
        }
        resp = requests.post(f"{api_url}/users/", json=duplicate_payload)
        assert resp.status_code == 400, f"Expected 400 for duplicate email, got {resp.status_code}"


# ---------------------------------------------------------------------------
# TC_02: Validate Order Creation with Existing User
# Linked to Requirements: 1.5, 1.6, 1.10, 3.3
# ---------------------------------------------------------------------------

class TestTC02OrderCreation:
    """TC_02: Validate Order Creation with Existing User."""

    def test_create_order_returns_201(self, created_order):
        """Step 1-2: POST /orders/ returns 201."""
        assert created_order is not None

    def test_create_order_has_order_id(self, created_order):
        """Step 3: Response contains a system-generated orderId."""
        assert created_order["orderId"] is not None
        assert len(created_order["orderId"]) > 0

    def test_create_order_fields_match(self, created_order, created_user):
        """Step 4: Response contains submitted items, userEmails, deliveryAddress, orderStatus."""
        assert len(created_order["items"]) == 2
        assert created_order["items"][0]["itemId"] == "ITEM001"
        assert created_order["items"][0]["quantity"] == 2
        assert created_order["items"][0]["price"] == 29.99
        assert created_order["userEmails"] == created_user["emails"]
        assert created_order["deliveryAddress"]["city"] == "Montreal"
        assert created_order["orderStatus"] == "under process"

    def test_get_orders_by_status(self, api_url, created_order):
        """Step 5: GET /orders/?status=under process returns the created order."""
        resp = requests.get(f"{api_url}/orders/", params={"status": "under process"})
        assert resp.status_code == 200
        orders = resp.json()
        order_ids = [o["orderId"] for o in orders]
        assert created_order["orderId"] in order_ids, "Created order not found in status query"

    def test_update_order_status(self, api_url, created_order):
        """Step 6-7: PUT /orders/{id}/status updates status to shipping."""
        order_id = created_order["orderId"]
        resp = requests.put(
            f"{api_url}/orders/{order_id}/status",
            json={"orderStatus": "shipping"}
        )
        assert resp.status_code == 200

        # Verify order appears under "shipping"
        get_resp = requests.get(f"{api_url}/orders/", params={"status": "shipping"})
        assert get_resp.status_code == 200
        orders = get_resp.json()
        order_ids = [o["orderId"] for o in orders]
        assert order_id in order_ids, "Order not found under 'shipping' status"

    def test_order_exists_in_mongodb(self, created_order, mongo):
        """Step 8: Order document exists in MongoDB and fields match."""
        _, orders_col = mongo
        db_order = orders_col.find_one({"orderId": created_order["orderId"]})
        assert db_order is not None, "Order not found in MongoDB"
        assert db_order["items"][0]["itemId"] == "ITEM001"
        assert db_order["userEmails"] == created_order["userEmails"]


# ---------------------------------------------------------------------------
# TC_03: Validate Event-Driven User Update Propagation
# Linked to Requirements: 1.2, 2.1, 2.2, 2.3, 3.1, 3.2
# ---------------------------------------------------------------------------

class TestTC03EventPropagation:
    """TC_03: Validate Event-Driven User Update Propagation."""

    def test_update_user_email_propagates_to_orders(self, api_url, created_user, created_order, mongo):
        """Steps 1-6: Update user email and verify it propagates to orders via RabbitMQ."""
        users_col, orders_col = mongo
        user_id = created_user["userId"]
        new_email = f"tc03_updated_{uuid.uuid4().hex[:8]}@test.com"

        # Update user email
        resp = requests.put(
            f"{api_url}/users/{user_id}",
            json={"emails": [new_email]}
        )
        assert resp.status_code == 200, f"User update failed: {resp.text}"

        # Verify response contains old and new data
        result = resp.json()
        assert isinstance(result, list), "Response should be a list of [old_user, new_user]"
        old_user, new_user = result[0], result[1]
        assert new_user["emails"] == [new_email]

        # Verify user updated in MongoDB
        db_user = users_col.find_one({"userId": user_id})
        assert db_user["emails"] == [new_email], "User email not updated in MongoDB"

        # Wait for RabbitMQ event propagation
        time.sleep(3)

        # Verify order updated in MongoDB
        db_order = orders_col.find_one({"orderId": created_order["orderId"]})
        assert db_order["userEmails"] == [new_email], \
            f"Order email not propagated. Expected [{new_email}], got {db_order['userEmails']}"

    def test_update_user_address_propagates_to_orders(self, api_url, created_user, created_order, mongo):
        """Steps 7-9: Update user address and verify it propagates to orders via RabbitMQ."""
        users_col, orders_col = mongo
        user_id = created_user["userId"]

        new_address = {
            "street": "500 Boulevard Rene-Levesque",
            "city": "Montreal",
            "state": "QC",
            "postalCode": "H2Z1W7",
            "country": "Canada"
        }

        # Update user address
        resp = requests.put(
            f"{api_url}/users/{user_id}",
            json={"deliveryAddress": new_address}
        )
        assert resp.status_code == 200, f"User address update failed: {resp.text}"

        # Verify user updated in MongoDB
        db_user = users_col.find_one({"userId": user_id})
        assert db_user["deliveryAddress"]["street"] == "500 Boulevard Rene-Levesque"

        # Wait for RabbitMQ event propagation
        time.sleep(3)

        # Verify order updated in MongoDB
        db_order = orders_col.find_one({"orderId": created_order["orderId"]})
        assert db_order["deliveryAddress"]["street"] == "500 Boulevard Rene-Levesque", \
            f"Order address not propagated. Got: {db_order['deliveryAddress']['street']}"


# ---------------------------------------------------------------------------
# TC_04: Validate API Gateway Routing (Strangler Pattern)
# Linked to Requirements: 1.9, 1.11, 1.12
# ---------------------------------------------------------------------------

class TestTC04GatewayRouting:
    """TC_04: Validate API Gateway Routing between v1 and v2."""

    def _rebuild_kong(self, p_value):
        """Helper: update P_VALUE, rebuild and restart Kong."""
        import subprocess

        # Update .env P_VALUE
        env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
        with open(env_path, "r") as f:
            lines = f.readlines()
        with open(env_path, "w") as f:
            for line in lines:
                if line.startswith("P_VALUE="):
                    f.write(f"P_VALUE={p_value}\n")
                else:
                    f.write(line)

        # Rebuild and restart Kong
        project_dir = os.path.join(os.path.dirname(__file__), "..")
        subprocess.run(
            ["docker-compose", "build", "kong"],
            cwd=project_dir, check=True, capture_output=True
        )
        subprocess.run(
            ["docker-compose", "up", "-d", "kong"],
            cwd=project_dir, check=True, capture_output=True
        )
        # Wait for Kong to be ready
        time.sleep(10)

    def _clear_logs(self):
        """Clear service logs."""
        import subprocess
        project_dir = os.path.join(os.path.dirname(__file__), "..")
        for svc in ["user-service-v1", "user-service-v2"]:
            subprocess.run(
                ["docker-compose", "restart", svc],
                cwd=project_dir, capture_output=True
            )
        time.sleep(5)

    def _get_logs(self, service):
        """Get logs for a service."""
        import subprocess
        project_dir = os.path.join(os.path.dirname(__file__), "..")
        result = subprocess.run(
            ["docker-compose", "logs", "--tail=50", service],
            cwd=project_dir, capture_output=True, text=True
        )
        return result.stdout

    def _send_user_requests(self, api_url, count):
        """Send N user creation requests with unique emails."""
        responses = []
        for i in range(count):
            payload = {
                "emails": [f"tc04_{uuid.uuid4().hex[:8]}@test.com"],
                "deliveryAddress": {
                    "street": "300 University St",
                    "city": "Montreal",
                    "state": "QC",
                    "postalCode": "H3A2A7",
                    "country": "Canada"
                }
            }
            resp = requests.post(f"{api_url}/users/", json=payload)
            if resp.status_code == 201:
                responses.append(resp.json())
        return responses

    def test_scenario_a_all_traffic_to_v1(self, api_url):
        """Scenario A: P_VALUE=100 -> all traffic to v1."""
        self._rebuild_kong(100)
        self._clear_logs()

        responses = self._send_user_requests(api_url, 10)
        assert len(responses) == 10, f"Expected 10 successful creations, got {len(responses)}"

        time.sleep(2)

        v1_logs = self._get_logs("user-service-v1")
        v2_logs = self._get_logs("user-service-v2")

        # Count POST requests in logs
        v1_posts = v1_logs.count("POST /users/")
        v2_posts = v2_logs.count("POST /users/")

        assert v1_posts >= 8, f"Expected most requests in v1 logs, found {v1_posts}"
        assert v2_posts == 0, f"Expected no requests in v2 logs, found {v2_posts}"

        # v1 does NOT set createdAt
        for resp in responses:
            assert resp.get("createdAt") is None, "v1 should not set createdAt"

    def test_scenario_b_all_traffic_to_v2(self, api_url):
        """Scenario B: P_VALUE=0 -> all traffic to v2."""
        self._rebuild_kong(0)
        self._clear_logs()

        responses = self._send_user_requests(api_url, 10)
        assert len(responses) == 10, f"Expected 10 successful creations, got {len(responses)}"

        time.sleep(2)

        v1_logs = self._get_logs("user-service-v1")
        v2_logs = self._get_logs("user-service-v2")

        v1_posts = v1_logs.count("POST /users/")
        v2_posts = v2_logs.count("POST /users/")

        assert v1_posts == 0, f"Expected no requests in v1 logs, found {v1_posts}"
        assert v2_posts >= 8, f"Expected most requests in v2 logs, found {v2_posts}"

        # v2 DOES set createdAt
        for resp in responses:
            assert resp.get("createdAt") is not None, "v2 should set createdAt"

    def test_scenario_c_50_50_split(self, api_url):
        """Scenario C: P_VALUE=50 -> roughly 50/50 split."""
        self._rebuild_kong(50)
        self._clear_logs()

        responses = self._send_user_requests(api_url, 20)
        assert len(responses) == 20, f"Expected 20 successful creations, got {len(responses)}"

        # Count how many have createdAt set (v2) vs not set (v1)
        v2_count = sum(1 for r in responses if r.get("createdAt") is not None)
        v1_count = len(responses) - v2_count

        # Allow generous tolerance for small sample: between 20% and 80%
        assert v1_count >= 4, f"Expected at least 4 requests to v1, got {v1_count}"
        assert v2_count >= 4, f"Expected at least 4 requests to v2, got {v2_count}"

        # Restore P_VALUE=100
        self._rebuild_kong(100)
