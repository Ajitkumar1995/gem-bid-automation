import re
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse

from apps.bids.models import BidCreationLock


class AccountRegistrationTests(TestCase):
    def test_login_page_renders_sign_in_form(self):
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sign in to your account")
        self.assertContains(response, "Forgot password?")
        self.assertContains(response, "Create an account")

    def test_registration_creates_username_from_email_and_logs_user_in(self):
        response = self.client.post(reverse("register"), {
            "email": "Tender.User@example.com",
            "password1": "Sufficiently-Strong-42!",
            "password2": "Sufficiently-Strong-42!",
        })

        self.assertRedirects(response, reverse("bid-dashboard"))
        user = get_user_model().objects.get(email="tender.user@example.com")
        self.assertEqual(user.username, "tender.user")
        self.assertTrue(user.check_password("Sufficiently-Strong-42!"))
        self.assertTrue(BidCreationLock.objects.filter(user=user).exists())
        response = self.client.get(reverse("bid-dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_login_accepts_email_and_password(self):
        get_user_model().objects.create_user(
            username="tender.user",
            email="tender.user@example.com",
            password="Sufficiently-Strong-42!",
        )

        response = self.client.post(reverse("login"), {
            "username": "TENDER.USER@example.com",
            "password": "Sufficiently-Strong-42!",
        })

        self.assertRedirects(response, reverse("bid-dashboard"))
        self.assertEqual(self.client.get(reverse("bid-dashboard")).status_code, 200)

    def test_duplicate_email_is_rejected(self):
        get_user_model().objects.create_user(
            username="tender.user",
            email="tender.user@example.com",
            password="Sufficiently-Strong-42!",
        )

        response = self.client.post(reverse("register"), {
            "email": "TENDER.USER@EXAMPLE.COM",
            "password1": "Sufficiently-Strong-42!",
            "password2": "Sufficiently-Strong-42!",
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")
        self.assertEqual(get_user_model().objects.filter(username="tender.user").count(), 1)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_password_reset_email_can_set_a_new_password(self):
        user = get_user_model().objects.create_user(
            username="tender.user",
            email="tender.user@example.com",
            password="Sufficiently-Strong-42!",
        )

        response = self.client.post(reverse("password_reset"), {"email": user.email})
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/accounts/reset/", mail.outbox[0].body)
        reset_link = re.search(r"http://testserver\S+", mail.outbox[0].body).group(0)
        response = self.client.get(urlsplit(reset_link).path, follow=True)
        self.assertContains(response, "Choose a new password")
        confirm_url = response.request["PATH_INFO"]

        response = self.client.post(confirm_url, {
            "new_password1": "An-Even-Stronger-Password-53!",
            "new_password2": "An-Even-Stronger-Password-53!",
        })
        self.assertRedirects(response, reverse("password_reset_complete"))
        user.refresh_from_db()
        self.assertTrue(user.check_password("An-Even-Stronger-Password-53!"))
