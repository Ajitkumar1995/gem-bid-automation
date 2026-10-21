from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password


User = get_user_model()


def username_from_email(email):
    """Use the normalized local part as the workspace username."""
    return email.strip().lower().split("@", 1)[0]


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(label="Email address", widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}))

    def clean(self):
        email = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")
        if email and password:
            self.user_cache = authenticate(
                self.request,
                username=username_from_email(email),
                password=password,
            )
            if self.user_cache is None:
                raise self.get_invalid_login_error()
            self.confirm_login_allowed(self.user_cache)
        return self.cleaned_data


class RegistrationForm(forms.Form):
    email = forms.EmailField(max_length=254, widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    password1 = forms.CharField(label="Password", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="Confirm password", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        username = username_from_email(email)
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email address already exists. Sign in instead.")
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("This email’s username is already in use. Contact support to choose another account email.")
        return email

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "The passwords do not match.")
        if password1:
            candidate = User(username=username_from_email(cleaned.get("email", "user@example.invalid")), email=cleaned.get("email", ""))
            try:
                validate_password(password1, user=candidate)
            except forms.ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned

    def save(self):
        email = self.cleaned_data["email"]
        return User.objects.create_user(
            username=username_from_email(email),
            email=email,
            password=self.cleaned_data["password1"],
        )
