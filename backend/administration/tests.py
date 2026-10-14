from django.test import TestCase

from .models import Role, StaffAccount

PASSWORD = "ChangeMe123!"


def make_account(username, role_name, permissions, is_active=True):
    role, _ = Role.objects.get_or_create(name=role_name, defaults={"permissions": permissions})
    account = StaffAccount(
        full_name=username.title(),
        email=f"{username}@gym.com",
        username=username,
        job_title=StaffAccount.JobTitle.RECEPTIONIST,
        role=role,
        is_active=is_active,
    )
    account.set_password(PASSWORD)
    account.save()
    return account


# User story (SCRUM-117): "As a staff member, I want the system to block pages
# and actions outside my role's permissions, so that sensitive data stays
# restricted."
class RolePermissionEnforcementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        make_account("admin", "System Administrator", ["manage_staff_accounts", "manage_roles", "manage_members"])
        make_account("recep", "Receptionist", ["manage_members"])
        make_account("mkt", "Marketing Staff", ["manage_marketing_campaigns"])
        make_account("rolesonly", "Roles Only", ["manage_roles"])
        make_account("gone", "Receptionist", ["manage_members"], is_active=False)

    def login(self, username):
        res = self.client.post("/api/auth/login", {"username": username, "password": PASSWORD}, content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content)

    # --- not logged in -> 401 on every protected endpoint ---
    def test_anonymous_requests_are_rejected(self):
        for path in ["/api/staff", "/api/staff/1", "/api/roles", "/api/roles/1", "/api/permissions", "/api/members"]:
            self.assertEqual(self.client.get(path).status_code, 401, path)
        self.assertEqual(self.client.post("/api/members", {}, content_type="application/json").status_code, 401)
        self.assertEqual(self.client.post("/api/roles", {}, content_type="application/json").status_code, 401)

    # --- logged in, wrong role -> 403 ---
    def test_receptionist_cannot_touch_admin_endpoints(self):
        self.login("recep")
        for path in ["/api/staff", "/api/roles", "/api/permissions"]:
            self.assertEqual(self.client.get(path).status_code, 403, path)
        res = self.client.post("/api/roles", {"name": "X", "permissions": []}, content_type="application/json")
        self.assertEqual(res.status_code, 403)
        res = self.client.patch("/api/staff/1", {"isActive": False}, content_type="application/json")
        self.assertEqual(res.status_code, 403)

    def test_receptionist_can_use_member_directory(self):
        self.login("recep")
        self.assertEqual(self.client.get("/api/members").status_code, 200)

    def test_marketing_staff_cannot_read_member_directory(self):
        self.login("mkt")
        self.assertEqual(self.client.get("/api/members").status_code, 403)
        res = self.client.post("/api/members", {"name": "A"}, content_type="application/json")
        self.assertEqual(res.status_code, 403)

    def test_roles_can_be_read_with_either_admin_permission_but_written_only_with_manage_roles(self):
        self.login("admin")
        self.assertEqual(self.client.get("/api/roles").status_code, 200)
        self.client.post("/api/auth/logout")
        self.login("rolesonly")
        self.assertEqual(self.client.get("/api/roles").status_code, 200)
        self.assertEqual(self.client.get("/api/staff").status_code, 403)

    def test_admin_keeps_access(self):
        self.login("admin")
        for path in ["/api/staff", "/api/roles", "/api/permissions", "/api/members"]:
            self.assertEqual(self.client.get(path).status_code, 200, path)

    # --- permissions are checked live, not frozen at login ---
    def test_permission_change_applies_to_existing_session(self):
        self.login("recep")
        self.assertEqual(self.client.get("/api/members").status_code, 200)
        Role.objects.filter(name="Receptionist").update(permissions=[])
        self.assertEqual(self.client.get("/api/members").status_code, 403)

    def test_deactivated_account_loses_access_immediately(self):
        self.login("recep")
        StaffAccount.objects.filter(username="recep").update(is_active=False)
        self.assertEqual(self.client.get("/api/members").status_code, 401)

    def test_member_session_is_not_staff(self):
        session = self.client.session
        session["member_id"] = 1
        session.save()
        self.assertEqual(self.client.get("/api/members").status_code, 401)
        self.assertEqual(self.client.get("/api/staff").status_code, 401)

    # --- public endpoints stay public ---
    def test_public_endpoints_still_open(self):
        self.assertEqual(self.client.get("/api/members/meta").status_code, 200)
        self.assertEqual(self.client.get("/api/plans").status_code, 200)
        self.assertEqual(self.client.get("/api/health").status_code, 200)
