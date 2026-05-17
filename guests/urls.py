from django.urls import path

from .views import GuestLoginView, GuestRegisterView, GuestUpdateProfileView

app_name = "guests"

urlpatterns = [
    path("register/", GuestRegisterView.as_view(), name="register"),
    path("login/", GuestLoginView.as_view(), name="login"),
    path("me/", GuestUpdateProfileView.as_view(), name="update-profile"),
]
