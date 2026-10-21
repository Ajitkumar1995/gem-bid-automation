from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import LoginView, PasswordResetDoneView, PasswordResetView
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .forms import EmailAuthenticationForm, RegistrationForm


class EmailLoginView(LoginView):
    authentication_form = EmailAuthenticationForm
    template_name = "registration/login.html"


class WorkspacePasswordResetView(PasswordResetView):
    """Show local reset links in the browser when no email server is configured."""

    template_name = "registration/password_reset_form.html"

    def form_valid(self, form):
        self.request.session.pop("local_password_reset_link", None)
        if settings.DEBUG:
            email = form.cleaned_data["email"]
            user_model = get_user_model()
            for user in user_model._default_manager.filter(email__iexact=email, is_active=True):
                if user.has_usable_password():
                    uid = urlsafe_base64_encode(force_bytes(user.pk))
                    token = default_token_generator.make_token(user)
                    path = reverse("password_reset_confirm", kwargs={"uidb64": uid, "token": token})
                    self.request.session["local_password_reset_link"] = f"{self.request.scheme}://{self.request.get_host()}{path}"
                    break
        return super().form_valid(form)


class WorkspacePasswordResetDoneView(PasswordResetDoneView):
    template_name = "registration/password_reset_done.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if settings.DEBUG:
            context["local_password_reset_link"] = self.request.session.pop("local_password_reset_link", None)
        return context


def register(request):
    if request.user.is_authenticated:
        return redirect("bid-dashboard")

    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                user = form.save()
        except IntegrityError:
            # A concurrent registration can claim the username after form validation.
            form.add_error("email", "An account with this email username was just created. Please sign in.")
        else:
            login(request, user)
            messages.success(request, "Your account has been created.")
            return redirect("bid-dashboard")

    return render(request, "registration/register.html", {"form": form})
