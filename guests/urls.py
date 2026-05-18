from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import GuestAuthView, GuestLoginView, GuestMeView, GuestRegisterView

app_name = "guests"

urlpatterns = [
    path("register/", GuestRegisterView.as_view(), name="register"),
    path("login/", GuestLoginView.as_view(), name="login"),
    path("auth/", GuestAuthView.as_view(), name="auth"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("me/", GuestMeView.as_view(), name="me"),
]