from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.test import SimpleTestCase

from apps.users.models import CustomUser


class AvatarUrlTest(SimpleTestCase):
    """No Gravatar fallback: it would send an MD5 of the email to a third party."""

    def test_falls_back_to_local_default_avatar(self):
        url = CustomUser(email="test@example.com").avatar_url
        self.assertEqual(url, static("images/default-avatar.svg"))
        self.assertNotIn("gravatar", url)

    def test_default_avatar_is_a_static_file(self):
        self.assertIsNotNone(finders.find("images/default-avatar.svg"))

    def test_uploaded_avatar_is_used(self):
        user = CustomUser(email="test@example.com", avatar="profile-pictures/abc.png")
        self.assertEqual(user.avatar_url, user.avatar.url)
        self.assertTrue(user.avatar_url.endswith("profile-pictures/abc.png"), user.avatar_url)
